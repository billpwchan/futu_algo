from datetime import date

import numpy as np
import pandas as pd
import pytest

from futu_algo.data import (
    DataManager,
    FutuSource,
    ParquetStore,
    SeriesKey,
    resample_bars,
    to_bars,
    validate_bars,
)
from futu_algo.data.manager import last_complete_date
from futu_algo.data.source import QuotaStatus
from futu_algo.data.store import InstrumentInfo
from futu_algo.errors import DataError, QuotaExceededError
from futu_algo.futu_gateway import QuoteGateway, RateLimiter
from futu_algo.market.instrument import MARKETS
from futu_algo.timeframe import Timeframe

from .conftest import synthetic_bars

HK = MARKETS["HK"]


def test_to_bars_normalises_futu_frames():
    raw = pd.DataFrame({
        "code": ["HK.00700"] * 2, "time_key": ["2024-06-12 09:31:00", "2024-06-12 09:32:00"],
        "open": ["400", 401], "close": [401, 402], "high": [402, 403], "low": [399, 400], "volume": [100, 200],
    })
    bars = to_bars(raw, HK.tz)
    assert list(bars.columns) == ["open", "high", "low", "close", "volume", "turnover"]
    assert str(bars.index.tz) == HK.tz
    assert bars["open"].iloc[0] == 400.0
    assert bars["turnover"].isna().all()


def test_validate_bars_flags_bad_rows():
    bars = synthetic_bars(10)
    bars.iloc[3, bars.columns.get_loc("high")] = bars["low"].iloc[3] - 1
    bars.iloc[5, bars.columns.get_loc("close")] = -1
    problems = validate_bars(bars)
    assert any("non-positive" in p for p in problems)
    assert any("high/low" in p for p in problems)


def test_store_round_trip_and_coverage(tmp_path):
    from futu_algo.data.store import Coverage

    store = ParquetStore(tmp_path)
    key = SeriesKey("HK.00700", "K_DAY", "qfq")
    bars = synthetic_bars(20)
    store.write(key, bars, Coverage(date(2023, 1, 1), date(2023, 1, 31)), "test")
    back = store.read(key)
    pd.testing.assert_frame_equal(back, bars, check_freq=False)
    assert store.coverage(key).contains(date(2023, 1, 5), date(2023, 1, 20))
    assert store.list_series()[0]["rows"] == 20
    store.write_instruments({"HK.00700": InstrumentInfo("HK.00700", "TENCENT", 100, "STOCK", None, "2024-01-01T00:00:00+00:00")})
    assert store.read_instruments()["HK.00700"].lot_size == 100


class FakeSource:
    name = "fake"

    def __init__(self, bars: pd.DataFrame) -> None:
        self.bars = bars
        self.calls: list[tuple[date, date]] = []
        self.quota_status = QuotaStatus(used=0, remaining=5)

    def fetch_bars(self, symbol, ktype, adjust, start, end):
        self.calls.append((start, end))
        d = self.bars.index.date
        return self.bars[(d >= start) & (d <= end)]

    def fetch_instruments(self, symbols):
        return {s: InstrumentInfo(s, s, 100, "STOCK", None, "2099-01-01T00:00:00+00:00") for s in symbols}

    def quota(self):
        return self.quota_status

    def close(self):
        pass


def test_manager_fetches_only_missing_ranges(tmp_path):
    bars = synthetic_bars(300, start="2023-01-02")
    src = FakeSource(bars)
    dm = DataManager(ParquetStore(tmp_path), lambda: src, today=lambda tz: date(2024, 6, 1))
    key = SeriesKey("HK.00700", "K_DAY", "qfq")
    first = dm.ensure(key, date(2023, 3, 1), date(2023, 6, 30))
    assert len(src.calls) == 1 and len(first) > 0
    dm.ensure(key, date(2023, 4, 1), date(2023, 5, 31))  # inside coverage: no fetch
    assert len(src.calls) == 1
    dm.ensure(key, date(2023, 3, 1), date(2023, 8, 31))  # extends forward, overlapping 10 days
    assert len(src.calls) == 2
    assert src.calls[1][0] == date(2023, 6, 20)


def test_manager_never_caches_the_current_period(tmp_path):
    bars = synthetic_bars(300, start="2023-01-02")
    today = bars.index[-1].date()
    src = FakeSource(bars)
    dm = DataManager(ParquetStore(tmp_path), lambda: src, today=lambda tz: today)
    key = SeriesKey("HK.00700", "K_DAY", "qfq")
    dm.ensure(key, date(2023, 6, 1), today)
    assert ParquetStore(tmp_path).coverage(key).end == last_complete_date("K_DAY", today)


