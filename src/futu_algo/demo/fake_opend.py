"""A simulated Futu OpenD: quote and trade contexts backed by a synthetic HK market.

It implements the subset of ``futu-api`` calls futu_algo uses, returning the same shapes
(``(RET_OK, DataFrame)`` tuples, paging keys, filter result objects), so the real
``FutuSource``, ``FutuBroker``, ``FutuBarFeed`` and ``Screener`` run against it unchanged.
Used by the test suite and by ``futu-algo web --demo``.

Prices are a deterministic random walk per symbol and trading day (seeded by symbol and
date), so every query for the same minute returns the same bar.
"""

from __future__ import annotations

import contextlib
import hashlib
import itertools
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from futu_algo.data.resample import session_labels
from futu_algo.market.instrument import MARKETS

RET_OK, RET_ERROR = 0, -1
HK = MARKETS["HK"]

DEMO_SYMBOLS: dict[str, tuple[str, int, float]] = {
    "HK.00700": ("TENCENT (demo)", 100, 420.0),
    "HK.09988": ("BABA-W (demo)", 100, 110.0),
    "HK.00005": ("HSBC HOLDINGS (demo)", 400, 95.0),
    "HK.01299": ("AIA (demo)", 200, 62.0),
    "HK.00388": ("HKEX (demo)", 100, 330.0),
    "HK.03690": ("MEITUAN-W (demo)", 100, 135.0),
    "HK.02318": ("PING AN (demo)", 500, 48.0),
    "HK.00941": ("CHINA MOBILE (demo)", 500, 82.0),
    "HK.800000": ("HSI (demo)", 1, 25000.0),
}
ANCHOR = date(2021, 1, 4)


def _seed(*parts: object) -> int:
    return int.from_bytes(hashlib.sha256("|".join(map(str, parts)).encode()).digest()[:8], "little")


def _minutes_of_day(day: date) -> pd.DatetimeIndex:
    base = pd.Timestamp(day, tz=HK.tz)
    times = [base + pd.Timedelta(hours=9, minutes=30)]  # opening auction bar
    for start, end in HK.sessions:
        m = start.hour * 60 + start.minute + 1
        while m <= end.hour * 60 + end.minute:
            times.append(base + pd.Timedelta(minutes=m))
            m += 1
    return pd.DatetimeIndex(times, name="time")


