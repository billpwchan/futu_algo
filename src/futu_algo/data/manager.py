"""Cache-first access to bars and instrument metadata.

The manager only asks Futu for date ranges the cache has not seen, never caches a bar whose
period is still in progress, and, for adjusted prices, re-downloads the whole series when an
overlapping bar no longer matches: a new dividend or split changes every earlier
forward-adjusted price, and mixing old and new adjustments would silently corrupt returns.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd

from futu_algo.data.resample import resample_bars
from futu_algo.data.schema import empty_bars, validate_bars
from futu_algo.data.source import DataSource, QuotaStatus
from futu_algo.data.store import Coverage, InstrumentInfo, ParquetStore, SeriesKey
from futu_algo.errors import DataError, QuotaExceededError
from futu_algo.market.instrument import MARKETS, Instrument, parse_symbol
from futu_algo.timeframe import Timeframe

log = logging.getLogger(__name__)

OVERLAP_DAYS = {"K_WEEK": 21, "K_MON": 62}


def last_complete_date(ktype: str, today: date) -> date:
    """Latest date whose bars of ``ktype`` are final, given today's exchange-local date."""
    if ktype == "K_WEEK":
        return today - timedelta(days=today.weekday() + 1)
    if ktype == "K_MON":
        return today.replace(day=1) - timedelta(days=1)
    return today - timedelta(days=1)


def _market_today(tz: str) -> date:
    return pd.Timestamp.now(tz=tz).date()


