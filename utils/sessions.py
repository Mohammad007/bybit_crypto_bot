"""Trading session helpers (Asia / London / New York + Kill Zones)."""
from __future__ import annotations

from datetime import datetime, time, timezone

from config import settings


def _hhmm_to_time(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def current_session(now: datetime | None = None) -> str:
    """Return one of: 'asia', 'london', 'new_york', 'overlap', 'off'."""
    now = (now or datetime.now(tz=timezone.utc)).time()
    sessions_cfg = settings.market.get("sessions", {})
    active: list[str] = []
    for name, rng in sessions_cfg.items():
        start = _hhmm_to_time(rng["start"])
        end = _hhmm_to_time(rng["end"])
        if start <= now <= end:
            active.append(name)
    if len(active) >= 2:
        return "overlap"
    if active:
        return active[0]
    return "off"


def in_kill_zone(now: datetime | None = None) -> str | None:
    """Return name of active kill zone, or None."""
    now = (now or datetime.now(tz=timezone.utc)).time()
    kz_cfg = settings.market.get("kill_zones", {})
    for name, rng in kz_cfg.items():
        if _hhmm_to_time(rng["start"]) <= now <= _hhmm_to_time(rng["end"]):
            return name
    return None
