"""
Standalone win-rate report.

This is a "live test" – it reads the SQLite journal and prints
today's stats per timeframe (M5 / M15).  Run it any time:

    python tests/test_winrate.py             # today
    python tests/test_winrate.py week        # last 7 days
    python tests/test_winrate.py all         # all-time

It is NOT auto-discovered by pytest (no `test_` prefix on functions).
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Allow this script to be run from anywhere
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.models import get_session, Trade        # noqa: E402


def _window(since: str) -> tuple[datetime, str]:
    now = datetime.utcnow()
    if since == "today":
        start = datetime.combine(now.date(), datetime.min.time())
        return start, f"today ({start.strftime('%Y-%m-%d')} UTC -> now)"
    if since == "week":
        return now - timedelta(days=7), "last 7 days"
    return datetime(2000, 1, 1), "all time"


def _bucket_by_tf(trades) -> dict[str, list]:
    pattern = re.compile(r"\[(M\d+)\]")
    buckets: dict[str, list] = {}
    for t in trades:
        m = pattern.search(t.reason or "")
        key = m.group(1) if m else "unknown"
        buckets.setdefault(key, []).append(t)
    return buckets


def _row(name: str, rows: list) -> str:
    if not rows:
        return ""
    wins = sum(1 for r in rows if r.pnl > 0)
    losses = sum(1 for r in rows if r.pnl <= 0)
    total = len(rows)
    win_rate = wins * 100.0 / total
    pnl = sum(r.pnl for r in rows)
    avg = pnl / total
    best = max(r.pnl for r in rows)
    worst = min(r.pnl for r in rows)
    return (
        f"{name:<8} | {total:>6} | {wins:>4} | {losses:>4} | "
        f"{win_rate:>6.1f}% | {pnl:+9.2f} | {avg:+7.2f} | "
        f"{best:+7.2f} | {worst:+7.2f}"
    )


def main(since: str = "today") -> None:
    start, label = _window(since)
    with get_session() as s:
        trades = list(
            s.query(Trade)
            .filter(Trade.open_time >= start, Trade.status == "closed")
            .order_by(Trade.open_time)
            .all()
        )

    print()
    print("=" * 92)
    print(f"  WIN-RATE REPORT  -  {label}")
    print("=" * 92)
    if not trades:
        print("  No closed trades in this window.")
        print("=" * 92)
        return

    print(f"  {'TF':<8} | {'Trades':>6} | {'Wins':>4} | {'Loss':>4} | "
          f"{'Win %':>7} | {'Total PnL':>9} | {'Avg':>7} | {'Best':>7} | {'Worst':>7}")
    print("-" * 92)

    buckets = _bucket_by_tf(trades)
    totals_all = []
    for tf_name in sorted(buckets.keys()):
        row = _row(tf_name, buckets[tf_name])
        if row:
            print("  " + row)
        totals_all.extend(buckets[tf_name])

    print("-" * 92)
    print("  " + _row("TOTAL", totals_all))
    print("=" * 92)
    print()


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "today"
    main(arg)
