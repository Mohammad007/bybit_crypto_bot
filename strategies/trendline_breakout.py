"""
Trendline Break + Retest + Confirmation Strategy  (crypto / percentage-based)
=============================================================================

Designed to run across the WHOLE top-30 universe: every threshold is expressed
as a PERCENT of price, so the identical config works for a $100k BTC candle and
a $0.40 DOGE candle.

Order modes (configurable):
    *  market – fire a market BUY/SELL the moment all 5 rules pass
    *  stop   – place a conditional buy_stop / sell_stop at the breakout level

Entry rules:
    1. Trend       :  EMA20 > EMA50  AND  RSI > rsi_bull   (BUY)
                      EMA20 < EMA50  AND  RSI < rsi_bear   (SELL)
    2. Volatility  :  ATR/price*100 > atr_pct_min
    3. Liquidity   :  prev low broke prior low             (BUY sweep)
                      prev high broke prior high           (SELL sweep)
    4. Breakout    :  last close > prev high               (BUY) – market mode
                      last close < prev low                (SELL) – market mode
    5. Confirmation:  candle body/price*100 > body_pct_min – market mode

Risk
----
    SL = entry ± entry*sl_pct/100
    TP = entry ± entry*tp_pct/100        (default 1:2 R:R)
"""
from __future__ import annotations

from typing import Any

from config import settings
from utils.logger import get_logger
from utils.sessions import current_session

from .base import BaseStrategy, StrategyPlan

log = get_logger(__name__)


