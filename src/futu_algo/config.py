"""Configuration: one YAML file validated by pydantic.

Secrets never live in the YAML. Each secret field names an environment variable instead
(``password_env: FUTU_ALGO_SMTP_PASSWORD``), and a ``.env`` file next to the config is loaded
into the environment on startup if present. Relative paths are resolved against the config
file's directory, so the process can be started from anywhere.
"""

from __future__ import annotations

import os
import re
from datetime import date, time
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from futu_algo.errors import ConfigError
from futu_algo.market.costs import HKBrokerFees, USBrokerFees
from futu_algo.market.instrument import normalize_symbol
from futu_algo.timeframe import Timeframe

EXAMPLE_CONFIG = Path(__file__).with_name("example_config.yaml")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


def _tf(value: str) -> str:
    return str(Timeframe.parse(value))


# --------------------------------------------------------------------------- connection


class FutuConfig(_Model):
    host: str = "127.0.0.1"
    port: int = Field(11111, ge=1, le=65535)
    rsa_private_key: str | None = Field(
        None, description="PKCS#1 key file; required by OpenD for trading over a non-local address"
    )
    security_firm: str = Field(
        "FUTUSECURITIES", description="Futu SecurityFirm; set explicitly since futu-api 10.4"
    )
    trade_password_md5_env: str = "FUTU_TRADE_PASSWORD_MD5"


class DataConfig(_Model):
    dir: Path = Path("data")
    adjust: Literal["qfq", "hfq", "none"] = "qfq"
    offline: bool = False
    instrument_ttl_days: int = Field(7, ge=0)
    lot_sizes: dict[str, int] = Field(default_factory=dict)

    @field_validator("lot_sizes")
    @classmethod
    def _norm_lots(cls, v: dict[str, int]) -> dict[str, int]:
        return {normalize_symbol(k): int(n) for k, n in v.items()}


# --------------------------------------------------------------------------- shared trading


class SimpleCostConfig(_Model):
    rate: float = Field(0.001, ge=0)
    min_fee: float = Field(0.0, ge=0)


class CostsConfig(_Model):
    model: Literal["market", "simple"] = "market"
    hk: HKBrokerFees = Field(default_factory=HKBrokerFees)
    us: USBrokerFees = Field(default_factory=USBrokerFees)
    simple: SimpleCostConfig = Field(default_factory=SimpleCostConfig)


Sizer = Literal["equal_weight", "fixed_value", "fixed_lots", "percent_equity", "all_in"]


class SizingConfig(_Model):
    method: Sizer = "equal_weight"
    max_positions: int = Field(5, ge=1)
    value: float | None = Field(None, gt=0, description="fixed_value: currency per position")
    lots: int = Field(1, ge=1, description="fixed_lots: board lots per position")
    percent: float | None = Field(None, gt=0, le=1, description="percent_equity: 0-1")

    @model_validator(mode="after")
    def _check(self) -> SizingConfig:
        if self.method == "fixed_value" and self.value is None:
            raise ValueError("sizing.value is required for method fixed_value")
        if self.method == "percent_equity" and self.percent is None:
            raise ValueError("sizing.percent is required for method percent_equity")
        return self


class ExitRules(_Model):
    stop_loss: float | None = Field(None, gt=0, lt=1, description="Fraction below entry")
    trailing_stop: float | None = Field(None, gt=0, lt=1, description="Fraction below the peak")
    take_profit: float | None = Field(None, gt=0, description="Fraction above entry")
    max_holding_bars: int | None = Field(None, ge=1)


class StrategySpec(_Model):
    name: str = "macd"
    params: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- backtest


class ExecutionConfig(_Model):
    fill: Literal["next_open", "close"] = "next_open"
    slippage_ticks: float = Field(1.0, ge=0)
    slippage_bps: float = Field(0.0, ge=0)
    max_volume_pct: float | None = Field(None, gt=0, le=1)
    entry_requires_fresh_signal: bool = True
    liquidate_at_end: bool = False


