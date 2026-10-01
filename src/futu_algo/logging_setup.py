"""Logging: console, a daily-rotated file, and (optionally) the event bus for the web console."""

from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from futu_algo.events import BusLogHandler, EventBus

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_configured: list[logging.Handler] = []


def setup_logging(level: str = "INFO", log_dir: Path | None = None, bus: EventBus | None = None) -> None:
    root = logging.getLogger()
    for handler in _configured:
        root.removeHandler(handler)
    _configured.clear()
    root.setLevel(logging.DEBUG)
    fmt = logging.Formatter(FORMAT)

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    console.setFormatter(fmt)
    _configured.append(console)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = TimedRotatingFileHandler(log_dir / "futu_algo.log", when="midnight", backupCount=30, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG if level == "DEBUG" else logging.INFO)
        file_handler.setFormatter(fmt)
        _configured.append(file_handler)

    if bus is not None:
        bus_handler = BusLogHandler(bus, logging.INFO)
        bus_handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        bus_handler.addFilter(lambda r: r.name.startswith("futu_algo"))
        _configured.append(bus_handler)

    for handler in _configured:
        root.addHandler(handler)
    # futu-api logs every request at INFO and writes its own files; keep it quiet.
    logging.getLogger("futu").setLevel(logging.WARNING)
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).setLevel(logging.WARNING)
