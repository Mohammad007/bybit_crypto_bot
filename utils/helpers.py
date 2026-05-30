"""Small utility helpers used across the project."""
from __future__ import annotations

from datetime import datetime, timezone


def now_utc() -> datetime:
    """Return timezone-aware UTC datetime."""
    return datetime.now(tz=timezone.utc)


def fmt_money(value: float, symbol: str = "$") -> str:
    """Format a monetary value with two decimals."""
    sign = "-" if value < 0 else ""
    return f"{sign}{symbol}{abs(value):,.2f}"


def fmt_pct(value: float, digits: int = 2) -> str:
    return f"{value:+.{digits}f}%"


def safe_div(num: float, denom: float, default: float = 0.0) -> float:
    return num / denom if denom else default


def pct_change(a: float, b: float) -> float:
    """Percentage change from a to b."""
    return safe_div((b - a) * 100.0, a, 0.0)


# Price/point helpers -------------------------------------------------------
# `point_size` is the instrument tick size (read per-symbol from Bybit).

def points_to_price(points: float, point_size: float = 0.01) -> float:
    """Convert broker points to a price delta."""
    return points * point_size


def price_to_points(price_delta: float, point_size: float = 0.01) -> float:
    """Convert a price delta back into broker points."""
    return price_delta / point_size if point_size else 0.0


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def pick_frame(frames: dict, *preferred):
    """
    Return the first non-empty DataFrame from `frames` matching one of the
    `preferred` timeframe keys.  Avoids the truthiness-on-DataFrame trap.
    """
    for tf in preferred:
        df = frames.get(tf)
        if df is not None and not getattr(df, "empty", True):
            return df
    return None
