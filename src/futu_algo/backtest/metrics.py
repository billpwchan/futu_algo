"""Performance metrics.

Definitions (r = per-bar returns of the equity curve, the first bar measured against the
initial capital; P = bars per year):

* Periods per year P is measured from the data (bars / elapsed years) when the test spans at
  least three months, otherwise taken from the timeframe and market calendar. This keeps
  intraday and daily results comparable without a hard-coded 252.
* CAGR uses elapsed calendar time: (final / initial) ** (365.25 / days) - 1.
* Volatility = std(r, ddof=1) * sqrt(P).
* Sharpe = (mean(r) - rf/P) / std(r) * sqrt(P).
* Sortino = (mean(r) - rf/P) * P / (sqrt(mean(min(r - rf/P, 0)^2)) * sqrt(P)), i.e. the
  downside deviation is taken over *all* bars, not only losing ones.
* Max drawdown is measured from the running peak including the initial capital; its duration
  runs from the peak to full recovery (or to the end if never recovered).
* VaR/CVaR 95% are historical, per bar.
* Beta/alpha/correlation/information ratio are against the benchmark's per-bar returns on the
  same timestamps.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:  # runtime import would cycle: engine.runner imports this module
    from futu_algo.backtest.types import Book, Trade


def _nan() -> float:
    return float("nan")


def bar_returns(equity: pd.Series, initial: float) -> pd.Series:
    prev = equity.shift(1)
    prev.iloc[0] = initial
    return equity / prev - 1.0


def elapsed_years(index: pd.DatetimeIndex) -> float:
    if len(index) < 2:
        return 0.0
    return (index[-1] - index[0]).total_seconds() / (365.25 * 86400)


def periods_per_year(index: pd.DatetimeIndex, fallback: float) -> float:
    years = elapsed_years(index)
    if years >= 0.25 and len(index) > 1:
        return (len(index) - 1) / years
    return fallback


def drawdown(equity: pd.Series, initial: float) -> pd.Series:
    peak = np.maximum.accumulate(np.maximum(equity.to_numpy(float), initial))
    return pd.Series(equity.to_numpy(float) / peak - 1.0, index=equity.index)


def drawdown_periods(equity: pd.Series, initial: float, top: int = 5) -> list[dict[str, Any]]:
    """The ``top`` deepest peak-to-recovery episodes."""
    values = equity.to_numpy(float)
    index = equity.index
    peak_val = initial
    peak_i = -1
    episodes: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for i, v in enumerate(values):
        if v >= peak_val:
            if current is not None:
                current["end"] = index[i]
                current["bars"] = i - current["_start_i"]
                episodes.append(current)
                current = None
            peak_val, peak_i = v, i
            continue
        depth = v / peak_val - 1
        if current is None:
            current = {
                "start": index[peak_i] if peak_i >= 0 else index[0],
                "_start_i": max(peak_i, 0),
                "trough": index[i],
                "depth": depth,
                "end": None,
            }
        elif depth < current["depth"]:
            current["depth"] = depth
            current["trough"] = index[i]
    if current is not None:
        current["bars"] = len(values) - 1 - current["_start_i"]
        episodes.append(current)
    for ep in episodes:
        ep.pop("_start_i", None)
        end = ep["end"] if ep["end"] is not None else index[-1]
        ep["days"] = (end - ep["start"]).total_seconds() / 86400
        ep["recovered"] = ep["end"] is not None
    episodes.sort(key=lambda e: e["depth"])
    return episodes[:top]


def monthly_returns(equity: pd.Series, initial: float) -> pd.DataFrame:
    """Year x month table of compounded returns, plus a ``year`` column."""
    if equity.empty:
        return pd.DataFrame()
    local = equity.copy()
    index = pd.DatetimeIndex(local.index)
    local.index = index.tz_localize(None) if index.tz is not None else index
    month_end = local.resample("ME").last().dropna()
    prev = month_end.shift(1)
    prev.iloc[0] = initial
    rets = month_end / prev - 1
    month_index = pd.DatetimeIndex(rets.index)
    table = pd.DataFrame(
        {"year": month_index.year, "month": month_index.month, "ret": rets.to_numpy()}
    )
    pivot = table.pivot(index="year", columns="month", values="ret").reindex(columns=range(1, 13))
    year_end = local.resample("YE").last().dropna()
    prev_y = year_end.shift(1)
    prev_y.iloc[0] = initial
    pivot["year"] = (year_end / prev_y - 1).to_numpy()
    return pivot


def trade_stats(trades: list[Trade]) -> dict[str, Any]:
    closed = [t for t in trades if not t.is_open]
    open_ = [t for t in trades if t.is_open]
    pnls = np.array([t.pnl for t in closed], dtype=float)
    rets = np.array([t.return_pct for t in closed], dtype=float)
    wins, losses = pnls[pnls > 0], pnls[pnls < 0]
    streak_w = streak_l = best_w = best_l = 0
    for p in pnls:
        if p > 0:
            streak_w, streak_l = streak_w + 1, 0
        elif p < 0:
            streak_w, streak_l = 0, streak_l + 1
        else:
            streak_w = streak_l = 0
        best_w, best_l = max(best_w, streak_w), max(best_l, streak_l)
    bars = [t.bars_held for t in closed if t.bars_held is not None]
    days = [t.days_held for t in closed if t.days_held is not None]
    gross_win, gross_loss = float(wins.sum()), float(-losses.sum())
    return {
        "trades": len(closed),
        "open_trades": len(open_),
        "win_rate": float(len(wins) / len(closed)) if closed else _nan(),
        "profit_factor": gross_win / gross_loss
        if gross_loss > 0
        else (math.inf if gross_win > 0 else _nan()),
        "expectancy": float(pnls.mean()) if len(pnls) else _nan(),
        "avg_trade_return": float(rets.mean()) if len(rets) else _nan(),
        "avg_win": float(wins.mean()) if len(wins) else _nan(),
        "avg_loss": float(losses.mean()) if len(losses) else _nan(),
        "payoff_ratio": float(wins.mean() / -losses.mean())
        if len(wins) and len(losses)
        else _nan(),
        "largest_win": float(pnls.max()) if len(pnls) else _nan(),
        "largest_loss": float(pnls.min()) if len(pnls) else _nan(),
        "max_consecutive_wins": best_w,
        "max_consecutive_losses": best_l,
        "avg_bars_held": float(np.mean(bars)) if bars else _nan(),
        "avg_days_held": float(np.mean(days)) if days else _nan(),
        "realized_pnl": float(pnls.sum()),
        "unrealized_pnl": float(sum(t.pnl for t in open_)),
        "exit_reasons": dict(Counter(t.exit_reason or "open" for t in trades if not t.is_open)),
    }


def return_metrics(
    equity: pd.Series,
    initial: float,
    *,
    fallback_ppy: float,
    risk_free_rate: float = 0.0,
) -> dict[str, float]:
    if equity.empty:
        return {}
    r = bar_returns(equity, initial)
    ppy = periods_per_year(pd.DatetimeIndex(equity.index), fallback_ppy)
    years = elapsed_years(pd.DatetimeIndex(equity.index))
    final = float(equity.iloc[-1])
    total = final / initial - 1
    rf = risk_free_rate / ppy
    std = float(r.std(ddof=1)) if len(r) > 1 else _nan()
    mean = float(r.mean())
    downside = float(np.sqrt(np.mean(np.minimum(r.to_numpy() - rf, 0.0) ** 2)))
    dd = drawdown(equity, initial)
    max_dd = float(dd.min())
    cagr = (final / initial) ** (1 / years) - 1 if years > 1 / 365.25 and final > 0 else _nan()
    var95 = float(np.quantile(r, 0.05))
    tail = r[r <= var95]
    periods = drawdown_periods(equity, initial, top=1)
    return {
        "start_equity": initial,
        "final_equity": final,
        "total_return": total,
        "cagr": cagr,
        "volatility": std * math.sqrt(ppy) if std == std else _nan(),
        "sharpe": (mean - rf) / std * math.sqrt(ppy) if std and std == std and std > 0 else _nan(),
        "sortino": (mean - rf) * ppy / (downside * math.sqrt(ppy)) if downside > 0 else _nan(),
        "max_drawdown": max_dd,
        "max_drawdown_days": periods[0]["days"] if periods else 0.0,
        "max_drawdown_bars": periods[0]["bars"] if periods else 0,
        "calmar": cagr / abs(max_dd) if max_dd < 0 and cagr == cagr else _nan(),
        "var_95": var95,
        "cvar_95": float(tail.mean()) if len(tail) else _nan(),
        "best_bar": float(r.max()),
        "worst_bar": float(r.min()),
        "periods_per_year": ppy,
        "years": years,
        "bars": len(equity),
    }


def align_series(
    series: pd.Series, index: pd.DatetimeIndex, initial: float, *, rebase: bool = False
) -> pd.Series:
    """Sample ``series`` at ``index``: the last value at or before each point, compared in UTC
    so different exchange timezones line up. Points before the series starts take ``initial``.
    With ``rebase``, the result is scaled to equal ``initial`` at the first point, so a
    benchmark is measured over exactly the same span as the equity curve.
    """
    src = series.dropna().sort_index()
    src_utc = pd.Series(src.to_numpy(float), index=pd.DatetimeIndex(src.index).tz_convert("UTC"))
    src_utc = src_utc[~src_utc.index.duplicated(keep="last")]
    target = pd.DatetimeIndex(index).tz_convert("UTC")
    aligned = src_utc.reindex(src_utc.index.union(target)).ffill().reindex(target)
    aligned.index = index
    if rebase:
        first = aligned.first_valid_index()
        if first is not None:
            aligned = aligned / float(aligned.loc[first]) * initial
    return aligned.fillna(initial)


def benchmark_metrics(
    equity: pd.Series, bench: pd.Series, initial: float, *, fallback_ppy: float
) -> dict[str, float]:
    if bench.dropna().empty:
        return {}
    aligned = align_series(bench, pd.DatetimeIndex(equity.index), initial)
    r = bar_returns(equity, initial)
    rb = bar_returns(aligned, initial)
    ppy = periods_per_year(pd.DatetimeIndex(equity.index), fallback_ppy)
    years = elapsed_years(pd.DatetimeIndex(equity.index))
    var_b = float(rb.var(ddof=1)) if len(rb) > 1 else _nan()
    beta = float(r.cov(rb) / var_b) if var_b and var_b > 0 else _nan()
    active = r - rb
    te = float(active.std(ddof=1))
    b_final = float(aligned.iloc[-1])
    return {
        "benchmark_total_return": b_final / initial - 1,
        "benchmark_cagr": (b_final / initial) ** (1 / years) - 1
        if years > 1 / 365.25 and b_final > 0
        else _nan(),
        "benchmark_max_drawdown": float(drawdown(aligned, initial).min()),
        "excess_return": float(equity.iloc[-1] / initial - b_final / initial),
        "beta": beta,
        "alpha": float((r.mean() - beta * rb.mean()) * ppy) if beta == beta else _nan(),
        "correlation": float(r.corr(rb)) if r.std() > 0 and rb.std() > 0 else _nan(),
        "tracking_error": te * math.sqrt(ppy) if te == te else _nan(),
        "information_ratio": float(active.mean() / te * math.sqrt(ppy))
        if te and te > 0
        else _nan(),
    }


def book_metrics(book: Book, *, fallback_ppy: float, risk_free_rate: float = 0.0) -> dict[str, Any]:
    m: dict[str, Any] = return_metrics(
        book.equity, book.initial_capital, fallback_ppy=fallback_ppy, risk_free_rate=risk_free_rate
    )
    if not m:
        return m
    years = max(m["years"], 1e-9)
    traded = sum(f.value for f in book.fills)
    fees = book.total_fees
    m.update(
        {
            "exposure": float(book.exposure.mean()) if len(book.exposure) else _nan(),
            "time_in_market": float((book.exposure > 0).mean()) if len(book.exposure) else _nan(),
            "turnover": traded / float(book.equity.mean()) / years if years > 0.01 else _nan(),
            "total_fees": fees,
            "fees_pct_of_capital": fees / book.initial_capital,
            "fills": len(book.fills),
        }
    )
    m.update(trade_stats(book.trades))
    if book.benchmark is not None:
        m.update(
            benchmark_metrics(
                book.equity, book.benchmark, book.initial_capital, fallback_ppy=fallback_ppy
            )
        )
    if book.buy_hold is not None:
        bh_final = float(
            align_series(
                book.buy_hold, pd.DatetimeIndex(book.equity.index), book.initial_capital
            ).iloc[-1]
        )
        m["buy_hold_return"] = bh_final / book.initial_capital - 1
    return m
