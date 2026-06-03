"""Unit tests for the IB connection wrapper and contract builder.

Mocks `ib_insync` via sys.modules so this suite runs without the real package
installed. Integration tests against an actual paper gateway live in
test_step3_ib_integration.py and are skipped unless IB_INTEGRATION=1.
"""
from __future__ import annotations

import sys
import types
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest


# ---- Install a stub ib_insync module BEFORE app.executor imports it ----

class _FakeOption:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __repr__(self) -> str:
        return f"FakeOption({self.__dict__})"


class _FakeLimitOrder:
    def __init__(self, action, totalQuantity, lmtPrice):
        self.action = action
        self.totalQuantity = totalQuantity
        self.lmtPrice = lmtPrice
        self.tif = "DAY"
        self.outsideRth = False
        self.orderId = 0
        self.permId = 0


class _FakeIB:
    """Placeholder so `from ib_insync import IB` resolves; tests inject their own
    factory rather than using this."""


if "ib_insync" not in sys.modules:
    fake = types.ModuleType("ib_insync")
    fake.IB = _FakeIB
    fake.Option = _FakeOption
    fake.LimitOrder = _FakeLimitOrder
    sys.modules["ib_insync"] = fake


# Now the imports from app.executor will resolve.
from app.executor.contracts import build_option_contract, format_contract_key  # noqa: E402
from app.executor.ib_connection import (  # noqa: E402
    IBConnection,
    IBConnectionError,
    Quote,
    _trade_to_order_result,
)
from app.shared.enums import Mode, OptionRight, OrderStatus, SignalAction, SignalSource  # noqa: E402
from app.shared.models import Signal  # noqa: E402


def _signal(**overrides) -> Signal:
    base = dict(
        source=SignalSource.DISCORD,
        action=SignalAction.BTO,
        ticker="SPY",
        strike=500.0,
        right=OptionRight.CALL,
        expiry=date.today() + timedelta(days=14),
        price=2.50,
    )
    base.update(overrides)
    return Signal(**base)


# ----------- contract builder -----------


class TestContracts:
    def test_call_contract_fields(self):
        s = _signal(right=OptionRight.CALL, strike=500.0, ticker="SPY")
        c = build_option_contract(s)
        assert c.symbol == "SPY"
        assert c.strike == 500.0
        assert c.right == "C"
        assert c.exchange == "SMART"
        assert c.currency == "USD"
        assert c.lastTradeDateOrContractMonth == s.expiry.strftime("%Y%m%d")

    def test_put_contract_right_letter(self):
        s = _signal(right=OptionRight.PUT, strike=180.0)
        c = build_option_contract(s)
        assert c.right == "P"

    def test_format_contract_key(self):
        s = _signal(ticker="NVDA", strike=500.0, right=OptionRight.PUT,
                    expiry=date(2026, 7, 17))
        assert format_contract_key(s) == "NVDA_20260717_500P"


# ----------- IBConnection lifecycle -----------


def _make_ib_mock(connected: bool = True) -> MagicMock:
    """A configurable mock standing in for ib_insync.IB()."""
    ib = MagicMock()
    ib.isConnected.return_value = connected
    ib.connect.return_value = None
    ib.disconnect.return_value = None
    ib.qualifyContracts.return_value = []
    ib.reqMktData.return_value = MagicMock(bid=4.95, ask=5.05, last=5.00)
    ib.positions.return_value = []
    ib.accountSummary.return_value = []
    ib.sleep = MagicMock()
    return ib


