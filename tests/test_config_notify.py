import json
import os

import pytest

from futu_algo.config import EXAMPLE_CONFIG, apply_overrides, load_config, load_dotenv, parse_config
from futu_algo.errors import ConfigError
from futu_algo.events import FILL, SCREENER, EventBus
from futu_algo.notify import Notifier, TelegramChannel, screener_html
from futu_algo.notify.channels import EmailChannel


def test_example_config_is_valid():
    cfg = load_config(EXAMPLE_CONFIG)
    assert cfg.trading.env == "SIMULATE"
    assert cfg.trading.strategy_for("HK.09988").name == "kdj"
    assert cfg.trading.strategy_for("HK.00700").name == "macd"
    assert "liquid_uptrend" in cfg.screener.presets


def test_errors_are_readable_and_unknown_keys_rejected(tmp_path):
    with pytest.raises(ConfigError, match=r"trading\.sizing"):
        parse_config({"trading": {"sizing": {"method": "fixed_value"}}})
    with pytest.raises(ConfigError, match="typo"):
        parse_config({"trading": {"typo": 1}})
    with pytest.raises(ConfigError, match="more than once"):
        parse_config({"trading": {"universe": ["HK.700", "HK.00700"]}})
    with pytest.raises(ConfigError, match="unknown preset"):
        parse_config({"screener": {"schedule": [{"preset": "nope"}]}})


def test_paths_resolve_against_config_dir_and_overrides(tmp_path):
    p = tmp_path / "cfg" / "c.yaml"
    p.parent.mkdir()
    p.write_text("data: {dir: cache}\ntrading: {universe: [HK.700]}\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.path(cfg.data.dir) == (tmp_path / "cfg" / "cache").resolve()
    cfg2 = apply_overrides(cfg, ["trading.timeframe=5min", "backtest.capital=5e5"])
    assert cfg2.trading.timeframe == "5M" and cfg2.backtest.capital == 5e5
    assert cfg2.source_path == cfg.source_path
    with pytest.raises(ConfigError):
        apply_overrides(cfg, ["nope.key=1"])


def test_dotenv_does_not_override_existing(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('A_TEST_KEY="from file"\nexport B_TEST_KEY=two\n# comment\n', encoding="utf-8")
    monkeypatch.setenv("A_TEST_KEY", "from env")
    monkeypatch.delenv("B_TEST_KEY", raising=False)
    load_dotenv(env)
    assert os.environ["A_TEST_KEY"] == "from env"
    assert os.environ["B_TEST_KEY"] == "two"
    monkeypatch.delenv("B_TEST_KEY")


def test_config_dump_contains_no_secret_values(tmp_path, monkeypatch):
    monkeypatch.setenv("FUTU_ALGO_SMTP_PASSWORD", "hunter2")
    cfg = parse_config({"notify": {"email": {"enabled": True, "smtp_host": "h", "sender": "a@b", "recipients": ["a@b"]}}})
    assert "hunter2" not in json.dumps(cfg.public_dict())


class Recorder:
    name = "rec"

    def __init__(self):
        self.sent = []

    def send(self, subject, text, html_body=None):
        self.sent.append((subject, text, html_body))


def test_notifier_routes_dedupes_and_formats():
    from futu_algo.config import NotifyConfig

    bus = EventBus()
    rec = Recorder()
    n = Notifier(NotifyConfig(events=["fills", "errors", "screener"]), bus, channels=[rec])
    n.start()
    try:
        bus.emit(FILL, "BUY 100 HK.00700 @ 420")
        bus.emit("error", "boom")
        bus.emit("error", "boom")  # duplicate within the window: dropped
        bus.emit("order", "not routed")
        bus.emit(SCREENER, "quiet run", notify=False, result={"rows": []})
        bus.emit(SCREENER, "loud run", notify=True, result={"preset": "p", "rows": [{"symbol": "HK.1", "name": "<b>x</b>"}], "matched": 1})
        import time

        time.sleep(0.3)
    finally:
        n.stop()
    subjects = [s for s, _, _ in rec.sent]
    assert len(rec.sent) == 3
    assert any("Fill" in s for s in subjects) and any("Error" in s for s in subjects)
    html_body = rec.sent[-1][2]
    assert "&lt;b&gt;x&lt;/b&gt;" in html_body and "<b>x</b>" not in html_body


def test_screener_html_escapes_everything():
    out = screener_html({"preset": "<script>", "description": "&", "rows": [{"symbol": "HK.1", "name": "\"q\""}], "matched": 1, "warnings": ["<w>"]})
    assert "<script>" not in out and "&lt;w&gt;" in out


def test_telegram_channel_escapes_and_posts(monkeypatch):
    from futu_algo.config import TelegramConfig

    captured = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["data"] = req.data.decode()
        return Resp()

    monkeypatch.setenv("TG_TEST_TOKEN", "123:abc")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    TelegramChannel(TelegramConfig(enabled=True, token_env="TG_TEST_TOKEN", chat_id="42")).send("Hi <there>", "a & b")
    assert "bot123:abc/sendMessage" in captured["url"]
    assert "chat_id=42" in captured["data"] and "%26lt%3Bthere%26gt%3B" in captured["data"]


def test_email_channel_uses_starttls_and_login(monkeypatch):
    from futu_algo.config import EmailConfig

    events = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=0):
            events.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context=None):
            events.append(("starttls",))

        def login(self, user, pw):
            events.append(("login", user, pw))

        def send_message(self, msg):
            events.append(("send", msg["To"], msg["Subject"]))

    monkeypatch.setenv("SMTP_TEST_PW", "pw")
    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    cfg = EmailConfig(enabled=True, smtp_host="smtp.x", username="u", password_env="SMTP_TEST_PW", sender="a@x", recipients=["b@x", "c@x"])
    EmailChannel(cfg).send("S", "T", "<p>H</p>")
    assert events[0] == ("connect", "smtp.x", 587)
    assert ("starttls",) in events and ("login", "u", "pw") in events
    assert events[-1] == ("send", "b@x, c@x", "S")
