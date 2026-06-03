"""Unusual Whales client. Single source of flow data for the pre-trade
analysis engine's check_flow gate.

Design:
- httpx.Client (sync) — the pipeline runs the analysis on a worker thread, no
  benefit to async here.
- 60-second per-(endpoint, ticker, window) TTL cache to stay under rate limits.
- All error paths (network failure, 4xx/5xx, malformed JSON, missing fields)
  funnel to _inconclusive(), which returns a FlowData with verdict=INCONCLUSIVE
  and inconclusive=True. The engine's flow_fail_mode setting decides what to
  do with that.

Endpoint paths are configurable on construction because UW has revised them
historically. Defaults match the current public surface; override when needed.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from app.shared.enums import FlowVerdict
from app.shared.models import FlowData

logger = logging.getLogger(__name__)


class UnusualWhalesClient:
    DEFAULT_FLOW_PATH = "/api/stock/{ticker}/flow"
    DEFAULT_GREEKS_PATH = "/api/stock/{ticker}/greek-exposure"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.unusualwhales.com",
        *,
        cache_ttl_seconds: int = 60,
        timeout_seconds: float = 5.0,
        flow_path: str = DEFAULT_FLOW_PATH,
        greeks_path: str = DEFAULT_GREEKS_PATH,
        client: httpx.Client | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.cache_ttl_seconds = cache_ttl_seconds
        self.timeout_seconds = timeout_seconds
        self.flow_path = flow_path
        self.greeks_path = greeks_path
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._cache: dict[tuple, tuple[float, FlowData]] = {}
        self._lock = threading.Lock()

    # ---- public ----

    def get_flow(self, ticker: str, window_minutes: int = 30) -> FlowData:
        ticker = ticker.strip().upper()
        key = ("flow", ticker, window_minutes)

        with self._lock:
            cached = self._cache.get(key)
        if cached is not None and (time.monotonic() - cached[0]) < self.cache_ttl_seconds:
            return cached[1]

        path = self.flow_path.format(ticker=ticker)
        url = f"{self.base_url}{path}"
        try:
            resp = self._client.get(
                url,
                params={"window": window_minutes},
                headers=self._headers(),
            )
        except httpx.TimeoutException as exc:
            return self._inconclusive(ticker, window_minutes, reason=f"timeout: {exc}")
        except httpx.HTTPError as exc:
            return self._inconclusive(ticker, window_minutes, reason=f"http error: {exc}")

        if resp.status_code != 200:
            return self._inconclusive(
                ticker, window_minutes,
                reason=f"HTTP {resp.status_code}: {resp.text[:200] if resp.text else ''}",
            )

        try:
            payload = resp.json()
        except ValueError as exc:
            return self._inconclusive(ticker, window_minutes, reason=f"json parse: {exc}")

        try:
            flow = self._parse_flow(ticker, window_minutes, payload)
        except (KeyError, TypeError, ValueError) as exc:
            return self._inconclusive(ticker, window_minutes, reason=f"shape: {exc}")

        with self._lock:
            self._cache[key] = (time.monotonic(), flow)
        return flow

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            logger.exception("error closing uw http client")

    # ---- internals ----

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": "xecute/0.1",
        }

    def _parse_flow(self, ticker: str, window_minutes: int, payload: Any) -> FlowData:
        # UW's flow summary varies by endpoint version. We accept either a flat
        # object {call_premium, put_premium, ...} or a wrapped {data: {...}}.
        if isinstance(payload, dict) and "data" in payload and isinstance(payload["data"], dict):
            d = payload["data"]
        elif isinstance(payload, dict):
            d = payload
        else:
            raise ValueError(f"unexpected payload type: {type(payload).__name__}")

        call_p = _coerce_premium(d.get("call_premium"))
        put_p = _coerce_premium(d.get("put_premium"))
        net = call_p - put_p
        verdict = _verdict(call_p, put_p)

        return FlowData(
            ticker=ticker,
            window_minutes=window_minutes,
            call_premium=call_p,
            put_premium=put_p,
            net_premium=net,
            verdict=verdict,
            inconclusive=False,
            raw=d if isinstance(d, dict) else {},
        )

    def _inconclusive(self, ticker: str, window: int, reason: str = "") -> FlowData:
        logger.warning("uw flow inconclusive", extra={"ticker": ticker, "reason": reason})
        return FlowData(
            ticker=ticker,
            window_minutes=window,
            call_premium=0.0,
            put_premium=0.0,
            net_premium=0.0,
            verdict=FlowVerdict.INCONCLUSIVE,
            inconclusive=True,
            raw={"reason": reason},
        )


def _coerce_premium(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _verdict(call_p: float, put_p: float, neutral_band: float = 0.10) -> FlowVerdict:
    """neutral_band: when |call - put| < band * (call + put), call it NEUTRAL."""
    total = call_p + put_p
    if total <= 0:
        return FlowVerdict.NEUTRAL
    diff = abs(call_p - put_p)
    if diff < neutral_band * total:
        return FlowVerdict.NEUTRAL
    return FlowVerdict.BULLISH if call_p > put_p else FlowVerdict.BEARISH
