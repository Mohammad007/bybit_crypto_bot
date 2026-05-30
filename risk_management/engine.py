"""Risk envelope engine – daily / weekly limits, kill switch, sizing."""
from __future__ import annotations

from datetime import datetime, timezone

from config import settings
from database import TradeJournal
from utils.logger import get_logger

from .position_sizing import compute_qty

log = get_logger(__name__)


class RiskEngine:
    def __init__(self, journal: TradeJournal, capital: float | None = None) -> None:
        self.journal = journal
        self.capital = capital if capital is not None else settings.capital
        self._equity_high = self.capital
        self.killed = False
        self.kill_reason: str | None = None

    # ------------------------------------------------------------------
    def update_equity(self, equity: float) -> None:
        if equity > self._equity_high:
            self._equity_high = equity

    def drawdown_pct(self, equity: float) -> float:
        if self._equity_high <= 0:
            return 0.0
        return max(0.0, (self._equity_high - equity) * 100.0 / self._equity_high)

    # ------------------------------------------------------------------
    def can_trade(self) -> tuple[bool, str]:
        """Return (allowed, reason)."""
        if self.killed:
            return False, f"KILL_SWITCH: {self.kill_reason}"

        risk_cfg = settings.risk
        max_concurrent = int(risk_cfg.get("max_concurrent_trades", 2))
        max_per_day = int(risk_cfg.get("max_trades_per_day", settings.max_trades_per_day))
        # max_daily = float(risk_cfg.get("max_daily_loss_pct", settings.max_daily_loss))
        # max_weekly = float(risk_cfg.get("max_weekly_loss_pct", settings.max_weekly_loss))

        if len(self.journal.open_trades()) >= max_concurrent:
            return False, f"max concurrent trades reached ({max_concurrent})"

        if self.journal.trades_today() >= max_per_day:
            return False, f"max trades per day reached ({max_per_day})"

        # ------------------------------------------------------------------
        # 🚨 SAFETY: daily / weekly loss limits DISABLED by user request.
        # Re-enable when balance grows or after live testing phase ends.
        # To re-enable: uncomment the block below AND the max_daily /
        # max_weekly assignments above.
        # ------------------------------------------------------------------
        # daily_pnl_pct = self.journal.daily_pnl() * 100.0 / max(self.capital, 1.0)
        # if daily_pnl_pct <= -max_daily:
        #     return False, f"daily loss limit hit ({daily_pnl_pct:.2f}% <= -{max_daily}%)"
        #
        # weekly_pnl_pct = self.journal.weekly_pnl() * 100.0 / max(self.capital, 1.0)
        # if weekly_pnl_pct <= -max_weekly:
        #     return False, f"weekly loss limit hit ({weekly_pnl_pct:.2f}% <= -{max_weekly}%)"

        return True, "ok"

    # ------------------------------------------------------------------
    def trigger_kill_switch(self, reason: str) -> None:
        self.killed = True
        self.kill_reason = reason
        log.error(f"KILL SWITCH TRIGGERED: {reason}")

    def reset_kill_switch(self) -> None:
        self.killed = False
        self.kill_reason = None
        log.warning("kill switch reset")

    # ------------------------------------------------------------------
    def size_position(self, entry: float, sl: float, risk_usdt: float | None = None) -> float:
        """
        Raw coin quantity for a linear USDT perp (broker rounds to qtyStep).

        If ``risk_usdt`` > 0, the trade is sized to lose exactly that many USDT
        at the stop (fixed-dollar risk).  Otherwise it falls back to risking
        ``risk_per_trade_pct`` of capital.
        """
        distance = abs(entry - sl)
        if distance <= 0:
            return 0.0
        if risk_usdt and risk_usdt > 0:
            return risk_usdt / distance
        risk_cfg = settings.risk
        return compute_qty(
            capital=self.capital,
            risk_pct=float(risk_cfg.get("risk_per_trade_pct", settings.risk_per_trade)),
            entry_price=entry,
            stop_price=sl,
        )
