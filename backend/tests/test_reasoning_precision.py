from app.services.reasoning_precision import (
    benchmark_excess,
    confidence_delta_from_evidence,
    ensemble_disagreement_penalty,
    training_value_score,
)


def test_confidence_cannot_increase_without_strong_evidence():
    assert confidence_delta_from_evidence(strengthening_score=48, decay_score=30) == 0.0


def test_confidence_decays_when_contradictions_dominate():
    assert confidence_delta_from_evidence(strengthening_score=35, decay_score=80) < -2.0


def test_ensemble_disagreement_penalty_rises_when_votes_conflict():
    penalty = ensemble_disagreement_penalty({"bullish": 0.5, "bearish": 0.5})
    assert penalty == 50.0


def test_benchmark_relative_excess_return_is_asset_minus_benchmark():
    assert round(benchmark_excess(0.12, 0.05), 4) == 0.07


def test_training_quality_requires_more_than_reasoning_depth():
    score = training_value_score(
        {
            "reasoning_quality_score": 90,
            "outcome_clarity_score": 20,
            "data_quality_score": 40,
            "contradiction_handling_score": 35,
            "confidence_calibration_score": 40,
            "regime_context_score": 35,
            "benchmark_relevance_score": 20,
            "reproducibility_score": 55,
        }
    )
    assert score < 55
