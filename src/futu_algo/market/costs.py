"""Transaction cost models.

HK costs are modelled line by line with dated schedules, because several statutory rates
changed inside a typical backtest window:

* Stamp duty: 0.13% from 2021-08-01 to 2023-11-16, 0.1% otherwise; rounded *up* to the next
  whole HK dollar; ETFs exempt (since 2015-02-13).
* HKEX trading fee: 0.005% plus a HK$0.50 per-trade tariff before 2023-01-01, 0.00565% after.
* SFC levy 0.0027%; AFRC levy 0.00015% from 2022-01-01.
* HKEX stock settlement fee: 0.002% (min HK$2, max HK$100) before 2025-06-30, 0.0042% flat after.

Broker fees default to Futu HK's fixed plan (0.03% commission with a HK$3 minimum, HK$15
platform fee per order) and are configurable, e.g. set ``commission_rate: 0`` during a
zero-commission promotion.

US costs follow Futu's per-share plan plus the sell-side SEC Section 31 fee and FINRA TAF.
Historical SEC/TAF rates before 2023 are approximated with the nearest known rate; their
effect is far below one basis point.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from futu_algo.market.instrument import Instrument

Side = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class FeeBreakdown:
    commission: float = 0.0
    platform: float = 0.0
    stamp_duty: float = 0.0
    exchange: float = 0.0
    levies: float = 0.0
    settlement: float = 0.0

    @property
    def total(self) -> float:
        return (
            self.commission
            + self.platform
            + self.stamp_duty
            + self.exchange
            + self.levies
            + self.settlement
        )

    def __add__(self, other: FeeBreakdown) -> FeeBreakdown:
        return FeeBreakdown(
            commission=self.commission + other.commission,
            platform=self.platform + other.platform,
            stamp_duty=self.stamp_duty + other.stamp_duty,
            exchange=self.exchange + other.exchange,
            levies=self.levies + other.levies,
            settlement=self.settlement + other.settlement,
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "commission": self.commission,
            "platform": self.platform,
            "stamp_duty": self.stamp_duty,
            "exchange": self.exchange,
            "levies": self.levies,
            "settlement": self.settlement,
            "total": self.total,
        }


class CostModel(Protocol):
    def fees(
        self, side: Side, quantity: int, price: float, instrument: Instrument, when: date
    ) -> FeeBreakdown: ...

    def describe(self) -> dict[str, object]: ...


def _cents(value: float) -> float:
    """Round a regulatory fee to the cent, with a one-cent floor for any non-zero charge."""
    if value <= 0:
        return 0.0
    return max(0.01, math.floor(value * 100 + 0.5) / 100)


# --------------------------------------------------------------------------- HK


@dataclass(frozen=True)
class HKStatutoryRates:
    effective: date
    stamp_duty: float
    trading_fee: float
    trading_tariff: float
    sfc_levy: float
    afrc_levy: float
    settlement_rate: float
    settlement_min: float
    settlement_max: float | None


HK_STATUTORY_SCHEDULE: tuple[HKStatutoryRates, ...] = (
    HKStatutoryRates(date(1990, 1, 1), 0.001, 0.00005, 0.5, 0.000027, 0.0, 0.00002, 2.0, 100.0),
    HKStatutoryRates(date(2021, 8, 1), 0.0013, 0.00005, 0.5, 0.000027, 0.0, 0.00002, 2.0, 100.0),
    HKStatutoryRates(
        date(2022, 1, 1), 0.0013, 0.00005, 0.5, 0.000027, 0.0000015, 0.00002, 2.0, 100.0
    ),
    HKStatutoryRates(
        date(2023, 1, 1), 0.0013, 0.0000565, 0.0, 0.000027, 0.0000015, 0.00002, 2.0, 100.0
    ),
    HKStatutoryRates(
        date(2023, 11, 17), 0.001, 0.0000565, 0.0, 0.000027, 0.0000015, 0.00002, 2.0, 100.0
    ),
    HKStatutoryRates(
        date(2025, 6, 30), 0.001, 0.0000565, 0.0, 0.000027, 0.0000015, 0.000042, 0.0, None
    ),
)
_HK_DATES = [s.effective for s in HK_STATUTORY_SCHEDULE]
STAMP_DUTY_ETF_EXEMPT_FROM = date(2015, 2, 13)


def hk_statutory_rates(when: date) -> HKStatutoryRates:
    idx = bisect.bisect_right(_HK_DATES, when) - 1
    return HK_STATUTORY_SCHEDULE[max(idx, 0)]


class HKBrokerFees(BaseModel):
    """Broker-side HK charges. Defaults: Futu HK fixed plan."""

    model_config = ConfigDict(extra="forbid")

    commission_rate: float = Field(0.0003, ge=0)
    commission_min: float = Field(3.0, ge=0)
    platform_fee: float = Field(15.0, ge=0, description="Flat HKD per order")
    include_statutory: bool = True


class HKCostModel:
    def __init__(self, broker: HKBrokerFees | None = None) -> None:
        self.broker = broker or HKBrokerFees()

    def fees(
        self, side: Side, quantity: int, price: float, instrument: Instrument, when: date
    ) -> FeeBreakdown:
        if quantity <= 0:
            return FeeBreakdown()
        value = quantity * price
        b = self.broker
        commission = max(value * b.commission_rate, b.commission_min) if b.commission_rate else 0.0
        if not b.include_statutory:
            return FeeBreakdown(commission=round(commission, 2), platform=b.platform_fee)
        rates = hk_statutory_rates(when)
        exempt = instrument.security_type.upper() == "ETF" and when >= STAMP_DUTY_ETF_EXEMPT_FROM
        stamp = 0.0 if exempt else float(math.ceil(value * rates.stamp_duty - 1e-9))
        exchange = _cents(value * rates.trading_fee) + rates.trading_tariff
        levies = _cents(value * rates.sfc_levy) + _cents(value * rates.afrc_levy)
        settlement = value * rates.settlement_rate
        settlement = max(settlement, rates.settlement_min)
        if rates.settlement_max is not None:
            settlement = min(settlement, rates.settlement_max)
        return FeeBreakdown(
            commission=round(commission, 2),
            platform=b.platform_fee,
            stamp_duty=stamp,
            exchange=exchange,
            levies=levies,
            settlement=_cents(settlement),
        )

    def describe(self) -> dict[str, object]:
        return {"model": "hk", **self.broker.model_dump()}


# --------------------------------------------------------------------------- US

# (effective date, SEC Section 31 fee per dollar of sale proceeds)
US_SEC_FEE_SCHEDULE: tuple[tuple[date, float], ...] = (
    (date(1990, 1, 1), 22.90e-6),
    (date(2023, 5, 22), 8.00e-6),
    (date(2024, 5, 22), 27.80e-6),
    (date(2025, 5, 14), 0.0),
    (date(2026, 4, 4), 20.60e-6),
)
# (effective date, FINRA TAF per share sold, per-trade min, per-trade max)
US_TAF_SCHEDULE: tuple[tuple[date, float, float, float], ...] = (
    (date(1990, 1, 1), 0.000166, 0.01, 8.30),
    (date(2026, 1, 1), 0.000195, 0.01, 9.79),
    (date(2026, 10, 1), 0.0, 0.0, 0.0),
    (date(2027, 1, 1), 0.000195, 0.01, 9.79),
)


def _dated(schedule: Sequence[tuple[Any, ...]], when: date) -> tuple[Any, ...]:
    idx = bisect.bisect_right([row[0] for row in schedule], when) - 1
    return schedule[max(idx, 0)]


class USBrokerFees(BaseModel):
    """Broker-side US charges. Defaults: Futu per-share plan."""

    model_config = ConfigDict(extra="forbid")

    commission_per_share: float = Field(0.0049, ge=0)
    commission_min: float = Field(0.99, ge=0)
    platform_per_share: float = Field(0.005, ge=0)
    platform_min: float = Field(1.0, ge=0)
    max_pct_of_value: float | None = Field(
        0.005, ge=0, description="Cap on each of commission and platform fee"
    )
    settlement_per_share: float = Field(0.003, ge=0)
    include_regulatory: bool = True


class USCostModel:
    def __init__(self, broker: USBrokerFees | None = None) -> None:
        self.broker = broker or USBrokerFees()

    def fees(
        self, side: Side, quantity: int, price: float, instrument: Instrument, when: date
    ) -> FeeBreakdown:
        if quantity <= 0:
            return FeeBreakdown()
        b = self.broker
        value = quantity * price
        commission = max(quantity * b.commission_per_share, b.commission_min)
        platform = max(quantity * b.platform_per_share, b.platform_min)
        if b.max_pct_of_value is not None:
            cap = value * b.max_pct_of_value
            commission = min(commission, cap)
            platform = min(platform, cap)
        settlement = quantity * b.settlement_per_share
        levies = 0.0
        if b.include_regulatory and side == "SELL":
            _, sec_rate = _dated(US_SEC_FEE_SCHEDULE, when)
            _, taf_rate, taf_min, taf_max = _dated(US_TAF_SCHEDULE, when)
            sec = _cents(value * sec_rate) if sec_rate else 0.0
            taf = min(max(quantity * taf_rate, taf_min), taf_max) if taf_rate else 0.0
            levies = sec + round(taf, 2)
        return FeeBreakdown(
            commission=round(commission, 2),
            platform=round(platform, 2),
            levies=levies,
            settlement=round(settlement, 2),
        )

    def describe(self) -> dict[str, object]:
        return {"model": "us", **self.broker.model_dump()}


# --------------------------------------------------------------------------- simple


class SimpleCostModel:
    """Proportional commission with an optional per-order minimum; for quick comparisons."""

    def __init__(self, rate: float = 0.001, min_fee: float = 0.0) -> None:
        self.rate = rate
        self.min_fee = min_fee

    def fees(
        self, side: Side, quantity: int, price: float, instrument: Instrument, when: date
    ) -> FeeBreakdown:
        if quantity <= 0:
            return FeeBreakdown()
        return FeeBreakdown(commission=max(quantity * price * self.rate, self.min_fee))

    def describe(self) -> dict[str, object]:
        return {"model": "simple", "rate": self.rate, "min_fee": self.min_fee}


class MarketCostModel:
    """Dispatches to a per-market model based on the instrument."""

    def __init__(self, hk: CostModel, us: CostModel) -> None:
        self.by_market: dict[str, CostModel] = {"HK": hk, "US": us}

    def fees(
        self, side: Side, quantity: int, price: float, instrument: Instrument, when: date
    ) -> FeeBreakdown:
        return self.by_market[instrument.market.code].fees(side, quantity, price, instrument, when)

    def describe(self) -> dict[str, object]:
        return {market: model.describe() for market, model in self.by_market.items()}
