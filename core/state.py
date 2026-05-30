"""Lightweight global bot state shared between engine and dashboard."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class BotState:
    started_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    running: bool = False
    paused: bool = False
    cycles: int = 0
    last_decision: dict[str, Any] = field(default_factory=dict)
    last_error: str | None = None
    closed_partial: dict[str, bool] = field(default_factory=dict)   # ticket -> already partialled?

    def heartbeat(self) -> None:
        self.cycles += 1
