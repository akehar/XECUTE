"""Top-level signal parser: regex first, LLM fallback, threshold + validation."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.parser.llm import LLMClient
from app.parser.multileg import detect_multileg
from app.parser.parse_result import ParseResult
from app.parser.regex import parse_text_regex
from app.shared.config import get_settings
from app.shared.enums import OptionRight, SignalAction, SignalSource
from app.shared.models import Signal

logger = logging.getLogger(__name__)

_VALID_ACTIONS = {a.value for a in SignalAction}
_VALID_RIGHTS = {"C", "P"}


def _coerce_llm_signal(
    payload: dict[str, Any],
    raw_text: str,
    source: SignalSource,
) -> tuple[Signal | None, str]:
    """Convert an LLM JSON payload into a validated Signal. Returns (signal, reason_if_none)."""
    if not payload.get("is_signal"):
        return None, "llm: not a signal"
    if payload.get("is_multileg"):
        return None, "llm: multi-leg"

    action_raw = payload.get("action")
    ticker = payload.get("ticker")
    strike = payload.get("strike")
    right_raw = payload.get("right")
    expiry_raw = payload.get("expiry")
    price = payload.get("price")

    if action_raw not in _VALID_ACTIONS:
        return None, f"llm: invalid action {action_raw!r}"
    if not ticker or not isinstance(ticker, str):
        return None, "llm: missing ticker"
    if not isinstance(strike, (int, float)) or strike <= 0:
        return None, "llm: invalid strike"
    if right_raw not in _VALID_RIGHTS:
        return None, f"llm: invalid right {right_raw!r}"
    if not expiry_raw or not isinstance(expiry_raw, str):
        return None, "llm: missing expiry"
    action = SignalAction(action_raw)
    is_exit = action in (SignalAction.STC, SignalAction.BTC)
    if not is_exit and (not isinstance(price, (int, float)) or price <= 0):
        return None, "llm: invalid price"

    try:
        expiry = date.fromisoformat(expiry_raw)
    except ValueError:
        return None, f"llm: bad expiry date {expiry_raw!r}"

    try:
        signal = Signal(
            source=source,
            action=action,
            ticker=ticker,
            strike=float(strike),
            right=OptionRight(right_raw),
            expiry=expiry,
            price=float(price) if isinstance(price, (int, float)) and price > 0 else 0.01,
            stop=float(payload["stop"]) if isinstance(payload.get("stop"), (int, float)) else None,
            target=float(payload["target"]) if isinstance(payload.get("target"), (int, float)) else None,
            raw_text=raw_text,
        )
    except Exception as exc:  # pydantic ValidationError
        return None, f"llm: validation {exc}"
    return signal, ""


def parse_text(
    text: str,
    *,
    source: SignalSource = SignalSource.DISCORD,
    today: date | None = None,
    llm_client: LLMClient | None = None,
    min_confidence: float | None = None,
    default_expiry_today: bool | None = None,
) -> ParseResult:
    """Run the full parse pipeline. Threshold defaults to settings.parse_min_confidence.

    default_expiry_today=True treats messages with no expiry token as 0DTE — the
    convention used by the signal channel we're following. None reads the setting.
    """
    if min_confidence is None:
        try:
            min_confidence = get_settings().parse_min_confidence
        except Exception:
            min_confidence = 0.85
    if default_expiry_today is None:
        try:
            default_expiry_today = get_settings().parser_default_expiry_today
        except Exception:
            default_expiry_today = False

    raw = text.strip() if text else ""
    if not raw:
        return ParseResult(source="rejected", reason="empty", raw_text="")

    multileg, ml_reason = detect_multileg(raw)
    if multileg:
        return ParseResult(
            source="rejected",
            reason=f"multi-leg: {ml_reason}",
            raw_text=raw,
            multileg=True,
        )

    regex_result = parse_text_regex(
        raw, source=source, today=today, default_expiry_today=default_expiry_today
    )
    if regex_result.signal is not None and regex_result.confidence >= min_confidence:
        return regex_result

    if llm_client is None:
        # No LLM available; surface the best regex failure reason or low-confidence note.
        reason = regex_result.reason or f"regex confidence {regex_result.confidence:.2f} below threshold"
        return ParseResult(
            source="rejected",
            reason=reason,
            raw_text=raw,
            confidence=regex_result.confidence,
            field_confidence=regex_result.field_confidence,
            multileg=regex_result.multileg,
        )

    context_date = (today or date.today()).isoformat()
    payload = llm_client.parse(raw, context_date=context_date)
    if payload is None:
        return ParseResult(
            source="rejected",
            reason="llm: no response",
            raw_text=raw,
            llm_attempted=True,
            confidence=regex_result.confidence,
            field_confidence=regex_result.field_confidence,
        )

    overall = float(payload.get("overall_confidence") or 0.0)
    field_conf = {k: float(v) for k, v in (payload.get("field_confidence") or {}).items()}

    signal, reason = _coerce_llm_signal(payload, raw, source)
    if signal is None:
        return ParseResult(
            source="rejected",
            reason=reason,
            raw_text=raw,
            confidence=overall,
            field_confidence=field_conf,
            llm_attempted=True,
            llm_payload=payload,
            multileg=bool(payload.get("is_multileg")),
        )
    if overall < min_confidence:
        return ParseResult(
            source="rejected",
            reason=f"llm confidence {overall:.2f} below threshold {min_confidence:.2f}",
            raw_text=raw,
            confidence=overall,
            field_confidence=field_conf,
            llm_attempted=True,
            llm_payload=payload,
        )

    signal.parse_confidence = overall
    return ParseResult(
        signal=signal,
        source="llm",
        confidence=overall,
        field_confidence=field_conf,
        raw_text=raw,
        llm_attempted=True,
        llm_payload=payload,
    )
