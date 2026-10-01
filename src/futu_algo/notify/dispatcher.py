"""Route bus events to notification channels.

Sending happens on a background thread so a slow SMTP server can never stall the engine.
Identical messages within a short window are dropped, so a repeating error does not flood
anyone's inbox.
"""

from __future__ import annotations

import html
import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

from futu_algo.config import NotifyConfig
from futu_algo.events import (
    ENGINE,
    ERROR,
    FILL,
    ORDER,
    REJECTION,
    RISK,
    SCREENER,
    SUMMARY,
    Event,
    EventBus,
)
from futu_algo.notify.channels import Channel, EmailChannel, TelegramChannel

log = logging.getLogger(__name__)

ROUTES: dict[str, str] = {
    FILL: "fills",
    ORDER: "orders",
    REJECTION: "rejections",
    ERROR: "errors",
    RISK: "risk",
    SUMMARY: "daily_summary",
    SCREENER: "screener",
    ENGINE: "engine",
}
DEDUPE_SECONDS = 300


def screener_html(result: dict[str, Any]) -> str:
    rows = result.get("rows", [])
    cols = [c for c in ("symbol", "name", "last_price", "change_pct", "turnover_today", "market_cap", "pe_ttm", "signal") if any(c in r for r in rows)]
    head = "".join(f"<th style='text-align:left;padding:6px 10px;border-bottom:2px solid #2f6f5e'>{html.escape(c)}</th>" for c in cols)

    def fmt(v: Any) -> str:
        if isinstance(v, float):
            return f"{v:,.2f}"
        return "" if v is None else str(v)

    body = "".join(
        "<tr>" + "".join(f"<td style='padding:6px 10px;border-bottom:1px solid #ddd'>{html.escape(fmt(r.get(c)))}</td>" for c in cols) + "</tr>"
        for r in rows
    )
    warn = "".join(f"<li>{html.escape(w)}</li>" for w in result.get("warnings", []))
    return (
        "<div style='font-family:-apple-system,Segoe UI,sans-serif'>"
        f"<h2 style='margin:0 0 4px'>Screener: {html.escape(str(result.get('preset')))}</h2>"
        f"<p style='color:#555;margin:0 0 12px'>{html.escape(str(result.get('description') or ''))} "
        f"({len(rows)} of {result.get('matched')} matches, run {html.escape(str(result.get('run_at')))})</p>"
        f"<table style='border-collapse:collapse;font-size:14px'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
        + (f"<ul style='color:#8a5a00'>{warn}</ul>" if warn else "")
        + "<p style='color:#888;font-size:12px'>futu_algo · not investment advice</p></div>"
    )


class Notifier:
    def __init__(self, cfg: NotifyConfig, bus: EventBus, channels: list[Channel] | None = None) -> None:
        self.cfg = cfg
        self.bus = bus
        if channels is None:
            channels = []
            if cfg.email.enabled:
                channels.append(EmailChannel(cfg.email))
            if cfg.telegram.enabled:
                channels.append(TelegramChannel(cfg.telegram))
        self.channels = channels
        self.enabled_events = set(cfg.events)
        self._queue: queue.Queue[tuple[str, str, str | None]] = queue.Queue(maxsize=500)
        self._recent: dict[str, float] = {}
        self._thread: threading.Thread | None = None
        self._unsubscribe: Callable[[], None] | None = None
        self.sent = 0
        self.failed = 0

    def start(self) -> None:
        if not self.channels or self._thread is not None:
            return
        self._unsubscribe = self.bus.subscribe(self.on_event)
        self._thread = threading.Thread(target=self._worker, name="futu-algo-notify", daemon=True)
        self._thread.start()
        log.info("Notifications enabled via %s for %s", [c.name for c in self.channels], sorted(self.enabled_events))

    def stop(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
        self._queue.put(("__stop__", "", None))
        if self._thread:
            self._thread.join(5)
            self._thread = None

    def on_event(self, event: Event) -> None:
        route = ROUTES.get(event.kind)
        if route is None or route not in self.enabled_events:
            return
        if event.kind == SCREENER and not event.data.get("notify", False):
            return
        key = f"{event.kind}:{event.message}"
        now = time.monotonic()
        if now - self._recent.get(key, -1e9) < DEDUPE_SECONDS and event.kind not in (FILL, SUMMARY, SCREENER):
            return
        self._recent[key] = now
        subject, text, html_body = self.render(event)
        try:
            self._queue.put_nowait((subject, text, html_body))
        except queue.Full:
            log.warning("Notification queue full; dropping %s", subject)

    @staticmethod
    def render(event: Event) -> tuple[str, str, str | None]:
        tag = {FILL: "Fill", ORDER: "Order", REJECTION: "Rejected", ERROR: "Error", RISK: "Risk",
               SUMMARY: "Daily summary", SCREENER: "Screener", ENGINE: "Engine"}.get(event.kind, event.kind)
        subject = f"[futu_algo] {tag}: {event.message[:80]}"
        text = f"{event.message}\n\n{event.time:%Y-%m-%d %H:%M:%S} UTC"
        html_body = None
        if event.kind == SCREENER and "result" in event.data:
            html_body = screener_html(event.data["result"])
            rows = event.data["result"].get("rows", [])
            text += "\n\n" + "\n".join(f"{r['symbol']} {r.get('name', '')} {r.get('last_price', '')}" for r in rows[:50])
        return subject, text, html_body

    def send_now(self, subject: str, text: str, html_body: str | None = None) -> list[str]:
        """Send synchronously to every channel; returns errors (used by the console's test button)."""
        errors = []
        for ch in self.channels:
            try:
                ch.send(subject, text, html_body)
            except Exception as exc:
                errors.append(f"{ch.name}: {exc}")
        return errors

    def _worker(self) -> None:
        while True:
            subject, text, html_body = self._queue.get()
            if subject == "__stop__":
                return
            for ch in self.channels:
                try:
                    ch.send(subject, text, html_body)
                    self.sent += 1
                except Exception as exc:
                    self.failed += 1
                    log.warning("Notification via %s failed: %s", ch.name, exc)