class TestConnectionLifecycle:
    def test_connect_calls_ib_with_correct_args(self):
        ib = _make_ib_mock(connected=True)
        conn = IBConnection("127.0.0.1", 4002, 11, Mode.PAPER, ib_factory=lambda: ib)
        conn.connect()
        ib.connect.assert_called_once_with("127.0.0.1", 4002, clientId=11, timeout=10.0)
        assert conn.is_connected

    def test_connect_failure_raises_ibconnection_error(self):
        ib = _make_ib_mock(connected=False)
        ib.connect.side_effect = RuntimeError("timeout")
        conn = IBConnection("127.0.0.1", 4002, 11, Mode.PAPER, ib_factory=lambda: ib)
        with pytest.raises(IBConnectionError) as exc:
            conn.connect()
        assert "timeout" in str(exc.value)

    def test_connect_idempotent_when_already_connected(self):
        ib = _make_ib_mock(connected=True)
        conn = IBConnection("127.0.0.1", 4002, 11, Mode.PAPER, ib_factory=lambda: ib)
        conn._ib = ib  # simulate already-connected state
        conn.connect()
        ib.connect.assert_not_called()

    def test_disconnect_clears_handle(self):
        ib = _make_ib_mock()
        conn = IBConnection("127.0.0.1", 4002, 11, Mode.PAPER, ib_factory=lambda: ib)
        conn._ib = ib
        conn.disconnect()
        assert conn._ib is None
        ib.disconnect.assert_called_once()

    def test_disconnect_safe_when_never_connected(self):
        conn = IBConnection("127.0.0.1", 4002, 11, Mode.PAPER)
        conn.disconnect()  # must not raise

    def test_operations_require_connection(self):
        conn = IBConnection("127.0.0.1", 4002, 11, Mode.PAPER)
        with pytest.raises(IBConnectionError):
            conn.qualify(object())
        with pytest.raises(IBConnectionError):
            conn.quote(object())
        with pytest.raises(IBConnectionError):
            conn.place_limit(object(), "BUY", 1, 1.0)


# ----------- qualify / quote -----------


class TestQualifyAndQuote:
    def _connected(self) -> tuple[IBConnection, MagicMock]:
        ib = _make_ib_mock(connected=True)
        conn = IBConnection("127.0.0.1", 4002, 11, Mode.PAPER, ib_factory=lambda: ib)
        conn._ib = ib
        return conn, ib

    def test_qualify_returns_first_qualified(self):
        conn, ib = self._connected()
        qualified = MagicMock(symbol="SPY", conId=12345)
        ib.qualifyContracts.return_value = [qualified]
        c = conn.qualify(MagicMock())
        assert c is qualified

    def test_qualify_raises_when_nothing_returned(self):
        conn, ib = self._connected()
        ib.qualifyContracts.return_value = []
        with pytest.raises(IBConnectionError):
            conn.qualify(MagicMock())

    def test_quote_returns_quote_with_mid(self):
        conn, ib = self._connected()
        ib.reqMktData.return_value = MagicMock(bid=4.95, ask=5.05, last=5.00)
        q = conn.quote(MagicMock(), snapshot_wait=0)
        assert q.bid == 4.95
        assert q.ask == 5.05
        assert q.mid == pytest.approx(5.00)
        ib.cancelMktData.assert_called_once()

    def test_quote_handles_no_market_data(self):
        conn, ib = self._connected()
        # IB reports -1.0 for unavailable bid/ask
        ib.reqMktData.return_value = MagicMock(bid=-1.0, ask=-1.0, last=-1.0)
        q = conn.quote(MagicMock(), snapshot_wait=0)
        assert q.bid is None
        assert q.ask is None
        assert q.mid is None

    def test_quote_handles_nan_bid_ask(self):
        conn, ib = self._connected()
        ib.reqMktData.return_value = MagicMock(bid=float("nan"), ask=float("nan"), last=float("nan"))
        q = conn.quote(MagicMock(), snapshot_wait=0)
        assert q.bid is None and q.ask is None and q.mid is None


# ----------- place_limit / cancel / wait_for_fill -----------


def _make_trade(status: str = "PreSubmitted", filled: int = 0,
                requested: int = 1, avg_fill: float | None = None,
                lmt: float | None = 1.50, order_id: int = 42, perm_id: int = 99) -> MagicMock:
    order = MagicMock()
    order.orderId = order_id
    order.permId = perm_id
    order.totalQuantity = requested
    order.lmtPrice = lmt
    status_obj = MagicMock()
    status_obj.status = status
    status_obj.filled = filled
    status_obj.avgFillPrice = avg_fill
    trade = MagicMock()
    trade.order = order
    trade.orderStatus = status_obj
    return trade