def test_manager_redownloads_when_adjusted_prices_change(tmp_path):
    bars = synthetic_bars(200, start="2023-01-02")
    src = FakeSource(bars)
    dm = DataManager(ParquetStore(tmp_path), lambda: src, today=lambda tz: date(2024, 6, 1))
    key = SeriesKey("HK.00700", "K_DAY", "qfq")
    dm.ensure(key, date(2023, 1, 2), date(2023, 5, 31))
    src.bars = bars * 0.97  # a dividend re-scales every earlier qfq price
    out = dm.ensure(key, date(2023, 1, 2), date(2023, 7, 31))
    assert any("re-downloaded" in w for w in dm.warnings)
    assert out["close"].iloc[0] == pytest.approx(bars["close"].iloc[0] * 0.97)


def test_manager_quota_guard_and_offline(tmp_path):
    src = FakeSource(synthetic_bars(50))
    src.quota_status = QuotaStatus(used=100, remaining=0, codes={"HK.00005"})
    dm = DataManager(ParquetStore(tmp_path), lambda: src, today=lambda tz: date(2024, 6, 1))
    with pytest.raises(QuotaExceededError):
        dm.ensure(SeriesKey("HK.00700", "K_DAY", "qfq"), date(2023, 1, 2), date(2023, 2, 1))
    dm.ensure(SeriesKey("HK.00005", "K_DAY", "qfq"), date(2023, 1, 2), date(2023, 2, 1))  # already counted: free
    offline = DataManager(ParquetStore(tmp_path), None)
    with pytest.raises(DataError):
        offline.ensure(SeriesKey("HK.09988", "K_DAY", "qfq"), date(2023, 1, 2), date(2023, 2, 1))


def test_session_resample_never_spans_lunch(minute_bars):
    one_day = minute_bars["HK.00700"].loc["2022-04-12"]
    sixty = resample_bars(one_day, Timeframe.parse("1M"), Timeframe.parse("60M"), HK)
    assert [t.strftime("%H:%M") for t in sixty.index] == ["10:30", "11:30", "12:00", "14:00", "15:00", "16:00"]
    two_h = resample_bars(one_day, Timeframe.parse("1M"), Timeframe.parse("120M"), HK)
    assert [t.strftime("%H:%M") for t in two_h.index] == ["11:30", "12:00", "15:00", "16:00"]
    assert two_h["volume"].sum() == pytest.approx(one_day["volume"].sum())
    first = one_day.loc[:"2022-04-12 11:30"]
    assert two_h["open"].iloc[0] == first["open"].iloc[0]  # auction bar joins the first chunk
    assert two_h["high"].iloc[0] == first["high"].max()


def test_futu_source_pages_through_history(fake_opend):
    gw = QuoteGateway(context_factory=fake_opend.quote_factory, limits={"history_kline": (1000, 1.0)})
    src = FutuSource(gw)
    bars = src.fetch_bars("HK.00700", "K_1M", "qfq", date(2024, 6, 3), date(2024, 6, 11))
    assert len(bars) == 7 * 331  # seven weekdays, more than one 1,000-bar page
    assert fake_opend.quote.calls.count("history:HK.00700:K_1M") >= 3
    assert bars.index.is_monotonic_increasing
    info = src.fetch_instruments(["HK.00700", "HK.00005"])
    assert info["HK.00005"].lot_size == 400
    q = src.quota()
    assert q.used == 1 and "HK.00700" in q.codes
    assert date(2024, 6, 8) not in src.trading_days("HK", date(2024, 6, 3), date(2024, 6, 14))


def test_gateway_retries_rate_limits_and_raises_on_quota():
    calls = {"n": 0}
    sleeps: list[float] = []

    class Ctx:
        def ping(self):
            calls["n"] += 1
            return (0, "ok") if calls["n"] >= 3 else (-1, "请求频率太高 too frequent")

        def quota(self):
            return (-1, "历史K线额度不足")

        def close(self):
            pass

    gw = QuoteGateway(context_factory=lambda h, p: Ctx(), sleep=sleeps.append)
    assert gw.call("default", "ping", lambda c: c.ping()) == (0, "ok")
    assert len(sleeps) == 2
    with pytest.raises(QuotaExceededError):
        gw.call("default", "quota", lambda c: c.quota())


def test_rate_limiter_sliding_window():
    t = {"now": 0.0}
    slept: list[float] = []

    def sleep(s):
        slept.append(s)
        t["now"] += s

    lim = RateLimiter(3, 10.0, clock=lambda: t["now"], sleep=sleep)
    for _ in range(3):
        lim.acquire()
    lim.acquire()
    assert slept and slept[0] == pytest.approx(10.05)


def test_load_bars_builds_non_native_timeframes(tmp_path, minute_bars):
    bars = minute_bars["HK.00700"]
    src = FakeSource(bars)
    dm = DataManager(ParquetStore(tmp_path), lambda: src, today=lambda tz: date(2022, 4, 14))
    out = dm.load_bars("HK.00700", Timeframe.parse("10M"), date(2022, 4, 12), date(2022, 4, 13))
    assert np.all(np.diff(out.index.asi8) > 0)
    assert out.index[0].strftime("%H:%M") == "09:40"
