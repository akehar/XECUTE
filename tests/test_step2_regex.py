"""Regex parser focused tests (no LLM fallback)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.parser.regex import parse_text_regex
from app.shared.enums import OptionRight, SignalAction


# Use real today so the Signal pydantic validator (which uses date.today()) agrees with parse_expiry.
TODAY = date.today()


def _future(days: int) -> date:
    return TODAY + timedelta(days=days)


def _mdy(d: date) -> str:
    return f"{d.month}/{d.day}"


def test_canonical_bto() -> None:
    exp = _future(28)
    r = parse_text_regex(f"BTO SPY 500c {_mdy(exp)} @ 2.50", today=TODAY)
    assert r.signal is not None, r.reason
    s = r.signal
    assert s.action == SignalAction.BTO
    assert s.ticker == "SPY"
    assert s.strike == 500.0
    assert s.right == OptionRight.CALL
    assert s.expiry == exp
    assert s.price == 2.50
    assert r.confidence >= 0.85


def test_dollar_prefix_ticker_and_price() -> None:
    exp = _future(25)
    r = parse_text_regex(f"BTO $AAPL 180p {_mdy(exp)} @ $1.20", today=TODAY)
    assert r.signal is not None, r.reason
    assert r.signal.ticker == "AAPL"
    assert r.signal.right == OptionRight.PUT
    assert r.signal.price == 1.20


def test_calls_word_form() -> None:
    exp = _future(28)
    r = parse_text_regex(f"Buying SPY 500 calls {_mdy(exp)} @ 2.50", today=TODAY)
    assert r.signal is not None, r.reason
    assert r.signal.action == SignalAction.BTO
    assert r.signal.right == OptionRight.CALL


def test_inverted_calls_strike() -> None:
    exp = _future(28)
    r = parse_text_regex(f"SPY {_mdy(exp)} calls 500 @ 2.50", today=TODAY)
    assert r.signal is not None, r.reason
    assert r.signal.strike == 500.0
    assert r.signal.right == OptionRight.CALL


def test_zero_dte() -> None:
    r = parse_text_regex("BTO SPY 500c 0DTE @ 1.10", today=TODAY)
    assert r.signal is not None, r.reason
    assert r.signal.expiry == TODAY


def test_stc_without_price() -> None:
    exp = _future(28)
    r = parse_text_regex(f"STC SPY 500c {_mdy(exp)}", today=TODAY)
    assert r.signal is not None, r.reason
    assert r.signal.action == SignalAction.STC


def test_add_action() -> None:
    exp = _future(28)
    r = parse_text_regex(f"Adding to SPY 500c {_mdy(exp)} @ 2.80", today=TODAY)
    assert r.signal is not None, r.reason
    assert r.signal.action == SignalAction.BTO_ADD


def test_implicit_bto_lower_confidence() -> None:
    exp = _future(28)
    r = parse_text_regex(f"SPY 500c {_mdy(exp)} @ 2.50", today=TODAY)
    assert r.signal is not None, r.reason
    assert r.signal.action == SignalAction.BTO
    assert r.field_confidence["action"] < 0.95


def test_missing_expiry_returns_reject() -> None:
    r = parse_text_regex("BTO SPY 500c @ 2.50", today=TODAY)
    assert r.signal is None
    assert "expiry" in r.reason


def test_missing_price_returns_reject_for_entry() -> None:
    exp = _future(28)
    r = parse_text_regex(f"BTO SPY 500c {_mdy(exp)}", today=TODAY)
    assert r.signal is None
    assert "price" in r.reason


def test_multileg_returns_reject() -> None:
    exp = _future(28)
    r = parse_text_regex(f"BTO SPY 500/505 call spread {_mdy(exp)} @ 1.50", today=TODAY)
    assert r.signal is None
    assert r.multileg
    assert "multi-leg" in r.reason


def test_decimal_strike() -> None:
    exp = _future(28)
    r = parse_text_regex(f"BTO SPX 4995.5c {_mdy(exp)} @ 12.00", today=TODAY)
    assert r.signal is not None, r.reason
    assert r.signal.strike == 4995.5


def test_lowercase_action_and_ticker() -> None:
    exp = _future(28)
    r = parse_text_regex(f"bto spy 500c {_mdy(exp)} @ 2.50", today=TODAY)
    assert r.signal is not None, r.reason
    assert r.signal.ticker == "SPY"


def test_price_keywords() -> None:
    exp = _future(28)
    for phrase in ["filled 2.50", "for 2.50", "around 2.50", "near 2.50", "@ 2.50", "at 2.50"]:
        r = parse_text_regex(f"BTO SPY 500c {_mdy(exp)} {phrase}", today=TODAY)
        assert r.signal is not None, f"failed on '{phrase}': {r.reason}"
        assert r.signal.price == 2.50


def test_expiry_too_far_validation_rejects() -> None:
    far = TODAY + timedelta(days=90)
    r = parse_text_regex(f"BTO SPY 500c {far.month}/{far.day}/{far.year % 100} @ 2.50", today=TODAY)
    assert r.signal is None
    assert "validation" in r.reason or "expiry" in r.reason


def test_ticker_blocklist_does_not_eat_keywords() -> None:
    exp = _future(28)
    r = parse_text_regex(f"BTO SPY 500c {_mdy(exp)} @ 2.50", today=TODAY)
    assert r.signal is not None, r.reason
    assert r.signal.ticker == "SPY"  # not "BTO", not "DTE"


def test_dual_strike_dash_rejected_as_multileg() -> None:
    """Verify the contract regex's lookbehind doesn't accidentally accept a multi-leg form."""
    r = parse_text_regex("BTO TSLA 220-225 calls 0DTE @ 1.50", today=TODAY)
    assert r.signal is None
    assert r.multileg
