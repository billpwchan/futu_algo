"""Application container shared by the CLI and the web console.

It owns the long-lived objects (event bus, quote gateway, data manager, state store,
notifier, live engine, scheduler, background jobs) and knows how to build them from the
config. Everything that talks to OpenD is created lazily, so offline commands and the web
console start without it.
"""

from __future__ import annotations

import logging
import os
import threading
import time as _time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from futu_algo.config import AppConfig
from futu_algo.data.manager import DataManager
from futu_algo.data.source import FutuSource
from futu_algo.data.store import ParquetStore
from futu_algo.errors import ConfigError
from futu_algo.events import ENGINE, EventBus
from futu_algo.futu_gateway import QuoteGateway, configure_encryption
from futu_algo.live.engine import LiveEngine
from futu_algo.live.feed import FutuBarFeed
from futu_algo.live.futu_broker import FutuBroker, FutuQuoteProvider
from futu_algo.live.sim_broker import SimBroker
from futu_algo.live.store import StateStore
from futu_algo.market.calendar import TradingCalendar
from futu_algo.market.instrument import MARKETS, Instrument
from futu_algo.notify.dispatcher import Notifier
from futu_algo.screener.engine import Screener
from futu_algo.strategy.registry import load_strategy_paths
from futu_algo.timeframe import Timeframe

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- jobs


@dataclass
class Job:
    id: str
    kind: str
    title: str
    status: str = "queued"  # queued | running | done | failed
    message: str = ""
    result: Any = None
    error: str = ""
    created: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    finished: str | None = None

    def to_dict(self, with_result: bool = False) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if k != "result"}
        if with_result:
            d["result"] = self.result
        return d


class JobManager:
    """Runs slow work (backtests, data downloads, screens) off the request thread."""

    def __init__(self, workers: int = 2, keep: int = 100) -> None:
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="futu-algo-job")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self.keep = keep

    def submit(self, kind: str, title: str, fn: Callable[[Job], Any]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, title=title)
        with self._lock:
            self._jobs[job.id] = job
            if len(self._jobs) > self.keep:
                for old in sorted(self._jobs.values(), key=lambda j: j.created)[: len(self._jobs) - self.keep]:
                    if old.status in ("done", "failed"):
                        self._jobs.pop(old.id, None)

        def run() -> None:
            job.status = "running"
            try:
                job.result = fn(job)
                job.status = "done"
            except Exception as exc:
                job.status = "failed"
                job.error = str(exc)
                log.warning("Job %s (%s) failed: %s\n%s", job.id, title, exc, traceback.format_exc())
            finally:
                job.finished = datetime.now(UTC).isoformat(timespec="seconds")

        self._pool.submit(run)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.created, reverse=True)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


# --------------------------------------------------------------------------- app


