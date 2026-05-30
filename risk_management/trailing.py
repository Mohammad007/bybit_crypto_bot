"""Trailing-stop, break-even, partial close helpers."""
from __future__ import annotations


def compute_trailing_stop(
    side: str,
    entry: float,
    current: float,
    sl: float,
    atr: float,
    trail_mult: float = 1.5,
) -> float:
    """Return new SL price; never widen the stop."""
    if side == "BUY":
        proposed = current - atr * trail_mult
        return max(sl, proposed)
    proposed = current + atr * trail_mult
    return min(sl, proposed)


def manage_open_trade(
    side: str,
    entry: float,
    current: float,
    sl: float,
    tp: float,
    atr: float,
    risk_cfg: dict,
    closed_partial: bool,
    point_size: float = 0.01,
    elapsed_minutes: float = 0.0,
    current_pnl: float = 0.0,
) -> dict:
    """
    Inspect a live trade and return an action dict.

    Returns:
        {
          'new_sl':           float | None,
          'partial_close_pct': float | None,
          'close':            bool,
          'close_reason':     str | None,
        }
    """
    out = {"new_sl": None, "partial_close_pct": None, "close": False, "close_reason": None}
    risk_per_R = abs(entry - sl)
    if risk_per_R <= 0:
        return out

    move = (current - entry) if side == "BUY" else (entry - current)
    R = move / risk_per_R

    be_at      = float(risk_cfg.get("break_even_at_R", 1.0))
    trail_at   = float(risk_cfg.get("trailing_at_R", 1.5))
    partial_at = float(risk_cfg.get("partial_take_R", 2.0))
    partial_pct = float(risk_cfg.get("partial_close_pct", 50))

    # ---------- Scalper: USD-based quick profit booking ------------------
    # Most accurate trigger – uses the broker-reported PnL (account currency).
    # 0 / unset = disabled.
    quick_close_usd = float(risk_cfg.get("quick_close_usd", 0) or 0)
    if quick_close_usd > 0 and current_pnl >= quick_close_usd:
        out["close"] = True
        out["close_reason"] = f"quick_profit_${current_pnl:.2f}"
        return out

    # ---------- Scalper: pip-based quick profit booking (fallback) -------
    # Triggers when N pips in profit. Useful if PnL not yet reflected
    # (e.g. mid-tick on paper broker).  1 pip = 10 broker points.
    quick_close_pips = float(risk_cfg.get("quick_close_pips", 0) or 0)
    if quick_close_pips > 0:
        profit_pips = move / (point_size * 10.0)
        if profit_pips >= quick_close_pips:
            out["close"] = True
            out["close_reason"] = f"quick_profit_{profit_pips:.0f}pips"
            return out

    # ---------- Scalper feature: time stop -------------------------------
    # If we've been in the trade `time_stop_minutes` and aren't materially
    # in profit (R < time_stop_min_R), exit – avoids dead trades.
    time_stop_min  = float(risk_cfg.get("time_stop_minutes", 0) or 0)
    time_stop_minR = float(risk_cfg.get("time_stop_min_R", 0.3) or 0.3)
    if time_stop_min > 0 and elapsed_minutes >= time_stop_min and R < time_stop_minR:
        out["close"] = True
        out["close_reason"] = f"time_stop_{elapsed_minutes:.0f}min_R={R:.2f}"
        return out

    # ---------- Standard BE / trail / partial ----------------------------
    if R >= be_at:
        if side == "BUY" and sl < entry:
            out["new_sl"] = entry
        elif side == "SELL" and sl > entry:
            out["new_sl"] = entry

    if R >= trail_at:
        new_sl = compute_trailing_stop(side, entry, current, sl, atr)
        if (side == "BUY" and new_sl > (out["new_sl"] or sl)) or (
            side == "SELL" and new_sl < (out["new_sl"] or sl)
        ):
            out["new_sl"] = new_sl

    if R >= partial_at and not closed_partial:
        out["partial_close_pct"] = float(partial_pct)

    return out
