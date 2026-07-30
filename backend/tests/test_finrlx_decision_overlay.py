from __future__ import annotations

from app.services.trading_ml.finrlx import QuantPolicyProposal
from app.services.trading_ml.finrlx_overlay import FinRLXDecisionOverlay


def proposal(**overrides) -> QuantPolicyProposal:
    payload = {
        "status": "SHADOW",
        "action": "LONG",
        "directional_score": 0.72,
        "confidence": 0.68,
        "validation_sample_count": 120,
        "directional_accuracy": 0.58,
        "mean_policy_net_r": 0.12,
        "regression_improvement": 0.08,
    }
    payload.update(overrides)
    return QuantPolicyProposal(**payload)


def test_finrlx_overlay_freezes_weak_policy_until_more_evidence() -> None:
    result = FinRLXDecisionOverlay().evaluate(
        baseline_direction="LONG",
        baseline_confidence=0.64,
        proposal=proposal(validation_sample_count=20),
    )

    assert result.applied is False
    assert result.confidence_adjustment == 0.0
    assert result.status == "FROZEN_INSUFFICIENT_EVIDENCE"


def test_finrlx_overlay_adds_bounded_confidence_only_for_validated_alignment() -> None:
    result = FinRLXDecisionOverlay().evaluate(
        baseline_direction="LONG",
        baseline_confidence=0.64,
        proposal=proposal(),
    )

    assert result.applied is True
    assert 0.0 < result.confidence_adjustment <= 0.05
    assert result.require_confirmation is False


def test_finrlx_overlay_cannot_remove_deterministic_blocker() -> None:
    result = FinRLXDecisionOverlay().evaluate(
        baseline_direction="LONG",
        baseline_confidence=0.64,
        proposal=proposal(),
        deterministic_blockers=("STALE_DATA",),
    )

    assert result.applied is False
    assert result.status == "BLOCKED_BY_DETERMINISTIC_AUTHORITY"
    assert result.preserved_blockers == ("STALE_DATA",)