class App:
    def __init__(
        self,
        cfg: AppConfig,
        *,
        bus: EventBus | None = None,
        quote_factory: Callable[[str, int], Any] | None = None,
        trade_factory: Callable[[str, int, str, bool], Any] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.cfg = cfg
        self.bus = bus or EventBus()
        self._quote_factory = quote_factory
        self._trade_factory = trade_factory
        self._clock = clock
        self.market = MARKETS[cfg.trading.market]
        if cfg.strategy_paths:
            load_strategy_paths([cfg.path(p) for p in cfg.strategy_paths])
        self.store = ParquetStore(cfg.path(cfg.data.dir))
        self._gateway: QuoteGateway | None = None
        self._data: DataManager | None = None
        self._state: StateStore | None = None
        self._calendar: TradingCalendar | None = None
        self.engine: LiveEngine | None = None
        self.jobs = JobManager()
        self.notifier = Notifier(cfg.notify, self.bus)
        self.scheduler: Scheduler | None = None
        self._persist_unsub: Callable[[], None] | None = None
        self._lock = threading.RLock()

    # --------------------------------------------------------------- plumbing

    @property
    def gateway(self) -> QuoteGateway:
        with self._lock:
            if self._gateway is None:
                configure_encryption(self.cfg.path(self.cfg.futu.rsa_private_key) if self.cfg.futu.rsa_private_key else None)
                self._gateway = QuoteGateway(self.cfg.futu.host, self.cfg.futu.port, context_factory=self._quote_factory)
            return self._gateway

    @property
    def data(self) -> DataManager:
        with self._lock:
            if self._data is None:
                offline = self.cfg.data.offline
                self._data = DataManager(
                    self.store,
                    None if offline else (lambda: FutuSource(self.gateway)),
                    adjust=self.cfg.data.adjust,
                    offline=offline,
                    instrument_ttl_days=self.cfg.data.instrument_ttl_days,
                    **self._today_kw(),
                )
            return self._data

    def fresh_data(self, offline: bool | None = None) -> DataManager:
        """A new manager (its own warnings list) for one job."""
        off = self.cfg.data.offline if offline is None else offline
        return DataManager(
            self.store,
            None if off else (lambda: FutuSource(self.gateway)),
            adjust=self.cfg.data.adjust,
            offline=off,
            instrument_ttl_days=self.cfg.data.instrument_ttl_days,
            **self._today_kw(),
        )

    def _today_kw(self) -> dict[str, Any]:
        """With an injected clock (demo, tests), 'today' for the cache follows that clock."""
        if self._clock is None:
            return {}
        clock = self._clock
        return {"today": lambda tz: pd.Timestamp(clock()).tz_convert(tz).date()}

    @property
    def state(self) -> StateStore:
        with self._lock:
            if self._state is None:
                self._state = StateStore(self.cfg.path(self.cfg.trading.state_db))
                self._persist_unsub = self.bus.subscribe(self._persist_event)
            return self._state

    # Kinds kept in the SQLite audit trail. Bars and routine log lines are too chatty.
    _PERSISTED = frozenset({"engine", "signal", "order", "fill", "rejection", "risk", "error", "account", "daily_summary", "screener"})

    def _persist_event(self, event: Any) -> None:
        if self._state is None or (event.kind not in self._PERSISTED and event.level not in ("warning", "error")):
            return
        try:
            data = {k: v for k, v in event.data.items() if k != "result"}
            self._state.add_event(event.time, event.kind, event.level, event.message, event.symbol, data)
        except Exception:  # pragma: no cover - persistence must never break publishing
            log.debug("Could not persist event", exc_info=True)

    @property
    def calendar(self) -> TradingCalendar:
        if self._calendar is None:
            loader = None
            if not self.cfg.data.offline:
                source = FutuSource(self.gateway)
                loader = lambda a, b: source.trading_days(self.market.code, a, b)  # noqa: E731
            self._calendar = TradingCalendar(self.market, loader)
        return self._calendar

    def screener(self) -> Screener:
        return Screener(self.gateway, self.data, self.bus, self.cfg.path(self.cfg.screener.results_dir))

    def instruments(self, symbols: list[str]) -> dict[str, Instrument]:
        return self.data.instruments(symbols, self.cfg.data.lot_sizes)

    # ------------------------------------------------------------------ engine

    def check_real_allowed(self) -> None:
        tc = self.cfg.trading
        allowed = tc.allow_real and os.environ.get("FUTU_ALGO_ALLOW_REAL") == "1"
        if tc.env == "REAL" and tc.mode == "paper" and not allowed:
            raise ConfigError(
                "trading.env is REAL. This release is validated for paper trading only; to send "
                "real orders anyway set trading.allow_real: true AND FUTU_ALGO_ALLOW_REAL=1."
            )

    def build_engine(self) -> LiveEngine:
        tc = self.cfg.trading
        self.check_real_allowed()
        symbols = tc.symbols
        if not symbols:
            raise ConfigError("trading.universe is empty; add symbols to trade")
        instruments = self.instruments(symbols)
        clock = self._clock
        quotes = FutuQuoteProvider(self.gateway)
        if tc.mode == "dry_run":
            from futu_algo.backtest.runner import build_cost_model

            sim = SimBroker(
                tc.capital or 1_000_000.0, build_cost_model(self.cfg.costs), lambda s: instruments[s],
                fill_mode="quote", currency=self.market.currency,
            )

            class _Quotes:
                def quotes(self, syms: list[str]) -> dict[str, Any]:
                    out = quotes.quotes(syms)
                    for q in out.values():
                        sim.on_quote(q)
                    return out

            broker: Any = sim
            provider: Any = _Quotes()
        else:
            broker = FutuBroker(
                host=self.cfg.futu.host,
                port=self.cfg.futu.port,
                env=tc.env,
                security_firm=self.cfg.futu.security_firm,
                password_md5=os.environ.get(self.cfg.futu.trade_password_md5_env),
                encrypt=bool(self.cfg.futu.rsa_private_key),
                context_factory=self._trade_factory,
                market=tc.market,
            )
            provider = quotes
        tf = Timeframe.parse(tc.timeframe)

        def feed_factory(on_bar: Callable[..., None]) -> FutuBarFeed:
            return FutuBarFeed(self.gateway, tf, self.market, on_bar, grace_seconds=tc.bar_grace_seconds)

        kwargs: dict[str, Any] = {}
        if clock is not None:
            kwargs["clock"] = clock
        return LiveEngine(
            self.cfg, broker=broker, quotes=provider, store=self.state, bus=self.bus,
            instruments=instruments, data=self.data, feed_factory=feed_factory,
            calendar=self.calendar, **kwargs,
        )

    def start_engine(self) -> LiveEngine:
        with self._lock:
            if self.engine is not None and self.engine.state == "running":
                return self.engine
            if self.engine is None or self.engine.state in ("stopped", "error"):
                self.engine = self.build_engine()
            self.engine.start()
            return self.engine

    def stop_engine(self) -> None:
        with self._lock:
            if self.engine is not None:
                self.engine.stop()

    # --------------------------------------------------------------- services

    def start_services(self, *, scheduler: bool = True) -> None:
        self.notifier.start()
        _ = self.state
        if scheduler and self.scheduler is None:
            self.scheduler = Scheduler(self)
            self.scheduler.start()

    def shutdown(self) -> None:
        if self.scheduler:
            self.scheduler.stop()
        self.stop_engine()
        self.notifier.stop()
        self.jobs.shutdown()
        if self._gateway:
            self._gateway.close()
        if self._persist_unsub:
            self._persist_unsub()


# --------------------------------------------------------------------------- scheduler


class Scheduler:
    """Daily jobs in exchange-local time on trading days: instrument refresh, scheduled
    screens and the post-close summary."""

    def __init__(self, app: App, interval: float = 15.0) -> None:
        self.app = app
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._done: set[str] = set()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="futu-algo-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(5)

    def jobs_for_today(self) -> list[tuple[str, Any, Callable[[], None]]]:
        cfg = self.app.cfg
        out: list[tuple[str, Any, Callable[[], None]]] = []
        if cfg.schedule.refresh_instruments:
            out.append(("refresh_instruments", cfg.schedule.refresh_instruments, self._refresh_instruments))
        for job in cfg.screener.schedule:

            def run_screen(preset: str = job.preset, notify: bool = job.notify) -> None:
                self._screen(preset, notify)

            out.append((f"screen:{job.preset}", job.at, run_screen))
        if cfg.schedule.daily_summary:
            out.append(("daily_summary", cfg.schedule.daily_summary, self._summary))
        return out

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.run_due(datetime.now(UTC))
            except Exception:
                log.exception("Scheduler error")

    def run_due(self, now: datetime) -> list[str]:
        local = pd.Timestamp(now).tz_convert(self.app.market.tz)
        day = local.date()
        try:
            trading = self.app.calendar.is_trading_day(day)
        except Exception:
            trading = day.weekday() < 5
        ran: list[str] = []
        if not trading:
            return ran
        for name, at, fn in self.jobs_for_today():
            key = f"{day}:{name}"
            if key in self._done:
                continue
            due = local.normalize() + pd.Timedelta(hours=at.hour, minutes=at.minute)
            if due <= local < due + pd.Timedelta(minutes=30):
                self._done.add(key)
                ran.append(name)
                self.app.jobs.submit("schedule", name, _as_job(fn))
        return ran

    def _refresh_instruments(self) -> None:
        symbols = self.app.cfg.trading.symbols
        if symbols:
            self.app.fresh_data().instruments(symbols, self.app.cfg.data.lot_sizes)

    def _screen(self, preset: str, notify: bool) -> None:
        spec = self.app.cfg.screener.presets[preset]
        self.app.screener().run(preset, spec, notify=notify)

    def _summary(self) -> None:
        engine = self.app.engine
        if engine is not None and engine.state == "running":
            engine.daily_summary()
        else:
            self.app.bus.emit(ENGINE, "Daily summary skipped: engine not running")


def _as_job(fn: Callable[[], None]) -> Callable[[Job], None]:
    def run(_job: Job) -> None:
        fn()

    return run


def wait_for(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    end = _time.monotonic() + timeout
    while _time.monotonic() < end:
        if predicate():
            return True
        _time.sleep(0.05)
    return predicate()

