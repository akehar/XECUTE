"""LLM fallback behaviour using a mock client."""
from __future__ import annotations

from datetime import date
from typing import Any

from app.parser.llm import FunctionLLMClient, extract_json
from app.parser.parser import parse_text
from app.shared.enums import OptionRight, SignalAction


TODAY = date(2026, 5, 22)


def _fake_llm(payload: dict[str, Any]):
    def _fn(text: str, ctx: str) -> dict[str, Any]:
        return payload
    return FunctionLLMClient(_fn)


def test_llm_invoked_when_regex_fails() -> None:
    payload = {
        "is_signal": True,
        "is_multileg": False,
        "action": "BTO",
        "ticker": "SPY",
        "strike": 500.0,
        "right": "C",
        "expiry": "2026-06-19",
        "price": 2.50,
        "stop": None,
        "target": None,
        "field_confidence": {
            "action": 0.95, "ticker": 0.99, "strike": 0.99,
            "right": 0.99, "expiry": 0.95, "price": 0.95,
        },
        "overall_confidence": 0.95,
    }
    # Prose-y text the regex will struggle with
    r = parse_text(
        "Picked up some SPY June 19th 500 strike calls a moment ago, paid two-fifty.",
        today=TODAY,
        llm_client=_fake_llm(payload),
        min_confidence=0.85,
    )
    assert r.accepted, r.reason
    assert r.source == "llm"
    assert r.signal.ticker == "SPY"
    assert r.signal.action == SignalAction.BTO
    assert r.signal.right == OptionRight.CALL
    assert r.signal.expiry == date(2026, 6, 19)
    assert r.signal.parse_confidence == 0.95


def test_llm_low_confidence_rejected() -> None:
    payload = {
        "is_signal": True,
        "is_multileg": False,
        "action": "BTO",
        "ticker": "SPY",
        "strike": 500.0,
        "right": "C",
        "expiry": "2026-06-19",
        "price": 2.50,
        "field_confidence": {},
        "overall_confidence": 0.70,
    }
    r = parse_text(
        "Maybe SPY 500 calls? Not sure.",
        today=TODAY,
        llm_client=_fake_llm(payload),
        min_confidence=0.85,
    )
    assert not r.accepted
    assert "confidence" in r.reason


def test_llm_marks_not_a_signal() -> None:
    payload = {
        "is_signal": False,
        "is_multileg": False,
        "action": None, "ticker": None, "strike": None,
        "right": None, "expiry": None, "price": None,
        "field_confidence": {}, "overall_confidence": 0.1,
    }
    r = parse_text(
        "Anyone catch that fed presser? Wild.",
        today=TODAY,
        llm_client=_fake_llm(payload),
    )
    assert not r.accepted
    assert "not a signal" in r.reason


def test_llm_marks_multileg() -> None:
    payload = {
        "is_signal": False, "is_multileg": True,
        "action": None, "ticker": None, "strike": None,
        "right": None, "expiry": None, "price": None,
        "field_confidence": {}, "overall_confidence": 0.95,
    }
    r = parse_text(
        "Opened a SPY iron condor for tomorrow.",
        today=TODAY,
        llm_client=_fake_llm(payload),
    )
    assert not r.accepted
    # Note: the regex pass also short-circuits "iron condor" via multileg.detect


def test_llm_invalid_payload_rejected() -> None:
    payload = {"is_signal": True, "ticker": "spy"}  # missing required fields
    r = parse_text(
        "spy calls bought",
        today=TODAY,
        llm_client=_fake_llm(payload),
    )
    assert not r.accepted


def test_llm_not_called_when_regex_accepts() -> None:
    calls: list[str] = []

    def _fn(text: str, ctx: str):
        calls.append(text)
        return {}

    r = parse_text(
        "BTO SPY 500c 6/19 @ 2.50",
        today=TODAY,
        llm_client=FunctionLLMClient(_fn),
    )
    assert r.accepted
    assert r.source == "regex"
    assert calls == []  # LLM never invoked


def test_extract_json_strips_code_fences() -> None:
    body = '```json\n{"is_signal": true, "ticker": "SPY"}\n```'
    assert extract_json(body) == {"is_signal": True, "ticker": "SPY"}


def test_extract_json_handles_prose_wrapper() -> None:
    body = 'Sure! Here you go: {"is_signal": false} Hope that helps.'
    assert extract_json(body) == {"is_signal": False}


def test_extract_json_invalid_returns_none() -> None:
    assert extract_json("not json at all") is None
    assert extract_json("") is None
