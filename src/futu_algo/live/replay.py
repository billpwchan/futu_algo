"""Replay historical bars through the *live* engine with the local simulated broker.

This runs exactly the code path used in paper trading (engine decisions, intents, executor,
risk checks, order book-keeping in SQLite) against cached history, with fills at the next
bar's open. It is how the test suite proves live/backtest parity, and ``futu-algo replay``
exposes it for checking a configuration before running it against OpenD.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from futu_algo.backtest.runner import build_cost_model
from futu_algo.config import AppConfig
from futu_algo.events import EventBus
from futu_algo.live.engine import Decision, LiveEngine
from futu_algo.live.feed import Bar
from futu_algo.live.sim_broker import SimBroker
from futu_algo.live.store import StateStore
from futu_algo.market.instrument import MARKETS, Instrument


@dataclass
class ReplayResult:
    decisions: list[Decision]
    fills: list[dict[str, Any]]
    orders: list[dict[str, Any]]
    equity: list[tuple[datetime, float]]
    engine: LiveEngine
    broker: SimBroker
    events: list[dict[str, Any]] = field(default_factory=list)


def _session_opens(prev: pd.Timestamp, cur: pd.Timestamp, tz: str) -> list[pd.Timestamp]:
    """Continuous-session start times strictly between two bar times (local)."""
    market = next(m for m in MARKETS.values() if m.tz == tz)
    out = []
    day = prev.normalize()
    while day <= cur.normalize():
        for start, _ in market.sessions:
            t = day + pd.Timedelta(hours=start.hour, minutes=start.minute)
            if prev < t < cur:
                out.append(t)
        day += pd.Timedelta(days=1)
    return out


def replay(
    cfg: AppConfig,
    bars_by_symbol: dict[str, pd.DataFrame],
    instruments: dict[str, Instrument],
    *,
    start: pd.Timestamp | None = None,
    capital: float = 1_000_000.0,
    store_path: str = ":memory:",
) -> ReplayResult:
    """Warm up on bars before ``start`` and replay the rest bar by bar."""
    market = MARKETS[cfg.trading.market]
    clock_now: list[datetime] = [pd.Timestamp("2000-01-01", tz=market.tz).to_pydatetime()]

    def clock() -> datetime:
        return clock_now[0]

    broker = SimBroker(
        capital, build_cost_model(cfg.costs), lambda s: instruments[s],
        fill_mode="next_bar_open", clock=clock, currency=market.currency,
    )
    bus = EventBus(history=5000)
    engine = LiveEngine(
        cfg, broker=broker, quotes=broker, store=StateStore(store_path), bus=bus,
        instruments=instruments, clock=clock,
    )
    timeline: dict[pd.Timestamp, list[Bar]] = {}
    for sym, bars in bars_by_symbol.items():
        if sym not in engine.strategies:
            continue
        warm = bars[bars.index < start] if start is not None else bars.iloc[:0]
        engine.warmup(sym, warm)
        rest = bars[bars.index >= start] if start is not None else bars
        for ts, r in zip(pd.DatetimeIndex(rest.index), rest.to_dict("records"), strict=True):
            turnover = r.get("turnover", 0.0)
            timeline.setdefault(ts, []).append(
                Bar(sym, ts, r["open"], r["high"], r["low"], r["close"], r["volume"], turnover if turnover == turnover else 0.0)
            )
    decisions: list[Decision] = []
    equity: list[tuple[datetime, float]] = []
    prev: pd.Timestamp | None = None
    for t in sorted(timeline):
        if prev is not None:
            for opening in _session_opens(prev, t, market.tz):
                clock_now[0] = opening.to_pydatetime()
                engine.sync(clock_now[0])
        for bar in timeline[t]:
            broker.on_bar(bar.symbol, t.to_pydatetime(), bar.open, bar.high, bar.low, bar.close)
        clock_now[0] = t.to_pydatetime()
        engine.sync(clock_now[0])
        for bar in timeline[t]:
            d = engine.on_bar(bar)
            if d is not None:
                decisions.append(d)
        engine.executor.sync(clock_now[0])
        equity.append((clock_now[0], broker.account().equity))
        prev = t
    return ReplayResult(
        decisions=decisions,
        fills=list(reversed(engine.store.fills(limit=100000))),
        orders=list(reversed(engine.store.orders(limit=100000))),
        equity=equity,
        engine=engine,
        broker=broker,
        events=[e.to_dict() for e in bus.recent(5000)],
    )
