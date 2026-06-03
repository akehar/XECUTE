"""Per-check unit tests on synthetic bars / liquidity / flow."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.analysis.checks import (
    check_atr,
    check_flow,
    check_liquidity,
    check_rsi,
    check_trend,
    check_volume,
    check_vwap,
)
from app.analysis.config import AnalysisConfig
from app.analysis.inputs import OptionLiquidity
from app.shared.enums import FlowVerdict, OptionRight, SignalAction, SignalSource
from app.shared.models import FlowData, Signal


def _signal(right: OptionRight = OptionRight.CALL, price: float = 1.50,
            strike: float = 500.0, ticker: str = "SPY") -> Signal:
    return Signal(
        source=SignalSource.DISCORD,
        action=SignalAction.BTO,
        ticker=ticker,
        strike=strike,
        right=right,
        expiry=date.today() + timedelta(days=7),
        price=price,
    )


def _bars(closes, highs=None, lows=None, vols=None,
          start="2026-05-22 09:30", freq="5min") -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range(start, periods=n, freq=freq)
    highs = highs or [c + 0.5 for c in closes]
    lows = lows or [c - 0.5 for c in closes]
    vols = vols or [1000] * n
    return pd.DataFrame({"open": closes, "high": highs, "low": lows,
                         "close": closes, "volume": vols}, index=idx)


CFG = AnalysisConfig()


# ---------------- trend ----------------

class TestTrend:
    def test_call_passes_in_uptrend(self):
        df = _bars(list(np.linspace(100, 120, 40)))
        r = check_trend(_signal(right=OptionRight.CALL), df, CFG)
        assert r.passed, r.reason

    def test_call_fails_in_downtrend(self):
        df = _bars(list(np.linspace(120, 100, 40)))
        r = check_trend(_signal(right=OptionRight.CALL), df, CFG)
        assert not r.passed, r.reason

    def test_put_passes_in_downtrend(self):
        df = _bars(list(np.linspace(120, 100, 40)))
        r = check_trend(_signal(right=OptionRight.PUT), df, CFG)
        assert r.passed, r.reason

    def test_put_fails_in_uptrend(self):
        df = _bars(list(np.linspace(100, 120, 40)))
        r = check_trend(_signal(right=OptionRight.PUT), df, CFG)
        assert not r.passed, r.reason

    def test_insufficient_bars_passes_with_note(self):
        df = _bars([100.0] * 5)
        r = check_trend(_signal(), df, CFG)
        assert r.passed
        assert "insufficient" in r.reason


# ---------------- vwap ----------------

class TestVWAP:
    def test_call_passes_above_vwap(self):
        # Build a series where the last close is well above the running VWAP.
        closes = [100, 100, 100, 100, 100, 105]
        df = _bars(closes, vols=[1000] * len(closes))
        r = check_vwap(_signal(right=OptionRight.CALL), df, CFG)
        assert r.passed, r.reason

    def test_call_fails_below_vwap(self):
        closes = [100, 100, 100, 100, 100, 95]
        df = _bars(closes, vols=[1000] * len(closes))
        r = check_vwap(_signal(right=OptionRight.CALL), df, CFG)
        assert not r.passed, r.reason

    def test_put_passes_below_vwap(self):
        closes = [100, 100, 100, 100, 100, 95]
        df = _bars(closes, vols=[1000] * len(closes))
        r = check_vwap(_signal(right=OptionRight.PUT), df, CFG)
        assert r.passed, r.reason


# ---------------- volume ----------------

class TestVolume:
    def test_pass_when_current_volume_well_above_average(self):
        vols = [1000] * 19 + [10000]
        df = _bars([100] * 20, vols=vols)
        r = check_volume(_signal(), df, CFG)
        assert r.passed, r.reason

    def test_fail_when_volume_is_average_or_below(self):
        vols = [1000] * 19 + [800]
        df = _bars([100] * 20, vols=vols)
        r = check_volume(_signal(), df, CFG)
        assert not r.passed, r.reason

    def test_zero_average_volume_passes_with_note(self):
        df = _bars([100, 100], vols=[0, 1])
        r = check_volume(_signal(), df, CFG)
        assert r.passed
        assert "zero" in r.reason


# ---------------- rsi ----------------

class TestRSI:
    def test_call_rejected_when_rsi_too_hot(self):
        df = _bars(list(np.linspace(100, 130, 40)))
        r = check_rsi(_signal(right=OptionRight.CALL), df, CFG)
        assert not r.passed, r.reason
        assert "RSI" in r.reason

    def test_call_passes_at_neutral_rsi(self):
        # Slight upward drift but not strong enough to peg RSI.
        closes = [100.0]
        for _ in range(30):
            closes.append(closes[-1] + (0.1 if len(closes) % 2 == 0 else -0.05))
        df = _bars(closes)
        r = check_rsi(_signal(right=OptionRight.CALL), df, CFG)
        assert r.passed, r.reason

    def test_put_rejected_when_rsi_too_cold(self):
        df = _bars(list(np.linspace(130, 100, 40)))
        r = check_rsi(_signal(right=OptionRight.PUT), df, CFG)
        assert not r.passed, r.reason


# ---------------- atr ----------------

class TestATR:
    def test_premium_within_atr_passes(self):
        df = _bars([500] * 20, highs=[503] * 20, lows=[497] * 20, freq="1D",
                   start="2026-01-01")
        # daily ATR ~3, premium = 2.5, cap = 6 → passes
        r = check_atr(_signal(price=2.50), df, CFG)
        assert r.passed, r.reason

    def test_premium_exceeding_atr_cap_fails(self):
        df = _bars([500] * 20, highs=[501] * 20, lows=[499] * 20, freq="1D",
                   start="2026-01-01")
        # daily ATR ~2, premium = 10, cap = 4 → fail
        r = check_atr(_signal(price=10.0), df, CFG)
        assert not r.passed, r.reason

    def test_insufficient_daily_bars_passes_with_note(self):
        df = _bars([500] * 3, freq="1D", start="2026-01-01")
        r = check_atr(_signal(), df, CFG)
        assert r.passed
        assert "insufficient" in r.reason


# ---------------- liquidity ----------------

class TestLiquidity:
    def test_tight_spread_and_high_oi_passes(self):
        liq = OptionLiquidity(bid=1.45, ask=1.55, open_interest=5000)
        r = check_liquidity(_signal(), liq, CFG)
        assert r.passed, r.reason

    def test_wide_spread_fails(self):
        liq = OptionLiquidity(bid=1.00, ask=1.50, open_interest=5000)  # 33% spread
        r = check_liquidity(_signal(), liq, CFG)
        assert not r.passed, r.reason

    def test_low_open_interest_fails(self):
        liq = OptionLiquidity(bid=1.48, ask=1.52, open_interest=50)
        r = check_liquidity(_signal(), liq, CFG)
        assert not r.passed, r.reason

    def test_no_quote_fails(self):
        liq = OptionLiquidity(bid=None, ask=None, open_interest=5000)
        r = check_liquidity(_signal(), liq, CFG)
        assert not r.passed
        assert "bid" in r.reason

    def test_no_oi_uses_spread_only(self):
        liq = OptionLiquidity(bid=1.45, ask=1.55, open_interest=None)
        r = check_liquidity(_signal(), liq, CFG)
        assert r.passed


# ---------------- flow ----------------

def _flow(call_premium: float, put_premium: float,
          verdict: FlowVerdict = FlowVerdict.NEUTRAL,
          inconclusive: bool = False) -> FlowData:
    return FlowData(
        ticker="SPY", window_minutes=30,
        call_premium=call_premium, put_premium=put_premium,
        net_premium=call_premium - put_premium,
        verdict=verdict, inconclusive=inconclusive,
        as_of=datetime.now(timezone.utc),
    )


class TestFlow:
    def test_call_signal_passes_when_calls_dominate(self):
        r = check_flow(_signal(right=OptionRight.CALL),
                       _flow(call_premium=100_000, put_premium=20_000), CFG)
        assert r.passed, r.reason

    def test_call_signal_fails_when_puts_dominate_strongly(self):
        r = check_flow(_signal(right=OptionRight.CALL),
                       _flow(call_premium=10_000, put_premium=30_000), CFG)
        assert not r.passed, r.reason

    def test_put_signal_passes_when_puts_dominate(self):
        r = check_flow(_signal(right=OptionRight.PUT),
                       _flow(call_premium=10_000, put_premium=100_000), CFG)
        assert r.passed, r.reason

    def test_inconclusive_flow_passes(self):
        r = check_flow(_signal(),
                       _flow(call_premium=0, put_premium=0,
                             verdict=FlowVerdict.INCONCLUSIVE, inconclusive=True), CFG)
        assert r.passed
        assert "inconclusive" in r.reason

    def test_no_flow_data_passes(self):
        r = check_flow(_signal(), None, CFG)
        assert r.passed
