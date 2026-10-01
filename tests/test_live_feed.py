import pandas as pd

from futu_algo.live.feed import Bar, BarAssembler, bar_end, split_in_progress
from futu_algo.market.instrument import MARKETS
from futu_algo.timeframe import Timeframe

HK = MARKETS["HK"]
TZ = HK.tz


def _bar(t: str, close: float = 10.0, sym: str = "HK.00700", vol: float = 100) -> Bar:
    ts = pd.Timestamp(t, tz=TZ)
    return Bar(sym, ts, close, close + 0.1, close - 0.1, close, vol, vol * close)


def _now(t: str):
    return pd.Timestamp(t, tz=TZ).to_pydatetime()


def test_bar_completes_when_next_bar_arrives():
    a = BarAssembler(Timeframe.parse("1M"), HK)
    assert a.update(_bar("2024-06-12 10:01", 10.0)) == []
    assert a.update(_bar("2024-06-12 10:01", 10.2)) == []  # in-progress update
    done = a.update(_bar("2024-06-12 10:02", 10.3))
    assert [b.time.strftime("%H:%M") for b in done] == ["10:01"]
    assert done[0].close == 10.2


def test_bar_completes_by_clock_at_lunch_and_late_updates_are_ignored():
    a = BarAssembler(Timeframe.parse("1M"), HK, grace_seconds=2)
    a.update(_bar("2024-06-12 12:00", 10.0))
    assert a.tick(_now("2024-06-12 12:00:01")) == []
    done = a.tick(_now("2024-06-12 12:00:03"))
    assert [b.time.strftime("%H:%M") for b in done] == ["12:00"]
    assert a.update(_bar("2024-06-12 12:00", 11.0)) == []  # late push for a final bar
    assert a.tick(_now("2024-06-12 12:30")) == []


def test_resampled_bars_follow_session_buckets():
    a = BarAssembler(Timeframe.parse("10M"), HK, grace_seconds=1)
    out = []
    for m in range(31, 60):
        out += a.update(_bar(f"2024-06-12 09:{m:02d}", 10 + m / 100))
    out += a.update(_bar("2024-06-12 10:00", 11.0))
    labels = [b.time.strftime("%H:%M") for b in out]
    assert labels == ["09:40", "09:50"]
    out = a.tick(_now("2024-06-12 10:00:02"))
    assert [b.time.strftime("%H:%M") for b in out] == ["10:00"]
    first = [b for b in out]
    assert first[0].close == 11.0


def test_resampled_bucket_flushes_at_lunch_boundary():
    a = BarAssembler(Timeframe.parse("60M"), HK, grace_seconds=1)
    for m in range(31, 60):
        a.update(_bar(f"2024-06-12 11:{m:02d}"))
    a.update(_bar("2024-06-12 12:00"))
    out = a.tick(_now("2024-06-12 12:00:02"))
    assert [b.time.strftime("%H:%M") for b in out] == ["12:00"]


def test_daily_bar_end_and_split():
    tf = Timeframe.parse("DAY")
    end = bar_end(pd.Timestamp("2024-06-12", tz=TZ), tf, HK)
    assert end == pd.Timestamp("2024-06-12 16:10", tz=TZ)  # after the closing auction
    idx = pd.DatetimeIndex([pd.Timestamp("2024-06-11", tz=TZ), pd.Timestamp("2024-06-12", tz=TZ)], name="time")
    bars = pd.DataFrame({"open": [1, 2], "high": [1, 2], "low": [1, 2], "close": [1, 2], "volume": [1, 1], "turnover": [1, 1]}, index=idx)
    done, live = split_in_progress(bars, tf, HK, _now("2024-06-12 15:00"), 2)
    assert len(done) == 1 and len(live) == 1


def test_symbols_are_independent():
    a = BarAssembler(Timeframe.parse("1M"), HK)
    a.update(_bar("2024-06-12 10:01", sym="HK.00700"))
    assert a.update(_bar("2024-06-12 10:02", sym="HK.09988")) == []
    assert len(a.update(_bar("2024-06-12 10:02", sym="HK.00700"))) == 1
