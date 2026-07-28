from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ReasoningStatus = Literal[
    "avoid",
    "watch",
    "wait_for_trigger",
    "actionable_if_confirmed",
    "manage_open_position",
    "reduce",
    "exit",
    "insufficient_evidence",
]


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str = Field(min_length=1)
    value: Any
    source: str | None = None
    observed_at: datetime | None = None


class FinancialReasoningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, max_length=32)
    as_of: datetime
    horizon: str = "swing"
    market_context: dict[str, Any] = Field(default_factory=dict)
    portfolio_context: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceItem] = Field(min_length=1)
    question: str = "Evaluate the evidence and state what would change the view."


class FinancialReasoningResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ReasoningStatus
    thesis: str = Field(min_length=1)
    bull_case: list[str] = Field(default_factory=list)
    bear_case: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=100)
    what_would_change_the_view: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def require_risk_definition_for_actionable_states(self) -> "FinancialReasoningResponse":
        actionable = {
            "actionable_if_confirmed",
            "manage_open_position",
            "reduce",
            "exit",
        }
        if self.status in actionable and (not self.risks or not self.invalidation_conditions):
            raise ValueError("Actionable states require risks and invalidation conditions.")
        return self
