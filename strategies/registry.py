"""Strategy registry."""
from __future__ import annotations

from .base import BaseStrategy
from .trendline_breakout import TrendlineBreakoutStrategy

_REGISTRY: dict[str, type[BaseStrategy]] = {
    TrendlineBreakoutStrategy.name: TrendlineBreakoutStrategy,
}


def get_strategy(name: str) -> BaseStrategy:
    """Resolve a strategy by name.  Falls back to the only active strategy."""
    cls = _REGISTRY.get(name) or _REGISTRY[TrendlineBreakoutStrategy.name]
    return cls()


def available_strategies() -> list[str]:
    return list(_REGISTRY.keys())
