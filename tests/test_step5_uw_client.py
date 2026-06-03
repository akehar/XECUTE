"""Unusual Whales client unit tests. Uses pytest-httpx to intercept httpx
without hitting the real API."""
from __future__ import annotations

import time

import httpx
import pytest

from app.analysis.flow import UnusualWhalesClient, _verdict
from app.shared.enums import FlowVerdict


# ----- helpers -----

def _client(**kw) -> UnusualWhalesClient:
    defaults = dict(
        api_key="test-key",
        base_url="https://api.unusualwhales.test",
        cache_ttl_seconds=60,
        timeout_seconds=2.0,
    )
    defaults.update(kw)
    return UnusualWhalesClient(**defaults)


# ----- happy path -----


def test_get_flow_parses_flat_payload(httpx_mock):
    httpx_mock.add_response(
        url="https://api.unusualwhales.test/api/stock/SPY/flow?window=30",
        json={"call_premium": 1_000_000, "put_premium": 250_000, "underlying": 500.0},
    )
    c = _client()
    flow = c.get_flow("SPY", window_minutes=30)
    assert flow.ticker == "SPY"
    assert flow.window_minutes == 30
    assert flow.call_premium == 1_000_000
    assert flow.put_premium == 250_000
    assert flow.net_premium == 750_000
    assert flow.verdict == FlowVerdict.BULLISH
    assert flow.inconclusive is False
    assert flow.raw.get("underlying") == 500.0


def test_get_flow_parses_wrapped_data_payload(httpx_mock):
    httpx_mock.add_response(
        url="https://api.unusualwhales.test/api/stock/AAPL/flow?window=15",
        json={"data": {"call_premium": 100, "put_premium": 400}},
    )
    c = _client()
    flow = c.get_flow("AAPL", window_minutes=15)
    assert flow.verdict == FlowVerdict.BEARISH
    assert flow.net_premium == -300


def test_ticker_uppercased_in_url(httpx_mock):
    httpx_mock.add_response(
        url="https://api.unusualwhales.test/api/stock/NVDA/flow?window=30",
        json={"call_premium": 1, "put_premium": 1},
    )
    c = _client()
    c.get_flow("nvda")  # lowercase in
    req = httpx_mock.get_request()
    assert "/NVDA/flow" in str(req.url)


def test_authorization_header_sent(httpx_mock):
    httpx_mock.add_response(
        url="https://api.unusualwhales.test/api/stock/SPY/flow?window=30",
        json={"call_premium": 0, "put_premium": 0},
    )
    c = _client()
    c.get_flow("SPY")
    req = httpx_mock.get_request()
    assert req.headers["Authorization"] == "Bearer test-key"


# ----- caching -----


def test_cache_hit_skips_network(httpx_mock):
    httpx_mock.add_response(
        url="https://api.unusualwhales.test/api/stock/SPY/flow?window=30",
        json={"call_premium": 100, "put_premium": 50},
    )
    c = _client()
    a = c.get_flow("SPY")
    b = c.get_flow("SPY")  # should not hit network
    assert a == b
    # pytest-httpx records each call; only one should be in the log.
    assert len(httpx_mock.get_requests()) == 1


def test_cache_miss_after_expiry(httpx_mock):
    httpx_mock.add_response(
        url="https://api.unusualwhales.test/api/stock/SPY/flow?window=30",
        json={"call_premium": 100, "put_premium": 50},
    )
    httpx_mock.add_response(
        url="https://api.unusualwhales.test/api/stock/SPY/flow?window=30",
        json={"call_premium": 200, "put_premium": 50},
    )
    c = _client(cache_ttl_seconds=0)  # immediate expiry
    a = c.get_flow("SPY")
    # Sleep a touch so monotonic clock advances past 0-TTL.
    time.sleep(0.01)
    b = c.get_flow("SPY")
    assert a.call_premium == 100
    assert b.call_premium == 200
    assert len(httpx_mock.get_requests()) == 2


