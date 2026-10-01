"""Stock screener.

Two stages:

1. **Server side (Futu ``get_stock_filter``)**. Price, liquidity, valuation, financial and
   technical-pattern filters (MA/EMA alignment, MACD/KDJ/RSI crosses, BOLL breaks, custom
   indicator comparisons) run on Futu's servers over the whole HK market. This costs no
   historical K-line quota, which matters: screening 2,600 stocks by downloading their bars
   would exhaust a 100-300 symbol quota in one run.
2. **Local confirmation (optional)**. The best ``max_confirm`` candidates are checked with a
   futu_algo strategy on cached daily bars ("keep only stocks whose MACD strategy is long
   today"). This uses quota for symbols not fetched in the current window, and is capped.

Results are saved as JSON and CSV and published on the event bus for notification.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from futu_algo.config import ScreenFilter, ScreenPreset
from futu_algo.data.manager import DataManager
from futu_algo.errors import ConfigError, DataError
from futu_algo.events import SCREENER, EventBus
from futu_algo.futu_gateway import QuoteGateway
from futu_algo.strategy.registry import create_strategy
from futu_algo.timeframe import Timeframe

log = logging.getLogger(__name__)
PAGE = 200
SNAPSHOT_BATCH = 400


@dataclass
class ScreenResult:
    preset: str
    run_at: str
    description: str
    rows: list[dict[str, Any]]
    matched: int  # candidates returned by Futu before the result cap
    confirmed_with: str | None = None
    warnings: list[str] = field(default_factory=list)
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _field(name: str) -> str:
    from futu import StockField

    key = name.strip().upper()
    if key not in StockField.get_all_key_list():
        raise ConfigError(f"Unknown Futu StockField {name!r}")
    return key


def build_futu_filter(spec: ScreenFilter) -> Any:
    """Translate a config filter into the futu-api filter object."""
    import futu

    sort = {"asc": futu.SortDir.ASCEND, "desc": futu.SortDir.DESCEND}.get(spec.sort or "")
    kind = spec.kind
    if kind in ("simple", "accumulate", "financial"):
        cls = {"simple": futu.SimpleFilter, "accumulate": futu.AccumulateFilter, "financial": futu.FinancialFilter}[kind]
        f = cls()
        f.stock_field = _field(spec.field)
        f.filter_min = spec.min
        f.filter_max = spec.max
        f.is_no_filter = spec.min is None and spec.max is None
        if sort:
            f.sort = sort
        if kind == "accumulate":
            f.days = spec.days or 1
        if kind == "financial":
            f.quarter = (spec.quarter or "ANNUAL").upper()
        return f
    if kind == "pattern":
        f = futu.PatternFilter()
        f.stock_field = _field(spec.field)
        f.ktype = (spec.ktype or "K_DAY").upper()
        f.is_no_filter = False
        if spec.consecutive_period:
            f.consecutive_period = spec.consecutive_period
        return f
    f = futu.CustomIndicatorFilter()
    f.stock_field1 = _field(spec.field)
    f.stock_field2 = _field(spec.field2 or "VALUE")
    f.relative_position = spec.relative_position or "MORE"
    if spec.value is not None:
        f.value = spec.value
    f.ktype = (spec.ktype or "K_DAY").upper()
    f.stock_field1_para = list(spec.field1_params)
    f.stock_field2_para = list(spec.field2_params)
    f.is_no_filter = False
    if spec.consecutive_period:
        f.consecutive_period = spec.consecutive_period
    return f


def _clean(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "item"):
        try:
            return _clean(value.item())
        except (ValueError, AttributeError):
            return value
    return value


class Screener:
    def __init__(self, gateway: QuoteGateway, data: DataManager | None, bus: EventBus | None, results_dir: Path) -> None:
        self.gateway = gateway
        self.data = data
        self.bus = bus
        self.results_dir = results_dir

    # ----------------------------------------------------------------- stage 1

    def _server_screen(self, preset: ScreenPreset) -> tuple[list[dict[str, Any]], int]:
        filters = [(spec, build_futu_filter(spec)) for spec in preset.filters]
        objs = [f for _, f in filters]
        rows: list[dict[str, Any]] = []
        begin, total = 0, 0
        while True:
            def page(ctx: Any, begin: int = begin) -> tuple[Any, ...]:
                return ctx.get_stock_filter(
                    market=preset.market, filter_list=objs, plate_code=preset.plate, begin=begin, num=PAGE
                )

            _, (last_page, total, items) = self.gateway.call(
                "stock_filter", f"get_stock_filter({preset.market}, begin={begin})", page
            )
            for item in items:
                row: dict[str, Any] = {"symbol": item.stock_code, "name": item.stock_name}
                for spec, obj in filters:
                    if spec.kind in ("simple", "accumulate", "financial"):
                        with contextlib.suppress(KeyError, AttributeError):
                            row[spec.field.lower()] = _clean(item[obj])
                rows.append(row)
            begin += PAGE
            if last_page or begin >= total or len(rows) >= preset.max_results:
                break
        return rows[: preset.max_results], int(total)

    def _enrich(self, rows: list[dict[str, Any]]) -> None:
        codes = [r["symbol"] for r in rows]
        snap: dict[str, dict[str, Any]] = {}
        for i in range(0, len(codes), SNAPSHOT_BATCH):
            batch = codes[i : i + SNAPSHOT_BATCH]
            def snapshot(ctx: Any, b: list[str] = batch) -> tuple[Any, ...]:
                return ctx.get_market_snapshot(b)

            try:
                _, data = self.gateway.call("snapshot", "get_market_snapshot", snapshot)
            except Exception as exc:
                log.warning("Snapshot for screener results failed: %s", exc)
                continue
            for rec in data.to_dict("records"):
                snap[str(rec["code"])] = rec
        for row in rows:
            rec = snap.get(row["symbol"])
            if not rec:
                continue
            last, prev = rec.get("last_price"), rec.get("prev_close_price")
            row.update(
                {
                    "last_price": _clean(last),
                    "change_pct": _clean((last / prev - 1) * 100) if last and prev else None,
                    "turnover_today": _clean(rec.get("turnover")),
                    "volume_today": _clean(rec.get("volume")),
                    "lot_size": _clean(rec.get("lot_size")),
                    "market_cap": _clean(rec.get("total_market_val")),
                    "pe_ttm": _clean(rec.get("pe_ttm_ratio")),
                }
            )

    # ----------------------------------------------------------------- stage 2

    def _confirm(self, preset: ScreenPreset, rows: list[dict[str, Any]], warnings: list[str]) -> list[dict[str, Any]]:
        spec = preset.confirm_strategy
        if spec is None:
            return rows
        if self.data is None:
            warnings.append("confirmation skipped: no data manager")
            return rows
        strategy = create_strategy(spec.name, spec.params)
        tf = Timeframe.parse(preset.confirm_timeframe)
        end = date.today()
        start = end - timedelta(days=preset.confirm_lookback_days)
        kept: list[dict[str, Any]] = []
        for row in rows[: preset.max_confirm]:
            sym = row["symbol"]
            try:
                bars = self.data.load_bars(sym, tf, start, end, warmup_bars=strategy.warmup_bars())
            except DataError as exc:
                warnings.append(f"{sym}: {exc}")
                continue
            if len(bars) <= strategy.warmup_bars():
                continue
            _, sig = strategy.run(bars)
            last = sig.dropna()
            state = float(last.iloc[-1]) if len(last) else math.nan
            fired_today = bool(len(sig) and sig.iloc[-1] == 1.0)
            if state == 1.0:
                row["signal"] = "buy today" if fired_today else "long"
                row["signal_since"] = last.index[-1].date().isoformat() if len(last) else None
                kept.append(row)
        if len(rows) > preset.max_confirm:
            warnings.append(f"only the first {preset.max_confirm} of {len(rows)} candidates were confirmed (max_confirm)")
        return kept

    # --------------------------------------------------------------------- run

    def run(self, name: str, preset: ScreenPreset, *, notify: bool = False) -> ScreenResult:
        started = datetime.now(UTC)
        warnings: list[str] = []
        rows, matched = self._server_screen(preset)
        self._enrich(rows)
        rows = self._confirm(preset, rows, warnings)
        result = ScreenResult(
            preset=name,
            run_at=started.isoformat(timespec="seconds"),
            description=preset.description,
            rows=rows,
            matched=matched,
            confirmed_with=preset.confirm_strategy.name if preset.confirm_strategy else None,
            warnings=warnings,
        )
        result.path = str(self.save(result))
        if self.bus is not None:
            self.bus.emit(
                SCREENER,
                f"Screener {name}: {len(rows)} stock(s) ({matched} matched on Futu)",
                preset=name,
                count=len(rows),
                notify=notify,
                result=result.to_dict(),
            )
        return result

    def save(self, result: ScreenResult) -> Path:
        self.results_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        base = self.results_dir / f"{stamp}_{re.sub(r'[^A-Za-z0-9_-]+', '_', result.preset)}"
        base.with_suffix(".json").write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        pd.DataFrame(result.rows).to_csv(base.with_suffix(".csv"), index=False, encoding="utf-8-sig")
        return base.with_suffix(".json")


def list_results(results_dir: Path, limit: int = 50) -> list[dict[str, Any]]:
    out = []
    for path in sorted(results_dir.glob("*.json"), reverse=True)[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append({"id": path.stem, "preset": data.get("preset"), "run_at": data.get("run_at"), "count": len(data.get("rows", [])), "matched": data.get("matched")})
    return out


def load_result(results_dir: Path, result_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", result_id):
        raise FileNotFoundError(result_id)
    path = results_dir / f"{result_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))
