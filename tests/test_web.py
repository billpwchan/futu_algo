import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from futu_algo.app import wait_for
from futu_algo.demo import build_demo_app
from futu_algo.web.server import create_app

from .conftest import HK_TZ

H = {"X-Futu-Algo": "1"}


@pytest.fixture
def demo(tmp_path):
    start = pd.Timestamp("2024-06-12 10:00", tz=HK_TZ).to_pydatetime()
    app, _opend, _clock = build_demo_app(tmp_path, speed=60, start=start)
    app.start_services(scheduler=False)
    yield app
    app.shutdown()


@pytest.fixture
def client(demo):
    return TestClient(create_app(demo, token="", allowed_hosts=["testserver"]))


def _wait_job(client, job_id, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def test_status_and_static(client):
    st = client.get("/api/status").json()
    assert st["trading"]["env"] == "SIMULATE" and st["engine"] is None
    page = client.get("/")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert client.get("/static/vendor/lightweight-charts.standalone.production.js").status_code == 200


def test_mutations_need_the_csrf_header(client):
    assert client.post("/api/engine/start").status_code == 403


def test_only_local_or_configured_hosts_are_served(demo):
    c = TestClient(create_app(demo, token=""), base_url="http://127.0.0.1:8765")
    assert c.get("/api/status").status_code == 200
    for host in ("localhost:8765", "[::1]:8765", "127.0.0.1"):
        assert c.get("/api/status", headers={"Host": host}).status_code == 200, host
    for host in ("attacker.example", "attacker.example:8765", "127.0.0.1.attacker.example", ""):
        for path in ("/api/status", "/api/health", "/"):
            assert c.get(path, headers={"Host": host}).status_code == 400, (host, path)
    assert c.post("/api/engine/start", headers={**H, "Host": "attacker.example"}).status_code == 400
    assert demo.engine is None
    # The TestClient's default host is not allowed unless passed in; web.allowed_hosts adds names.
    assert TestClient(create_app(demo, token="")).get("/api/status").status_code == 400
    demo.cfg.web.allowed_hosts = ["Console.LAN"]
    assert TestClient(create_app(demo, token=""), base_url="http://console.lan:8765").get("/api/status").status_code == 200


def test_cross_site_origin_cannot_mutate(demo):
    c = TestClient(create_app(demo, token=""), base_url="http://127.0.0.1:8765")
    for origin in ("http://attacker.example", "http://127.0.0.1.attacker.example:8765", "null"):
        r = c.post("/api/engine/start", headers={**H, "Origin": origin})
        assert r.status_code == 403, origin
    assert demo.engine is None
    assert c.get("/api/status", headers={"Origin": "http://attacker.example"}).status_code == 200  # reads are not mutations
    for origin in ("http://127.0.0.1:8765", "http://localhost:8765", "http://[::1]:8765"):
        r = c.post("/api/config/validate", headers={**H, "Origin": origin}, json={"text": "{}"})
        assert r.status_code == 200 and r.json()["ok"], origin
    assert c.post("/api/config/validate", headers=H, json={"text": "{}"}).status_code == 200  # no Origin header


def test_token_is_enforced(demo):
    c = TestClient(create_app(demo, token="s3cret", allowed_hosts=["testserver"]))
    assert c.get("/api/status").status_code == 401
    assert c.get("/api/status", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert c.get("/api/health").status_code == 200
    r = c.get("/?token=s3cret")
    assert "futu_algo_token" in r.headers.get("set-cookie", "")


def test_engine_lifecycle_and_views(client, demo):
    assert client.post("/api/engine/halt", headers=H, json={}).status_code == 409  # not running
    st = client.post("/api/engine/start", headers=H).json()
    assert st["state"] == "running"
    assert wait_for(lambda: client.get("/api/account").json()["account"] is not None, 10)
    assert client.post("/api/engine/halt", headers=H, json={"reason": "t"}).json()["halted"]
    assert client.get("/api/status").json()["engine"]["halted"]
    client.post("/api/engine/resume", headers=H)
    chart = client.get("/api/chart/HK.00700").json()
    assert chart["source"] == "live" and chart["candles"] and chart["lines"]
    assert client.post("/api/engine/flatten", headers=H, json={}).status_code == 200
    assert client.post("/api/engine/cancel-all", headers=H).status_code == 200
    for path in ("/api/orders", "/api/fills", "/api/signals?actions_only=true", "/api/intents", "/api/equity", "/api/events"):
        assert client.get(path).status_code == 200, path
    client.post("/api/engine/stop", headers=H)
    assert demo.engine.state == "stopped"


def test_backtest_job_and_history(client):
    strategies = client.get("/api/strategies").json()
    assert {"macd", "kdj", "boll"} <= {s["name"] for s in strategies}
    job = client.post("/api/backtests", headers=H, json={"overrides": {"symbols": ["HK.00700", "HK.09988"], "strategy": {"name": "kdj", "params": {}}}}).json()
    done = _wait_job(client, job["id"])
    assert done["status"] == "done", done
    run_id = done["result"]["id"]
    result = client.get(f"/api/backtests/{run_id}").json()
    assert result["strategy"]["name"] == "kdj" and result["books"]
    assert client.get("/api/backtests").json()[0]["id"] == run_id
    assert client.get("/api/backtests/../../etc").status_code == 404
    assert client.delete(f"/api/backtests/{run_id}", headers=H).status_code == 200
    bad = client.post("/api/backtests", headers=H, json={"overrides": {"timeframe": "nonsense"}})
    assert bad.status_code == 422


def test_screener_job(client):
    presets = client.get("/api/screener/presets").json()
    assert "liquid" in presets
    job = client.post("/api/screener/run", headers=H, json={"preset": "liquid"}).json()
    done = _wait_job(client, job["id"])
    assert done["status"] == "done", done
    results = client.get("/api/screener/results").json()
    assert results and results[0]["preset"] == "liquid"
    detail = client.get(f"/api/screener/results/{results[0]['id']}").json()
    assert detail["rows"]


def test_data_endpoints(client):
    job = client.post("/api/data/fetch", headers=H, json={"symbols": ["HK.00005"], "timeframe": "DAY", "start": "2024-01-02"}).json()
    assert _wait_job(client, job["id"])["status"] == "done"
    series = client.get("/api/data/series").json()
    assert any(s["symbol"] == "HK.00005" for s in series)
    assert client.get("/api/data/quota").json()["used"] >= 1
    assert client.get("/api/data/bars/HK.00005?ktype=K_DAY").json()["rows"] > 50


def test_config_validation_and_save(tmp_path):
    from futu_algo.app import App
    from futu_algo.config import load_config

    p = tmp_path / "c.yaml"
    p.write_text("trading: {universe: [HK.00700]}\ndata: {offline: true}\n", encoding="utf-8")
    app = App(load_config(p))
    c = TestClient(create_app(app, token="", allowed_hosts=["testserver"]))
    got = c.get("/api/config").json()
    assert got["editable"] and "HK.00700" in got["text"]
    bad = c.post("/api/config/validate", headers=H, json={"text": "trading: {sizing: {method: nope}}"}).json()
    assert not bad["ok"] and "sizing" in bad["error"]
    assert c.put("/api/config", headers=H, json={"text": "trading: [oops"}).status_code == 422
    ok = c.put("/api/config", headers=H, json={"text": "trading: {universe: [HK.09988]}\n"}).json()
    assert ok["restart_required"] and "HK.09988" in p.read_text()
    assert list(tmp_path.glob("c.yaml.bak-*"))
    assert c.post("/api/notify/test", headers=H, json={}).status_code == 409
    app.shutdown()


def test_switching_strategy_does_not_inherit_params(client, demo):
    from futu_algo.config import StrategySpec

    demo.cfg.backtest.strategy = StrategySpec(name="macd", params={"fast_period": 10})
    job = client.post("/api/backtests", headers=H, json={"overrides": {"strategy": {"name": "rsi", "params": {"period": 9}}}})
    assert job.status_code == 200, job.text
    done = _wait_job(client, job.json()["id"])
    assert done["status"] == "done", done
    result = client.get(f"/api/backtests/{done['result']['id']}").json()
    assert result["strategy"]["params"]["period"] == 9
