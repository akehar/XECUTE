"""Toggles + thresholds for the pre-trade analysis engine.

Defaults all-ON per spec; the only globally non-toggleable behaviour is that the
engine runs at all (mandatory filter).  Individual checks can be turned off via
config_overrides table (loaded at engine call time in Step 10).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AnalysisConfig:
    # ---- toggles ----
    check_trend: bool = True
    check_vwap: bool = True
    check_volume: bool = True
    check_rsi: bool = True
    check_atr: bool = True
    check_liquidity: bool = True
    check_flow: bool = True

    # ---- trend ----
    ema_fast: int = 9
    ema_slow: int = 21

    # ---- volume ----
    volume_lookback: int = 20
    volume_multiplier: float = 1.2

    # ---- RSI ----
    rsi_period: int = 14
    rsi_call_max: float = 80.0
    rsi_put_min: float = 20.0

    # ---- ATR ----
    atr_period: int = 14
    atr_multiplier: float = 2.0

    # ---- Liquidity ----
    max_spread_pct: float = 0.10
    min_open_interest: int = 100

    # ---- Flow ----
    flow_against_ratio: float = 2.0  # call_prem:put_prem ratio considered "strongly against"

    @classmethod
    def from_settings(cls, settings) -> "AnalysisConfig":
        return cls(
            check_trend=settings.check_trend,
            check_vwap=settings.check_vwap,
            check_volume=settings.check_volume,
            check_rsi=settings.check_rsi,
            check_atr=settings.check_atr,
            check_liquidity=settings.check_liquidity,
            check_flow=settings.check_flow,
        )
