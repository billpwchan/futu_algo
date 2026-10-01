"""Canonical bar frame.

Every bar frame in the package has:

* a tz-aware ``DatetimeIndex`` named ``time`` in the exchange's timezone, sorted, unique;
* float columns ``open, high, low, close, volume, turnover``.

Intraday bars keep Futu's convention of labelling a bar by its *end* time (the HK 60-minute
bars are 10:30, 11:30, 12:00, 14:00, 15:00, 16:00). Daily and longer bars are labelled with
the trading date at midnight.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from futu_algo.errors import DataError

BAR_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume", "turnover")

_TIME_CANDIDATES = ("time_key", "time", "timestamp", "datetime", "date", "日期", "时间", "時間")
_ALIASES = {
    "open": ("open", "开盘", "開盤", "开盘价", "開盤價", "o"),
    "high": ("high", "最高", "最高价", "最高價", "h"),
    "low": ("low", "最低", "最低价", "最低價", "l"),
    "close": ("close", "收盘", "收盤", "收盘价", "收盤價", "c"),
    "volume": ("volume", "vol", "成交量", "v"),
    "turnover": ("turnover", "amount", "成交额", "成交額", "value"),
}


def empty_bars(tz: str) -> pd.DataFrame:
    index = pd.DatetimeIndex([], tz=tz, name="time")
    return pd.DataFrame({c: pd.Series(dtype="float64") for c in BAR_COLUMNS}, index=index)


def _find(columns: Iterable[str], candidates: Iterable[str]) -> str | None:
    lookup = {str(c).strip().lower(): c for c in columns}
    for cand in candidates:
        if cand.lower() in lookup:
            return lookup[cand.lower()]
    return None


def to_bars(raw: pd.DataFrame, tz: str) -> pd.DataFrame:
    """Normalize a Futu K-line frame (or a CSV/Parquet export) to the canonical schema.

    Naive timestamps are interpreted as exchange-local time, which is what Futu returns
    (HK time for HK, US Eastern for US).
    """
    if raw is None or len(raw) == 0:
        return empty_bars(tz)
    frame = raw
    if isinstance(frame.index, pd.DatetimeIndex) and _find(frame.columns, _TIME_CANDIDATES) is None:
        times = pd.DatetimeIndex(frame.index)
    else:
        time_col = _find(frame.columns, _TIME_CANDIDATES)
        if time_col is None:
            raise DataError(f"No time column found; expected one of {_TIME_CANDIDATES}")
        times = pd.DatetimeIndex(pd.to_datetime(frame[time_col]))
    times = times.tz_localize(tz) if times.tz is None else times.tz_convert(tz)

    data: dict[str, np.ndarray] = {}
    for col, aliases in _ALIASES.items():
        src = _find(frame.columns, aliases)
        if src is None:
            if col in ("volume", "turnover"):
                data[col] = np.full(len(frame), np.nan if col == "turnover" else 0.0)
                continue
            raise DataError(f"Missing required column {col!r} (accepted names: {aliases})")
        data[col] = pd.to_numeric(frame[src], errors="coerce").to_numpy(dtype="float64")

    bars = pd.DataFrame(data, index=pd.DatetimeIndex(times, name="time"))
    bars = bars[~bars.index.duplicated(keep="last")].sort_index()
    return bars.loc[:, list(BAR_COLUMNS)]


def validate_bars(bars: pd.DataFrame) -> list[str]:
    """Return human-readable data-quality warnings (does not modify the frame)."""
    problems: list[str] = []
    if bars.empty:
        return problems
    if not bars.index.is_monotonic_increasing or bars.index.has_duplicates:
        problems.append("timestamps are not strictly increasing")
    ohlc = bars[["open", "high", "low", "close"]]
    if (ohlc <= 0).any().any():
        problems.append(f"{int((ohlc <= 0).any(axis=1).sum())} bars with non-positive prices")
    if ohlc.isna().any().any():
        problems.append(f"{int(ohlc.isna().any(axis=1).sum())} bars with missing prices")
    if bars["volume"].isna().any():
        problems.append(
            f"{int(bars['volume'].isna().sum())} bars with missing volume (treated as 0 by volume caps)"
        )
    tol = 1e-9
    bad_high = bars["high"] + tol < bars[["open", "close"]].max(axis=1)
    bad_low = bars["low"] - tol > bars[["open", "close"]].min(axis=1)
    if bad_high.any() or bad_low.any():
        problems.append(
            f"{int((bad_high | bad_low).sum())} bars where high/low do not bound open/close"
        )
    return problems
