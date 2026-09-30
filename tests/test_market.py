from datetime import date, time

import pandas as pd
import pytest

from futu_algo.errors import ConfigError
from futu_algo.market import (
    HKCostModel,
    Instrument,
    Phase,
    TradingCalendar,
    normalize_symbol,
    round_to_tick,
    session_phase,
    shift_ticks,
    tick_size,
)
from futu_algo.market.calendar import minutes_to_close
from futu_algo.market.instrument import MARKETS
from futu_algo.timeframe import Timeframe

HK = MARKETS["HK"]
TENCENT = Instrument("HK.700", 100)


def test_symbols_are_normalised():
    assert normalize_symbol("hk.700") == "HK.00700"
    assert TENCENT.symbol == "HK.00700"
    assert normalize_symbol("US.aapl") == "US.AAPL"
    with pytest.raises(ConfigError):
        normalize_symbol("700.HK")
    with pytest.raises(ConfigError):
        normalize_symbol("SZ.000001")


@pytest.mark.parametrize(
    ("price", "when", "tick"),
    [
        (0.2, date(2024, 1, 2), 0.001),
        (9.99, date(2024, 1, 2), 0.01),
        (15.0, date(2024, 1, 2), 0.02),
        (15.0, date(2025, 8, 4), 0.01),  # 2025 reform: HK$10-20 band narrowed
        (45.0, date(2025, 8, 4), 0.02),
        (5.0, date(2026, 8, 3), 0.005),  # 2026 reform: HK$0.50-10 band narrowed
        (420.0, date(2024, 1, 2), 0.2),
    ],
)
def test_hk_tick_table_by_date(price, when, tick):
    assert tick_size(price, TENCENT, when) == tick


def test_round_to_tick_directions():
    d = date(2024, 1, 2)
    assert round_to_tick(420.13, TENCENT, d, "up") == 420.2
    assert round_to_tick(420.13, TENCENT, d, "down") == 420.0
    assert round_to_tick(420.0, TENCENT, d, "up") == 420.0


def test_shift_ticks_crosses_band_boundaries():
    d = date(2024, 1, 2)
    assert shift_ticks(10.0, 1, TENCENT, d) == 10.02  # above HK$10 the tick is 0.02
    assert shift_ticks(10.02, -1, TENCENT, d) == 10.0
    assert shift_ticks(10.0, -1, TENCENT, d) == 9.99
    assert shift_ticks(420.0, 2, TENCENT, d) == 420.4


def test_hk_costs_line_by_line():
    model = HKCostModel()
    buy = model.fees("BUY", 100, 200.0, TENCENT, date(2025, 9, 1))  # HK$20,000
    assert buy.commission == 6.0  # 0.03%, above the HK$3 minimum
    assert buy.platform == 15.0
    assert buy.stamp_duty == 20.0  # 0.1%, rounded up to whole dollars
    assert buy.exchange == pytest.approx(1.13)  # 0.00565%
    assert buy.levies == pytest.approx(0.54 + 0.03)  # SFC 0.0027% + AFRC 0.00015%
    assert buy.settlement == pytest.approx(0.84)  # 0.0042% since 2025-06-30
    assert buy.total == pytest.approx(43.54)
    odd = model.fees("BUY", 100, 200.01, TENCENT, date(2025, 9, 1))
    assert odd.stamp_duty == 21.0  # any fraction of a dollar rounds up


def test_hk_settlement_schedule_change():
    model = HKCostModel()
    before = model.fees("BUY", 100, 200.0, TENCENT, date(2025, 6, 27))
    after = model.fees("BUY", 100, 200.0, TENCENT, date(2025, 7, 2))
    assert before.settlement == 2.0  # 0.002% = 0.40, lifted to the HK$2 minimum
    assert after.settlement == pytest.approx(0.84)  # 0.0042%, no minimum


def test_stamp_duty_rate_2022_and_etf_exemption():
    model = HKCostModel()
    assert model.fees("SELL", 100, 200.0, TENCENT, date(2022, 6, 1)).stamp_duty == 26.0  # 0.13%
    etf = Instrument("HK.02800", 500, security_type="ETF")
    assert model.fees("BUY", 500, 20.0, etf, date(2024, 1, 2)).stamp_duty == 0.0


@pytest.mark.parametrize(
    ("clock", "phase"),
    [
        ("09:10", Phase.PRE_OPEN),
        ("09:30", Phase.CONTINUOUS),
        ("11:59", Phase.CONTINUOUS),
        ("12:30", Phase.LUNCH),
        ("13:00", Phase.CONTINUOUS),
        ("16:05", Phase.CLOSING_AUCTION),
        ("16:30", Phase.AFTER_HOURS),
        ("08:00", Phase.CLOSED),
    ],
)
def test_session_phase(clock, phase):
    now = pd.Timestamp(f"2024-06-12 {clock}", tz="Asia/Hong_Kong").to_pydatetime()
    assert session_phase(now, HK) == phase
    assert session_phase(now, HK, is_trading_day=False) == Phase.CLOSED


def test_calendar_uses_loader_and_falls_back_to_weekdays():
    holiday = date(2024, 6, 10)  # Tuen Ng Festival

    def loader(a, b):
        days = pd.bdate_range(a, b).date
        return [d for d in days if d != holiday]

    cal = TradingCalendar(HK, loader)
    assert not cal.is_trading_day(holiday)
    assert cal.is_trading_day(date(2024, 6, 11))
    assert cal.next_trading_day(date(2024, 6, 7)) == date(2024, 6, 11)

    def broken(a, b):
        raise RuntimeError("OpenD down")

    fallback = TradingCalendar(HK, broken)
    assert fallback.is_trading_day(holiday)  # weekday fallback
    assert not fallback.is_trading_day(date(2024, 6, 15))


def test_minutes_to_close():
    now = pd.Timestamp("2024-06-12 15:50", tz="Asia/Hong_Kong").to_pydatetime()
    assert minutes_to_close(now, HK) == pytest.approx(10)


def test_timeframes():
    assert str(Timeframe.parse("K_5M")) == "5M"
    assert str(Timeframe.parse("2h")) == "120M"
    assert Timeframe.parse("10M").base == Timeframe.parse("5M")
    assert Timeframe.parse("120M").base == Timeframe.parse("60M")
    assert Timeframe.parse("DAY").futu_ktype == "K_DAY"
    assert Timeframe.parse("1M").futu_ktype == "K_1M"
    assert HK.bars_per_day(60) == 6  # 10:30 11:30 12:00 14:00 15:00 16:00
    assert HK.open_time == time(9, 30)
    with pytest.raises(ConfigError):
        Timeframe.parse("7X")
