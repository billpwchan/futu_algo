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


def _open(browser, url: str, width: int = 1440, height: int = 900, locale: str = "en-US"):
    ctx = browser.new_context(viewport={"width": width, "height": height}, locale=locale)
    page = ctx.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url)
    return ctx, page, errors


@pytest.mark.parametrize("route", PAGES)
@pytest.mark.parametrize("locale", ["en-US", "zh-CN"])
def test_every_page_renders_without_errors(console, browser, route, locale):
    ctx, page, errors = _open(browser, f"{console}/#/{route}", locale=locale)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)
    body = page.inner_text("body")
    assert len(body.strip()) > 50, f"{route} rendered almost nothing"
    assert page.locator("html").get_attribute("lang") == ("en" if locale == "en-US" else locale)
    assert page.locator("#nav").get_by_text("设置" if locale == "zh-CN" else "Settings", exact=True).count() == 1
    assert not errors, f"{route}: {errors}"
    ctx.close()


@pytest.mark.parametrize("route", ["dashboard", "backtest", "chart/HK.00700"])
@pytest.mark.parametrize("locale", ["en-US", "zh-CN"])
def test_mobile_layout_has_no_horizontal_scroll(console, browser, route, locale):
    ctx, page, errors = _open(browser, f"{console}/#/{route}", 390, 844, locale=locale)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(600)
    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 1, f"{route} scrolls horizontally by {overflow}px"
    assert not errors
    ctx.close()


@pytest.mark.parametrize("locale", ["en-US", "zh-CN"])
def test_backtest_runs_from_the_browser(console, browser, locale):
    ctx, page, errors = _open(browser, f"{console}/#/backtest", locale=locale)
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="运行回测" if locale == "zh-CN" else "Run backtest").click()
    # The backtest's history requests share the Futu rate limit with the demo engine running in the
    # same app, so how long the job takes depends on the engine's load: allow a slow CI runner.
    page.wait_for_url("**/#/backtest/*", timeout=180_000)
    page.wait_for_timeout(1500)
    text = page.inner_text("body").lower()  # labels are upper-cased by CSS
    labels = ["夏普比率", "最大回撤", "交易"] if locale == "zh-CN" else ["sharpe", "max drawdown", "trades"]
    assert all(label in text for label in labels)
    assert page.locator("canvas").count() > 0
    assert not errors, errors
    ctx.close()


def test_language_choice_persists_and_protects_config(console, browser):
    ctx, page, errors = _open(browser, f"{console}/#/settings", locale="zh-CN")
    page.wait_for_selector(".code-area")
    editor = page.locator(".code-area")
    original = editor.input_value()
    editor.fill(original + "\n# unsaved edit\n")
    page.locator("#language-select").select_option("en")
    page.get_by_role("button", name="取消", exact=True).click()
    assert "# unsaved edit" in editor.input_value()
    assert page.locator("#language-select").input_value() == "zh-CN"
    page.locator("#language-select").select_option("en")
    page.get_by_role("button", name="确认", exact=True).click()
    page.wait_for_function("document.documentElement.lang === 'en'")
    page.wait_for_selector("#language-select")
    assert page.locator("#language-select").input_value() == "en"
    page.reload()
    page.wait_for_selector("#language-select")
    assert page.locator("html").get_attribute("lang") == "en"
    assert page.locator(".code-area").input_value() == original
    assert not errors, errors
    ctx.close()


@pytest.mark.parametrize("locale", ["en-US", "zh-CN"])
def test_screener_conditions_and_results_are_localized(console, browser, locale):
    ctx, page, errors = _open(browser, f"{console}/#/screener", locale=locale)
    page.wait_for_load_state("networkidle")
    chinese = locale == "zh-CN"
    preset = page.locator(".preset").first
    assert preset.locator(".preset-name").inner_text() == ("高流动性股票" if chinese else "liquid")
    assert ("股价高于" if chinese else "Price above") in preset.locator(".preset-desc").inner_text()
    assert ("现价" if chinese else "CUR_PRICE") in preset.locator(".preset-filters").inner_text()
    assert ("基础" if chinese else "simple") in preset.locator(".preset-filters").inner_text().lower()
    page.get_by_role("button", name="执行选股" if chinese else "Run screen").click()
    page.wait_for_url("**/#/screener/*", timeout=30_000)
    page.get_by_role("columnheader", name="今日成交额" if chinese else "Turnover Today").wait_for()
    assert page.get_by_role("columnheader", name="现价" if chinese else "Cur Price").count() == 1
    assert page.get_by_role("columnheader", name="股票代码" if chinese else "Symbol").count() == 1
    rows = page.request.get(f"{console}/api/screener/results/{page.url.split('/')[-1]}").json()["rows"]
    assert rows and "cur_price" in rows[0]
    assert "turnover_today" in rows[0]
    assert not errors, errors
    ctx.close()


@pytest.mark.parametrize("locale", ["en-US", "zh-CN"])
def test_chart_and_screener_can_add_symbols_to_personal_watchlist(console, browser, locale):
    ctx, page, errors = _open(browser, f"{console}/#/chart/HK.00700", locale=locale)
    chinese = locale == "zh-CN"
    add_label = "添加到自选股" if chinese else "Add to watchlist"
    remove_label = "从自选股移除" if chinese else "Remove from watchlist"
    page.get_by_role("button", name=f"{add_label}: HK.00700").click()
    page.goto(f"{console}/#/watchlist")
    page.locator("#personal-watchlist").get_by_text("HK.00700").wait_for()
    page.locator("#personal-watchlist").get_by_role("button", name=f"{remove_label}: HK.00700").click()
    page.locator("#personal-watchlist").get_by_text("No saved symbols" if not chinese else "还没有收藏股票").wait_for()

    page.goto(f"{console}/#/screener")
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="执行选股" if chinese else "Run screen").click()
    page.wait_for_url("**/#/screener/*", timeout=30_000)
    row = page.locator("#screener-result tbody tr.clickable").first
    symbol = row.locator(".sym").inner_text()
    row.get_by_role("button", name=f"{add_label}: {symbol}").click()
    page.goto(f"{console}/#/watchlist")
    page.locator("#personal-watchlist").get_by_text(symbol).wait_for()
    assert not errors, errors
    ctx.close()
