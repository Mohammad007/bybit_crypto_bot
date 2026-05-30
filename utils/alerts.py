"""Alert dispatch (Telegram + Discord).  All channels best-effort, async-friendly."""
from __future__ import annotations

import asyncio
from typing import Any

try:
    import httpx  # type: ignore
except Exception:
    httpx = None

from config import settings
from utils.logger import get_logger

log = get_logger(__name__)


class AlertManager:
    def __init__(self) -> None:
        self.telegram_token = settings.telegram_bot_token
        self.telegram_chat = settings.telegram_chat_id
        self.discord_webhook = settings.discord_webhook_url

    async def _telegram(self, text: str) -> None:
        if not (self.telegram_token and self.telegram_chat) or httpx is None:
            return
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=8.0) as c:
                await c.post(
                    url,
                    json={
                        "chat_id": self.telegram_chat,
                        "text": text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                )
        except Exception as exc:
            log.debug(f"telegram send failed: {exc}")

    async def _discord(self, text: str) -> None:
        if not self.discord_webhook or httpx is None:
            return
        try:
            async with httpx.AsyncClient(timeout=8.0) as c:
                await c.post(self.discord_webhook, json={"content": text})
        except Exception as exc:
            log.debug(f"discord send failed: {exc}")

    async def send_async(self, text: str) -> None:
        await asyncio.gather(self._telegram(text), self._discord(text))

    def send(self, text: str) -> None:
        try:
            asyncio.run(self.send_async(text))
        except RuntimeError:
            # already inside a running loop – fire & forget
            asyncio.create_task(self.send_async(text))

    # convenience helpers
    def trade_opened(self, symbol: str, side: str, lot: float, entry: float,
                     sl: float, tp: float, conf: float) -> None:
        self.send(
            f"🚀 <b>{side}</b> {symbol}  qty={lot:g}\n"
            f"Entry: <code>{entry:.6g}</code>\n"
            f"SL: <code>{sl:.6g}</code>  TP: <code>{tp:.6g}</code>\n"
            f"Confidence: {conf:.0f}%"
        )

    def trade_closed(self, symbol: str, side: str, pnl: float, pnl_pct: float) -> None:
        emoji = "✅" if pnl >= 0 else "🛑"
        self.send(
            f"{emoji} Closed {side} {symbol}  PnL: {pnl:+.2f} ({pnl_pct:+.2f}%)"
        )

    def warning(self, text: str) -> None:
        self.send(f"⚠️ {text}")
