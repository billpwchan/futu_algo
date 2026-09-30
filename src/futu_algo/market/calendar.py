"""Trading sessions and the trading-day calendar.

``session_phase`` answers "what is the market doing right now" from the wall clock, which is
what the live engine needs to decide whether it may send orders. Trading days come from Futu
(``request_trading_days``) when OpenD is reachable; otherwise weekdays are assumed, which is
wrong on public holidays but only means the engine idles through a closed day.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import StrEnum

import pandas as pd

from futu_algo.market.instrument import MarketSpec

log = logging.getLogger(__name__)


class Phase(StrEnum):
    CLOSED = "closed"  # not a trading day, or outside all sessions
    PRE_OPEN = "pre_open"  # opening auction (HK 09:00-09:30)
    CONTINUOUS = "continuous"  # continuous trading session
    LUNCH = "lunch"  # between the morning and afternoon sessions
    CLOSING_AUCTION = "closing_auction"  # HK closing auction (16:00-16:10)
    AFTER_HOURS = "after_hours"  # trading day, after the close


def _within(t: time, window: tuple[time, time]) -> bool:
    return window[0] <= t < window[1]


def session_phase(now: datetime, market: MarketSpec, is_trading_day: bool = True) -> Phase:
    """Market phase at ``now`` (any tz-aware datetime; converted to exchange time)."""
    if not is_trading_day:
        return Phase.CLOSED
    stamp = pd.Timestamp(now)
    local = stamp.tz_convert(market.tz) if stamp.tzinfo else stamp
    t = local.time()
    for window in market.sessions:
        if _within(t, window):
            return Phase.CONTINUOUS
    if market.pre_open and _within(t, market.pre_open):
        return Phase.PRE_OPEN
    if market.closing_auction and _within(t, market.closing_auction):
        return Phase.CLOSING_AUCTION
    if market.sessions[0][1] <= t < market.sessions[-1][0]:
        return Phase.LUNCH
    if t >= market.close_time:
        return Phase.AFTER_HOURS
    return Phase.CLOSED


def minutes_to_close(now: datetime, market: MarketSpec) -> float:
    local = pd.Timestamp(now).tz_convert(market.tz)
    close = local.normalize() + pd.Timedelta(
        hours=market.close_time.hour, minutes=market.close_time.minute
    )
    return (close - local).total_seconds() / 60


@dataclass
class TradingCalendar:
    """Trading days for one market, with an optional Futu-backed loader."""

    market: MarketSpec
    loader: Callable[[date, date], Iterable[date]] | None = None
    _days: set[date] = field(default_factory=set)
    _loaded: tuple[date, date] | None = None

    def _ensure(self, day: date) -> None:
        if self.loader is None:
            return
        if self._loaded and self._loaded[0] <= day <= self._loaded[1]:
            return
        start, end = day - timedelta(days=45), day + timedelta(days=45)
        try:
            self._days |= set(self.loader(start, end))
            lo = min(start, self._loaded[0]) if self._loaded else start
            hi = max(end, self._loaded[1]) if self._loaded else end
            self._loaded = (lo, hi)
        except Exception as exc:  # calendar is best effort; weekdays are the fallback
            log.warning("Could not load %s trading days: %s", self.market.code, exc)
            self.loader = None

    def is_trading_day(self, day: date) -> bool:
        self._ensure(day)
        if self._loaded and self._loaded[0] <= day <= self._loaded[1]:
            return day in self._days
        return day.weekday() < 5

    def phase(self, now: datetime) -> Phase:
        local = pd.Timestamp(now).tz_convert(self.market.tz)
        return session_phase(now, self.market, self.is_trading_day(local.date()))

    def next_trading_day(self, day: date) -> date:
        probe = day + timedelta(days=1)
        for _ in range(30):
            if self.is_trading_day(probe):
                return probe
            probe += timedelta(days=1)
        return probe

    def previous_trading_day(self, day: date) -> date:
        probe = day - timedelta(days=1)
        for _ in range(30):
            if self.is_trading_day(probe):
                return probe
            probe -= timedelta(days=1)
        return probe
