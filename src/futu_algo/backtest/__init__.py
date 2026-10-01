"""Bar-level backtester: next-open fills, board lots, dated HK costs, exits and portfolio sizing."""

from futu_algo.backtest.runner import (
    COMPOSITE,
    PORTFOLIO,
    BacktestResult,
    build_cost_model,
    result_payload,
    run_backtest,
    run_on_bars,
    save_result,
)
from futu_algo.backtest.simulator import Simulator, SymbolFeed, fit_lots
from futu_algo.backtest.types import Book, Fill, Trade

__all__ = [
    "COMPOSITE",
    "PORTFOLIO",
    "BacktestResult",
    "Book",
    "Fill",
    "Simulator",
    "SymbolFeed",
    "Trade",
    "build_cost_model",
    "fit_lots",
    "result_payload",
    "run_backtest",
    "run_on_bars",
    "save_result",
]
