from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from futu_algo.config import AppConfig, parse_config
from futu_algo.demo.fake_opend import FakeOpenD, SyntheticMarket
from futu_algo.market.instrument import Instrument

FIXTURES = Path(__file__).parent / "fixtures"
HK_TZ = "Asia/Hong_Kong"


@pytest.fixture
def minute_bars() -> dict[str, pd.DataFrame]:
    """Real HK 1-minute bars, 2022-04-11..13 (331 bars per day incl. the 09:30 auction bar)."""
    return {s: pd.read_parquet(FIXTURES / f"{s}_1M_2022-04-11_13.parquet") for s in ("HK.00700", "HK.09988")}


@pytest.fixture
def daily_bars() -> dict[str, pd.DataFrame]:
    return {s: pd.read_parquet(FIXTURES / f"{s}_DAY_2021.parquet") for s in ("HK.00700", "HK.09988")}


@pytest.fixture
def instruments() -> dict[str, Instrument]:
    return {"HK.00700": Instrument("HK.00700", 100, "TENCENT"), "HK.09988": Instrument("HK.09988", 100, "BABA-W")}


@pytest.fixture
def make_config(tmp_path: Path) -> Callable[..., AppConfig]:
    def make(data: dict[str, Any] | None = None) -> AppConfig:
        return parse_config(data or {}, tmp_path)

    return make


def synthetic_bars(n: int = 400, seed: int = 1, start: str = "2023-01-02", freq: str = "B", price: float = 100.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq=freq, tz=HK_TZ, name="time")
    close = price * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    open_ = np.concatenate([[price], close[:-1]]) * np.exp(rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.01, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.01, n)))
    vol = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol, "turnover": vol * close}, index=idx)


class MutableClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def set(self, value: datetime | pd.Timestamp | str) -> None:
        self.now = pd.Timestamp(value).to_pydatetime()


@pytest.fixture
def clock() -> MutableClock:
    return MutableClock(pd.Timestamp("2022-04-12 10:00", tz=HK_TZ).to_pydatetime())


@pytest.fixture
def fake_opend() -> FakeOpenD:
    """Simulated OpenD frozen at 2024-06-12 11:00 HKT (a Wednesday), no background pushes."""
    frozen = pd.Timestamp("2024-06-12 11:00", tz=HK_TZ).to_pydatetime()
    market = SyntheticMarket(clock=lambda: frozen)
    return FakeOpenD(market, push_interval=0)


def utc(ts: str) -> datetime:
    return pd.Timestamp(ts, tz=HK_TZ).tz_convert(UTC).to_pydatetime()
