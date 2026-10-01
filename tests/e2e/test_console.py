"""Browser tests: the web console against the simulated OpenD.

Run with ``pytest -m e2e`` (needs ``pip install -e .[e2e]`` and a Chromium for Playwright;
set ``FUTU_ALGO_CHROMIUM`` to use a specific browser binary).
"""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest

pytestmark = pytest.mark.e2e

playwright_api = pytest.importorskip("playwright.sync_api")

PAGES = ["dashboard", "watchlist", "chart/HK.00700", "backtest", "screener", "orders", "data", "settings", "logs"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def console(tmp_path_factory) -> Iterator[str]:
    import uvicorn

    from futu_algo.demo import build_demo_app
    from futu_algo.logging_setup import setup_logging
    from futu_algo.web.server import create_app

    work: Path = tmp_path_factory.mktemp("console")
    start = pd.Timestamp("2024-06-12 10:05", tz="Asia/Hong_Kong").to_pydatetime()
    app, _opend, _clock = build_demo_app(work, speed=60, start=start)
    setup_logging("WARNING", None, app.bus)
    app.start_services(scheduler=False)
    app.start_engine()
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(app, token=""), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(10)
    app.shutdown()


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        exe = os.environ.get("FUTU_ALGO_CHROMIUM")
        if not exe and Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome").exists():
            exe = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
        try:
            b = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        except Exception as exc:  # pragma: no cover - environment without a browser
            pytest.skip(f"Chromium not available: {exc}")
        yield b
        b.close()


def _open(browser, url: str, width: int = 1440, height: int = 900):
    ctx = browser.new_context(viewport={"width": width, "height": height})
    page = ctx.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url)
    return ctx, page, errors


@pytest.mark.parametrize("route", PAGES)
def test_every_page_renders_without_errors(console, browser, route):
    ctx, page, errors = _open(browser, f"{console}/#/{route}")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)
    body = page.inner_text("body")
    assert len(body.strip()) > 50, f"{route} rendered almost nothing"
    assert not errors, f"{route}: {errors}"
    ctx.close()


@pytest.mark.parametrize("route", ["dashboard", "backtest", "chart/HK.00700"])
def test_mobile_layout_has_no_horizontal_scroll(console, browser, route):
    ctx, page, errors = _open(browser, f"{console}/#/{route}", 390, 844)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(600)
    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 1, f"{route} scrolls horizontally by {overflow}px"
    assert not errors
    ctx.close()


def test_backtest_runs_from_the_browser(console, browser):
    ctx, page, errors = _open(browser, f"{console}/#/backtest")
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Run backtest").click()
    page.wait_for_url("**/#/backtest/*", timeout=60_000)
    page.wait_for_timeout(1500)
    text = page.inner_text("body").lower()  # labels are upper-cased by CSS
    assert "sharpe" in text and "max drawdown" in text and "trades" in text
    assert page.locator("canvas").count() > 0
    assert not errors, errors
    ctx.close()
