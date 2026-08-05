"""Exchange-time clock. Everything date-sensitive (0DTE defaults, expiry
validation, daily caps, trading-hours windows) must use Eastern time, not the
server's local clock — the VPS runs UTC, which is a day ahead of New York
between 8pm ET and midnight ET.

Tests monkeypatch today_et / now_et here rather than freezing the whole clock.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def now_et() -> datetime:
    return datetime.now(ET)


def today_et() -> date:
    return now_et().date()
