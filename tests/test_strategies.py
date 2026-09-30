import numpy as np
import pandas as pd
import pytest

from futu_algo.errors import StrategyError
from futu_algo.indicators import CROSS, EMA, KDJ, MACD, RSI, SMA, ZIG
from futu_algo.strategy import available, check_lookahead, create_strategy, events
from futu_algo.strategy.registry import get_strategy_class

from .conftest import synthetic_bars


def test_sma_is_tdx_recursive_smoothing():
    x = pd.Series([10.0, 20.0, 30.0])
    # Y1 = X1; Y2 = (1*20 + 2*10)/3; Y3 = (1*30 + 2*Y2)/3
    y2 = (20 + 2 * 10) / 3
    assert SMA(x, 3, 1).tolist() == pytest.approx([10.0, y2, (30 + 2 * y2) / 3])
    with pytest.raises(ValueError):
        SMA(x, 3, 4)


def test_macd_matches_hand_computation():
    close = pd.Series(np.linspace(10, 20, 60))
    m = MACD(close, 12, 26, 9)
    dif = EMA(close, 12) - EMA(close, 26)
    assert m["dif"].tolist() == pytest.approx(dif.tolist())
    assert m["macd"].tolist() == pytest.approx((2 * (dif - EMA(dif, 9))).tolist())


def test_kdj_and_rsi_ranges():
    bars = synthetic_bars(200)
    k = KDJ(bars["high"], bars["low"], bars["close"])
    assert k["k"].dropna().between(0, 100).all() and k["k"].notna().sum() > 150
    r = RSI(bars["close"], 6).dropna()
    assert r.between(0, 100).all()


def test_cross_only_on_the_crossing_bar():
    a = pd.Series([1, 2, 3, 2, 1, 2, 3.0])
    b = pd.Series(2.0, index=a.index)
    assert CROSS(a, b).tolist() == [False, False, True, False, False, False, True]


@pytest.mark.parametrize("name", sorted(available()))
def test_builtin_strategies_are_causal(name):
    strategy = create_strategy(name)
    bars = synthetic_bars(max(400, strategy.warmup_bars() * 3))
    report = check_lookahead(strategy, bars, checkpoints=8)
    assert report.ok, report.summary()
    ind, sig = strategy.run(bars)
    assert set(sig.dropna().unique()) <= {0.0, 1.0}
    assert ind.index.equals(bars.index)


def test_zig_is_detected_as_future_function():
    from futu_algo.strategy import Strategy, StrategyParams

    class Zigzag(Strategy):
        name = "zig_test"
        Params = StrategyParams

        def indicators(self, bars):
            return pd.DataFrame({"zig": ZIG(bars["close"], 5)}, index=bars.index)

        def signals(self, bars, ind):
            z = ind["zig"]
            return events(z > z.shift(1), z < z.shift(1))

    assert not check_lookahead(Zigzag(), synthetic_bars(300)).ok


def test_parameter_validation():
    with pytest.raises(StrategyError):
        create_strategy("macd", {"fast_period": 30, "slow_period": 26})
    with pytest.raises(StrategyError):
        create_strategy("macd", {"nope": 1})
    with pytest.raises(StrategyError):
        get_strategy_class("does_not_exist")
    assert create_strategy("kdj", {"over_sell": 25}).params.over_sell == 25


def test_ema_ribbon_trades_now(minute_bars):
    """The 1.x EMA_Ribbon compared a bar with itself and never fired; the fix must."""
    _, sig = create_strategy("ema_ribbon").run(minute_bars["HK.09988"])
    assert (sig == 1).sum() > 5 and (sig == 0).sum() > 5


def test_decide_last_equals_full_run_value(minute_bars):
    bars = minute_bars["HK.00700"]
    strategy = create_strategy("macd")
    _, full = strategy.run(bars)
    for i in (200, 400, 700, len(bars) - 1):
        got = strategy.decide_last(bars.iloc[: i + 1])
        want = full.iloc[i]
        assert (np.isnan(got) and np.isnan(want)) or got == want


def test_user_strategy_file(tmp_path):
    from futu_algo.strategy.registry import load_strategy_paths

    (tmp_path / "mine.py").write_text(
        "import pandas as pd\n"
        "from futu_algo.strategy import Strategy, StrategyParams, state\n"
        "from futu_algo.indicators import MA\n"
        "class Above(Strategy):\n"
        "    name = 'above_ma_test'\n"
        "    Params = StrategyParams\n"
        "    def indicators(self, bars):\n"
        "        return pd.DataFrame({'ma': MA(bars['close'], 5)}, index=bars.index)\n"
        "    def signals(self, bars, ind):\n"
        "        return state((bars['close'] > ind['ma']).where(ind['ma'].notna()))\n",
        encoding="utf-8",
    )
    load_strategy_paths([tmp_path])
    s = create_strategy("above_ma_test")
    _, sig = s.run(synthetic_bars(30))
    assert sig.notna().sum() == 26
