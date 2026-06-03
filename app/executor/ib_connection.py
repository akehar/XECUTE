"""Thin sync-style wrapper around ib_insync.IB.

Step 3 deliberately stops at connect / qualify / quote / place_limit / cancel /
positions. Bracket orders, shadow mode, and rate-limiting come in later steps.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from app.shared.enums import Mode, OrderStatus
from app.shared.models import OrderResult

logger = logging.getLogger(__name__)


class IBConnectionError(RuntimeError):
    pass


@dataclass
class Quote:
    bid: float | None
    ask: float | None
    last: float | None
    mid: float | None

    @classmethod
    def from_ticker(cls, ticker: Any) -> "Quote":
        bid = float(ticker.bid) if ticker.bid not in (None, -1.0) and ticker.bid == ticker.bid else None
        ask = float(ticker.ask) if ticker.ask not in (None, -1.0) and ticker.ask == ticker.ask else None
        last = float(ticker.last) if getattr(ticker, "last", None) not in (None, -1.0) and ticker.last == ticker.last else None  # noqa: E501
        mid: float | None = None
        if bid is not None and ask is not None and ask > 0 and bid > 0:
            mid = (bid + ask) / 2
        return cls(bid=bid, ask=ask, last=last, mid=mid)


class IBConnection:
    """Sync wrapper. One instance per IB Gateway (paper or live)."""

    def __init__(
        self,
        host: str,
        port: int,
        client_id: int,
        mode: Mode,
        connect_timeout: float = 10.0,
        ib_factory: Callable[[], Any] | None = None,
    ):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.mode = mode
        self.connect_timeout = connect_timeout
        self._ib: Any | None = None
        # Injection point for unit tests; production calls _default_factory which imports ib_insync.
        self._ib_factory = ib_factory or _default_ib_factory

    # ------- lifecycle -------

    def connect(self) -> None:
        if self._ib is not None and getattr(self._ib, "isConnected", lambda: False)():
            return
        ib = self._ib_factory()
        try:
            ib.connect(self.host, self.port, clientId=self.client_id, timeout=self.connect_timeout)
        except Exception as exc:
            raise IBConnectionError(
                f"connect failed host={self.host} port={self.port} clientId={self.client_id}: {exc}"
            ) from exc
        self._ib = ib
        logger.info(
            "ib connected", extra={"host": self.host, "port": self.port,
                                   "clientId": self.client_id, "mode": self.mode.value}
        )

    def disconnect(self) -> None:
        if self._ib is None:
            return
        try:
            self._ib.disconnect()
        except Exception:
            logger.exception("ib disconnect raised")
        self._ib = None

    @property
    def is_connected(self) -> bool:
        return self._ib is not None and bool(self._ib.isConnected())

    def _require_connected(self) -> Any:
        if not self.is_connected:
            raise IBConnectionError("ib not connected; call .connect() first")
        return self._ib

    # ------- contracts & quotes -------

    def qualify(self, contract: Any) -> Any:
        ib = self._require_connected()
        qualified = ib.qualifyContracts(contract)
        if not qualified:
            raise IBConnectionError(f"qualifyContracts returned nothing for {contract}")
        return qualified[0]

    def quote(self, contract: Any, snapshot_wait: float = 2.0) -> Quote:
        """Snapshot a top-of-book quote. Returns Quote with possibly-None fields when
        market data isn't available (e.g., outside RTH, no subscription, etc.)."""
        ib = self._require_connected()
        ticker = ib.reqMktData(contract, "", snapshot=False, regulatorySnapshot=False)
        try:
            # Allow IB to populate bid/ask. ib_insync's sleep() pumps the eventkit loop.
            if hasattr(ib, "sleep"):
                ib.sleep(snapshot_wait)
            return Quote.from_ticker(ticker)
        finally:
            try:
                ib.cancelMktData(contract)
            except Exception:
                pass

    # ------- orders -------

    def place_limit(
        self,
        contract: Any,
        action: str,
        quantity: int,
        limit_price: float,
        *,
        tif: str = "DAY",
        outside_rth: bool = False,
    ) -> Any:
        """Submit a limit order. Returns the ib_insync.Trade object so callers can
        poll trade.orderStatus or attach a callback."""
        if action not in ("BUY", "SELL"):
            raise ValueError(f"action must be BUY or SELL, got {action!r}")
        if quantity <= 0:
            raise ValueError(f"quantity must be positive, got {quantity}")
        if limit_price <= 0:
            raise ValueError(f"limit_price must be positive, got {limit_price}")
        ib = self._require_connected()
        from ib_insync import LimitOrder  # type: ignore[import-untyped]

        order = LimitOrder(action, quantity, limit_price)
        order.tif = tif
        order.outsideRth = outside_rth
        trade = ib.placeOrder(contract, order)
        logger.info(
            "ib limit order placed",
            extra={"action": action, "qty": quantity, "lmt": limit_price,
                   "mode": self.mode.value, "ib_order_id": trade.order.orderId},
        )
        return trade

    def cancel(self, trade: Any) -> None:
        ib = self._require_connected()
        ib.cancelOrder(trade.order)

    def wait_for_fill(self, trade: Any, timeout_seconds: float) -> "OrderResult":
        """Poll the trade's status until fill, cancel, or timeout. Returns OrderResult
        reflecting whichever terminal state we observed."""
        ib = self._require_connected()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            status = trade.orderStatus.status if trade.orderStatus else ""
            if status in ("Filled",):
                break
            if status in ("Cancelled", "Inactive", "ApiCancelled"):
                break
            if hasattr(ib, "sleep"):
                ib.sleep(0.5)
            else:
                time.sleep(0.5)
        return _trade_to_order_result(trade, self.mode)

    def positions(self) -> list[Any]:
        return self._require_connected().positions()

    def account_summary(self) -> list[Any]:
        return self._require_connected().accountSummary()


