"""Pre-trade risk checks and the kill switch.

Every order the engine wants to send passes :meth:`RiskManager.check`. Exits (sells that
reduce a long position) are only blocked by checks that protect against bad prices; entries
are also subject to exposure, loss and schedule limits, so a halted engine can still get out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from futu_algo.config import RiskConfig
from futu_algo.errors import RiskRejected
from futu_algo.live.models import AccountSnapshot, OrderRequest, PositionInfo, Quote
from futu_algo.market.calendar import Phase, minutes_to_close
from futu_algo.market.instrument import MarketSpec


@dataclass
class RiskContext:
    now: datetime
    phase: Phase
    account: AccountSnapshot
    positions: dict[str, PositionInfo]
    working_buy_value: float  # value of open buy orders not yet filled
    quote: Quote | None
    orders_today: int
    day_start_equity: float | None
    halted: bool
    halt_reason: str = ""


class RiskManager:
    def __init__(self, cfg: RiskConfig, market: MarketSpec) -> None:
        self.cfg = cfg
        self.market = market

    def daily_loss_breached(self, account: AccountSnapshot, day_start_equity: float | None) -> str | None:
        if day_start_equity is None or day_start_equity <= 0:
            return None
        loss = day_start_equity - account.equity
        if self.cfg.max_daily_loss is not None and loss >= self.cfg.max_daily_loss:
            return f"daily loss {loss:,.2f} >= limit {self.cfg.max_daily_loss:,.2f}"
        if self.cfg.max_daily_loss_pct is not None and loss / day_start_equity >= self.cfg.max_daily_loss_pct:
            return f"daily loss {loss / day_start_equity:.2%} >= limit {self.cfg.max_daily_loss_pct:.2%}"
        return None

    def entries_closed(self, now: datetime) -> bool:
        n = self.cfg.no_entries_minutes_before_close
        return bool(n) and minutes_to_close(now, self.market) <= n

    def should_flatten(self, now: datetime) -> bool:
        n = self.cfg.flatten_minutes_before_close
        return n is not None and 0 < minutes_to_close(now, self.market) <= n

    def check(self, req: OrderRequest, ctx: RiskContext) -> None:
        cfg = self.cfg
        if ctx.phase != Phase.CONTINUOUS:
            raise RiskRejected(f"market is {ctx.phase}, orders are only sent in continuous trading")
        if ctx.orders_today >= cfg.max_orders_per_day:
            raise RiskRejected(f"max_orders_per_day ({cfg.max_orders_per_day}) reached")
        q = ctx.quote
        if q is not None and q.suspended:
            raise RiskRejected(f"{req.symbol} is suspended")
        ref = q.last if q and q.last else None
        if req.price is not None and ref:
            band = abs(req.price / ref - 1)
            if band > cfg.price_band_pct:
                raise RiskRejected(
                    f"limit {req.price} is {band:.2%} from last {ref} (price_band_pct {cfg.price_band_pct:.2%})"
                )
        if req.side == "SELL":
            pos = ctx.positions.get(req.symbol)
            if pos is None or req.quantity > pos.can_sell:
                have = pos.can_sell if pos else 0
                raise RiskRejected(f"sell {req.quantity} exceeds sellable {have} (no short selling)")
            return

        # ---- entries only below this line
        if ctx.halted:
            raise RiskRejected(f"entries halted: {ctx.halt_reason or 'kill switch'}")
        if self.entries_closed(ctx.now):
            raise RiskRejected(f"no new entries within {cfg.no_entries_minutes_before_close} min of the close")
        price = req.price if req.price is not None else (q.ask or q.last if q else None)
        if not price:
            raise RiskRejected("no price available to value the order")
        value = req.quantity * price
        if cfg.max_order_value is not None and value > cfg.max_order_value:
            raise RiskRejected(f"order value {value:,.2f} > max_order_value {cfg.max_order_value:,.2f}")
        held = ctx.positions.get(req.symbol)
        position_value = (held.market_value if held else 0.0) + value
        if cfg.max_position_value is not None and position_value > cfg.max_position_value:
            raise RiskRejected(f"position value {position_value:,.2f} > max_position_value {cfg.max_position_value:,.2f}")
        equity = ctx.account.equity
        if equity > 0:
            exposure = (ctx.account.market_value + ctx.working_buy_value + value) / equity
            if exposure > cfg.max_total_exposure + 1e-9:
                raise RiskRejected(f"exposure would be {exposure:.1%} > max_total_exposure {cfg.max_total_exposure:.0%}")
        if value > ctx.account.buying_power + 1e-6:
            raise RiskRejected(f"order value {value:,.2f} > buying power {ctx.account.buying_power:,.2f}")
        breach = self.daily_loss_breached(ctx.account, ctx.day_start_equity)
        if breach:
            raise RiskRejected(breach)