class SyntheticMarket:
    """Deterministic 1-minute bars for the demo symbols on weekdays."""

    def __init__(self, symbols: dict[str, tuple[str, int, float]] | None = None, clock: Callable[[], datetime] | None = None) -> None:
        self.symbols = symbols or DEMO_SYMBOLS
        self.clock = clock or (lambda: datetime.now(UTC))
        self._closes_series: dict[str, pd.Series] = {}
        self._days: dict[tuple[str, date], pd.DataFrame] = {}
        self._lock = threading.RLock()

    @staticmethod
    def is_trading_day(day: date) -> bool:
        return day.weekday() < 5

    def trading_days(self, start: date, end: date) -> list[date]:
        out, d = [], start
        while d <= end:
            if self.is_trading_day(d):
                out.append(d)
            d += timedelta(days=1)
        return out

    def _daily(self, symbol: str) -> pd.Series:
        """Daily closes for every weekday from the anchor, as one vectorised random walk."""
        with self._lock:
            series = self._closes_series.get(symbol)
            horizon = date.today() + timedelta(days=400)
            if series is not None and series.index[-1] >= horizon:
                return series
            days = pd.bdate_range(ANCHOR, horizon).date
            rng = np.random.default_rng(_seed(symbol, "daily"))
            vol = 0.018 if symbol != "HK.800000" else 0.011
            rets = rng.normal(0.0002, vol, len(days))
            closes = self.symbols[symbol][2] * np.exp(np.cumsum(rets))
            series = pd.Series(closes, index=days)
            self._closes_series[symbol] = series
            return series

    def _prev_close(self, symbol: str, day: date) -> float:
        series = self._daily(symbol)
        pos = series.index.searchsorted(day) - 1
        return float(series.iloc[pos]) if pos >= 0 else self.symbols[symbol][2]

    def day_bars(self, symbol: str, day: date) -> pd.DataFrame:
        key = (symbol, day)
        with self._lock:
            if key in self._days:
                return self._days[key]
            series = self._daily(symbol)
            prev = self._prev_close(symbol, day)
            target = float(series.get(day, prev))
            idx = _minutes_of_day(day)
            rng = np.random.default_rng(_seed(symbol, day))
            n = len(idx)
            vol = 0.0012 if symbol != "HK.800000" else 0.0006
            steps = rng.normal(0, vol, n)
            path = np.cumsum(steps)
            # Brownian bridge onto the day's close so minute and daily bars agree.
            path = path - np.linspace(0, 1, n) * (path[-1] - np.log(target / prev))
            close = prev * np.exp(path)
            open_ = np.concatenate([[prev * np.exp(path[0] * 0.5)], close[:-1]])
            spread = np.abs(rng.normal(0, vol * 0.8, n))
            high = np.maximum(open_, close) * (1 + spread)
            low = np.minimum(open_, close) * (1 - spread)
            volume = np.round(rng.lognormal(10, 0.6, n) / 100) * 100
            tick = 0.05 if prev >= 20 else 0.01
            frame = pd.DataFrame(
                {
                    "open": np.round(open_ / tick) * tick,
                    "high": np.round(high / tick) * tick,
                    "low": np.round(low / tick) * tick,
                    "close": np.round(close / tick) * tick,
                    "volume": volume,
                },
                index=idx,
            )
            frame["high"] = frame[["open", "high", "close"]].max(axis=1)
            frame["low"] = frame[["open", "low", "close"]].min(axis=1)
            frame["turnover"] = frame["close"] * frame["volume"]
            self._days[key] = frame
            if len(self._days) > 4000:
                self._days.pop(next(iter(self._days)))
            return frame

    def minute_bars(self, symbol: str, start: date, end: date, until: datetime | None = None) -> pd.DataFrame:
        frames = [self.day_bars(symbol, d) for d in self.trading_days(start, end)]
        bars = pd.concat(frames) if frames else pd.DataFrame(columns=["open", "high", "low", "close", "volume", "turnover"])
        if until is not None and len(bars):
            stamp = pd.Timestamp(until).tz_convert(HK.tz)
            # Include the minute in progress: its label is the next whole minute.
            bars = bars[bars.index <= stamp.ceil("min")]
        return bars

    def daily_bars(self, symbol: str, start: date, end: date, until: datetime | None = None) -> pd.DataFrame:
        """Daily bars: past days straight from the daily walk (fast); the current day is
        aggregated from its minutes so far, like a live in-progress bar."""
        series = self._daily(symbol)
        now_day = pd.Timestamp(until).tz_convert(HK.tz).date() if until is not None else None
        days = [d for d in self.trading_days(start, end) if now_day is None or d <= now_day]
        rows, index = [], []
        for d in days:
            if d == now_day:
                m = self.minute_bars(symbol, d, d, until)
                if m.empty:
                    continue
                rows.append({"open": m["open"].iloc[0], "high": m["high"].max(), "low": m["low"].min(),
                             "close": m["close"].iloc[-1], "volume": m["volume"].sum(), "turnover": m["turnover"].sum()})
            else:
                prev, close = self._prev_close(symbol, d), float(series.get(d, 0.0)) or self._prev_close(symbol, d)
                rng = np.random.default_rng(_seed(symbol, d, "ohlc"))
                open_ = prev * np.exp(rng.normal(0, 0.005))
                hi = max(open_, close) * (1 + abs(rng.normal(0, 0.006)))
                lo = min(open_, close) * (1 - abs(rng.normal(0, 0.006)))
                vol = float(np.round(rng.lognormal(15, 0.4) / 100) * 100)
                rows.append({"open": open_, "high": hi, "low": lo, "close": close, "volume": vol, "turnover": vol * close})
            index.append(pd.Timestamp(d, tz=HK.tz))
        frame = pd.DataFrame(rows, index=pd.DatetimeIndex(index, name="time"), columns=["open", "high", "low", "close", "volume", "turnover"])
        return frame.round({"open": 3, "high": 3, "low": 3, "close": 3})

    def bars(self, symbol: str, ktype: str, start: date, end: date, until: datetime | None = None) -> pd.DataFrame:
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "turnover": "sum"}
        if ktype in ("K_DAY", "K_WEEK", "K_MON"):
            m = self.daily_bars(symbol, start, end, until)
            if ktype == "K_DAY" or m.empty:
                return m
            local = pd.DatetimeIndex(m.index).tz_convert(HK.tz)
            if ktype == "K_WEEK":
                key = (local.normalize() - pd.to_timedelta(local.weekday, unit="D"))
            else:
                key = local.normalize() - pd.to_timedelta(local.day - 1, unit="D")
            out = m.groupby(key).agg(agg)
            out.index = pd.DatetimeIndex(out.index, name="time")
            return out
        m = self.minute_bars(symbol, start, end, until)
        if ktype == "K_1M" or m.empty:
            return m
        minutes = int(ktype[2:-1])
        labels = session_labels(pd.DatetimeIndex(m.index), minutes, HK)
        out = m.groupby(labels).agg(agg)
        out.index.name = "time"
        return out

    def last(self, symbol: str, now: datetime | None = None) -> tuple[float, float]:
        """(last price, previous close) at ``now``."""
        now = now or self.clock()
        stamp = pd.Timestamp(now).tz_convert(HK.tz)
        day = stamp.date()
        while not self.is_trading_day(day):
            day -= timedelta(days=1)
        bars = self.day_bars(symbol, day)
        seen = bars[bars.index <= stamp.ceil("min")]
        prev = self._prev_close(symbol, day)
        if seen.empty:
            return prev, prev
        return float(seen["close"].iloc[-1]), prev


