"""Shared plumbing for talking to Futu OpenD.

Everything that touches ``futu`` goes through here so that:

* ``futu`` is imported lazily (backtests on cached data, the web console and the tests run
  without OpenD);
* every request is rate-limited per API family and retried on OpenD's "too frequent" errors;
* protocol encryption (RSA) is configured once, before any context is created;
* tests can inject fake contexts through ``context_factory``.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from futu_algo.errors import DataSourceError, QuotaExceededError

log = logging.getLogger(__name__)

RET_OK = 0
_RATE_LIMIT_MARKERS = ("频率", "頻率", "frequen", "too many", "限频", "rate limit")
_QUOTA_MARKERS = ("额度", "額度", "quota")
_encryption_configured = False


class RateLimiter:
    """Sliding-window limiter: at most ``max_calls`` in any ``window`` seconds. Thread-safe."""

    def __init__(
        self,
        max_calls: int,
        window: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.max_calls = max_calls
        self.window = window
        self.clock = clock
        self.sleep = sleep
        self.calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = self.clock()
            while self.calls and now - self.calls[0] >= self.window:
                self.calls.popleft()
            if len(self.calls) >= self.max_calls:
                wait = self.window - (now - self.calls[0]) + 0.05
                log.info("Futu rate limit reached; waiting %.1fs", wait)
                self.sleep(wait)
                now = self.clock()
                while self.calls and now - self.calls[0] >= self.window:
                    self.calls.popleft()
            self.calls.append(now)


# Documented or conservative limits per API family (requests per 30 seconds).
DEFAULT_LIMITS: dict[str, tuple[int, float]] = {
    "history_kline": (30, 30.0),
    "snapshot": (60, 30.0),
    "stock_filter": (10, 30.0),
    "trading_days": (30, 30.0),
    "basicinfo": (10, 30.0),
    "plate": (10, 30.0),
    "subscribe": (60, 30.0),
    "trade_query": (10, 30.0),
    "trade_order": (15, 30.0),
    "default": (60, 30.0),
}


def configure_encryption(rsa_private_key: str | Path | None) -> bool:
    """Enable Futu protocol encryption globally when an RSA private key is configured.

    OpenD requires it for trading when it listens on a non-local address.
    """
    global _encryption_configured
    if not rsa_private_key:
        return False
    path = Path(rsa_private_key).expanduser()
    if not path.is_file():
        raise DataSourceError(f"RSA private key {path} does not exist")
    if _encryption_configured:
        return True
    from futu import SysConfig

    SysConfig.enable_proto_encrypt(True)
    SysConfig.set_init_rsa_file(str(path))
    _encryption_configured = True
    log.info("Futu protocol encryption enabled with %s", path)
    return True


def is_rate_limited(message: str) -> bool:
    lowered = message.lower()
    return any(m in lowered for m in _RATE_LIMIT_MARKERS)


def is_quota_error(message: str) -> bool:
    lowered = message.lower()
    return any(m in lowered for m in _QUOTA_MARKERS)


def probe_opend(host: str, port: int, timeout: float = 3.0) -> None:
    """Fail fast when nothing listens on OpenD's port.

    futu-api's context constructors retry a refused connection forever, which would hang the
    CLI, the console's jobs and the engine start-up; a plain TCP connect detects it in seconds.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return
    except OSError as exc:
        raise DataSourceError(
            f"Futu OpenD is not reachable at {host}:{port} ({exc.strerror or exc}). Start OpenD and "
            "log in, check futu.host/futu.port, or work offline from the local cache."
        ) from None


_futu_configured = False


def configure_futu_runtime() -> None:
    """Keep futu-api quiet on the console (it prints INFO lines itself) and make its threads
    daemons so a stuck connection never keeps the process alive. Idempotent."""
    global _futu_configured
    if _futu_configured:
        return
    try:
        from futu import SysConfig
        from futu.common.ft_logger import logger as ft_logger
    except ImportError:  # pragma: no cover
        return
    SysConfig.set_all_thread_daemon(True)
    ft_logger._console_level = logging.WARNING
    ft_logger.console_logger.setLevel(logging.WARNING)
    ft_logger.consoleHandler.setLevel(logging.WARNING)
    _futu_configured = True


def _default_quote_factory(host: str, port: int) -> Any:
    try:
        from futu import OpenQuoteContext
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise DataSourceError("futu-api is not installed; pip install futu-api") from exc
    configure_futu_runtime()
    probe_opend(host, port)
    return OpenQuoteContext(host=host, port=port)


class QuoteGateway:
    """Lazily connected, rate-limited OpenQuoteContext shared by data, screener and live feed."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 11111,
        *,
        context_factory: Callable[[str, int], Any] | None = None,
        limits: dict[str, tuple[int, float]] | None = None,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.host = host
        self.port = port
        self._factory = context_factory or _default_quote_factory
        self._ctx: Any = None
        self._lock = threading.RLock()
        self._sleep = sleep
        self.max_retries = max_retries
        merged = {**DEFAULT_LIMITS, **(limits or {})}
        self.limiters = {k: RateLimiter(n, w, sleep=sleep) for k, (n, w) in merged.items()}
        self.requests = 0

    @property
    def connected(self) -> bool:
        return self._ctx is not None

    def context(self) -> Any:
        with self._lock:
            if self._ctx is None:
                log.info("Connecting quote context to Futu OpenD at %s:%s", self.host, self.port)
                try:
                    self._ctx = self._factory(self.host, self.port)
                except DataSourceError:
                    raise
                except Exception as exc:
                    raise DataSourceError(
                        f"Cannot connect to Futu OpenD at {self.host}:{self.port}: {exc}. "
                        "Start OpenD and log in, or work offline from the local cache."
                    ) from exc
            return self._ctx

    def close(self) -> None:
        with self._lock:
            if self._ctx is not None:
                try:
                    self._ctx.close()
                except Exception:  # pragma: no cover - best effort on shutdown
                    log.debug("Error closing quote context", exc_info=True)
                finally:
                    self._ctx = None

    def __enter__(self) -> QuoteGateway:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def call(self, family: str, what: str, fn: Callable[[Any], tuple[Any, ...]]) -> tuple[Any, ...]:
        """Run ``fn(ctx)`` under the family's rate limit; return the full result tuple.

        Rate-limit errors are retried with backoff; quota errors raise ``QuotaExceededError``;
        any other error raises ``DataSourceError`` with OpenD's message.
        """
        limiter = self.limiters.get(family, self.limiters["default"])
        ctx = self.context()
        attempt = 0
        while True:
            limiter.acquire()
            self.requests += 1
            result = fn(ctx)
            ret, data = result[0], result[1]
            if ret == RET_OK:
                return result
            message = str(data)
            if is_quota_error(message):
                raise QuotaExceededError(f"{what}: {message}")
            if is_rate_limited(message) and attempt < self.max_retries:
                attempt += 1
                wait = limiter.window * attempt / 2
                log.warning("%s rate-limited (%s); retry %d in %.0fs", what, message, attempt, wait)
                self._sleep(wait)
                continue
            raise DataSourceError(f"{what} failed: {message}")
