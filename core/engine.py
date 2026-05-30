"""
Bot Engine – multi-symbol scanner for the Trendline Breakout strategy on
Bybit V5 USDT perpetuals.

Each tick the engine:
1.  Syncs equity from the broker
2.  Reconciles broker-closed positions into the journal
3.  Captures pending (conditional) orders that filled
4.  Manages every open position (BE / trail / time-stop – disabled by default)
5.  SCANS the whole top-30 universe: pulls M15 history + EMA/RSI/ATR and asks
    the strategy for a BUY / SELL / HOLD verdict per symbol
6.  Ranks the actionable signals and opens up to ``max_new_per_tick`` trades,
    respecting the global risk envelope (max concurrent / per-day)
7.  Builds a snapshot (scan table + positions) for the Rich dashboard
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from config import settings
from database import TradeJournal, TradeRecord
from execution import Order, build_broker
from indicators import add_all_indicators
from risk_management import RiskEngine, manage_open_trade
from strategies import get_strategy
from utils.alerts import AlertManager
from utils.helpers import pick_frame
from utils.logger import get_logger

from .state import BotState

log = get_logger(__name__)


class BotEngine:
    """Multi-symbol scanner orchestrator."""

    def __init__(self, mode: str | None = None) -> None:
        self.mode = (mode or settings.mode).lower()
        self.state = BotState()
        self.journal = TradeJournal()
        self.broker = build_broker(self.mode)
        self.risk = RiskEngine(self.journal)
        self.strategy = get_strategy(settings.strategies.get("active", "trendline_breakout"))
        self.alerts = AlertManager()

        # universe of symbols the scanner trades (resolved at start())
        self.symbols: list[str] = list(settings.universe.get("symbols", []) or [])
        self.focus_symbol: str = settings.symbol

        self._snapshot: dict[str, Any] = {}
        self._snap_lock = threading.RLock()
        self._broker_ping_ms = 0.0

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self.state.running

    def start(self) -> None:
        if self.state.running:
            return
        if not self.broker.connect():
            if self.mode in ("demo", "live") and self.broker.name != "paper":
                log.error(
                    "\n==========================================================\n"
                    "  Bybit connect FAILED – check BYBIT_API_KEY/SECRET, demo flag,\n"
                    "  and network. Falling back to PAPER broker (SIMULATED).\n"
                    "=========================================================="
                )
                from execution.paper_broker import PaperBroker
                self.broker = PaperBroker()
                if not self.broker.connect():
                    log.error("Paper broker connection failed too – aborting.")
                    return
                self.mode = "paper-fallback"
            else:
                log.error("Broker connection failed – aborting start.")
                return

        self.state.running = True
        self._resolve_universe()

        # Sync RiskEngine.capital with real broker balance
        try:
            acct = self.broker.account_info() or {}
            real_balance = float(acct.get("balance") or acct.get("equity") or 0.0)
            if real_balance > 0:
                self.risk.capital = real_balance
                self.risk._equity_high = max(self.risk._equity_high, real_balance)
                log.info(f"risk capital synced to broker balance: {real_balance:.2f}")
        except Exception as exc:
            log.warning(f"could not sync broker balance: {exc}")

        log.info(
            f"engine started ({self.mode} mode, {len(self.symbols)} symbols, "
            f"strategy={self.strategy.name})"
        )

    def _resolve_universe(self) -> None:
        """Pick the trading universe: live top-N by turnover, or the static list."""
        count = int(settings.universe.get("count", 30))
        static = list(settings.universe.get("symbols", []) or [])
        auto = bool(settings.universe.get("auto_top30", True))
        exclude = set(settings.universe.get("exclude", []) or [])

        chosen = static[:count]
        if auto and hasattr(self.broker, "top_symbols_by_turnover") and self.broker.is_connected():
            try:
                top = self.broker.top_symbols_by_turnover(count, exclude=exclude)
                if top:
                    chosen = top
                    log.info(f"universe = live top {len(chosen)} USDT perps by turnover")
            except Exception as exc:
                log.warning(f"auto top-30 failed ({exc}); using static list")
        self.symbols = chosen or static[:count]
        if self.focus_symbol not in self.symbols and self.symbols:
            self.focus_symbol = self.symbols[0]

    def stop(self) -> None:
        self.state.running = False
        try:
            self.broker.disconnect()
        except Exception:
            pass
        log.info("engine stopped")

    # ------------------------------------------------------------------
    # main loop
    # ------------------------------------------------------------------
    _TF_BARS = {"M5": 200, "M15": 200, "M30": 200, "H1": 200, "H4": 200, "D1": 200}

    def tick(self) -> None:
        if not self.state.running:
            return
        t0 = time.perf_counter()
        try:
            acct = self.broker.account_info() or {}
            live_equity = float(acct.get("equity") or 0.0)
            if live_equity > 0:
                self.risk.update_equity(live_equity)
                self.risk.capital = live_equity

            # keep the journal in sync with broker reality first
            self._reconcile_closed_trades()
            self._journal_filled_pendings()

            # scan the whole universe
            scan = self._scan_universe()

            # manage existing trades (uses scan frames where available)
            self._manage_open_trades(scan)

            # open new trades from the best signals
            self._open_from_scan(scan)

            self.state.heartbeat()
            self._broker_ping_ms = (time.perf_counter() - t0) * 1000.0
            self._update_snapshot(self._build_snapshot(scan, acct))
        except Exception as exc:
            log.opt(exception=exc).error(f"tick error: {exc}")
            self.state.last_error = str(exc)

    def run_forever(self) -> None:
        try:
            self.start()
            refresh = float(settings.bot.get("refresh_seconds", 6))
            while self.state.running:
                self.tick()
                time.sleep(refresh)
        except KeyboardInterrupt:
            log.warning("KeyboardInterrupt – stopping")
        finally:
            self.stop()

    # ------------------------------------------------------------------
    # data pipeline
    # ------------------------------------------------------------------
    def _timeframes(self) -> list[str]:
        tfs: list[str] = []
        for key in ("htf", "itf", "ltf", "scalp"):
            tfs += settings.timeframes.get(key, []) or []
        return list(dict.fromkeys(tfs))

    def _pull_frames(self, symbol: str) -> dict[str, pd.DataFrame]:
        frames: dict[str, pd.DataFrame] = {}
        for tf in self._timeframes():
            bars = self._TF_BARS.get(tf, 500)
            df = self.broker.get_history(symbol, tf, bars)
            if df is None or df.empty:
                continue
            frames[tf] = add_all_indicators(df, settings.indicators)
        return frames

    def _scan_universe(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        max_spread = float(settings.market.get("spread_max_points", 5000))
        for sym in self.symbols:
            frames = self._pull_frames(sym)
            if not frames:
                continue
            price = self.broker.get_price(sym)
            if not price:
                continue
            ctx = {
                "symbol": sym,
                "frames": frames,
                "price": price,
                "spread_points": float(price.get("spread_points", 0.0)),
                "max_spread_points": max_spread,
            }
            decision = self.strategy.compute_decision(ctx)
            if decision["decision"] in ("BUY", "SELL"):
                # only persist actionable signals (avoid flooding the DB)
                self.journal.record_signal(
                    sym, decision["decision"], decision.get("confidence", 0.0),
                    {"signals": decision.get("signals", [])},
                    notes=decision.get("reason", ""), executed=False,
                )
            results.append({"symbol": sym, "ctx": ctx, "frames": frames,
                            "price": price, "decision": decision})
        return results

    # ------------------------------------------------------------------
    # opening trades
    # ------------------------------------------------------------------
    def _open_from_scan(self, scan: list[dict[str, Any]]) -> None:
        actionable = [r for r in scan if r["decision"]["decision"] in ("BUY", "SELL")]
        if not actionable:
            return

        rank_by = str(settings.scanner.get("rank_by", "confidence"))
        if rank_by == "turnover":
            actionable.sort(key=lambda r: r["price"].get("turnover24h", 0.0), reverse=True)
        else:
            actionable.sort(key=lambda r: r["decision"].get("confidence", 0.0), reverse=True)

        one_per_symbol = bool(settings.scanner.get("one_position_per_symbol", True))
        max_new = int(settings.scanner.get("max_new_per_tick", 2))

        held = {p.symbol for p in self.broker.open_positions()}
        pending_syms = {p.symbol for p in self.broker.pending_orders()}

        opened = 0
        for r in actionable:
            if opened >= max_new:
                break
            sym = r["symbol"]
            if one_per_symbol and sym in held:
                continue
            if sym in pending_syms:
                continue
            ok, why = self.risk.can_trade()
            if not ok:
                log.info(f"scanner stop: risk envelope – {why}")
                break
            if self._open_trade(r):
                opened += 1
                held.add(sym)

    def _open_trade(self, r: dict[str, Any]) -> bool:
        sym = r["symbol"]
        decision = r["decision"]
        ctx = r["ctx"]
        plan = self.strategy.build_plan(decision, ctx)
        if not plan.actionable:
            return False

        order_type = getattr(plan, "order_type", "market")
        trigger_price = getattr(plan, "trigger_price", 0.0)

        spread = float(ctx.get("spread_points", 0.0))
        if spread > float(ctx.get("max_spread_points", 5000)):
            log.info(f"{sym}: skip – spread {spread:.0f} too wide")
            return False

        active = settings.strategies.get("active", "trendline_breakout")
        risk_usdt = float(settings.strategies.get(active, {}).get("sl_usdt", 0.0))
        qty = self.risk.size_position(plan.entry, plan.sl, risk_usdt=risk_usdt)
        if qty <= 0:
            log.warning(f"{sym}: computed qty 0; skipping")
            return False

        pending_expiry = float(settings.risk.get("pending_expiry_minutes", 15.0))
        order = Order(
            side=plan.direction,
            symbol=sym,
            lot=qty,
            sl=plan.sl,
            tp=plan.tp,
            comment=settings.execution.get("order_link_prefix", "CRYPTO_BRK"),
            order_type=order_type,
            trigger_price=trigger_price,
            expiry_minutes=pending_expiry if order_type != "market" else 0.0,
        )
        pos = self.broker.place_order(order)

        if pos is None:
            # pending/conditional order placed (or rejected) – journal on fill
            if order_type in ("buy_stop", "sell_stop"):
                log.info(f"{sym}: pending {order_type} @ {trigger_price:.6g}")
                return True
            return False

        self.journal.open_trade(
            TradeRecord(
                ticket=pos.ticket, symbol=sym, side=plan.direction, lot=pos.lot,
                entry_price=pos.entry_price, sl=plan.sl, tp=plan.tp,
                confidence=plan.confidence, strategy=self.strategy.name,
                mode=self.mode, reason=plan.reason,
            )
        )
        self.alerts.trade_opened(sym, plan.direction, pos.lot, pos.entry_price,
                                 plan.sl, plan.tp, plan.confidence)
        return True

    def _journal_filled_pendings(self) -> None:
        """Conditional orders that filled appear as broker positions with no
        journal entry – discover and record them."""
        journal_tickets = {t.ticket for t in self.journal.open_trades()}
        for p in self.broker.open_positions():
            if p.ticket in journal_tickets:
                continue
            self.journal.open_trade(
                TradeRecord(
                    ticket=p.ticket, symbol=p.symbol, side=p.side, lot=p.lot,
                    entry_price=p.entry_price, sl=p.sl, tp=p.tp, confidence=90.0,
                    strategy=self.strategy.name, mode=self.mode,
                    reason="pending order filled",
                )
            )
            self.alerts.trade_opened(p.symbol, p.side, p.lot, p.entry_price,
                                     p.sl, p.tp, 90.0)
            log.info(f"pending fill captured: {p.side} {p.symbol} @ {p.entry_price:.6g}")

    # ------------------------------------------------------------------
    # managing / closing trades
    # ------------------------------------------------------------------
    def _manage_open_trades(self, scan: list[dict[str, Any]]) -> None:
        positions = self.broker.open_positions()
        if not positions:
            return
        frame_by_sym = {r["symbol"]: r["frames"] for r in scan}
        price_by_sym = {r["symbol"]: r["price"] for r in scan}
        now_utc = datetime.now(tz=timezone.utc)

        for pos in positions:
            frames = frame_by_sym.get(pos.symbol)
            df = pick_frame(frames, "M15", "M5") if frames else None
            if df is None or "atr" not in df.columns:
                continue
            atr_val = float(df["atr"].iat[-1])
            price = price_by_sym.get(pos.symbol) or self.broker.get_price(pos.symbol)
            if not price:
                continue
            current_price = price["bid"] if pos.side == "BUY" else price["ask"]
            tick_size = float(getattr(self.broker, "broker_point", 0.01)) or 0.01
            open_time = pos.open_time
            if open_time.tzinfo is None:
                open_time = open_time.replace(tzinfo=timezone.utc)
            elapsed_minutes = max(0.0, (now_utc - open_time).total_seconds() / 60.0)

            action = manage_open_trade(
                side=pos.side, entry=pos.entry_price, current=current_price,
                sl=pos.sl, tp=pos.tp, atr=atr_val, risk_cfg=settings.risk,
                closed_partial=self.state.closed_partial.get(pos.ticket, False),
                point_size=tick_size, elapsed_minutes=elapsed_minutes,
                current_pnl=float(pos.pnl or 0.0),
            )
            if action.get("close"):
                if self.broker.close_position(pos.ticket, price=current_price):
                    log.info(f"closed {pos.symbol} → {action.get('close_reason', '?')}")
                continue
            if action["new_sl"] is not None:
                self.broker.modify_position(pos.ticket, sl=action["new_sl"])
                log.info(f"trail SL {pos.symbol} -> {action['new_sl']:.6g}")
            if action["partial_close_pct"]:
                self.state.closed_partial[pos.ticket] = True

    def _reconcile_closed_trades(self) -> None:
        live_tickets = {p.ticket for p in self.broker.open_positions()}
        for t in self.journal.open_trades():
            if t.ticket in live_tickets:
                continue
            exit_p, pnl = self._fetch_realised_pnl(t)
            pnl_pct = pnl * 100.0 / max(self.risk.capital, 1.0)
            self.journal.close_trade(t.ticket, exit_p, pnl, pnl_pct)
            self.alerts.trade_closed(t.symbol, t.side, pnl, pnl_pct)
            log.info(f"reconciled {t.symbol}: exit={exit_p:.6g} pnl={pnl:+.2f}")

    def _fetch_realised_pnl(self, t) -> tuple[float, float]:
        """Prefer broker realised-PnL history; fall back to a mark estimate."""
        if hasattr(self.broker, "realised_pnl"):
            try:
                exit_p, pnl = self.broker.realised_pnl(t.symbol)
                if exit_p > 0:
                    return float(exit_p), float(pnl)
            except Exception as exc:
                log.debug(f"realised_pnl({t.symbol}) failed: {exc}")
        price = self.broker.get_price(t.symbol)
        exit_p = float(price.get("mid", t.entry_price)) if price else t.entry_price
        sign = 1 if t.side == "BUY" else -1
        pnl = (exit_p - t.entry_price) * sign * t.lot
        return exit_p, pnl

    # ------------------------------------------------------------------
    # snapshot for dashboard
    # ------------------------------------------------------------------
    def _build_snapshot(self, scan: list[dict[str, Any]], acct: dict[str, Any]) -> dict[str, Any]:
        positions = self.broker.open_positions()
        positions_payload = [{
            "ticket": p.ticket, "symbol": p.symbol, "side": p.side, "lot": p.lot,
            "entry": p.entry_price, "sl": p.sl, "tp": p.tp, "pnl": p.pnl,
        } for p in positions]

        pending_payload = [{
            "ticket": p.ticket, "symbol": p.symbol, "side": p.side, "lot": p.lot,
            "trigger": p.trigger_price, "sl": p.sl, "tp": p.tp, "type": p.order_type,
        } for p in self.broker.pending_orders()]

        # scan rows: actionable first, then by confidence
        held = {p.symbol for p in positions}
        scan_rows = []
        for r in scan:
            d = r["decision"]
            scan_rows.append({
                "symbol": r["symbol"],
                "last": r["price"].get("mid", 0.0),
                "change24h": r["price"].get("price24h_pcnt", 0.0) * 100.0,
                "decision": d["decision"],
                "confidence": d.get("confidence", 0.0),
                "reason": d.get("reason", ""),
                "held": r["symbol"] in held,
            })
        scan_rows.sort(key=lambda x: (
            0 if x["decision"] in ("BUY", "SELL") else 1,
            -x["confidence"],
        ))

        # focus symbol for the chart: a held position, else first actionable, else default
        focus = None
        if positions:
            focus = positions[0].symbol
        else:
            for x in scan_rows:
                if x["decision"] in ("BUY", "SELL"):
                    focus = x["symbol"]
                    break
        focus = focus or self.focus_symbol
        self.focus_symbol = focus
        chart_df = None
        focus_price = {}
        for r in scan:
            if r["symbol"] == focus:
                chart_df = pick_frame(r["frames"], "M15", "M5")
                focus_price = r["price"]
                break

        ok, why = self.risk.can_trade()
        return {
            "mode": self.mode,
            "broker": self.broker.name,
            "connected": self.broker.is_connected(),
            "account": acct or self.broker.account_info(),
            "universe_size": len(self.symbols),
            "scanned": len(scan),
            "focus_symbol": focus,
            "price": focus_price,
            "chart_df": chart_df,
            "scan": scan_rows,
            "positions": positions_payload,
            "pending": pending_payload,
            "daily_pnl": self.journal.daily_pnl(),
            "weekly_pnl": self.journal.weekly_pnl(),
            "trades_today": self.journal.trades_today(),
            "win_rate": self.journal.win_rate(),
            "risk_state": "OK" if ok else f"BLOCKED: {why}",
            "broker_ping_ms": self._broker_ping_ms,
        }

    def _update_snapshot(self, snap: dict[str, Any]) -> None:
        with self._snap_lock:
            self._snapshot.update(snap)

    def snapshot(self) -> dict[str, Any]:
        with self._snap_lock:
            return dict(self._snapshot)
