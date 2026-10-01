"""Markets and instruments.

Symbols use Futu's ``MARKET.CODE`` convention (``HK.00700``, ``US.AAPL``). Hong Kong is the
primary market. US equities are modelled for data, backtests and costs; live trading in this
release is limited to HK.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import time

import pandas as pd

from futu_algo.errors import ConfigError


@dataclass(frozen=True)
class MarketSpec:
    code: str
    currency: str
    tz: str
    # Continuous trading sessions in exchange-local time, in order.
    sessions: tuple[tuple[time, time], ...]
    trading_days_per_year: int
    # Auctions around the continuous sessions (exchange-local), informational.
    pre_open: tuple[time, time] | None = None
    closing_auction: tuple[time, time] | None = None

    @property
    def open_time(self) -> time:
        return self.sessions[0][0]

    @property
    def close_time(self) -> time:
        return self.sessions[-1][1]

    @property
    def session_minutes(self) -> int:
        return sum(_m(end) - _m(start) for start, end in self.sessions)

    def bars_per_day(self, minutes: int) -> int:
        """Number of end-labelled intraday bars per day, counting truncated session tails."""
        return sum(-(-(_m(end) - _m(start)) // minutes) for start, end in self.sessions)


def _m(t: time) -> int:
    return t.hour * 60 + t.minute


MARKETS: dict[str, MarketSpec] = {
    "HK": MarketSpec(
        code="HK",
        currency="HKD",
        tz="Asia/Hong_Kong",
        sessions=((time(9, 30), time(12, 0)), (time(13, 0), time(16, 0))),
        trading_days_per_year=247,
        pre_open=(time(9, 0), time(9, 30)),
        closing_auction=(time(16, 0), time(16, 10)),
    ),
    "US": MarketSpec(
        code="US",
        currency="USD",
        tz="America/New_York",
        sessions=((time(9, 30), time(16, 0)),),
        trading_days_per_year=252,
    ),
}

_SYMBOL_RE = re.compile(r"^(?P<market>[A-Z]+)\.(?P<code>[A-Z0-9.\-]+)$")


def parse_symbol(symbol: str) -> tuple[str, str]:
    """Split ``HK.00700`` into (``HK``, ``00700``), validating the market."""
    normalized = str(symbol).strip().upper()
    match = _SYMBOL_RE.match(normalized)
    if not match:
        raise ConfigError(
            f"Invalid symbol {symbol!r}; expected Futu format like HK.00700 or US.AAPL"
        )
    market, code = match["market"], match["code"]
    if market not in MARKETS:
        raise ConfigError(
            f"Market {market!r} in {symbol!r} is not supported; supported markets: {sorted(MARKETS)}"
        )
    if market == "HK" and code.isdigit():
        code = code.zfill(5)
    return market, code


def normalize_symbol(symbol: str) -> str:
    market, code = parse_symbol(symbol)
    return f"{market}.{code}"


def market_of(symbol: str) -> MarketSpec:
    return MARKETS[parse_symbol(symbol)[0]]


@dataclass(frozen=True)
class Instrument:
    symbol: str
    lot_size: int = 1
    name: str = ""
    # Futu SecurityType string: STOCK, ETF, IDX, WARRANT, ...
    security_type: str = "STOCK"
    market: MarketSpec = field(init=False)

    def __post_init__(self) -> None:
        market, code = parse_symbol(self.symbol)
        object.__setattr__(self, "symbol", f"{market}.{code}")
        object.__setattr__(self, "market", MARKETS[market])
        if self.lot_size < 1:
            raise ConfigError(f"Lot size for {self.symbol} must be >= 1, got {self.lot_size}")

    @property
    def code(self) -> str:
        return self.symbol.split(".", 1)[1]

    @property
    def currency(self) -> str:
        return self.market.currency

    @property
    def tz(self) -> str:
        return self.market.tz

    @property
    def is_index(self) -> bool:
        return self.security_type.upper() in {"IDX", "INDEX"}

    def to_local(self, ts: pd.Timestamp) -> pd.Timestamp:
        return ts.tz_convert(self.tz) if ts.tzinfo else ts.tz_localize(self.tz)
