"""
BYBIT CRYPTO BREAKOUT BOT – Typer CLI entry-point.

Multi-symbol scanner over the top-30 Bybit USDT perpetuals (demo trading).

Examples
--------
    python main.py start                 # start scanner + live dashboard (demo)
    python main.py start --paper         # force synthetic paper mode
    python main.py start --live          # force REAL account
    python main.py start --no-dashboard  # headless loop
    python main.py status
    python main.py dashboard
    python main.py universe               # show the trading universe
    python main.py demo-mode | live-mode | paper-mode
    python main.py reconcile
    python main.py winrate
    python main.py wipe-journal
    python main.py test-alerts
    python main.py emergency-stop
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from utils.logger import setup_logging

setup_logging()

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="[bold yellow]BYBIT CRYPTO BREAKOUT BOT[/bold yellow] – top-30 USDT-perp scanner",
)
console = Console()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _banner() -> None:
    art = r"""
  ____  _   _ ____ ___ _____    ____ ____  _   _ ____ _____ ___
 | __ )| | | | __ )_ _|_   _|  / ___|  _ \| | | |  _ \_   _/ _ \
 |  _ \| |_| |  _ \| |  | |   | |   | |_) | | | | |_) || || | | |
 | |_) |  _  | |_) | |  | |   | |___|  _ <| |_| |  __/ | || |_| |
 |____/|_| |_|____/___| |_|    \____|_| \_\\___/|_|    |_| \___/

        BYBIT CRYPTO BREAKOUT BOT  –  top-30 USDT-perp scanner
