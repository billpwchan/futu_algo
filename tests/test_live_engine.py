from datetime import date

import pandas as pd
import pytest

from futu_algo.backtest import run_on_bars
from futu_algo.config import BacktestConfig
from futu_algo.live.feed import Bar
from futu_algo.live.replay import replay
from futu_algo.strategy import create_strategy

SYMS = ["HK.00700", "HK.09988"]
START = pd.Timestamp("2022-04-12", tz="Asia/Hong_Kong")


def _trading(make_config, name="macd", **extra):
    cfg = {
        "universe": SYMS, "timeframe": "1M", "strategy": {"name": name},
        "sizing": {"method": "fixed_lots", "lots": 1, "max_positions": 5},
        "order": {"price": "market"}, "risk": {"price_band_pct": 0.5},
    }
    cfg.update(extra)
    return make_config({"trading": cfg})


@pytest.mark.parametrize("strategy", ["macd", "kdj", "rsi", "ema_ribbon", "boll"])
def test_live_engine_matches_backtest_fill_for_fill(make_config, minute_bars, instruments, strategy):
    """The central guarantee: the live engine trades exactly what the backtest traded."""
    cfg = _trading(make_config, strategy)
    live = replay(cfg, minute_bars, instruments, start=START)
    bt = BacktestConfig(
        symbols=SYMS, timeframe="1M", start=date(2022, 4, 12), end=date(2022, 4, 13), capital=1e6,
        benchmark=None, sizing={"method": "fixed_lots", "lots": 1, "max_positions": 5}, execution={"slippage_ticks": 0},
    )
    back = run_on_bars(bt, cfg.costs, create_strategy(strategy), minute_bars, instruments).main
    want = [(f.symbol, f.side, f.quantity, pd.Timestamp(f.time), round(f.price, 4)) for f in back.fills]
    got = [(f["symbol"], f["side"], f["quantity"], pd.Timestamp(f["time"]), round(f["price"], 4)) for f in live.fills]
    assert got == want
    assert live.broker.fees_paid == pytest.approx(sum(f.fees.total for f in back.fills))
    assert live.broker.account().equity == pytest.approx(back.equity.iloc[-1], rel=1e-9)


def test_decisions_match_backtest_signals(make_config, minute_bars, instruments):
    cfg = _trading(make_config, "macd")
    live = replay(cfg, minute_bars, instruments, start=START)
    _, sig = create_strategy("macd").run(minute_bars["HK.00700"])
    for d in [d for d in live.decisions if d.symbol == "HK.00700" and d.action != "warmup"]:
        want = sig.loc[d.bar_time]
        assert (pd.isna(want) and pd.isna(d.signal)) or want == d.signal


def test_fresh_signal_required_after_start(make_config, minute_bars, instruments):
    """A state-style strategy that is already long at start waits for the signal to reset."""
    cfg = _trading(make_config, "ma_cross", strategy={"name": "ma_cross", "params": {"short_window": 5, "long_window": 20, "mode": "state"}})
    live = replay(cfg, minute_bars, instruments, start=START)
    first_buy = next(d for d in live.decisions if d.action == "buy")
    earlier = [d for d in live.decisions if d.symbol == first_buy.symbol and d.bar_time < first_buy.bar_time and d.action == "hold"]
    assert any(d.signal == 0.0 for d in earlier) or any("fresh" in d.detail for d in earlier)


def test_max_positions_skips_extra_entries(make_config, minute_bars, instruments):
    cfg = _trading(make_config, "ema_ribbon", sizing={"method": "fixed_lots", "lots": 1, "max_positions": 1})
    live = replay(cfg, minute_bars, instruments, start=START)
    assert any(d.action == "skip" and "max_positions" in d.detail for d in live.decisions)
    held = {}
    for f in live.fills:
        held[f["symbol"]] = held.get(f["symbol"], 0) + (f["quantity"] if f["side"] == "BUY" else -f["quantity"])
        assert sum(1 for q in held.values() if q > 0) <= 1


def test_stop_loss_exit_and_block(make_config, minute_bars, instruments):
    cfg = _trading(make_config, "ema_ribbon", exits={"stop_loss": 0.001})
    live = replay(cfg, minute_bars, instruments, start=START)
    reasons = {d.detail for d in live.decisions if d.action == "sell"}
    assert "stop_loss" in reasons


def test_halt_blocks_entries_but_not_exits(make_config, minute_bars, instruments):
    cfg = _trading(make_config, "ema_ribbon")
    live = replay(cfg, {k: v.loc[:"2022-04-12 11:00"] for k, v in minute_bars.items()}, instruments, start=START)
    eng = live.engine
    eng.halt("test")
    assert eng.store.get("halted") is True
    sym = "HK.09988"
    bar = eng.last_bar[sym]
    nxt = Bar(sym, bar.time + pd.Timedelta(minutes=1), bar.close, bar.close * 1.01, bar.close * 0.99, bar.close * 1.005)
    d = eng.on_bar(nxt)
    assert d.action in ("hold", "skip", "sell", "cancel")
    assert d.action != "buy"


def test_flatten_and_state_persist(make_config, minute_bars, instruments, tmp_path):
    db = str(tmp_path / "state.sqlite")
    cfg = _trading(make_config, "ema_ribbon")
    live = replay(cfg, {k: v.loc[:"2022-04-12 10:30"] for k, v in minute_bars.items()}, instruments, start=START, store_path=db)
    eng = live.engine
    eng.refresh_account()
    held = [s for s, p in eng.positions.items() if p.quantity > 0]
    n = eng.flatten()
    assert n == len(held)
    assert all(i.side == "SELL" for i in eng.executor.working())
    assert eng.store.get("blocked")


def test_daily_loss_halts(make_config, minute_bars, instruments):
    cfg = _trading(make_config, "ema_ribbon", risk={"price_band_pct": 0.5, "max_daily_loss": 1.0},
                   sizing={"method": "fixed_lots", "lots": 20, "max_positions": 5})
    live = replay(cfg, minute_bars, instruments, start=START)
    assert live.engine.halted or any(e["kind"] == "risk" for e in live.events)
