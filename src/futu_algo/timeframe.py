"""Bar timeframes and their mapping onto Futu K-line types.

Futu serves 1/3/5/15/30/60-minute, daily, weekly and monthly K-lines. Any other minute
multiple (e.g. ``120M`` / ``2H``, ``240M`` / ``4H``, ``10M``) is built locally from the largest
native divisor with session-aware resampling (see :mod:`futu_algo.data.resample`).

String conventions follow the old CLI and Futu: ``1M`` = one minute, ``MON`` = one month.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

from futu_algo.errors import ConfigError
from futu_algo.market.instrument import MarketSpec

Unit = Literal["min", "day", "week", "month"]

NATIVE_MINUTES: tuple[int, ...] = (1, 3, 5, 15, 30, 60)

_MINUTE_RE = re.compile(r"^(\d+)\s*(M|MIN|MINS|MINUTE|MINUTES|T)$")
_HOUR_RE = re.compile(r"^(\d+)\s*(H|HR|HOUR|HOURS)$")


@dataclass(frozen=True)
class Timeframe:
    unit: Unit
    minutes: int = 0

    @classmethod
    def parse(cls, value: str | Timeframe) -> Timeframe:
        if isinstance(value, Timeframe):
            return value
        text = str(value).strip().upper()
        if text in {"DAY", "D", "1D", "DAILY", "K_DAY"}:
            return cls("day")
        if text in {"WEEK", "W", "1W", "WEEKLY", "K_WEEK"}:
            return cls("week")
        if text in {"MON", "MONTH", "1MO", "MONTHLY", "K_MON"}:
            return cls("month")
        if text.startswith("K_") and text.endswith("M"):
            text = text[2:]
        if m := _MINUTE_RE.match(text):
            minutes = int(m.group(1))
        elif m := _HOUR_RE.match(text):
            minutes = int(m.group(1)) * 60
        else:
            raise ConfigError(
                f"Unknown timeframe {value!r}; use e.g. 1M, 5M, 60M, 2H, 4H, DAY, WEEK or MON"
            )
        if minutes <= 0 or minutes > 24 * 60:
            raise ConfigError(f"Timeframe {value!r} out of range")
        return cls("min", minutes)

    def __str__(self) -> str:
        if self.unit == "min":
            return f"{self.minutes}M"
        return {"day": "DAY", "week": "WEEK", "month": "MON"}[self.unit]

    @property
    def is_intraday(self) -> bool:
        return self.unit == "min"

    @property
    def is_native(self) -> bool:
        return not self.is_intraday or self.minutes in NATIVE_MINUTES

    @property
    def base(self) -> Timeframe:
        """The native timeframe that is fetched from Futu to build this one."""
        if self.is_native:
            return self
        divisor = max(n for n in NATIVE_MINUTES if self.minutes % n == 0)
        return Timeframe("min", divisor)

    @property
    def futu_ktype(self) -> str:
        if not self.is_native:
            raise ConfigError(f"{self} is not a native Futu K-line type; fetch {self.base} instead")
        if self.is_intraday:
            return f"K_{self.minutes}M"
        return {"day": "K_DAY", "week": "K_WEEK", "month": "K_MON"}[self.unit]

    def bars_per_year(self, market: MarketSpec) -> float:
        days = market.trading_days_per_year
        if self.unit == "day":
            return float(days)
        if self.unit == "week":
            return 52.0
        if self.unit == "month":
            return 12.0
        return float(days * market.bars_per_day(self.minutes))

    def calendar_days_for(self, bars: int, market: MarketSpec) -> int:
        """Generous calendar-day lookback that contains at least ``bars`` bars."""
        if bars <= 0:
            return 0
        if self.unit == "day":
            trading_days = bars
        elif self.unit == "week":
            return math.ceil(bars * 7 * 1.1) + 14
        elif self.unit == "month":
            return math.ceil(bars * 31 * 1.05) + 31
        else:
            trading_days = math.ceil(bars / market.bars_per_day(self.minutes))
        # ~252 trading days per 365 calendar days, plus room for holidays and suspensions.
        return math.ceil(trading_days * 365 / 240) + 10
