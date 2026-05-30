"""Centralised logging via loguru with file rotation + Rich console output."""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

_CONFIGURED = False


def setup_logging(log_dir: str | Path = "logs", level: str = "INFO") -> None:
    """Configure global logger sinks.  Safe to call multiple times."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        colorize=True,
        format=(
            "<green>{time:HH:mm:ss}</green> "
            "<level>{level: <8}</level> "
            "<cyan>{name}:{line}</cyan> "
            "<level>{message}</level>"
        ),
        backtrace=False,
        diagnose=False,
    )
    logger.add(
        log_path / "bot_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="30 days",
        level="DEBUG",
        encoding="utf-8",
        enqueue=True,
    )
    logger.add(
        log_path / "trades.log",
        filter=lambda r: r["extra"].get("trade", False),
        rotation="10 MB",
        retention="180 days",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {message}",
    )
    logger.add(
        log_path / "errors.log",
        level="ERROR",
        rotation="10 MB",
        retention="90 days",
    )
    _CONFIGURED = True


def get_logger(name: str | None = None):
    """Return a bound logger for the given module name."""
    if not _CONFIGURED:
        setup_logging()
    return logger.bind(module=name) if name else logger
