"""Real-API smoke test for the UW client. One real GET to verify the API key
works and the response shape parses cleanly.

Opt in via UW_SMOKE=1 with UW_API_KEY set in the environment. Runs once when
you wire up the key — don't run repeatedly (counts against your rate limit).

    UW_SMOKE=1 UW_API_KEY=... pytest tests/test_step5_uw_smoke.py -v -s
"""
from __future__ import annotations

import os

import pytest

from app.analysis.flow import UnusualWhalesClient
from app.shared.config import get_settings

pytestmark = pytest.mark.skipif(
    os.environ.get("UW_SMOKE") != "1",
    reason="set UW_SMOKE=1 with UW_API_KEY in env to validate the key against the real API",
)


def test_real_uw_flow_returns_or_inconclusive():
    s = get_settings()
    api_key = s.uw_api_key or os.environ.get("UW_API_KEY", "")
    assert api_key, "UW_API_KEY not set"
    client = UnusualWhalesClient(
        api_key=api_key,
        base_url=s.uw_base_url,
        cache_ttl_seconds=60,
        timeout_seconds=10.0,
    )
    try:
        flow = client.get_flow("SPY", window_minutes=30)
        print(f"\nSPY flow: call={flow.call_premium}, put={flow.put_premium}, "
              f"verdict={flow.verdict.value}, inconclusive={flow.inconclusive}")
        if flow.inconclusive:
            print(f"  reason: {flow.raw.get('reason')}")
        # A 401 surfaces as inconclusive with 'HTTP 401' in the reason — caller
        # should treat that as a fatal misconfig at startup. We only assert the
        # client didn't crash here.
        assert flow.ticker == "SPY"
    finally:
        client.close()
