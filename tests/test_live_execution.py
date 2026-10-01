from datetime import timedelta

import pandas as pd
import pytest

from futu_algo.backtest.runner import build_cost_model
from futu_algo.config import CostsConfig, OrderConfig, RiskConfig
from futu_algo.errors import RiskRejected
from futu_algo.events import EventBus
from futu_algo.live.executor import OrderExecutor, limit_price
from futu_algo.live.models import AccountSnapshot, OrderRequest, PositionInfo, Quote
from futu_algo.live.risk import RiskContext, RiskManager
from futu_algo.live.sim_broker import SimBroker
from futu_algo.live.store import StateStore
from futu_algo.market.calendar import Phase
from futu_algo.market.instrument import MARKETS, Instrument

HK = MARKETS["HK"]
INST = {"HK.00700": Instrument("HK.00700", 100), "HK.09988": Instrument("HK.09988", 100)}


def _ts(t: str):
    return pd.Timestamp(t, tz=HK.tz).to_pydatetime()


class Env:
    def __init__(self, clock, *, order=None, risk=None, cash=1_000_000.0):
        self.clock = clock
        self.broker = SimBroker(cash, build_cost_model(CostsConfig()), INST.__getitem__, fill_mode="quote", clock=clock)
        self.store = StateStore(":memory:")
        self.bus = EventBus()
        self.risk = RiskManager(risk or RiskConfig(price_band_pct=0.2), HK)
        self.phase = Phase.CONTINUOUS
        self.halted = False
        self.executor = OrderExecutor(
            self.broker, self.broker, self.store, self.bus, self.risk, order or OrderConfig(),
            INST.__getitem__, self.context, env="DRY_RUN",
        )

    def context(self, symbol, quote):
        return RiskContext(
            now=self.clock(), phase=self.phase, account=self.broker.account(), positions=self.broker.positions(),
            working_buy_value=0.0, quote=quote, orders_today=0, day_start_equity=None, halted=self.halted,
        )

    def quote(self, sym, bid, ask, last=None):
        self.broker.on_quote(Quote(sym, last=last or (bid + ask) / 2, bid=bid, ask=ask))


def test_limit_price_rounds_to_ticks():
    q = Quote("HK.00700", last=420.1, bid=420.0, ask=420.13)
    inst = INST["HK.00700"]
    now = _ts("2024-06-12 10:00")
    assert limit_price("BUY", q, inst, OrderConfig(), now) == 420.2
    assert limit_price("SELL", q, inst, OrderConfig(), now) == 420.0
    assert limit_price("BUY", q, inst, OrderConfig(extra_ticks=2), now) == 420.6
    assert limit_price("BUY", q, inst, OrderConfig(price="passive"), now) == 420.0
    assert limit_price("BUY", q, inst, OrderConfig(price="market"), now) is None


def test_intent_fills_once_and_is_recorded(clock):
    env = Env(clock)
    env.quote("HK.00700", 420.0, 420.2)
    iid = env.executor.submit("HK.00700", "BUY", 300, "signal")
    env.executor.sync(clock())
    fills = env.store.fills()
    assert len(fills) == 1 and fills[0]["quantity"] == 300 and fills[0]["price"] == 420.2
    assert iid not in env.executor.intents
    env.executor.sync(clock())  # a second sync must not duplicate the fill
    assert len(env.store.fills()) == 1
    assert env.broker.positions()["HK.00700"].quantity == 300
    kinds = [e.kind for e in env.bus.recent()]
    assert kinds.index("order") < kinds.index("fill")


def test_unfilled_orders_are_repriced_then_abandoned(clock):
    env = Env(clock, order=OrderConfig(price="passive", timeout_seconds=10, max_replaces=1))
    env.quote("HK.00700", 420.0, 420.4)
    env.executor.submit("HK.00700", "BUY", 100, "signal")
    env.executor.sync(clock())
    first = next(iter(env.executor.intents.values()))
    assert first.attempts == 1 and first.order_id
    clock.set(clock.now + timedelta(seconds=11))
    env.executor.sync(clock())  # timeout -> cancel
    env.executor.sync(clock())  # cancelled -> re-price (attempt 2)
    assert first.attempts == 2
    clock.set(clock.now + timedelta(seconds=11))
    env.executor.sync(clock())
    env.executor.sync(clock())
    assert not env.executor.intents
    assert any(e.kind == "rejection" and "gave up" in e.message for e in env.bus.recent())
    assert env.store.intents()[0]["status"] == "failed"


def test_new_decision_supersedes_working_intent(clock):
    env = Env(clock, order=OrderConfig(price="passive"))
    env.quote("HK.00700", 420.0, 420.4)
    env.executor.submit("HK.00700", "BUY", 100, "signal")
    env.executor.sync(clock())
    order_id = next(iter(env.executor.intents.values())).order_id
    env.executor.submit("HK.00700", "SELL", 100, "signal")
    assert next(o for o in env.broker.orders() if o.order_id == order_id).state == "cancelled"


def test_risk_rejection_outside_session_waits(clock):
    env = Env(clock)
    env.quote("HK.00700", 420.0, 420.2)
    env.phase = Phase.LUNCH
    env.executor.submit("HK.00700", "BUY", 100, "signal")
    env.executor.sync(clock())
    assert env.executor.intents  # waiting, not failed
    env.phase = Phase.CONTINUOUS
    env.executor.sync(clock())
    assert not env.executor.intents and env.store.fills()


