"""
Bybit V5 broker integration (USDT Perpetuals / linear).

Uses the official `pybit` SDK against Bybit's **demo trading** environment by
default (``demo=True`` → api-demo.bybit.com).  Set ``BYBIT_DEMO=false`` in .env
to trade the real account, or ``BYBIT_TESTNET=true`` for the public testnet.

Docs: https://bybit-exchange.github.io/docs/v5/intro

Design notes
------------
*  We trade **one-way mode** linear USDT perps, so each symbol has at most ONE
   position.  We therefore use the *symbol* itself as the position "ticket".
*  Quantities are in coin units (1 contract = 1 coin for linear USDT perps).
*  SL / TP are attached to the position (tpslMode="Full").
*  Instrument filters (qtyStep / minOrderQty / tickSize) are cached so order
   prices & sizes are always rounded to broker precision.
"""
from __future__ import annotations

import math
import time as time_mod
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from config import settings
from utils.logger import get_logger

from .base import BaseBroker, Order, PendingOrder, Position

log = get_logger(__name__)

try:
    from pybit.unified_trading import HTTP  # type: ignore
    PYBIT_AVAILABLE = True
except Exception as exc:  # pragma: no cover - dependency missing
    HTTP = None  # type: ignore
    PYBIT_AVAILABLE = False
    log.debug(f"pybit not importable: {exc}")


# Bybit V5 kline interval codes.  Minutes are bare numbers; D/W/M are letters.
_TF_MAP = {
    "M1": "1", "M3": "3", "M5": "5", "M15": "15", "M30": "30",
    "H1": "60", "H2": "120", "H4": "240", "H6": "360", "H12": "720",
    "D1": "D", "W1": "W", "MN1": "M",
}

CATEGORY = "linear"
SETTLE_COIN = "USDT"


