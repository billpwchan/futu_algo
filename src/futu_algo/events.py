"""In-process event bus.

The live engine, the screener and the scheduler publish :class:`Event` objects; the notifier
and the web console's server-sent-events stream subscribe. The bus keeps a bounded history so
a browser that connects late still sees recent activity.
"""

from __future__ import annotations

import itertools
import logging
import queue
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

log = logging.getLogger(__name__)

Level = Literal["debug", "info", "warning", "error"]

# Event kinds (the ``kind`` field). Notification routing keys off these.
ENGINE = "engine"
BAR = "bar"
SIGNAL = "signal"
ORDER = "order"
FILL = "fill"
REJECTION = "rejection"
RISK = "risk"
ERROR = "error"
ACCOUNT = "account"
SCREENER = "screener"
SUMMARY = "daily_summary"
BACKTEST = "backtest"
LOG = "log"

_ids = itertools.count(1)


@dataclass(frozen=True)
class Event:
    kind: str
    message: str
    level: Level = "info"
    symbol: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    time: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: int = field(default_factory=lambda: next(_ids))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "level": self.level,
            "message": self.message,
            "symbol": self.symbol,
            "data": self.data,
            "time": self.time.isoformat(),
        }


class EventBus:
    def __init__(self, history: int = 1000) -> None:
        self._lock = threading.Lock()
        self._history: deque[Event] = deque(maxlen=history)
        self._callbacks: list[Callable[[Event], None]] = []
        self._queues: list[queue.Queue[Event]] = []

    def publish(self, event: Event) -> Event:
        with self._lock:
            self._history.append(event)
            callbacks = list(self._callbacks)
            queues = list(self._queues)
        for q in queues:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass  # a slow browser tab must never block trading
        for cb in callbacks:
            try:
                cb(event)
            except Exception:
                log.exception("Event subscriber failed on %s", event.kind)
        return event

    def emit(
        self,
        kind: str,
        message: str,
        *,
        level: Level = "info",
        symbol: str | None = None,
        **data: Any,
    ) -> Event:
        return self.publish(Event(kind=kind, message=message, level=level, symbol=symbol, data=data))

    def subscribe(self, callback: Callable[[Event], None]) -> Callable[[], None]:
        with self._lock:
            self._callbacks.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                if callback in self._callbacks:
                    self._callbacks.remove(callback)

        return unsubscribe

    def open_queue(self, maxsize: int = 1000) -> queue.Queue[Event]:
        q: queue.Queue[Event] = queue.Queue(maxsize=maxsize)
        with self._lock:
            self._queues.append(q)
        return q

    def close_queue(self, q: queue.Queue[Event]) -> None:
        with self._lock:
            if q in self._queues:
                self._queues.remove(q)

    def recent(self, limit: int = 200, kinds: set[str] | None = None, after_id: int = 0) -> list[Event]:
        with self._lock:
            items = [e for e in self._history if e.id > after_id and (kinds is None or e.kind in kinds)]
        return items[-limit:]


class BusLogHandler(logging.Handler):
    """Mirror WARNING+ log records (and optionally INFO) onto the bus for the web console."""

    def __init__(self, bus: EventBus, level: int = logging.INFO) -> None:
        super().__init__(level)
        self.bus = bus

    def emit(self, record: logging.LogRecord) -> None:
        try:
            lvl: Level = (
                "error" if record.levelno >= logging.ERROR
                else "warning" if record.levelno >= logging.WARNING
                else "info" if record.levelno >= logging.INFO
                else "debug"
            )
            self.bus.emit(LOG, self.format(record), level=lvl, logger=record.name)
        except Exception:  # pragma: no cover - logging must never raise
            self.handleError(record)
