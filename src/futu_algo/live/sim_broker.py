"""Local paper broker used for ``dry_run`` mode, replays and tests.

It keeps its own cash, positions and orders and never talks to Futu. Two fill models:

* ``quote``: a marketable order fills immediately at the current ask (buy) / bid (sell);
  resting limit orders fill when a later quote or bar trades through the limit. This is what
  ``dry_run`` uses against live quotes.
* ``next_bar_open``: every order waits for the next bar of its symbol and fills at that bar's
  open (limit orders: at the open if marketable, else at the limit if the bar trades
  through it). This mirrors the backtester's ``next_open`` fills and is what the live-vs-
  backtest parity tests use.

Costs come from the same :class:`~futu_algo.market.costs.CostModel` as the backtester.
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from futu_algo.errors import BrokerError
from futu_algo.live.models import AccountSnapshot, OrderInfo, OrderRequest, OrderState, PositionInfo, Quote
from futu_algo.market.costs import CostModel
from futu_algo.market.instrument import Instrument
from futu_algo.market.ticks import shift_ticks

FillMode = Literal["quote", "next_bar_open"]


@dataclass
class _Pos:
    quantity: int = 0
    cost: float = 0.0  # total cost basis including buy fees

    @property
    def avg(self) -> float:
        return self.cost / self.quantity if self.quantity else 0.0


class SimBroker:
    name = "sim"

    def __init__(
        self,
        capital: float,
        costs: CostModel,
        instruments: Callable[[str], Instrument],
        *,
        fill_mode: FillMode = "quote",
        slippage_ticks: int = 0,
        currency: str = "HKD",
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.env = "DRY_RUN"
        self.cash = float(capital)
        self.costs = costs
        self.instrument = instruments
        self.fill_mode = fill_mode
        self.slippage_ticks = slippage_ticks
        self.currency = currency
        self.clock = clock
        self.realized_pl = 0.0
        self._pos: dict[str, _Pos] = {}
        self._orders: dict[str, OrderInfo] = {}
        self._quotes: dict[str, Quote] = {}
        self._ids = itertools.count(1)
        self._lock = threading.RLock()
        self._listener: Callable[[], None] | None = None
        self.fees_paid = 0.0

    # ---------------------------------------------------------------- lifecycle

    def connect(self) -> None:
        return None

    def close(self) -> None:
        return None

    def set_order_listener(self, callback: Callable[[], None]) -> None:
        self._listener = callback

    def _notify(self) -> None:
        if self._listener:
            self._listener()

    # ------------------------------------------------------------------ queries

    def _last(self, symbol: str) -> float:
        q = self._quotes.get(symbol)
        return q.last if q else 0.0

    def account(self) -> AccountSnapshot:
        with self._lock:
            mv = sum(p.quantity * self._last(s) for s, p in self._pos.items())
            unreal = sum(p.quantity * self._last(s) - p.cost for s, p in self._pos.items())
            reserved = sum(
                o.remaining * (o.price or self._last(o.symbol))
                for o in self._orders.values()
                if o.state.is_open and o.side == "BUY"
            )
            return AccountSnapshot(
                currency=self.currency,
                equity=self.cash + mv,
                cash=self.cash,
                market_value=mv,
                buying_power=max(self.cash - reserved, 0.0),
                realized_pl=self.realized_pl,
                unrealized_pl=unreal,
                time=self.clock(),
            )

    def positions(self) -> dict[str, PositionInfo]:
        with self._lock:
            out = {}
            for sym, p in self._pos.items():
                if p.quantity <= 0:
                    continue
                last = self._last(sym) or p.avg
                selling = sum(o.remaining for o in self._orders.values() if o.symbol == sym and o.side == "SELL" and o.state.is_open)
                out[sym] = PositionInfo(
                    symbol=sym,
                    quantity=p.quantity,
                    can_sell=max(p.quantity - selling, 0),
                    cost_price=p.avg,
                    last_price=last,
                    market_value=p.quantity * last,
                    unrealized_pl=p.quantity * last - p.cost,
                    unrealized_pl_pct=(p.quantity * last / p.cost - 1) if p.cost else 0.0,
                )
            return out

    def orders(self) -> list[OrderInfo]:
        with self._lock:
            return [OrderInfo(**{**o.__dict__}) for o in self._orders.values()]

    # ------------------------------------------------------------------- orders

    def place(self, request: OrderRequest) -> OrderInfo:
        with self._lock:
            if request.quantity <= 0:
                raise BrokerError("Quantity must be positive")
            inst = self.instrument(request.symbol)
            if request.quantity % inst.lot_size:
                raise BrokerError(f"Quantity {request.quantity} is not a multiple of the board lot {inst.lot_size}")
            if request.side == "SELL":
                pos = self._pos.get(request.symbol, _Pos())
                selling = sum(o.remaining for o in self._orders.values() if o.symbol == request.symbol and o.side == "SELL" and o.state.is_open)
                if request.quantity > pos.quantity - selling:
                    raise BrokerError(f"Cannot sell {request.quantity} {request.symbol}: only {pos.quantity - selling} available")
            else:
                ref = request.price or (self._quotes.get(request.symbol).ask if self._quotes.get(request.symbol) else None) or self._last(request.symbol)
                if ref:
                    need = request.quantity * ref + self.costs.fees("BUY", request.quantity, ref, inst, self.clock().date()).total
                    if need > self.account().buying_power + 1e-6:
                        raise BrokerError(f"Insufficient buying power for {request.quantity} {request.symbol} (need {need:,.2f})")
            now = self.clock()
            order = OrderInfo(
                order_id=f"SIM{next(self._ids):06d}",
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                price=float(request.price or 0.0),
                state=OrderState.SUBMITTED,
                order_type="MARKET" if request.is_market else "NORMAL",
                created=now,
                updated=now,
                remark=request.remark,
            )
            self._orders[order.order_id] = order
            if self.fill_mode == "quote":
                self._try_fill_quote(order)
            snapshot = OrderInfo(**{**order.__dict__})
        self._notify()
        return snapshot

    def cancel(self, order_id: str) -> None:
        with self._lock:
            order = self._orders.get(order_id)
            if order is None:
                raise BrokerError(f"Unknown order {order_id}")
            if order.state.is_open:
                order.state = OrderState.CANCELLED
                order.updated = self.clock()
        self._notify()

    # -------------------------------------------------------------- market data

    def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        """QuoteProvider interface: the last quote or bar close seen for each symbol."""
        with self._lock:
            return {s: self._quotes[s] for s in symbols if s in self._quotes}

    def on_quote(self, quote: Quote) -> None:
        with self._lock:
            self._quotes[quote.symbol] = quote
            if self.fill_mode == "quote":
                for order in list(self._orders.values()):
                    if order.symbol == quote.symbol and order.state.is_open:
                        self._try_fill_quote(order)
        self._notify()

    def on_bar(self, symbol: str, time: datetime, open_: float, high: float, low: float, close: float) -> None:
        """Feed a completed bar: fill waiting orders, then mark to the close."""
        filled = False
        with self._lock:
            for order in list(self._orders.values()):
                if order.symbol != symbol or not order.state.is_open:
                    continue
                created = order.created or time
                if self.fill_mode == "next_bar_open" and created >= time:
                    continue
                price = self._bar_fill_price(order, open_, high, low)
                if price is not None:
                    self._fill(order, price, time)
                    filled = True
            q = self._quotes.get(symbol)
            self._quotes[symbol] = Quote(symbol, last=close, bid=q.bid if q else None, ask=q.ask if q else None, time=time)
        if filled:
            self._notify()

    # ------------------------------------------------------------------ filling

    def _bar_fill_price(self, order: OrderInfo, open_: float, high: float, low: float) -> float | None:
        inst = self.instrument(order.symbol)
        day = (order.created or self.clock()).date()
        if order.order_type == "MARKET":
            base = open_
        elif order.side == "BUY":
            if open_ <= order.price:
                base = open_
            elif low <= order.price:
                return order.price
            else:
                return None
        else:
            if open_ >= order.price:
                base = open_
            elif high >= order.price:
                return order.price
            else:
                return None
        if self.slippage_ticks:
            base = shift_ticks(base, self.slippage_ticks if order.side == "BUY" else -self.slippage_ticks, inst, day)
            base = min(base, high) if order.side == "BUY" else max(base, low)
        return base

    def _try_fill_quote(self, order: OrderInfo) -> None:
        q = self._quotes.get(order.symbol)
        if q is None:
            return
        if order.side == "BUY":
            px = q.ask or q.last
            if px and (order.order_type == "MARKET" or px <= order.price + 1e-9):
                self._fill(order, px if order.order_type == "MARKET" else min(px, order.price), self.clock())
        else:
            px = q.bid or q.last
            if px and (order.order_type == "MARKET" or px >= order.price - 1e-9):
                self._fill(order, px if order.order_type == "MARKET" else max(px, order.price), self.clock())

    def _fill(self, order: OrderInfo, price: float, when: datetime) -> None:
        qty = order.remaining
        inst = self.instrument(order.symbol)
        fees = self.costs.fees(order.side, qty, price, inst, when.date()).total
        pos = self._pos.setdefault(order.symbol, _Pos())
        if order.side == "BUY":
            self.cash -= qty * price + fees
            pos.quantity += qty
            pos.cost += qty * price + fees
        else:
            avg = pos.avg
            self.cash += qty * price - fees
            self.realized_pl += qty * (price - avg) - fees
            pos.cost -= avg * qty
            pos.quantity -= qty
            if pos.quantity == 0:
                pos.cost = 0.0
        self.fees_paid += fees
        total_value = order.avg_fill_price * order.filled_qty + price * qty
        order.filled_qty += qty
        order.avg_fill_price = total_value / order.filled_qty
        order.state = OrderState.FILLED
        order.updated = when
