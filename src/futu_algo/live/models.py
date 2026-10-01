"""Broker-neutral records used by the live engine, the store and the web console."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

Side = Literal["BUY", "SELL"]


class OrderState(StrEnum):
    PENDING = "pending"  # accepted locally / waiting to be submitted by the exchange
    SUBMITTED = "submitted"  # live on the exchange, nothing filled
    PARTIAL = "partial"  # partly filled, remainder live
    FILLED = "filled"
    CANCELLED = "cancelled"  # cancelled (possibly after a partial fill)
    FAILED = "failed"  # rejected / failed / disabled

    @property
    def is_open(self) -> bool:
        return self in (OrderState.PENDING, OrderState.SUBMITTED, OrderState.PARTIAL)


# Futu OrderStatus strings -> normalised state.
FUTU_STATUS: dict[str, OrderState] = {
    "UNSUBMITTED": OrderState.PENDING,
    "WAITING_SUBMIT": OrderState.PENDING,
    "SUBMITTING": OrderState.PENDING,
    "SUBMITTED": OrderState.SUBMITTED,
    "FILLED_PART": OrderState.PARTIAL,
    "FILLED_ALL": OrderState.FILLED,
    "CANCELLING_PART": OrderState.PARTIAL,
    "CANCELLING_ALL": OrderState.SUBMITTED,
    "CANCELLED_PART": OrderState.CANCELLED,
    "CANCELLED_ALL": OrderState.CANCELLED,
    "FILL_CANCELLED": OrderState.CANCELLED,
    "SUBMIT_FAILED": OrderState.FAILED,
    "FAILED": OrderState.FAILED,
    "TIMEOUT": OrderState.FAILED,
    "DISABLED": OrderState.FAILED,
    "DELETED": OrderState.CANCELLED,
}


@dataclass
class AccountSnapshot:
    currency: str
    equity: float  # total assets
    cash: float
    market_value: float
    buying_power: float
    realized_pl: float = 0.0
    unrealized_pl: float = 0.0
    time: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["time"] = self.time.isoformat() if self.time else None
        return d


@dataclass
class PositionInfo:
    symbol: str
    quantity: int
    can_sell: int
    cost_price: float
    last_price: float
    market_value: float
    unrealized_pl: float = 0.0
    unrealized_pl_pct: float = 0.0
    name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OrderInfo:
    order_id: str
    symbol: str
    side: Side
    quantity: int
    price: float
    state: OrderState
    order_type: str = "NORMAL"
    filled_qty: int = 0
    avg_fill_price: float = 0.0
    created: datetime | None = None
    updated: datetime | None = None
    remark: str = ""
    error: str = ""
    name: str = ""

    @property
    def remaining(self) -> int:
        return max(self.quantity - self.filled_qty, 0)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = str(self.state)
        d["created"] = self.created.isoformat() if self.created else None
        d["updated"] = self.updated.isoformat() if self.updated else None
        return d


@dataclass
class Quote:
    symbol: str
    last: float
    bid: float | None = None
    ask: float | None = None
    time: datetime | None = None
    lot_size: int | None = None
    suspended: bool = False

    @property
    def mid(self) -> float:
        if self.bid and self.ask:
            return (self.bid + self.ask) / 2
        return self.last


@dataclass
class OrderRequest:
    symbol: str
    side: Side
    quantity: int
    price: float | None  # None = market order
    reason: str = ""
    remark: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_market(self) -> bool:
        return self.price is None
