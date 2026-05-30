"""Strategy abstraction – converts an AI decision into actionable plan."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class StrategyPlan:
    direction: str          # 'BUY' / 'SELL' / 'HOLD'
    entry: float
    sl: float
    tp: float
    reason: str
    confidence: float = 0.0
    rr: float = 0.0

    @property
    def actionable(self) -> bool:
        return self.direction in ("BUY", "SELL") and self.entry > 0 and self.sl != self.entry


class BaseStrategy(ABC):
    name: str = "base"
    # When True, the engine skips the AI ensemble vote and asks the
    # strategy itself to produce the decision via compute_decision().
    # All safety filters (news, spread, zigzag, risk envelope, trade
    # management) still apply.
    exclusive: bool = False

    def compute_decision(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """
        Only called when ``exclusive`` is True.  Subclasses override
        this to return their own BUY / SELL / HOLD verdict.
        """
        return {
            "decision": "HOLD",
            "confidence": 0.0,
            "consensus": 0.0,
            "signals": [],
            "votes": {},
        }

    @abstractmethod
    def build_plan(
        self, decision: dict[str, Any], ctx: dict[str, Any]
    ) -> StrategyPlan: ...
