"""Built-in strategies.

``macd``, ``kdj`` and ``rsi`` keep the buy/sell rules of the 1.x strategies (``MACD_Cross``,
``KDJ_Cross``, ``RSI_Threshold``) on TDX-exact indicators. ``ema_ribbon`` is the 1.x
``EMA_Ribbon`` with its crossing rule fixed (the old version compared a bar with itself and
could never fire). ``boll`` and ``donchian`` are new.

Every strategy here is causal, so the live engine's ``decide_last`` on the most recent
completed bar returns exactly the decision the backtester made on that bar.
"""

from __future__ import annotations

from typing import Literal

import pandas as pd
from pydantic import Field, model_validator

from futu_algo.indicators.tdx import BOLL, CROSS, EMA, HHV, KDJ, LLV, MA, MACD, MAX, REF, RSI
from futu_algo.strategy.base import PlotSpec, Strategy, StrategyParams, events, state
from futu_algo.strategy.registry import register

Mode = Literal["cross", "state"]


class MACDParams(StrategyParams):
    fast_period: int = Field(12, ge=2, le=200)
    slow_period: int = Field(26, ge=3, le=400)
    signal_period: int = Field(9, ge=2, le=200)
    mode: Mode = Field(
        "cross", description="cross: act on DIF/DEA crossings; state: long while DIF > DEA"
    )

    @model_validator(mode="after")
    def _order(self) -> MACDParams:
        if self.fast_period >= self.slow_period:
            raise ValueError("fast_period must be less than slow_period")
        return self


@register
class MACDStrategy(Strategy):
    name = "macd"
    title = "MACD cross"
    description = "Buy when DIF crosses above DEA, sell when it crosses below (TDX MACD)."
    Params = MACDParams
    plots = (
        PlotSpec("dif", "lower", "line", "DIF"),
        PlotSpec("dea", "lower", "line", "DEA"),
        PlotSpec("macd", "lower", "histogram", "MACD"),
    )
    params: MACDParams

    def warmup_bars(self) -> int:
        # EMAs are seeded with the first bar; ~3x the longest span removes the seed's effect.
        return 3 * (self.params.slow_period + self.params.signal_period)

    def indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        return MACD(bars["close"], p.fast_period, p.slow_period, p.signal_period)

    def signals(self, bars: pd.DataFrame, ind: pd.DataFrame) -> pd.Series:
        if self.params.mode == "state":
            return state(ind["dif"] > ind["dea"])
        return events(CROSS(ind["dif"], ind["dea"]), CROSS(ind["dea"], ind["dif"]))


class MACrossParams(StrategyParams):
    short_window: int = Field(20, ge=1, le=500)
    long_window: int = Field(50, ge=2, le=1000)
    ma_type: Literal["sma", "ema"] = "sma"
    mode: Mode = "cross"

    @model_validator(mode="after")
    def _order(self) -> MACrossParams:
        if self.short_window >= self.long_window:
            raise ValueError("short_window must be less than long_window")
        return self


@register
class MACrossStrategy(Strategy):
    name = "ma_cross"
    title = "Moving-average cross"
    description = "Buy when the short MA crosses above the long MA, sell on the reverse cross."
    Params = MACrossParams
    plots = (
        PlotSpec("ma_short", "price", "line", "MA short"),
        PlotSpec("ma_long", "price", "line", "MA long"),
    )
    params: MACrossParams

    def warmup_bars(self) -> int:
        return self.params.long_window * (3 if self.params.ma_type == "ema" else 1)

    def indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        fn = MA if p.ma_type == "sma" else EMA
        return pd.DataFrame(
            {
                "ma_short": fn(bars["close"], p.short_window),
                "ma_long": fn(bars["close"], p.long_window),
            },
            index=bars.index,
        )

    def signals(self, bars: pd.DataFrame, ind: pd.DataFrame) -> pd.Series:
        s, lg = ind["ma_short"], ind["ma_long"]
        if self.params.mode == "state":
            return state((s > lg).where(lg.notna()))
        return events(CROSS(s, lg), CROSS(lg, s))


class KDJParams(StrategyParams):
    n: int = Field(9, ge=2, le=200, description="RSV lookback (1.x fast_k)")
    m1: int = Field(3, ge=1, le=50, description="K smoothing (slow_k)")
    m2: int = Field(3, ge=1, le=50, description="D smoothing (slow_d)")
    over_buy: float = Field(80.0, ge=50, le=100)
    over_sell: float = Field(20.0, ge=0, le=50)


@register
class KDJStrategy(Strategy):
    name = "kdj"
    title = "KDJ oversold/overbought cross"
    description = (
        "KDJ_Cross rules: buy on a K-over-D turn while D is below the oversold "
        "level, sell on a K-under-D turn while D is above the overbought level."
    )
    Params = KDJParams
    plots = (
        PlotSpec("k", "lower", "line", "K"),
        PlotSpec("d", "lower", "line", "D"),
        PlotSpec("j", "lower", "line", "J"),
    )
    params: KDJParams

    def warmup_bars(self) -> int:
        return self.params.n + 10 * max(self.params.m1, self.params.m2)

    def indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        return KDJ(bars["high"], bars["low"], bars["close"], p.n, p.m1, p.m2)

    def signals(self, bars: pd.DataFrame, ind: pd.DataFrame) -> pd.Series:
        p = self.params
        k, d = ind["k"], ind["d"]
        pk, pd_ = REF(k, 1), REF(d, 1)
        buy = (p.over_sell > d) & (d > pd_) & (pd_ > pk) & (k > pk) & (k > d)
        sell = (p.over_buy < d) & (d < pd_) & (pd_ < pk) & (k < pk) & (k < d)
        return events(buy, sell)


