"""Pre-trade analysis engine. Mandatory filter — every signal flows through
run_analysis before the risk engine ever sees it. Individual checks can be
toggled in AnalysisConfig; the engine itself can't be disabled.

flow_fail_mode controls behaviour when Unusual Whales is down or inconclusive:
- "inconclusive_passes" (default): missing flow data does not block the signal
- "fail_closed": missing flow data fails the flow check
"""
from __future__ import annotations

import logging
from typing import Literal

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
from app.analysis.inputs import AnalysisInputs
from app.shared.enums import FlowVerdict
from app.shared.models import AnalysisReport, CheckResult, Signal

logger = logging.getLogger(__name__)

FlowFailMode = Literal["inconclusive_passes", "fail_closed"]


def run_analysis(
    signal: Signal,
    inputs: AnalysisInputs,
    config: AnalysisConfig | None = None,
    flow_fail_mode: FlowFailMode = "inconclusive_passes",
) -> AnalysisReport:
    cfg = config or AnalysisConfig()
    checks: list[CheckResult] = []

    if cfg.check_trend:
        checks.append(check_trend(signal, inputs.bars_5m, cfg))
    if cfg.check_vwap:
        checks.append(check_vwap(signal, inputs.bars_5m, cfg))
    if cfg.check_volume:
        checks.append(check_volume(signal, inputs.bars_5m, cfg))
    if cfg.check_rsi:
        checks.append(check_rsi(signal, inputs.bars_5m, cfg))
    if cfg.check_atr:
        checks.append(check_atr(signal, inputs.bars_daily, cfg))
    if cfg.check_liquidity:
        checks.append(check_liquidity(signal, inputs.option_liquidity, cfg))
    if cfg.check_flow:
        flow_check = check_flow(signal, inputs.flow, cfg)
        # Apply the fail-mode policy when flow is missing/inconclusive. The UW
        # client never returns None — its failure paths return a FlowData with
        # inconclusive=True — so fail_closed must cover both shapes.
        flow_missing = (
            inputs.flow is None
            or inputs.flow.inconclusive
            or inputs.flow.verdict == FlowVerdict.INCONCLUSIVE
        )
        if flow_missing and flow_fail_mode == "fail_closed":
            flow_check = CheckResult(
                name="flow", passed=False,
                reason="flow data missing/inconclusive and flow_fail_mode=fail_closed",
                value=None,
            )
        checks.append(flow_check)

    flow_verdict = (inputs.flow.verdict if inputs.flow is not None
                    else FlowVerdict.INCONCLUSIVE)
    indicators = _snapshot_indicators(inputs)

    overall_pass = all(c.passed for c in checks)
    report = AnalysisReport(
        signal_id=signal.id,
        overall_pass=overall_pass,
        checks=checks,
        indicators=indicators,
        flow_verdict=flow_verdict,
    )
    logger.info(
        "analysis complete",
        extra={"signal_id": signal.id, "overall_pass": overall_pass,
               "fail_names": [c.name for c in report.failing_checks()]},
    )
    return report


def _snapshot_indicators(inputs: AnalysisInputs) -> dict[str, float | str | None]:
    snap: dict[str, float | str | None] = {}
    try:
        snap["bars_5m_count"] = float(len(inputs.bars_5m))
        snap["bars_daily_count"] = float(len(inputs.bars_daily))
        snap["underlying_price"] = float(inputs.underlying_price)
    except Exception:
        pass
    if inputs.option_liquidity is not None:
        snap["bid"] = inputs.option_liquidity.bid
        snap["ask"] = inputs.option_liquidity.ask
        snap["mid"] = inputs.option_liquidity.mid
        if inputs.option_liquidity.open_interest is not None:
            snap["open_interest"] = float(inputs.option_liquidity.open_interest)
    return snap
