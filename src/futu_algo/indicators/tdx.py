"""通达信 (TDX) formula functions with TDX semantics.

Names follow TDX so formulas port line by line::

    DIF := EMA(CLOSE, 12) - EMA(CLOSE, 26)     ->  dif = EMA(c, 12) - EMA(c, 26)
    K   := SMA(RSV, 3, 1)                      ->  k = SMA(rsv, 3, 1)

Semantics worth knowing:

* ``MA`` is a simple moving average that is undefined (NaN) until N bars exist.
* ``EMA(X, N)`` uses alpha = 2/(N+1), seeded with the first value (pandas ``adjust=False``).
* ``SMA(X, N, M)`` is TDX's *recursive* smoothing Y = (M*X + (N-M)*Y') / N, **not** a simple
  average. KDJ, RSI and many TDX formulas depend on it; porting it as a rolling mean (as the
  old LEG port did with ``talib.SMA``) gives different numbers.
* ``ZIG`` is a future function: its last leg is redrawn when price reverses by N%. It is
  provided for charting and for reproducing TDX's (inflated) backtests; strategies should use
  :func:`point_in_time` to evaluate it as it would have looked at each bar.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

Series = pd.Series


def _s(x: Series | float, like: Series) -> Series:
    return x if isinstance(x, pd.Series) else pd.Series(float(x), index=like.index)


def _bool(x: Series) -> Series:
    if x.dtype == bool:
        return x
    return x.astype("boolean").fillna(False).astype(bool)


def REF(x: Series, n: int = 1) -> Series:
    return x.shift(n)


def MA(x: Series, n: int) -> Series:
    return x.rolling(n, min_periods=n).mean()


def EMA(x: Series, n: int) -> Series:
    return x.ewm(span=n, adjust=False).mean()


def SMA(x: Series, n: int, m: int = 1) -> Series:
    if not 0 < m <= n:
        raise ValueError(f"SMA requires 0 < M <= N, got N={n}, M={m}")
    return x.ewm(alpha=m / n, adjust=False).mean()


def WMA(x: Series, n: int) -> Series:
    weights = np.arange(1, n + 1, dtype=float)
    return x.rolling(n, min_periods=n).apply(lambda w: np.dot(w, weights) / weights.sum(), raw=True)


def HHV(x: Series, n: int) -> Series:
    return x.expanding().max() if n == 0 else x.rolling(n, min_periods=n).max()


def LLV(x: Series, n: int) -> Series:
    return x.expanding().min() if n == 0 else x.rolling(n, min_periods=n).min()


def SUM(x: Series, n: int) -> Series:
    return x.cumsum() if n == 0 else x.rolling(n, min_periods=n).sum()


def COUNT(cond: Series, n: int) -> Series:
    return SUM(cond.astype(float), n)


def STD(x: Series, n: int) -> Series:
    return x.rolling(n, min_periods=n).std(ddof=1)


def ABS(x: Series) -> Series:
    return x.abs()


def MAX(a: Series | float, b: Series | float) -> Series:
    like = a if isinstance(a, pd.Series) else b
    assert isinstance(like, pd.Series)
    return pd.concat([_s(a, like), _s(b, like)], axis=1).max(axis=1, skipna=False)


def MIN(a: Series | float, b: Series | float) -> Series:
    like = a if isinstance(a, pd.Series) else b
    assert isinstance(like, pd.Series)
    return pd.concat([_s(a, like), _s(b, like)], axis=1).min(axis=1, skipna=False)


def IF(cond: Series, a: Series | float, b: Series | float) -> Series:
    like = cond
    return pd.Series(np.where(_bool(cond), _s(a, like), _s(b, like)), index=cond.index)


def CROSS(a: Series | float, b: Series | float) -> Series:
    """True on the bar where ``a`` moves from <= ``b`` to > ``b``."""
    like = a if isinstance(a, pd.Series) else b
    assert isinstance(like, pd.Series)
    a_, b_ = _s(a, like), _s(b, like)
    return _bool((a_ > b_) & (a_.shift(1) <= b_.shift(1)))


def BARSLAST(cond: Series) -> Series:
    """Bars since ``cond`` was last true (0 on the bar itself); NaN before the first true."""
    flags = _bool(cond).to_numpy(dtype=bool)
    out = np.full(len(flags), np.nan)
    last = -1
    for i, flag in enumerate(flags):
        if flag:
            last = i
        if last >= 0:
            out[i] = i - last
    return pd.Series(out, index=cond.index)


def EVERY(cond: Series, n: int) -> Series:
    return COUNT(cond, n) == n


def EXIST(cond: Series, n: int) -> Series:
    return COUNT(cond, n) > 0


# ---------------------------------------------------------------- indicators


def MACD(close: Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """TDX MACD: DIF, DEA and the histogram MACD = 2 * (DIF - DEA)."""
    dif = EMA(close, fast) - EMA(close, slow)
    dea = EMA(dif, signal)
    return pd.DataFrame({"dif": dif, "dea": dea, "macd": 2 * (dif - dea)}, index=close.index)


def KDJ(
    high: Series, low: Series, close: Series, n: int = 9, m1: int = 3, m2: int = 3
) -> pd.DataFrame:
    llv, hhv = LLV(low, n), HHV(high, n)
    rsv = (close - llv) / (hhv - llv).replace(0.0, np.nan) * 100
    k = SMA(rsv, m1, 1)
    d = SMA(k, m2, 1)
    return pd.DataFrame({"k": k, "d": d, "j": 3 * k - 2 * d}, index=close.index)


def RSI(close: Series, n: int = 6) -> Series:
    lc = REF(close, 1)
    up = SMA(MAX(close - lc, 0.0), n, 1)
    total = SMA(ABS(close - lc), n, 1)
    return up / total.replace(0.0, np.nan) * 100


def DMI(high: Series, low: Series, close: Series, n: int = 14, m: int = 6) -> pd.DataFrame:
    """TDX DMI: PDI, MDI, ADX, ADXR."""
    lc = REF(close, 1)
    tr = MAX(MAX(high - low, ABS(high - lc)), ABS(lc - low))
    mtr = SUM(tr, n)
    hd = high - REF(high, 1)
    ld = REF(low, 1) - low
    dmp = SUM(IF((hd > 0) & (hd > ld), hd, 0.0), n)
    dmm = SUM(IF((ld > 0) & (ld > hd), ld, 0.0), n)
    pdi = dmp * 100 / mtr
    mdi = dmm * 100 / mtr
    adx = MA(ABS(mdi - pdi) / (mdi + pdi) * 100, m)
    adxr = (adx + REF(adx, m)) / 2
    return pd.DataFrame({"pdi": pdi, "mdi": mdi, "adx": adx, "adxr": adxr}, index=close.index)


# ---------------------------------------------------------------------- ZIG


def zig_pivots(values: np.ndarray, pct: float) -> list[int]:
    """Indices of zigzag vertices for a reversal threshold of ``pct`` percent.

    The first bar and the last bar are always vertices. The running extreme of the
    unfinished leg is a vertex too, which is why the drawing changes as new bars arrive.
    """
    n = len(values)
    if n == 0:
        return []
    t = pct / 100.0
    pivots = [0]
    trend = 0
    ext = 0
    for i in range(1, n):
        x = values[i]
        if np.isnan(x):
            continue
        if trend == 0:
            if x >= values[0] * (1 + t):
                trend, ext = 1, i
            elif x <= values[0] * (1 - t):
                trend, ext = -1, i
        elif trend == 1:
            if x >= values[ext]:
                ext = i
            elif x <= values[ext] * (1 - t):
                pivots.append(ext)
                trend, ext = -1, i
        else:
            if x <= values[ext]:
                ext = i
            elif x >= values[ext] * (1 + t):
                pivots.append(ext)
                trend, ext = 1, i
    if trend != 0 and ext != pivots[-1]:
        pivots.append(ext)
    if pivots[-1] != n - 1:
        pivots.append(n - 1)
    return pivots


def ZIG(x: Series, pct: float) -> Series:
    """TDX-style ZIG(3, N) on ``x``: straight lines between zigzag vertices.

    WARNING: uses future data. Value at bar i depends on bars after i.
    """
    values = x.to_numpy(dtype=float)
    pivots = zig_pivots(values, pct)
    if not pivots:
        return pd.Series(dtype=float, index=x.index)
    out = np.interp(np.arange(len(values)), pivots, values[pivots])
    return pd.Series(out, index=x.index)


def point_in_time(
    fn: Callable[[pd.DataFrame], Series],
    frame: pd.DataFrame,
    window: int,
    *,
    min_bars: int = 2,
) -> Series:
    """Evaluate ``fn`` as it would have been seen live: value[i] = fn(frame[i-window+1 : i+1])[-1].

    This turns any repainting formula (ZIG, peak/trough detectors, centred smoothing) into a
    causal series, at O(n * window) cost. ``fn`` receives a window of the frame and returns a
    Series aligned to it; only its last value is kept.
    """
    n = len(frame)
    out = np.full(n, np.nan)
    for i in range(min_bars - 1, n):
        lo = max(0, i - window + 1)
        result = fn(frame.iloc[lo : i + 1])
        out[i] = float(result.iloc[-1]) if len(result) else np.nan
    return pd.Series(out, index=frame.index)


def BOLL(close: Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    """Bollinger bands as TDX draws them: MA(N) +/- K * population standard deviation."""
    mid = MA(close, n)
    dev = close.rolling(n, min_periods=n).std(ddof=0)
    return pd.DataFrame(
        {"boll_mid": mid, "boll_upper": mid + k * dev, "boll_lower": mid - k * dev},
        index=close.index,
    )


def ATR(high: Series, low: Series, close: Series, n: int = 14) -> Series:
    """Average true range: simple mean of the true range over N bars (TDX ``ATR``)."""
    lc = REF(close, 1)
    tr = MAX(MAX(high - low, ABS(high - lc)), ABS(lc - low))
    return MA(tr, n)