def _frame(symbol: str, name: str, bars: pd.DataFrame) -> pd.DataFrame:
    if bars.empty:
        return pd.DataFrame(columns=["code", "name", "time_key", "open", "close", "high", "low", "volume", "turnover"])
    local = pd.DatetimeIndex(bars.index).tz_convert(HK.tz).tz_localize(None)
    return pd.DataFrame(
        {
            "code": symbol,
            "name": name,
            "time_key": local.strftime("%Y-%m-%d %H:%M:%S"),
            "open": bars["open"].to_numpy(),
            "close": bars["close"].to_numpy(),
            "high": bars["high"].to_numpy(),
            "low": bars["low"].to_numpy(),
            "volume": bars["volume"].to_numpy(),
            "turnover": bars["turnover"].to_numpy(),
        }
    )


@dataclass
class _FilterItem:
    stock_code: str
    stock_name: str
    values: dict[int, float] = field(default_factory=dict)

    def __getitem__(self, key: Any) -> float:
        return self.values[id(key)]


class FakeQuoteContext:
    def __init__(self, market: SyntheticMarket, quota: int = 300, push_interval: float = 1.0) -> None:
        self.market = market
        self.quota_total = quota
        self.quota_codes: set[str] = set()
        self.subscriptions: dict[str, set[str]] = {}
        self.handlers: list[Any] = []
        self.push_interval = push_interval
        self.calls: list[str] = []
        self._pages: dict[str, tuple[pd.DataFrame, int]] = {}
        self._keys = itertools.count(1)
        self._stop = threading.Event()
        self._pusher: threading.Thread | None = None
        self.closed = False

    # -- helpers
    def _name(self, code: str) -> str:
        return self.market.symbols.get(code, (code, 1, 0))[0]

    def _known(self, code: str) -> bool:
        return code in self.market.symbols

    # -- history
    def request_history_kline(self, code: str, start: str | None = None, end: str | None = None, ktype: str = "K_DAY",
                              autype: str = "qfq", fields: Any = None, max_count: int = 1000,
                              page_req_key: Any = None, extended_time: bool = False, session: str = "N/A") -> tuple[int, Any, Any]:
        self.calls.append(f"history:{code}:{ktype}")
        if not self._known(code):
            return RET_ERROR, f"unknown stock {code}", None
        if page_req_key is None:
            if code not in self.quota_codes:
                if len(self.quota_codes) >= self.quota_total:
                    return RET_ERROR, "历史K线额度不足 (quota exceeded)", None
                self.quota_codes.add(code)
            s = date.fromisoformat(start[:10]) if start else date.today() - timedelta(days=365)
            e = date.fromisoformat(end[:10]) if end else s + timedelta(days=365)
            frame = _frame(code, self._name(code), self.market.bars(code, str(ktype), s, e, until=self.market.clock()))
            key = f"k{next(self._keys)}"
            self._pages[key] = (frame, 0)
        else:
            if page_req_key not in self._pages:
                return RET_ERROR, "bad page key", None
            key = page_req_key
        frame, pos = self._pages[key]
        chunk = frame.iloc[pos : pos + max_count]
        pos += max_count
        if pos >= len(frame):
            self._pages.pop(key, None)
            return RET_OK, chunk.reset_index(drop=True), None
        self._pages[key] = (frame, pos)
        return RET_OK, chunk.reset_index(drop=True), key

    def get_history_kl_quota(self, get_detail: bool = False) -> tuple[int, Any]:
        details = [{"code": c, "name": self._name(c), "request_time": ""} for c in sorted(self.quota_codes)]
        return RET_OK, (len(self.quota_codes), self.quota_total - len(self.quota_codes), details)

    # -- static info
    def get_stock_basicinfo(self, market: str, stock_type: str = "STOCK", code_list: list[str] | None = None) -> tuple[int, Any]:
        codes = code_list or [c for c in self.market.symbols if c.startswith(f"{market}.")]
        rows = [
            {"code": c, "name": self._name(c), "lot_size": self.market.symbols[c][1],
             "stock_type": "IDX" if c == "HK.800000" else "STOCK", "listing_date": "2004-06-16"}
            for c in codes if self._known(c)
        ]
        return RET_OK, pd.DataFrame(rows)

    def get_market_snapshot(self, code_list: list[str]) -> tuple[int, Any]:
        now = self.market.clock()
        rows = []
        for c in code_list:
            if not self._known(c):
                return RET_ERROR, f"unknown stock {c}"
            last, prev = self.market.last(c, now)
            tick = 0.05 if last >= 20 else 0.01
            rows.append({
                "code": c, "name": self._name(c), "last_price": last, "prev_close_price": prev,
                "bid_price": round(last - tick, 3), "ask_price": round(last + tick, 3),
                "lot_size": self.market.symbols[c][1], "turnover": last * 2e7, "volume": 2e7 / 100,
                "total_market_val": last * 1e10, "pe_ttm_ratio": 15.0, "suspension": False,
                "update_time": pd.Timestamp(now).tz_convert(HK.tz).strftime("%Y-%m-%d %H:%M:%S"),
            })
        return RET_OK, pd.DataFrame(rows)

    def request_trading_days(self, market: Any = None, start: str | None = None, end: str | None = None, code: Any = None) -> tuple[int, Any]:
        s = date.fromisoformat(start) if start else date.today() - timedelta(days=30)
        e = date.fromisoformat(end) if end else date.today()
        return RET_OK, [{"time": d.isoformat(), "trade_date_type": "WHOLE"} for d in self.market.trading_days(s, e)]

    def get_stock_filter(self, market: str, filter_list: list[Any] | None = None, plate_code: Any = None, begin: int = 0, num: int = 200) -> tuple[int, Any]:
        self.calls.append("stock_filter")
        codes = [c for c in self.market.symbols if c.startswith(f"{market}.") and c != "HK.800000"]
        items = []
        for c in codes:
            last, prev = self.market.last(c)
            item = _FilterItem(c, self._name(c))
            ok = True
            for flt in filter_list or []:
                fld = str(getattr(flt, "stock_field", getattr(flt, "stock_field1", "")))
                value = {"CUR_PRICE": last, "TURNOVER": last * 2e7, "CHANGE_RATE": (last / prev - 1) * 100,
                         "MARKET_VAL": last * 1e10, "PE_TTM": 15.0}.get(fld, last)
                item.values[id(flt)] = value
                lo, hi = getattr(flt, "filter_min", None), getattr(flt, "filter_max", None)
                if (lo is not None and value < lo) or (hi is not None and value > hi):
                    ok = False
            if ok:
                items.append(item)
        page = items[begin : begin + num]
        return RET_OK, (begin + num >= len(items), len(items), page)

    # -- subscription / push
    def subscribe(self, code_list: list[str], subtype_list: list[str], is_first_push: bool = True, subscribe_push: bool = True, **_: Any) -> tuple[int, Any]:
        for c in code_list:
            if not self._known(c):
                return RET_ERROR, f"unknown stock {c}"
            self.subscriptions.setdefault(c, set()).update(str(s) for s in subtype_list)
        if subscribe_push and self._pusher is None and self.push_interval > 0:
            self._pusher = threading.Thread(target=self._push_loop, daemon=True, name="fake-opend-push")
            self._pusher.start()
        return RET_OK, None

    def unsubscribe(self, code_list: list[str], subtype_list: list[str], **_: Any) -> tuple[int, Any]:
        for c in code_list:
            self.subscriptions.pop(c, None)
        return RET_OK, None

    def query_subscription(self, is_all_conn: bool = True) -> tuple[int, Any]:
        used = sum(len(v) for v in self.subscriptions.values())
        return RET_OK, {"total_used": used, "remain": 300 - used, "own_used": used, "sub_list": {}}

    def set_handler(self, handler: Any) -> int:
        self.handlers.append(handler)
        return RET_OK

    def get_cur_kline(self, code: str, num: int, ktype: str = "K_DAY", autype: str = "qfq") -> tuple[int, Any]:
        if code not in self.subscriptions or str(ktype) not in self.subscriptions[code]:
            return RET_ERROR, f"请先订阅 {code} {ktype}"
        now = self.market.clock()
        today = pd.Timestamp(now).tz_convert(HK.tz).date()
        lookback = {"K_DAY": 1500, "K_WEEK": 3000, "K_MON": 6000}.get(str(ktype), max(3, num // 300 + 3))
        bars = self.market.bars(code, str(ktype), today - timedelta(days=lookback), today, until=now)
        return RET_OK, _frame(code, self._name(code), bars.iloc[-num:])

    def push_now(self) -> None:
        for code, types in list(self.subscriptions.items()):
            for kt in types:
                ret, frame = self.get_cur_kline(code, 2, kt)
                if ret != RET_OK:
                    continue
                for h in self.handlers:
                    deliver = getattr(h, "deliver", None)
                    if deliver is not None:
                        deliver(frame)

    def _push_loop(self) -> None:
        while not self._stop.wait(self.push_interval):
            with contextlib.suppress(Exception):  # demo only: never kill the pusher
                self.push_now()

    def close(self) -> None:
        self._stop.set()
        self.closed = True


class FakeTradeContext:
    """A SIMULATE HK securities account that fills marketable orders at the synthetic price."""

    def __init__(self, market: SyntheticMarket, cash: float = 1_000_000.0, acc_id: int = 1001) -> None:
        self.market = market
        self.cash = cash
        self.acc_id = acc_id
        self.positions: dict[str, dict[str, float]] = {}
        self.orders: dict[str, dict[str, Any]] = {}
        self.handlers: list[Any] = []
        self._ids = itertools.count(1)
        self._lock = threading.RLock()
        self.closed = False
        self.fee_rate = 0.0005

    def get_acc_list(self) -> tuple[int, Any]:
        return RET_OK, pd.DataFrame([
            {"acc_id": self.acc_id, "trd_env": "SIMULATE", "acc_type": "CASH", "sim_acc_type": "STOCK",
             "trdmarket_auth": ["HK"], "acc_status": "ACTIVE", "security_firm": "FUTUSECURITIES"},
            {"acc_id": 9999, "trd_env": "REAL", "acc_type": "CASH", "sim_acc_type": "N/A",
             "trdmarket_auth": ["HK"], "acc_status": "ACTIVE", "security_firm": "FUTUSECURITIES"},
        ])

    def unlock_trade(self, password: Any = None, password_md5: Any = None, is_unlock: bool = True) -> tuple[int, Any]:
        return RET_OK, None

    def set_handler(self, handler: Any) -> int:
        self.handlers.append(handler)
        return RET_OK

    def _match(self) -> None:
        now = self.market.clock()
        for o in self.orders.values():
            if o["order_status"] not in ("SUBMITTED",):
                continue
            last, _ = self.market.last(o["code"], now)
            tick = 0.05 if last >= 20 else 0.01
            ask, bid = last + tick, last - tick
            if o["trd_side"] == "BUY" and (o["order_type"] == "MARKET" or ask <= o["price"] + 1e-9):
                self._fill(o, ask if o["order_type"] == "MARKET" else min(ask, o["price"]))
            elif o["trd_side"] == "SELL" and (o["order_type"] == "MARKET" or bid >= o["price"] - 1e-9):
                self._fill(o, bid if o["order_type"] == "MARKET" else max(bid, o["price"]))

    def _fill(self, o: dict[str, Any], price: float) -> None:
        qty = o["qty"]
        fee = qty * price * self.fee_rate
        pos = self.positions.setdefault(o["code"], {"qty": 0.0, "cost": 0.0})
        if o["trd_side"] == "BUY":
            self.cash -= qty * price + fee
            pos["cost"] += qty * price + fee
            pos["qty"] += qty
        else:
            avg = pos["cost"] / pos["qty"] if pos["qty"] else 0
            self.cash += qty * price - fee
            pos["cost"] -= avg * qty
            pos["qty"] -= qty
        o.update(order_status="FILLED_ALL", dealt_qty=qty, dealt_avg_price=price,
                 updated_time=pd.Timestamp(self.market.clock()).tz_convert(HK.tz).strftime("%Y-%m-%d %H:%M:%S"))

    def place_order(self, price: float, qty: float, code: str, trd_side: str, order_type: str = "NORMAL", adjust_limit: float = 0,
                    trd_env: str = "REAL", acc_id: int = 0, acc_index: int = 0, remark: str | None = None, **_: Any) -> tuple[int, Any]:
        with self._lock:
            if code not in self.market.symbols:
                return RET_ERROR, f"unknown stock {code}"
            lot = self.market.symbols[code][1]
            if int(qty) % lot:
                return RET_ERROR, f"数量必须是每手股数({lot})的整数倍"
            if str(trd_side) == "SELL" and self.positions.get(code, {}).get("qty", 0) < qty:
                return RET_ERROR, "可卖数量不足"
            oid = f"F{next(self._ids):08d}"
            stamp = pd.Timestamp(self.market.clock()).tz_convert(HK.tz).strftime("%Y-%m-%d %H:%M:%S")
            self.orders[oid] = {
                "order_id": oid, "code": code, "stock_name": self.market.symbols[code][0], "trd_side": str(trd_side),
                "order_type": str(order_type), "order_status": "SUBMITTED", "qty": float(qty), "price": float(price),
                "create_time": stamp, "updated_time": stamp, "dealt_qty": 0.0, "dealt_avg_price": 0.0,
                "last_err_msg": "", "remark": remark or "",
            }
            self._match()
            row = dict(self.orders[oid])
        for h in self.handlers:
            deliver = getattr(h, "deliver", None)
            if deliver:
                deliver(None)
        return RET_OK, pd.DataFrame([row])

    def modify_order(self, modify_order_op: str, order_id: str, qty: float, price: float, adjust_limit: float = 0,
                     trd_env: str = "REAL", acc_id: int = 0, acc_index: int = 0, **_: Any) -> tuple[int, Any]:
        with self._lock:
            o = self.orders.get(order_id)
            if o is None:
                return RET_ERROR, "order not found"
            if str(modify_order_op) == "CANCEL" and o["order_status"] == "SUBMITTED":
                o["order_status"] = "CANCELLED_ALL"
            return RET_OK, pd.DataFrame([{"order_id": order_id}])

    def order_list_query(self, **_: Any) -> tuple[int, Any]:
        with self._lock:
            self._match()
            return RET_OK, pd.DataFrame(list(self.orders.values()), columns=[
                "order_id", "code", "stock_name", "trd_side", "order_type", "order_status", "qty", "price",
                "create_time", "updated_time", "dealt_qty", "dealt_avg_price", "last_err_msg", "remark"])

    def position_list_query(self, **_: Any) -> tuple[int, Any]:
        with self._lock:
            self._match()
            rows: list[dict[str, Any]] = []
            for code, p in self.positions.items():
                if p["qty"] <= 0:
                    continue
                last, _prev = self.market.last(code)
                avg = p["cost"] / p["qty"]
                rows.append({"code": code, "stock_name": self.market.symbols[code][0], "qty": p["qty"], "can_sell_qty": p["qty"],
                             "cost_price": avg, "average_cost": avg, "nominal_price": last, "market_val": last * p["qty"],
                             "pl_val": (last - avg) * p["qty"], "unrealized_pl": (last - avg) * p["qty"], "pl_ratio": (last / avg - 1) * 100})
            return RET_OK, pd.DataFrame(rows, columns=["code", "stock_name", "qty", "can_sell_qty", "cost_price", "average_cost",
                                                        "nominal_price", "market_val", "pl_val", "unrealized_pl", "pl_ratio"])

    def accinfo_query(self, **_: Any) -> tuple[int, Any]:
        with self._lock:
            self._match()
            mv = sum(self.market.last(c)[0] * p["qty"] for c, p in self.positions.items() if p["qty"] > 0)
            return RET_OK, pd.DataFrame([{"total_assets": self.cash + mv, "cash": self.cash, "market_val": mv,
                                           "power": self.cash, "currency": "HKD", "realized_pl": 0.0, "unrealized_pl": 0.0}])

    def close(self) -> None:
        self.closed = True


class FakeOpenD:
    """Factory pair for :class:`~futu_algo.app.App` (``quote_factory`` / ``trade_factory``)."""

    def __init__(self, market: SyntheticMarket | None = None, *, cash: float = 1_000_000.0, push_interval: float = 1.0) -> None:
        self.market = market or SyntheticMarket()
        self.quote = FakeQuoteContext(self.market, push_interval=push_interval)
        self.trade = FakeTradeContext(self.market, cash=cash)

    def quote_factory(self, host: str, port: int) -> FakeQuoteContext:
        return self.quote

    def trade_factory(self, host: str, port: int, firm: str, encrypt: bool) -> FakeTradeContext:
        return self.trade
