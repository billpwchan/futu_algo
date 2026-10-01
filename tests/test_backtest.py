import json
from datetime import date

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from futu_algo.backtest import COMPOSITE, PORTFOLIO, run_on_bars, save_result
from futu_algo.backtest.runner import result_payload
from futu_algo.config import BacktestConfig, CostsConfig
from futu_algo.market.instrument import Instrument
from futu_algo.strategy import create_strategy

from .conftest import synthetic_bars


def _bt(**kw):
    base = {"symbols": ["HK.00700"], "timeframe": "DAY", "start": date(2023, 3, 1), "end": date(2024, 6, 30),
            "capital": 1_000_000, "benchmark": None, "execution": {"slippage_ticks": 0}}
    base.update(kw)
    return BacktestConfig.model_validate(base)


def _run(bt, bars, strategy="macd", inst=None, costs=None):
    inst = inst or {s: Instrument(s, 100) for s in bars}
    return run_on_bars(bt, costs or CostsConfig(), create_strategy(strategy), bars, inst)


def test_fills_are_next_open_in_whole_lots():
    bars = {"HK.00700": synthetic_bars(400)}
    res = _run(_bt(), bars)
    book = res.main
    closes = bars["HK.00700"]
    _, sig = create_strategy("macd").run(closes)
    assert book.fills
    for f in book.fills:
        assert f.quantity % 100 == 0
        i = closes.index.get_loc(f.time)
        assert f.price == pytest.approx(closes["open"].iloc[i])  # no slippage configured
        assert not np.isnan(sig.iloc[i - 1])  # decided on the previous bar


def test_accounting_identity_and_no_negative_cash():
    bars = {s: synthetic_bars(400, seed=i) for i, s in enumerate(["HK.00700", "HK.09988", "HK.00005"])}
    res = _run(_bt(symbols=list(bars), sizing={"method": "equal_weight", "max_positions": 2}), bars)
    book = res.books[PORTFOLIO]
    assert (book.cash >= -1e-6).all()
    fees = sum(f.fees.total for f in book.fills)
    flows = sum(f.cash_delta for f in book.fills)
    assert book.cash.iloc[-1] == pytest.approx(1_000_000 + flows)
    assert fees > 0
    held = pd.Series(0.0, index=book.equity.index)
    assert (book.equity >= book.cash - 1e-6).all()
    assert len(held) == len(book.equity)


def test_scan_mode_builds_composite():
    bars = {s: synthetic_bars(300, seed=i) for i, s in enumerate(["HK.00700", "HK.09988"])}
    res = _run(_bt(symbols=list(bars), mode="scan", start=date(2023, 2, 1)), bars)
    assert set(res.books) == {"HK.00700", "HK.09988", COMPOSITE}
    assert res.primary == COMPOSITE


def test_stop_loss_exits():
    bars = {"HK.00700": synthetic_bars(400, seed=3)}
    res = _run(_bt(exits={"stop_loss": 0.02}), bars)
    reasons = {t.exit_reason for t in res.main.trades if not t.is_open}
    assert "stop_loss" in reasons


def test_payload_is_json_and_report_saved(tmp_path, minute_bars, instruments):
    bt = _bt(symbols=list(minute_bars), timeframe="1M", start=date(2022, 4, 12), end=date(2022, 4, 13))
    res = run_on_bars(bt, CostsConfig(), create_strategy("kdj"), minute_bars, instruments)
    payload = result_payload(res)
    text = json.dumps(payload)
    assert "NaN" not in text
    assert payload["books"][PORTFOLIO]["equity"]
    assert payload["symbols"]["HK.00700"]["candles"][0]["time"] > 0
    out = save_result(res, tmp_path)
    assert (out / "result.json").is_file() and (out / "trades.csv").is_file()


def test_intraday_warmup_starts_at_requested_day(minute_bars, instruments):
    bt = _bt(symbols=["HK.00700"], timeframe="1M", start=date(2022, 4, 12), end=date(2022, 4, 13))
    res = run_on_bars(bt, CostsConfig(), create_strategy("macd"), {"HK.00700": minute_bars["HK.00700"]}, instruments)
    first = res.books[PORTFOLIO].equity.index[0]
    assert first.date() == date(2022, 4, 12)
    assert not res.warnings


@settings(max_examples=25, deadline=None)
@given(seed=st.integers(0, 10_000), slippage=st.integers(0, 3), method=st.sampled_from(["equal_weight", "percent_equity", "fixed_lots"]))
def test_property_cash_never_negative(seed, slippage, method):
    bars = {s: synthetic_bars(260, seed=seed + i) for i, s in enumerate(["HK.00700", "HK.09988"])}
    sizing = {"method": method, "max_positions": 2}
    if method == "percent_equity":
        sizing["percent"] = 0.6
    if method == "fixed_lots":
        sizing["lots"] = 30
    res = _run(_bt(symbols=list(bars), start=date(2023, 2, 1), sizing=sizing, execution={"slippage_ticks": slippage}), bars, "ema_ribbon")
    book = res.books[PORTFOLIO]
    assert (book.cash >= -1e-6).all()
    for f in book.fills:
        assert f.quantity > 0 and f.quantity % 100 == 0
