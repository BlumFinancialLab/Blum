from __future__ import annotations

from pydantic import BaseModel

from model_release.evaluation.metrics import EvaluationMetrics


class PromotionDecision(BaseModel):
    promoted: bool
    reasons: list[str]
    aggregate_delta: float
    base_revision: str
    candidate_revision: str


def promotion_gate(
    *,
    base: EvaluationMetrics,
    candidate: EvaluationMetrics,
    minimum_test_samples: int = 50,
) -> PromotionDecision:
    reasons: list[str] = []
    if candidate.sample_size < minimum_test_samples:
        reasons.append("insufficient_test_sample")
    if candidate.aggregate_score <= base.aggregate_score:
        reasons.append("no_target_metric_improvement")
    if candidate.aggregate_ci_lower < base.aggregate_ci_lower:
        reasons.append("aggregate_confidence_interval_regression")
    if candidate.no_fabrication < base.no_fabrication - 0.02:
        reasons.append("no_fabrication_regression")
    if candidate.structured_validity < 0.95:
        reasons.append("structured_validity_below_gate")
    if candidate.risk_completeness < base.risk_completeness - 0.02:
        reasons.append("risk_completeness_regression")
    if candidate.invalidation_completeness < base.invalidation_completeness - 0.02:
        reasons.append("invalidation_completeness_regression")
    if candidate.calibration_error > base.calibration_error + 0.02:
        reasons.append("confidence_calibration_regression")
    return PromotionDecision(
        promoted=not reasons,
        reasons=reasons,
        aggregate_delta=round(
            candidate.aggregate_score - base.aggregate_score,
            6,
        ),
        base_revision=base.model_revision,
        candidate_revision=candidate.model_revision,
    )
