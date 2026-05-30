"""
Paper-trading broker that:

*  Generates synthetic OHLCV when no upstream data is provided
*  Tracks an internal positions ledger
*  Simulates spread and slippage
*  Can be fed real ticks (e.g. mirrored from a live feed) via feed_tick()
"""
from __future__ import annotations

import math
import random
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from config import settings
from utils.logger import get_logger

from .base import BaseBroker, Order, PendingOrder, Position

log = get_logger(__name__)


_TF_MINUTES = {
    "M1": 1, "M2": 2, "M3": 3, "M4": 4, "M5": 5, "M6": 6,
    "M10": 10, "M12": 12, "M15": 15, "M20": 20, "M30": 30,
    "H1": 60, "H2": 120, "H3": 180, "H4": 240, "H6": 360, "H8": 480, "H12": 720,
    "D1": 1440, "W1": 10080, "MN1": 43200,
}


class PaperBroker(BaseBroker):
    """Self-contained paper broker."""

    name = "paper"

    def __init__(self, starting_price: float = 2350.0) -> None:
        self._connected = False
        self._positions: dict[str, Position] = {}
        self._pending: dict[str, "PendingOrder"] = {}
        self._last_price = starting_price
        self._spread_points = 25.0
        self._point = float(settings.market.get("point_value", 0.01))
        self._balance = float(settings.capital)
        self._equity = float(settings.capital)
        self._tick_history: list[tuple[datetime, float]] = []
        random.seed()

    # ---------------- connection ----------------
    def connect(self) -> bool:
        self._connected = True
        log.info(f"paper broker connected (balance={self._balance:.2f} {settings.base_currency})")
        return True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    # ---------------- account ----------------
    def account_info(self) -> dict[str, Any]:
        margin = sum(p.lot * p.entry_price * 100.0 / 100.0 for p in self._positions.values())
        free = max(0.0, self._equity - margin)
        return {
            "broker": "paper",
            "balance": self._balance,
            "equity": self._equity,
            "margin": margin,
            "free_margin": free,
            "currency": settings.base_currency,
            "leverage": 100,
        }

    # ---------------- pricing ----------------
    # Realistic gold range with soft mean reversion so multi-hour paper runs
    # don't drift into nonsense values like $62 or $20,000.
    _ANCHOR = 2350.0       # centre price for gold
    _PRICE_MIN = 1500.0    # hard floor
    _PRICE_MAX = 4000.0    # hard ceiling
    _MR_STRENGTH = 0.001   # how strongly we pull back toward the anchor

    def _next_synth_price(self) -> float:
        # Geometric Brownian walk + Ornstein-Uhlenbeck mean reversion.
        drift = 0.00002
        vol = 0.0009
        # mean-reversion pull keeps the random walk anchored
        mr = -self._MR_STRENGTH * math.log(self._last_price / self._ANCHOR)
        ret = drift + mr + vol * random.gauss(0, 1)
        new_p = self._last_price * math.exp(ret)
        # add an intraday wave around current price (not absolute)
        wave = math.sin(time.time() / 600) * (self._last_price * 0.0003)
        new_p += wave
        # hard clamp so even bad RNG streaks can't break realism
        self._last_price = max(self._PRICE_MIN, min(self._PRICE_MAX, new_p))
        return self._last_price

    def feed_tick(self, price: float) -> None:
        self._last_price = price
        self._tick_history.append((datetime.now(tz=timezone.utc), price))
        self._mark_to_market()

    def get_price(self, symbol: str) -> dict[str, float]:
        mid = self._next_synth_price() if not self._tick_history else self._last_price
        half = self._spread_points * self._point / 2.0
        bid = mid - half
        ask = mid + half
        self._tick_history.append((datetime.now(tz=timezone.utc), mid))
        self._check_pending_fills()
        self._mark_to_market()
        return {"bid": bid, "ask": ask, "spread_points": self._spread_points, "mid": mid}

    # ---------------- history ----------------
    def get_history(
        self, symbol: str, timeframe: str, bars: int = 500
    ) -> pd.DataFrame:
        """Generate plausible synthetic OHLCV history if we don't have one."""
        tf_min = _TF_MINUTES.get(timeframe, 15)
        end = datetime.now(tz=timezone.utc).replace(second=0, microsecond=0)
        rng = pd.date_range(end=end, periods=bars, freq=f"{tf_min}min", tz=timezone.utc)
        price = self._last_price
        rows = []
        rs = np.random.default_rng(seed=hash((symbol, timeframe)) & 0xFFFFFFFF)
        for i, ts in enumerate(rng):
            move = rs.normal(0, 0.0008) * price
            open_ = price
            close = price + move
            high = max(open_, close) + abs(rs.normal(0, 0.0006)) * price
            low = min(open_, close) - abs(rs.normal(0, 0.0006)) * price
            vol = float(rs.integers(500, 5000))
            rows.append((ts, open_, high, low, close, vol))
            price = close
        df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
        df = df.set_index("time")
        self._last_price = float(df["close"].iat[-1])
        return df

    # ---------------- orders ----------------
    def place_order(self, order: Order) -> Position | None:
        if not self._connected:
            return None

        # ----- Pending STOP order? -------------------------------------
        if order.order_type in ("buy_stop", "sell_stop"):
            ticket = str(uuid.uuid4())[:12]
            pending = PendingOrder(
                ticket=ticket,
                side=order.side,
                symbol=order.symbol,
                lot=order.lot,
                sl=order.sl,
                tp=order.tp,
                trigger_price=order.trigger_price,
                order_type=order.order_type,
                placed_at=datetime.now(tz=timezone.utc),
                expiry_minutes=order.expiry_minutes,
                comment=order.comment,
            )
            self._pending[ticket] = pending
            log.info(
                f"paper PENDING {order.order_type.upper()} {order.symbol} lot={order.lot} "
                f"trigger={order.trigger_price:.2f} sl={order.sl:.2f} tp={order.tp:.2f} "
                f"expiry={order.expiry_minutes:.0f}min"
            )
            # Return None – position will materialise when the trigger fills.
            return None

        # ----- Market order (existing behavior) ------------------------
        price = self.get_price(order.symbol)
        entry = price["ask"] if order.side == "BUY" else price["bid"]
        ticket = str(uuid.uuid4())[:12]
        pos = Position(
            ticket=ticket,
            side=order.side,
            symbol=order.symbol,
            lot=order.lot,
            entry_price=entry,
            sl=order.sl,
            tp=order.tp,
            open_time=datetime.now(tz=timezone.utc),
            current_price=entry,
        )
        self._positions[ticket] = pos
        log.info(
            f"paper order opened: {order.side} {order.symbol} lot={order.lot} "
            f"@ {entry:.2f} sl={order.sl:.2f} tp={order.tp:.2f}"
        )
        return pos

    def pending_orders(self) -> list[PendingOrder]:
        return list(self._pending.values())

    # ---------------- symbol management ----------------------------
    def is_market_open(self, symbol: str) -> bool:
        # Paper broker is always "open" – synthetic data never sleeps
        return True

    def set_symbol(self, symbol: str) -> bool:
        log.info(f"paper broker switched symbol -> {symbol}")
        return True

    def cancel_pending(self, ticket: str) -> bool:
        if ticket in self._pending:
            del self._pending[ticket]
            log.info(f"paper pending {ticket} cancelled")
            return True
        return False

    def _check_pending_fills(self) -> None:
        """Called on each price update – fill triggered pending orders."""
        if not self._pending:
            return
        price = {"bid": self._last_price - self._spread_points * self._point / 2.0,
                 "ask": self._last_price + self._spread_points * self._point / 2.0,
                 "mid": self._last_price}
        now = datetime.now(tz=timezone.utc)
        for ticket in list(self._pending.keys()):
            p = self._pending[ticket]
            # expire check
            if p.expiry_minutes > 0:
                age_min = (now - p.placed_at).total_seconds() / 60.0
                if age_min >= p.expiry_minutes:
                    del self._pending[ticket]
                    log.info(f"paper pending {ticket} expired after {age_min:.1f}min")
                    continue
            # trigger check
            should_fill = (
                (p.order_type == "buy_stop" and price["ask"] >= p.trigger_price)
                or (p.order_type == "sell_stop" and price["bid"] <= p.trigger_price)
            )
            if should_fill:
                entry = p.trigger_price                 # fill exactly at trigger
                new_ticket = str(uuid.uuid4())[:12]
                self._positions[new_ticket] = Position(
                    ticket=new_ticket,
                    side=p.side,
                    symbol=p.symbol,
                    lot=p.lot,
                    entry_price=entry,
                    sl=p.sl,
                    tp=p.tp,
                    open_time=now,
                    current_price=entry,
                )
                del self._pending[ticket]
                log.info(
                    f"paper pending {ticket} → FILLED as {p.side} @ {entry:.2f} "
                    f"(new ticket={new_ticket})"
                )

    def close_position(self, ticket: str, price: float | None = None) -> bool:
        pos = self._positions.pop(ticket, None)
        if not pos:
            return False
        if price is None:
            price = self.get_price(pos.symbol)["mid"]
        pnl = self._compute_pnl(pos, price)
        self._balance += pnl
        log.info(f"paper close {ticket} @ {price:.2f}  pnl={pnl:+.2f}")
        return True

    def modify_position(
        self, ticket: str, sl: float | None = None, tp: float | None = None
    ) -> bool:
        pos = self._positions.get(ticket)
        if not pos:
            return False
        if sl is not None:
            pos.sl = sl
        if tp is not None:
            pos.tp = tp
        return True

    def open_positions(self) -> list[Position]:
        return list(self._positions.values())

    # ---------------- mark to market ----------------
    def _compute_pnl(self, pos: Position, current: float) -> float:
        # Linear USDT perp: 1 contract = 1 coin, PnL = qty * price_change.
        contract = float(settings.market.get("contract_size", 1))
        sign = 1 if pos.side == "BUY" else -1
        return (current - pos.entry_price) * sign * pos.lot * contract

    def _mark_to_market(self) -> None:
        equity = self._balance
        for pos in self._positions.values():
            pos.current_price = self._last_price
            pos.pnl = self._compute_pnl(pos, self._last_price)
            equity += pos.pnl
        self._equity = equity
