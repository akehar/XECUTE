"""Multi-leg detection."""
from __future__ import annotations

import pytest

from app.parser.multileg import detect_multileg


@pytest.mark.parametrize(
    "text",
    [
        "BTO SPY 500/505 call spread 12/15 @ 1.50",
        "Selling SPY 500/495 put credit spread",
        "Iron condor on SPX this week",
        "SPY butterfly 495/500/505 calls",
        "Long strangle on TSLA earnings",
        "Diagonal AAPL 180/185 calls",
        "Calendar spread NVDA 500c",
        "Broken wing fly on QQQ",
        "Vertical SPY 500/510 calls 12/15",
        "AAPL 180c / 185c spread",
        "TSLA 220-225 calls",
    ],
)
def test_multileg_detected(text: str) -> None:
    is_ml, reason = detect_multileg(text)
    assert is_ml, f"should be multi-leg: {text!r} reason={reason!r}"
    assert reason


@pytest.mark.parametrize(
    "text",
    [
        "BTO SPY 500c 12/15 @ 2.50",
        "Got AAPL 180p 1/19 @ 1.20",
        "STC TSLA 220c @ 3.50",
        "SPY 500 calls 0DTE @ 1.10",
        "NVDA 500p tomorrow @ 5.00",
        "loading QQQ 400c next friday",
    ],
)
def test_single_leg_not_flagged(text: str) -> None:
    is_ml, reason = detect_multileg(text)
    assert not is_ml, f"should be single-leg: {text!r} reason={reason!r}"


def test_empty_text() -> None:
    assert detect_multileg("") == (False, "")
