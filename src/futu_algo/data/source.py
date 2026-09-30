"""Historical data sources: the protocol and the Futu OpenD implementation."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Protocol

import pandas as pd

from futu_algo.data.schema import to_bars
from futu_algo.data.store import InstrumentInfo
from futu_algo.errors import DataSourceError
from futu_algo.futu_gateway import QuoteGateway
from futu_algo.market.instrument import MARKETS, parse_symbol

log = logging.getLogger(__name__)

# Futu AuType values are plain strings: AuType.QFQ == "qfq", AuType.NONE == "None".
AUTYPE = {"qfq": "qfq", "hfq": "hfq", "none": "None"}
PAGE_SIZE = 1000


@dataclass
class QuotaStatus:
    used: int
    remaining: int
    codes: set[str] = field(default_factory=set)


class DataSource(Protocol):
    name: str

    def fetch_bars(
        self, symbol: str, ktype: str, adjust: str, start: date, end: date
    ) -> pd.DataFrame: ...

    def fetch_instruments(self, symbols: list[str]) -> dict[str, InstrumentInfo]: ...

    def quota(self) -> QuotaStatus | None: ...

    def close(self) -> None: ...


class FutuSource:
    """Historical K-lines, instrument metadata and quota from OpenD.

    ``request_history_kline`` is paged by hand (1,000 bars per page) so long intraday
    histories are never silently truncated to their first page.
    """

    name = "futu"

    def __init__(self, gateway: QuoteGateway, *, owns_gateway: bool = False) -> None:
        self.gateway = gateway
        self._owns = owns_gateway

    def close(self) -> None:
        if self._owns:
            self.gateway.close()

    def fetch_bars(
        self, symbol: str, ktype: str, adjust: str, start: date, end: date
    ) -> pd.DataFrame:
        market = MARKETS[parse_symbol(symbol)[0]]
        frames: list[pd.DataFrame] = []
        page_key: Any = None
        pages = 0
        while True:
            key = page_key
            _, data, page_key = self.gateway.call(
                "history_kline",
                f"request_history_kline({symbol}, {ktype}, {adjust}, {start}..{end})",
                lambda ctx, key=key: ctx.request_history_kline(
                    symbol,
                    start=start.isoformat(),
                    end=end.isoformat(),
                    ktype=ktype,
                    autype=AUTYPE[adjust],
                    max_count=PAGE_SIZE,
                    page_req_key=key,
                ),
            )
            pages += 1
            if data is not None and len(data):
                frames.append(data)
            if page_key is None:
                break
        raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        bars = to_bars(raw, market.tz)
        log.info(
            "Fetched %s %s %s %s..%s: %d bars in %d page(s)",
            symbol, ktype, adjust, start, end, len(bars), pages,
        )
        return bars

    def fetch_instruments(self, symbols: list[str]) -> dict[str, InstrumentInfo]:
        if not symbols:
            return {}
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        out: dict[str, InstrumentInfo] = {}
        by_market: dict[str, list[str]] = {}
        for sym in symbols:
            by_market.setdefault(parse_symbol(sym)[0], []).append(sym)
        for market, codes in by_market.items():
            try:
                _, frame = self.gateway.call(
                    "basicinfo",
                    f"get_stock_basicinfo({market})",
                    lambda ctx, market=market, codes=codes: ctx.get_stock_basicinfo(
                        market, "STOCK", codes
                    ),
                )
            except DataSourceError as exc:
                log.warning("get_stock_basicinfo failed for %s: %s", codes, exc)
                continue
            for row in frame.to_dict("records"):
                sym = str(row["code"])
                out[sym] = InstrumentInfo(
                    symbol=sym,
                    name=str(row.get("name") or ""),
                    lot_size=max(int(row.get("lot_size") or 1), 1),
                    security_type=str(row.get("stock_type") or "STOCK"),
                    listing_date=str(row.get("listing_date") or "") or None,
                    updated_at=stamp,
                )
        missing = [s for s in symbols if s not in out]
        if missing:
            try:
                _, snap = self.gateway.call(
                    "snapshot", "get_market_snapshot", lambda ctx: ctx.get_market_snapshot(missing)
                )
                for row in snap.to_dict("records"):
                    sym = str(row["code"])
                    out[sym] = InstrumentInfo(
                        symbol=sym,
                        name=str(row.get("name") or ""),
                        lot_size=max(int(row.get("lot_size") or 1), 1),
                        security_type="STOCK",
                        listing_date=None,
                        updated_at=stamp,
                    )
            except DataSourceError as exc:
                log.warning("get_market_snapshot failed for %s: %s", missing, exc)
        return out

    def quota(self) -> QuotaStatus | None:
        try:
            _, (used, remaining, details) = self.gateway.call(
                "default",
                "get_history_kl_quota",
                lambda ctx: ctx.get_history_kl_quota(get_detail=True),
            )
        except DataSourceError as exc:
            log.warning("Could not read historical K-line quota: %s", exc)
            return None
        return QuotaStatus(
            used=int(used),
            remaining=int(remaining),
            codes={str(d.get("code")) for d in details or []},
        )

    def trading_days(self, market: str, start: date, end: date) -> list[date]:
        _, data = self.gateway.call(
            "trading_days",
            f"request_trading_days({market})",
            lambda ctx: ctx.request_trading_days(
                market=market, start=start.isoformat(), end=end.isoformat()
            ),
        )
        days: list[date] = []
        for row in data or []:
            if str(row.get("trade_date_type", "WHOLE")).upper() in {"WHOLE", "MORNING", "AFTERNOON"}:
                days.append(date.fromisoformat(str(row["time"])[:10]))
        return days
