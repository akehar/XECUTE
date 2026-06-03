"""The seven individual pre-trade checks. Each is a pure function: takes inputs
and config, returns CheckResult. Reasons are written for the audit log on
/signal/{id}.

All checks default to PASS-rather-than-error when an indicator can't be computed
on the input bars (e.g. not enough lookback). The engine logs a separate
'insufficient_data' note so the operator sees what happened, but the signal
isn't rejected for an environmental issue. Hard rejects only fire when the
indicator clearly says "no".
"""
from __future__ import annotations

import math

import pandas as pd

from app.analysis.config import AnalysisConfig
from app.analysis.indicators import atr, average_volume, ema, rsi, vwap_intraday
from app.analysis.inputs import AnalysisInputs, OptionLiquidity
from app.shared.enums import FlowVerdict, OptionRight
from app.shared.models import CheckResult, Signal


def _latest(series: pd.Series) -> float | None:
    if series.empty:
        return None
    val = series.iloc[-1]
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    return float(val)


def check_trend(signal: Signal, bars_5m: pd.DataFrame, cfg: AnalysisConfig) -> CheckResult:
    if len(bars_5m) < cfg.ema_slow:
        return CheckResult(name="trend", passed=True,
                           reason=f"insufficient bars ({len(bars_5m)} < {cfg.ema_slow})",
                           value=None, threshold=f"{cfg.ema_fast}>{cfg.ema_slow} for calls")
    fast = _latest(ema(bars_5m["close"], cfg.ema_fast))
    slow = _latest(ema(bars_5m["close"], cfg.ema_slow))
    if fast is None or slow is None:
        return CheckResult(name="trend", passed=True, reason="ema computation produced NaN",
                           value=None, threshold=None)
    if signal.right == OptionRight.CALL:
        passed = fast > slow
        reason = f"call trend OK (9EMA {fast:.2f} > 21EMA {slow:.2f})" if passed \
                 else f"call rejects: 9EMA {fast:.2f} not above 21EMA {slow:.2f}"
    else:
        passed = fast < slow
        reason = f"put trend OK (9EMA {fast:.2f} < 21EMA {slow:.2f})" if passed \
                 else f"put rejects: 9EMA {fast:.2f} not below 21EMA {slow:.2f}"
    return CheckResult(name="trend", passed=passed, reason=reason,
                       value=f"fast={fast:.2f},slow={slow:.2f}",
                       threshold=f"{cfg.ema_fast}vs{cfg.ema_slow}")


def check_vwap(signal: Signal, bars_5m: pd.DataFrame, cfg: AnalysisConfig) -> CheckResult:
    if bars_5m.empty:
        return CheckResult(name="vwap", passed=True, reason="no bars", value=None)
    vwap_val = _latest(vwap_intraday(bars_5m))
    price = float(bars_5m["close"].iloc[-1])
    if vwap_val is None or vwap_val <= 0:
        return CheckResult(name="vwap", passed=True, reason="vwap not computable", value=None)
    if signal.right == OptionRight.CALL:
        passed = price > vwap_val
        reason = f"call OK (price {price:.2f} > VWAP {vwap_val:.2f})" if passed \
                 else f"call rejects: price {price:.2f} not above VWAP {vwap_val:.2f}"
    else:
        passed = price < vwap_val
        reason = f"put OK (price {price:.2f} < VWAP {vwap_val:.2f})" if passed \
                 else f"put rejects: price {price:.2f} not below VWAP {vwap_val:.2f}"
    return CheckResult(name="vwap", passed=passed, reason=reason,
                       value=f"price={price:.2f},vwap={vwap_val:.2f}")


def check_volume(signal: Signal, bars_5m: pd.DataFrame, cfg: AnalysisConfig) -> CheckResult:
    if len(bars_5m) < 2:
        return CheckResult(name="volume", passed=True, reason="not enough bars", value=None)
    last_vol = float(bars_5m["volume"].iloc[-1])
    avg_vol = float(average_volume(bars_5m.iloc[:-1], cfg.volume_lookback).iloc[-1] or 0.0)
    if avg_vol <= 0:
        return CheckResult(name="volume", passed=True, reason="zero avg volume", value=None)
    ratio = last_vol / avg_vol
    passed = ratio > cfg.volume_multiplier
    return CheckResult(
        name="volume", passed=passed,
        reason=f"volume {ratio:.2f}x avg "
               f"({'>' if passed else '<='} {cfg.volume_multiplier}x threshold)",
        value=f"last={last_vol:.0f},avg={avg_vol:.0f},ratio={ratio:.2f}",
        threshold=f">{cfg.volume_multiplier}x",
    )


