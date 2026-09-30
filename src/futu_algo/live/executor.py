"""Order execution: turn intents ("buy 400 HK.00700 because of a MACD cross") into broker
orders and see them through.

An intent is filled by one or more orders. Each order is a limit (or market) order priced
from a fresh quote; if it is not filled within ``order.timeout_seconds`` it is cancelled and
the remainder is re-priced and re-sent, up to ``order.max_replaces`` times. Fills are derived
from each order's cumulative filled quantity on every sync, which works for paper accounts
(Futu sends no deal pushes there) and survives restarts because the last seen quantity is
stored in SQLite.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from futu_algo.config import OrderConfig
from futu_algo.errors import BrokerError, RiskRejected
from futu_algo.events import FILL, ORDER, REJECTION, EventBus
from futu_algo.live.broker import Broker, QuoteProvider
from futu_algo.live.models import OrderInfo, OrderRequest, Quote, Side
from futu_algo.live.risk import RiskContext, RiskManager
from futu_algo.live.store import StateStore
from futu_algo.market.calendar import Phase
from futu_algo.market.instrument import Instrument
from futu_algo.market.ticks import round_to_tick, shift_ticks

log = logging.getLogger(__name__)

REMARK_PREFIX = "futu_algo"


def limit_price(side: Side, quote: Quote, inst: Instrument, cfg: OrderConfig, day: datetime) -> float | None:
    """Limit price for an order, rounded onto the exchange tick grid (``None`` = market)."""
    if cfg.price == "market":
        return None
    when = day.date()
    if cfg.price == "aggressive":
        base = (quote.ask if side == "BUY" else quote.bid) or quote.last
    elif cfg.price == "passive":
        base = (quote.bid if side == "BUY" else quote.ask) or quote.last
    else:
        base = quote.mid
    if not base:
        return None
    price = round_to_tick(base, inst, when, "up" if side == "BUY" else "down")
    if cfg.extra_ticks:
        price = shift_ticks(price, cfg.extra_ticks if side == "BUY" else -cfg.extra_ticks, inst, when)
    return price


@dataclass
class Intent:
    id: int
    symbol: str
    side: Side
    quantity: int
    reason: str
    attempts: int = 0
    order_id: str | None = None
    sent_at: datetime | None = None
    cancel_requested: bool = False
    filled: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def remaining(self) -> int:
        return max(self.quantity - self.filled, 0)


class OrderExecutor:
    def __init__(
        self,
        broker: Broker,
        quotes: QuoteProvider,
        store: StateStore,
        bus: EventBus,
        risk: RiskManager,
        cfg: OrderConfig,
        instruments: Callable[[str], Instrument],
        context: Callable[[str, Quote | None], RiskContext],
        *,
        env: str,
    ) -> None:
        self.broker = broker
        self.quotes = quotes
        self.store = store
        self.bus = bus
        self.risk = risk
        self.cfg = cfg
        self.instrument = instruments
        self.context = context
        self.env = env
        self.intents: dict[int, Intent] = {}
        self.orders: dict[str, OrderInfo] = {}
        self._seen: dict[str, tuple[object, ...]] = {}
        self._quote_cache: dict[str, Quote] | None = None
        self._restore()

    # ------------------------------------------------------------------ restore

    def _restore(self) -> None:
        """Re-adopt intents that were still working when the process stopped."""
        for row in self.store.intents(status="working"):
            intent = Intent(
                id=int(row["id"]), symbol=row["symbol"], side=row["side"], quantity=int(row["quantity"]),
                reason=row["reason"] or "", attempts=int(row["attempts"]),
            )
            for o in self.store.orders_for_intent(intent.id):
                intent.filled += int(o["filled_qty"])
                if o["state"] in ("pending", "submitted", "partial"):
                    intent.order_id = o["order_id"]
            self.intents[intent.id] = intent
        if self.intents:
            log.info("Restored %d working intent(s) from %s", len(self.intents), self.store.path)

    # -------------------------------------------------------------------- views

    def working(self, symbol: str | None = None) -> list[Intent]:
        return [i for i in self.intents.values() if symbol is None or i.symbol == symbol]

    def working_side(self, symbol: str, side: Side) -> int:
        return sum(i.remaining for i in self.intents.values() if i.symbol == symbol and i.side == side)

    def working_buy_value(self, prices: dict[str, float]) -> float:
        return sum(i.remaining * prices.get(i.symbol, 0.0) for i in self.intents.values() if i.side == "BUY")

    # ------------------------------------------------------------------ intents

    def submit(self, symbol: str, side: Side, quantity: int, reason: str, bar_time: datetime | None = None) -> int | None:
        if quantity <= 0:
            return None
        # A new decision supersedes working intents for the same symbol (e.g. a sell signal
        # while a buy is still being worked).
        for other in list(self.working(symbol)):
            self.abandon(other.id, f"superseded by {side} ({reason})")
        intent_id = self.store.add_intent(symbol, side, quantity, reason, bar_time)
        self.intents[intent_id] = Intent(intent_id, symbol, side, quantity, reason)
        self.bus.emit(ORDER, f"{side} {quantity} {symbol}: {reason}", symbol=symbol, intent=intent_id, side=side, quantity=quantity, reason=reason)
        return intent_id

    def abandon(self, intent_id: int, why: str) -> None:
        intent = self.intents.pop(intent_id, None)
        if intent is None:
            return
        if intent.order_id and intent.order_id in self.orders and self.orders[intent.order_id].state.is_open:
            self._cancel(intent.order_id)
        self.store.update_intent(intent_id, status="cancelled", detail=why)
        log.info("Intent %d (%s %s) cancelled: %s", intent_id, intent.side, intent.symbol, why)

    def cancel_all(self, why: str = "cancel all") -> int:
        n = 0
        for intent_id in list(self.intents):
            self.abandon(intent_id, why)
            n += 1
        for order in list(self.orders.values()):
            if order.state.is_open:
                self._cancel(order.order_id)
                n += 1
        return n

    def _cancel(self, order_id: str) -> None:
        try:
            self.broker.cancel(order_id)
        except BrokerError as exc:
            log.warning("Cancel %s failed: %s", order_id, exc)

    # --------------------------------------------------------------------- sync

    def _record(self, order: OrderInfo, intent_id: int | None, now: datetime) -> int:
        """Store an order snapshot; record and announce any newly filled quantity."""
        self.orders[order.order_id] = order
        fingerprint = (str(order.state), order.filled_qty, order.avg_fill_price, order.price, order.error)
        if self._seen.get(order.order_id) == fingerprint:
            return 0  # unchanged since the last sync
        self._seen[order.order_id] = fingerprint
        new_qty, _ = self.store.upsert_order(order, intent_id, self.env)
        if new_qty > 0:
            price = order.avg_fill_price or order.price
            self.store.add_fill(order.order_id, order.symbol, order.side, new_qty, price, self.env, order.updated or now)
            self.bus.emit(
                FILL, f"{order.side} {new_qty} {order.symbol} @ {price:g}", symbol=order.symbol,
                order_id=order.order_id, side=order.side, quantity=new_qty, price=price,
            )
            if intent_id is not None and intent_id in self.intents:
                self.intents[intent_id].filled += new_qty
        return new_qty

    def refresh_orders(self, now: datetime) -> list[tuple[OrderInfo, int]]:
        """Pull today's orders from the broker, record new fills; return (order, new_qty)."""
        fills: list[tuple[OrderInfo, int]] = []
        for order in self.broker.orders():
            fingerprint = (str(order.state), order.filled_qty, order.avg_fill_price, order.price, order.error)
            if self._seen.get(order.order_id) == fingerprint:
                self.orders[order.order_id] = order
                continue
            intent_id = self.store.order_intent(order.order_id)
            if intent_id is None and order.remark.startswith(f"{REMARK_PREFIX}:"):
                try:
                    intent_id = int(order.remark.split(":", 1)[1])
                except ValueError:
                    intent_id = None
            new_qty = self._record(order, intent_id, now)
            if new_qty > 0:
                fills.append((order, new_qty))
        return fills

    def sync(self, now: datetime) -> list[tuple[OrderInfo, int]]:
        fills = self.refresh_orders(now)
        self._quote_cache = None
        for intent in list(self.intents.values()):
            self._advance(intent, now)
        self._quote_cache = None
        return fills

    def _quote(self, symbol: str) -> Quote | None:
        """One snapshot request per sync for every intent that needs a price."""
        if self._quote_cache is None:
            wanted = sorted({i.symbol for i in self.intents.values() if i.order_id is None} | {symbol})
            try:
                self._quote_cache = self.quotes.quotes(wanted)
            except Exception as exc:
                log.warning("No quotes for %s: %s", wanted, exc)
                self._quote_cache = {}
        cache = self._quote_cache if self._quote_cache is not None else {}
        if symbol not in cache:
            try:
                cache.update(self.quotes.quotes([symbol]))
            except Exception as exc:
                log.warning("No quote for %s: %s", symbol, exc)
        return cache.get(symbol)

    def _advance(self, intent: Intent, now: datetime) -> None:
        order = self.orders.get(intent.order_id) if intent.order_id else None
        if order is not None and order.state.is_open:
            age = (now - (intent.sent_at or order.created or now)).total_seconds()
            if age >= self.cfg.timeout_seconds and not intent.cancel_requested:
                log.info("Order %s for intent %d unfilled after %.0fs; cancelling to re-price", order.order_id, intent.id, age)
                intent.cancel_requested = True
                self._cancel(order.order_id)
            return
        intent.order_id, intent.cancel_requested = None, False
        if intent.remaining <= 0:
            self._finish(intent, "done")
            return
        if intent.attempts > self.cfg.max_replaces:
            self._finish(intent, "failed", f"not filled after {intent.attempts} order(s); {intent.remaining} left")
            self.bus.emit(
                REJECTION, f"{intent.side} {intent.symbol}: gave up after {intent.attempts} attempts ({intent.remaining} unfilled)",
                level="warning", symbol=intent.symbol, intent=intent.id,
            )
            return
        self._send(intent, now)

    def _finish(self, intent: Intent, status: str, detail: str = "") -> None:
        self.intents.pop(intent.id, None)
        self.store.update_intent(intent.id, status=status, attempts=intent.attempts, detail=detail)

    def _send(self, intent: Intent, now: datetime) -> None:
        inst = self.instrument(intent.symbol)
        if self.context(intent.symbol, None).phase != Phase.CONTINUOUS:
            return  # wait for the session without spending quote requests
        quote = self._quote(intent.symbol)
        ctx = self.context(intent.symbol, quote)
        qty = intent.remaining
        if intent.side == "SELL":
            held = ctx.positions.get(intent.symbol)
            qty = min(qty, held.can_sell if held else 0)
            if qty <= 0:
                self._finish(intent, "done", "nothing left to sell")
                return
        else:
            qty -= qty % inst.lot_size
            if qty <= 0:
                self._finish(intent, "done", "remainder below one board lot")
                return
        price = limit_price(intent.side, quote, inst, self.cfg, now) if quote else None
        if price is None and self.cfg.price != "market":
            if ctx.phase == Phase.CONTINUOUS:
                log.warning("No usable quote for %s; will retry", intent.symbol)
            return
        request = OrderRequest(
            symbol=intent.symbol, side=intent.side, quantity=qty, price=price,
            reason=intent.reason, remark=f"{REMARK_PREFIX}:{intent.id}",
        )
        try:
            self.risk.check(request, ctx)
        except RiskRejected as exc:
            if ctx.phase != Phase.CONTINUOUS:
                return  # wait for the session; not a failure
            self._finish(intent, "rejected", str(exc))
            self.bus.emit(REJECTION, f"{intent.side} {qty} {intent.symbol} blocked: {exc}", level="warning", symbol=intent.symbol, intent=intent.id)
            return
        intent.attempts += 1
        try:
            order = self.broker.place(request)
        except BrokerError as exc:
            self.store.update_intent(intent.id, attempts=intent.attempts, detail=str(exc))
            self.bus.emit(REJECTION, f"{intent.side} {qty} {intent.symbol} rejected by broker: {exc}", level="warning", symbol=intent.symbol, intent=intent.id)
            if intent.attempts > self.cfg.max_replaces:
                self._finish(intent, "failed", str(exc))
            return
        intent.order_id = order.order_id
        intent.sent_at = now
        self.store.update_intent(intent.id, attempts=intent.attempts)
        px = "MKT" if price is None else f"{price:g}"
        self.bus.emit(
            ORDER, f"Sent {intent.side} {qty} {intent.symbol} @ {px} (attempt {intent.attempts})",
            symbol=intent.symbol, order_id=order.order_id, side=intent.side, quantity=qty, price=price,
        )
        self._record(order, intent.id, now)
        if not order.state.is_open and intent.remaining <= 0:
            self._finish(intent, "done")
