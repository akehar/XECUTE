"""Expiry parsing."""
from __future__ import annotations

from datetime import date, timedelta

from app.parser.expiry import parse_expiry


def test_dte() -> None:
    today = date(2026, 5, 22)  # Friday
    assert parse_expiry("BTO SPY 500c 0DTE @ 1.10", today=today) == today
    assert parse_expiry("SPY 500c 1DTE", today=today) == today + timedelta(days=1)


def test_plus_days_and_weeks() -> None:
    today = date(2026, 5, 22)
    assert parse_expiry("SPY 500c +3d @ 2", today=today) == today + timedelta(days=3)
    assert parse_expiry("SPY 500c +2w @ 2", today=today) == today + timedelta(days=14)


def test_iso_date() -> None:
    today = date(2026, 5, 22)
    assert parse_expiry("SPY 500c exp 2026-06-19 @ 2", today=today) == date(2026, 6, 19)


def test_mdy_no_year_assumes_current_then_next() -> None:
    today = date(2026, 5, 22)
    # 6/19 hasn't happened yet this year → 2026-06-19
    assert parse_expiry("SPY 500c 6/19 @ 2", today=today) == date(2026, 6, 19)
    # 1/15 already passed this year → 2027-01-15
    assert parse_expiry("SPY 500c 1/15 @ 2", today=today) == date(2027, 1, 15)


def test_mdy_with_two_digit_year() -> None:
    today = date(2026, 5, 22)
    assert parse_expiry("SPY 500c 12/15/26 @ 2", today=today) == date(2026, 12, 15)


def test_today_tomorrow() -> None:
    today = date(2026, 5, 22)
    assert parse_expiry("SPY 500c today @ 1", today=today) == today
    assert parse_expiry("SPY 500c tomorrow @ 1", today=today) == today + timedelta(days=1)
    assert parse_expiry("SPY 500c tmrw @ 1", today=today) == today + timedelta(days=1)


def test_this_friday_when_today_is_friday() -> None:
    today = date(2026, 5, 22)  # Friday
    # "this Friday" while today is Friday → next Friday (next occurrence)
    assert parse_expiry("SPY 500c this friday @ 1", today=today) == today + timedelta(days=7)


def test_next_friday() -> None:
    today = date(2026, 5, 19)  # Tuesday
    # this Friday = 2026-05-22; next Friday = 2026-05-29
    assert parse_expiry("SPY 500c next friday @ 1", today=today) == date(2026, 5, 29)


def test_none_when_no_expiry() -> None:
    today = date(2026, 5, 22)
    assert parse_expiry("STC SPY 500c", today=today) is None


def test_invalid_iso() -> None:
    today = date(2026, 5, 22)
    assert parse_expiry("SPY 500c 2026-13-40 @ 1", today=today) is None