class RSIParams(StrategyParams):
    period: int = Field(6, ge=2, le=200)
    lower: float = Field(30.0, ge=0, le=100)
    upper: float = Field(70.0, ge=0, le=100)

    @model_validator(mode="after")
    def _order(self) -> RSIParams:
        if self.lower >= self.upper:
            raise ValueError("lower must be below upper")
        return self


@register
class RSIStrategy(Strategy):
    name = "rsi"
    title = "RSI threshold"
    description = (
        "RSI_Threshold rules: buy when RSI drops through the lower level, sell when "
        "it rises through the upper level (TDX RSI)."
    )
    Params = RSIParams
    plots = (PlotSpec("rsi", "lower", "line", "RSI"),)
    params: RSIParams

    def warmup_bars(self) -> int:
        return 10 * self.params.period

    def indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({"rsi": RSI(bars["close"], self.params.period)}, index=bars.index)

    def signals(self, bars: pd.DataFrame, ind: pd.DataFrame) -> pd.Series:
        p = self.params
        rsi, prev = ind["rsi"], REF(ind["rsi"], 1)
        return events((rsi < p.lower) & (prev > p.lower), (rsi > p.upper) & (prev < p.upper))


class EMARibbonParams(StrategyParams):
    fast: int = Field(5, ge=2, le=200)
    slow: int = Field(8, ge=3, le=400)
    support: int = Field(13, ge=4, le=600)

    @model_validator(mode="after")
    def _order(self) -> EMARibbonParams:
        if not self.fast < self.slow < self.support:
            raise ValueError("expected fast < slow < support")
        return self


@register
class EMARibbonStrategy(Strategy):
    name = "ema_ribbon"
    title = "EMA ribbon"
    description = (
        "Buy when the fast EMA rises above both the slow and the support EMA; sell when it "
        "drops back below either of them."
    )
    Params = EMARibbonParams
    plots = (
        PlotSpec("ema_fast", "price", "line", "EMA fast"),
        PlotSpec("ema_slow", "price", "line", "EMA slow"),
        PlotSpec("ema_support", "price", "line", "EMA support"),
    )
    params: EMARibbonParams

    def warmup_bars(self) -> int:
        return 3 * self.params.support

    def indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        p, c = self.params, bars["close"]
        return pd.DataFrame(
            {"ema_fast": EMA(c, p.fast), "ema_slow": EMA(c, p.slow), "ema_support": EMA(c, p.support)},
            index=bars.index,
        )

    def signals(self, bars: pd.DataFrame, ind: pd.DataFrame) -> pd.Series:
        upper = MAX(ind["ema_slow"], ind["ema_support"])
        # Above both now and not before -> buy; was above both and no longer is -> sell.
        return events(CROSS(ind["ema_fast"], upper), CROSS(upper, ind["ema_fast"]))


class BollParams(StrategyParams):
    period: int = Field(20, ge=5, le=400)
    width: float = Field(2.0, gt=0, le=5)
    mode: Literal["breakout", "reversion"] = Field(
        "breakout",
        description="breakout: buy a close above the upper band, sell below the middle band; "
        "reversion: buy a close back above the lower band, sell at the middle band",
    )


@register
class BollStrategy(Strategy):
    name = "boll"
    title = "Bollinger bands"
    description = "Bollinger band breakout or mean reversion (TDX BOLL)."
    Params = BollParams
    plots = (
        PlotSpec("boll_upper", "price", "line", "BOLL upper"),
        PlotSpec("boll_mid", "price", "line", "BOLL mid"),
        PlotSpec("boll_lower", "price", "line", "BOLL lower"),
    )
    params: BollParams

    def warmup_bars(self) -> int:
        return self.params.period + 1

    def indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        return BOLL(bars["close"], self.params.period, self.params.width)

    def signals(self, bars: pd.DataFrame, ind: pd.DataFrame) -> pd.Series:
        c = bars["close"]
        if self.params.mode == "breakout":
            return events(CROSS(c, ind["boll_upper"]), CROSS(ind["boll_mid"], c))
        return events(CROSS(c, ind["boll_lower"]), CROSS(c, ind["boll_mid"]))


class DonchianParams(StrategyParams):
    entry: int = Field(20, ge=2, le=400, description="Breakout lookback (highest high)")
    exit: int = Field(10, ge=2, le=400, description="Exit lookback (lowest low)")


@register
class DonchianStrategy(Strategy):
    name = "donchian"
    title = "Donchian channel breakout"
    description = (
        "Turtle-style: buy when the close breaks the prior N-bar high, sell when it breaks "
        "the prior M-bar low."
    )
    Params = DonchianParams
    plots = (
        PlotSpec("upper", "price", "line", "Upper channel"),
        PlotSpec("lower", "price", "line", "Lower channel"),
    )
    params: DonchianParams

    def warmup_bars(self) -> int:
        return max(self.params.entry, self.params.exit) + 1

    def indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        return pd.DataFrame(
            {
                "upper": REF(HHV(bars["high"], p.entry), 1),
                "lower": REF(LLV(bars["low"], p.exit), 1),
            },
            index=bars.index,
        )

    def signals(self, bars: pd.DataFrame, ind: pd.DataFrame) -> pd.Series:
        c = bars["close"]
        return events(c > ind["upper"], c < ind["lower"])