def test_working_intents_survive_restart(clock):
    env = Env(clock, order=OrderConfig(price="passive"))
    env.quote("HK.00700", 420.0, 420.4)
    iid = env.executor.submit("HK.00700", "BUY", 100, "signal")
    env.executor.sync(clock())
    restored = OrderExecutor(env.broker, env.broker, env.store, env.bus, env.risk, OrderConfig(), INST.__getitem__, env.context, env="DRY_RUN")
    assert iid in restored.intents and restored.intents[iid].order_id


def _ctx(**kw):
    base = dict(
        now=_ts("2024-06-12 10:00"), phase=Phase.CONTINUOUS,
        account=AccountSnapshot("HKD", equity=1_000_000, cash=600_000, market_value=400_000, buying_power=600_000),
        positions={"HK.00700": PositionInfo("HK.00700", 400, 400, 400.0, 420.0, 168_000)},
        working_buy_value=0.0, quote=Quote("HK.09988", last=80.0, bid=79.95, ask=80.0), orders_today=0,
        day_start_equity=1_000_000, halted=False,
    )
    base.update(kw)
    return RiskContext(**base)


@pytest.mark.parametrize(
    ("cfg", "req", "ctx", "fragment"),
    [
        ({}, OrderRequest("HK.09988", "BUY", 100, 80.0), {"phase": Phase.LUNCH}, "continuous"),
        ({"max_orders_per_day": 5}, OrderRequest("HK.09988", "BUY", 100, 80.0), {"orders_today": 5}, "max_orders_per_day"),
        ({}, OrderRequest("HK.09988", "BUY", 100, 90.0), {}, "from last"),
        ({"max_order_value": 5000}, OrderRequest("HK.09988", "BUY", 100, 80.0), {}, "max_order_value"),
        ({"max_position_value": 170_000}, OrderRequest("HK.00700", "BUY", 100, 420.0), {"quote": Quote("HK.00700", 420.0)}, "max_position_value"),
        ({"max_total_exposure": 0.4}, OrderRequest("HK.09988", "BUY", 100, 80.0), {}, "exposure"),
        ({}, OrderRequest("HK.09988", "BUY", 100, 80.0), {"halted": True, "halt_reason": "test"}, "halted"),
        ({"max_daily_loss_pct": 0.01}, OrderRequest("HK.09988", "BUY", 100, 80.0),
         {"account": AccountSnapshot("HKD", 980_000, 580_000, 400_000, 580_000)}, "daily loss"),
        ({}, OrderRequest("HK.00700", "SELL", 500, 420.0), {"quote": Quote("HK.00700", 420.0)}, "no short"),
    ],
)
def test_risk_rules(cfg, req, ctx, fragment):
    rm = RiskManager(RiskConfig(**cfg), HK)
    with pytest.raises(RiskRejected, match=fragment):
        rm.check(req, _ctx(**ctx))


def test_exits_pass_when_entries_are_halted():
    rm = RiskManager(RiskConfig(), HK)
    rm.check(OrderRequest("HK.00700", "SELL", 400, 419.8), _ctx(halted=True, quote=Quote("HK.00700", 420.0)))


def test_no_entries_near_close():
    rm = RiskManager(RiskConfig(no_entries_minutes_before_close=10), HK)
    with pytest.raises(RiskRejected, match="close"):
        rm.check(OrderRequest("HK.09988", "BUY", 100, 80.0), _ctx(now=_ts("2024-06-12 15:55")))


def test_sim_broker_next_bar_open_and_lots():
    t0 = _ts("2024-06-12 10:00")
    b = SimBroker(1e6, build_cost_model(CostsConfig()), INST.__getitem__, fill_mode="next_bar_open", clock=lambda: t0)
    b.on_bar("HK.00700", t0, 420, 421, 419, 420.5)
    with pytest.raises(Exception, match="board lot"):
        b.place(OrderRequest("HK.00700", "BUY", 150, None))
    o = b.place(OrderRequest("HK.00700", "BUY", 200, None))
    b.on_bar("HK.00700", _ts("2024-06-12 10:01"), 421.0, 422, 420, 421.5)
    filled = next(x for x in b.orders() if x.order_id == o.order_id)
    assert filled.state == "filled" and filled.avg_fill_price == 421.0
    acct = b.account()
    assert acct.cash < 1e6 - 200 * 421.0  # fees charged


def test_one_snapshot_request_per_sync_for_all_intents(clock):
    env = Env(clock)
    env.quote("HK.00700", 420.0, 420.2)
    env.quote("HK.09988", 80.0, 80.05)
    calls: list[list[str]] = []
    real = env.broker.quotes

    def counting(symbols):
        calls.append(list(symbols))
        return real(symbols)

    env.executor.quotes = type("Q", (), {"quotes": staticmethod(counting)})()
    env.executor.submit("HK.00700", "BUY", 100, "signal")
    env.executor.submit("HK.09988", "BUY", 100, "signal")
    env.executor.sync(clock())
    assert calls == [["HK.00700", "HK.09988"]]
    assert len(env.store.fills()) == 2
