"""Tests for the specific signal-channel formats we're following.

Channel posts in two shapes:
  0DTE (no expiry stated):    META 630C @1.00
                              MSFT 462.50C @1.45
  Dated:                      MS 210C @2.25 05/06

For the 0DTE shape the parser needs default_expiry_today=True (set globally by
PARSER_DEFAULT_EXPIRY_TODAY=true in .env)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.parser.parser import parse_text
from app.parser.regex import parse_text_regex
from app.shared.enums import OptionRight, SignalAction


TODAY = date.today()


def _future_mdy(days: int) -> tuple[date, str]:
    d = TODAY + timedelta(days=days)
    return d, f"{d.month:02d}/{d.day:02d}"


class TestChannel0DTEFormat:
    def test_meta_call_no_expiry(self):
        r = parse_text("META 630C @1.00", today=TODAY, default_expiry_today=True)
        assert r.accepted, r.reason
        s = r.signal
        assert s.ticker == "META"
        assert s.strike == 630.0
        assert s.right == OptionRight.CALL
        assert s.action == SignalAction.BTO  # implicit
        assert s.expiry == TODAY  # 0DTE by channel convention
        assert s.price == 1.00

    def test_msft_decimal_strike_no_expiry(self):
        r = parse_text("MSFT 462.50C @1.45", today=TODAY, default_expiry_today=True)
        assert r.accepted, r.reason
        assert r.signal.ticker == "MSFT"
        assert r.signal.strike == 462.50
        assert r.signal.expiry == TODAY
        assert r.signal.price == 1.45

    def test_two_letter_ticker_no_expiry(self):
        # MS = Morgan Stanley
        r = parse_text("MS 210C @2.25", today=TODAY, default_expiry_today=True)
        assert r.accepted, r.reason
        assert r.signal.ticker == "MS"
        assert r.signal.strike == 210.0
        assert r.signal.expiry == TODAY

    def test_without_default_expiry_flag_rejects(self):
        # Same input, flag off: parser should reject for missing expiry.
        r = parse_text("META 630C @1.00", today=TODAY, default_expiry_today=False, llm_client=None)
        assert not r.accepted
        assert "expiry" in r.reason


class TestChannelDatedFormat:
    def test_dated_mdy(self):
        d, mdy = _future_mdy(days=14)
        r = parse_text(f"MS 210C @2.25 {mdy}", today=TODAY, default_expiry_today=True)
        assert r.accepted, r.reason
        assert r.signal.ticker == "MS"
        assert r.signal.strike == 210.0
        assert r.signal.expiry == d
        assert r.signal.price == 2.25

    def test_dated_overrides_default(self):
        # When an explicit date is present, default_expiry_today should NOT clobber it.
        d, mdy = _future_mdy(days=21)
        r = parse_text(f"META 630C @1.00 {mdy}", today=TODAY, default_expiry_today=True)
        assert r.accepted, r.reason
        assert r.signal.expiry == d
        assert r.signal.expiry != TODAY


class TestRegexLayerDirectly:
    """Verify the flag plumbs through parse_text_regex too (not just parse_text)."""

    def test_regex_with_flag_sets_today(self):
        r = parse_text_regex("META 630C @1.00", today=TODAY, default_expiry_today=True)
        assert r.signal is not None, r.reason
        assert r.signal.expiry == TODAY

    def test_regex_without_flag_rejects_no_expiry(self):
        r = parse_text_regex("META 630C @1.00", today=TODAY, default_expiry_today=False)
        assert r.signal is None
        assert "expiry" in r.reason
