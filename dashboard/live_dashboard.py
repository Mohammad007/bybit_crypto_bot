"""
Live CLI dashboard for the Bybit Crypto Breakout scanner.

Panels:
    +----------------------------------------------------------+
    | Header (bot, universe, mode, broker, UTC)                |
    +------------------------------+---------------------------+
    | Live Chart (focus symbol)    | Account / PnL             |
    |                              +---------------------------+
    | Open Trades & Pending        | Scanner (top-30 signals)  |
    +----------------------------------------------------------+
    | Footer (scanned, risk, ping)                             |
    +----------------------------------------------------------+
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from rich.align import Align
from rich.console import Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from config import settings
from utils.helpers import fmt_money

from .render import render_candles_ascii


def _color(val: float) -> str:
    if val > 0:
        return "bold green"
    if val < 0:
        return "bold red"
    return "yellow"


def _sig_style(decision: str) -> str:
    return {"BUY": "bold green", "SELL": "bold red"}.get(decision, "dim")


class LiveDashboard:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.layout = self._make_layout()

    # ------------------------------------------------------------------
    def _make_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body", ratio=1),
            Layout(name="footer", size=3),
        )
        layout["body"].split_row(
            Layout(name="left", ratio=3),
            Layout(name="right", ratio=2),
        )
        layout["left"].split_column(
            Layout(name="chart", ratio=2),
            Layout(name="trades", ratio=1),
        )
        layout["right"].split_column(
            Layout(name="account", size=8),
            Layout(name="scan", ratio=1),
        )
        return layout

    # ------------------------------------------------------------------
    def _header(self, snap: dict[str, Any]) -> Panel:
        bot_name = settings.bot.get("name", "BYBIT CRYPTO BREAKOUT BOT")
        mode = snap.get("mode", settings.mode).upper()
        broker = snap.get("broker", "paper")
        connected = "✓" if snap.get("connected") else "✗"
        size = snap.get("universe_size", len(self.engine.symbols))
        title = Text()
        title.append(f"{bot_name} ", style="bold yellow")
        title.append(f"  Universe: top {size}", style="bold cyan")
        title.append("  ", style="dim")
        mode_style = "bold magenta" if mode == "LIVE" else ("bold cyan" if mode == "DEMO" else "bold green")
        title.append(f"Mode: {mode}  ", style=mode_style)
        title.append(f"Broker: {broker} [{connected}]  ", style="cyan")
        title.append(f"  UTC {datetime.now(tz=timezone.utc).strftime('%H:%M:%S')}", style="dim")
        return Panel(Align.center(title), border_style="bright_yellow")

    def _account(self, snap: dict[str, Any]) -> Panel:
        acct = snap.get("account", {})
        balance = float(acct.get("balance", 0.0))
        equity = float(acct.get("equity", 0.0))
        pnl_day = float(snap.get("daily_pnl", 0.0))
        win_rate = float(snap.get("win_rate", 0.0))
        trades_today = int(snap.get("trades_today", 0))
        open_n = len(snap.get("positions", []))
        sym = "$"

        tbl = Table.grid(padding=(0, 1))
        tbl.add_column(style="cyan", no_wrap=True)
        tbl.add_column()
        tbl.add_row("Balance", fmt_money(balance, sym))
        tbl.add_row("Equity", fmt_money(equity, sym))
        tbl.add_row("Daily PnL", Text(fmt_money(pnl_day, sym), style=_color(pnl_day)))
        tbl.add_row("Win Rate", Text(f"{win_rate:.1f}%", style="bold green" if win_rate >= 50 else "yellow"))
        tbl.add_row("Open / Today", f"{open_n} open · {trades_today} today")
        return Panel(tbl, title="[bold]Account / PnL (USDT)[/bold]", border_style="green")

    def _chart(self, snap: dict[str, Any]) -> Panel:
        df = snap.get("chart_df")
        focus = snap.get("focus_symbol", settings.symbol)
        candles = int(settings.dashboard.get("chart_candles", 60))
        chart = render_candles_ascii(df, height=14, width=candles) if df is not None else Text("no chart")

        price = snap.get("price", {})
        last = price.get("mid", 0.0)
        spread = price.get("spread_points", 0.0)
        sub = Text(f"{focus}   Last: {last:,.6g}   Spread: {spread:.0f}pts   TF: M15",
                   style="bold white")
        legend = Text()
        legend.append(" ─ ", style="bold cyan"); legend.append("EMA20  ", style="dim")
        legend.append(" ─ ", style="bold yellow"); legend.append("EMA50  ", style="dim")
        legend.append(" · ", style="bold bright_green"); legend.append("BUY trig  ", style="dim")
        legend.append(" · ", style="bold bright_red"); legend.append("SELL trig", style="dim")
        return Panel(Group(sub, legend, chart),
                     title="[bold]Focus Chart + Breakout Triggers[/bold]",
                     border_style="cyan")

    def _scan(self, snap: dict[str, Any]) -> Panel:
        rows = snap.get("scan", [])
        max_rows = int(settings.dashboard.get("scan_rows", 18))
        tbl = Table(show_header=True, header_style="bold magenta", expand=True)
        tbl.add_column("Symbol", no_wrap=True)
        tbl.add_column("Last", justify="right")
        tbl.add_column("24h%", justify="right")
        tbl.add_column("Signal", justify="center")
        tbl.add_column("Conf", justify="right")

        for r in rows[:max_rows]:
            chg = r.get("change24h", 0.0)
            held_mark = "● " if r.get("held") else ""
            tbl.add_row(
                f"{held_mark}{r['symbol']}",
                f"{r['last']:,.6g}",
                Text(f"{chg:+.2f}", style=_color(chg)),
                Text(r["decision"], style=_sig_style(r["decision"])),
                f"{r['confidence']:.0f}",
            )
        if not rows:
            tbl.add_row("scanning…", "—", "—", "—", "—")
        n = snap.get("scanned", 0)
        return Panel(tbl, title=f"[bold]Scanner — {n} symbols[/bold]  [dim](● = open)[/dim]",
                     border_style="magenta")

    def _trades(self, snap: dict[str, Any]) -> Panel:
        positions = snap.get("positions", [])
        pending = snap.get("pending", [])

        tbl = Table(show_header=True, header_style="bold magenta", expand=True)
        tbl.add_column("Symbol", no_wrap=True)
        tbl.add_column("Type", justify="center")
        tbl.add_column("Side", justify="center")
        tbl.add_column("Qty", justify="right")
        tbl.add_column("Entry/Trig", justify="right")
        tbl.add_column("SL", justify="right")
        tbl.add_column("TP", justify="right")
        tbl.add_column("PnL", justify="right")

        for p in positions:
            color = "green" if p["pnl"] >= 0 else "red"
            tbl.add_row(
                p["symbol"],
                Text("OPEN", style="bold green"),
                Text(p["side"], style="bold green" if p["side"] == "BUY" else "bold red"),
                f"{p['lot']:g}",
                f"{p['entry']:.6g}",
                f"{p['sl']:.6g}",
                f"{p['tp']:.6g}",
                Text(f"{p['pnl']:+.2f}", style=color),
            )
        for p in pending:
            tbl.add_row(
                p["symbol"],
                Text("PEND", style="bold yellow"),
                Text(p["side"], style="bold cyan"),
                f"{p['lot']:g}",
                Text(f"{p['trigger']:.6g}", style="bold yellow"),
                f"{p['sl']:.6g}",
                f"{p['tp']:.6g}",
                Text("waiting", style="dim"),
            )
        if not positions and not pending:
            tbl.add_row("—", "—", "—", "—", "—", "—", "—", "—")
        return Panel(tbl, title="[bold]Open Trades & Pending Orders[/bold]",
                     border_style="bright_blue")

    def _footer(self, snap: dict[str, Any]) -> Panel:
        risk_state = snap.get("risk_state", "OK")
        ping_ms = snap.get("broker_ping_ms", 0.0)
        scanned = snap.get("scanned", 0)
        line = Text()
        line.append("Market: 24/7 crypto   ", style="bold cyan")
        line.append(f"Scanned: {scanned}   ", style="bold yellow")
        line.append(f"Risk: {risk_state}   ", style="green" if "OK" in risk_state else "red")
        line.append(f"Scan time: {ping_ms:.0f}ms", style="dim")
        return Panel(line, border_style="bright_black")

    # ------------------------------------------------------------------
    def update(self, snap: dict[str, Any]) -> None:
        self.layout["header"].update(self._header(snap))
        self.layout["chart"].update(self._chart(snap))
        self.layout["trades"].update(self._trades(snap))
        self.layout["account"].update(self._account(snap))
        self.layout["scan"].update(self._scan(snap))
        self.layout["footer"].update(self._footer(snap))

    # ------------------------------------------------------------------
    def run(self) -> None:
        with Live(self.layout, refresh_per_second=2, screen=True) as live:
            while self.engine.running:
                snap = self.engine.snapshot()
                self.update(snap)
                live.refresh()
                time.sleep(0.5)
