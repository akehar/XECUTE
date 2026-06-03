"""Regex-driven parser for the common Discord signal shapes.

Approach: extract each field independently (action, ticker, strike+right, expiry, price) with
per-field confidence, then assemble. Anything ambiguous returns None so the LLM fallback can try.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.parser.expiry import parse_expiry
from app.parser.multileg import detect_multileg
from app.parser.parse_result import ParseResult
from app.shared.enums import OptionRight, SignalAction, SignalSource
from app.shared.models import Signal

# Reserved tokens that should never be parsed as a ticker.
_TICKER_BLOCKLIST = {
    # Order-action verbs (covers every key in _ACTION_MAP plus surface variants)
    "BTO", "STC", "STO", "BTC",
    "BUY", "BUYING", "BOUGHT", "GOT", "FILLED", "GRABBED",
    "LONG", "LOADING", "OPENED", "ENTRY",
    "SELL", "SELLING", "SOLD",
    "CLOSE", "CLOSING", "CLOSED",
    "TRIM", "TRIMMING", "TRIMMED", "OUT",
    "ADD", "ADDED", "ADDING", "ADDS",
    "PICKED", "JUST",
    # Option / market jargon
    "DTE", "ATM", "ITM", "OTM", "IV", "PT", "EOD", "EOW", "MOC", "RTH",
    "PM", "AM", "ET", "EST", "PST",
    "CALL", "CALLS", "PUT", "PUTS",
    # Connectors / fillers
    "AT", "FOR", "THE", "AND", "OR", "IN", "ON", "OF", "TO", "TOO", "BY", "UP",
    "IS", "IT", "AS", "BE", "WE", "MY", "ME", "DO", "GO", "SO", "NO", "IF",
    "A", "I", "AN",
    "WITH", "FROM", "THIS", "THAT", "WHEN", "JUST", "ABOUT", "AROUND", "NEAR",
    "MAYBE", "YOLO", "BIG", "MAY", "FREE", "USA",
    "HALF", "ALL", "SOME", "FEW",
    "TODAY", "TMRW", "TMR", "TOMORROW",
    "EXP", "EXPIRY",
}

_ACTION_MAP: dict[str, SignalAction] = {
    "BTO": SignalAction.BTO,
    "BUY": SignalAction.BTO,
    "BUYING": SignalAction.BTO,
    "BOUGHT": SignalAction.BTO,
    "GOT": SignalAction.BTO,
    "FILLED": SignalAction.BTO,
    "GRABBED": SignalAction.BTO,
    "LONG": SignalAction.BTO,
    "LOADING": SignalAction.BTO,
    "OPENED": SignalAction.BTO,
    "ENTRY": SignalAction.BTO,
    "STC": SignalAction.STC,
    "SELL": SignalAction.STC,
    "SELLING": SignalAction.STC,
    "SOLD": SignalAction.STC,
    "CLOSING": SignalAction.STC,
    "CLOSE": SignalAction.STC,
    "CLOSED": SignalAction.STC,
    "TRIM": SignalAction.STC,
    "TRIMMING": SignalAction.STC,
    "TRIMMED": SignalAction.STC,
    "OUT": SignalAction.STC,
    "STO": SignalAction.STO,
    "BTC": SignalAction.BTC,
    "ADD": SignalAction.BTO_ADD,
    "ADDED": SignalAction.BTO_ADD,
    "ADDING": SignalAction.BTO_ADD,
    "ADDS": SignalAction.BTO_ADD,
}

_ACTION_RE = re.compile(
    r"(?<![A-Za-z])(" + "|".join(sorted(_ACTION_MAP.keys(), key=len, reverse=True)) + r")(?![A-Za-z])",
    re.IGNORECASE,
)

# Strike-right token: 500c, 500 calls, $500c, 499.50p. The leading lookbehind
# prevents "19 calls" inside "6/19 calls" from being parsed as strike=19.
_CONTRACT_RE = re.compile(
    r"""
    (?<![\d./-])
    \$?
    (?<![\d./-])
    (?P<strike>\d{1,5}(?:\.\d{1,2})?)
    \s*
    (?P<right>calls?|puts?|[cCpP])
    (?![A-Za-z0-9])
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Inverted "calls/puts 500" form, e.g. "SPY 12/15 500 calls"
_CONTRACT_INVERTED_RE = re.compile(
    r"""
    \b
    (?P<right>calls?|puts?)
    \s+
    (?:at|@)?\s*\$?\s*
    (?P<strike>\d{1,5}(?:\.\d{1,2})?)
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_TICKER_DOLLAR_RE = re.compile(r"\$([A-Za-z]{1,5})\b")
_TICKER_BARE_RE = re.compile(r"\b([A-Za-z]{1,5})\b")

# Price: @, at, for, filled, fill, around, near, "@$2.50"
_PRICE_RE = re.compile(
    r"""
    (?:@|\bat\b|\bfor\b|\bfilled?\b|\baround\b|\bnear\b|\bavg\b|\bcost\b)
    \s*\$?
    (?P<price>\d+(?:\.\d{1,4})?)
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Price-only $X.XX form as last resort
_DOLLAR_PRICE_RE = re.compile(r"\$(\d+(?:\.\d{1,4})?)(?![cCpP\d])")


def _normalize_right(token: str) -> OptionRight:
    t = token.strip().lower()
    return OptionRight.CALL if t.startswith("c") else OptionRight.PUT


def _extract_action(text: str) -> tuple[SignalAction | None, float]:
    m = _ACTION_RE.search(text)
    if not m:
        return None, 0.0
    raw = m.group(1).upper()
    return _ACTION_MAP[raw], 0.99


def _extract_contract(text: str) -> tuple[float, OptionRight, tuple[int, int]] | None:
    """Return (strike, right, span) or None. Span is used to chop out the contract token
    so the leftover doesn't get mistaken for a price later."""
    m = _CONTRACT_RE.search(text)
    if m:
        return float(m.group("strike")), _normalize_right(m.group("right")), m.span()
    m = _CONTRACT_INVERTED_RE.search(text)
    if m:
        return float(m.group("strike")), _normalize_right(m.group("right")), m.span()
    return None


def _extract_ticker(text: str, contract_span: tuple[int, int] | None) -> tuple[str | None, float]:
    m = _TICKER_DOLLAR_RE.search(text)
    if m:
        return m.group(1).upper(), 0.99
    # Bare uppercase token not in blocklist; prefer one before the contract span if present.
    candidates: list[tuple[str, int]] = []
    for bm in _TICKER_BARE_RE.finditer(text):
        token = bm.group(1).upper()
        if token in _TICKER_BLOCKLIST:
            continue
        if not token.isalpha():
            continue
        if contract_span and contract_span[0] <= bm.start() <= contract_span[1]:
            continue
        candidates.append((token, bm.start()))
    if not candidates:
        return None, 0.0
    if contract_span:
        before = [c for c in candidates if c[1] < contract_span[0]]
        if before:
            return before[-1][0], 0.85
    return candidates[0][0], 0.7


def _extract_price(text: str, contract_span: tuple[int, int] | None) -> tuple[float | None, float]:
    masked = text
    if contract_span:
        # Replace the contract token with spaces so its strike isn't matched as a price.
        s, e = contract_span
        masked = text[:s] + (" " * (e - s)) + text[e:]
    m = _PRICE_RE.search(masked)
    if m:
        return float(m.group("price")), 0.95
    m2 = _DOLLAR_PRICE_RE.search(masked)
    if m2:
        return float(m2.group(1)), 0.8
    return None, 0.0


def _extract_expiry(text: str, today: date | None = None) -> tuple[date | None, float]:
    d = parse_expiry(text, today=today)
    if d is None:
        return None, 0.0
    return d, 0.92


def parse_text_regex(
    text: str,
    *,
    source: SignalSource = SignalSource.DISCORD,
    today: date | None = None,
    default_expiry_today: bool = False,
) -> ParseResult:
    """Run the regex pipeline. Returns a ParseResult; missing fields mean the LLM must try."""
    raw = text.strip()
    if not raw:
        return ParseResult(source="rejected", reason="empty", raw_text=raw)

    multileg, ml_reason = detect_multileg(raw)
    if multileg:
        return ParseResult(
            source="rejected",
            reason=f"multi-leg: {ml_reason}",
            raw_text=raw,
            multileg=True,
        )

    action, action_conf = _extract_action(raw)
    contract = _extract_contract(raw)
    if contract is None:
        return ParseResult(
            source="rejected",
            reason="no strike/right token found",
            raw_text=raw,
            confidence=0.0,
        )
    strike, right, contract_span = contract

    ticker, ticker_conf = _extract_ticker(raw, contract_span)
    price, price_conf = _extract_price(raw, contract_span)
    expiry, expiry_conf = _extract_expiry(raw, today=today)

    field_conf: dict[str, float] = {
        "action": action_conf,
        "ticker": ticker_conf,
        "strike": 0.99,
        "right": 0.99,
        "price": price_conf,
        "expiry": expiry_conf,
    }

    if ticker is None:
        return ParseResult(
            source="rejected",
            reason="ticker not found",
            raw_text=raw,
            field_confidence=field_conf,
        )

    # Exits/closes don't always carry a price or expiry in the message; we still want a Signal
    # downstream so the executor can match it against the open position.
    is_exit = action in (SignalAction.STC, SignalAction.BTC)

    if not is_exit and price is None:
        return ParseResult(
            source="rejected",
            reason="price not found",
            raw_text=raw,
            field_confidence=field_conf,
        )
    if expiry is None:
        # Some channels use the convention "no expiry stated = 0DTE". When the caller
        # sets default_expiry_today, fall back to today rather than reject.
        if default_expiry_today:
            expiry = today or date.today()
            field_conf["expiry"] = 0.9
        else:
            return ParseResult(
                source="rejected",
                reason="expiry not found",
                raw_text=raw,
                field_confidence=field_conf,
            )

    # Default to BTO if action absent but everything else is present (slightly lower confidence).
    if action is None:
        action = SignalAction.BTO
        field_conf["action"] = 0.88

    # For exits without price, use a placeholder; downstream exit logic will price at market.
    effective_price = price if price is not None else 0.01
    if is_exit and price is None:
        field_conf["price"] = 0.5

    try:
        signal = Signal(
            source=source,
            action=action,
            ticker=ticker,
            strike=strike,
            right=right,
            expiry=expiry,
            price=effective_price,
            raw_text=raw,
        )
    except Exception as exc:  # pydantic ValidationError or value error
        return ParseResult(
            source="rejected",
            reason=f"validation: {exc}",
            raw_text=raw,
            field_confidence=field_conf,
        )

    # Missing price on an exit is acceptable; don't let its low confidence drag the overall down.
    if is_exit and price is None:
        relevant = [v for k, v in field_conf.items() if k != "price"]
    else:
        relevant = list(field_conf.values())
    overall = min(relevant) if relevant else 0.0
    return ParseResult(
        signal=signal,
        source="regex",
        confidence=overall,
        field_confidence=field_conf,
        raw_text=raw,
    )
