"""Futu OpenD broker: ``OpenSecTradeContext`` for HK securities.

Notes that shape this implementation (futu-api 10.x):

* ``OpenHKTradeContext`` was removed in 10.3; ``OpenSecTradeContext(filter_trdmarket=HK)`` is
  the replacement, and since 10.4 its ``security_firm`` default is ``NONE``, so it is always
  passed explicitly.
* Paper (``SIMULATE``) accounts get order pushes but no deal pushes, so fills are derived from
  each order's ``dealt_qty`` by polling; pushes only make the engine poll sooner.
* ``unlock_trade`` only applies to ``REAL`` accounts.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import pandas as pd

from futu_algo.errors import BrokerError, ConfigError, DataSourceError
from futu_algo.futu_gateway import (
    RET_OK,
    QuoteGateway,
    RateLimiter,
    configure_futu_runtime,
    is_rate_limited,
    probe_opend,
)
from futu_algo.live.models import (
    FUTU_STATUS,
    AccountSnapshot,
    OrderInfo,
    OrderRequest,
    OrderState,
    PositionInfo,
    Quote,
)
from futu_algo.market.instrument import MARKETS

log = logging.getLogger(__name__)


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return default if out != out else out  # NaN -> default


def _ts(value: Any, tz: str) -> datetime | None:
    if value in (None, "", "N/A"):
        return None
    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    return (ts.tz_localize(tz) if ts.tzinfo is None else ts).to_pydatetime()


def order_from_row(row: dict[str, Any], tz: str) -> OrderInfo:
    status = str(row.get("order_status", ""))
    return OrderInfo(
        order_id=str(row["order_id"]),
        symbol=str(row["code"]),
        side="BUY" if str(row.get("trd_side", "")).upper().startswith("BUY") else "SELL",
        quantity=int(_f(row.get("qty"))),
        price=_f(row.get("price")),
        state=FUTU_STATUS.get(status, OrderState.SUBMITTED),
        order_type=str(row.get("order_type", "NORMAL")),
        filled_qty=int(_f(row.get("dealt_qty"))),
        avg_fill_price=_f(row.get("dealt_avg_price")),
        created=_ts(row.get("create_time"), tz),
        updated=_ts(row.get("updated_time"), tz),
        remark=str(row.get("remark") or ""),
        error=str(row.get("last_err_msg") or ""),
        name=str(row.get("stock_name") or ""),
    )


def _default_trade_factory(host: str, port: int, firm: str, encrypt: bool) -> Any:
    from futu import OpenSecTradeContext, TrdMarket

    configure_futu_runtime()
    try:
        probe_opend(host, port)
    except DataSourceError as exc:
        raise BrokerError(str(exc)) from None

    return OpenSecTradeContext(
        filter_trdmarket=TrdMarket.HK,
        host=host,
        port=port,
        is_encrypt=encrypt or None,
        security_firm=firm,
    )


class FutuBroker:
    name = "futu"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        env: str = "SIMULATE",
        security_firm: str = "FUTUSECURITIES",
        password_md5: str | None = None,
        acc_id: int | None = None,
        encrypt: bool = False,
        context_factory: Callable[[str, int, str, bool], Any] | None = None,
        market: str = "HK",
    ) -> None:
        if env not in ("SIMULATE", "REAL"):
            raise ConfigError(f"Unknown trading env {env!r}")
        self.host, self.port = host, port
        self.env = env
        self.firm = security_firm
        self.password_md5 = password_md5
        self.acc_id = acc_id
        self.encrypt = encrypt
        self.market = MARKETS[market]
        self._factory = context_factory or _default_trade_factory
        self._ctx: Any = None
        self._lock = threading.RLock()
        self._listener: Callable[[], None] | None = None
        # Futu limits trade queries only when refresh_cache=True (10 per 30 s per API); cached
        # reads are served by OpenD, which keeps them current from its own pushes.
        self._limiter = RateLimiter(10, 30.0)
        self._order_limiter = RateLimiter(15, 30.0)
        self._refresh_every = 20.0
        self._last_refresh: dict[str, float] = {}

    # ---------------------------------------------------------------- lifecycle

    def connect(self) -> None:
        with self._lock:
            if self._ctx is not None:
                return
            log.info("Connecting trade context (%s, %s) to %s:%s", self.env, self.firm, self.host, self.port)
            try:
                self._ctx = self._factory(self.host, self.port, self.firm, self.encrypt)
            except BrokerError:
                raise
            except Exception as exc:
                raise BrokerError(f"Cannot open Futu trade context at {self.host}:{self.port}: {exc}") from exc
            self._install_handler()
            self.acc_id = self._resolve_account()
            if self.env == "REAL":
                self._unlock()
            log.info("Using Futu %s account %s", self.env, self.acc_id)

    def close(self) -> None:
        with self._lock:
            if self._ctx is not None:
                try:
                    self._ctx.close()
                finally:
                    self._ctx = None

    def set_order_listener(self, callback: Callable[[], None]) -> None:
        self._listener = callback

    def _install_handler(self) -> None:
        try:
            from futu import TradeDealHandlerBase, TradeOrderHandlerBase
        except ImportError:  # pragma: no cover
            return
        broker = self

        class _Orders(TradeOrderHandlerBase):
            def on_recv_rsp(self, rsp_pb: Any) -> Any:
                ret, data = super().on_recv_rsp(rsp_pb)
                if ret == RET_OK and broker._listener:
                    broker._listener()
                return ret, data

            def deliver(self, _data: Any) -> None:
                if broker._listener:
                    broker._listener()

        class _Deals(TradeDealHandlerBase):
            def on_recv_rsp(self, rsp_pb: Any) -> Any:
                ret, data = super().on_recv_rsp(rsp_pb)
                if ret == RET_OK and broker._listener:
                    broker._listener()
                return ret, data

        try:
            self._ctx.set_handler(_Orders())
            self._ctx.set_handler(_Deals())
        except Exception:  # fake contexts in tests may not support handlers
            log.debug("Trade push handlers not installed", exc_info=True)

    # ----------------------------------------------------------------- plumbing

    def _refresh(self, api: str) -> bool:
        """Whether this query should bypass OpenD's cache (rate-limited), at most every 20 s."""
        now = time.monotonic()
        if now - self._last_refresh.get(api, -1e9) >= self._refresh_every:
            self._last_refresh[api] = now
            return True
        return False

    def force_refresh(self) -> None:
        self._last_refresh.clear()

    def _call(
        self, what: str, fn: Callable[[Any], tuple[Any, ...]], *, order: bool = False, limited: bool = True
    ) -> Any:
        if self._ctx is None:
            self.connect()
        limiter = self._order_limiter if order else self._limiter
        for attempt in range(3):
            if limited:
                limiter.acquire()
            ret, data = fn(self._ctx)[:2]
            if ret == RET_OK:
                return data
            if is_rate_limited(str(data)) and attempt < 2:
                continue
            raise BrokerError(f"{what} failed: {data}")
        raise BrokerError(f"{what} failed: rate limited")  # pragma: no cover

    def _resolve_account(self) -> int:
        data = self._call("get_acc_list", lambda ctx: ctx.get_acc_list())
        rows = data.to_dict("records") if hasattr(data, "to_dict") else list(data)
        if self.acc_id is not None:
            if not any(int(r["acc_id"]) == int(self.acc_id) for r in rows):
                raise BrokerError(f"Account {self.acc_id} not found in get_acc_list")
            return int(self.acc_id)
        candidates = []
        for r in rows:
            if str(r.get("trd_env")) != self.env:
                continue
            if str(r.get("acc_status", "ACTIVE")).upper() not in ("ACTIVE", "N/A"):
                continue
            auth = r.get("trdmarket_auth") or []
            if auth and "HK" not in [str(a) for a in auth]:
                continue
            sim_type = str(r.get("sim_acc_type", "N/A")).upper()
            if self.env == "SIMULATE" and sim_type not in ("STOCK", "N/A", "STOCK_AND_OPTION"):
                continue
            candidates.append(int(r["acc_id"]))
        if not candidates:
            raise BrokerError(
                f"No active {self.env} HK securities account found. Check OpenD login and "
                "trading.acc_id in the config."
            )
        return candidates[0]

    def _unlock(self) -> None:
        if not self.password_md5:
            raise BrokerError(
                "REAL trading needs the trade password MD5 in the environment variable named by "
                "futu.trade_password_md5_env"
            )
        self._call("unlock_trade", lambda ctx: ctx.unlock_trade(password_md5=self.password_md5))

    @property
    def _kw(self) -> dict[str, Any]:
        return {"trd_env": self.env, "acc_id": self.acc_id}

    # ------------------------------------------------------------------ queries

    def account(self) -> AccountSnapshot:
        refresh = self._refresh("accinfo")
        data = self._call(
            "accinfo_query",
            lambda ctx: ctx.accinfo_query(refresh_cache=refresh, currency=self.market.currency, **self._kw),
            limited=refresh,
        )
        row = data.iloc[0].to_dict()
        return AccountSnapshot(
            currency=str(row.get("currency") or self.market.currency),
            equity=_f(row.get("total_assets")),
            cash=_f(row.get("cash")),
            market_value=_f(row.get("market_val")),
            buying_power=_f(row.get("power"), _f(row.get("cash"))),
            realized_pl=_f(row.get("realized_pl")),
            unrealized_pl=_f(row.get("unrealized_pl")),
            time=datetime.now().astimezone(),
        )

    def positions(self) -> dict[str, PositionInfo]:
        refresh = self._refresh("positions")
        data = self._call(
            "position_list_query",
            lambda ctx: ctx.position_list_query(refresh_cache=refresh, **self._kw),
            limited=refresh,
        )
        out: dict[str, PositionInfo] = {}
        for row in data.to_dict("records"):
            qty = int(_f(row.get("qty")))
            if qty == 0:
                continue
            sym = str(row["code"])
            out[sym] = PositionInfo(
                symbol=sym,
                quantity=qty,
                can_sell=int(_f(row.get("can_sell_qty"), qty)),
                cost_price=_f(row.get("average_cost"), _f(row.get("cost_price"))) or _f(row.get("cost_price")),
                last_price=_f(row.get("nominal_price")),
                market_value=_f(row.get("market_val")),
                unrealized_pl=_f(row.get("unrealized_pl"), _f(row.get("pl_val"))),
                unrealized_pl_pct=_f(row.get("pl_ratio")) / 100,
                name=str(row.get("stock_name") or ""),
            )
        return out

    def orders(self) -> list[OrderInfo]:
        refresh = self._refresh("orders")
        data = self._call(
            "order_list_query",
            lambda ctx: ctx.order_list_query(refresh_cache=refresh, **self._kw),
            limited=refresh,
        )
        return [order_from_row(r, self.market.tz) for r in data.to_dict("records")]

    # ------------------------------------------------------------------- orders

    def place(self, request: OrderRequest) -> OrderInfo:
        from futu import OrderType, TrdSide

        order_type = OrderType.MARKET if request.is_market else OrderType.NORMAL
        price = 0.0 if request.price is None else float(request.price)
        data = self._call(
            f"place_order({request.symbol} {request.side} {request.quantity}@{price})",
            lambda ctx: ctx.place_order(
                price=price,
                qty=int(request.quantity),
                code=request.symbol,
                trd_side=TrdSide.BUY if request.side == "BUY" else TrdSide.SELL,
                order_type=order_type,
                remark=request.remark[:60] or None,
                **self._kw,
            ),
            order=True,
        )
        row = data.iloc[0].to_dict()
        row.setdefault("code", request.symbol)
        row.setdefault("qty", request.quantity)
        row.setdefault("price", price)
        row.setdefault("trd_side", request.side)
        info = order_from_row(row, self.market.tz)
        if info.state == OrderState.FAILED:
            raise BrokerError(f"Order rejected: {info.error or row}")
        return info

    def cancel(self, order_id: str) -> None:
        from futu import ModifyOrderOp

        self._call(
            f"cancel({order_id})",
            lambda ctx: ctx.modify_order(ModifyOrderOp.CANCEL, order_id, 0, 0, **self._kw),
            order=True,
        )


class FutuQuoteProvider:
    """Best bid/ask and last price from market snapshots (no subscription quota needed)."""

    def __init__(self, gateway: QuoteGateway) -> None:
        self.gateway = gateway

    def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        if not symbols:
            return {}
        _, data = self.gateway.call("snapshot", "get_market_snapshot", lambda ctx: ctx.get_market_snapshot(symbols))
        out: dict[str, Quote] = {}
        for row in data.to_dict("records"):
            sym = str(row["code"])
            bid = _f(row.get("bid_price")) or None
            ask = _f(row.get("ask_price")) or None
            out[sym] = Quote(
                symbol=sym,
                last=_f(row.get("last_price")),
                bid=bid,
                ask=ask,
                lot_size=int(_f(row.get("lot_size"))) or None,
                suspended=bool(row.get("suspension", False)) is True,
                time=datetime.now().astimezone(),
            )
        return out
