"""The real Futu adapters (broker, source, feed, screener) against the simulated OpenD."""

import time
from datetime import date

import pandas as pd
import pytest

from futu_algo.app import App, wait_for
from futu_algo.config import ScreenFilter, ScreenPreset, StrategySpec
from futu_algo.demo import build_demo_app
from futu_algo.errors import BrokerError, ConfigError
from futu_algo.futu_gateway import QuoteGateway
from futu_algo.live.futu_broker import FutuBroker, FutuQuoteProvider
from futu_algo.live.models import OrderRequest, OrderState
from futu_algo.screener import Screener, build_futu_filter

from .conftest import HK_TZ


def _broker(fake, env="SIMULATE", **kw):
    b = FutuBroker(host="h", port=1, env=env, context_factory=fake.trade_factory, **kw)
    b.connect()
    return b


def test_broker_picks_the_simulate_hk_account(fake_opend):
    b = _broker(fake_opend)
    assert b.acc_id == 1001
    acct = b.account()
    assert acct.equity == pytest.approx(1_000_000) and acct.currency == "HKD"


def test_real_account_requires_password(fake_opend):
    with pytest.raises(BrokerError, match="password"):
        _broker(fake_opend, env="REAL")
    assert _broker(fake_opend, env="REAL", password_md5="x").acc_id == 9999


def test_broker_orders_positions_and_cancel(fake_opend):
    b = _broker(fake_opend)
    quotes = FutuQuoteProvider(QuoteGateway(context_factory=fake_opend.quote_factory)).quotes(["HK.00700"])
    q = quotes["HK.00700"]
    assert q.ask > q.bid > 0
    filled = b.place(OrderRequest("HK.00700", "BUY", 200, q.ask + 1, remark="futu_algo:1"))
    assert filled.state == OrderState.FILLED and filled.filled_qty == 200
    pos = b.positions()["HK.00700"]
    assert pos.quantity == 200 and pos.can_sell == 200
    resting = b.place(OrderRequest("HK.00700", "SELL", 100, q.ask * 1.2))
    assert resting.state == OrderState.SUBMITTED
    b.cancel(resting.order_id)
    states = {o.order_id: o.state for o in b.orders()}
    assert states[resting.order_id] == OrderState.CANCELLED
    assert next(o.remark for o in b.orders()) == "futu_algo:1"
    with pytest.raises(BrokerError):
        b.place(OrderRequest("HK.00700", "BUY", 150, q.ask))  # not a board lot


def test_screener_server_side_and_confirmation(fake_opend, tmp_path):
    from futu_algo.data import DataManager, FutuSource, ParquetStore

    gw = QuoteGateway(context_factory=fake_opend.quote_factory, limits={"history_kline": (1000, 1.0)})
    dm = DataManager(ParquetStore(tmp_path / "data"), lambda: FutuSource(gw), today=lambda tz: date(2024, 6, 12))
    screener = Screener(gw, dm, None, tmp_path / "screens")
    preset = ScreenPreset(filters=[ScreenFilter(kind="simple", field="CUR_PRICE", min=50)], max_results=50)
    result = screener.run("px50", preset)
    assert result.rows and all(r["last_price"] >= 50 for r in result.rows)
    assert (tmp_path / "screens").glob("*.csv")
    confirmed = screener.run("macd", preset.model_copy(update={"confirm_strategy": StrategySpec(name="macd"), "max_confirm": 3}))
    assert len(confirmed.rows) <= 3
    assert all(r["signal"] in ("long", "buy today") for r in confirmed.rows)


def test_filter_translation_covers_every_kind():
    import futu

    kinds = [
        ScreenFilter(kind="simple", field="CUR_PRICE", min=1, sort="desc"),
        ScreenFilter(kind="accumulate", field="TURNOVER", min=1e8, days=10),
        ScreenFilter(kind="financial", field="RETURN_ON_EQUITY_RATE", min=12, quarter="annual"),
        ScreenFilter(kind="pattern", field="MA_ALIGNMENT_LONG", ktype="K_DAY"),
        ScreenFilter(kind="indicator", field="MA", field2="MA", relative_position="CROSS_UP", field1_params=[5], field2_params=[20]),
    ]
    built = [build_futu_filter(k) for k in kinds]
    assert isinstance(built[0], futu.SimpleFilter) and built[0].sort == futu.SortDir.DESCEND
    assert built[1].days == 10 and built[2].quarter == "ANNUAL"
    assert isinstance(built[3], futu.PatternFilter) and isinstance(built[4], futu.CustomIndicatorFilter)
    with pytest.raises(ConfigError):
        build_futu_filter(ScreenFilter(kind="simple", field="NOT_A_FIELD"))


