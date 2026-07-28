from __future__ import annotations

import math
import random
from statistics import mean
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field


class ConfidenceInterval(BaseModel):
    mean: float | None
    lower: float | None
    upper: float | None
    sample_size: int
    confidence: float = 0.95


class EvaluationMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    sample_size: int = Field(ge=0)
    aggregate_score: float = Field(ge=0, le=1)
    aggregate_ci_lower: float = Field(ge=0, le=1)
    structured_validity: float = Field(ge=0, le=1)
    evidence_attribution_precision: float = Field(ge=0, le=1)
    contradiction_coverage: float = Field(ge=0, le=1)
    invalidation_completeness: float = Field(ge=0, le=1)
    risk_completeness: float = Field(ge=0, le=1)
    abstention_accuracy: float = Field(ge=0, le=1)
    numerical_consistency: float = Field(ge=0, le=1)
    no_fabrication: float = Field(ge=0, le=1)
    calibration_error: float = Field(ge=0, le=1)


def bootstrap_ci(
    values: Iterable[float],
    *,
    seed: int,
    confidence: float = 0.95,
    resamples: int = 2_000,
) -> ConfidenceInterval:
    observed = [float(value) for value in values if math.isfinite(float(value))]
    if not observed:
        return ConfidenceInterval(
            mean=None,
            lower=None,
            upper=None,
            sample_size=0,
            confidence=confidence,
        )
    rng = random.Random(seed)
    simulations = sorted(
        mean(rng.choices(observed, k=len(observed))) for _ in range(resamples)
    )
    tail = (1 - confidence) / 2
    lower_index = max(0, int(tail * resamples))
    upper_index = min(resamples - 1, int((1 - tail) * resamples) - 1)
    return ConfidenceInterval(
        mean=round(mean(observed), 6),
        lower=round(simulations[lower_index], 6),
        upper=round(simulations[upper_index], 6),
        sample_size=len(observed),
        confidence=confidence,
    )


def expected_calibration_error(
    confidences: Iterable[float],
    outcomes: Iterable[int],
    *,
    bins: int = 10,
) -> float:
    pairs = [
        (max(0.0, min(1.0, float(confidence))), int(outcome))
        for confidence, outcome in zip(confidences, outcomes, strict=True)
    ]
    if not pairs:
        return 0.0
    error = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        bucket = [
            (confidence, outcome)
            for confidence, outcome in pairs
            if lower <= confidence < upper or (index == bins - 1 and confidence == 1)
        ]
        if not bucket:
            continue
        bucket_confidence = mean(item[0] for item in bucket)
        bucket_accuracy = mean(item[1] for item in bucket)
        error += (len(bucket) / len(pairs)) * abs(
            bucket_accuracy - bucket_confidence
        )
    return round(error, 6)
