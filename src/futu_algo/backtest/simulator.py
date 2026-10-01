"""Bar-by-bar execution simulator.

Timeline and ordering
---------------------
Bars of all symbols are merged on their *close* time (UTC), so HK and US bars interleave
correctly. At each timeline step, for every symbol that has a bar at that step:

1. Pending orders fill at the bar's open (sells before buys, so freed cash can be reused).
2. Resting stop-loss / trailing-stop / take-profit levels are checked against the bar's
   range. If both a stop and a target are inside the range the stop is assumed to hit first.
3. The position is marked at the close and the equity curve is recorded.
4. The strategy's signal at this bar's close decides the next order.

With ``fill: next_open`` (default) an order decided at bar t fills at bar t+1's open; nothing
the strategy saw at t's close can trade at t's close. ``fill: close`` fills at the signal bar's
close, the way TDX's built-in backtest does, and is optimistic.

Fills
-----
Quantities are whole board lots. Buys are sized from the configured sizer, then shrunk lot
by lot until price x quantity + fees fits the budget and cash. Slippage is adverse and
expressed in exchange ticks (HK spread table by date) plus optional basis points; fill
prices are clamped to the bar's high/low.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from futu_algo.backtest.types import Book, Fill, Trade
from futu_algo.config import ExecutionConfig, ExitRules, SizingConfig
from futu_algo.market.costs import CostModel, FeeBreakdown, Side
from futu_algo.market.instrument import Instrument
from futu_algo.market.ticks import tick_size
from futu_algo.strategy.base import BarContext, Strategy

MAX_EVENTS = 500


@dataclass
class SymbolFeed:
    instrument: Instrument
    bars: pd.DataFrame
    indicators: pd.DataFrame
    signal: np.ndarray
    first: int
    last: int
    close_ns: np.ndarray = field(init=False)
    dates: list[date] = field(init=False)
    o: np.ndarray = field(init=False)
    h: np.ndarray = field(init=False)
    lo: np.ndarray = field(init=False)
    c: np.ndarray = field(init=False)
    v: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        index = pd.DatetimeIndex(self.bars.index)
        self.close_ns = bar_close_ns(index, self.instrument)
        self.dates = list(index.date)
        self.o = self.bars["open"].to_numpy(float)
        self.h = self.bars["high"].to_numpy(float)
        self.lo = self.bars["low"].to_numpy(float)
        self.c = self.bars["close"].to_numpy(float)
        self.v = np.nan_to_num(self.bars["volume"].to_numpy(float), nan=0.0)

    @property
    def symbol(self) -> str:
        return self.instrument.symbol


def is_intraday_index(index: pd.DatetimeIndex) -> bool:
    if len(index) == 0:
        return False
    return bool((index.hour != 0).any() or (index.minute != 0).any())


def bar_close_ns(index: pd.DatetimeIndex, instrument: Instrument) -> np.ndarray:
    """UTC nanoseconds at which each bar is complete.

    Intraday bars are end-labelled already. Daily and longer bars are labelled with the date,
    so their close is that date at the market's closing time.
    """
    local = index.tz_convert(instrument.tz)
    if not is_intraday_index(local):
        close = instrument.market.close_time
        local = local.normalize() + pd.Timedelta(hours=close.hour, minutes=close.minute)
    return local.tz_convert("UTC").tz_localize(None).as_unit("ns").to_numpy().astype("int64")


def fit_lots(
    max_lots: int,
    lot: int,
    price: float,
    fees: Callable[[int], FeeBreakdown],
    limit: float,
) -> tuple[int, FeeBreakdown]:
    """Largest quantity of at most ``max_lots`` lots whose cost plus fees fits ``limit``.

    Binary search: fees never decrease with size, so feasibility is monotonic.
    """
    lo, hi = 0, max(int(max_lots), 0)
    best = (0, FeeBreakdown())
    while lo < hi:
        mid = (lo + hi + 1) // 2
        f = fees(mid * lot)
        if mid * lot * price + f.total <= limit + 1e-9:
            lo, best = mid, (mid * lot, f)
        else:
            hi = mid - 1
    return best


@dataclass
class _Position:
    quantity: int = 0
    entry_index: int = -1
    trade: Trade | None = None
    peak: float = 0.0

    @property
    def avg_price(self) -> float:
        assert self.trade is not None
        return self.trade.entry_value / self.trade.quantity


@dataclass
class _Order:
    side: Side
    reason: str
    created_index: int


class Simulator:
    def __init__(
        self,
        feeds: list[SymbolFeed],
        strategy: Strategy,
        costs: CostModel,
        *,
        capital: float,
        execution: ExecutionConfig,
        exits: ExitRules,
        sizing: SizingConfig,
        name: str,
    ) -> None:
        if not feeds:
            raise ValueError("Simulator needs at least one feed")
        self.feeds = feeds
        self.strategy = strategy
        self.costs = costs
        self.capital = capital
        self.ex = execution
        self.risk = exits
        self.pf = sizing
        self.sizer = sizing.method
        self.name = name
        self.cash = capital
        self.positions: dict[str, _Position] = {f.symbol: _Position() for f in feeds}
        self.pending: dict[str, _Order] = {}
        self.blocked: dict[str, bool] = {
            f.symbol: execution.entry_requires_fresh_signal for f in feeds
        }
        self.last_close: dict[str, float] = {f.symbol: math.nan for f in feeds}
        self.fills: list[Fill] = []
        self.trades: list[Trade] = []
        self.events: list[dict[str, Any]] = []
        self.event_counts: dict[str, int] = {}
        self.use_hook = strategy.has_bar_hook

    # ------------------------------------------------------------ helpers

    def _event(self, feed: SymbolFeed, i: int, kind: str, detail: str) -> None:
        self.event_counts[kind] = self.event_counts.get(kind, 0) + 1
        if len(self.events) < MAX_EVENTS:
            self.events.append(
                {
                    "time": feed.bars.index[i].isoformat(),
                    "symbol": feed.symbol,
                    "event": kind,
                    "detail": detail,
                }
            )

    def _slip(self, price: float, feed: SymbolFeed, i: int) -> float:
        slip = 0.0
        if self.ex.slippage_ticks:
            slip += self.ex.slippage_ticks * tick_size(price, feed.instrument, feed.dates[i])
        if self.ex.slippage_bps:
            slip += price * self.ex.slippage_bps / 10_000
        return slip

    def _holdings_value(self) -> float:
        total = 0.0
        for sym, pos in self.positions.items():
            if pos.quantity:
                total += pos.quantity * self.last_close[sym]
        return total

    def equity(self) -> float:
        return self.cash + self._holdings_value()

    def _held_count(self) -> int:
        return sum(1 for p in self.positions.values() if p.quantity > 0)

    def _open_count(self) -> int:
        """Positions that will still be held after pending sells fill."""
        return sum(
            1
            for sym, p in self.positions.items()
            if p.quantity > 0 and not (sym in self.pending and self.pending[sym].side == "SELL")
        )

    def _pending_buys(self) -> int:
        return sum(1 for o in self.pending.values() if o.side == "BUY")

    def _fees(self, side: Side, qty: int, price: float, feed: SymbolFeed, i: int) -> FeeBreakdown:
        return self.costs.fees(side, qty, price, feed.instrument, feed.dates[i])

    # ---------------------------------------------------------------- fills

    def _budget(self) -> float:
        equity = self.equity()
        if self.sizer == "all_in":
            return self.cash
        if self.sizer == "equal_weight":
            return min(self.cash, equity / self.pf.max_positions)
        if self.sizer == "percent_equity":
            assert self.pf.percent is not None
            return min(self.cash, equity * self.pf.percent)
        if self.sizer == "fixed_value":
            assert self.pf.value is not None
            return min(self.cash, self.pf.value)
        return self.cash  # fixed_lots: bounded by cash only

    def _buy(self, feed: SymbolFeed, i: int, base_price: float, reason: str, kind: str) -> None:
        inst = feed.instrument
        lot = inst.lot_size
        price = min(base_price + self._slip(base_price, feed, i), feed.h[i])
        budget = self._budget()
        if self.sizer == "fixed_lots":
            max_lots = self.pf.lots
        else:
            max_lots = int(budget / price // lot) if price > 0 else 0
        if self.ex.max_volume_pct is not None:
            max_lots = min(max_lots, int(feed.v[i] * self.ex.max_volume_pct // lot))
        limit = min(budget, self.cash)
        qty, fees = fit_lots(
            max_lots, lot, price, lambda q: self._fees("BUY", q, price, feed, i), limit
        )
        if qty <= 0:
            need = lot * price + self._fees("BUY", lot, price, feed, i).total
            self._event(feed, i, "buy_skipped", f"budget {limit:,.2f} < one lot {need:,.2f}")
            return
        fill = Fill(feed.symbol, feed.bars.index[i], "BUY", qty, price, fees, reason, i)
        self.cash += fill.cash_delta
        pos = self.positions[feed.symbol]
        if pos.quantity == 0:
            pos.entry_index = i
            pos.trade = Trade(
                symbol=feed.symbol,
                entry_time=feed.bars.index[i],
                entry_index=i,
                quantity=0,
                entry_value=0.0,
                entry_fees=0.0,
                entry_fill=kind,
            )
            pos.peak = price
        assert pos.trade is not None
        pos.quantity += qty
        pos.trade.quantity += qty
        pos.trade.entry_value += fill.value
        pos.trade.entry_fees += fees.total
        self.fills.append(fill)

    def _sell(self, feed: SymbolFeed, i: int, price: float, reason: str, kind: str) -> None:
        pos = self.positions[feed.symbol]
        qty = pos.quantity
        if qty <= 0:
            return
        price = max(price, feed.lo[i])
        if self.ex.max_volume_pct is not None and reason == "signal":
            lot = feed.instrument.lot_size
            cap = int(feed.v[i] * self.ex.max_volume_pct // lot) * lot
            qty = min(qty, max(cap, 0))
            if qty <= 0:
                self._event(feed, i, "sell_deferred", "volume cap below one lot")
                self.pending[feed.symbol] = _Order("SELL", reason, i)
                return
        fees = self._fees("SELL", qty, price, feed, i)
        if qty < pos.quantity and qty * price <= fees.total:
            # A volume-capped slice that would not even cover its fixed fees: wait for volume.
            self._event(feed, i, "sell_deferred", "capped slice proceeds below fees")
            self.pending[feed.symbol] = _Order("SELL", reason, i)
            return
        fill = Fill(feed.symbol, feed.bars.index[i], "SELL", qty, price, fees, reason, i)
        self.cash += fill.cash_delta
        self.fills.append(fill)
        assert pos.trade is not None
        pos.trade.exit_value += fill.value
        pos.trade.exit_fees += fees.total
        pos.quantity -= qty
        if pos.quantity == 0:
            trade = pos.trade
            trade.exit_time = feed.bars.index[i]
            trade.exit_index = i
            trade.exit_reason = reason
            trade.exit_fill = kind
            self._excursions(feed, trade)
            self.trades.append(trade)
            pos.trade = None
            pos.entry_index = -1
        elif reason == "signal":
            # Partially filled under a volume cap: keep selling on following bars.
            self.pending[feed.symbol] = _Order("SELL", reason, i)

    @staticmethod
    def _excursions(feed: SymbolFeed, trade: Trade) -> None:
        """Worst and best price relative to the entry, over the bars actually held.

        A bar entered at its close, or exited at its open or intrabar, contributes only its
        fill price, because the rest of its range happened outside the holding period.
        """
        start = trade.entry_index + (1 if trade.entry_fill == "close" else 0)
        if trade.is_open or trade.exit_index is None:
            end = feed.last
        else:
            end = trade.exit_index - (0 if trade.exit_fill in ("close", "end") else 1)
        entry = trade.entry_price
        points_lo = [entry]
        points_hi = [entry]
        exit_price = trade.exit_price
        if exit_price is not None:
            points_lo.append(exit_price)
            points_hi.append(exit_price)
        if start <= end:
            points_lo.append(float(feed.lo[start : end + 1].min()))
            points_hi.append(float(feed.h[start : end + 1].max()))
        trade.mae_pct = float(min(points_lo) / entry - 1)
        trade.mfe_pct = float(max(points_hi) / entry - 1)

    # ----------------------------------------------------------------- risk

    def _risk_exit(self, feed: SymbolFeed, i: int) -> None:
        r = self.risk
        pos = self.positions[feed.symbol]
        if pos.quantity <= 0 or not (r.stop_loss or r.trailing_stop or r.take_profit):
            return
        entry = pos.avg_price
        stop, stop_reason = None, ""
        if r.stop_loss:
            stop, stop_reason = entry * (1 - r.stop_loss), "stop_loss"
        if r.trailing_stop:
            trail = pos.peak * (1 - r.trailing_stop)
            if stop is None or trail > stop:
                stop, stop_reason = trail, "trailing_stop"
        target = entry * (1 + r.take_profit) if r.take_profit else None
        o, h, lo = feed.o[i], feed.h[i], feed.lo[i]
        price: float | None = None
        reason = ""
        # The open trades first, so gaps through either level fill at the open. Inside the bar
        # the path is unknown; if both levels are in range the stop is assumed to hit first.
        kind = "intrabar"
        if stop is not None and o <= stop:
            price, reason, kind = o - self._slip(o, feed, i), stop_reason, "open"
        elif target is not None and o >= target:
            price, reason, kind = o, "take_profit", "open"
        elif stop is not None and lo <= stop:
            price, reason = stop - self._slip(stop, feed, i), stop_reason
        elif target is not None and h >= target:
            price, reason = target, "take_profit"
        if price is None:
            return
        self.pending.pop(feed.symbol, None)
        self._sell(feed, i, price, reason, kind)
        self.blocked[feed.symbol] = self.ex.entry_requires_fresh_signal

    # ------------------------------------------------------------- decisions

    def _decide(self, feed: SymbolFeed, i: int) -> None:
        sym = feed.symbol
        pos = self.positions[sym]
        sig = float(feed.signal[i])
        if self.use_hook:
            ctx = BarContext(
                symbol=sym,
                index=i,
                time=feed.bars.index[i],
                open=feed.o[i],
                high=feed.h[i],
                low=feed.lo[i],
                close=feed.c[i],
                volume=feed.v[i],
                signal=sig,
                position=pos.quantity,
                entry_price=pos.avg_price if pos.quantity else None,
                bars_held=self._bars_held(pos, i),
                indicators=feed.indicators.iloc[: i + 1],
                bars=feed.bars.iloc[: i + 1],
            )
            out = self.strategy.on_bar(ctx)
            sig = math.nan if out is None else float(out)
        if self.blocked[sym] and sig != 1.0:
            self.blocked[sym] = False
        if sym in self.pending:
            return
        at_close = self.ex.fill == "close"
        if pos.quantity > 0:
            reason = None
            if sig == 0.0:
                reason = "signal"
            elif (
                self.risk.max_holding_bars and self._bars_held(pos, i) >= self.risk.max_holding_bars
            ):
                reason = "max_hold"
            if reason is None:
                return
            if at_close:
                self._sell(feed, i, feed.c[i] - self._slip(feed.c[i], feed, i), reason, "close")
            else:
                self.pending[sym] = _Order("SELL", reason, i)
            if reason == "max_hold":
                self.blocked[sym] = self.ex.entry_requires_fresh_signal
            return
        if sig != 1.0 or self.blocked[sym]:
            return
        if not at_close and i >= feed.last:
            return
        if self._open_count() + self._pending_buys() >= self.pf.max_positions:
            self._event(feed, i, "buy_skipped", f"max_positions={self.pf.max_positions} reached")
            return
        if at_close:
            self._buy(feed, i, feed.c[i], "signal", "close")
        else:
            self.pending[sym] = _Order("BUY", "signal", i)

    @staticmethod
    def _bars_held(pos: _Position, i: int) -> int:
        """Bars held through bar i's close; a bar entered at its open counts as held."""
        if pos.quantity <= 0 or pos.trade is None:
            return 0
        return i - pos.entry_index + (1 if pos.trade.entry_fill == "open" else 0)

    # ------------------------------------------------------------------ run

    def run(self) -> Book:
        feeds = self.feeds
        times = np.unique(np.concatenate([f.close_ns[f.first : f.last + 1] for f in feeds]))
        ptr = [f.first for f in feeds]
        equity = np.empty(len(times))
        cash = np.empty(len(times))
        exposure = np.empty(len(times))

        for step, t in enumerate(times):
            active: list[tuple[SymbolFeed, int]] = []
            for k, f in enumerate(feeds):
                i = ptr[k]
                if i <= f.last and f.close_ns[i] == t:
                    active.append((f, i))
                    ptr[k] = i + 1
            for f, i in active:
                order = self.pending.get(f.symbol)
                if order is not None and order.side == "SELL":
                    del self.pending[f.symbol]
                    self._sell(f, i, f.o[i] - self._slip(f.o[i], f, i), order.reason, "open")
            for f, i in active:
                order = self.pending.get(f.symbol)
                if order is not None and order.side == "BUY":
                    del self.pending[f.symbol]
                    if self._held_count() >= self.pf.max_positions:
                        # A sell counted on at decision time did not fill (e.g. no bar yet).
                        self._event(f, i, "buy_skipped", "max_positions still full at the open")
                        continue
                    self._buy(f, i, f.o[i], order.reason, "open")
            for f, i in active:
                self._risk_exit(f, i)
            for f, i in active:
                self.last_close[f.symbol] = f.c[i]
                pos = self.positions[f.symbol]
                if pos.quantity:
                    pos.peak = max(pos.peak, f.h[i])
            for f, i in active:
                self._decide(f, i)
            holdings = self._holdings_value()
            equity[step] = self.cash + holdings
            cash[step] = self.cash
            exposure[step] = holdings / equity[step] if equity[step] > 0 else 0.0

        for f in feeds:
            order = self.pending.pop(f.symbol, None)
            if order is not None:
                self._event(f, f.last, "order_expired", f"{order.side} after last bar")
        if self.ex.liquidate_at_end:
            for f in feeds:
                if self.positions[f.symbol].quantity:
                    self._sell(
                        f, f.last, f.c[f.last] - self._slip(f.c[f.last], f, f.last), "end", "end"
                    )
            if len(times):
                equity[-1] = self.cash + self._holdings_value()
                cash[-1] = self.cash
                exposure[-1] = 0.0 if equity[-1] <= 0 else self._holdings_value() / equity[-1]
        for f in feeds:
            pos = self.positions[f.symbol]
            if pos.quantity and pos.trade is not None:
                trade = pos.trade
                trade.is_open = True
                trade.mark_price = f.c[f.last]
                trade.open_quantity = pos.quantity
                self._excursions(f, trade)
                self.trades.append(trade)

        index = display_index(times, feeds)
        self.trades.sort(key=lambda tr: tr.entry_time)
        return Book(
            name=self.name,
            currency=feeds[0].instrument.currency,
            initial_capital=self.capital,
            equity=pd.Series(equity, index=index, name="equity"),
            cash=pd.Series(cash, index=index, name="cash"),
            exposure=pd.Series(exposure, index=index, name="exposure"),
            fills=self.fills,
            trades=self.trades,
            events=self.events,
            event_counts=self.event_counts,
            symbols=[f.symbol for f in feeds],
        )


