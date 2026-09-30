"""SQLite state for the live engine.

It is the engine's memory across restarts and the audit trail the web console reads:
signals, order intents, broker orders, fills, account snapshots, events and small key/value
state (kill switch, entry blocks, the day's starting equity). WAL mode lets the console read
while the engine writes.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from futu_algo.live.models import OrderInfo

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time TEXT NOT NULL,
    symbol TEXT NOT NULL,
    bar_time TEXT NOT NULL,
    strategy TEXT NOT NULL,
    signal REAL,
    close REAL,
    action TEXT,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS signals_symbol ON signals(symbol, bar_time);

CREATE TABLE IF NOT EXISTS intents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    reason TEXT,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    bar_time TEXT,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS intents_status ON intents(status);

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    intent_id INTEGER,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL,
    order_type TEXT,
    state TEXT NOT NULL,
    filled_qty INTEGER NOT NULL DEFAULT 0,
    avg_fill_price REAL NOT NULL DEFAULT 0,
    created TEXT,
    updated TEXT,
    remark TEXT,
    error TEXT,
    env TEXT
);
CREATE INDEX IF NOT EXISTS orders_created ON orders(created);

CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time TEXT NOT NULL,
    order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    env TEXT
);
CREATE INDEX IF NOT EXISTS fills_time ON fills(time);

CREATE TABLE IF NOT EXISTS equity (
    time TEXT PRIMARY KEY,
    equity REAL,
    cash REAL,
    market_value REAL,
    env TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time TEXT NOT NULL,
    kind TEXT NOT NULL,
    level TEXT NOT NULL,
    symbol TEXT,
    message TEXT NOT NULL,
    data TEXT
);
CREATE INDEX IF NOT EXISTS events_time ON events(time);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


class StateStore:
    def __init__(self, path: str | Path, clock: Callable[[], datetime] | None = None) -> None:
        self.path = Path(path)
        self._clock = clock
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            if str(path) != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _now(self) -> str:
        """Timestamps follow the engine clock (virtual in replays and demo mode), in UTC."""
        if self._clock is None:
            return _now()
        return pd.Timestamp(self._clock()).tz_convert("UTC").isoformat(timespec="seconds")

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def _rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    # ----------------------------------------------------------------------- kv

    def get(self, key: str, default: Any = None) -> Any:
        rows = self._rows("SELECT value FROM kv WHERE key = ?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set(self, key: str, value: Any) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )

    # ------------------------------------------------------------------ signals

    def add_signal(
        self, symbol: str, bar_time: datetime, strategy: str, signal: float | None,
        close: float, action: str, detail: dict[str, Any] | None = None,
    ) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO signals(time, symbol, bar_time, strategy, signal, close, action, detail) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (self._now(), symbol, bar_time.isoformat(), strategy,
                 None if signal is None or signal != signal else float(signal),
                 close, action, json.dumps(detail or {}, default=str)),
            )

    def signals(self, limit: int = 200, symbol: str | None = None) -> list[dict[str, Any]]:
        if symbol:
            return self._rows("SELECT * FROM signals WHERE symbol = ? ORDER BY id DESC LIMIT ?", (symbol, limit))
        return self._rows("SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,))

    # ------------------------------------------------------------------ intents

    def add_intent(self, symbol: str, side: str, quantity: int, reason: str, bar_time: datetime | None) -> int:
        now = self._now()
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO intents(created, updated, symbol, side, quantity, reason, status, bar_time) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (now, now, symbol, side, quantity, reason, "working", _iso(bar_time)),
            )
            return int(cur.lastrowid or 0)

    def update_intent(self, intent_id: int, **fields: Any) -> None:
        if not fields:
            return
        fields["updated"] = self._now()
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self._tx() as c:
            c.execute(f"UPDATE intents SET {cols} WHERE id = ?", (*fields.values(), intent_id))

    def intents(self, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if status:
            return self._rows("SELECT * FROM intents WHERE status = ? ORDER BY id DESC LIMIT ?", (status, limit))
        return self._rows("SELECT * FROM intents ORDER BY id DESC LIMIT ?", (limit,))

    # ------------------------------------------------------------------- orders

    def upsert_order(self, order: OrderInfo, intent_id: int | None, env: str) -> tuple[int, bool]:
        """Store the broker's view of an order.

        Returns ``(new_fill_qty, newly_final)`` relative to what was stored before, so the
        caller can record fills without deal pushes (paper accounts have none).
        """
        with self._tx() as c:
            prev = c.execute("SELECT filled_qty, state, intent_id FROM orders WHERE order_id = ?", (order.order_id,)).fetchone()
            prev_filled = int(prev["filled_qty"]) if prev else 0
            prev_state = str(prev["state"]) if prev else None
            if intent_id is None and prev is not None:
                intent_id = prev["intent_id"]
            c.execute(
                "INSERT INTO orders(order_id, intent_id, symbol, side, quantity, price, order_type, state, "
                "filled_qty, avg_fill_price, created, updated, remark, error, env) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET "
                "state=excluded.state, filled_qty=excluded.filled_qty, avg_fill_price=excluded.avg_fill_price, "
                "updated=excluded.updated, error=excluded.error, price=excluded.price, "
                "intent_id=COALESCE(orders.intent_id, excluded.intent_id)",
                (order.order_id, intent_id, order.symbol, order.side, order.quantity, order.price,
                 order.order_type, str(order.state), order.filled_qty, order.avg_fill_price,
                 _iso(order.created) or self._now(), _iso(order.updated) or self._now(), order.remark,
                 order.error, env),
            )
            new_qty = max(order.filled_qty - prev_filled, 0)
            final_now = (not order.state.is_open) and (prev_state is None or prev_state in ("pending", "submitted", "partial"))
            return new_qty, final_now

    def orders(self, limit: int = 200, open_only: bool = False) -> list[dict[str, Any]]:
        if open_only:
            return self._rows(
                "SELECT * FROM orders WHERE state IN ('pending','submitted','partial') ORDER BY created DESC LIMIT ?",
                (limit,),
            )
        return self._rows("SELECT * FROM orders ORDER BY created DESC LIMIT ?", (limit,))

    def order_intent(self, order_id: str) -> int | None:
        rows = self._rows("SELECT intent_id FROM orders WHERE order_id = ?", (order_id,))
        return rows[0]["intent_id"] if rows else None

    def orders_for_intent(self, intent_id: int) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM orders WHERE intent_id = ? ORDER BY created", (intent_id,))

    def count_orders_since(self, since_iso: str) -> int:
        rows = self._rows("SELECT COUNT(*) AS n FROM orders WHERE created >= ?", (since_iso,))
        return int(rows[0]["n"])

    # -------------------------------------------------------------------- fills

    def add_fill(self, order_id: str, symbol: str, side: str, quantity: int, price: float, env: str, when: datetime | None = None) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO fills(time, order_id, symbol, side, quantity, price, env) VALUES(?,?,?,?,?,?,?)",
                (_iso(when) or self._now(), order_id, symbol, side, quantity, price, env),
            )

    def fills(self, limit: int = 200, since_iso: str | None = None) -> list[dict[str, Any]]:
        if since_iso:
            return self._rows("SELECT * FROM fills WHERE time >= ? ORDER BY id DESC LIMIT ?", (since_iso, limit))
        return self._rows("SELECT * FROM fills ORDER BY id DESC LIMIT ?", (limit,))

    # ------------------------------------------------------------------- equity

    def add_equity(self, when: datetime, equity: float, cash: float, market_value: float, env: str) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO equity(time, equity, cash, market_value, env) VALUES(?,?,?,?,?)",
                (when.isoformat(timespec="seconds"), equity, cash, market_value, env),
            )

    def equity_curve(self, since_iso: str | None = None, limit: int = 5000) -> list[dict[str, Any]]:
        if since_iso:
            rows = self._rows("SELECT * FROM equity WHERE time >= ? ORDER BY time DESC LIMIT ?", (since_iso, limit))
        else:
            rows = self._rows("SELECT * FROM equity ORDER BY time DESC LIMIT ?", (limit,))
        return list(reversed(rows))

    # ------------------------------------------------------------------- events

    def add_event(self, when: datetime, kind: str, level: str, message: str, symbol: str | None, data: dict[str, Any]) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO events(time, kind, level, symbol, message, data) VALUES(?,?,?,?,?,?)",
                (when.isoformat(timespec="seconds"), kind, level, symbol, message, json.dumps(data, default=str)),
            )

    def events(self, limit: int = 200, kinds: list[str] | None = None) -> list[dict[str, Any]]:
        if kinds:
            marks = ",".join("?" for _ in kinds)
            return self._rows(f"SELECT * FROM events WHERE kind IN ({marks}) ORDER BY id DESC LIMIT ?", (*kinds, limit))
        return self._rows("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
