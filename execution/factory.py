"""Broker factory based on settings.mode.

Modes:
    paper          → PaperBroker (synthetic, offline – no API keys needed)
    demo / live    → BybitBroker (V5 USDT perps; demo=True unless BYBIT_DEMO=false)
"""
from __future__ import annotations

from config import settings
from utils.logger import get_logger

from .base import BaseBroker
from .bybit_broker import BybitBroker, PYBIT_AVAILABLE
from .paper_broker import PaperBroker

log = get_logger(__name__)


def build_broker(mode: str | None = None) -> BaseBroker:
    mode = (mode or settings.mode).lower()
    if mode in ("demo", "live"):
        if not PYBIT_AVAILABLE:
            log.error(
                "\n"
                "==========================================================\n"
                "  pybit not importable but MODE=%s.\n"
                "  Falling back to PAPER broker. Trades are SIMULATED.\n"
                "  Fix:  pip install pybit\n"
                "==========================================================" % mode
            )
            return PaperBroker()
        return BybitBroker()
    return PaperBroker()
