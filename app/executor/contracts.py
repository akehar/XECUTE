"""Translate Signal -> ib_insync.Option. Kept tiny so the executor doesn't depend on
the option-chain logic (Step 9 will add nearest-strike picking)."""
from __future__ import annotations

from typing import Any

from app.shared.enums import OptionRight
from app.shared.models import Signal


def build_option_contract(signal: Signal, exchange: str = "SMART", currency: str = "USD") -> Any:
    """Returns an ib_insync.Option contract for the given Signal.

    Lazy import so the module loads in environments where ib_insync isn't installed."""
    from ib_insync import Option  # type: ignore[import-untyped]

    right_letter = "C" if signal.right == OptionRight.CALL else "P"
    # IB wants YYYYMMDD as the lastTradeDateOrContractMonth.
    expiry_str = signal.expiry.strftime("%Y%m%d")
    return Option(
        symbol=signal.ticker,
        lastTradeDateOrContractMonth=expiry_str,
        strike=float(signal.strike),
        right=right_letter,
        exchange=exchange,
        currency=currency,
    )


def format_contract_key(signal: Signal) -> str:
    """Stable string key for a contract used in logs and dedup keys."""
    side = "C" if signal.right == OptionRight.CALL else "P"
    return f"{signal.ticker}_{signal.expiry.strftime('%Y%m%d')}_{signal.strike:g}{side}"
