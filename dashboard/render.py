"""ASCII candle renderer with strategy overlays.

Overlays shown on the chart:
    *  EMA20 (cyan) and EMA50 (yellow) lines
    *  Previous candle's HIGH → green dotted line = BUY breakout trigger
    *  Previous candle's LOW  → red dotted line   = SELL breakout trigger
"""
from __future__ import annotations

import pandas as pd
from rich.console import Group
from rich.text import Text


def render_candles_ascii(df: pd.DataFrame, height: int = 14, width: int = 60) -> Group:
    """Render an ASCII candlestick chart + EMA + breakout trigger lines."""
    if df is None or df.empty:
        return Group(Text("(no chart data)", style="dim"))

    candles = df.tail(width)
    hi = candles["high"].max()
    lo = candles["low"].min()
    if "ema_mid" in candles.columns:
        hi = max(hi, candles["ema_mid"].max())
        lo = min(lo, candles["ema_mid"].min())
    if hi == lo:
        return Group(Text("(flat data)", style="dim"))
    rng = hi - lo

    grid = [[" "] * len(candles) for _ in range(height)]
    colors = [[None] * len(candles) for _ in range(height)]

    def to_row(p: float) -> int:
        return int(round((hi - p) / rng * (height - 1)))

    # ----- Breakout trigger lines (drawn FIRST, candles paint over) -------
    if len(candles) >= 2:
        prev = candles.iloc[-2]
        prev_high = float(prev["high"])
        prev_low = float(prev["low"])

        hh = to_row(prev_high)
        ll = to_row(prev_low)
        if 0 <= hh < height:
            for c in range(len(candles)):
                grid[hh][c] = "·"
                colors[hh][c] = "bright_green"
        if 0 <= ll < height:
            for c in range(len(candles)):
                grid[ll][c] = "·"
                colors[ll][c] = "bright_red"

    # ----- EMA lines (also drawn before candles) --------------------------
    def _draw_line(col_name: str, color: str, char: str = "─"):
        if col_name not in candles.columns:
            return
        for c, v in enumerate(candles[col_name]):
            try:
                if pd.notna(v):
                    r = to_row(float(v))
                    if 0 <= r < height and grid[r][c] in (" ", "·"):
                        grid[r][c] = char
                        colors[r][c] = color
            except Exception:
                pass

    _draw_line("ema_mid", "yellow", "─")
    _draw_line("ema_fast", "cyan", "─")

    # ----- Candles (paint on top) -----------------------------------------
    for col, (_, row) in enumerate(candles.iterrows()):
        open_r = to_row(row["open"])
        close_r = to_row(row["close"])
        high_r = to_row(row["high"])
        low_r = to_row(row["low"])
        bullish = row["close"] >= row["open"]
        color = "green" if bullish else "red"

        for r in range(high_r, low_r + 1):
            grid[r][col] = "│"
            colors[r][col] = color
        body_top = min(open_r, close_r)
        body_bot = max(open_r, close_r)
        for r in range(body_top, body_bot + 1):
            grid[r][col] = "█"
            colors[r][col] = color

    # ----- assemble Text --------------------------------------------------
    chart = Text()
    for r in range(height):
        for c in range(len(candles)):
            ch = grid[r][c]
            color = colors[r][c]
            if color:
                chart.append(ch, style=f"bold {color}")
            else:
                chart.append(ch)
        chart.append("\n")

    # ----- trigger level summary ------------------------------------------
    summary = Text()
    if len(candles) >= 2:
        prev = candles.iloc[-2]
        last_close = float(candles["close"].iat[-1])
        prev_high = float(prev["high"])
        prev_low = float(prev["low"])
        diff_up = prev_high - last_close
        diff_dn = last_close - prev_low

        summary.append("BUY  > ", style="bold bright_green")
        summary.append(
            f"{prev_high:.2f}  ({diff_up:+.2f} away)   ",
            style="green",
        )
        summary.append("│  ", style="dim")
        summary.append("SELL < ", style="bold bright_red")
        summary.append(
            f"{prev_low:.2f}  ({-diff_dn:+.2f} away)",
            style="red",
        )
        summary.append("\n")
        if "ema_fast" in candles.columns and "ema_mid" in candles.columns:
            ef = float(candles["ema_fast"].iat[-1])
            em = float(candles["ema_mid"].iat[-1])
            summary.append("EMA20=", style="cyan")
            summary.append(f"{ef:.2f}  ", style="bold cyan")
            summary.append("EMA50=", style="yellow")
            summary.append(f"{em:.2f}", style="bold yellow")
            summary.append("  ")
            if "rsi" in candles.columns:
                rsi_v = float(candles["rsi"].iat[-1])
                rsi_color = "green" if rsi_v > 55 else ("red" if rsi_v < 45 else "yellow")
                summary.append("RSI=", style="dim")
                summary.append(f"{rsi_v:.1f}", style=f"bold {rsi_color}")
            if "atr" in candles.columns:
                atr_v = float(candles["atr"].iat[-1])
                summary.append("  ATR=", style="dim")
                summary.append(f"{atr_v:.2f}", style="bold magenta")

    footer = Text(
        f"high={hi:.2f}  low={lo:.2f}  last={candles['close'].iat[-1]:.2f}",
        style="dim",
    )
    return Group(chart, summary, footer)