def display_index(times_ns: np.ndarray, feeds: list[SymbolFeed]) -> pd.DatetimeIndex:
    """Timeline as bar labels: local dates for daily+ bars, local end times for intraday."""
    tzs = {f.instrument.tz for f in feeds}
    tz = tzs.pop() if len(tzs) == 1 else "UTC"
    idx = pd.DatetimeIndex(pd.to_datetime(times_ns, utc=True)).tz_convert(tz)
    if tz != "UTC" and not any(is_intraday_index(pd.DatetimeIndex(f.bars.index)) for f in feeds):
        idx = idx.normalize()
    return pd.DatetimeIndex(idx, name="time")


def buy_and_hold(
    feeds: list[SymbolFeed],
    costs: CostModel,
    capital: float,
    execution: ExecutionConfig,
    index: pd.DatetimeIndex,
) -> pd.Series:
    """Equal-weight buy-and-hold of ``feeds``, bought at each first tradable bar's open."""
    sleeve = capital / len(feeds)
    total = pd.Series(0.0, index=index)
    for f in feeds:
        i = f.first
        lot = f.instrument.lot_size
        tick = tick_size(f.o[i], f.instrument, f.dates[i]) * execution.slippage_ticks
        price = min(f.o[i] + tick + f.o[i] * execution.slippage_bps / 10_000, f.h[i])
        inst, day = f.instrument, f.dates[i]

        def buy_fees(
            q: int, inst: Instrument = inst, day: date = day, px: float = price
        ) -> FeeBreakdown:
            return costs.fees("BUY", q, px, inst, day)

        qty, fb = fit_lots(int(sleeve / price // lot), lot, price, buy_fees, sleeve)
        left = sleeve - (qty * price + fb.total if qty > 0 else 0.0)
        closes = pd.Series(
            f.c[f.first : f.last + 1], index=display_index(f.close_ns[f.first : f.last + 1], [f])
        )
        closes = closes[~closes.index.duplicated(keep="last")]
        value = (left + qty * closes).reindex(index).ffill().fillna(sleeve)
        total = total + value
    return total
