"""SQLAlchemy models for the trade journal and bot state."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from config import settings

Base = declarative_base()


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket = Column(String(32), index=True)
    symbol = Column(String(16), index=True)
    side = Column(String(8))                # BUY / SELL
    lot = Column(Float)
    entry_price = Column(Float)
    sl = Column(Float)
    tp = Column(Float)
    exit_price = Column(Float, nullable=True)
    pnl = Column(Float, default=0.0)
    pnl_pct = Column(Float, default=0.0)
    confidence = Column(Float, default=0.0)
    strategy = Column(String(64))
    mode = Column(String(16))               # paper / live
    reason = Column(Text, nullable=True)
    open_time = Column(DateTime, default=datetime.utcnow)
    close_time = Column(DateTime, nullable=True)
    status = Column(String(16), default="open")  # open / closed / cancelled


class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    symbol = Column(String(16))
    direction = Column(String(8))           # BUY / SELL / HOLD
    confidence = Column(Float)
    agents_json = Column(Text)
    notes = Column(Text, nullable=True)
    executed = Column(Integer, default=0)   # 0/1


class DailyStat(Base):
    __tablename__ = "daily_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    day = Column(DateTime, index=True, unique=True)
    trades = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    pnl = Column(Float, default=0.0)
    pnl_pct = Column(Float, default=0.0)
    drawdown_pct = Column(Float, default=0.0)


# --------------------------------------------------------------------------
# engine / session helpers
# --------------------------------------------------------------------------

def _db_url() -> str:
    """Resolve DB URL relative to project root if sqlite path is relative."""
    url = settings.database_url
    if url.startswith("sqlite:///./"):
        rel = url.replace("sqlite:///./", "")
        full = Path(__file__).resolve().parent.parent / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{full.as_posix()}"
    return url


_engine = create_engine(_db_url(), echo=False, future=True)
_SessionLocal = sessionmaker(bind=_engine, autoflush=False, future=True)


def init_db() -> None:
    """Create all tables.  Idempotent."""
    Base.metadata.create_all(_engine)


def get_session() -> Session:
    return _SessionLocal()
