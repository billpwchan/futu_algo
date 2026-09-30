"""Exception types raised by futu_algo."""


class FutuAlgoError(Exception):
    """Base class for every error raised by the package."""


class ConfigError(FutuAlgoError):
    """Invalid or inconsistent configuration."""


class DataError(FutuAlgoError):
    """Market data is missing, malformed or could not be fetched."""


class DataSourceError(DataError):
    """Futu OpenD returned an error for a quote request."""


class QuotaExceededError(DataSourceError):
    """Fetching a new symbol would exceed the Futu historical K-line quota."""


class StrategyError(FutuAlgoError):
    """A strategy is unknown, misconfigured or produced invalid output."""


class BrokerError(FutuAlgoError):
    """The broker (Futu trade context or the local simulator) rejected a request."""


class RiskRejected(FutuAlgoError):
    """A pre-trade risk check blocked an order."""