class TestPlaceLimitAndFill:
    def _connected(self) -> tuple[IBConnection, MagicMock]:
        ib = _make_ib_mock(connected=True)
        conn = IBConnection("127.0.0.1", 4002, 11, Mode.PAPER, ib_factory=lambda: ib)
        conn._ib = ib
        return conn, ib

    def test_place_limit_validates_action(self):
        conn, _ib = self._connected()
        with pytest.raises(ValueError):
            conn.place_limit(MagicMock(), "HOLD", 1, 1.5)

    def test_place_limit_validates_quantity(self):
        conn, _ib = self._connected()
        with pytest.raises(ValueError):
            conn.place_limit(MagicMock(), "BUY", 0, 1.5)

    def test_place_limit_validates_price(self):
        conn, _ib = self._connected()
        with pytest.raises(ValueError):
            conn.place_limit(MagicMock(), "BUY", 1, 0.0)

    def test_place_limit_builds_order_and_calls_ib(self):
        conn, ib = self._connected()
        trade = _make_trade()
        ib.placeOrder.return_value = trade
        contract = MagicMock()
        result = conn.place_limit(contract, "BUY", 2, 1.50)
        assert result is trade
        ib.placeOrder.assert_called_once()
        called_contract, called_order = ib.placeOrder.call_args[0]
        assert called_contract is contract
        # The shim's _FakeLimitOrder records the args.
        assert called_order.action == "BUY"
        assert called_order.totalQuantity == 2
        assert called_order.lmtPrice == 1.50
        assert called_order.tif == "DAY"

    def test_cancel_passes_order_to_ib(self):
        conn, ib = self._connected()
        trade = _make_trade()
        conn.cancel(trade)
        ib.cancelOrder.assert_called_once_with(trade.order)

    def test_wait_for_fill_returns_filled_immediately(self):
        conn, ib = self._connected()
        trade = _make_trade(status="Filled", filled=1, requested=1, avg_fill=1.55)
        result = conn.wait_for_fill(trade, timeout_seconds=1)
        assert result.status == OrderStatus.FILLED
        assert result.contracts_filled == 1
        assert result.avg_fill_price == 1.55
        assert result.mode == Mode.PAPER
        assert result.ib_order_id == 42

    def test_wait_for_fill_returns_cancelled(self):
        conn, _ib = self._connected()
        trade = _make_trade(status="Cancelled", filled=0)
        result = conn.wait_for_fill(trade, timeout_seconds=1)
        assert result.status == OrderStatus.CANCELLED
        assert result.contracts_filled == 0

    def test_wait_for_fill_times_out(self):
        conn, ib = self._connected()
        trade = _make_trade(status="Submitted", filled=0)
        # ib.sleep is a no-op MagicMock, so the poll loop spins fast.
        result = conn.wait_for_fill(trade, timeout_seconds=0.1)
        assert result.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED)


# ----------- _trade_to_order_result mapping -----------


class TestTradeToOrderResult:
    def test_partial_fill_maps_to_partial_status(self):
        trade = _make_trade(status="Submitted", filled=1, requested=3, avg_fill=1.50)
        r = _trade_to_order_result(trade, Mode.LIVE)
        assert r.status == OrderStatus.PARTIAL
        assert r.contracts_filled == 1
        assert r.contracts_requested == 3
        assert r.avg_fill_price == 1.50
        assert r.mode == Mode.LIVE

    def test_unknown_status_falls_back_to_pending(self):
        trade = _make_trade(status="Mystery", filled=0)
        r = _trade_to_order_result(trade, Mode.PAPER)
        assert r.status == OrderStatus.PENDING

    def test_zero_order_id_becomes_none(self):
        trade = _make_trade(status="Filled", filled=1, order_id=0, perm_id=0)
        r = _trade_to_order_result(trade, Mode.PAPER)
        assert r.ib_order_id is None
        assert r.ib_perm_id is None
