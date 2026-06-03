"""Real IB Gateway integration test for Step 3.

Skipped unless IB_INTEGRATION=1 is set, because it requires:
- A running IB Gateway / TWS connected to a paper account
- Market data subscription for SPY options on the paper account
- The ib_insync package installed in the venv

How to run on the VPS (or your laptop with IB Gateway):

    pip install ib_insync
    IB_INTEGRATION=1 IBKR_PAPER_PORT=4002 pytest tests/test_step3_ib_integration.py -v -s

What it does:
1. Connects to the paper gateway.
2. Builds a SPY weekly ATM-ish call contract and qualifies it via IB.
3. Pulls a snapshot quote (bid/ask/mid).
4. With IB_INTEGRATION_ORDER=1, places a deliberately un-fillable far-OTM
   buy-limit, asserts it submitted, then cancels it. The "real paper fill"
   variant is gated separately by IB_INTEGRATION_FILL=1 — it picks an ATM
   strike and a limit at ask+buffer so the order actually fills.

The fill variant is opt-in because it touches paper-account state. Use it
once on the VPS to validate the end-to-end pipeline, then keep it off.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import pytest

from app.shared.config import get_settings
from app.shared.enums import Mode, OptionRight, OrderStatus, SignalAction, SignalSource
from app.shared.models import Signal

pytestmark = pytest.mark.skipif(
    os.environ.get("IB_INTEGRATION") != "1",
    reason="set IB_INTEGRATION=1 with a running IB paper gateway to run",
)


def _next_friday(today: date) -> date:
    days_ahead = (4 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return today + timedelta(days=days_ahead)


def _build_spy_signal(strike: float, price: float) -> Signal:
    return Signal(
        source=SignalSource.DISCORD,
        action=SignalAction.BTO,
        ticker="SPY",
        strike=strike,
        right=OptionRight.CALL,
        expiry=_next_friday(date.today()),
        price=price,
    )


def _make_connection():
    from app.executor.ib_connection import IBConnection

    s = get_settings()
    return IBConnection(
        host=s.ibkr_paper_host,
        port=s.ibkr_paper_port,
        client_id=s.ibkr_paper_client_id,
        mode=Mode.PAPER,
        connect_timeout=15.0,
    )


def test_connect_and_quote_spy_atm_call():
    from app.executor.contracts import build_option_contract

    conn = _make_connection()
    conn.connect()
    try:
        assert conn.is_connected
        # Pick a deep-OTM strike that's still on the chain to avoid noise.
        signal = _build_spy_signal(strike=600.0, price=0.10)
        contract = build_option_contract(signal)
        qualified = conn.qualify(contract)
        assert qualified is not None
        quote = conn.quote(qualified, snapshot_wait=2.5)
        # bid/ask may be None outside RTH; we only assert quote() returned without raising
        assert quote is not None
    finally:
        conn.disconnect()


def test_positions_endpoint_returns_list():
    conn = _make_connection()
    conn.connect()
    try:
        positions = conn.positions()
        assert isinstance(positions, list)
    finally:
        conn.disconnect()


@pytest.mark.skipif(
    os.environ.get("IB_INTEGRATION_ORDER") != "1",
    reason="set IB_INTEGRATION_ORDER=1 to place + cancel a deliberately unfillable test order",
)
def test_place_far_otm_limit_and_cancel():
    from app.executor.contracts import build_option_contract

    conn = _make_connection()
    conn.connect()
    try:
        # Buy way-OTM far below market so it submits but doesn't fill.
        signal = _build_spy_signal(strike=700.0, price=0.01)
        contract = build_option_contract(signal)
        qualified = conn.qualify(contract)
        trade = conn.place_limit(qualified, "BUY", quantity=1, limit_price=0.01)
        assert trade is not None
        # Give IB a moment to acknowledge.
        result_after_short_wait = conn.wait_for_fill(trade, timeout_seconds=3)
        assert result_after_short_wait.status in (
            OrderStatus.PENDING,
            OrderStatus.SUBMITTED,
            OrderStatus.PARTIAL,
        )
        conn.cancel(trade)
        result_after_cancel = conn.wait_for_fill(trade, timeout_seconds=5)
        assert result_after_cancel.status == OrderStatus.CANCELLED
    finally:
        conn.disconnect()


@pytest.mark.skipif(
    os.environ.get("IB_INTEGRATION_FILL") != "1",
    reason=(
        "set IB_INTEGRATION_FILL=1 to place a real paper fill. Requires market open + "
        "a liquid SPY weekly chain. Run once to validate end-to-end."
    ),
)
def test_place_atm_limit_real_paper_fill():
    """The 'real paper fill' from the spec: pick an ATM-ish strike, limit at ask+buffer,
    confirm IB reports Filled, then close the position."""
    from app.executor.contracts import build_option_contract

    conn = _make_connection()
    conn.connect()
    try:
        # SPY weekly ATM call, ballparked. Use a moderately near strike; the bot's
        # smarter chain-walking lives in Step 9.
        signal = _build_spy_signal(strike=510.0, price=1.00)
        contract = build_option_contract(signal)
        qualified = conn.qualify(contract)
        quote = conn.quote(qualified, snapshot_wait=2.5)
        assert quote.ask is not None and quote.ask > 0, (
            "no live ask — market closed or data subscription missing"
        )
        limit = round(quote.ask * 1.02, 2)
        buy_trade = conn.place_limit(qualified, "BUY", quantity=1, limit_price=limit)
        buy_result = conn.wait_for_fill(buy_trade, timeout_seconds=30)
        assert buy_result.status == OrderStatus.FILLED, f"did not fill: {buy_result}"
        assert buy_result.contracts_filled == 1

        # Close it so the paper account doesn't accumulate state across runs.
        quote = conn.quote(qualified, snapshot_wait=2.5)
        sell_limit = round((quote.bid or quote.ask or limit) * 0.95, 2)
        sell_trade = conn.place_limit(qualified, "SELL", quantity=1, limit_price=sell_limit)
        conn.wait_for_fill(sell_trade, timeout_seconds=30)
    finally:
        conn.disconnect()