class BacktestConfig(_Model):
    symbols: list[str] = Field(default_factory=lambda: ["HK.00700"])
    strategy: StrategySpec = Field(default_factory=StrategySpec)
    timeframe: str = "DAY"
    start: date = date(2023, 1, 1)
    end: date | None = None
    capital: float = Field(1_000_000, gt=0)
    mode: Literal["portfolio", "scan"] = "portfolio"
    benchmark: str | None = "HK.800000"
    sizing: SizingConfig = Field(default_factory=SizingConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    exits: ExitRules = Field(default_factory=ExitRules)
    check_lookahead: bool = True
    risk_free_rate: float = 0.0
    output_dir: Path = Path("reports")

    @field_validator("timeframe")
    @classmethod
    def _norm_tf(cls, v: str) -> str:
        return _tf(v)

    @field_validator("symbols")
    @classmethod
    def _norm(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("backtest.symbols must not be empty")
        return list(dict.fromkeys(normalize_symbol(s) for s in v))

    @field_validator("benchmark")
    @classmethod
    def _norm_bench(cls, v: str | None) -> str | None:
        return normalize_symbol(v) if v else None


# --------------------------------------------------------------------------- live trading


class SymbolSpec(_Model):
    symbol: str
    strategy: StrategySpec | None = None
    enabled: bool = True

    @field_validator("symbol")
    @classmethod
    def _norm(cls, v: str) -> str:
        return normalize_symbol(v)


class OrderConfig(_Model):
    price: Literal["aggressive", "mid", "passive", "market"] = Field(
        "aggressive",
        description="aggressive: cross the spread (buy at ask, sell at bid); passive: join "
        "the near side; mid: midpoint rounded to tick; market: market order",
    )
    extra_ticks: int = Field(0, ge=0, le=20, description="Extra ticks of aggression")
    timeout_seconds: float = Field(30.0, gt=0)
    max_replaces: int = Field(2, ge=0, le=20)


class RiskConfig(_Model):
    max_order_value: float | None = Field(None, gt=0)
    max_position_value: float | None = Field(None, gt=0)
    max_total_exposure: float = Field(1.0, gt=0, le=1, description="Market value / equity")
    max_orders_per_day: int = Field(100, ge=1)
    max_daily_loss: float | None = Field(None, gt=0, description="Currency; halts new entries")
    max_daily_loss_pct: float | None = Field(None, gt=0, lt=1)
    price_band_pct: float = Field(0.05, gt=0, le=0.5, description="Max limit vs last price")
    no_entries_minutes_before_close: int = Field(0, ge=0, le=390)
    flatten_minutes_before_close: int | None = Field(None, ge=1, le=390)


class TradingConfig(_Model):
    env: Literal["SIMULATE", "REAL"] = "SIMULATE"
    mode: Literal["paper", "dry_run"] = Field(
        "paper",
        description="paper: orders go to the Futu account for `env`; dry_run: a local "
        "simulator fills orders against live quotes and nothing reaches Futu",
    )
    allow_real: bool = Field(False, description="Must be true (plus FUTU_ALGO_ALLOW_REAL=1) for REAL")
    market: Literal["HK"] = "HK"
    timeframe: str = "1M"
    strategy: StrategySpec = Field(default_factory=StrategySpec)
    universe: list[SymbolSpec] = Field(default_factory=list)
    capital: float | None = Field(
        None, gt=0, description="Cap on the equity the engine sizes against (None: account)"
    )
    sizing: SizingConfig = Field(default_factory=lambda: SizingConfig(method="fixed_lots"))
    exits: ExitRules = Field(default_factory=ExitRules)
    order: OrderConfig = Field(default_factory=OrderConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    entry_requires_fresh_signal: bool = True
    warmup_from_cache: bool = True
    poll_seconds: float = Field(3.0, gt=0, le=60)
    bar_grace_seconds: float = Field(2.0, ge=0, le=60)
    state_db: Path = Path("state/futu_algo.sqlite")

    @field_validator("timeframe")
    @classmethod
    def _norm_tf(cls, v: str) -> str:
        return _tf(v)

    @field_validator("universe", mode="before")
    @classmethod
    def _coerce(cls, v: Any) -> Any:
        if isinstance(v, list):
            return [{"symbol": x} if isinstance(x, str) else x for x in v]
        return v

    @model_validator(mode="after")
    def _unique(self) -> TradingConfig:
        seen = [s.symbol for s in self.universe]
        dupes = {s for s in seen if seen.count(s) > 1}
        if dupes:
            raise ValueError(f"trading.universe lists {sorted(dupes)} more than once")
        return self

    def strategy_for(self, symbol: str) -> StrategySpec:
        for spec in self.universe:
            if spec.symbol == symbol and spec.strategy is not None:
                return spec.strategy
        return self.strategy

    @property
    def symbols(self) -> list[str]:
        return [s.symbol for s in self.universe if s.enabled]


# --------------------------------------------------------------------------- screener

FilterKind = Literal["simple", "accumulate", "financial", "pattern", "indicator"]


class ScreenFilter(_Model):
    kind: FilterKind
    field: str = Field(description="Futu StockField name, e.g. CUR_PRICE, TURNOVER, MA_ALIGNMENT_LONG")
    min: float | None = None
    max: float | None = None
    sort: Literal["asc", "desc"] | None = None
    days: int | None = Field(None, ge=1, description="accumulate: number of days")
    quarter: str | None = Field(None, description="financial: ANNUAL, FIRST_QUARTER, ...")
    ktype: str | None = Field(None, description="pattern/indicator: K_60M, K_DAY, K_WEEK, K_MON")
    field2: str | None = Field(None, description="indicator: second StockField")
    relative_position: Literal["MORE", "LESS", "CROSS_UP", "CROSS_DOWN"] | None = None
    value: float | None = Field(None, description="indicator: compare field1 with this value")
    field1_params: list[int] = Field(default_factory=list)
    field2_params: list[int] = Field(default_factory=list)
    consecutive_period: int | None = Field(None, ge=1)


class ScreenPreset(_Model):
    description: str = ""
    market: Literal["HK"] = "HK"
    plate: str | None = Field(None, description="Restrict to a Futu plate, e.g. HK.LIST1910")
    filters: list[ScreenFilter] = Field(default_factory=list)
    confirm_strategy: StrategySpec | None = Field(
        None, description="Optional: keep only candidates whose strategy says 'long' on daily bars"
    )
    confirm_timeframe: str = "DAY"
    confirm_lookback_days: int = Field(250, ge=30)
    max_confirm: int = Field(30, ge=1, description="Caps history K-line quota used per run")
    max_results: int = Field(100, ge=1, le=2000)

    @field_validator("confirm_timeframe")
    @classmethod
    def _norm_tf(cls, v: str) -> str:
        return _tf(v)


class ScheduledScreen(_Model):
    preset: str
    at: time = time(8, 45)
    notify: bool = True


class ScreenerConfig(_Model):
    presets: dict[str, ScreenPreset] = Field(default_factory=dict)
    schedule: list[ScheduledScreen] = Field(default_factory=list)
    results_dir: Path = Path("reports/screener")

    @model_validator(mode="after")
    def _known(self) -> ScreenerConfig:
        for job in self.schedule:
            if job.preset not in self.presets:
                raise ValueError(f"screener.schedule refers to unknown preset {job.preset!r}")
        return self


# --------------------------------------------------------------------------- ops

NotifyEvent = Literal["fills", "orders", "rejections", "errors", "risk", "daily_summary", "screener", "engine"]


class EmailConfig(_Model):
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    security: Literal["starttls", "ssl", "none"] = "starttls"
    username: str = ""
    password_env: str = "FUTU_ALGO_SMTP_PASSWORD"
    sender: str = ""
    recipients: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> EmailConfig:
        if self.enabled and not (self.smtp_host and self.sender and self.recipients):
            raise ValueError("notify.email needs smtp_host, sender and recipients when enabled")
        return self


class TelegramConfig(_Model):
    enabled: bool = False
    token_env: str = "FUTU_ALGO_TELEGRAM_TOKEN"
    chat_id: str = ""

    @model_validator(mode="after")
    def _check(self) -> TelegramConfig:
        if self.enabled and not self.chat_id:
            raise ValueError("notify.telegram.chat_id is required when enabled")
        return self


class NotifyConfig(_Model):
    email: EmailConfig = Field(default_factory=EmailConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    events: list[NotifyEvent] = Field(
        default_factory=lambda: ["fills", "rejections", "errors", "risk", "daily_summary", "screener"]
    )


class WebConfig(_Model):
    host: str = "127.0.0.1"
    port: int = Field(8765, ge=1, le=65535)
    token_env: str = "FUTU_ALGO_WEB_TOKEN"
    autostart_engine: bool = False


class ScheduleConfig(_Model):
    daily_summary: time | None = time(16, 20)
    refresh_instruments: time | None = time(8, 50)


class LoggingConfig(_Model):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    dir: Path | None = Path("logs")


class AppConfig(_Model):
    futu: FutuConfig = Field(default_factory=FutuConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    costs: CostsConfig = Field(default_factory=CostsConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    screener: ScreenerConfig = Field(default_factory=ScreenerConfig)
    notify: NotifyConfig = Field(default_factory=NotifyConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    strategy_paths: list[Path] = Field(default_factory=list)

    # Set by load_config; not part of the YAML.
    base_dir: Path = Field(default_factory=Path.cwd, exclude=True)
    source_path: Path | None = Field(None, exclude=True)

    def path(self, p: Path | str) -> Path:
        """Resolve a configured path against the config file's directory."""
        q = Path(p).expanduser()
        return q if q.is_absolute() else (self.base_dir / q).resolve()

    def public_dict(self) -> dict[str, Any]:
        """Config as plain data for display. Secrets are env var names, so nothing to mask."""
        return self.model_dump(mode="json", exclude={"base_dir", "source_path"})


# --------------------------------------------------------------------------- loading


def secret(env_name: str) -> str | None:
    value = os.environ.get(env_name)
    return value if value else None


_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$")


def load_dotenv(path: Path) -> int:
    """Minimal ``.env`` loader: KEY=VALUE lines, optional quotes; existing env wins."""
    if not path.is_file():
        return 0
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _ENV_LINE.match(line)
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key not in os.environ:
            os.environ[key] = value
            count += 1
    return count


def _format_errors(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err["loc"])
        lines.append(f"  {loc}: {err['msg']}")
    return "Invalid configuration:\n" + "\n".join(lines)


def parse_config(data: dict[str, Any], base_dir: Path | None = None) -> AppConfig:
    try:
        cfg = AppConfig.model_validate(data or {})
    except ValidationError as exc:
        raise ConfigError(_format_errors(exc)) from exc
    cfg.base_dir = (base_dir or Path.cwd()).resolve()
    return cfg


def load_config(path: str | Path | None = None, *, dotenv: bool = True) -> AppConfig:
    """Load a YAML config. ``None`` gives defaults (useful for tests and offline tools)."""
    if path is None:
        return parse_config({})
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise ConfigError(f"Config file {p} not found. Create one with `futu-algo init {p.name}`.")
    if dotenv:
        load_dotenv(p.parent / ".env")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{p}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{p}: top level must be a mapping")
    cfg = parse_config(data, p.parent)
    cfg.source_path = p
    return cfg


def validate_yaml_text(text: str, base_dir: Path) -> AppConfig:
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("Top level must be a mapping")
    return parse_config(data, base_dir)


def _coerce_scalar(text: str) -> Any:
    return yaml.safe_load(text)


def apply_overrides(cfg: AppConfig, overrides: list[str]) -> AppConfig:
    """Apply ``dotted.key=value`` overrides (values parsed as YAML) and re-validate."""
    if not overrides:
        return cfg
    data = cfg.model_dump(mode="json", exclude={"base_dir", "source_path"})
    for item in overrides:
        if "=" not in item:
            raise ConfigError(f"Override {item!r} must look like key.path=value")
        key, raw = item.split("=", 1)
        node: Any = data
        parts = key.strip().split(".")
        for part in parts[:-1]:
            if not isinstance(node, dict) or part not in node:
                raise ConfigError(f"Unknown config key {key!r}")
            node = node[part]
        if not isinstance(node, dict):
            raise ConfigError(f"Unknown config key {key!r}")
        node[parts[-1]] = _coerce_scalar(raw)
    out = parse_config(data, cfg.base_dir)
    out.source_path = cfg.source_path
    return out
