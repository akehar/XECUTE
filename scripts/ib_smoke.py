"""Manual IB Gateway smoke test.

Usage on the VPS once the paper / live gateway is up:

    python -m scripts.ib_smoke --gateway paper
    python -m scripts.ib_smoke --gateway live

Connects, qualifies a SPY weekly call, prints a quote, lists positions, disconnects.
No orders are placed. Use the integration test (test_step3_ib_integration.py) for
order-placement validation.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

from app.shared.config import get_settings
from app.shared.enums import Mode, OptionRight, SignalAction, SignalSource
from app.shared.models import Signal


def _next_friday(today: date) -> date:
    days_ahead = (4 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return today + timedelta(days=days_ahead)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    p = argparse.ArgumentParser(description="IB Gateway smoke test (no orders placed)")
    p.add_argument("--gateway", choices=("paper", "live"), default="paper")
    p.add_argument("--ticker", default="SPY")
    p.add_argument("--strike", type=float, default=510.0)
    p.add_argument("--right", choices=("C", "P"), default="C")
    args = p.parse_args()

    from app.executor.contracts import build_option_contract
    from app.executor.ib_connection import IBConnection

    s = get_settings()
    if args.gateway == "paper":
        host, port, client_id, mode = s.ibkr_paper_host, s.ibkr_paper_port, s.ibkr_paper_client_id, Mode.PAPER
    else:
        host, port, client_id, mode = s.ibkr_live_host, s.ibkr_live_port, s.ibkr_live_client_id, Mode.LIVE

    print(f"connecting to {args.gateway} at {host}:{port} clientId={client_id} ...")
    conn = IBConnection(host=host, port=port, client_id=client_id, mode=mode, connect_timeout=15.0)
    try:
        conn.connect()
        print(f"connected: {conn.is_connected}")
    except Exception as exc:
        print(f"connect failed: {exc}")
        return 2

    try:
        signal = Signal(
            source=SignalSource.SCANNER,
            action=SignalAction.BTO,
            ticker=args.ticker,
            strike=args.strike,
            right=OptionRight.CALL if args.right == "C" else OptionRight.PUT,
            expiry=_next_friday(date.today()),
            price=1.00,
        )
        contract = build_option_contract(signal)
        print(f"qualifying {args.ticker} {args.strike}{args.right} {signal.expiry} ...")
        qualified = conn.qualify(contract)
        print(f"qualified: conId={getattr(qualified, 'conId', '?')} "
              f"primaryExchange={getattr(qualified, 'primaryExchange', '?')}")

        print("requesting snapshot quote ...")
        quote = conn.quote(qualified, snapshot_wait=3.0)
        print(f"quote: bid={quote.bid} ask={quote.ask} mid={quote.mid} last={quote.last}")

        print("listing positions ...")
        positions = conn.positions()
        print(f"open positions: {len(positions)}")
        for pos in positions[:10]:
            print(f"  {pos}")

        return 0
    finally:
        conn.disconnect()
        print("disconnected.")


if __name__ == "__main__":
    sys.exit(main())
