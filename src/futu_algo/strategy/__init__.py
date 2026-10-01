"""Strategy API shared by the backtester and the live engine."""

from futu_algo.strategy.base import (
    BarContext,
    PlotSpec,
    Strategy,
    StrategyParams,
    as_bool,
    events,
    state,
)
from futu_algo.strategy.lookahead import LookaheadReport, check_lookahead
from futu_algo.strategy.registry import (
    available,
    create_strategy,
    get_strategy_class,
    load_strategy_paths,
    register,
)

__all__ = [
    "BarContext",
    "LookaheadReport",
    "PlotSpec",
    "Strategy",
    "StrategyParams",
    "as_bool",
    "available",
    "check_lookahead",
    "create_strategy",
    "events",
    "get_strategy_class",
    "load_strategy_paths",
    "register",
    "state",
]