"""
    console.print(Panel.fit(f"[bold yellow]{art}[/bold yellow]", border_style="bright_yellow"))


def _mode_from_flags(paper: bool, demo: bool, live: bool) -> Optional[str]:
    chosen = [m for m, f in (("paper", paper), ("demo", demo), ("live", live)) if f]
    if len(chosen) > 1:
        console.print("[red]--paper / --demo / --live are mutually exclusive[/red]")
        raise typer.Exit(2)
    return chosen[0] if chosen else None


def _set_env(key: str, value: str) -> None:
    env_path = Path(".env")
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value


def _run_with_dashboard(mode: Optional[str]) -> None:
    from core import BotEngine
    from dashboard import LiveDashboard
    from config import settings as _settings

    engine = BotEngine(mode=mode)
    engine.start()
    if not engine.running:
        console.print("[red]engine failed to start[/red]")
        raise typer.Exit(1)

    interval = float(_settings.bot.get("refresh_seconds", 6))

    def _loop():
        try:
            while engine.running:
                engine.tick()
                time.sleep(interval)
        except Exception as exc:
            console.print(f"[red]engine crashed: {exc}[/red]")
            engine.stop()

    threading.Thread(target=_loop, daemon=True).start()
    try:
        LiveDashboard(engine).run()
    finally:
        engine.stop()


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
@app.command()
def start(
    paper: bool = typer.Option(False, "--paper", help="Force synthetic paper mode"),
    demo: bool = typer.Option(False, "--demo", help="Force Bybit demo trading"),
    live: bool = typer.Option(False, "--live", help="Force REAL account"),
    no_dashboard: bool = typer.Option(False, help="Run without the Rich dashboard"),
) -> None:
    """Start the scanner loop (with live dashboard by default)."""
    _banner()
    mode = _mode_from_flags(paper, demo, live)
    if no_dashboard:
        from core import BotEngine
        BotEngine(mode=mode).run_forever()
        return
    _run_with_dashboard(mode)


@app.command()
def dashboard() -> None:
    """Launch the live dashboard with the scanner."""
    _banner()
    _run_with_dashboard(None)


@app.command()
def stop() -> None:
    """Place a stop signal file."""
    Path(".engine_stop").touch()
    console.print("[yellow]stop signal written (.engine_stop)[/yellow]")


@app.command()
def status() -> None:
    """Show current configuration + last DB state."""
    from config import settings
    from database import TradeJournal

    # Live wallet balance for demo/live; configured CAPITAL for paper.
    capital_str = f"{settings.capital} {settings.base_currency} (configured)"
    if settings.mode in ("demo", "live"):
        try:
            from execution.bybit_broker import BybitBroker
            b = BybitBroker()
            if b.connect():
                acct = b.account_info() or {}
                bal = float(acct.get("balance") or 0.0)
                eq = float(acct.get("equity") or 0.0)
                capital_str = f"{bal:,.2f} {settings.base_currency} wallet  |  equity {eq:,.2f} (live)"
                b.disconnect()
        except Exception:
            pass

    tbl = Table(title="Configuration", show_header=False)
    tbl.add_column(style="cyan", no_wrap=True)
    tbl.add_column()
    tbl.add_row("mode", settings.mode)
    tbl.add_row("base currency", settings.base_currency)
    tbl.add_row("capital", capital_str)
    tbl.add_row("leverage", f"{settings.bybit_leverage}x")
    tbl.add_row("risk%/trade", str(settings.risk_per_trade))
    tbl.add_row("max concurrent", str(settings.risk.get("max_concurrent_trades", 5)))
    tbl.add_row("universe", f"top {settings.universe.get('count', 30)} "
                            f"({'auto' if settings.universe.get('auto_top30') else 'static'})")
    tbl.add_row("strategy", settings.strategies.get("active", "trendline_breakout"))
    console.print(tbl)

    j = TradeJournal()
    console.print(
        Panel(
            f"Trades today: [bold]{j.trades_today()}[/bold]\n"
            f"Daily PnL:   [bold]{j.daily_pnl():+.2f}[/bold]\n"
            f"Win rate:    [bold]{j.win_rate():.1f}%[/bold]",
            title="Journal",
        )
    )


@app.command()
def universe(
    live_top: bool = typer.Option(False, "--live", help="Query Bybit for the live top-30 by turnover"),
) -> None:
    """Show the trading universe (static list, or live top-30 with --live)."""
    from config import settings

    syms = list(settings.universe.get("symbols", []) or [])
    source = "static config list"
    if live_top:
        from execution.bybit_broker import BybitBroker
        b = BybitBroker()
        if b.connect():
            exclude = set(settings.universe.get("exclude", []) or [])
            top = b.top_symbols_by_turnover(int(settings.universe.get("count", 30)), exclude=exclude)
            if top:
                syms, source = top, "live Bybit top-30 by 24h turnover"
            b.disconnect()
        else:
            console.print("[red]could not connect to Bybit – showing static list[/red]")

    tbl = Table(title=f"Universe – {source}  ({len(syms)} symbols)")
    tbl.add_column("#", justify="right", style="dim")
    tbl.add_column("Symbol", style="cyan")
    for i, s in enumerate(syms, 1):
        tbl.add_row(str(i), s)
    console.print(tbl)


@app.command()
def symbol(
    new: str = typer.Argument(None, help="Set the default FOCUS symbol shown on the chart (e.g. ETHUSDT)."),
) -> None:
    """View or set the default focus symbol (the scanner still trades all 30)."""
    from config import settings as _settings

    if new is None:
        console.print(f"[cyan]Focus symbol[/cyan]: [bold]{_settings.symbol}[/bold]")
        return
    _set_env("SYMBOL", new.upper())
    console.print(f"[green]focus SYMBOL set to {new.upper()}[/green] – restart to apply.")


@app.command("paper-mode")
def paper_mode() -> None:
    """Switch the persisted MODE env to 'paper' (synthetic)."""
    _set_env("MODE", "paper")
    console.print("[green]MODE set to paper[/green]")


@app.command("demo-mode")
def demo_mode() -> None:
    """Switch the persisted MODE env to 'demo' (Bybit demo trading)."""
    _set_env("MODE", "demo")
    console.print("[cyan]MODE set to demo[/cyan]")


@app.command("live-mode")
def live_mode() -> None:
    """Switch the persisted MODE env to 'live' (REAL account)."""
    if not typer.confirm("Switch to LIVE trading? Real money at risk."):
        raise typer.Exit()
    _set_env("MODE", "live")
    console.print("[red]MODE set to live[/red]")


@app.command("wipe-journal")
def wipe_journal(
    confirm: bool = typer.Option(False, "--yes", help="skip interactive confirmation"),
) -> None:
    """Delete ALL trades + signals from the SQLite journal."""
    from database.models import get_session, Trade, Signal

    if not confirm:
        if not typer.confirm("This will permanently delete ALL trade and signal rows. Proceed?"):
            raise typer.Exit()
    with get_session() as s:
        t_count = s.query(Trade).delete()
        sig_count = s.query(Signal).delete()
        s.commit()
    console.print(f"[green]journal wiped[/green] – removed {t_count} trades, {sig_count} signals")


@app.command()
def reconcile() -> None:
    """Force-sync the trade journal with the broker."""
    from core import BotEngine

    engine = BotEngine()
    if not engine.broker.connect():
        console.print("[red]could not connect broker[/red]")
        raise typer.Exit(1)
    before = len(engine.journal.open_trades())
    engine._reconcile_closed_trades()
    after = len(engine.journal.open_trades())
    engine.broker.disconnect()
    console.print(
        f"[green]reconciled[/green] – journal open before={before} "
        f"after={after}  (closed {before - after} stale entries)"
    )


@app.command()
def winrate(
    since: str = typer.Option("today", help="today | week | all"),
    tf: str = typer.Option(None, help="filter by TF: M5 / M15 / all"),
) -> None:
    """Show win rate broken down by entry timeframe (parsed from each trade's reason)."""
    import re
    from datetime import datetime, timedelta
    from database.models import get_session, Trade
    from rich.text import Text

    now = datetime.utcnow()
    if since == "today":
        start = datetime.combine(now.date(), datetime.min.time())
        window_label = f"today ({start.strftime('%Y-%m-%d')} UTC -> now)"
    elif since == "week":
        start = now - timedelta(days=7)
        window_label = "last 7 days"
    elif since == "all":
        start = datetime(2000, 1, 1)
        window_label = "all time"
    else:
        console.print(f"[red]unknown --since value: {since}[/red]")
        raise typer.Exit(2)

    with get_session() as s:
        trades = list(
            s.query(Trade)
            .filter(Trade.open_time >= start, Trade.status == "closed")
            .order_by(Trade.open_time)
            .all()
        )

    if not trades:
        console.print(f"[yellow]No closed trades in window: {window_label}[/yellow]")
        return

    buckets: dict[str, list] = {"M5": [], "M15": [], "unknown": []}
    pattern = re.compile(r"\[(M\d+)\]")
    for t in trades:
        m = pattern.search(t.reason or "")
        key = m.group(1) if m else "unknown"
        buckets.setdefault(key, []).append(t)

    if tf:
        buckets = {tf: buckets.get(tf, [])}

    tbl = Table(title=f"Win Rate Report  -  {window_label}")
    for col, kw in (("TF", {"style": "cyan"}), ("Trades", {"justify": "right"}),
                    ("Wins", {"justify": "right", "style": "green"}),
                    ("Loss", {"justify": "right", "style": "red"}),
                    ("Win %", {"justify": "right"}), ("Total PnL", {"justify": "right"}),
                    ("Avg PnL", {"justify": "right"}), ("Best", {"justify": "right"}),
                    ("Worst", {"justify": "right"})):
        tbl.add_column(col, **kw)

    total_trades = total_wins = total_losses = 0
    total_pnl = 0.0
    best_overall, worst_overall = -1e18, 1e18

    for tf_name in sorted(buckets.keys()):
        rows = buckets[tf_name]
        if not rows:
            continue
        wins = sum(1 for r in rows if r.pnl > 0)
        losses = sum(1 for r in rows if r.pnl <= 0)
        total = len(rows)
        win_rate = wins * 100.0 / total if total else 0.0
        pnl = sum(r.pnl for r in rows)
        avg = pnl / total if total else 0.0
        best = max(r.pnl for r in rows)
        worst = min(r.pnl for r in rows)
        wr_color = "green" if win_rate >= 50 else ("yellow" if win_rate >= 30 else "red")
        pnl_color = "green" if pnl >= 0 else "red"
        tbl.add_row(tf_name, str(total), str(wins), str(losses),
                    Text(f"{win_rate:.1f}%", style=f"bold {wr_color}"),
                    Text(f"{pnl:+.2f}", style=f"bold {pnl_color}"),
                    f"{avg:+.2f}", f"{best:+.2f}", f"{worst:+.2f}")
        total_trades += total; total_wins += wins; total_losses += losses
        total_pnl += pnl
        best_overall = max(best_overall, best); worst_overall = min(worst_overall, worst)

    if total_trades:
        tbl.add_section()
        overall_wr = total_wins * 100.0 / total_trades
        wr_color = "green" if overall_wr >= 50 else ("yellow" if overall_wr >= 30 else "red")
        pnl_color = "green" if total_pnl >= 0 else "red"
        tbl.add_row(Text("TOTAL", style="bold"), Text(str(total_trades), style="bold"),
                    Text(str(total_wins), style="bold green"), Text(str(total_losses), style="bold red"),
                    Text(f"{overall_wr:.1f}%", style=f"bold {wr_color}"),
                    Text(f"{total_pnl:+.2f}", style=f"bold {pnl_color}"),
                    Text(f"{total_pnl/total_trades:+.2f}", style="bold"),
                    Text(f"{best_overall:+.2f}", style="bold green"),
                    Text(f"{worst_overall:+.2f}", style="bold red"))

    console.print(tbl)


@app.command("test-alerts")
def test_alerts() -> None:
    """Send a test message to Telegram + Discord using current .env."""
    from config import settings
    from utils.alerts import AlertManager

    am = AlertManager()
    if not (am.telegram_token and am.telegram_chat) and not am.discord_webhook:
        console.print(
            "[red]No alert channels configured.[/red]\n"
            "Set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID and/or DISCORD_WEBHOOK_URL in .env"
        )
        raise typer.Exit(1)

    console.print("[yellow]Sending test alert...[/yellow]")
    am.send(
        f"✅ <b>BYBIT CRYPTO BREAKOUT BOT</b>\n"
        f"Test alert. Mode: {settings.mode} | "
        f"Universe: top {settings.universe.get('count', 30)} USDT perps"
    )
    console.print(
        f"[green]Sent →[/green] "
        f"Telegram: {'✓' if am.telegram_token and am.telegram_chat else '✗'}   "
        f"Discord: {'✓' if am.discord_webhook else '✗'}"
    )


@app.command("emergency-stop")
def emergency_stop() -> None:
    """Close all open positions immediately and write a kill-switch file."""
    from core import BotEngine

    engine = BotEngine()
    if not engine.broker.connect():
        console.print("[red]could not connect broker[/red]")
        raise typer.Exit(1)
    closed = 0
    for p in engine.broker.open_positions():
        if engine.broker.close_position(p.ticket):
            closed += 1
    engine.broker.disconnect()
    Path(".kill_switch").write_text("KILLED")
    console.print(f"[red]emergency stop: closed {closed} positions[/red]")


if __name__ == "__main__":
    app()