class DataManager:
    def __init__(
        self,
        store: ParquetStore,
        source_factory: Callable[[], DataSource] | None = None,
        *,
        adjust: str = "qfq",
        offline: bool = False,
        instrument_ttl_days: int = 7,
        today: Callable[[str], date] = _market_today,
    ) -> None:
        self.store = store
        self._source_factory = source_factory
        self._source: DataSource | None = None
        self.adjust = adjust
        self.offline = offline or source_factory is None
        self.instrument_ttl_days = instrument_ttl_days
        self._today = today
        self._quota: QuotaStatus | None = None
        self._quota_checked = False
        self.warnings: list[str] = []

    # ------------------------------------------------------------- plumbing

    @property
    def source(self) -> DataSource:
        if self._source is None:
            if self._source_factory is None:
                raise DataError("No data source configured (offline mode)")
            self._source = self._source_factory()
        return self._source

    def close(self) -> None:
        if self._source is not None:
            self._source.close()
            self._source = None

    def __enter__(self) -> DataManager:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _warn(self, message: str) -> None:
        log.warning(message)
        if message not in self.warnings:
            self.warnings.append(message)

    def quota(self) -> QuotaStatus | None:
        if not self._quota_checked:
            self._quota_checked = True
            self._quota = self.source.quota()
            if self._quota is not None:
                log.info(
                    "Futu history K-line quota: %d used, %d remaining",
                    self._quota.used,
                    self._quota.remaining,
                )
        return self._quota

    def _reserve_quota(self, symbol: str) -> None:
        status = self.quota()
        if status is None or symbol in status.codes:
            return
        if status.remaining <= 0:
            raise QuotaExceededError(
                f"Fetching {symbol} needs one more history K-line quota slot but none remain "
                f"({status.used} used). Re-requesting symbols already fetched in the current "
                "window is free; wait for the quota window to reset or use cached data (offline mode)."
            )
        status.codes.add(symbol)
        status.remaining -= 1
        status.used += 1

    # ------------------------------------------------------------------ bars

    def ensure(self, key: SeriesKey, start: date, end: date) -> pd.DataFrame:
        """Return cached bars for [start, end] (local dates), fetching what is missing."""
        tz = MARKETS[key.market].tz
        end_cap = min(end, last_complete_date(key.ktype, self._today(tz)))
        cached = self.store.read(key)
        cov = self.store.coverage(key) if cached is not None else None
        if start > end_cap:
            return self._slice(cached, start, end, tz)
        if cov is not None and cov.contains(start, end_cap):
            return self._slice(cached, start, end, tz)
        if self.offline:
            if cached is None or cov is None:
                raise DataError(
                    f"{key.symbol} {key.ktype} ({key.adjust}) is not in the local cache "
                    f"({self.store.root}). Run `futu-algo data fetch` with OpenD running, or disable offline mode."
                )
            self._warn(
                f"{key.symbol} {key.ktype}: cache covers {cov.start}..{cov.end}, requested "
                f"{start}..{end_cap}; offline mode uses the cached part only"
            )
            return self._slice(cached, start, end, tz)

        # Each incremental fetch overlaps the cache by a few periods so the adjusted-price
        # consistency check always has trading days to compare, even across holidays.
        overlap = timedelta(days=OVERLAP_DAYS.get(key.ktype, 10))
        ranges: list[tuple[date, date]] = []
        if cov is None:
            ranges.append((start, end_cap))
        else:
            if start < cov.start:
                ranges.append((start, min(cov.start + overlap, cov.end)))
            if end_cap > cov.end:
                ranges.append((max(cov.end - overlap, cov.start), end_cap))

        self._reserve_quota(key.symbol)
        fetched = [
            self.source.fetch_bars(key.symbol, key.ktype, key.adjust, a, b) for a, b in ranges
        ]
        merged, consistent = self._merge(cached, fetched, check=key.adjust != "none")
        coverage = cov.union(start, end_cap) if cov is not None else Coverage(start, end_cap)
        if not consistent:
            self._warn(
                f"{key.symbol}: {key.adjust} prices changed since they were cached (new corporate "
                f"action); re-downloaded {coverage.start}..{coverage.end}"
            )
            merged = self.source.fetch_bars(
                key.symbol, key.ktype, key.adjust, coverage.start, coverage.end
            )
        for problem in validate_bars(merged):
            self._warn(f"{key.symbol} {key.ktype}: {problem}")
        self.store.write(key, merged, coverage, self.source.name)
        return self._slice(merged, start, end, tz)

    @staticmethod
    def _merge(
        cached: pd.DataFrame | None, fetched: list[pd.DataFrame], *, check: bool
    ) -> tuple[pd.DataFrame, bool]:
        parts = [f for f in fetched if f is not None and len(f)]
        consistent = True
        if cached is not None and len(cached) and check:
            for part in parts:
                common = cached.index.intersection(part.index)
                if len(common) and not np.allclose(
                    cached.loc[common, "close"].to_numpy(),
                    part.loc[common, "close"].to_numpy(),
                    rtol=1e-6,
                    atol=1e-9,
                    equal_nan=True,
                ):
                    consistent = False
        frames = ([cached] if cached is not None and len(cached) else []) + parts
        if not frames:
            first = pd.DatetimeIndex(fetched[0].index) if fetched else None
            tz = str(first.tz) if first is not None and first.tz else "UTC"
            return empty_bars(tz), consistent
        merged = pd.concat(frames)
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        return merged, consistent

    @staticmethod
    def _slice(bars: pd.DataFrame | None, start: date, end: date, tz: str) -> pd.DataFrame:
        if bars is None:
            return empty_bars(tz)
        dates = pd.DatetimeIndex(bars.index).tz_convert(tz).date
        mask = (dates >= start) & (dates <= end)
        return bars.loc[mask]

    def load_bars(
        self, symbol: str, timeframe: Timeframe, start: date, end: date, *, warmup_bars: int = 0
    ) -> pd.DataFrame:
        """Bars from ``warmup_bars`` before ``start`` through ``end`` at ``timeframe``."""
        market = MARKETS[parse_symbol(symbol)[0]]
        base = timeframe.base
        lookback = timeframe.calendar_days_for(warmup_bars, market)
        # Resampled bars need warmup in *target* bars, which the calendar estimate already covers.
        fetch_start = start - timedelta(days=lookback)
        bars = self.ensure(SeriesKey(symbol, base.futu_ktype, self.adjust), fetch_start, end)
        if not timeframe.is_native:
            bars = resample_bars(bars, base, timeframe, market)
        return bars

    # ----------------------------------------------------------- instruments

    def instruments(
        self, symbols: list[str], lot_overrides: dict[str, int] | None = None
    ) -> dict[str, Instrument]:
        overrides = lot_overrides or {}
        cached = self.store.read_instruments()
        now = datetime.now(UTC)

        def stale(info: InstrumentInfo | None) -> bool:
            if info is None:
                return True
            updated = datetime.fromisoformat(info.updated_at)
            return now - updated > timedelta(days=self.instrument_ttl_days)

        need = [s for s in symbols if stale(cached.get(s))]
        if need and not self.offline:
            fetched = self.source.fetch_instruments(need)
            if fetched:
                self.store.write_instruments(fetched)
                cached.update(fetched)

        out: dict[str, Instrument] = {}
        for sym in symbols:
            info = cached.get(sym)
            market = parse_symbol(sym)[0]
            lot = overrides.get(sym) or (info.lot_size if info else None)
            if lot is None:
                if market == "US":
                    lot = 1
                else:
                    raise DataError(
                        f"Board lot for {sym} is unknown (not cached and offline). "
                        f"Set lot_sizes.{sym} in the config or fetch with OpenD running."
                    )
            out[sym] = Instrument(
                symbol=sym,
                lot_size=int(lot),
                name=info.name if info else "",
                security_type=info.security_type if info else "STOCK",
            )
        return out
