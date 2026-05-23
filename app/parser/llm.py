"""Claude Haiku 4.5 fallback parser. Strict JSON output, per-field + overall confidence."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)


LLM_SYSTEM_PROMPT = """You parse Discord options-trading signals into strict JSON.

Output ONLY a single JSON object — no prose, no markdown fences. The object MUST have these fields:

{
  "is_signal": boolean,             // false if the message is not an actionable single-leg options trade
  "is_multileg": boolean,           // true if message describes a spread/condor/butterfly/strangle/straddle/calendar/diagonal/vertical
  "action": "BTO" | "STC" | "STO" | "BTC" | "BTO_ADD" | null,
  "ticker": string | null,          // uppercase US-equity ticker
  "strike": number | null,          // positive number
  "right": "C" | "P" | null,        // call or put
  "expiry": string | null,          // ISO 8601 date YYYY-MM-DD. Resolve "0DTE"/"today"/"this Friday" using the given context date.
  "price": number | null,           // signal entry/limit premium per contract
  "stop": number | null,
  "target": number | null,
  "field_confidence": {             // 0.0 - 1.0 per extracted field
    "action": number, "ticker": number, "strike": number, "right": number, "expiry": number, "price": number
  },
  "overall_confidence": number      // 0.0 - 1.0; lowest of the per-field confidences for required fields, or lower if you're unsure
}

Rules:
- "BTO" = open long, "STC" = close long, "STO" = open short, "BTC" = close short.
- Words "added"/"adds"/"adding" = "BTO_ADD".
- If the message is chit-chat, news, or not actionable, set is_signal=false and overall_confidence below 0.5.
- If multi-leg, set is_multileg=true and is_signal=false.
- Do not guess: if a field is genuinely unknown, return null and lower its field_confidence.
- Resolve relative dates ("0DTE", "today", "tomorrow", "this Friday", "+1w", "next week") to an explicit YYYY-MM-DD using CONTEXT_DATE.
- For exits (STC/BTC) where no premium is quoted, leave price null and lower price confidence; do not invent it.
"""


class LLMClient(Protocol):
    """Anything that turns text into the JSON schema above."""

    def parse(self, text: str, *, context_date: str) -> dict[str, Any] | None: ...


class AnthropicLLMClient:
    """Real Claude Haiku 4.5 client. Lazy-imports anthropic so unit tests don't need the SDK."""

    def __init__(self, api_key: str, model: str = "claude-haiku-4-5", max_tokens: int = 512):
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic  # noqa: PLC0415

            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def parse(self, text: str, *, context_date: str) -> dict[str, Any] | None:
        client = self._get_client()
        user_msg = f"CONTEXT_DATE: {context_date}\n\nMESSAGE:\n{text}"
        try:
            resp = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=LLM_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
        except Exception:
            logger.exception("anthropic call failed")
            return None
        if not resp.content:
            return None
        body = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
        return extract_json(body)


def extract_json(body: str) -> dict[str, Any] | None:
    """Best-effort JSON extraction. Tolerates code fences and surrounding prose."""
    if not body:
        return None
    body = body.strip()
    if body.startswith("```"):
        body = re.sub(r"^```[a-zA-Z]*\n?", "", body)
        body = re.sub(r"\n?```$", "", body)
        body = body.strip()
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        start = body.find("{")
        end = body.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(body[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


CallableLLMClient = Callable[[str, str], "dict[str, Any] | None"]


class FunctionLLMClient:
    """Adapter so tests can pass a plain callable instead of implementing the Protocol."""

    def __init__(self, fn: CallableLLMClient):
        self._fn = fn

    def parse(self, text: str, *, context_date: str) -> dict[str, Any] | None:
        return self._fn(text, context_date)
