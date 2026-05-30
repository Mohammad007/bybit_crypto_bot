"""Trading strategies (each builds entry/SL/TP and optionally its own decision)."""
from .base import BaseStrategy, StrategyPlan
from .trendline_breakout import TrendlineBreakoutStrategy
from .registry import get_strategy, available_strategies

__all__ = [
    "BaseStrategy",
    "StrategyPlan",
    "TrendlineBreakoutStrategy",
    "get_strategy",
    "available_strategies",
]