def _default_ib_factory() -> Any:
    from ib_insync import IB  # type: ignore[import-untyped]

    return IB()


def _trade_to_order_result(trade: Any, mode: Mode) -> OrderResult:
    """Translate ib_insync Trade into our OrderResult. Tolerates missing fields."""
    status_map = {
        "Filled": OrderStatus.FILLED,
        "Submitted": OrderStatus.SUBMITTED,
        "PreSubmitted": OrderStatus.SUBMITTED,
        "Cancelled": OrderStatus.CANCELLED,
        "Inactive": OrderStatus.CANCELLED,
        "ApiCancelled": OrderStatus.CANCELLED,
        "PendingSubmit": OrderStatus.PENDING,
        "PendingCancel": OrderStatus.SUBMITTED,
    }
    ib_status = (trade.orderStatus.status if trade.orderStatus else "") or ""
    status = status_map.get(ib_status, OrderStatus.PENDING)
    filled_qty = int(trade.orderStatus.filled or 0) if trade.orderStatus else 0
    requested_qty = int(getattr(trade.order, "totalQuantity", 0) or 0)
    if status == OrderStatus.SUBMITTED and 0 < filled_qty < requested_qty:
        status = OrderStatus.PARTIAL

    avg_fill: float | None = None
    if trade.orderStatus and getattr(trade.orderStatus, "avgFillPrice", None):
        try:
            avg_fill = float(trade.orderStatus.avgFillPrice) or None
        except (TypeError, ValueError):
            avg_fill = None

    limit_price: float | None = None
    try:
        limit_price = float(trade.order.lmtPrice) if getattr(trade.order, "lmtPrice", None) else None
    except (TypeError, ValueError):
        limit_price = None

    return OrderResult(
        mode=mode,
        status=status,
        ib_order_id=int(getattr(trade.order, "orderId", 0) or 0) or None,
        ib_perm_id=int(getattr(trade.order, "permId", 0) or 0) or None,
        contracts_requested=requested_qty,
        contracts_filled=filled_qty,
        avg_fill_price=avg_fill,
        limit_price=limit_price,
        error=None,
    )
