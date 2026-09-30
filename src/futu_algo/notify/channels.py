"""Notification channels: SMTP email and Telegram.

Both escape every value they interpolate (stock names and error messages are external
text), time out quickly, and raise on failure so the dispatcher can log it.
"""

from __future__ import annotations

import html
import json
import logging
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from typing import Protocol

from futu_algo.config import EmailConfig, TelegramConfig, secret

log = logging.getLogger(__name__)


class Channel(Protocol):
    name: str

    def send(self, subject: str, text: str, html_body: str | None = None) -> None: ...


class EmailChannel:
    name = "email"

    def __init__(self, cfg: EmailConfig, timeout: float = 20.0) -> None:
        self.cfg = cfg
        self.timeout = timeout

    def send(self, subject: str, text: str, html_body: str | None = None) -> None:
        cfg = self.cfg
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = cfg.sender
        msg["To"] = ", ".join(cfg.recipients)
        msg.set_content(text)
        if html_body:
            msg.add_alternative(html_body, subtype="html")
        password = secret(cfg.password_env)
        context = ssl.create_default_context()
        if cfg.security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=self.timeout, context=context)
        else:
            server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=self.timeout)
        with server:
            if cfg.security == "starttls":
                server.starttls(context=context)
            if cfg.username and password:
                server.login(cfg.username, password)
            server.send_message(msg)


class TelegramChannel:
    name = "telegram"
    API = "https://api.telegram.org"

    def __init__(self, cfg: TelegramConfig, timeout: float = 10.0) -> None:
        self.cfg = cfg
        self.timeout = timeout

    def send(self, subject: str, text: str, html_body: str | None = None) -> None:
        token = secret(self.cfg.token_env)
        if not token:
            raise RuntimeError(f"Telegram token env var {self.cfg.token_env} is not set")
        body = f"<b>{html.escape(subject)}</b>\n{html.escape(text)}"
        if len(body) > 4000:
            body = body[:3990] + "…"
        payload = urllib.parse.urlencode(
            {"chat_id": self.cfg.chat_id, "text": body, "parse_mode": "HTML", "disable_web_page_preview": "true"}
        ).encode()
        req = urllib.request.Request(f"{self.API}/bot{token}/sendMessage", data=payload, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Telegram API HTTP {exc.code}") from None
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data.get('description')}")