class BybitBroker(BaseBroker):
    name = "bybit"

    def __init__(self) -> None:
        self._connected = False
        self._session: Any = None
        self._instruments: dict[str, dict[str, float]] = {}
        self._leverage_set: set[str] = set()
        self._ticker_cache: dict[str, dict[str, float]] = {}
        self._ticker_cache_ts: float = 0.0
        # broker_* attrs kept for engine compatibility (it reads them at start)
        self.broker_contract_size = 1.0
        self.broker_point = 0.01
        self.broker_min_lot = 0.0
        self.broker_max_lot = 0.0
        self.broker_lot_step = 0.0

    # ------------------------------------------------------------------
    # connection
    # ------------------------------------------------------------------
    def connect(self) -> bool:
        if not PYBIT_AVAILABLE:
            log.error("pybit package not available – cannot use BybitBroker (pip install pybit)")
            return False
        api_key = settings.bybit_api_key
        api_secret = settings.bybit_api_secret
        if not api_key or not api_secret:
            log.error("BYBIT_API_KEY / BYBIT_API_SECRET not set in .env")
            return False
        try:
            self._session = HTTP(
                testnet=bool(settings.bybit_testnet),
                demo=bool(settings.bybit_demo),
                api_key=api_key,
                api_secret=api_secret,
            )
            # smoke test the credentials
            bal = self._session.get_wallet_balance(accountType="UNIFIED")
            if bal.get("retCode") != 0:
                log.error(f"bybit auth failed: {bal.get('retMsg')}")
                return False
        except Exception as exc:
            log.error(f"bybit connect failed: {exc}")
            return False

        env = (
            "TESTNET" if settings.bybit_testnet
            else ("DEMO" if settings.bybit_demo else "LIVE")
        )
        self._connected = True
        log.info(f"Bybit connected [{env}]  category={CATEGORY} settle={SETTLE_COIN}")
        return True

    def disconnect(self) -> None:
        self._connected = False
        self._session = None

    def is_connected(self) -> bool:
        return self._connected and self._session is not None

    # ------------------------------------------------------------------
    # instrument metadata
    # ------------------------------------------------------------------
    def _instrument(self, symbol: str) -> dict[str, float]:
        """Return cached {qty_step, min_qty, max_qty, tick_size, price_decimals}."""
        if symbol in self._instruments:
            return self._instruments[symbol]
        meta = {"qty_step": 0.001, "min_qty": 0.001, "max_qty": 1e9,
                "tick_size": 0.01, "price_decimals": 2, "qty_decimals": 3}
        try:
            r = self._session.get_instruments_info(category=CATEGORY, symbol=symbol)
            row = (r.get("result", {}).get("list") or [None])[0]
            if row:
                lot = row.get("lotSizeFilter", {})
                prc = row.get("priceFilter", {})
                meta["qty_step"] = float(lot.get("qtyStep", meta["qty_step"]))
                meta["min_qty"] = float(lot.get("minOrderQty", meta["min_qty"]))
                meta["max_qty"] = float(lot.get("maxOrderQty", meta["max_qty"]))
                meta["tick_size"] = float(prc.get("tickSize", meta["tick_size"]))
                meta["price_decimals"] = _decimals(meta["tick_size"])
                meta["qty_decimals"] = _decimals(meta["qty_step"])
        except Exception as exc:
            log.debug(f"get_instruments_info({symbol}) failed: {exc}")
        self._instruments[symbol] = meta
        return meta

    def round_qty(self, symbol: str, qty: float) -> float:
        meta = self._instrument(symbol)
        step = meta["qty_step"] or 0.001
        q = math.floor(qty / step) * step
        q = max(q, meta["min_qty"])
        q = min(q, meta["max_qty"])
        return round(q, meta["qty_decimals"])

    def round_price(self, symbol: str, price: float) -> float:
        meta = self._instrument(symbol)
        tick = meta["tick_size"] or 0.01
        return round(round(price / tick) * tick, meta["price_decimals"])

    # ------------------------------------------------------------------
    # account
    # ------------------------------------------------------------------
    def account_info(self) -> dict[str, Any]:
        if not self.is_connected():
            return {}
        try:
            r = self._session.get_wallet_balance(accountType="UNIFIED", coin=SETTLE_COIN)
            row = (r.get("result", {}).get("list") or [{}])[0]

            # Prefer the USDT coin's own figures (the actual demo wallet USDT),
            # falling back to the account-wide USD totals if the coin is absent.
            coin = next(
                (c for c in (row.get("coin") or []) if c.get("coin") == SETTLE_COIN),
                {},
            )
            wallet = float(coin.get("walletBalance") or row.get("totalWalletBalance") or 0.0)
            equity = float(
                coin.get("equity")
                or row.get("totalEquity")
                or wallet
            )
            avail = float(
                coin.get("availableToWithdraw")
                or coin.get("availableBalance")
                or row.get("totalAvailableBalance")
                or 0.0
            )
            used = float(coin.get("totalPositionIM") or row.get("totalInitialMargin") or 0.0)
            return {
                "broker": "bybit",
                "balance": wallet,
                "equity": equity,
                "margin": used,
                "free_margin": avail,
                "currency": SETTLE_COIN,
                "leverage": int(settings.bybit_leverage),
            }
        except Exception as exc:
            log.debug(f"account_info failed: {exc}")
            return {}

    # ------------------------------------------------------------------
    # pricing
    # ------------------------------------------------------------------
    def all_tickers(self, max_age: float = 2.0) -> dict[str, dict[str, float]]:
        """Batch-fetch every linear ticker once and cache for `max_age` seconds."""
        now = time_mod.time()
        if self._ticker_cache and (now - self._ticker_cache_ts) < max_age:
            return self._ticker_cache
        out: dict[str, dict[str, float]] = {}
        try:
            r = self._session.get_tickers(category=CATEGORY)
            for t in r.get("result", {}).get("list", []):
                sym = t.get("symbol")
                if not sym:
                    continue
                bid = float(t.get("bid1Price") or 0.0)
                ask = float(t.get("ask1Price") or 0.0)
                last = float(t.get("lastPrice") or 0.0)
                out[sym] = {
                    "bid": bid or last,
                    "ask": ask or last,
                    "last": last,
                    "mid": (bid + ask) / 2 if (bid and ask) else last,
                    "turnover24h": float(t.get("turnover24h") or 0.0),
                    "price24h_pcnt": float(t.get("price24hPcnt") or 0.0),
                }
            self._ticker_cache = out
            self._ticker_cache_ts = now
        except Exception as exc:
            log.debug(f"get_tickers failed: {exc}")
        return self._ticker_cache

    def get_price(self, symbol: str) -> dict[str, float]:
        tickers = self.all_tickers()
        t = tickers.get(symbol)
        if not t:
            return {}
        meta = self._instrument(symbol)
        tick = meta["tick_size"] or 0.01
        spread_points = abs(t["ask"] - t["bid"]) / tick if tick else 0.0
        return {
            "bid": t["bid"],
            "ask": t["ask"],
            "mid": t["mid"],
            "spread_points": spread_points,
        }

    def top_symbols_by_turnover(self, n: int = 30,
                                exclude: set[str] | None = None) -> list[str]:
        """Return the top `n` USDT-perp symbols by 24h turnover (USD volume)."""
        exclude = exclude or set()
        tickers = self.all_tickers(max_age=60.0)
        rows = [
            (sym, d["turnover24h"])
            for sym, d in tickers.items()
            if sym.endswith("USDT") and sym not in exclude
        ]
        rows.sort(key=lambda x: x[1], reverse=True)
        return [sym for sym, _ in rows[:n]]

    # ------------------------------------------------------------------
    # history
    # ------------------------------------------------------------------
    def get_history(self, symbol: str, timeframe: str, bars: int = 500) -> pd.DataFrame:
        if not self.is_connected():
            return pd.DataFrame()
        interval = _TF_MAP.get(timeframe, "15")
        limit = min(int(bars), 1000)
        try:
            r = self._session.get_kline(
                category=CATEGORY, symbol=symbol, interval=interval, limit=limit
            )
            rows = r.get("result", {}).get("list", [])
        except Exception as exc:
            log.debug(f"get_kline({symbol},{timeframe}) failed: {exc}")
            return pd.DataFrame()
        if not rows:
            return pd.DataFrame()
        # Bybit returns newest-first: [start, open, high, low, close, volume, turnover]
        df = pd.DataFrame(
            rows, columns=["time", "open", "high", "low", "close", "volume", "turnover"]
        )
        df = df.iloc[::-1]  # oldest-first
        df["time"] = pd.to_datetime(df["time"].astype("int64"), unit="ms", utc=True)
        for c in ("open", "high", "low", "close", "volume"):
            df[c] = df[c].astype(float)
        return df.set_index("time")[["open", "high", "low", "close", "volume"]]

    # ------------------------------------------------------------------
    # leverage
    # ------------------------------------------------------------------
    def _ensure_leverage(self, symbol: str) -> None:
        if symbol in self._leverage_set:
            return
        lev = str(settings.bybit_leverage)
        try:
            self._session.set_leverage(
                category=CATEGORY, symbol=symbol, buyLeverage=lev, sellLeverage=lev
            )
        except Exception as exc:
            # "leverage not modified" (110043) is fine – it's already set
            if "110043" not in str(exc):
                log.debug(f"set_leverage({symbol}) note: {exc}")
        self._leverage_set.add(symbol)

    # ------------------------------------------------------------------
    # orders
    # ------------------------------------------------------------------
    def place_order(self, order: Order) -> Position | None:
        if not self.is_connected():
            return None
        symbol = order.symbol
        self._ensure_leverage(symbol)
        side = "Buy" if order.side == "BUY" else "Sell"
        qty = self.round_qty(symbol, order.lot)
        if qty <= 0:
            log.warning(f"{symbol}: computed qty 0 – skipping")
            return None

        params: dict[str, Any] = {
            "category": CATEGORY,
            "symbol": symbol,
            "side": side,
            "orderType": "Market",
            "qty": _fmt(qty, self._instrument(symbol)["qty_decimals"]),
            "positionIdx": 0,
            "tpslMode": "Full",
        }
        if order.sl:
            params["stopLoss"] = _fmt(self.round_price(symbol, order.sl),
                                      self._instrument(symbol)["price_decimals"])
        if order.tp:
            params["takeProfit"] = _fmt(self.round_price(symbol, order.tp),
                                        self._instrument(symbol)["price_decimals"])

        # Pending stop = conditional market order at a trigger price.
        if order.order_type in ("buy_stop", "sell_stop"):
            trig = self.round_price(symbol, order.trigger_price)
            params["triggerPrice"] = _fmt(trig, self._instrument(symbol)["price_decimals"])
            # 1 = trigger when last price rises to trigger; 2 = when it falls
            params["triggerDirection"] = 1 if order.order_type == "buy_stop" else 2

        try:
            r = self._session.place_order(**params)
            if r.get("retCode") != 0:
                log.error(f"bybit place_order {symbol} failed: {r.get('retMsg')}")
                return None
        except Exception as exc:
            log.error(f"bybit place_order {symbol} error: {exc}")
            return None

        # Conditional order → position materialises on trigger; journal later.
        if order.order_type in ("buy_stop", "sell_stop"):
            log.info(f"bybit conditional {order.order_type.upper()} {symbol} "
                     f"qty={qty} trigger={trig}")
            return None

        # Market filled – read the resulting position for the real avg price.
        entry = self.round_price(symbol, self.get_price(symbol).get("mid", 0.0))
        for p in self.open_positions(symbol):
            if p.symbol == symbol:
                entry = p.entry_price
                break
        log.info(f"bybit MARKET {order.side} {symbol} qty={qty} @ {entry} "
                 f"sl={order.sl:.6g} tp={order.tp:.6g}")
        return Position(
            ticket=symbol,
            side=order.side,
            symbol=symbol,
            lot=qty,
            entry_price=entry,
            sl=order.sl,
            tp=order.tp,
            open_time=datetime.now(tz=timezone.utc),
            current_price=entry,
        )

    def close_position(self, ticket: str, price: float | None = None) -> bool:
        """`ticket` is the symbol (one-way mode → one position per symbol)."""
        if not self.is_connected():
            return False
        symbol = ticket
        pos = next((p for p in self.open_positions(symbol) if p.symbol == symbol), None)
        if pos is None:
            return False
        close_side = "Sell" if pos.side == "BUY" else "Buy"
        try:
            r = self._session.place_order(
                category=CATEGORY,
                symbol=symbol,
                side=close_side,
                orderType="Market",
                qty=_fmt(pos.lot, self._instrument(symbol)["qty_decimals"]),
                positionIdx=0,
                reduceOnly=True,
            )
            ok = r.get("retCode") == 0
            if not ok:
                log.error(f"bybit close {symbol} failed: {r.get('retMsg')}")
            return ok
        except Exception as exc:
            log.error(f"bybit close {symbol} error: {exc}")
            return False

    def modify_position(self, ticket: str, sl: float | None = None,
                        tp: float | None = None) -> bool:
        if not self.is_connected():
            return False
        symbol = ticket
        params: dict[str, Any] = {
            "category": CATEGORY, "symbol": symbol, "positionIdx": 0, "tpslMode": "Full",
        }
        dec = self._instrument(symbol)["price_decimals"]
        if sl is not None:
            params["stopLoss"] = _fmt(self.round_price(symbol, sl), dec)
        if tp is not None:
            params["takeProfit"] = _fmt(self.round_price(symbol, tp), dec)
        try:
            r = self._session.set_trading_stop(**params)
            return r.get("retCode") == 0
        except Exception as exc:
            # 34040 = "not modified"
            if "34040" not in str(exc):
                log.debug(f"set_trading_stop({symbol}) note: {exc}")
            return False

    def open_positions(self, symbol: str | None = None) -> list[Position]:
        if not self.is_connected():
            return []
        try:
            kwargs: dict[str, Any] = {"category": CATEGORY}
            if symbol:
                kwargs["symbol"] = symbol
            else:
                kwargs["settleCoin"] = SETTLE_COIN
            r = self._session.get_positions(**kwargs)
            rows = r.get("result", {}).get("list", [])
        except Exception as exc:
            log.debug(f"get_positions failed: {exc}")
            return []
        out: list[Position] = []
        for p in rows:
            size = float(p.get("size") or 0.0)
            if size <= 0:
                continue
            sym = p.get("symbol")
            side = "BUY" if p.get("side") == "Buy" else "SELL"
            created = int(p.get("createdTime") or 0)
            out.append(
                Position(
                    ticket=sym,
                    side=side,
                    symbol=sym,
                    lot=size,
                    entry_price=float(p.get("avgPrice") or 0.0),
                    sl=float(p.get("stopLoss") or 0.0),
                    tp=float(p.get("takeProfit") or 0.0),
                    open_time=(
                        datetime.fromtimestamp(created / 1000, tz=timezone.utc)
                        if created else datetime.now(tz=timezone.utc)
                    ),
                    current_price=float(p.get("markPrice") or 0.0),
                    pnl=float(p.get("unrealisedPnl") or 0.0),
                )
            )
        return out

    # ------------------------------------------------------------------
    # pending (conditional) orders
    # ------------------------------------------------------------------
    def pending_orders(self) -> list[PendingOrder]:
        if not self.is_connected():
            return []
        try:
            r = self._session.get_open_orders(category=CATEGORY, settleCoin=SETTLE_COIN)
            rows = r.get("result", {}).get("list", [])
        except Exception as exc:
            log.debug(f"get_open_orders failed: {exc}")
            return []
        out: list[PendingOrder] = []
        for o in rows:
            trig = float(o.get("triggerPrice") or 0.0)
            if trig <= 0:
                continue  # only conditional/stop orders
            side = "BUY" if o.get("side") == "Buy" else "SELL"
            kind = "buy_stop" if side == "BUY" else "sell_stop"
            created = int(o.get("createdTime") or 0)
            out.append(
                PendingOrder(
                    ticket=str(o.get("orderId")),
                    side=side,
                    symbol=o.get("symbol"),
                    lot=float(o.get("qty") or 0.0),
                    sl=float(o.get("stopLoss") or 0.0),
                    tp=float(o.get("takeProfit") or 0.0),
                    trigger_price=trig,
                    order_type=kind,
                    placed_at=(
                        datetime.fromtimestamp(created / 1000, tz=timezone.utc)
                        if created else datetime.now(tz=timezone.utc)
                    ),
                    comment=o.get("orderLinkId", ""),
                )
            )
        return out

    def cancel_pending(self, ticket: str) -> bool:
        if not self.is_connected():
            return False
        # ticket is an orderId; we need the symbol – look it up in open orders
        for o in self.pending_orders():
            if o.ticket == ticket:
                try:
                    r = self._session.cancel_order(
                        category=CATEGORY, symbol=o.symbol, orderId=ticket
                    )
                    return r.get("retCode") == 0
                except Exception as exc:
                    log.debug(f"cancel_order failed: {exc}")
                    return False
        return False

    # ------------------------------------------------------------------
    # realised pnl (for journal reconcile)
    # ------------------------------------------------------------------
    def realised_pnl(self, symbol: str) -> tuple[float, float]:
        """Return (last_exit_price, realised_pnl) for the most recent close."""
        if not self.is_connected():
            return 0.0, 0.0
        try:
            r = self._session.get_closed_pnl(category=CATEGORY, symbol=symbol, limit=1)
            rows = r.get("result", {}).get("list", [])
            if rows:
                row = rows[0]
                return float(row.get("avgExitPrice") or 0.0), float(row.get("closedPnl") or 0.0)
        except Exception as exc:
            log.debug(f"get_closed_pnl({symbol}) failed: {exc}")
        return 0.0, 0.0

    # ------------------------------------------------------------------
    # symbol management
    # ------------------------------------------------------------------
    def is_market_open(self, symbol: str) -> bool:
        # Crypto perps trade 24/7.
        return True

    def set_symbol(self, symbol: str) -> bool:
        meta = self._instrument(symbol)
        self.broker_lot_step = meta["qty_step"]
        self.broker_min_lot = meta["min_qty"]
        self.broker_max_lot = meta["max_qty"]
        self.broker_point = meta["tick_size"]
        return True


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _decimals(step: float) -> int:
    """Number of decimal places implied by a step/tick size (e.g. 0.001 → 3)."""
    s = f"{step:.10f}".rstrip("0")
    if "." in s:
        return len(s.split(".")[1])
    return 0


def _fmt(value: float, decimals: int) -> str:
    """Format a number to a fixed decimal count (Bybit wants strings)."""
    return f"{value:.{decimals}f}"