def check_rsi(signal: Signal, bars_5m: pd.DataFrame, cfg: AnalysisConfig) -> CheckResult:
    if len(bars_5m) < cfg.rsi_period + 1:
        return CheckResult(name="rsi", passed=True, reason="insufficient bars for RSI",
                           value=None)
    val = _latest(rsi(bars_5m["close"], cfg.rsi_period))
    if val is None:
        return CheckResult(name="rsi", passed=True, reason="rsi NaN", value=None)
    if signal.right == OptionRight.CALL:
        passed = val <= cfg.rsi_call_max
        reason = f"call OK (RSI {val:.1f} <= {cfg.rsi_call_max})" if passed \
                 else f"call rejects: RSI {val:.1f} > {cfg.rsi_call_max} (chasing)"
        threshold = f"<= {cfg.rsi_call_max}"
    else:
        passed = val >= cfg.rsi_put_min
        reason = f"put OK (RSI {val:.1f} >= {cfg.rsi_put_min})" if passed \
                 else f"put rejects: RSI {val:.1f} < {cfg.rsi_put_min} (chasing)"
        threshold = f">= {cfg.rsi_put_min}"
    return CheckResult(name="rsi", passed=passed, reason=reason, value=f"{val:.1f}",
                       threshold=threshold)


def check_atr(signal: Signal, bars_daily: pd.DataFrame, cfg: AnalysisConfig) -> CheckResult:
    if len(bars_daily) < cfg.atr_period + 1:
        return CheckResult(name="atr", passed=True, reason="insufficient daily bars",
                           value=None)
    val = _latest(atr(bars_daily, cfg.atr_period))
    if val is None or val <= 0:
        return CheckResult(name="atr", passed=True, reason="atr not computable", value=None)
    cap = val * cfg.atr_multiplier
    premium = float(signal.price)
    passed = premium <= cap
    return CheckResult(
        name="atr", passed=passed,
        reason=f"premium ${premium:.2f} {'<=' if passed else '>'} {cfg.atr_multiplier}x ATR ${cap:.2f}",
        value=f"premium={premium:.2f},atr={val:.2f},cap={cap:.2f}",
        threshold=f"premium <= {cfg.atr_multiplier} * ATR",
    )


def check_liquidity(signal: Signal, liq: OptionLiquidity, cfg: AnalysisConfig) -> CheckResult:
    if liq.bid is None or liq.ask is None or liq.bid <= 0 or liq.ask <= 0:
        # No quote at all is itself a reject — we can't price a sensible limit.
        return CheckResult(name="liquidity", passed=False, reason="no live bid/ask",
                           value=None)
    mid = liq.mid
    spread = liq.spread
    if mid is None or mid <= 0:
        return CheckResult(name="liquidity", passed=False, reason="mid not computable",
                           value=None)
    spread_pct = (spread / mid) if spread is not None else None
    if spread_pct is None:
        return CheckResult(name="liquidity", passed=False, reason="spread not computable",
                           value=None)
    spread_ok = spread_pct < cfg.max_spread_pct
    oi_ok = True
    if liq.open_interest is not None:
        oi_ok = liq.open_interest > cfg.min_open_interest
    passed = spread_ok and oi_ok
    oi_part = (f"OI {liq.open_interest}" if liq.open_interest is not None else "OI n/a")
    reason = (
        f"spread {spread_pct:.2%} of mid ({'<' if spread_ok else '>='} {cfg.max_spread_pct:.0%}), "
        f"{oi_part} ({'>' if oi_ok else '<='} {cfg.min_open_interest})"
    )
    return CheckResult(
        name="liquidity", passed=passed, reason=reason,
        value=f"bid={liq.bid:.2f},ask={liq.ask:.2f},spread_pct={spread_pct:.3f},oi={liq.open_interest}",
        threshold=f"spread<{cfg.max_spread_pct:.0%}, OI>{cfg.min_open_interest}",
    )


def check_flow(signal: Signal, flow, cfg: AnalysisConfig) -> CheckResult:
    """flow: FlowData | None. None or inconclusive flow passes when FLOW_FAIL_MODE
    is inconclusive_passes (default); else fails closed. The fail-mode wiring lives
    in the engine — this check only judges whether the flow direction contradicts."""
    if flow is None:
        return CheckResult(name="flow", passed=True, reason="no flow data",
                           value=None)
    if flow.inconclusive or flow.verdict == FlowVerdict.INCONCLUSIVE:
        return CheckResult(name="flow", passed=True,
                           reason="flow inconclusive", value=None)
    call_p = max(flow.call_premium, 0.0)
    put_p = max(flow.put_premium, 0.0)
    if signal.right == OptionRight.CALL:
        # Bearish ratio = put_p / call_p.  Reject if put_p / call_p > threshold.
        ratio = (put_p / call_p) if call_p > 0 else float("inf")
        passed = ratio < cfg.flow_against_ratio
        reason = (f"calls OK: put/call premium ratio {ratio:.2f} < {cfg.flow_against_ratio}"
                  if passed else
                  f"calls rejected: put/call premium ratio {ratio:.2f} >= {cfg.flow_against_ratio} (strongly against)")
    else:
        ratio = (call_p / put_p) if put_p > 0 else float("inf")
        passed = ratio < cfg.flow_against_ratio
        reason = (f"puts OK: call/put premium ratio {ratio:.2f} < {cfg.flow_against_ratio}"
                  if passed else
                  f"puts rejected: call/put premium ratio {ratio:.2f} >= {cfg.flow_against_ratio} (strongly against)")
    return CheckResult(
        name="flow", passed=passed, reason=reason,
        value=f"call_prem={call_p:.0f},put_prem={put_p:.0f},against_ratio={ratio:.2f}",
        threshold=f"against_ratio < {cfg.flow_against_ratio}",
    )