class TrendlineBreakoutStrategy(BaseStrategy):
    name = "trendline_breakout"
    exclusive = True

    # Active timeframes – only M15 by default.
    TF_LADDER = ("M15",)

    # ------------------------------------------------------------------
    def _cfg(self) -> dict:
        return settings.strategies.get(self.name, {}) or {}

    def compute_decision(self, ctx: dict[str, Any]) -> dict[str, Any]:
        cfg = self._cfg()
        avoid_asian = bool(cfg.get("avoid_asian", False))
        order_mode = str(cfg.get("order_type", "market")).lower()   # 'market' | 'stop'

        if avoid_asian and current_session() == "asia":
            return self._hold("Asian session avoided", order_mode)

        frames = ctx.get("frames", {})
        all_diag: list[str] = []
        for tf in self.TF_LADDER:
            df = frames.get(tf)
            if df is None or len(df) < 4 or "ema_fast" not in df.columns:
                all_diag.append(f"[{tf}] no data")
                continue
            result = self._check_rules(df, cfg, tf, order_mode)
            if result["decision"] != "HOLD":
                return result
            all_diag.extend(result.get("signals", [{}])[0].get("reasoning", []))
            all_diag.append("")

        return {
            "decision": "HOLD",
            "confidence": 50.0,
            "consensus": 1.0,
            "reason": "no setup",
            "signals": [{"name": "TrendlineBreakout", "direction": "HOLD",
                         "confidence": 50.0, "reasoning": all_diag}],
            "votes": {"HOLD": 1.0},
            "order_type": order_mode,
        }

    # ------------------------------------------------------------------
    def _hold(self, reason: str, order_mode: str = "market") -> dict[str, Any]:
        return {
            "decision": "HOLD",
            "confidence": 0.0,
            "consensus": 0.0,
            "reason": reason,
            "signals": [{"name": "TrendlineBreakout", "direction": "HOLD",
                         "confidence": 0.0, "reasoning": [reason]}],
            "votes": {"HOLD": 1.0},
            "order_type": order_mode,
        }

    # ------------------------------------------------------------------
    def _check_rules(self, df, cfg: dict, tf_name: str, order_mode: str) -> dict[str, Any]:
        atr_pct_min = float(cfg.get("atr_pct_min", 0.30))
        body_pct_min = float(cfg.get("body_pct_min", 0.10))
        rsi_bull = float(cfg.get("rsi_bull", 55))
        rsi_bear = float(cfg.get("rsi_bear", 45))

        last = df.iloc[-1]
        prev = df.iloc[-2]
        prev2 = df.iloc[-3]

        price = float(last["close"]) or 1.0

        # ---- 1. Trend ----
        bull_trend = (last["ema_fast"] > last["ema_mid"]) and (last["rsi"] > rsi_bull)
        bear_trend = (last["ema_fast"] < last["ema_mid"]) and (last["rsi"] < rsi_bear)

        # ---- 2. ATR filter (relative to price) ----
        atr_now = float(last.get("atr", 0.0))
        atr_pct = atr_now / price * 100.0
        atr_ok = atr_pct > atr_pct_min

        # ---- 3. Liquidity sweep ----
        liq_buy = float(prev["low"]) < float(prev2["low"])
        liq_sell = float(prev["high"]) > float(prev2["high"])

        prev_high = float(prev["high"])
        prev_low = float(prev["low"])

        # ---- 4. Breakout (market mode) ----
        brk_buy = float(last["close"]) > prev_high
        brk_sell = float(last["close"]) < prev_low

        # ---- 5. Confirmation candle (market mode) ----
        body_pct = abs(float(last["close"]) - float(last["open"])) / price * 100.0
        bull_conf = (last["close"] > last["open"]) and (body_pct > body_pct_min)
        bear_conf = (last["close"] < last["open"]) and (body_pct > body_pct_min)

        reasoning = [
            f"[{tf_name}] trend(bull={bull_trend},bear={bear_trend})",
            f"atr%={atr_pct:.3f}>{atr_pct_min}? {atr_ok}",
            f"liq(buy={liq_buy},sell={liq_sell})",
            f"brk(buy={brk_buy},sell={brk_sell})",
            f"conf%(bull={bull_conf},bear={bear_conf})",
            f"prev_high={prev_high:.6g}  prev_low={prev_low:.6g}",
        ]

        if order_mode == "stop":
            if bull_trend and atr_ok and liq_buy:
                return self._fire("BUY", tf_name, prev_high, reasoning,
                                  order_type="buy_stop",
                                  reason=f"[{tf_name}] BUY STOP pending @ {prev_high:.6g}")
            if bear_trend and atr_ok and liq_sell:
                return self._fire("SELL", tf_name, prev_low, reasoning,
                                  order_type="sell_stop",
                                  reason=f"[{tf_name}] SELL STOP pending @ {prev_low:.6g}")
        else:
            if bull_trend and atr_ok and liq_buy and brk_buy and bull_conf:
                return self._fire("BUY", tf_name, 0.0, reasoning,
                                  order_type="market",
                                  reason=f"[{tf_name}] all 5 BUY rules satisfied")
            if bear_trend and atr_ok and liq_sell and brk_sell and bear_conf:
                return self._fire("SELL", tf_name, 0.0, reasoning,
                                  order_type="market",
                                  reason=f"[{tf_name}] all 5 SELL rules satisfied")

        return {
            "decision": "HOLD",
            "confidence": 50.0,
            "consensus": 1.0,
            "reason": f"[{tf_name}] rules not aligned",
            "signals": [{"name": "TrendlineBreakout", "direction": "HOLD",
                         "confidence": 50.0, "reasoning": reasoning}],
            "votes": {"HOLD": 1.0},
            "order_type": order_mode,
            "tf_used": tf_name,
        }

    # ------------------------------------------------------------------
    def _fire(self, direction: str, tf_name: str, trigger_price: float,
              reasoning: list[str], order_type: str, reason: str) -> dict[str, Any]:
        return {
            "decision": direction,
            "confidence": 90.0,
            "consensus": 1.0,
            "reason": reason,
            "signals": [{"name": "TrendlineBreakout", "direction": direction,
                         "confidence": 90.0, "reasoning": reasoning}],
            "votes": {direction: 1.0},
            "order_type": order_type,
            "trigger_price": float(trigger_price),
            "tf_used": tf_name,
        }

    # ------------------------------------------------------------------
    def build_plan(self, decision: dict[str, Any], ctx: dict[str, Any]) -> StrategyPlan:
        direction = decision.get("decision", "HOLD")
        if direction == "HOLD":
            return StrategyPlan("HOLD", 0, 0, 0, "no signal")

        cfg = self._cfg()
        sl_pct = float(cfg.get("sl_pct", 1.0)) / 100.0
        # Fixed-USDT model: TP distance is scaled to the tp_usdt : sl_usdt ratio,
        # so profit at TP / loss at SL == tp_usdt / sl_usdt (default 10:5 = 2R).
        sl_usdt = float(cfg.get("sl_usdt", 0.0))
        tp_usdt = float(cfg.get("tp_usdt", 0.0))
        rr_ratio = (tp_usdt / sl_usdt) if (sl_usdt > 0 and tp_usdt > 0) else 2.0
        order_type = decision.get("order_type", "market")

        price = ctx.get("price", {})
        if not price:
            return StrategyPlan("HOLD", 0, 0, 0, "no price")

        if order_type in ("buy_stop", "sell_stop"):
            entry = float(decision.get("trigger_price", 0.0))
        elif direction == "BUY":
            entry = float(price.get("ask") or price.get("mid"))
        else:
            entry = float(price.get("bid") or price.get("mid"))

        if entry <= 0:
            return StrategyPlan("HOLD", 0, 0, 0, "no entry")

        sl_dist = entry * sl_pct
        tp_dist = sl_dist * rr_ratio
        if direction == "BUY":
            sl = entry - sl_dist
            tp = entry + tp_dist
        else:
            sl = entry + sl_dist
            tp = entry - tp_dist

        rr = rr_ratio
        plan = StrategyPlan(
            direction=direction,
            entry=entry,
            sl=sl,
            tp=tp,
            confidence=float(decision.get("confidence", 90.0)),
            reason=decision.get("reason", "trendline breakout"),
            rr=rr,
        )
        plan.order_type = order_type                          # type: ignore[attr-defined]
        plan.trigger_price = float(decision.get("trigger_price", 0.0))  # type: ignore[attr-defined]
        return plan
