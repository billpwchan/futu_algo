"""Historical daily FX rates used to report backtests in HKD."""

from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import pandas as pd

from futu_algo.errors import DataError

_RATE_URL = "https://api.frankfurter.app"
_PAIR = "USD_HKD"


def load_usd_hkd_rates(
    start: date, end: date, cache_root: str | Path, *, offline: bool = False
) -> pd.Series:
    """Return daily HKD per USD reference rates, using a local cache when possible.

    FX observations are daily, so callers should apply the last observation strictly before
    each market date. The ten-day lead supplies a prior business-day observation after holidays.
    """
    path = Path(cache_root) / "fx" / f"{_PAIR}.json"
    payload: dict[str, object] = {"rates": {}, "coverage": []}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = {**payload, **loaded}
        except (OSError, json.JSONDecodeError):
            pass
    rates = payload.get("rates")
    rates = dict(rates) if isinstance(rates, dict) else {}
    coverage = payload.get("coverage")
    coverage = list(coverage) if isinstance(coverage, list) else []
    query_start = start - timedelta(days=10)
    covered = any(
        isinstance(row, list) and len(row) == 2
        and str(row[0]) <= query_start.isoformat() and str(row[1]) >= end.isoformat()
        for row in coverage
    )

    if not covered and not offline:
        url = f"{_RATE_URL}/{query_start.isoformat()}..{end.isoformat()}?from=USD&to=HKD"
        request = Request(url, headers={"User-Agent": "futu-algo/2.1"})
        try:
            with urlopen(request, timeout=15) as response:
                fetched = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise DataError(
                f"Could not download historical USD/HKD rates from {_RATE_URL}: {exc}. "
                f"Check network access or populate the FX cache at {path}."
            ) from exc
        fetched_rates = fetched.get("rates", {}) if isinstance(fetched, dict) else {}
        if not isinstance(fetched_rates, dict) or not fetched_rates:
            raise DataError(f"No historical USD/HKD rates returned for {query_start}..{end}")
        normalized: dict[str, float] = {}
        try:
            for day, value in fetched_rates.items():
                if not isinstance(value, dict) or "HKD" not in value:
                    continue
                rate = float(value["HKD"])
                if math.isfinite(rate) and rate > 0:
                    normalized[str(day)] = rate
        except (TypeError, ValueError) as exc:
            raise DataError(f"Invalid historical USD/HKD rates returned for {query_start}..{end}") from exc
        if not normalized:
            raise DataError(f"No valid historical USD/HKD rates returned for {query_start}..{end}")
        rates.update(normalized)
        coverage.append([query_start.isoformat(), end.isoformat()])
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"rates": rates, "coverage": coverage}, handle, indent=2)
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    try:
        series = pd.Series({pd.Timestamp(day): float(value) for day, value in rates.items()}, dtype=float)
        series = series.sort_index()
    except (TypeError, ValueError) as exc:
        raise DataError(f"The USD/HKD FX cache at {path} is invalid: {exc}") from exc
    series = series.loc[(series.index.date >= query_start) & (series.index.date <= end)]
    if series.empty:
        raise DataError(
            f"No cached historical USD/HKD rates cover {query_start}..{end}. "
            "Run the backtest with network access to fetch them."
        )
    return series


def prior_rate(rate_series: pd.Series, market_date: date) -> float:
    """Get the most recent FX fixing strictly before market_date, preventing look-ahead."""
    pos = int(rate_series.index.searchsorted(pd.Timestamp(market_date), side="left")) - 1
    if pos < 0:
        raise DataError(f"No prior USD/HKD rate is available for {market_date}")
    observed = rate_series.index[pos].date()
    age = (market_date - observed).days
    rate = float(rate_series.iloc[pos])
    if age > 7 or not math.isfinite(rate) or rate <= 0:
        raise DataError(f"USD/HKD rate for {market_date} is missing or stale (last rate {observed})")
    return rate
