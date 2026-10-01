from datetime import date

import pandas as pd
import pytest

from futu_algo.cli import main
from futu_algo.data import ParquetStore, SeriesKey
from futu_algo.data.store import Coverage, InstrumentInfo


@pytest.fixture
def workspace(tmp_path, minute_bars, daily_bars):
    """A config plus a pre-filled cache, so CLI commands run fully offline."""
    store = ParquetStore(tmp_path / "data")
    for sym, bars in minute_bars.items():
        store.write(SeriesKey(sym, "K_1M", "qfq"), bars, Coverage(date(2022, 4, 1), date(2022, 4, 13)), "fixture")
    for sym, bars in daily_bars.items():
        store.write(SeriesKey(sym, "K_DAY", "qfq"), bars, Coverage(date(2021, 1, 1), date(2021, 12, 31)), "fixture")
    store.write_instruments({s: InstrumentInfo(s, s, 100, "STOCK", None, "2099-01-01T00:00:00+00:00") for s in minute_bars})
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "data: {offline: true}\n"
        "backtest: {symbols: [HK.00700, HK.09988], timeframe: DAY, start: 2021-06-01, end: 2021-12-31, benchmark: null}\n"
        "trading: {universe: [HK.00700, HK.09988], timeframe: 1M, order: {price: market}, risk: {price_band_pct: 0.5}}\n"
        "logging: {dir: null}\n",
        encoding="utf-8",
    )
    return cfg


def test_init_writes_config_and_env_example(tmp_path, capsys):
    target = tmp_path / "new" / "config.yaml"
    assert main(["init", str(target)]) == 0
    assert target.is_file() and (target.parent / ".env.example").is_file()
    assert main(["init", str(target)]) == 1  # refuses to overwrite


def test_strategies_listing(capsys):
    assert main(["strategies"]) == 0
    out = capsys.readouterr().out
    assert "macd" in out and "donchian" in out


def test_backtest_offline(workspace, capsys, tmp_path):
    assert main(["backtest", "-c", str(workspace), "--offline", "-s", "rsi", "-p", "period=9"]) == 0
    out = capsys.readouterr().out
    assert "PORTFOLIO" in out and "{'period': 9" in out
    assert list((tmp_path / "reports").glob("*/result.json"))


def test_backtest_overrides_via_set(workspace, capsys):
    assert main(["backtest", "-c", str(workspace), "--offline", "--set", "backtest.mode=scan"]) == 0
    assert "COMPOSITE" in capsys.readouterr().out


def test_replay_runs_the_live_engine(workspace, capsys):
    rc = main(["replay", "-c", str(workspace), "--offline", "--start", "2022-04-12", "--end", "2022-04-13"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "fill(s); final equity" in out


def test_config_errors_are_reported_cleanly(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("trading: {sizing: {method: wrong}}\n", encoding="utf-8")
    assert main(["backtest", "-c", str(bad)]) == 2
    assert "trading.sizing" in capsys.readouterr().err


def test_web_refuses_public_bind_without_token(workspace, capsys, monkeypatch):
    monkeypatch.delenv("FUTU_ALGO_WEB_TOKEN", raising=False)
    assert main(["web", "-c", str(workspace), "--host", "0.0.0.0"]) == 1
    assert "token" in capsys.readouterr().err


def test_data_list(workspace, capsys):
    assert main(["data", "list", "-c", str(workspace)]) == 0
    out = capsys.readouterr().out
    assert "K_1M" in out and "HK.09988" in out
    pd.Timestamp.now()  # keep pandas import used
