from __future__ import annotations

import json
import re
from statistics import mean
from typing import Any

from model_release.blum_finance.schemas import FinancialReasoningResponse
from model_release.evaluation.metrics import (
    EvaluationMetrics,
    bootstrap_ci,
    expected_calibration_error,
)


NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?%?")


def evaluate_predictions(
    *,
    model_revision: str,
    examples: list[dict[str, Any]],
    predictions: list[dict[str, Any] | None],
    seed: int = 20260728,
) -> tuple[EvaluationMetrics, list[dict[str, Any]]]:
    if len(examples) != len(predictions):
        raise ValueError("Examples and predictions must have identical lengths.")
    traces = [
        score_prediction(example=example, prediction=prediction)
        for example, prediction in zip(examples, predictions, strict=True)
    ]
    aggregate_values = [trace["aggregate_score"] for trace in traces]
    aggregate_ci = bootstrap_ci(aggregate_values, seed=seed)
    confidences = [
        trace["confidence"]
        for trace in traces
        if trace["calibration_outcome"] is not None
    ]
    outcomes = [
        trace["calibration_outcome"]
        for trace in traces
        if trace["calibration_outcome"] is not None
    ]
    metric = EvaluationMetrics(
        model_revision=model_revision,
        sample_size=len(traces),
        aggregate_score=_average(traces, "aggregate_score"),
        aggregate_ci_lower=float(aggregate_ci.lower or 0.0),
        structured_validity=_average(traces, "structured_validity"),
        evidence_attribution_precision=_average(
            traces, "evidence_attribution_precision"
        ),
        contradiction_coverage=_average(traces, "contradiction_coverage"),
        invalidation_completeness=_average(
            traces, "invalidation_completeness"
        ),
        risk_completeness=_average(traces, "risk_completeness"),
        abstention_accuracy=_average(traces, "abstention_accuracy"),
        numerical_consistency=_average(traces, "numerical_consistency"),
        no_fabrication=_average(traces, "no_fabrication"),
        calibration_error=expected_calibration_error(
            confidences,
            outcomes,
            bins=10,
        ),
        calibration_sample_size=len(outcomes),
    )
    return metric, traces


def score_prediction(
    *,
    example: dict[str, Any],
    prediction: dict[str, Any] | None,
) -> dict[str, Any]:
    target = _target_response(example)
    parsed_prediction = _parse_prediction(prediction)
    structured = 1.0 if parsed_prediction is not None else 0.0
    if parsed_prediction is None:
        return {
            "example_id": example.get("example_id"),
            "structured_validity": 0.0,
            "evidence_attribution_precision": 0.0,
            "contradiction_coverage": 0.0,
            "invalidation_completeness": 0.0,
            "risk_completeness": 0.0,
            "abstention_accuracy": 0.0,
            "numerical_consistency": 0.0,
            "no_fabrication": 0.0,
            "confidence": 0.0,
            "calibration_outcome": _calibration_outcome(example),
            "aggregate_score": 0.0,
        }

    evidence = example.get("evidence") or {}
    allowed_claims = _texts(
        evidence.get("supporting"),
        evidence.get("contradicting"),
        evidence.get("risks"),
    )
    predicted_claims = (
        parsed_prediction.bull_case
        + parsed_prediction.bear_case
        + parsed_prediction.risks
    )
    attribution = _claim_precision(predicted_claims, allowed_claims)
    contradiction = _coverage(
        parsed_prediction.bear_case,
        target.bear_case,
    )
    invalidation = 1.0 if parsed_prediction.invalidation_conditions else 0.0
    risks = 1.0 if parsed_prediction.risks else 0.0
    target_abstains = target.status == "insufficient_evidence"
    prediction_abstains = parsed_prediction.status == "insufficient_evidence"
    abstention = 1.0 if target_abstains == prediction_abstains else 0.0
    allowed_numbers = _numbers(json.dumps(example.get("evidence") or {}))
    factual_prediction = parsed_prediction.model_dump(mode="json")
    factual_prediction.pop("confidence", None)
    predicted_numbers = _numbers(json.dumps(factual_prediction))
    numerical = 1.0 if predicted_numbers.issubset(allowed_numbers) else 0.0
    no_fabrication = round((attribution + numerical) / 2, 6)
    components = [
        structured,
        attribution,
        contradiction,
        invalidation,
        risks,
        abstention,
        numerical,
        no_fabrication,
    ]
    return {
        "example_id": example.get("example_id"),
        "structured_validity": structured,
        "evidence_attribution_precision": attribution,
        "contradiction_coverage": contradiction,
        "invalidation_completeness": invalidation,
        "risk_completeness": risks,
        "abstention_accuracy": abstention,
        "numerical_consistency": numerical,
        "no_fabrication": no_fabrication,
        "confidence": parsed_prediction.confidence / 100,
        "calibration_outcome": _calibration_outcome(example),
        "aggregate_score": round(mean(components), 6),
    }


def _target_response(example: dict[str, Any]) -> FinancialReasoningResponse:
    assistant = example["messages"][-1]["content"]
    return FinancialReasoningResponse.model_validate_json(assistant)


def _parse_prediction(
    prediction: dict[str, Any] | None,
) -> FinancialReasoningResponse | None:
    if prediction is None:
        return None
    try:
        return FinancialReasoningResponse.model_validate(prediction)
    except ValueError:
        return None


def _calibration_outcome(example: dict[str, Any]) -> int | None:
    label = str((example.get("outcome") or {}).get("label") or "").lower()
    if label == "correct":
        return 1
    if label == "wrong":
        return 0
    return None


def _claim_precision(predicted: list[str], allowed: list[str]) -> float:
    if not predicted:
        return 1.0 if not allowed else 0.0
    supported = sum(
        1
        for claim in predicted
        if any(_token_overlap(claim, reference) >= 0.6 for reference in allowed)
    )
    return round(supported / len(predicted), 6)


def _coverage(predicted: list[str], target: list[str]) -> float:
    if not target:
        return 1.0
    covered = sum(
        1
        for reference in target
        if any(_token_overlap(claim, reference) >= 0.6 for claim in predicted)
    )
    return round(covered / len(target), 6)


def _token_overlap(left: str, right: str) -> float:
    left_tokens = {token for token in re.findall(r"[a-z0-9]+", left.lower()) if len(token) > 2}
    right_tokens = {token for token in re.findall(r"[a-z0-9]+", right.lower()) if len(token) > 2}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _numbers(value: str) -> set[str]:
    return set(NUMBER_PATTERN.findall(value))


def _texts(*groups: Any) -> list[str]:
    result: list[str] = []
    for group in groups:
        if isinstance(group, list):
            result.extend(str(item) for item in group)
        elif isinstance(group, str):
            result.append(group)
    return result


def _average(rows: list[dict[str, Any]], key: str) -> float:
    return round(mean(float(row[key]) for row in rows), 6) if rows else 0.0