def test_different_windows_cache_separately(httpx_mock):
    httpx_mock.add_response(
        url="https://api.unusualwhales.test/api/stock/SPY/flow?window=30",
        json={"call_premium": 100, "put_premium": 0},
    )
    httpx_mock.add_response(
        url="https://api.unusualwhales.test/api/stock/SPY/flow?window=15",
        json={"call_premium": 50, "put_premium": 0},
    )
    c = _client()
    a = c.get_flow("SPY", window_minutes=30)
    b = c.get_flow("SPY", window_minutes=15)
    assert a.call_premium == 100
    assert b.call_premium == 50


def test_clear_cache_forces_refresh(httpx_mock):
    httpx_mock.add_response(
        url="https://api.unusualwhales.test/api/stock/SPY/flow?window=30",
        json={"call_premium": 100, "put_premium": 50},
    )
    httpx_mock.add_response(
        url="https://api.unusualwhales.test/api/stock/SPY/flow?window=30",
        json={"call_premium": 999, "put_premium": 50},
    )
    c = _client()
    c.get_flow("SPY")
    c.clear_cache()
    b = c.get_flow("SPY")
    assert b.call_premium == 999


# ----- graceful degradation -----


def test_5xx_returns_inconclusive(httpx_mock):
    httpx_mock.add_response(
        url="https://api.unusualwhales.test/api/stock/SPY/flow?window=30",
        status_code=503,
        text="service unavailable",
    )
    c = _client()
    flow = c.get_flow("SPY")
    assert flow.inconclusive is True
    assert flow.verdict == FlowVerdict.INCONCLUSIVE
    assert "503" in flow.raw["reason"]


def test_4xx_returns_inconclusive(httpx_mock):
    httpx_mock.add_response(
        url="https://api.unusualwhales.test/api/stock/SPY/flow?window=30",
        status_code=401,
        text="unauthorized",
    )
    c = _client()
    flow = c.get_flow("SPY")
    assert flow.inconclusive is True
    assert "401" in flow.raw["reason"]


def test_timeout_returns_inconclusive(httpx_mock):
    httpx_mock.add_exception(httpx.TimeoutException("read timeout"))
    c = _client()
    flow = c.get_flow("SPY")
    assert flow.inconclusive is True
    assert "timeout" in flow.raw["reason"]


def test_generic_http_error_returns_inconclusive(httpx_mock):
    httpx_mock.add_exception(httpx.ConnectError("connection refused"))
    c = _client()
    flow = c.get_flow("SPY")
    assert flow.inconclusive is True
    assert "http error" in flow.raw["reason"]


def test_malformed_json_returns_inconclusive(httpx_mock):
    httpx_mock.add_response(
        url="https://api.unusualwhales.test/api/stock/SPY/flow?window=30",
        text="this is not json {{",
    )
    c = _client()
    flow = c.get_flow("SPY")
    assert flow.inconclusive is True
    assert "json parse" in flow.raw["reason"]


def test_missing_fields_treated_as_zero(httpx_mock):
    # Spec interprets missing premium fields as zero — not an error. The
    # resulting verdict is NEUTRAL.
    httpx_mock.add_response(
        url="https://api.unusualwhales.test/api/stock/SPY/flow?window=30",
        json={"some_other_field": 123},
    )
    c = _client()
    flow = c.get_flow("SPY")
    assert flow.inconclusive is False
    assert flow.call_premium == 0
    assert flow.put_premium == 0
    assert flow.verdict == FlowVerdict.NEUTRAL


def test_non_dict_payload_returns_inconclusive(httpx_mock):
    httpx_mock.add_response(
        url="https://api.unusualwhales.test/api/stock/SPY/flow?window=30",
        json=["unexpected", "list", "payload"],
    )
    c = _client()
    flow = c.get_flow("SPY")
    assert flow.inconclusive is True
    assert "shape" in flow.raw["reason"]


# ----- verdict mapping (pure function) -----


@pytest.mark.parametrize(
    "call_p, put_p, expected",
    [
        (1000, 100, FlowVerdict.BULLISH),
        (100, 1000, FlowVerdict.BEARISH),
        (500, 500, FlowVerdict.NEUTRAL),
        (520, 480, FlowVerdict.NEUTRAL),    # within 10% band
        (600, 400, FlowVerdict.BULLISH),    # outside 10% band
        (0, 0, FlowVerdict.NEUTRAL),
    ],
)
def test_verdict_mapping(call_p, put_p, expected):
    assert _verdict(call_p, put_p) == expected
