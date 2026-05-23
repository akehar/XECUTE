from __future__ import annotations

import re

# Keywords that unambiguously indicate a multi-leg structure. Match must be word-bounded.
_MULTILEG_KEYWORDS = (
    "spread",
    "spreads",
    "credit spread",
    "debit spread",
    "vertical",
    "verticals",
    "iron condor",
    "condor",
    "butterfly",
    "fly",
    "strangle",
    "straddle",
    "calendar",
    "diagonal",
    "collar",
    "ratio spread",
    "broken wing",
)

_KEYWORD_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _MULTILEG_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# Explicit two-leg constructs. Slash-form ("500/505") is only flagged when one of the
# strikes has an attached c/p suffix; otherwise it collides with US date format M/D.
# Dash-form ("220-225 calls") is unambiguous since dates don't use dashes (ISO uses YYYY-MM-DD
# which doesn't appear next to a call/put keyword).
_DUAL_STRIKE_EXPLICIT_SLASH = re.compile(
    r"\b\d+(?:\.\d+)?\s*[cCpP]\s*[/]\s*\d+(?:\.\d+)?\s*[cCpP]?\b"
    r"|\b\d+(?:\.\d+)?\s*[/]\s*\d+(?:\.\d+)?\s*[cCpP]\b",
    re.IGNORECASE,
)
_DUAL_STRIKE_DASH = re.compile(
    r"\b\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s+(?:call|put|calls|puts)\b",
    re.IGNORECASE,
)


def detect_multileg(text: str) -> tuple[bool, str]:
    """Return (is_multileg, reason). Empty reason if single-leg."""
    if not text:
        return False, ""
    m = _KEYWORD_RE.search(text)
    if m:
        return True, f"multi-leg keyword: '{m.group(1).lower()}'"
    m2 = _DUAL_STRIKE_EXPLICIT_SLASH.search(text)
    if m2:
        return True, f"dual-strike construction: '{m2.group(0).strip()}'"
    m3 = _DUAL_STRIKE_DASH.search(text)
    if m3:
        return True, f"dual-strike construction: '{m3.group(0).strip()}'"
    return False, ""
