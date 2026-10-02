"""Web console: a FastAPI JSON API plus a static single-page app.

Security model:

* Binds to 127.0.0.1 by default. Binding elsewhere requires a token (``web.token_env``),
  enforced by the CLI.
* When a token is configured, every ``/api`` request must carry it (``Authorization:
  Bearer``, the ``futu_algo_token`` cookie, or ``?token=`` for the event stream).
* Every state-changing request must carry the ``X-Futu-Algo: 1`` header. Browsers cannot
  add custom headers to cross-site requests without a CORS preflight, which this server
  never approves, so another website cannot drive the engine through a visitor's browser.
* Requests must name an allowed host in ``Host`` (127.0.0.1, localhost, ::1, ``web.host`` and
  ``web.allowed_hosts``), so a DNS-rebinding page cannot reach the console, and a
  state-changing ``/api`` request whose ``Origin`` is another host is refused.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import math
import queue
import shutil
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pandas as pd
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from futu_algo import __version__
from futu_algo.app import App, Job
from futu_algo.backtest.runner import _epoch, _num, run_backtest, save_result
from futu_algo.config import BacktestConfig, secret, validate_yaml_text
from futu_algo.data.store import SeriesKey
from futu_algo.errors import ConfigError, FutuAlgoError
from futu_algo.events import BACKTEST, Event
from futu_algo.market.calendar import minutes_to_close
from futu_algo.screener.engine import list_results, load_result
from futu_algo.strategy.registry import available, create_strategy
from futu_algo.timeframe import Timeframe

log = logging.getLogger(__name__)
STATIC = Path(__file__).with_name("static")
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


# --------------------------------------------------------------------------- request models


class HaltBody(BaseModel):
    reason: str = "manual (console)"


class FlattenBody(BaseModel):
    symbol: str | None = None


class BacktestBody(BaseModel):
    """Overrides on top of the configured ``backtest`` section."""

    overrides: dict[str, Any] = Field(default_factory=dict)
    offline: bool | None = None


class ScreenBody(BaseModel):
    preset: str
    notify: bool = False


class FetchBody(BaseModel):
    symbols: list[str]
    timeframe: str = "DAY"
    start: date
    end: date | None = None


class ConfigBody(BaseModel):
    text: str


class NotifyBody(BaseModel):
    message: str = "Test notification from the futu_algo console"


# --------------------------------------------------------------------------- helpers


def _clean(obj: Any) -> Any:
    """JSON-safe: NaN/inf -> null, numpy scalars -> Python, timestamps -> ISO."""
    return _num(obj)


def _json(obj: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(_clean(obj), status_code=status)


def _deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in extra.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _loads(text: Any) -> Any:
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text)
    except ValueError:
        return text


def _url_host(url: str) -> str | None:
    """Lower-case host name of a URL, without port or IPv6 brackets; None if malformed."""
    try:
        return urlsplit(url).hostname
    except ValueError:
        return None


def _job_payload(job: Job) -> dict[str, Any]:
    return job.to_dict()


def list_backtests(root: Path, limit: int = 100) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not root.is_dir():
        return out
    for path in sorted(root.glob("*/result.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        main = data.get("books", {}).get(data.get("primary"), {})
        m = main.get("metrics", {})
        cfg = data.get("config", {})
        out.append({
            "id": path.parent.name,
            "strategy": data.get("strategy", {}).get("name"),
            "params": data.get("strategy", {}).get("params"),
            "symbols": cfg.get("symbols"),
            "timeframe": cfg.get("timeframe"),
            "start": cfg.get("start"),
            "end": cfg.get("end"),
            "mode": cfg.get("mode"),
            "finished_at": data.get("finished_at"),
            "total_return": m.get("total_return"),
            "sharpe": m.get("sharpe"),
            "max_drawdown": m.get("max_drawdown"),
            "trades": m.get("trades"),
        })
    return out


# --------------------------------------------------------------------------- app factory


def create_app(app: App, *, token: str | None = None, allowed_hosts: Iterable[str] = ()) -> FastAPI:
    """``allowed_hosts`` adds host names to the local ones, ``web.host`` and ``web.allowed_hosts``."""
    cfg = app.cfg
    api = FastAPI(title="futu_algo console", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    token = token if token is not None else secret(cfg.web.token_env)
    hosts = {h.strip().strip("[]").lower() for h in (*LOCAL_HOSTS, cfg.web.host, *cfg.web.allowed_hosts, *allowed_hosts)}
    api.state.app = app

    @api.middleware("http")
    async def guard(request: Request, call_next: Any) -> Any:
        path = request.url.path
        if _url_host("//" + request.headers.get("host", "")) not in hosts:
            return JSONResponse({"detail": "Host not allowed: add it to web.allowed_hosts"}, status_code=400)
        if path.startswith("/api") and path not in ("/api/health",):
            if token:
                supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
                supplied = supplied or request.cookies.get("futu_algo_token", "") or request.query_params.get("token", "")
                if not hmac.compare_digest(supplied.encode(), token.encode()):
                    return JSONResponse({"detail": "Unauthorized: missing or wrong console token"}, status_code=401)
            if request.method in MUTATING and request.headers.get("x-futu-algo") != "1":
                return JSONResponse({"detail": "Missing X-Futu-Algo header"}, status_code=403)
            origin = request.headers.get("origin")
            if request.method in MUTATING and origin is not None and _url_host(origin) not in hosts:
                return JSONResponse({"detail": "Cross-origin request refused"}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if not path.startswith("/api"):
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; connect-src 'self'; frame-ancestors 'none'",
            )
        return response

    @api.exception_handler(FutuAlgoError)
    async def _domain_error(_: Request, exc: FutuAlgoError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    # ------------------------------------------------------------------ status

    @api.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__, "token_required": bool(token)}

    @api.get("/api/status")
    def status() -> JSONResponse:
        engine = app.engine
        now = engine.clock() if engine else datetime.now(UTC)
        try:
            phase = str(app.calendar.phase(now))
        except Exception:
            phase = "unknown"
        return _json({
            "version": __version__,
            "config_path": str(cfg.source_path) if cfg.source_path else None,
            "now": now.isoformat(),
            "market": app.market.code,
            "market_tz": app.market.tz,
            "phase": phase,
            "minutes_to_close": minutes_to_close(now, app.market),
            "trading": {
                "env": cfg.trading.env, "mode": cfg.trading.mode, "timeframe": cfg.trading.timeframe,
                "symbols": cfg.trading.symbols, "sizing": cfg.trading.sizing.model_dump(),
            },
            "engine": engine.status() if engine else None,
            "notifications": [c.name for c in app.notifier.channels],
            "offline": cfg.data.offline,
            "token_required": bool(token),
        })

    # ------------------------------------------------------------------ engine

    def _engine() -> Any:
        if app.engine is None or app.engine.state != "running":
            raise HTTPException(409, "Engine is not running")
        return app.engine

    @api.post("/api/engine/start")
    def engine_start() -> JSONResponse:
        engine = app.start_engine()
        return _json(engine.status())

    @api.post("/api/engine/stop")
    def engine_stop() -> JSONResponse:
        app.stop_engine()
        return _json({"state": app.engine.state if app.engine else "stopped"})

    @api.post("/api/engine/halt")
    def engine_halt(body: HaltBody) -> JSONResponse:
        _engine().halt(body.reason)
        return _json({"halted": True})

    @api.post("/api/engine/resume")
    def engine_resume() -> JSONResponse:
        _engine().resume("console")
        return _json({"halted": False})

    @api.post("/api/engine/flatten")
    def engine_flatten(body: FlattenBody) -> JSONResponse:
        n = _engine().flatten(body.symbol, reason="flatten from console")
        return _json({"positions": n})

    @api.post("/api/engine/cancel-all")
    def engine_cancel_all() -> JSONResponse:
        return _json({"cancelled": _engine().cancel_all()})

    @api.post("/api/engine/summary")
    def engine_summary() -> JSONResponse:
        return _json(_engine().daily_summary())

    # ----------------------------------------------------------------- account

    @api.get("/api/account")
    def account() -> JSONResponse:
        engine = app.engine
        if engine is None or engine.account is None:
            return _json({"account": None, "positions": [], "source": "none"})
        positions = [p.to_dict() for p in engine.positions.values()]
        return _json({
            "account": engine.account.to_dict(),
            "positions": positions,
            "day_start_equity": engine.day_start_equity,
            "env": engine.env,
            "source": "engine",
        })

    @api.get("/api/orders")
    def orders(limit: int = 200, open_only: bool = False) -> JSONResponse:
        return _json(app.state.orders(limit=limit, open_only=open_only))

    @api.get("/api/fills")
    def fills(limit: int = 200, today: bool = False) -> JSONResponse:
        since = None
        if today:
            since = pd.Timestamp.now(tz=app.market.tz).normalize().tz_convert("UTC").isoformat()
        return _json(app.state.fills(limit=limit, since_iso=since))

    @api.get("/api/signals")
    def signals(limit: int = 200, symbol: str | None = None, actions_only: bool = False) -> JSONResponse:
        rows = app.state.signals(limit=limit * (5 if actions_only else 1), symbol=symbol)
        if actions_only:
            rows = [r for r in rows if r["action"] not in ("hold", "warmup")][:limit]
        return _json([{**r, "detail": _loads(r.get("detail"))} for r in rows])

    @api.get("/api/intents")
    def intents(limit: int = 200) -> JSONResponse:
        return _json(app.state.intents(limit=limit))

    @api.get("/api/equity")
    def equity(days: int = 1) -> JSONResponse:
        now = app.engine.clock() if app.engine else datetime.now(UTC)
        since = (pd.Timestamp(now).tz_convert("UTC") - timedelta(days=days)).isoformat(timespec="seconds")
        rows = app.state.equity_curve(since_iso=since)
        return _json(rows)

    @api.get("/api/events")
    def events(limit: int = 200, kinds: str | None = None) -> JSONResponse:
        rows = app.state.events(limit=limit, kinds=kinds.split(",") if kinds else None)
        return _json([{**r, "data": _loads(r.get("data"))} for r in rows])

    @api.get("/api/stream")
    async def stream(request: Request) -> StreamingResponse:
        q = app.bus.open_queue(maxsize=2000)
        backlog = [e for e in app.bus.recent(1000) if e.kind not in ("bar", "log")][-150:]

        async def gen() -> Any:
            try:
                yield "retry: 3000\n\n"
                for ev in backlog:
                    yield _sse(ev)
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        ev = await asyncio.to_thread(q.get, True, 15.0)
                    except queue.Empty:
                        yield ": keep-alive\n\n"
                        continue
                    yield _sse(ev)
            finally:
                app.bus.close_queue(q)

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # --------------------------------------------------------------- strategies

    @api.get("/api/strategies")
    def strategies() -> JSONResponse:
        out = []
        for name, cls in available().items():
            inst = cls()
            out.append({
                "name": name,
                "title": cls.title,
                "description": cls.description,
                "params": inst.params.model_dump(),
                "schema": cls.param_schema(),
                "warmup_bars": inst.warmup_bars(),
                "plots": [{"column": p.column, "pane": p.pane, "kind": p.kind, "label": p.label} for p in cls.plots],
            })
        return _json(out)

    # -------------------------------------------------------------------- chart

    @api.get("/api/chart/{symbol}")
    def chart(symbol: str, timeframe: str | None = None, bars: int = 400, strategy: str | None = None) -> JSONResponse:
        from futu_algo.market.instrument import normalize_symbol

        symbol = normalize_symbol(symbol)
        engine = app.engine
        tf = Timeframe.parse(timeframe or cfg.trading.timeframe)
        spec = cfg.trading.strategy_for(symbol)
        strat = create_strategy(strategy or spec.name, spec.params if not strategy or strategy == spec.name else {})
        frame: pd.DataFrame | None = None
        source = "cache"
        if engine is not None and symbol in engine.windows and str(tf) == str(engine.tf) and not strategy:
            frame = engine.windows[symbol]
            strat = engine.strategies[symbol]
            source = "live"
        if frame is None or frame.empty:
            dm = app.fresh_data()
            end = date.today()
            lookback = tf.calendar_days_for(bars + strat.warmup_bars(), app.market)
            try:
                frame = dm.load_bars(symbol, tf, end - timedelta(days=lookback), end)
            except FutuAlgoError as exc:
                raise HTTPException(404, f"No bars for {symbol} {tf}: {exc}") from exc
        if frame is None or frame.empty:
            raise HTTPException(404, f"No bars for {symbol} {tf}")
        ind, sig = strat.run(frame)
        frame, ind, sig = frame.iloc[-bars:], ind.iloc[-bars:], sig.iloc[-bars:]
        t = _epoch(pd.DatetimeIndex(frame.index))
        candles = [
            {"time": ts, "open": o, "high": h, "low": lo, "close": c, "volume": v}
            for ts, o, h, lo, c, v in zip(t, frame["open"], frame["high"], frame["low"], frame["close"], frame["volume"], strict=True)
        ]
        lines = []
        for p in strat.plots:
            if p.column in ind.columns:
                vals = ind[p.column].to_numpy(float)
                lines.append({"column": p.column, "label": p.label or p.column, "pane": p.pane, "kind": p.kind,
                              "data": [{"time": ts, "value": float(v)} for ts, v in zip(t, vals, strict=True) if not math.isnan(v)]})
        signals_ = [{"time": ts, "value": float(v)} for ts, v in zip(t, sig.to_numpy(float), strict=True) if not math.isnan(v)]
        first = frame.index[0]
        fills_ = [
            f for f in app.state.fills(limit=500)
            if f["symbol"] == symbol and pd.Timestamp(f["time"]) >= first
        ]
        markers = []
        for f in fills_:
            ts = pd.Timestamp(f["time"]).tz_convert(app.market.tz)
            # Place each fill on the bar that contains it (end-labelled bars).
            pos = min(int(frame.index.searchsorted(ts)), len(frame) - 1)
            markers.append({"time": t[pos], "side": f["side"], "price": f["price"], "quantity": f["quantity"]})
        return _json({
            "symbol": symbol, "timeframe": str(tf), "strategy": strat.describe(), "source": source,
            "candles": candles, "lines": lines, "signals": signals_, "markers": markers,
        })

    # ----------------------------------------------------------------- backtest

    reports_root = cfg.path(cfg.backtest.output_dir)

    @api.get("/api/backtests")
    def backtests() -> JSONResponse:
        return _json(list_backtests(reports_root))

    @api.get("/api/backtests/defaults")
    def backtest_defaults() -> JSONResponse:
        return _json(cfg.backtest.model_dump(mode="json"))

    @api.get("/api/backtests/{run_id}")
    def backtest(run_id: str) -> Response:
        path = reports_root / run_id / "result.json"
        if not path.resolve().is_relative_to(reports_root.resolve()) or not path.is_file():
            raise HTTPException(404, "Backtest not found")
        return Response(path.read_text(encoding="utf-8"), media_type="application/json")

    @api.delete("/api/backtests/{run_id}")
    def delete_backtest(run_id: str) -> JSONResponse:
        target = (reports_root / run_id).resolve()
        if not target.is_relative_to(reports_root.resolve()) or not (target / "result.json").is_file():
            raise HTTPException(404, "Backtest not found")
        shutil.rmtree(target)
        return _json({"deleted": run_id})

    @api.post("/api/backtests")
    def run_backtest_job(body: BacktestBody) -> JSONResponse:
        base = cfg.backtest.model_dump(mode="json")
        if "strategy" in body.overrides:
            base.pop("strategy")  # a different strategy must not inherit the old one's params
        merged = _deep_merge(base, body.overrides)
        try:
            bt = BacktestConfig.model_validate(merged)
        except Exception as exc:
            raise HTTPException(422, f"Invalid backtest settings: {exc}") from exc

        def work(job: Job) -> dict[str, Any]:
            job.message = "loading data"
            result = run_backtest(cfg, app.fresh_data(body.offline), bt)
            job.message = "saving report"
            out = save_result(result, reports_root)
            app.bus.emit(BACKTEST, f"Backtest {bt.strategy.name} on {len(bt.symbols)} symbol(s) finished: "
                         f"{(result.main.metrics.get('total_return') or 0):+.2%}", run_id=out.name)
            return {"id": out.name}

        job = app.jobs.submit("backtest", f"{bt.strategy.name} {bt.timeframe} {','.join(bt.symbols)}", work)
        return _json(_job_payload(job))

    @api.get("/api/jobs")
    def jobs() -> JSONResponse:
        return _json([_job_payload(j) for j in app.jobs.list()])

    @api.get("/api/jobs/{job_id}")
    def job(job_id: str) -> JSONResponse:
        j = app.jobs.get(job_id)
        if j is None:
            raise HTTPException(404, "Job not found")
        return _json(j.to_dict(with_result=True))

    # ----------------------------------------------------------------- screener

    screen_root = cfg.path(cfg.screener.results_dir)

    @api.get("/api/screener/presets")
    def screener_presets() -> JSONResponse:
        return _json({name: p.model_dump(mode="json") for name, p in cfg.screener.presets.items()})

    @api.post("/api/screener/run")
    def screener_run(body: ScreenBody) -> JSONResponse:
        preset = cfg.screener.presets.get(body.preset)
        if preset is None:
            raise HTTPException(404, f"Unknown preset {body.preset}")

        def work(job: Job) -> dict[str, Any]:
            job.message = "screening"
            result = app.screener().run(body.preset, preset, notify=body.notify)
            return {"id": Path(result.path or "").stem, "count": len(result.rows)}

        return _json(_job_payload(app.jobs.submit("screener", f"screen {body.preset}", work)))

    @api.get("/api/screener/results")
    def screener_results() -> JSONResponse:
        return _json(list_results(screen_root))

    @api.get("/api/screener/results/{result_id}")
    def screener_result(result_id: str) -> JSONResponse:
        try:
            return _json(load_result(screen_root, result_id))
        except (FileNotFoundError, OSError) as exc:
            raise HTTPException(404, "Result not found") from exc

    # --------------------------------------------------------------------- data

    @api.get("/api/data/series")
    def data_series() -> JSONResponse:
        return _json(app.store.list_series())

    @api.get("/api/data/quota")
    def data_quota() -> JSONResponse:
        if cfg.data.offline:
            return _json({"offline": True})
        q = app.data.source.quota()
        return _json({"used": q.used, "remaining": q.remaining, "symbols": sorted(q.codes)} if q else {"error": "quota unavailable"})

    @api.post("/api/data/fetch")
    def data_fetch(body: FetchBody) -> JSONResponse:
        from futu_algo.market.instrument import normalize_symbol

        tf = Timeframe.parse(body.timeframe)
        symbols = [normalize_symbol(s) for s in body.symbols]
        end = body.end or date.today()

        def work(job: Job) -> dict[str, Any]:
            dm = app.fresh_data(False)
            done = {}
            dm.instruments(symbols, cfg.data.lot_sizes)
            for i, sym in enumerate(symbols, 1):
                job.message = f"{sym} ({i}/{len(symbols)})"
                bars = dm.load_bars(sym, tf, body.start, end)
                done[sym] = len(bars)
            return {"bars": done, "warnings": dm.warnings}

        return _json(_job_payload(app.jobs.submit("data", f"fetch {tf} {','.join(symbols)}", work)))

    @api.get("/api/data/bars/{symbol}")
    def data_bars(symbol: str, ktype: str = "K_DAY") -> JSONResponse:
        from futu_algo.market.instrument import normalize_symbol

        key = SeriesKey(normalize_symbol(symbol), ktype, cfg.data.adjust)
        frame = app.store.read(key)
        if frame is None:
            raise HTTPException(404, "Series not cached")
        return _json({"rows": len(frame), "meta": app.store.read_meta(key), "tail": frame.tail(20).reset_index().to_dict("records")})

    # ------------------------------------------------------------------- config

    @api.get("/api/config")
    def get_config() -> JSONResponse:
        path = cfg.source_path
        text = path.read_text(encoding="utf-8") if path and path.is_file() else yaml.safe_dump(cfg.public_dict(), sort_keys=False, allow_unicode=True)
        return _json({"path": str(path) if path else None, "editable": bool(path), "text": text, "effective": cfg.public_dict()})

    @api.post("/api/config/validate")
    def validate_config(body: ConfigBody) -> JSONResponse:
        try:
            parsed = validate_yaml_text(body.text, cfg.base_dir)
        except ConfigError as exc:
            return _json({"ok": False, "error": str(exc)})
        return _json({"ok": True, "effective": parsed.public_dict()})

    @api.put("/api/config")
    def put_config(body: ConfigBody) -> JSONResponse:
        path = cfg.source_path
        if path is None:
            raise HTTPException(409, "No config file to write (started without --config)")
        try:
            validate_yaml_text(body.text, cfg.base_dir)
        except ConfigError as exc:
            raise HTTPException(422, str(exc)) from exc
        backup = path.with_suffix(path.suffix + f".bak-{datetime.now():%Y%m%d%H%M%S}")
        shutil.copy2(path, backup)
        path.write_text(body.text, encoding="utf-8")
        return _json({"saved": str(path), "backup": str(backup), "restart_required": True})

    @api.post("/api/notify/test")
    def notify_test(body: NotifyBody) -> JSONResponse:
        if not app.notifier.channels:
            raise HTTPException(409, "No notification channel is enabled in the config")
        errors = app.notifier.send_now("[futu_algo] Test", body.message)
        return _json({"ok": not errors, "errors": errors})

    # ------------------------------------------------------------------- static

    api.mount("/static", StaticFiles(directory=STATIC), name="static")

    @api.get("/", include_in_schema=False)
    def index(request: Request) -> Response:
        response = FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})
        supplied = request.query_params.get("token")
        if token and supplied and hmac.compare_digest(supplied.encode(), token.encode()):
            response.set_cookie("futu_algo_token", supplied, httponly=True, samesite="strict")
        return response

    return api


def _sse(ev: Event) -> str:
    return f"id: {ev.id}\nevent: {ev.kind}\ndata: {json.dumps(_clean(ev.to_dict()), default=str)}\n\n"
