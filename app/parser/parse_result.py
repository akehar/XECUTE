from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.shared.models import Signal

ParserSource = Literal["regex", "llm", "rejected"]


class ParseResult(BaseModel):
    """Outcome of running a raw text through the parser pipeline."""

    model_config = ConfigDict(use_enum_values=False)

    signal: Signal | None = None
    source: ParserSource
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    field_confidence: dict[str, float] = Field(default_factory=dict)
    reason: str = ""
    raw_text: str = ""
    multileg: bool = False
    llm_attempted: bool = False
    llm_payload: dict | None = None

    @property
    def accepted(self) -> bool:
        return self.signal is not None
