"""Broker abstraction."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd


@dataclass
class Order:
    side: str                          # 'BUY' / 'SELL'
    symbol: str
    lot: float
    sl: float
    tp: float
    comment: str = ""
    magic: int = 0
    # 'market'   → fill at current bid/ask (default)
    # 'buy_stop' → pending BUY at trigger_price (fills when ask >= trigger)
    # 'sell_stop'→ pending SELL at trigger_price (fills when bid <= trigger)
    order_type: str = "market"
    trigger_price: float = 0.0
    # When > 0, broker auto-cancels the pending order after this many minutes
    # if it hasn't filled.
    expiry_minutes: float = 0.0


@dataclass
class PendingOrder:
    """A pending stop order tracked by the broker."""
    ticket: str
    side: str
    symbol: str
    lot: float
    sl: float
    tp: float
    trigger_price: float
    order_type: str                    # 'buy_stop' | 'sell_stop'
    placed_at: datetime
    expiry_minutes: float = 0.0
    comment: str = ""


@dataclass
class Position:
    ticket: str
    side: str
    symbol: str
    lot: float
    entry_price: float
    sl: float
    tp: float
    open_time: datetime
    current_price: float = 0.0
    pnl: float = 0.0


class BaseBroker(ABC):
    """Common interface used by the bot."""

    name: str = "base"

    @abstractmethod
    def connect(self) -> bool: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    def account_info(self) -> dict[str, Any]: ...

    @abstractmethod
    def get_price(self, symbol: str) -> dict[str, float]:
        """Return {bid, ask, spread_points}."""

    @abstractmethod
    def get_history(
        self, symbol: str, timeframe: str, bars: int = 500
    ) -> pd.DataFrame: ...

    @abstractmethod
    def place_order(self, order: Order) -> Position | None: ...

    @abstractmethod
    def close_position(self, ticket: str, price: float | None = None) -> bool: ...

    @abstractmethod
    def modify_position(
        self, ticket: str, sl: float | None = None, tp: float | None = None
    ) -> bool: ...

    @abstractmethod
    def open_positions(self) -> list[Position]: ...

    # ---------------- pending orders (optional) -------------------------
    def pending_orders(self) -> list[PendingOrder]:
        """Return list of live pending orders.  Default: empty."""
        return []

    def cancel_pending(self, ticket: str) -> bool:
        """Cancel a pending order by ticket. Default: no-op."""
        return False

    # ---------------- symbol management (optional) ----------------------
    def is_market_open(self, symbol: str) -> bool:
        """Return True if the symbol's market is currently open."""
        return True

    def set_symbol(self, symbol: str) -> bool:
        """Switch the active trading symbol.  Returns True on success."""
        return True
