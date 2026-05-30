"""
Settings loader – merges .env values with YAML configuration into a single
typed Settings object that the rest of the codebase imports.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
LOG_DIR = ROOT_DIR / "logs"
DB_DIR = ROOT_DIR / "database"
MODELS_DIR = ROOT_DIR / "models"

for d in (LOG_DIR, DB_DIR, MODELS_DIR):
    d.mkdir(parents=True, exist_ok=True)

load_dotenv(ROOT_DIR / ".env", override=False)


class Settings(BaseModel):
    """Top-level settings object."""

    # mode
    mode: str = Field(default="demo")          # paper | demo | live
    symbol: str = Field(default="BTCUSDT")     # default active symbol
    base_currency: str = Field(default="USDT")
    capital: float = Field(default=1000.0)

    # Bybit V5 (USDT perpetuals)
    bybit_api_key: str | None = None
    bybit_api_secret: str | None = None
    bybit_demo: bool = True                     # demo trading (api-demo.bybit.com)
    bybit_testnet: bool = False                 # public testnet
    bybit_leverage: int = 5                     # leverage applied per symbol

    # risk
    risk_per_trade: float = 1.0
    max_daily_loss: float = 3.0
    max_weekly_loss: float = 7.0
    max_trades_per_day: int = 3
    min_confidence: float = 80.0

    # alerts
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    discord_webhook_url: str | None = None

    # infra
    redis_url: str = "redis://localhost:6379/0"
    enable_redis: bool = False
    database_url: str = "sqlite:///./database/db"
    log_level: str = "INFO"
    log_dir: str = "logs"

    # nested yaml config
    yaml_config: dict[str, Any] = Field(default_factory=dict)

    # ------------------------------------------------------------------
    # accessors for nested yaml sections
    # ------------------------------------------------------------------
    @property
    def bot(self) -> dict[str, Any]:
        return self.yaml_config.get("bot", {})

    @property
    def market(self) -> dict[str, Any]:
        return self.yaml_config.get("market", {})

    @property
    def timeframes(self) -> dict[str, Any]:
        return self.yaml_config.get("timeframes", {})

    @property
    def indicators(self) -> dict[str, Any]:
        return self.yaml_config.get("indicators", {})

    @property
    def smart_money(self) -> dict[str, Any]:
        return self.yaml_config.get("smart_money", {})

    @property
    def ai(self) -> dict[str, Any]:
        return self.yaml_config.get("ai", {})

    @property
    def risk(self) -> dict[str, Any]:
        return self.yaml_config.get("risk", {})

    @property
    def execution(self) -> dict[str, Any]:
        return self.yaml_config.get("execution", {})

    @property
    def strategies(self) -> dict[str, Any]:
        return self.yaml_config.get("strategies", {})

    @property
    def universe(self) -> dict[str, Any]:
        return self.yaml_config.get("universe", {})

    @property
    def scanner(self) -> dict[str, Any]:
        return self.yaml_config.get("scanner", {})

    @property
    def dashboard(self) -> dict[str, Any]:
        return self.yaml_config.get("dashboard", {})


def _load_yaml() -> dict[str, Any]:
    yaml_path = CONFIG_DIR / "config.yaml"
    if not yaml_path.exists():
        return {}
    with yaml_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _as_bool(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(val: str | None) -> int | None:
    try:
        return int(val) if val not in (None, "") else None
    except ValueError:
        return None


@lru_cache(maxsize=1)
def _build_settings() -> Settings:
    yaml_cfg = _load_yaml()
    risk_cfg = yaml_cfg.get("risk", {})
    return Settings(
        mode=os.getenv("MODE", "demo").lower(),
        symbol=os.getenv("SYMBOL", "BTCUSDT"),
        base_currency=os.getenv("BASE_CURRENCY", "USDT"),
        capital=float(os.getenv("CAPITAL", "1000")),
        bybit_api_key=os.getenv("BYBIT_API_KEY") or None,
        bybit_api_secret=os.getenv("BYBIT_API_SECRET") or None,
        bybit_demo=_as_bool(os.getenv("BYBIT_DEMO"), True),
        bybit_testnet=_as_bool(os.getenv("BYBIT_TESTNET"), False),
        bybit_leverage=int(os.getenv("BYBIT_LEVERAGE", "5")),
        risk_per_trade=float(
            os.getenv("RISK_PER_TRADE", risk_cfg.get("risk_per_trade_pct", 1.0))
        ),
        max_daily_loss=float(
            os.getenv("MAX_DAILY_LOSS", risk_cfg.get("max_daily_loss_pct", 3.0))
        ),
        max_weekly_loss=float(
            os.getenv("MAX_WEEKLY_LOSS", risk_cfg.get("max_weekly_loss_pct", 7.0))
        ),
        max_trades_per_day=int(
            os.getenv("MAX_TRADES_PER_DAY", risk_cfg.get("max_trades_per_day", 3))
        ),
        min_confidence=float(
            os.getenv("MIN_CONFIDENCE", yaml_cfg.get("ai", {}).get("min_confidence", 80))
        ),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
        discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL") or None,
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        enable_redis=_as_bool(os.getenv("ENABLE_REDIS"), False),
        database_url=os.getenv(
            "DATABASE_URL", "sqlite:///./database/db"
        ),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        log_dir=os.getenv("LOG_DIR", "logs"),
        yaml_config=yaml_cfg,
    )


settings: Settings = _build_settings()
