"""The live trading engine.

Decisions follow the backtester bar for bar:

1. On every *completed* bar the symbol's strategy runs on the rolling window and
   ``decide_last`` returns 1 (be long), 0 (be flat) or NaN (no opinion) — the same value the
   backtest computed for that bar.
2. The same entry rules apply: a symbol that is mid-signal when the engine starts (or after a
   stop-out) waits for the signal to reset (``entry_requires_fresh_signal``); ``max_positions``
   counts held symbols plus working buys.
3. The decision becomes an *intent*; the :class:`OrderExecutor` turns it into orders right
   away, which is the live equivalent of the backtester's next-open fill.

The engine core is synchronous (``on_bar``, ``sync``) so replays and tests drive it
deterministically; :meth:`start` wraps it in a worker thread fed by Futu pushes and a timer.
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd

from futu_algo.config import AppConfig
from futu_algo.data.manager import DataManager
from futu_algo.data.resample import resample_bars, session_labels
from futu_algo.data.schema import BAR_COLUMNS
from futu_algo.events import (
    ACCOUNT,
    BAR,
    ENGINE,
    ERROR,
    RISK,
    SIGNAL,
    SUMMARY,
    Event,
    EventBus,
    Level,
)
from futu_algo.live.broker import Broker, QuoteProvider
from futu_algo.live.executor import OrderExecutor
from futu_algo.live.feed import Bar, FutuBarFeed, split_in_progress
from futu_algo.live.models import AccountSnapshot, PositionInfo, Quote
from futu_algo.live.risk import RiskContext, RiskManager
from futu_algo.live.store import StateStore
from futu_algo.market.calendar import Phase, TradingCalendar
from futu_algo.market.instrument import MARKETS, Instrument
from futu_algo.strategy.base import Strategy
from futu_algo.strategy.registry import create_strategy
from futu_algo.timeframe import Timeframe

log = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Decision:
    symbol: str
    bar_time: pd.Timestamp
    signal: float
    action: str  # hold | buy | sell | skip | cancel | warmup | error
    detail: str = ""


class LiveEngine:
    def __init__(
        self,
        cfg: AppConfig,
        *,
        broker: Broker,
        quotes: QuoteProvider,
        store: StateStore,
        bus: EventBus,
        instruments: dict[str, Instrument],
        data: DataManager | None = None,
        feed_factory: Callable[[Callable[[Bar], None]], FutuBarFeed] | None = None,
        calendar: TradingCalendar | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.cfg = cfg
        self.tc = cfg.trading
        self.tf = Timeframe.parse(self.tc.timeframe)
        self.market = MARKETS[self.tc.market]
        self.broker = broker
        self.quotes = quotes
        self.store = store
        self.bus = bus
        self.instruments = instruments
        self.data = data
        self.clock = clock
        self.calendar = calendar or TradingCalendar(self.market)
        self.risk = RiskManager(self.tc.risk, self.market)
        self.env = "DRY_RUN" if self.tc.mode == "dry_run" else self.tc.env

        self.symbols = [s for s in self.tc.symbols if s in instruments]
        self.strategies: dict[str, Strategy] = {}
        for sym in self.symbols:
            spec = self.tc.strategy_for(sym)
            self.strategies[sym] = create_strategy(spec.name, spec.params)
        self.windows: dict[str, pd.DataFrame] = {}
        self.max_window = min(
            max([3 * s.warmup_bars() for s in self.strategies.values()] + [300]), 5000
        )

        self.account: AccountSnapshot | None = None
        self.positions: dict[str, PositionInfo] = {}
        self.last_bar: dict[str, Bar] = {}
        self.last_decision: dict[str, Decision] = {}
        self._last_prices: dict[str, float] = {}

        # Persistent state.
        fresh = self.tc.entry_requires_fresh_signal
        saved_blocked: dict[str, bool] = store.get("blocked", {})
        self.blocked = {s: bool(saved_blocked.get(s, fresh)) for s in self.symbols}
        self.bars_held: dict[str, int] = store.get("bars_held", {})
        self.peak: dict[str, float] = store.get("peak", {})
        self.halted: bool = bool(store.get("halted", False))
        self.halt_reason: str = store.get("halt_reason", "")
        self.trading_day: str | None = store.get("trading_day")
        self.day_start_equity: float | None = store.get("day_start_equity")
        self.flattened_day: str | None = store.get("flattened_day")

        self.executor = OrderExecutor(
            broker, quotes, store, bus, self.risk, self.tc.order,
            self.instrument, self._risk_context, env=self.env,
        )
        self._feed_factory = feed_factory
        self.feed: FutuBarFeed | None = None
        self._queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._sync_now = threading.Event()
        self.state = "stopped"
        self.started_at: datetime | None = None
        self.last_error: str = ""
        self._last_sync = 0.0
        self._last_equity = 0.0
        self._last_poll = 0.0
        self._lock = threading.RLock()
        broker.set_order_listener(self._sync_now.set)

    # ================================================================== helpers

    def instrument(self, symbol: str) -> Instrument:
        inst = self.instruments.get(symbol)
        if inst is None:
            raise KeyError(f"Unknown instrument {symbol}")
        return inst

    def phase(self, now: datetime | None = None) -> Phase:
        return self.calendar.phase(now or self.clock())

    def _persist(self) -> None:
        snapshot = (dict(self.blocked), dict(self.bars_held), dict(self.peak))
        if snapshot == getattr(self, "_persisted", None):
            return
        self._persisted = snapshot
        self.store.set("blocked", self.blocked)
        self.store.set("bars_held", self.bars_held)
        self.store.set("peak", self.peak)

    def _risk_context(self, symbol: str, quote: Quote | None) -> RiskContext:
        now = self.clock()
        account = self.account or self.broker.account()
        prices = {**self._last_prices, **({symbol: quote.last} if quote and quote.last else {})}
        return RiskContext(
            now=now,
            phase=self.phase(now),
            account=account,
            positions=self.positions,
            working_buy_value=self.executor.working_buy_value(prices),
            quote=quote,
            orders_today=self._orders_today(now),
            day_start_equity=self.day_start_equity,
            halted=self.halted,
            halt_reason=self.halt_reason,
        )

    def _local_midnight_utc(self, now: datetime) -> str:
        local = pd.Timestamp(now).tz_convert(self.market.tz).normalize()
        return local.tz_convert("UTC").isoformat()

    def _orders_today(self, now: datetime) -> int:
        return self.store.count_orders_since(self._local_midnight_utc(now))

    # ================================================================= warm-up

    def warmup(self, symbol: str, bars: pd.DataFrame) -> None:
        """Seed the rolling window with completed bars at the trading timeframe."""
        bars = bars.loc[:, list(BAR_COLUMNS)].sort_index()
        bars = bars[~bars.index.duplicated(keep="last")]
        self.windows[symbol] = bars.iloc[-self.max_window :]
        if len(bars):
            last = bars.iloc[-1]
            self.last_bar[symbol] = Bar(symbol, pd.Timestamp(bars.index[-1]), *(float(last[c]) for c in BAR_COLUMNS))
            self._last_prices[symbol] = float(last["close"])

    def _to_target(self, symbol: str, base_bars: pd.DataFrame, now: datetime) -> tuple[pd.DataFrame, list[Bar]]:
        """Completed target-timeframe bars from completed base bars, plus the base bars of a
        target bar that is still open (they seed the live assembler)."""
        if self.tf.is_native or base_bars.empty:
            return base_bars, []
        resampled = resample_bars(base_bars, self.tf.base, self.tf, self.market)
        stamp = pd.Timestamp(now).tz_convert(self.market.tz)
        if not len(resampled) or resampled.index[-1] + pd.Timedelta(seconds=self.tc.bar_grace_seconds) <= stamp:
            return resampled, []
        label = resampled.index[-1]
        labels = session_labels(pd.DatetimeIndex(base_bars.index), self.tf.minutes, self.market)
        part = base_bars[labels == label]
        open_chunk = [
            Bar(symbol, t, *(float(r[c]) for c in BAR_COLUMNS))
            for t, r in zip(pd.DatetimeIndex(part.index), part.to_dict("records"), strict=True)
        ]
        return resampled.iloc[:-1], open_chunk

    def _load_warmup(self, symbol: str) -> None:
        strategy = self.strategies[symbol]
        need = strategy.warmup_bars() + 2
        now = self.clock()
        base = self.tf.base
        live_base = pd.DataFrame(columns=list(BAR_COLUMNS))
        in_progress = pd.DataFrame(columns=list(BAR_COLUMNS))
        if self.feed is not None:
            try:
                frame = self.feed.recent_bars(symbol, 1000)
                live_base, in_progress = split_in_progress(frame, base, self.market, now, self.tc.bar_grace_seconds)
            except Exception as exc:
                log.warning("get_cur_kline %s failed: %s", symbol, exc)
        completed, open_chunk = self._to_target(symbol, live_base, now)
        if self.tc.warmup_from_cache and self.data is not None and len(completed) < need:
            try:
                yesterday = pd.Timestamp(now).tz_convert(self.market.tz).date() - timedelta(days=1)
                cached = self.data.load_bars(symbol, self.tf, yesterday, yesterday, warmup_bars=need)
                if len(completed):
                    cached = cached[cached.index < completed.index[0]]
                completed = pd.concat([cached, completed]) if len(completed) else cached
            except Exception as exc:
                log.warning("Warm-up from cache failed for %s: %s", symbol, exc)
        self.warmup(symbol, completed)
        if self.feed is not None:
            self.feed.assembler.prime(symbol, live_base.index[-1] if len(live_base) else None)
            if open_chunk:
                self.feed.assembler.seed(symbol, open_chunk)
            for t, row in zip(pd.DatetimeIndex(in_progress.index), in_progress.to_dict("records"), strict=True):
                self.feed.assembler.update(Bar(symbol, t, *(float(row[c]) for c in BAR_COLUMNS)))
        n = len(self.windows.get(symbol, []))
        if n < need:
            self.bus.emit(
                ENGINE, f"{symbol}: {n} warm-up bars, strategy needs {need}; decisions start once enough bars arrive",
                level="warning", symbol=symbol,
            )

    # =============================================================== decisions

    def _append(self, bar: Bar) -> pd.DataFrame:
        row = pd.DataFrame([bar.as_row()], index=pd.DatetimeIndex([bar.time], name="time"))
        win = self.windows.get(bar.symbol)
        if win is None or win.empty:
            win = row
        elif bar.time <= win.index[-1]:
            win = pd.concat([win[win.index < bar.time], row])
        else:
            win = pd.concat([win, row])
        win = win.iloc[-self.max_window :]
        self.windows[bar.symbol] = win
        self.last_bar[bar.symbol] = bar
        self._last_prices[bar.symbol] = bar.close
        return win

    def _exit_reason(self, symbol: str, pos: PositionInfo, bar: Bar) -> str | None:
        ex = self.tc.exits
        entry = pos.cost_price
        if entry > 0:
            if ex.stop_loss and bar.low <= entry * (1 - ex.stop_loss):
                return "stop_loss"
            if ex.trailing_stop:
                peak = self.peak.get(symbol, entry)
                if bar.low <= peak * (1 - ex.trailing_stop):
                    return "trailing_stop"
            if ex.take_profit and bar.high >= entry * (1 + ex.take_profit):
                return "take_profit"
        if ex.max_holding_bars and self.bars_held.get(symbol, 0) >= ex.max_holding_bars:
            return "max_hold"
        return None

    def _size(self, symbol: str, price: float) -> int:
        inst = self.instrument(symbol)
        lot = inst.lot_size
        s = self.tc.sizing
        if s.method == "fixed_lots":
            return s.lots * lot
        account = self.account
        if account is None or price <= 0:
            return 0
        equity = account.equity if self.tc.capital is None else min(account.equity, self.tc.capital)
        budget = {
            "equal_weight": equity / s.max_positions,
            "fixed_value": s.value or 0.0,
            "percent_equity": equity * (s.percent or 0.0),
            "all_in": account.buying_power,
        }[s.method]
        budget = min(budget, account.buying_power)
        if self.tc.risk.max_position_value:
            budget = min(budget, self.tc.risk.max_position_value)
        # Leave room for fees (HK round-trip costs are well under 0.5%).
        lots = math.floor(budget / (price * 1.005) / lot)
        return max(lots, 0) * lot

    def _open_slots(self) -> int:
        held = {
            s for s, p in self.positions.items()
            if p.quantity > 0 and self.executor.working_side(s, "SELL") == 0
        }
        buying = {i.symbol for i in self.executor.working() if i.side == "BUY"}
        return self.tc.sizing.max_positions - len(held | buying)

    def on_bar(self, bar: Bar) -> Decision | None:
        """Handle one completed bar at the trading timeframe."""
        sym = bar.symbol
        strategy = self.strategies.get(sym)
        if strategy is None:
            return None
        with self._lock:
            window = self._append(bar)
            self.bus.emit(BAR, f"{sym} {bar.time:%H:%M} close {bar.close:g}", level="debug", symbol=sym,
                          time=bar.time.isoformat(), open=bar.open, high=bar.high, low=bar.low, close=bar.close, volume=bar.volume)
            need = strategy.warmup_bars()
            if len(window) <= need:
                d = Decision(sym, bar.time, math.nan, "warmup", f"{len(window)}/{need + 1} bars")
                self.last_decision[sym] = d
                return d
            try:
                sig = strategy.decide_last(window)
            except Exception as exc:
                log.exception("Strategy %s failed on %s", strategy.name, sym)
                self.bus.emit(ERROR, f"{strategy.name} failed on {sym}: {exc}", level="error", symbol=sym)
                d = Decision(sym, bar.time, math.nan, "error", str(exc))
                self.last_decision[sym] = d
                return d
            d = self._decide(sym, bar, sig)
            self.last_decision[sym] = d
            self.store.add_signal(sym, bar.time.to_pydatetime(), strategy.name, sig, bar.close, d.action, {"detail": d.detail})
            if d.action not in ("hold", "warmup"):
                level: Level = "warning" if d.action == "skip" else "info"
                self.bus.emit(SIGNAL, f"{sym} {d.action.upper()} ({strategy.name}, signal={_fmt_sig(sig)}) {d.detail}".strip(),
                              level=level, symbol=sym, action=d.action, signal=None if math.isnan(sig) else sig, bar_time=bar.time.isoformat())
            self._persist()
            return d

    def _decide(self, sym: str, bar: Bar, sig: float) -> Decision:
        pos = self.positions.get(sym)
        qty = pos.quantity if pos else 0
        working_buy = self.executor.working_side(sym, "BUY")
        working_sell = self.executor.working_side(sym, "SELL")
        fresh = self.tc.entry_requires_fresh_signal
        if qty > 0:
            self.bars_held[sym] = self.bars_held.get(sym, 0) + 1
            self.peak[sym] = max(self.peak.get(sym, bar.high), bar.high)
        else:
            self.bars_held.pop(sym, None)
            self.peak.pop(sym, None)
        if self.blocked.get(sym) and sig != 1.0:
            self.blocked[sym] = False

        if qty > 0:
            if working_sell:
                return Decision(sym, bar.time, sig, "hold", "sell in progress")
            reason = self._exit_reason(sym, pos, bar) if pos else None
            if reason is None and sig == 0.0:
                reason = "signal"
            if reason is None:
                return Decision(sym, bar.time, sig, "hold")
            self.executor.submit(sym, "SELL", qty, reason, bar.time.to_pydatetime())
            if reason != "signal":
                self.blocked[sym] = fresh
            return Decision(sym, bar.time, sig, "sell", reason)

        if working_buy:
            if sig == 0.0:
                for intent in self.executor.working(sym):
                    self.executor.abandon(intent.id, "sell signal before the buy filled")
                return Decision(sym, bar.time, sig, "cancel", "buy not filled before sell signal")
            return Decision(sym, bar.time, sig, "hold", "buy in progress")

        if sig != 1.0 or self.blocked.get(sym):
            detail = "waiting for a fresh signal" if sig == 1.0 else ""
            return Decision(sym, bar.time, sig, "hold", detail)
        if self.halted:
            return Decision(sym, bar.time, sig, "skip", f"entries halted: {self.halt_reason}")
        if self._open_slots() <= 0:
            return Decision(sym, bar.time, sig, "skip", f"max_positions={self.tc.sizing.max_positions} reached")
        size = self._size(sym, bar.close)
        if size <= 0:
            return Decision(sym, bar.time, sig, "skip", "budget below one board lot")
        self.executor.submit(sym, "BUY", size, "signal", bar.time.to_pydatetime())
        return Decision(sym, bar.time, sig, "buy", f"{size} shares")

    # ==================================================================== sync

    def refresh_account(self) -> None:
        self.account = self.broker.account()
        self.positions = self.broker.positions()
        for sym, p in self.positions.items():
            if p.last_price:
                self._last_prices[sym] = p.last_price

    def sync(self, now: datetime | None = None) -> None:
        """Poll the broker, advance orders, apply day rollover, loss limits and flattening."""
        now = now or self.clock()
        with self._lock:
            self.executor.sync(now)
            self.refresh_account()
            self._rollover(now)
            self._check_loss(now)
            self._maybe_flatten(now)
            if self.executor.intents:
                # Orders may have been sent after the positions were read.
                self.executor.sync(now)
            trading_hours = self.phase(now) not in (Phase.CLOSED, Phase.AFTER_HOURS)
            minute = now.timestamp() // 60  # engine clock, so replays and demo mode record too
            if trading_hours and minute != self._last_equity and self.account is not None:
                self._last_equity = minute
                a = self.account
                self.store.add_equity(now, a.equity, a.cash, a.market_value, self.env)

    def _rollover(self, now: datetime) -> None:
        local_day = pd.Timestamp(now).tz_convert(self.market.tz).date().isoformat()
        if local_day == self.trading_day or self.account is None:
            return
        self.trading_day = local_day
        self.day_start_equity = self.account.equity
        self.store.set("trading_day", local_day)
        self.store.set("day_start_equity", self.day_start_equity)
        if self.halted and self.halt_reason.startswith("daily loss"):
            self.resume("new trading day")
        self.bus.emit(ACCOUNT, f"New trading day {local_day}; starting equity {self.account.equity:,.2f}", equity=self.account.equity)

    def _check_loss(self, now: datetime) -> None:
        if self.halted or self.account is None:
            return
        breach = self.risk.daily_loss_breached(self.account, self.day_start_equity)
        if breach:
            self.halt(breach)

    def _maybe_flatten(self, now: datetime) -> None:
        if not self.risk.should_flatten(now) or self.phase(now) != Phase.CONTINUOUS:
            return
        if self.flattened_day == self.trading_day:
            return
        self.flattened_day = self.trading_day
        self.store.set("flattened_day", self.flattened_day)
        n = self.flatten(None, reason="flatten before close")
        self.bus.emit(RISK, f"Flattening {n} position(s) before the close", level="warning")

    # ================================================================ commands

    def halt(self, reason: str = "manual") -> None:
        with self._lock:
            self.halted, self.halt_reason = True, reason
            self.store.set("halted", True)
            self.store.set("halt_reason", reason)
            for intent in [i for i in self.executor.working() if i.side == "BUY"]:
                self.executor.abandon(intent.id, f"halted: {reason}")
        self.bus.emit(RISK, f"New entries halted: {reason}", level="warning")

    def resume(self, reason: str = "manual") -> None:
        with self._lock:
            self.halted, self.halt_reason = False, ""
            self.store.set("halted", False)
            self.store.set("halt_reason", "")
        self.bus.emit(RISK, f"Entries resumed ({reason})")

    def flatten(self, symbol: str | None = None, reason: str = "manual flatten") -> int:
        with self._lock:
            if self.account is None:
                self.refresh_account()
            n = 0
            for sym, pos in list(self.positions.items()):
                if symbol and sym != symbol:
                    continue
                if pos.quantity <= 0:
                    continue
                self.executor.submit(sym, "SELL", pos.quantity, reason)
                self.blocked[sym] = self.tc.entry_requires_fresh_signal
                n += 1
            self._persist()
        self._sync_now.set()
        return n

    def cancel_all(self) -> int:
        with self._lock:
            return self.executor.cancel_all("cancelled from console")

    def daily_summary(self) -> dict[str, Any]:
        now = self.clock()
        if self.account is None:
            self.refresh_account()
        assert self.account is not None
        since = self._local_midnight_utc(now)
        fills = self.store.fills(limit=1000, since_iso=since)
        pnl = self.account.equity - (self.day_start_equity or self.account.equity)
        summary = {
            "day": self.trading_day,
            "equity": self.account.equity,
            "pnl": pnl,
            "pnl_pct": pnl / self.day_start_equity if self.day_start_equity else 0.0,
            "fills": len(fills),
            "positions": [p.to_dict() for p in self.positions.values()],
            "env": self.env,
        }
        self.bus.publish(Event(
            SUMMARY,
            f"{self.trading_day} ({self.env}): equity {self.account.equity:,.2f}, P/L {pnl:+,.2f}, "
            f"{len(fills)} fill(s), {len(self.positions)} position(s)",
            data=summary,
            time=now,
        ))
        return summary

    # ================================================================ runtime

    def replay_step(self, bar: Bar, now: datetime | None = None) -> Decision | None:
        """Deterministic step for replays and tests: sync, decide, send orders."""
        now = now or self.clock()
        self.sync(now)
        decision = self.on_bar(bar)
        self.executor.sync(now)
        return decision

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self.state = "starting"
        self._stop.clear()
        self.bus.emit(ENGINE, f"Engine starting ({self.env}, {self.tf}, {len(self.symbols)} symbols)")
        try:
            self.broker.connect()
            self.refresh_account()
            if self._feed_factory is not None:
                self.feed = self._feed_factory(self._enqueue_bar)
                # Futu serves get_cur_kline only for subscribed symbols, so subscribe first;
                # bars pushed meanwhile queue up until the worker thread starts.
                self.feed.subscribe(self.symbols)
            for sym in self.symbols:
                self._load_warmup(sym)
        except Exception as exc:
            self.state = "error"
            self.last_error = str(exc)
            self.bus.emit(ERROR, f"Engine failed to start: {exc}", level="error")
            raise
        self.started_at = self.clock()
        self._thread = threading.Thread(target=self._run, name="futu-algo-engine", daemon=True)
        self._thread.start()
        self.state = "running"
        self.bus.emit(ENGINE, f"Engine running: {', '.join(self.symbols)}")

    def stop(self, timeout: float = 10.0) -> None:
        if self._thread is None:
            self.state = "stopped"
            return
        self.state = "stopping"
        self._stop.set()
        self._thread.join(timeout)
        self._thread = None
        if self.feed is not None:
            self.feed.unsubscribe()
        self.state = "stopped"
        self.bus.emit(ENGINE, "Engine stopped")

    def _enqueue_bar(self, bar: Bar) -> None:
        self._queue.put(("bar", bar))

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:
                self.last_error = str(exc)
                log.exception("Engine loop error")
                self.bus.emit(ERROR, f"Engine loop error: {exc}", level="error")
                time.sleep(2)

    def _tick(self) -> None:
        try:
            first = self._queue.get(timeout=0.5)
        except queue.Empty:
            first = None
        now = self.clock()
        if self.feed is not None:
            self.feed.tick(now)
            if time.monotonic() - self._last_poll >= 30:
                self._last_poll = time.monotonic()
                self.feed.poll()
        items = [first] if first else []
        while True:
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                break
        bars = [payload for kind, payload in items if kind == "bar"]
        due = time.monotonic() - self._last_sync >= self.tc.poll_seconds
        if bars or due or self._sync_now.is_set():
            self._sync_now.clear()
            self._last_sync = time.monotonic()
            self.sync(now)
        if bars:
            for bar in sorted(bars, key=lambda b: (b.time, b.symbol)):
                self.on_bar(bar)
            self.executor.sync(now)

    # ================================================================== views

    def status(self) -> dict[str, Any]:
        now = self.clock()
        acct = self.account
        return {
            "state": self.state,
            "env": self.env,
            "mode": self.tc.mode,
            "timeframe": str(self.tf),
            "phase": str(self.phase(now)),
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_error": self.last_error,
            "trading_day": self.trading_day,
            "day_start_equity": self.day_start_equity,
            "account": acct.to_dict() if acct else None,
            "day_pnl": (acct.equity - self.day_start_equity) if acct and self.day_start_equity else None,
            "symbols": [
                {
                    "symbol": s,
                    "name": self.instruments[s].name,
                    "lot_size": self.instruments[s].lot_size,
                    "strategy": self.strategies[s].name,
                    "params": self.strategies[s].params.model_dump(),
                    "bars": len(self.windows.get(s, [])),
                    "warmup": self.strategies[s].warmup_bars(),
                    "last_bar": _bar_dict(self.last_bar.get(s)),
                    "last_decision": _decision_dict(self.last_decision.get(s)),
                    "blocked": self.blocked.get(s, False),
                    "position": self.positions[s].quantity if s in self.positions else 0,
                }
                for s in self.symbols
            ],
            "working": [
                {"id": i.id, "symbol": i.symbol, "side": i.side, "quantity": i.quantity, "filled": i.filled,
                 "reason": i.reason, "attempts": i.attempts, "order_id": i.order_id}
                for i in self.executor.working()
            ],
        }

    def window(self, symbol: str) -> pd.DataFrame | None:
        return self.windows.get(symbol)


def _fmt_sig(sig: float) -> str:
    return "nan" if sig != sig else f"{sig:g}"


def _bar_dict(bar: Bar | None) -> dict[str, Any] | None:
    if bar is None:
        return None
    return {"time": bar.time.isoformat(), "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close, "volume": bar.volume}


def _decision_dict(d: Decision | None) -> dict[str, Any] | None:
    if d is None:
        return None
    return {"bar_time": d.bar_time.isoformat(), "signal": None if d.signal != d.signal else d.signal, "action": d.action, "detail": d.detail}


def today_local(market_tz: str) -> date:
    return pd.Timestamp.now(tz=market_tz).date()
