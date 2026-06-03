from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.shared.enums import (
    FlowVerdict,
    Mode,
    OptionRight,
    OrderStatus,
    SignalAction,
    SignalSource,
    SignalStatus,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Signal(BaseModel):
    """Canonical signal flowing through the pipeline. Single-leg only."""

    model_config = ConfigDict(use_enum_values=False)

    id: str | None = None
    source: SignalSource
    action: SignalAction
    ticker: str
    strike: float
    right: OptionRight
    expiry: date
    price: float = Field(..., description="Signal limit/reference premium per contract")
    stop: float | None = None
    target: float | None = None
    raw_text: str | None = None
    parse_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    received_at: datetime = Field(default_factory=_utcnow)
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ticker")
    @classmethod
    def _upper_ticker(cls, v: str) -> str:
        v = v.strip().upper()
        if not v or not v.isascii():
            raise ValueError("ticker must be non-empty ASCII")
        return v

    @field_validator("strike")
    @classmethod
    def _positive_strike(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("strike must be positive")
        return v

    @field_validator("price")
    @classmethod
    def _positive_price(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("price must be positive")
        return v

    @field_validator("expiry")
    @classmethod
    def _expiry_within_window(cls, v: date) -> date:
        delta = (v - date.today()).days
        if delta < 0:
            raise ValueError("expiry must not be in the past")
        if delta > 60:
            raise ValueError("expiry must be within 60 days")
        return v


class CheckResult(BaseModel):
    name: str
    passed: bool
    reason: str
    value: float | str | None = None
    threshold: float | str | None = None


class AnalysisReport(BaseModel):
    signal_id: str | None = None
    overall_pass: bool
    checks: list[CheckResult]
    indicators: dict[str, float | str | None] = Field(default_factory=dict)
    flow_verdict: FlowVerdict = FlowVerdict.INCONCLUSIVE
    generated_at: datetime = Field(default_factory=_utcnow)

    def failing_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]


class FlowData(BaseModel):
    ticker: str
    window_minutes: int
    call_premium: float = 0.0
    put_premium: float = 0.0
    net_premium: float = 0.0
    verdict: FlowVerdict = FlowVerdict.NEUTRAL
    as_of: datetime = Field(default_factory=_utcnow)
    inconclusive: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class OrderResult(BaseModel):
    signal_id: str | None = None
    mode: Mode
    status: OrderStatus
    ib_order_id: int | None = None
    ib_perm_id: int | None = None
    contracts_requested: int = 0
    contracts_filled: int = 0
    avg_fill_price: float | None = None
    limit_price: float | None = None
    submitted_at: datetime | None = None
    filled_at: datetime | None = None
    error: str | None = None

    @property
    def is_filled(self) -> bool:
        return self.status == OrderStatus.FILLED


class RiskDecision(BaseModel):
    accepted: bool
    reason: str = ""
    rule: str | None = None
    snapshot: dict[str, Any] = Field(default_factory=dict)


class ModeState(BaseModel):
    mode: Mode = Mode.PAPER
    updated_at: datetime = Field(default_factory=_utcnow)
    confirmation_phrase_ok: bool = False


class PipelineOutcome(BaseModel):
    """End-to-end outcome for a single signal: parse → analysis → risk → execution."""

    signal: Signal
    status: SignalStatus
    analysis: AnalysisReport | None = None
    risk: RiskDecision | None = None
    order: OrderResult | None = None
    message: str = ""
