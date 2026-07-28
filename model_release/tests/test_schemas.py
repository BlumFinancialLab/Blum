from __future__ import annotations

import pytest
from pydantic import ValidationError

from model_release.blum_finance.schemas import (
    FinancialReasoningRequest,
    FinancialReasoningResponse,
)
from model_release.blum_finance.inference import BlumFinancePipeline


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


def test_pipeline_can_dispatch_to_explicit_mlx_runtime(monkeypatch) -> None:
    pipeline = BlumFinancePipeline(runtime="mlx")
    monkeypatch.setattr(
        pipeline,
        "_generate_with_mlx",
        lambda messages: (
            '{"status":"watch","thesis":"Wait for confirmation.",'
            '"bull_case":[],"bear_case":[],"risks":[],"invalidation_conditions":[],'
            '"confidence":42,"what_would_change_the_view":["New evidence."]}'
        ),
    )

    response = pipeline.generate(
        {
            "ticker": "NVDA",
            "as_of": "2026-07-28T10:00:00Z",
            "evidence": [{"type": "technical", "value": "Volume is incomplete."}],
        }
    )

    assert response.status == "watch"
    assert response.confidence == 42
