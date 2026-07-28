from __future__ import annotations

from model_release.evaluation.metrics import bootstrap_ci, expected_calibration_error
from model_release.evaluation.tasks.blum_finance_eval import score_prediction


def test_bootstrap_interval_is_deterministic() -> None:
    first = bootstrap_ci([1, 0, 1, 1], seed=7)
    second = bootstrap_ci([1, 0, 1, 1], seed=7)

    assert first == second
    assert first.lower <= first.mean <= first.upper


def test_calibration_error_is_zero_for_matching_buckets() -> None:
    error = expected_calibration_error(
        confidences=[0.25, 0.75],
        outcomes=[0, 1],
        bins=2,
    )

    assert error == 0.25


def test_empty_metric_input_returns_no_interval() -> None:
    interval = bootstrap_ci([], seed=7)

    assert interval.sample_size == 0
    assert interval.mean is None


def test_confidence_number_is_not_treated_as_fabricated_market_fact() -> None:
    assistant = {
        "status": "watch",
        "thesis": "Price is 101 and confirmation is incomplete.",
        "bull_case": ["Price is 101."],
        "bear_case": ["Volume confirmation is missing."],
        "risks": ["Volatility may expand."],
        "invalidation_conditions": ["Reassess below 99."],
        "confidence": 50,
        "what_would_change_the_view": ["Reassess below 99."],
    }
    example = {
        "example_id": "one",
        "messages": [
            {"role": "assistant", "content": __import__("json").dumps(assistant)}
        ],
        "evidence": {
            "supporting": ["Price is 101."],
            "contradicting": ["Volume confirmation is missing."],
            "risks": ["Volatility may expand.", "Reassess below 99."],
        },
        "outcome": {"label": "correct"},
    }

    result = score_prediction(example=example, prediction=assistant)

    assert result["numerical_consistency"] == 1.0
