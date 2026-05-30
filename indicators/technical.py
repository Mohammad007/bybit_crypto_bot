"""
Technical indicators used by the Trendline Breakout strategy.

Only the four indicators the strategy needs are implemented:
    *  EMA20 / EMA50  (trend filter)
    *  RSI 14         (momentum filter)
    *  ATR 14         (volatility filter)
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------
# EMA
# --------------------------------------------------------------------------
def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


# --------------------------------------------------------------------------
# RSI
# --------------------------------------------------------------------------
def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    roll_up = up.ewm(alpha=1 / period, adjust=False).mean()
    roll_down = down.ewm(alpha=1 / period, adjust=False).mean()
    rs = roll_up / roll_down.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    return out.fillna(50.0)


# --------------------------------------------------------------------------
# ATR
# --------------------------------------------------------------------------
def true_range(df: pd.DataFrame) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    return pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / period, adjust=False).mean()


# --------------------------------------------------------------------------
# convenience – attach the four indicators in one call
# --------------------------------------------------------------------------
def add_all_indicators(df: pd.DataFrame, cfg: dict | None = None) -> pd.DataFrame:
    """
    Mutates a copy of `df` with the four columns the strategy needs:
        ema_fast, ema_mid, rsi, atr.
    """
    cfg = cfg or {}
    out = df.copy()
    out["ema_fast"] = ema(out["close"], cfg.get("ema_fast", 20))
    out["ema_mid"] = ema(out["close"], cfg.get("ema_mid", 50))
    out["rsi"] = rsi(out["close"], cfg.get("rsi_period", 14))
    out["atr"] = atr(out, cfg.get("atr_period", 14))
    return out
