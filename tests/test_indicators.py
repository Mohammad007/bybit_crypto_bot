"""Smoke tests for the indicators used by Trendline Breakout."""
from __future__ import annotations

import numpy as np
import pandas as pd

from indicators import add_all_indicators, atr, ema, rsi


def _sample(n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    price = 2000 + np.cumsum(rng.normal(0, 1.0, n))
    high = price + rng.uniform(0.5, 2.0, n)
    low = price - rng.uniform(0.5, 2.0, n)
    open_ = np.r_[price[0], price[:-1]]
    df = pd.DataFrame(
        {
            "open": open_, "high": high, "low": low, "close": price,
            "volume": rng.integers(500, 5000, n),
        }
    )
    df.index = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    return df


def test_ema():
    df = _sample()
    e = ema(df["close"], 20)
    assert e.notna().any()


def test_rsi():
    df = _sample()
    r = rsi(df["close"], 14)
    assert r.between(0, 100).all()


def test_atr():
    df = _sample()
    a = atr(df, 14)
    assert (a.dropna() >= 0).all()
    assert a.notna().any()


def test_add_all_indicators():
    df = _sample()
    out = add_all_indicators(df)
    for col in ("ema_fast", "ema_mid", "rsi", "atr"):
        assert col in out.columns
    extras = set(out.columns) - {
        "open", "high", "low", "close", "volume",
        "ema_fast", "ema_mid", "rsi", "atr",
    }
    assert not extras, f"unexpected indicator columns: {extras}"
