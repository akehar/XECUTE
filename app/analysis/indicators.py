"""Pure indicator math. Hand-rolled in pandas so we don't take pandas-ta as a
hard dep (it has a numpy<2 pin issue on some setups). Outputs match the
standard Wilder-smoothed conventions used by most charting platforms.

All functions assume a DataFrame with columns: open, high, low, close, volume
and a DatetimeIndex sorted ascending. Series-only helpers take the relevant
column directly.
"""
from __future__ import annotations

import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def vwap_intraday(df: pd.DataFrame) -> pd.Series:
    """Cumulative VWAP per session (resets each calendar date in the index)."""
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = typical * df["volume"]
    dates = df.index.date
    return pv.groupby(dates).cumsum() / df["volume"].groupby(dates).cumsum()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    # Wilder smoothing == EMA with alpha=1/n.
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    out = 100.0 - (100.0 / (1.0 + rs))
    # When there are no losses the formula gives inf; report that as 100.
    return out.fillna(100.0).where(avg_loss != 0, 100.0)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    high_low = df["high"] - df["low"]
    high_pc = (df["high"] - prev_close).abs()
    low_pc = (df["low"] - prev_close).abs()
    tr = pd.concat([high_low, high_pc, low_pc], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def average_volume(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    return df["volume"].rolling(window=lookback, min_periods=1).mean()
