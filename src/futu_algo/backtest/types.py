"""Records produced by the simulator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from futu_algo.market.costs import FeeBreakdown, Side


@dataclass(frozen=True)
class Fill:
    symbol: str
    time: pd.Timestamp
    side: Side
    quantity: int
    price: float
    fees: FeeBreakdown
    reason: str
    bar_index: int

    @property
    def value(self) -> float:
        return self.quantity * self.price

    @property
    def cash_delta(self) -> float:
        if self.side == "BUY":
            return -(self.value + self.fees.total)
        return self.value - self.fees.total

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "time": self.time.isoformat(),
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "value": self.value,
            "fees": self.fees.total,
            **{f"fee_{k}": v for k, v in self.fees.as_dict().items() if k != "total"},
            "reason": self.reason,
        }


@dataclass
class Trade:
    """A round trip: from flat to long and back to flat (or still open at the end)."""

    symbol: str
    entry_time: pd.Timestamp
    entry_index: int
    quantity: int
    entry_value: float
    entry_fees: float
    exit_time: pd.Timestamp | None = None
    exit_index: int | None = None
    exit_value: float = 0.0
    exit_fees: float = 0.0
    exit_reason: str | None = None
    is_open: bool = False
    mark_price: float | None = None
    mae_pct: float | None = None
    mfe_pct: float | None = None
    # How the entry/exit filled: "open", "close", "intrabar" or "end".
    entry_fill: str = "open"
    exit_fill: str | None = None
    # Shares still held when an open trade is marked (may be less than ``quantity`` after
    # partial, volume-capped exits).
    open_quantity: int = 0

    @property
    def entry_price(self) -> float:
        return self.entry_value / self.quantity

    @property
    def exit_price(self) -> float | None:
        if self.is_open:
            return self.mark_price
        return self.exit_value / self.quantity if self.quantity else None

    @property
    def fees(self) -> float:
        return self.entry_fees + self.exit_fees

    @property
    def pnl(self) -> float:
        realised = self.exit_value - self.exit_fees - self.entry_value - self.entry_fees
        if self.is_open:
            assert self.mark_price is not None
            return realised + self.open_quantity * self.mark_price
        return realised

    @property
    def return_pct(self) -> float:
        basis = self.entry_value + self.entry_fees
        return self.pnl / basis if basis else 0.0

    @property
    def bars_held(self) -> int | None:
        if self.exit_index is None:
            return None
        return self.exit_index - self.entry_index

    @property
    def days_held(self) -> float | None:
        if self.exit_time is None:
            return None
        return (self.exit_time - self.entry_time).total_seconds() / 86400

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "entry_time": self.entry_time.isoformat(),
            "exit_time": self.exit_time.isoformat() if self.exit_time is not None else None,
            "quantity": self.quantity,
            "open_quantity": self.open_quantity if self.is_open else 0,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "pnl": self.pnl,
            "return_pct": self.return_pct,
            "fees": self.fees,
            "bars_held": self.bars_held,
            "days_held": self.days_held,
            "exit_reason": self.exit_reason if not self.is_open else "open",
            "is_open": self.is_open,
            "mae_pct": self.mae_pct,
            "mfe_pct": self.mfe_pct,
        }


@dataclass
class Book:
    """One simulated account: a single symbol in scan mode, or the whole portfolio."""

    name: str
    currency: str
    initial_capital: float
    equity: pd.Series
    cash: pd.Series
    exposure: pd.Series
    fills: list[Fill] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    event_counts: dict[str, int] = field(default_factory=dict)
    benchmark: pd.Series | None = None
    benchmark_name: str | None = None
    buy_hold: pd.Series | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    symbols: list[str] = field(default_factory=list)

    @property
    def total_fees(self) -> float:
        return sum(f.fees.total for f in self.fills)
