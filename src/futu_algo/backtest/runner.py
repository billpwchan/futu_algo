"""Run a configured backtest end to end and serialise the result.

Modes
-----
* ``portfolio``: all symbols share one cash balance; the sizer allocates it.
* ``scan``: every symbol is simulated alone with the full capital ("which stocks does this
  strategy work on"). The ``COMPOSITE`` book averages the symbol books.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from futu_algo.backtest.metrics import align_series, book_metrics, drawdown, drawdown_periods, monthly_returns
from futu_algo.backtest.simulator import (
    Simulator,
    SymbolFeed,
    bar_close_ns,
    buy_and_hold,
    display_index,
    is_intraday_index,
)
from futu_algo.backtest.types import Book
from futu_algo.config import AppConfig, BacktestConfig, CostsConfig
from futu_algo.data.manager import DataManager
from futu_algo.errors import DataError
from futu_algo.market.costs import (
    CostModel,
    HKCostModel,
    MarketCostModel,
    SimpleCostModel,
    USCostModel,
)
from futu_algo.market.instrument import Instrument
from futu_algo.strategy.base import PlotSpec, Strategy
from futu_algo.strategy.lookahead import LookaheadReport, check_lookahead
from futu_algo.strategy.registry import create_strategy, load_strategy_paths
from futu_algo.timeframe import Timeframe

log = logging.getLogger(__name__)

PORTFOLIO = "PORTFOLIO"
COMPOSITE = "COMPOSITE"
MAX_CURVE_POINTS = 3000
MAX_CHART_BARS = 5000


@dataclass
class SymbolView:
    instrument: Instrument
    bars: pd.DataFrame
    indicators: pd.DataFrame
    plots: tuple[PlotSpec, ...]


@dataclass
class BacktestResult:
    config: BacktestConfig
    strategy: dict[str, Any]
    books: dict[str, Book]
    primary: str
    symbols: dict[str, SymbolView]
    warnings: list[str] = field(default_factory=list)
    lookahead: LookaheadReport | None = None
    costs: dict[str, Any] = field(default_factory=dict)
    started_at: str = ""
    finished_at: str = ""

    @property
    def main(self) -> Book:
        return self.books[self.primary]

    def summary(self) -> pd.DataFrame:
        cols = [
            "total_return", "cagr", "sharpe", "sortino", "max_drawdown", "calmar", "trades",
            "win_rate", "profit_factor", "exposure", "total_fees", "buy_hold_return",
        ]
        rows = {name: {c: book.metrics.get(c) for c in cols} for name, book in self.books.items()}
        return pd.DataFrame.from_dict(rows, orient="index")


def build_cost_model(cfg: CostsConfig) -> CostModel:
    if cfg.model == "simple":
        return SimpleCostModel(cfg.simple.rate, cfg.simple.min_fee)
    return MarketCostModel(HKCostModel(cfg.hk), USCostModel(cfg.us))


def _window(bars: pd.DataFrame, tz: str, start: date, end: date) -> np.ndarray:
    dates = pd.DatetimeIndex(bars.index).tz_convert(tz).date
    return np.flatnonzero((dates >= start) & (dates <= end))


def make_feed(
    strategy: Strategy,
    bars: pd.DataFrame,
    instrument: Instrument,
    start: date,
    end: date,
    warnings: list[str],
) -> SymbolFeed | None:
    idx = _window(bars, instrument.tz, start, end)
    if len(idx) == 0:
        warnings.append(f"{instrument.symbol}: no bars between {start} and {end}; skipped")
        return None
    warmup = strategy.warmup_bars()
    first, last = max(int(idx[0]), warmup), int(idx[-1])
    if first > last:
        warnings.append(
            f"{instrument.symbol}: {len(bars)} bars are fewer than the {warmup}-bar warm-up; skipped"
        )
        return None
    if idx[0] < warmup:
        warnings.append(
            f"{instrument.symbol}: only {idx[0]} bars of history before {start}; trading starts "
            f"{bars.index[first].date()} after the {warmup}-bar warm-up"
        )
    trimmed = bars.iloc[: last + 1]
    ind, sig = strategy.run(trimmed)
    return SymbolFeed(instrument, trimmed, ind, sig.to_numpy(float), first, last)


def _by_date(series: pd.Series) -> pd.Series:
    local = pd.DatetimeIndex(series.index).tz_localize(None).normalize()
    out = pd.Series(series.to_numpy(), index=pd.DatetimeIndex(local, name="time").tz_localize("UTC"))
    return out[~out.index.duplicated(keep="last")]


def _composite(books: list[Book], name: str) -> Book:
    n = len(books)
    tzs = {str(pd.DatetimeIndex(b.equity.index).tz) for b in books}
    daily = not any(is_intraday_index(pd.DatetimeIndex(b.equity.index)) for b in books)
    key = _by_date if len(tzs) > 1 and daily else (lambda s: s)
    index = key(books[0].equity).index
    for b in books[1:]:
        index = index.union(key(b.equity).index)

    def avg(attr: str, fill: float | None) -> pd.Series:
        frames = []
        for b in books:
            s = key(getattr(b, attr)).reindex(index).ffill()
            frames.append(s.fillna(b.initial_capital if fill is None else fill))
        return pd.concat(frames, axis=1).mean(axis=1)

    comp = Book(
        name=name,
        currency=books[0].currency,
        initial_capital=books[0].initial_capital,
        equity=avg("equity", None),
        cash=avg("cash", None),
        exposure=avg("exposure", 0.0),
        fills=[f for b in books for f in b.fills],
        trades=sorted((t for b in books for t in b.trades), key=lambda t: t.entry_time),
        symbols=[s for b in books for s in b.symbols],
    )
    if all(b.buy_hold is not None for b in books):
        comp.buy_hold = pd.concat(
            [key(b.buy_hold).reindex(index).ffill().fillna(b.initial_capital) for b in books if b.buy_hold is not None],
            axis=1,
        ).mean(axis=1)
    for b in books:
        for k, v in b.event_counts.items():
            comp.event_counts[k] = comp.event_counts.get(k, 0) + v
    comp.events = [e for b in books for e in b.events][:500]
    comp.metrics["_scale"] = 1.0 / n
    return comp


def _index_benchmark(
    bars: pd.DataFrame, instrument: Instrument, start: date, end: date, capital: float
) -> pd.Series | None:
    idx = _window(bars, instrument.tz, start, end)
    if len(idx) == 0:
        return None
    sel = bars.iloc[idx]
    closes = pd.Series(
        sel["close"].to_numpy(float), index=bar_close_ns(pd.DatetimeIndex(sel.index), instrument)
    )
    feed_like = SymbolFeed(instrument, sel, pd.DataFrame(index=sel.index), np.zeros(len(sel)), 0, len(sel) - 1)
    closes.index = display_index(closes.index.to_numpy(), [feed_like])
    return capital * closes / closes.iloc[0]


_SCALED = (
    "total_fees", "fees_pct_of_capital", "turnover", "realized_pnl", "unrealized_pnl",
    "expectancy", "avg_win", "avg_loss", "largest_win", "largest_loss",
)


def run_on_bars(
    bt: BacktestConfig,
    costs_cfg: CostsConfig,
    strategy: Strategy,
    bars_by_symbol: dict[str, pd.DataFrame],
    instruments: dict[str, Instrument],
    *,
    benchmark: tuple[pd.DataFrame, Instrument] | None = None,
    extra_warnings: list[str] | None = None,
) -> BacktestResult:
    start = bt.start
    end = bt.end or date.today()
    started = datetime.now(UTC).isoformat(timespec="seconds")
    warnings = list(extra_warnings or []) + strategy.warnings()
    feeds: list[SymbolFeed] = []
    for sym in bt.symbols:
        bars = bars_by_symbol.get(sym)
        if bars is None or bars.empty:
            warnings.append(f"{sym}: no data; skipped")
            continue
        feed = make_feed(strategy, bars, instruments[sym], start, end, warnings)
        if feed is not None:
            feeds.append(feed)
    if not feeds:
        raise DataError("No symbol has enough data to backtest: " + "; ".join(warnings))

    lookahead = None
    if bt.check_lookahead:
        probe = max(feeds, key=lambda f: f.last)
        lookahead = check_lookahead(strategy, probe.bars, checkpoints=6)
        if not lookahead.ok:
            warnings.append(f"{strategy.name}: {lookahead.summary()} on {probe.symbol}")

    costs = build_cost_model(costs_cfg)
    capital = bt.capital
    tf = Timeframe.parse(bt.timeframe)
    common: dict[str, Any] = {"execution": bt.execution, "exits": bt.exits, "sizing": bt.sizing}
    if bt.mode == "scan":
        # Each symbol trades the full capital on its own.
        common["sizing"] = bt.sizing.model_copy(update={"method": "all_in", "max_positions": 1})

    bench_series = bench_name = None
    if benchmark is not None:
        bench_series = _index_benchmark(benchmark[0], benchmark[1], start, end, capital)
        bench_name = benchmark[1].name or benchmark[1].symbol
        if bench_series is None:
            warnings.append(f"Benchmark {benchmark[1].symbol}: no bars in range; using buy & hold")

    books: dict[str, Book] = {}
    if bt.mode == "portfolio":
        book = Simulator(feeds, strategy, costs, capital=capital, name=PORTFOLIO, **common).run()
        book.buy_hold = buy_and_hold(feeds, costs, capital, bt.execution, pd.DatetimeIndex(book.equity.index))
        books[PORTFOLIO] = book
        primary = PORTFOLIO
    else:
        for feed in feeds:
            book = Simulator([feed], strategy, costs, capital=capital, name=feed.symbol, **common).run()
            book.buy_hold = buy_and_hold([feed], costs, capital, bt.execution, pd.DatetimeIndex(book.equity.index))
            books[feed.symbol] = book
        if len(feeds) > 1:
            books[COMPOSITE] = _composite(list(books.values()), COMPOSITE)
            primary = COMPOSITE
        else:
            primary = feeds[0].symbol

    fallback = tf.bars_per_year(feeds[0].instrument.market)
    for book in books.values():
        if bench_series is not None:
            book.benchmark = align_series(bench_series, pd.DatetimeIndex(book.equity.index), capital, rebase=True)
            book.benchmark_name = bench_name
        else:
            book.benchmark, book.benchmark_name = book.buy_hold, "Buy & hold"
        scale = book.metrics.pop("_scale", None)
        book.metrics = book_metrics(book, fallback_ppy=fallback, risk_free_rate=bt.risk_free_rate)
        if scale is not None:
            for key in _SCALED:
                if isinstance(book.metrics.get(key), float):
                    book.metrics[key] *= scale

    views = {
        f.symbol: SymbolView(
            instrument=f.instrument,
            bars=f.bars.iloc[f.first : f.last + 1],
            indicators=f.indicators.iloc[f.first : f.last + 1],
            plots=strategy.plots,
        )
        for f in feeds
    }
    return BacktestResult(
        config=bt,
        strategy=strategy.describe(),
        books=books,
        primary=primary,
        symbols=views,
        warnings=warnings,
        lookahead=lookahead,
        costs={"model": costs_cfg.model, **costs.describe()},
        started_at=started,
        finished_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


@dataclass
class LoadedData:
    bars: dict[str, pd.DataFrame]
    instruments: dict[str, Instrument]
    benchmark: tuple[pd.DataFrame, Instrument] | None
    warnings: list[str]


def load_data(bt: BacktestConfig, data: DataManager, warmup_bars: int, lot_sizes: dict[str, int]) -> LoadedData:
    tf = Timeframe.parse(bt.timeframe)
    end = bt.end or date.today()
    instruments = data.instruments(bt.symbols, lot_sizes)
    bars: dict[str, pd.DataFrame] = {}
    for sym in bt.symbols:
        try:
            bars[sym] = data.load_bars(sym, tf, bt.start, end, warmup_bars=warmup_bars)
        except DataError as exc:
            data.warnings.append(f"{sym}: {exc}")
    benchmark = None
    if bt.benchmark:
        try:
            info = data.store.read_instruments().get(bt.benchmark)
            inst = Instrument(bt.benchmark, lot_size=1, name=info.name if info else "", security_type="IDX")
            benchmark = (data.load_bars(bt.benchmark, tf, bt.start, end), inst)
        except DataError as exc:
            data.warnings.append(f"Benchmark {bt.benchmark}: {exc}")
    return LoadedData(bars, instruments, benchmark, list(data.warnings))


def run_backtest(cfg: AppConfig, data: DataManager, bt: BacktestConfig | None = None) -> BacktestResult:
    bt = bt or cfg.backtest
    if cfg.strategy_paths:
        load_strategy_paths([cfg.path(p) for p in cfg.strategy_paths])
    strategy = create_strategy(bt.strategy.name, bt.strategy.params)
    loaded = load_data(bt, data, strategy.warmup_bars(), cfg.data.lot_sizes)
    log.info(
        "Backtest %s on %d symbol(s), %s %s..%s, mode=%s",
        strategy.name, len(loaded.bars), bt.timeframe, bt.start, bt.end, bt.mode,
    )
    return run_on_bars(
        bt, cfg.costs, strategy, loaded.bars, loaded.instruments,
        benchmark=loaded.benchmark, extra_warnings=loaded.warnings,
    )


# --------------------------------------------------------------------------- serialisation


def _num(x: Any) -> Any:
    if isinstance(x, (np.floating, float)):
        f = float(x)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, dict):
        return {str(k): _num(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_num(v) for v in x]
    if isinstance(x, (pd.Timestamp, datetime, date)):
        return x.isoformat()
    return x


def _epoch(index: pd.DatetimeIndex) -> list[int]:
    """Chart time: seconds, with exchange-local wall time presented as if it were UTC."""
    idx = pd.DatetimeIndex(index)
    naive = idx.tz_localize(None) if idx.tz is not None else idx
    return (naive.as_unit("s").asi8).tolist()


def _curve(series: pd.Series) -> list[dict[str, Any]]:
    s = series.dropna()
    if len(s) > MAX_CURVE_POINTS:
        step = math.ceil(len(s) / MAX_CURVE_POINTS)
        s = pd.concat([s.iloc[::step], s.iloc[[-1]]])
        s = s[~s.index.duplicated(keep="last")]
    return [{"time": t, "value": _num(v)} for t, v in zip(_epoch(pd.DatetimeIndex(s.index)), s.to_numpy(float), strict=True)]


def _book_payload(book: Book) -> dict[str, Any]:
    dd = drawdown(book.equity, book.initial_capital)
    monthly = monthly_returns(book.equity, book.initial_capital)
    return {
        "name": book.name,
        "currency": book.currency,
        "initial_capital": book.initial_capital,
        "metrics": _num(book.metrics),
        "equity": _curve(book.equity),
        "drawdown": _curve(dd),
        "benchmark": _curve(book.benchmark) if book.benchmark is not None else [],
        "benchmark_name": book.benchmark_name,
        "buy_hold": _curve(book.buy_hold) if book.buy_hold is not None else [],
        "trades": [_num(t.to_dict()) for t in book.trades],
        "drawdowns": _num(drawdown_periods(book.equity, book.initial_capital)),
        "monthly": {
            str(year): {str(k): _num(v) for k, v in row.items()} for year, row in monthly.iterrows()
        } if not monthly.empty else {},
        "event_counts": book.event_counts,
    }


def _symbol_payload(view: SymbolView, fills: list[Any]) -> dict[str, Any]:
    bars = view.bars.iloc[-MAX_CHART_BARS:]
    ind = view.indicators.loc[bars.index]
    t = _epoch(pd.DatetimeIndex(bars.index))
    candles = [
        {"time": ts, "open": _num(o), "high": _num(h), "low": _num(lo), "close": _num(c), "volume": _num(v)}
        for ts, o, h, lo, c, v in zip(
            t, bars["open"], bars["high"], bars["low"], bars["close"], bars["volume"], strict=True
        )
    ]
    lines = []
    for spec in view.plots:
        if spec.column in ind.columns:
            values = ind[spec.column].to_numpy(float)
            lines.append({
                "column": spec.column, "label": spec.label or spec.column, "pane": spec.pane, "kind": spec.kind,
                "data": [{"time": ts, "value": _num(v)} for ts, v in zip(t, values, strict=True) if not math.isnan(v)],
            })
    first = bars.index[0] if len(bars) else None
    markers = [
        {"time": _epoch(pd.DatetimeIndex([f.time]))[0], "side": f.side, "price": f.price, "quantity": f.quantity, "reason": f.reason}
        for f in fills
        if f.symbol == view.instrument.symbol and (first is None or f.time >= first)
    ]
    return {
        "symbol": view.instrument.symbol,
        "name": view.instrument.name,
        "lot_size": view.instrument.lot_size,
        "candles": candles,
        "lines": lines,
        "markers": markers,
    }


def result_payload(result: BacktestResult) -> dict[str, Any]:
    main = result.main
    return {
        "version": 1,
        "strategy": _num(result.strategy),
        "config": result.config.model_dump(mode="json"),
        "primary": result.primary,
        "books": {name: _book_payload(b) for name, b in result.books.items()},
        "symbols": {sym: _symbol_payload(v, main.fills) for sym, v in result.symbols.items()},
        "warnings": result.warnings,
        "lookahead": None if result.lookahead is None else {
            "ok": result.lookahead.ok, "summary": result.lookahead.summary(),
        },
        "costs": _num(result.costs),
        "started_at": result.started_at,
        "finished_at": result.finished_at,
    }


def save_result(result: BacktestResult, out_root: Path, run_id: str | None = None) -> Path:
    """Write ``result.json`` plus CSVs under ``out_root/<run_id>`` and return the directory."""
    if run_id is None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_id = f"{stamp}_{re.sub(r'[^A-Za-z0-9_]+', '_', result.strategy['name'])}_{result.config.timeframe}"
    out = out_root / run_id
    out.mkdir(parents=True, exist_ok=True)
    payload = result_payload(result)
    payload["id"] = run_id
    (out / "result.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    main = result.main
    pd.DataFrame([t.to_dict() for t in main.trades]).to_csv(out / "trades.csv", index=False)
    pd.DataFrame([f.to_dict() for f in main.fills]).to_csv(out / "fills.csv", index=False)
    pd.DataFrame({"equity": main.equity, "cash": main.cash, "exposure": main.exposure}).to_csv(out / "equity.csv")
    result.summary().to_csv(out / "summary.csv")
    return out
