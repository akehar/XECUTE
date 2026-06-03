"""Indicator math sanity checks on synthetic series."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from app.analysis.indicators import atr, average_volume, ema, rsi, vwap_intraday


def _bars(closes: list[float], highs=None, lows=None, vols=None,
          start: str = "2026-05-22 09:30") -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range(start, periods=n, freq="5min")
    highs = highs or [c + 0.5 for c in closes]
    lows = lows or [c - 0.5 for c in closes]
    vols = vols or [1000] * n
    return pd.DataFrame({"open": closes, "high": highs, "low": lows,
                         "close": closes, "volume": vols}, index=idx)


class TestEMA:
    def test_constant_series_converges_to_value(self):
        s = pd.Series([10.0] * 50)
        result = ema(s, 9)
        assert result.iloc[-1] == pytest.approx(10.0)

    def test_monotonic_up_produces_increasing_ema(self):
        s = pd.Series(range(1, 51), dtype=float)
        result = ema(s, 9)
        # The latest EMA should be > the value 10 bars ago.
        assert result.iloc[-1] > result.iloc[-10]

    def test_fast_above_slow_when_trending_up(self):
        s = pd.Series(range(1, 51), dtype=float)
        assert ema(s, 9).iloc[-1] > ema(s, 21).iloc[-1]

    def test_fast_below_slow_when_trending_down(self):
        s = pd.Series(range(50, 0, -1), dtype=float)
        assert ema(s, 9).iloc[-1] < ema(s, 21).iloc[-1]


class TestVWAP:
    def test_single_bar_vwap_equals_typical(self):
        df = _bars([100.0])
        vwap = vwap_intraday(df)
        # typical = (100+0.5 + 100-0.5 + 100)/3 = 100
        assert vwap.iloc[-1] == pytest.approx(100.0)

    def test_vwap_volume_weighted(self):
        df = _bars(closes=[100.0, 110.0], vols=[1000, 9000])
        vwap = vwap_intraday(df)
        # second bar dominates: vwap should be much closer to 110 than 100
        assert vwap.iloc[-1] > 108

    def test_vwap_resets_each_day(self):
        idx = pd.date_range("2026-05-22 09:30", periods=4, freq="5min").tolist() + \
              pd.date_range("2026-05-23 09:30", periods=4, freq="5min").tolist()
        closes = [100, 100, 100, 100, 200, 200, 200, 200]
        df = pd.DataFrame(
            {"open": closes,
             "high": [c + 1 for c in closes],
             "low":  [c - 1 for c in closes],
             "close": closes,
             "volume": [1000]*8},
            index=pd.DatetimeIndex(idx),
        )
        vwap = vwap_intraday(df)
        # On the second day VWAP should reflect day-2 typical price only, not blend with day 1.
        assert vwap.iloc[-1] == pytest.approx(200.0, abs=1.0)
        assert vwap.iloc[3] == pytest.approx(100.0, abs=1.0)


class TestRSI:
    def test_pure_uptrend_rsi_high(self):
        s = pd.Series(np.linspace(100, 120, 30))
        val = rsi(s, period=14).iloc[-1]
        assert val > 85  # pure uptrend pegs RSI

    def test_pure_downtrend_rsi_low(self):
        s = pd.Series(np.linspace(120, 100, 30))
        val = rsi(s, period=14).iloc[-1]
        assert val < 20

    def test_flat_series_rsi_mid(self):
        s = pd.Series([100.0] * 30)
        val = rsi(s, period=14).iloc[-1]
        # flat → no gain, no loss; our convention returns 100 in that case.
        assert val == 100.0 or math.isnan(val) or val == 50.0


class TestATR:
    def test_atr_increases_with_range(self):
        tight = _bars([100]*30, highs=[100.1]*30, lows=[99.9]*30)
        wide = _bars([100]*30, highs=[105]*30, lows=[95]*30)
        atr_tight = atr(tight, period=14).iloc[-1]
        atr_wide = atr(wide, period=14).iloc[-1]
        assert atr_wide > atr_tight

    def test_atr_with_synthetic_range(self):
        df = _bars([100]*30, highs=[102]*30, lows=[98]*30)
        # True range = high - low = 4 every bar
        val = atr(df, period=14).iloc[-1]
        assert val == pytest.approx(4.0, abs=0.1)


class TestAverageVolume:
    def test_rolling_average(self):
        vols = [100, 200, 300, 400]
        df = _bars([100]*4, vols=vols)
        avg = average_volume(df, lookback=2)
        # Last value is mean of last 2 volumes = 350
        assert avg.iloc[-1] == pytest.approx(350.0)
