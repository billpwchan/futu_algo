"""Minimum price increments (spread tables).

Used by the backtester to express slippage in ticks and by the live order manager to round
limit prices to a price the exchange accepts. HKEX narrowed its spread table in two steps
(2025-08-04 for the HK$10-50 bands, 2026-08-03 for the HK$0.50-10 band); the trade date
decides which table applies. US equities trade in cents above $1 and 1/100 cent below.
"""

from __future__ import annotations

import bisect
import math
from datetime import date
from typing import Literal

from futu_algo.market.instrument import Instrument

# (upper price bound inclusive, tick size) bands; the first band whose bound >= price applies.
_HK_BASE: tuple[tuple[float, float], ...] = (
    (0.25, 0.001),
    (0.50, 0.005),
    (10.00, 0.010),
    (20.00, 0.020),
    (100.00, 0.050),
    (200.00, 0.100),
    (500.00, 0.200),
    (1000.00, 0.500),
    (2000.00, 1.000),
    (5000.00, 2.000),
    (float("inf"), 5.000),
)
_HK_2025: tuple[tuple[float, float], ...] = (
    (0.25, 0.001),
    (0.50, 0.005),
    (10.00, 0.010),
    (20.00, 0.010),
    (50.00, 0.020),
    (100.00, 0.050),
    (200.00, 0.100),
    (500.00, 0.200),
    (1000.00, 0.500),
    (2000.00, 1.000),
    (5000.00, 2.000),
    (float("inf"), 5.000),
)
_HK_2026: tuple[tuple[float, float], ...] = (
    (0.25, 0.001),
    (0.50, 0.005),
    (10.00, 0.005),
    *_HK_2025[3:],
)
HK_SPREAD_TABLES: tuple[tuple[date, tuple[tuple[float, float], ...]], ...] = (
    (date(1990, 1, 1), _HK_BASE),
    (date(2025, 8, 4), _HK_2025),
    (date(2026, 8, 3), _HK_2026),
)


def hk_tick_size(price: float, when: date) -> float:
    idx = bisect.bisect_right([d for d, _ in HK_SPREAD_TABLES], when) - 1
    table = HK_SPREAD_TABLES[max(idx, 0)][1]
    for bound, tick in table:
        if price <= bound + 1e-12:
            return tick
    return table[-1][1]


def us_tick_size(price: float) -> float:
    return 0.01 if price >= 1.0 else 0.0001


def tick_size(price: float, instrument: Instrument, when: date) -> float:
    if instrument.market.code == "HK":
        return hk_tick_size(price, when)
    return us_tick_size(price)


def round_to_tick(
    price: float, instrument: Instrument, when: date, direction: Literal["up", "down", "nearest"]
) -> float:
    """Round ``price`` onto the exchange's price grid.

    Buys round *up* and sells round *down* so an aggressive limit never ends up less
    aggressive than intended. The tick is looked up at the rounded side of a band boundary.
    """
    if price <= 0:
        return price
    tick = tick_size(price, instrument, when)
    steps = price / tick
    if direction == "up":
        n = math.ceil(steps - 1e-9)
    elif direction == "down":
        n = math.floor(steps + 1e-9)
    else:
        n = round(steps)
    decimals = max(0, -math.floor(math.log10(tick))) + 1
    return round(n * tick, decimals)


def shift_ticks(price: float, ticks: int, instrument: Instrument, when: date) -> float:
    """Move ``price`` by ``ticks`` exchange ticks (positive = up), crossing bands correctly."""
    out = price
    for _ in range(abs(ticks)):
        if ticks > 0:
            # The tick of the band just above the current price applies when moving up.
            out += tick_size(out + 1e-9, instrument, when)
        else:
            out -= tick_size(max(out - 1e-9, 0.0), instrument, when)
    return round(max(out, 0.0), 6)
