from __future__ import annotations

import re
from datetime import date, datetime, timedelta

_DTE_RE = re.compile(r"(?P<n>\d+)\s*DTE", re.IGNORECASE)
_PLUS_RE = re.compile(r"\+\s*(?P<n>\d+)\s*(?P<unit>[dwDW])\b")
_ISO_RE = re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b")
_MDY_RE = re.compile(r"\b(?P<m>\d{1,2})/(?P<d>\d{1,2})(?:/(?P<y>\d{2,4}))?\b")

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "mon": 0,
    "tue": 1,
    "tues": 1,
    "wed": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "fri": 4,
}


def parse_expiry(text: str, today: date | None = None) -> date | None:
    """Best-effort expiry extraction. Returns None when ambiguous; let the LLM handle that."""
    if not text:
        return None
    today = today or date.today()

    m = _DTE_RE.search(text)
    if m:
        return today + timedelta(days=int(m.group("n")))

    m = _PLUS_RE.search(text)
    if m:
        n = int(m.group("n"))
        unit = m.group("unit").lower()
        days = n * 7 if unit == "w" else n
        return today + timedelta(days=days)

    m = _ISO_RE.search(text)
    if m:
        try:
            return date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
        except ValueError:
            return None

    lowered = text.lower()
    if re.search(r"\btoday\b", lowered):
        return today
    if re.search(r"\btomorrow\b|\btmrw\b|\btmr\b", lowered):
        return today + timedelta(days=1)

    for word, target in _WEEKDAYS.items():
        if re.search(rf"\b(this\s+)?{word}\b", lowered):
            delta = (target - today.weekday()) % 7
            if delta == 0:
                delta = 7
            base_date = today + timedelta(days=delta)
            if re.search(rf"\bnext\s+{word}\b", lowered):
                base_date = base_date + timedelta(days=7)
            return base_date

    m = _MDY_RE.search(text)
    if m:
        month = int(m.group("m"))
        day = int(m.group("d"))
        yr_raw = m.group("y")
        if yr_raw:
            year = int(yr_raw)
            if year < 100:
                year += 2000
        else:
            year = today.year
            try:
                tentative = date(year, month, day)
            except ValueError:
                return None
            if tentative < today:
                year += 1
        try:
            return date(year, month, day)
        except ValueError:
            return None

    return None
