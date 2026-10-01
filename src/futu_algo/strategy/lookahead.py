"""Detect future functions by recomputing on truncated history.

For a causal strategy, the indicator and signal values at bar t are identical whether they
are computed on bars[0..t] or on the full series. Any difference means the value at t used
bars after t (a 未来函数 such as TDX ZIG, a negative shift, a centred window, a full-sample
normalisation, ...). The check is cheap enough to run on every backtest.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from futu_algo.strategy.base import Strategy


@dataclass
class LookaheadReport:
    checked_bars: list[pd.Timestamp] = field(default_factory=list)
    mismatches: list[dict[str, object]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.mismatches

    def summary(self) -> str:
        if self.ok:
            return f"no look-ahead detected at {len(self.checked_bars)} checkpoints"
        cols = sorted({str(m["column"]) for m in self.mismatches})
        return (
            f"look-ahead detected: values at {len({m['time'] for m in self.mismatches})} of "
            f"{len(self.checked_bars)} checkpoints change when later bars are added "
            f"(columns: {', '.join(cols)})"
        )


def _same(a: object, b: object, rtol: float) -> bool:
    try:
        fa, fb = float(a), float(b)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return a == b
    if np.isnan(fa) and np.isnan(fb):
        return True
    return bool(np.isclose(fa, fb, rtol=rtol, atol=1e-10))


def check_lookahead(
    strategy: Strategy, bars: pd.DataFrame, checkpoints: int = 8, rtol: float = 1e-7
) -> LookaheadReport:
    report = LookaheadReport()
    n = len(bars)
    first = min(max(strategy.warmup_bars(), 2), n - 1)
    if n - first < 3:
        return report
    full_ind, full_sig = strategy.run(bars)
    positions = np.unique(
        np.linspace(first, n - 2, num=min(checkpoints, n - first - 1)).astype(int)
    )
    for pos in positions:
        ind, sig = strategy.run(bars.iloc[: pos + 1])
        t = bars.index[pos]
        report.checked_bars.append(t)
        if not _same(sig.iat[-1], full_sig.iat[pos], rtol):
            report.mismatches.append(
                {"time": t, "column": "signal", "truncated": sig.iat[-1], "full": full_sig.iat[pos]}
            )
        for col in full_ind.columns:
            if col not in ind.columns:
                continue
            if not _same(ind[col].iat[-1], full_ind[col].iat[pos], rtol):
                report.mismatches.append(
                    {
                        "time": t,
                        "column": col,
                        "truncated": ind[col].iat[-1],
                        "full": full_ind[col].iat[pos],
                    }
                )
    return report
