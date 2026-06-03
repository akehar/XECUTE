"""Lightweight input containers for the analysis engine.

Kept as dataclasses (not pydantic) so synthetic-data construction in tests stays
ergonomic. The pipeline (Step 6) builds these from real IB + UW responses.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from app.shared.models import FlowData


@dataclass
class OptionLiquidity:
    """Top-of-book + chain stats for the specific option contract under consideration."""
    bid: float | None
    ask: float | None
    open_interest: int | None = None

    @property
    def mid(self) -> float | None:
        if self.bid is None or self.ask is None or self.bid <= 0 or self.ask <= 0:
            return None
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float | None:
        if self.bid is None or self.ask is None or self.bid <= 0 or self.ask <= 0:
            return None
        return self.ask - self.bid


@dataclass
class AnalysisInputs:
    """Everything the engine needs to evaluate one signal.

    bars_5m / bars_1m / bars_daily: DataFrames with columns open/high/low/close/volume
    and a DatetimeIndex sorted ascending. Recent ~60 bars per spec.
    underlying_price: most recent close of the underlying.
    """
    bars_5m: pd.DataFrame
    bars_daily: pd.DataFrame
    underlying_price: float
    option_liquidity: OptionLiquidity
    flow: FlowData | None
    bars_1m: pd.DataFrame | None = None
    meta: dict = field(default_factory=dict)
