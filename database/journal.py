"""High-level trade journal API used by the rest of the bot."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func

from utils.logger import get_logger

from .models import DailyStat, Signal, Trade, get_session, init_db

log = get_logger(__name__)


@dataclass
class TradeRecord:
    ticket: str
    symbol: str
    side: str
    lot: float
    entry_price: float
    sl: float
    tp: float
    confidence: float = 0.0
    strategy: str = ""
    mode: str = "paper"
    reason: str = ""
    open_time: datetime = field(default_factory=datetime.utcnow)
    exit_price: float | None = None
    close_time: datetime | None = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    status: str = "open"


class TradeJournal:
    """Persistence layer for trades, signals, and daily statistics."""

    def __init__(self) -> None:
        init_db()

    # ---------------- trades ----------------
    def open_trade(self, rec: TradeRecord) -> int:
        with get_session() as s:
            row = Trade(
                ticket=rec.ticket,
                symbol=rec.symbol,
                side=rec.side,
                lot=rec.lot,
                entry_price=rec.entry_price,
                sl=rec.sl,
                tp=rec.tp,
                confidence=rec.confidence,
                strategy=rec.strategy,
                mode=rec.mode,
                reason=rec.reason,
                open_time=rec.open_time,
                status="open",
            )
            s.add(row)
            s.commit()
            log.bind(trade=True).info(
                f"OPEN  | {rec.side:<4} | {rec.symbol} | lot={rec.lot:.2f} "
                f"| entry={rec.entry_price:.2f} | sl={rec.sl:.2f} | tp={rec.tp:.2f} "
                f"| conf={rec.confidence:.0f}% | strat={rec.strategy} | {rec.mode}"
            )
            return row.id

    def close_trade(
        self,
        ticket: str,
        exit_price: float,
        pnl: float,
        pnl_pct: float,
        close_time: datetime | None = None,
    ) -> None:
        with get_session() as s:
            row = s.query(Trade).filter(Trade.ticket == ticket, Trade.status == "open").first()
            if row is None:
                log.warning(f"close_trade: ticket {ticket} not found / already closed")
                return
            row.exit_price = exit_price
            row.pnl = pnl
            row.pnl_pct = pnl_pct
            row.close_time = close_time or datetime.utcnow()
            row.status = "closed"
            s.commit()
            log.bind(trade=True).info(
                f"CLOSE | {row.side:<4} | {row.symbol} | exit={exit_price:.2f} "
                f"| pnl={pnl:+.2f} ({pnl_pct:+.2f}%) | ticket={ticket}"
            )

    def open_trades(self) -> list[Trade]:
        with get_session() as s:
            return list(s.query(Trade).filter(Trade.status == "open").all())

    def recent_trades(self, limit: int = 20) -> list[Trade]:
        with get_session() as s:
            return list(
                s.query(Trade)
                .order_by(Trade.open_time.desc())
                .limit(limit)
                .all()
            )

    # ---------------- signals ----------------
    def record_signal(
        self,
        symbol: str,
        direction: str,
        confidence: float,
        agents: dict[str, Any],
        notes: str = "",
        executed: bool = False,
    ) -> None:
        with get_session() as s:
            s.add(
                Signal(
                    symbol=symbol,
                    direction=direction,
                    confidence=confidence,
                    agents_json=json.dumps(agents, default=str),
                    notes=notes,
                    executed=1 if executed else 0,
                )
            )
            s.commit()

    # ---------------- stats ----------------
    def daily_pnl(self, day: datetime | None = None) -> float:
        day = (day or datetime.utcnow()).date()
        start = datetime.combine(day, datetime.min.time())
        end = start + timedelta(days=1)
        with get_session() as s:
            val = (
                s.query(func.coalesce(func.sum(Trade.pnl), 0.0))
                .filter(Trade.close_time >= start, Trade.close_time < end)
                .scalar()
            )
            return float(val or 0.0)

    def weekly_pnl(self) -> float:
        end = datetime.utcnow()
        start = end - timedelta(days=7)
        with get_session() as s:
            val = (
                s.query(func.coalesce(func.sum(Trade.pnl), 0.0))
                .filter(Trade.close_time >= start)
                .scalar()
            )
            return float(val or 0.0)

    def trades_today(self) -> int:
        today = datetime.utcnow().date()
        start = datetime.combine(today, datetime.min.time())
        with get_session() as s:
            return int(
                s.query(func.count(Trade.id))
                .filter(Trade.open_time >= start)
                .scalar()
                or 0
            )

    def win_rate(self) -> float:
        with get_session() as s:
            total = s.query(func.count(Trade.id)).filter(Trade.status == "closed").scalar() or 0
            if not total:
                return 0.0
            wins = (
                s.query(func.count(Trade.id))
                .filter(Trade.status == "closed", Trade.pnl > 0)
                .scalar()
                or 0
            )
            return float(wins) * 100.0 / float(total)
