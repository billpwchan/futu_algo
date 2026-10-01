"""Demo mode: the full application against a simulated OpenD and a synthetic market.

``futu-algo web --demo`` builds a throwaway workspace, a config trading eight synthetic HK
stocks on one-minute bars, and a virtual clock that starts inside the HK morning session
(optionally sped up), so every page of the console can be explored without a Futu account.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from futu_algo.app import App
from futu_algo.config import AppConfig, parse_config
from futu_algo.demo.fake_opend import DEMO_SYMBOLS, FakeOpenD, SyntheticMarket
from futu_algo.events import EventBus


class VirtualClock:
    """Wall clock that starts at ``start`` and runs ``speed`` times faster than real time."""

    def __init__(self, start: datetime, speed: float = 1.0) -> None:
        self.start = start
        self.speed = speed
        self._t0 = time.monotonic()
        self._lock = threading.Lock()

    def __call__(self) -> datetime:
        with self._lock:
            return self.start + timedelta(seconds=(time.monotonic() - self._t0) * self.speed)


def default_demo_start(now: datetime | None = None) -> datetime:
    """10:15 HKT on the most recent weekday (today if it is one)."""
    local = pd.Timestamp(now or datetime.now(UTC)).tz_convert("Asia/Hong_Kong")
    day = local.date()
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return pd.Timestamp(datetime(day.year, day.month, day.day, 10, 15), tz="Asia/Hong_Kong").to_pydatetime()


def demo_config(workdir: Path, *, timeframe: str = "1M", today: date | None = None) -> AppConfig:
    symbols = [s for s in DEMO_SYMBOLS if s != "HK.800000"]
    today = today or date.today()
    data: dict[str, Any] = {
        "data": {"dir": "data"},
        "backtest": {
            "symbols": symbols[:4],
            "strategy": {"name": "macd"},
            "timeframe": "DAY",
            "start": (today - timedelta(days=540)).isoformat(),
            "end": today.isoformat(),
            "capital": 1_000_000,
            "benchmark": "HK.800000",
            "sizing": {"method": "equal_weight", "max_positions": 4},
        },
        "trading": {
            "mode": "paper",
            "env": "SIMULATE",
            "timeframe": timeframe,
            "strategy": {"name": "macd"},
            "universe": [
                {"symbol": "HK.00700", "strategy": {"name": "macd"}},
                {"symbol": "HK.09988", "strategy": {"name": "kdj"}},
                {"symbol": "HK.00005", "strategy": {"name": "rsi"}},
                {"symbol": "HK.01299", "strategy": {"name": "ema_ribbon"}},
                {"symbol": "HK.00388", "strategy": {"name": "boll"}},
                "HK.03690",
            ],
            "sizing": {"method": "fixed_value", "value": 150_000, "max_positions": 5},
            "risk": {"max_position_value": 250_000, "max_daily_loss_pct": 0.05},
            "state_db": "state/demo.sqlite",
        },
        "screener": {
            "presets": {
                "liquid": {
                    "description": "Price above HK$20 and average turnover above HK$100M",
                    "filters": [
                        {"kind": "simple", "field": "CUR_PRICE", "min": 20, "sort": "desc"},
                        {"kind": "accumulate", "field": "TURNOVER", "min": 1e8, "days": 5},
                    ],
                },
                "macd_long": {
                    "description": "Liquid names where the MACD strategy is long on daily bars",
                    "filters": [{"kind": "simple", "field": "CUR_PRICE", "min": 1}],
                    "confirm_strategy": {"name": "macd"},
                    "max_confirm": 10,
                },
            },
            "results_dir": "reports/screener",
        },
        "web": {"autostart_engine": True},
        "logging": {"dir": "logs"},
    }
    cfg = parse_config(data, workdir)
    return cfg


def build_demo_app(workdir: Path, *, speed: float = 1.0, start: datetime | None = None, bus: EventBus | None = None,
                   timeframe: str = "1M") -> tuple[App, FakeOpenD, VirtualClock]:
    workdir.mkdir(parents=True, exist_ok=True)
    clock = VirtualClock(start or default_demo_start(), speed)
    market = SyntheticMarket(clock=clock)
    opend = FakeOpenD(market, push_interval=max(0.2, 1.0 / max(speed, 1.0)))
    cfg = demo_config(workdir, timeframe=timeframe, today=pd.Timestamp(clock.start).tz_convert("Asia/Hong_Kong").date())
    app = App(cfg, bus=bus, quote_factory=opend.quote_factory, trade_factory=opend.trade_factory, clock=clock)
    return app, opend, clock


__all__ = ["VirtualClock", "build_demo_app", "default_demo_start", "demo_config"]
