"""Local Parquet cache for bars and instrument metadata.

Layout under the data directory::

    bars/<KTYPE>/<adjust>/<MARKET>/<code>.parquet   bar frame (canonical schema)
    bars/<KTYPE>/<adjust>/<MARKET>/<code>.json      coverage metadata
    instruments.json                                lot size, name, type per symbol

``coverage`` is the inclusive date range that has been *requested and fully received* from
the source. It is tracked separately from the first/last bar because a range can legitimately
contain no bars (holidays, before listing), and re-asking Futu for it would waste requests.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from futu_algo.data.schema import BAR_COLUMNS
from futu_algo.market.instrument import parse_symbol


@dataclass(frozen=True)
class SeriesKey:
    symbol: str
    ktype: str
    adjust: str

    @property
    def market(self) -> str:
        return parse_symbol(self.symbol)[0]

    @property
    def code(self) -> str:
        return parse_symbol(self.symbol)[1]


@dataclass(frozen=True)
class Coverage:
    start: date
    end: date

    def contains(self, start: date, end: date) -> bool:
        return self.start <= start and end <= self.end

    def union(self, start: date, end: date) -> Coverage:
        return Coverage(min(self.start, start), max(self.end, end))


@dataclass(frozen=True)
class InstrumentInfo:
    symbol: str
    name: str
    lot_size: int
    security_type: str
    listing_date: str | None
    updated_at: str


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class ParquetStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------------ bars

    def _paths(self, key: SeriesKey) -> tuple[Path, Path]:
        base = self.root / "bars" / key.ktype / key.adjust / key.market
        return base / f"{key.code}.parquet", base / f"{key.code}.json"

    def read_meta(self, key: SeriesKey) -> dict[str, Any] | None:
        _, meta_path = self._paths(key)
        if not meta_path.exists():
            return None
        return json.loads(meta_path.read_text(encoding="utf-8"))

    def coverage(self, key: SeriesKey) -> Coverage | None:
        meta = self.read_meta(key)
        if not meta or not meta.get("coverage"):
            return None
        start, end = meta["coverage"]
        return Coverage(date.fromisoformat(start), date.fromisoformat(end))

    def read(self, key: SeriesKey) -> pd.DataFrame | None:
        data_path, _ = self._paths(key)
        if not data_path.exists():
            return None
        frame = pd.read_parquet(data_path)
        frame.index.name = "time"
        return frame.loc[:, list(BAR_COLUMNS)]

    def write(self, key: SeriesKey, bars: pd.DataFrame, coverage: Coverage, source: str) -> None:
        data_path, meta_path = self._paths(key)
        data_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = data_path.with_suffix(".parquet.tmp")
        bars.loc[:, list(BAR_COLUMNS)].to_parquet(tmp)
        os.replace(tmp, data_path)
        meta = {
            "symbol": key.symbol,
            "ktype": key.ktype,
            "adjust": key.adjust,
            "coverage": [coverage.start.isoformat(), coverage.end.isoformat()],
            "rows": len(bars),
            "first_bar": bars.index[0].isoformat() if len(bars) else None,
            "last_bar": bars.index[-1].isoformat() if len(bars) else None,
            "source": source,
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        _atomic_write_bytes(meta_path, json.dumps(meta, indent=2).encode("utf-8"))

    def list_series(self) -> list[dict[str, Any]]:
        out = []
        for meta_path in sorted((self.root / "bars").glob("*/*/*/*.json")):
            try:
                out.append(json.loads(meta_path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
        return out

    # ----------------------------------------------------------- instruments

    @property
    def _instruments_path(self) -> Path:
        return self.root / "instruments.json"

    def read_instruments(self) -> dict[str, InstrumentInfo]:
        path = self._instruments_path
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {sym: InstrumentInfo(**info) for sym, info in raw.items()}

    def write_instruments(self, infos: dict[str, InstrumentInfo]) -> None:
        current = self.read_instruments()
        current.update(infos)
        payload = {sym: asdict(info) for sym, info in sorted(current.items())}
        _atomic_write_bytes(
            self._instruments_path,
            json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"),
        )
