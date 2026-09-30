"""Strategy interface.

A strategy is two pure, vectorised steps plus an optional per-bar hook:

1. ``indicators(bars)`` returns indicator columns aligned to ``bars``. It must be *causal*:
   the value at bar i may only use bars 0..i. :func:`check_lookahead` enforces this by
   recomputing on truncated data.
2. ``signals(bars, ind)`` returns the desired state per bar: ``1`` = be long, ``0`` = be flat,
   ``NaN`` = no opinion (keep whatever position is held). Event-style strategies (crosses)
   emit 1/0 only on the event bar; state-style strategies emit 1/0 on every bar.
3. ``on_bar(ctx)`` (optional) can override the precomputed signal with position-aware logic.

Because indicators are causal, the value at the last bar of any window equals the backtest's
value at that bar. A live bot can therefore call ``decide_last(window)`` on each new bar and
get exactly the decision the backtest made, which is the point of sharing strategy code
between the backtester and the live engine.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, ValidationError

from futu_algo.errors import StrategyError


class StrategyParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


@dataclass(frozen=True)
class PlotSpec:
    column: str
    pane: Literal["price", "lower"] = "lower"
    kind: Literal["line", "histogram"] = "line"
    label: str | None = None


@dataclass
class BarContext:
    """Per-bar view passed to :meth:`Strategy.on_bar`."""

    symbol: str
    index: int
    time: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float
    signal: float
    position: int
    entry_price: float | None
    bars_held: int
    # History up to and including this bar only; later rows are never exposed.
    indicators: pd.DataFrame
    bars: pd.DataFrame

    def indicator(self, column: str) -> float:
        return float(self.indicators[column].to_numpy(dtype=float)[self.index])


class Strategy(ABC):
    name: ClassVar[str] = ""
    title: ClassVar[str] = ""
    description: ClassVar[str] = ""
    Params: ClassVar[type[StrategyParams]] = StrategyParams
    plots: ClassVar[tuple[PlotSpec, ...]] = ()

    def __init__(
        self, params: dict[str, Any] | StrategyParams | None = None, **kwargs: Any
    ) -> None:
        if isinstance(params, StrategyParams):
            params = params.model_dump()
        merged = {**(params or {}), **kwargs}
        try:
            self.params = self.Params.model_validate(merged)
        except ValidationError as exc:
            raise StrategyError(f"Invalid parameters for strategy {self.name!r}: {exc}") from exc

    # ---------------------------------------------------------------- hooks

    def warmup_bars(self) -> int:
        """Bars of history needed before the first trustworthy signal."""
        return 0

    @property
    def lookahead_safe(self) -> bool:
        """False when the strategy deliberately uses future data (e.g. raw ZIG)."""
        return True

    def warnings(self) -> list[str]:
        return []

    @abstractmethod
    def indicators(self, bars: pd.DataFrame) -> pd.DataFrame: ...

    @abstractmethod
    def signals(self, bars: pd.DataFrame, ind: pd.DataFrame) -> pd.Series: ...

    def on_bar(self, ctx: BarContext) -> float:
        return ctx.signal

    # --------------------------------------------------------------- running

    @property
    def has_bar_hook(self) -> bool:
        return type(self).on_bar is not Strategy.on_bar

    def run(self, bars: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
        ind = self.indicators(bars)
        if not isinstance(ind, pd.DataFrame) or not ind.index.equals(bars.index):
            raise StrategyError(f"{self.name}.indicators must return a DataFrame aligned to bars")
        sig = self.signals(bars, ind)
        if not isinstance(sig, pd.Series) or not sig.index.equals(bars.index):
            raise StrategyError(f"{self.name}.signals must return a Series aligned to bars")
        sig = sig.astype("float64")
        bad = sig.notna() & ~sig.isin([0.0, 1.0])
        if bad.any():
            raise StrategyError(
                f"{self.name}.signals must be 1, 0 or NaN; got {sorted(set(sig[bad].tolist()))[:5]}"
            )
        return ind, sig

    def decide_last(self, bars: pd.DataFrame) -> float:
        """Signal for the most recent bar; what a live bot calls on each completed bar."""
        _, sig = self.run(bars)
        return float(sig.to_numpy(dtype=float)[-1]) if len(sig) else float("nan")

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "params": self.params.model_dump(),
            "warmup_bars": self.warmup_bars(),
            "lookahead_safe": self.lookahead_safe,
        }

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return cls.Params.model_json_schema()


def as_bool(x: pd.Series) -> pd.Series:
    """Boolean series with missing values as False, without pandas' object-downcast path."""
    return x.astype("boolean").fillna(False).astype(bool)


def events(buy: pd.Series, sell: pd.Series) -> pd.Series:
    """Event signal from boolean buy/sell series: 1 on buy bars, 0 on sell bars, else NaN.

    A bar that is both a buy and a sell is treated as neither.
    """
    b = as_bool(buy)
    s = as_bool(sell)
    out = pd.Series(np.nan, index=buy.index)
    out[b & ~s] = 1.0
    out[s & ~b] = 0.0
    return out


def state(long: pd.Series) -> pd.Series:
    """State signal: 1 where ``long`` is true, 0 where false, NaN where undefined."""
    out = long.astype("float64")
    return out.where(long.notna())
