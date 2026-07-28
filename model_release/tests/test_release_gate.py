from __future__ import annotations

from model_release.evaluation.metrics import EvaluationMetrics
from model_release.release.build_repository import promotion_gate


def metrics(**overrides: float | int | str) -> EvaluationMetrics:
    payload = {
        "model_revision": "a" * 40,
        "sample_size": 120,
        "aggregate_score": 0.61,
        "aggregate_ci_lower": 0.58,
        "structured_validity": 0.97,
        "evidence_attribution_precision": 0.72,
        "contradiction_coverage": 0.70,
        "invalidation_completeness": 0.76,
        "risk_completeness": 0.79,
        "abstention_accuracy": 0.84,
        "numerical_consistency": 0.96,
        "no_fabrication": 0.93,
        "calibration_error": 0.11,
    }
    payload.update(overrides)
    return EvaluationMetrics.model_validate(payload)


def test_candidate_with_hallucination_regression_is_rejected() -> None:
    decision = promotion_gate(
        base=metrics(aggregate_score=0.61, no_fabrication=0.93),
        candidate=metrics(aggregate_score=0.70, no_fabrication=0.84),
    )

    assert decision.promoted is False
    assert "no_fabrication_regression" in decision.reasons


def test_candidate_with_low_absolute_no_fabrication_is_rejected() -> None:
    decision = promotion_gate(
        base=metrics(aggregate_score=0.30, no_fabrication=0.20),
        candidate=metrics(
            aggregate_score=0.70,
            aggregate_ci_lower=0.64,
            no_fabrication=0.43,
        ),
    )

    assert decision.promoted is False
    assert "no_fabrication_below_gate" in decision.reasons


def test_candidate_with_better_evidence_and_no_regression_is_promoted() -> None:
    decision = promotion_gate(
        base=metrics(aggregate_score=0.61, aggregate_ci_lower=0.58),
        candidate=metrics(
            model_revision="b" * 40,
            aggregate_score=0.68,
            aggregate_ci_lower=0.64,
            structured_validity=0.98,
            no_fabrication=0.94,
        ),
    )

    assert decision.promoted is True
    assert decision.aggregate_delta == 0.07


def test_candidate_without_enough_test_samples_is_rejected() -> None:
    decision = promotion_gate(
        base=metrics(sample_size=120),
        candidate=metrics(sample_size=20, aggregate_score=0.80),
    )

    assert decision.promoted is False
    assert "insufficient_test_sample" in decision.reasons
