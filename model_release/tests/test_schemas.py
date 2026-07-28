from __future__ import annotations

import pytest
from pydantic import ValidationError

from model_release.blum_finance.schemas import (
    FinancialReasoningRequest,
    FinancialReasoningResponse,
)


def test_request_requires_point_in_time_evidence() -> None:
    with pytest.raises(ValidationError):
        FinancialReasoningRequest.model_validate(
            {
                "ticker": "NVDA",
                "as_of": "2026-07-28T10:00:00Z",
                "evidence": [],
            }
        )


def test_response_requires_risk_and_invalidation_for_actionable_state() -> None:
    with pytest.raises(ValidationError):
        FinancialReasoningResponse.model_validate(
            {
                "status": "actionable_if_confirmed",
                "thesis": "Momentum may continue.",
                "bull_case": ["Relative strength is positive."],
                "bear_case": ["Valuation is elevated."],
                "risks": [],
                "invalidation_conditions": [],
                "confidence": 64,
                "what_would_change_the_view": ["A regime change."],
            }
        )


def test_insufficient_evidence_response_can_abstain() -> None:
    response = FinancialReasoningResponse.model_validate(
        {
            "status": "insufficient_evidence",
            "thesis": "There is not enough verified evidence.",
            "bull_case": [],
            "bear_case": [],
            "risks": [],
            "invalidation_conditions": [],
            "confidence": 0,
            "what_would_change_the_view": ["Provide timestamped market evidence."],
        }
    )

    assert response.status == "insufficient_evidence"