def test_full_app_trades_on_simulated_opend(tmp_path):
    """Engine thread + K-line pushes + Futu broker + notifier, on a fast virtual clock."""
    start = pd.Timestamp("2024-06-12 10:00", tz=HK_TZ).to_pydatetime()
    app, opend, _clock = build_demo_app(tmp_path, speed=120, start=start)
    app.start_services(scheduler=False)
    try:
        engine = app.start_engine()
        assert engine.state == "running"
        assert wait_for(lambda: any(s["bars"] > 0 for s in engine.status()["symbols"]), 10)
        before = {s["symbol"]: s["last_bar"]["time"] for s in engine.status()["symbols"] if s["last_bar"]}
        assert wait_for(lambda: any((s["last_bar"] or {}).get("time") != before.get(s["symbol"]) for s in engine.status()["symbols"]), 20)
        assert wait_for(lambda: len(app.state.signals(1000)) > 0, 20)
        engine.halt("test halt")
        assert engine.status()["halted"]
        engine.resume()
        st = engine.status()
        assert st["account"]["equity"] > 0 and st["env"] == "SIMULATE"
        assert opend.quote.subscriptions
    finally:
        app.shutdown()
    assert app.engine.state == "stopped"


def test_real_env_is_gated(tmp_path, monkeypatch):
    from futu_algo.config import parse_config

    cfg = parse_config({"trading": {"env": "REAL", "universe": ["HK.00700"]}}, tmp_path)
    app = App(cfg)
    with pytest.raises(ConfigError, match="allow_real"):
        app.build_engine()
    monkeypatch.setenv("FUTU_ALGO_ALLOW_REAL", "1")
    cfg2 = parse_config({"trading": {"env": "REAL", "allow_real": True, "universe": ["HK.00700"]}}, tmp_path)
    App(cfg2).check_real_allowed()  # no exception


def test_scheduler_runs_jobs_once_per_day(tmp_path):
    from futu_algo.app import Scheduler
    from futu_algo.config import parse_config

    cfg = parse_config({
        "screener": {"presets": {"p": {"filters": []}}, "schedule": [{"preset": "p", "at": "08:45", "notify": False}]},
        "schedule": {"refresh_instruments": None, "daily_summary": "16:20"},
        "data": {"offline": True},
    }, tmp_path)
    app = App(cfg)
    ran: list[str] = []
    sched = Scheduler(app)
    sched.jobs_for_today = lambda: [("screen:p", pd.Timestamp("08:45").time(), lambda: ran.append("screen"))]  # type: ignore[method-assign]
    at = pd.Timestamp("2024-06-12 08:46", tz=HK_TZ).to_pydatetime()
    assert sched.run_due(at) == ["screen:p"]
    assert sched.run_due(at) == []
    assert sched.run_due(pd.Timestamp("2024-06-15 08:46", tz=HK_TZ).to_pydatetime()) == []  # Saturday
    time.sleep(0.3)
    assert ran == ["screen"]
    app.shutdown()


def test_job_errors_hide_unexpected_exception_details():
    from futu_algo.app import JobManager
    from futu_algo.errors import DataError

    jobs = JobManager()

    def boom(_job):
        raise RuntimeError("secret /home/user/path detail")

    def domain(_job):
        raise DataError("No bars for HK.00700")

    a, b = jobs.submit("backtest", "a", boom), jobs.submit("backtest", "b", domain)
    assert wait_for(lambda: a.status == "failed" and b.status == "failed", 5)
    assert "secret" not in a.error and "server log" in a.error
    assert b.error == "No bars for HK.00700"
    jobs.shutdown()
