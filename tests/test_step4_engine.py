"""Engine integration: combined pass/fail logic, toggles, fail-mode handling."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from app.analysis.config import AnalysisConfig
from app.analysis.engine import run_analysis
from app.analysis.inputs import AnalysisInputs, OptionLiquidity
from app.shared.enums import FlowVerdict, OptionRight, SignalAction, SignalSource
from app.shared.models import FlowData, Signal


def _signal(right: OptionRight = OptionRight.CALL, price: float = 1.50) -> Signal:
    return Signal(
        source=SignalSource.DISCORD, action=SignalAction.BTO, ticker="SPY",
        strike=500.0, right=right,
        expiry=date.today() + timedelta(days=7), price=price,
    )


def _wavy_uptrend(start: float = 100.0, end: float = 105.0, n: int = 40) -> np.ndarray:
    """Linear drift up plus an oscillation big enough to produce some negative deltas
    so RSI lands in the 60-75 range (not pegged at 100)."""
    base = np.linspace(start, end, n)
    osc = np.sin(np.linspace(0, 4 * np.pi, n)) * 1.5
    return base + osc


def _bars_5m_uptrend() -> pd.DataFrame:
    idx = pd.date_range("2026-05-22 09:30", periods=40, freq="5min")
    closes = _wavy_uptrend()
    vols = [1000] * 39 + [5000]
    return pd.DataFrame(
        {"open": closes, "high": closes + 0.5, "low": closes - 0.5,
         "close": closes, "volume": vols}, index=idx,
    )


def _bars_5m_downtrend() -> pd.DataFrame:
    idx = pd.date_range("2026-05-22 09:30", periods=40, freq="5min")
    closes = _wavy_uptrend(start=105.0, end=100.0)
    vols = [1000] * 39 + [5000]
    return pd.DataFrame(
        {"open": closes, "high": closes + 0.5, "low": closes - 0.5,
         "close": closes, "volume": vols}, index=idx,
    )


def _bars_daily() -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=20, freq="1D")
    closes = [500] * 20
    return pd.DataFrame(
        {"open": closes, "high": [503] * 20, "low": [497] * 20,
         "close": closes, "volume": [1_000_000] * 20}, index=idx,
    )


def _flow_bullish() -> FlowData:
    return FlowData(
        ticker="SPY", window_minutes=30,
        call_premium=200_000, put_premium=50_000, net_premium=150_000,
        verdict=FlowVerdict.BULLISH, as_of=datetime.now(timezone.utc),
    )


_UNSET = object()  # sentinel so flow=None can be distinguished from "not specified"


def _inputs(
    bars_5m=None, bars_daily=None, flow=_UNSET,
    bid=1.48, ask=1.52, oi=5000, underlying=105.0,
) -> AnalysisInputs:
    return AnalysisInputs(
        bars_5m=bars_5m if bars_5m is not None else _bars_5m_uptrend(),
        bars_daily=bars_daily if bars_daily is not None else _bars_daily(),
        underlying_price=underlying,
        option_liquidity=OptionLiquidity(bid=bid, ask=ask, open_interest=oi),
        flow=_flow_bullish() if flow is _UNSET else flow,
    )


class TestEngineHappyPath:
    def test_clean_bullish_setup_passes_all_checks(self):
        report = run_analysis(_signal(right=OptionRight.CALL), _inputs())
        assert report.overall_pass, [c.reason for c in report.failing_checks()]
        # Every default check ran.
        names = [c.name for c in report.checks]
        assert {"trend", "vwap", "volume", "rsi", "atr", "liquidity", "flow"}.issubset(names)

    def test_bearish_signal_in_uptrend_fails_trend_and_vwap(self):
        report = run_analysis(_signal(right=OptionRight.PUT), _inputs())
        assert not report.overall_pass
        failing = {c.name for c in report.failing_checks()}
        assert "trend" in failing
        assert "vwap" in failing


class TestEngineToggles:
    def test_disabling_trend_skips_check(self):
        cfg = AnalysisConfig(check_trend=False)
        report = run_analysis(_signal(), _inputs(), cfg)
        names = [c.name for c in report.checks]
        assert "trend" not in names

    def test_disabling_all_checks_still_returns_report(self):
        cfg = AnalysisConfig(
            check_trend=False, check_vwap=False, check_volume=False,
            check_rsi=False, check_atr=False, check_liquidity=False,
            check_flow=False,
        )
        report = run_analysis(_signal(), _inputs(), cfg)
        assert report.checks == []
        # all([]) == True; with no checks the signal passes trivially.
        assert report.overall_pass


class TestEngineLiquidity:
    def test_no_quote_fails_overall_even_with_all_else_passing(self):
        report = run_analysis(
            _signal(),
            _inputs(bid=None, ask=None),
        )
        assert not report.overall_pass
        liq = [c for c in report.checks if c.name == "liquidity"][0]
        assert not liq.passed

    def test_wide_spread_fails_overall(self):
        report = run_analysis(_signal(), _inputs(bid=1.00, ask=1.50))
        assert not report.overall_pass


class TestEngineFlowFailMode:
    def test_missing_flow_passes_under_inconclusive_default(self):
        report = run_analysis(_signal(), _inputs(flow=None),
                              flow_fail_mode="inconclusive_passes")
        flow_check = [c for c in report.checks if c.name == "flow"][0]
        assert flow_check.passed

    def test_missing_flow_fails_under_fail_closed(self):
        report = run_analysis(_signal(), _inputs(flow=None),
                              flow_fail_mode="fail_closed")
        flow_check = [c for c in report.checks if c.name == "flow"][0]
        assert not flow_check.passed
        assert "fail_closed" in flow_check.reason
        assert not report.overall_pass

    def test_inconclusive_flowdata_fails_under_fail_closed(self):
        # The UW client's degradation paths return FlowData(inconclusive=True),
        # never None. fail_closed must catch that shape too.
        from app.shared.enums import FlowVerdict
        from app.shared.models import FlowData

        inconclusive = FlowData(
            ticker="SPY", window_minutes=30,
            verdict=FlowVerdict.INCONCLUSIVE, inconclusive=True,
        )
        report = run_analysis(_signal(), _inputs(flow=inconclusive),
                              flow_fail_mode="fail_closed")
        flow_check = [c for c in report.checks if c.name == "flow"][0]
        assert not flow_check.passed
        assert not report.overall_pass

    def test_inconclusive_flowdata_passes_under_default(self):
        from app.shared.enums import FlowVerdict
        from app.shared.models import FlowData

        inconclusive = FlowData(
            ticker="SPY", window_minutes=30,
            verdict=FlowVerdict.INCONCLUSIVE, inconclusive=True,
        )
        report = run_analysis(_signal(), _inputs(flow=inconclusive),
                              flow_fail_mode="inconclusive_passes")
        flow_check = [c for c in report.checks if c.name == "flow"][0]
        assert flow_check.passed


class TestEngineReportShape:
    def test_indicators_snapshot_includes_bar_counts_and_quote(self):
        report = run_analysis(_signal(), _inputs())
        assert "bars_5m_count" in report.indicators
        assert "bars_daily_count" in report.indicators
        assert "bid" in report.indicators
        assert "ask" in report.indicators
        assert "mid" in report.indicators

    def test_each_check_has_reason_string(self):
        report = run_analysis(_signal(), _inputs())
        for c in report.checks:
            assert c.reason, f"{c.name} has empty reason"
