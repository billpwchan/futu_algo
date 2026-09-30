"""Session-anchored intraday resampling.

Bars are grouped in N-minute chunks counted from the start of each trading session, and a
chunk never spans the lunch break. With Futu's end-labelled HK 60-minute bars
(10:30, 11:30, 12:00, 14:00, 15:00, 16:00):

* ``120M`` gives 11:30, 12:00, 15:00, 16:00;
* ``240M`` gives one morning bar (12:00) and one afternoon bar (16:00).

This reproduces the intent of the original hand-written HK 2H/4H buckets, but works for any
minute multiple and for the US session too. The HK 09:30 opening-auction bar joins the first
chunk; bars stamped after the session end (closing auction) join the last chunk.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from futu_algo.data.schema import BAR_COLUMNS
from futu_algo.errors import DataError
from futu_algo.market.instrument import MarketSpec
from futu_algo.timeframe import Timeframe


def _minutes(t: object) -> int:
    return t.hour * 60 + t.minute  # type: ignore[attr-defined]


def session_labels(index: pd.DatetimeIndex, minutes: int, market: MarketSpec) -> pd.DatetimeIndex:
    """End-label of the ``minutes``-long session chunk each end-labelled bar belongs to."""
    starts = np.array([_minutes(s) for s, _ in market.sessions])
    ends = np.array([_minutes(e) for _, e in market.sessions])
    local = index.tz_convert(market.tz) if index.tz is not None else index.tz_localize(market.tz)
    end_min = (local.hour * 60 + local.minute).to_numpy()
    sess = np.clip(np.searchsorted(starts, end_min, side="left") - 1, 0, len(starts) - 1)
    s_start = starts[sess]
    s_end = ends[sess]
    s_len = s_end - s_start
    offset = np.minimum(end_min, s_end) - s_start
    chunk = np.maximum(np.ceil(offset / minutes).astype(int) - 1, 0)
    n_chunks = np.ceil(s_len / minutes).astype(int)
    chunk = np.minimum(chunk, n_chunks - 1)
    label_min = s_start + np.minimum((chunk + 1) * minutes, s_len)
    day = local.normalize()
    return pd.DatetimeIndex(day + pd.to_timedelta(label_min, unit="min"), name="time")


def resample_bars(
    bars: pd.DataFrame, source: Timeframe, target: Timeframe, market: MarketSpec
) -> pd.DataFrame:
    if not (source.is_intraday and target.is_intraday):
        raise DataError(f"Can only resample intraday bars, got {source} -> {target}")
    if target.minutes % source.minutes:
        raise DataError(f"{target} is not a multiple of {source}")
    if bars.empty or target.minutes == source.minutes:
        return bars
    labels = session_labels(pd.DatetimeIndex(bars.index), target.minutes, market)
    grouped = bars.groupby(labels, sort=True)
    out = pd.DataFrame(
        {
            "open": grouped["open"].first(),
            "high": grouped["high"].max(),
            "low": grouped["low"].min(),
            "close": grouped["close"].last(),
            "volume": grouped["volume"].sum(),
            "turnover": grouped["turnover"].sum(min_count=1),
        }
    )
    out.index.name = "time"
    return out.loc[:, list(BAR_COLUMNS)]
