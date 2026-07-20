from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import log, sqrt
from typing import Iterable, Sequence

import numpy as np
from scipy.stats import kurtosis, norm, skew


@dataclass(frozen=True)
class PurgedFold:
    fold_number: int
    train_indices: tuple[int, ...]
    validation_indices: tuple[int, ...]
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    purge_bars: int
    embargo_bars: int
    embargo_end_index: int


@dataclass(frozen=True)
class BootstrapInterval:
    mean: float
    lower: float
    upper: float
    confidence: float
    iterations: int


@dataclass(frozen=True)
class MultipleTestingResult:
    index: int
    raw_p_value: float
    adjusted_p_value: float
    significant: bool


@dataclass(frozen=True)
class StrategyRobustnessResult:
    verdict: str
    reason: str
    sample_size: int
    net_expectancy_r: float
    benchmark_excess: float
    bootstrap_lower_bound: float
    bootstrap_upper_bound: float
    deflated_sharpe_probability: float
    overfitting_probability: float
    max_asset_contribution: float
    complexity_penalty: float
    metrics: dict


def build_purged_folds(
    timestamps: Sequence[datetime],
    *,
    n_splits: int = 3,
    purge_bars: int = 5,
    embargo_bars: int = 3,
) -> tuple[PurgedFold, ...]:
    ordered = tuple(timestamps)
    if n_splits < 2:
        raise ValueError("n_splits must be at least 2")
    if len(ordered) < (n_splits + 1) * 2:
        raise ValueError("insufficient observations for purged walk-forward")
    if any(left >= right for left, right in zip(ordered, ordered[1:])):
        raise ValueError("timestamps must be strictly increasing")
    purge = max(0, int(purge_bars))
    embargo = max(0, int(embargo_bars))
    block = len(ordered) // (n_splits + 1)
    folds: list[PurgedFold] = []
    for fold_number in range(1, n_splits + 1):
        validation_start_index = block * fold_number
        validation_end_index = len(ordered) - 1 if fold_number == n_splits else block * (fold_number + 1) - 1
        train_end_index = validation_start_index - purge - 1
        if train_end_index < 0:
            continue
        train = tuple(range(0, train_end_index + 1))
        validation = tuple(range(validation_start_index, validation_end_index + 1))
        folds.append(
            PurgedFold(
                fold_number=fold_number,
                train_indices=train,
                validation_indices=validation,
                train_start=ordered[train[0]],
                train_end=ordered[train[-1]],
                validation_start=ordered[validation[0]],
                validation_end=ordered[validation[-1]],
                purge_bars=purge,
                embargo_bars=embargo,
                embargo_end_index=min(len(ordered) - 1, validation_end_index + embargo),
            )
        )
    return tuple(folds)


def block_bootstrap_interval(
    values: Iterable[float],
    *,
    iterations: int = 1_000,
    block_size: int = 5,
    confidence: float = 0.95,
    seed: int = 7,
) -> BootstrapInterval:
    samples = np.asarray([float(value) for value in values if np.isfinite(float(value))], dtype=float)
    if samples.size < 2:
        mean = float(samples.mean()) if samples.size else 0.0
        return BootstrapInterval(mean, mean, mean, confidence, 0)
    iterations = max(100, min(20_000, int(iterations)))
    block_size = max(1, min(int(block_size), int(samples.size)))
    rng = np.random.default_rng(int(seed))
    starts = np.arange(0, samples.size - block_size + 1)
    block_count = int(np.ceil(samples.size / block_size))
    means = np.empty(iterations, dtype=float)
    for iteration in range(iterations):
        selected = rng.choice(starts, size=block_count, replace=True)
        replay = np.concatenate([samples[start : start + block_size] for start in selected])[: samples.size]
        means[iteration] = float(replay.mean())
    alpha = (1.0 - max(0.5, min(0.999, confidence))) / 2.0
    return BootstrapInterval(
        mean=round(float(samples.mean()), 8),
        lower=round(float(np.quantile(means, alpha)), 8),
        upper=round(float(np.quantile(means, 1.0 - alpha)), 8),
        confidence=confidence,
        iterations=iterations,
    )


def benjamini_hochberg(
    p_values: Sequence[float],
    *,
    false_discovery_rate: float = 0.05,
) -> tuple[MultipleTestingResult, ...]:
    if not p_values:
        return ()
    bounded = [max(0.0, min(1.0, float(value))) for value in p_values]
    order = sorted(range(len(bounded)), key=bounded.__getitem__)
    adjusted = [1.0] * len(bounded)
    running = 1.0
    total = len(bounded)
    for rank_index in range(total - 1, -1, -1):
        original_index = order[rank_index]
        rank = rank_index + 1
        candidate = bounded[original_index] * total / rank
        running = min(running, candidate)
        adjusted[original_index] = min(1.0, running)
    threshold = max(0.0, min(1.0, float(false_discovery_rate)))
    return tuple(
        MultipleTestingResult(
            index=index,
            raw_p_value=bounded[index],
            adjusted_p_value=round(adjusted[index], 10),
            significant=adjusted[index] <= threshold,
        )
        for index in range(total)
    )


def deflated_sharpe_probability(returns: Sequence[float], *, trials: int, observed_sharpe: float | None = None) -> float:
    values = np.asarray([float(value) for value in returns if np.isfinite(float(value))], dtype=float)
    if values.size < 3 or float(values.std(ddof=1)) <= 0:
        return 0.0
    sharpe = float(observed_sharpe) if observed_sharpe is not None else float(values.mean() / values.std(ddof=1) * sqrt(252))
    trials = max(1, int(trials))
    expected_max = norm.ppf(1.0 - 1.0 / max(2.0, trials * 2.0)) / sqrt(max(2, values.size))
    sample_skew = float(skew(values, bias=False))
    sample_kurtosis = float(kurtosis(values, fisher=False, bias=False))
    variance = max(1e-9, 1.0 - sample_skew * sharpe + ((sample_kurtosis - 1.0) / 4.0) * sharpe * sharpe)
    statistic = (sharpe - expected_max) * sqrt(values.size - 1) / sqrt(variance)
    return round(float(norm.cdf(statistic)), 8)


def backtest_overfitting_probability(rank_pairs: Sequence[tuple[int, int]], *, variants: int) -> float:
    if not rank_pairs:
        return 1.0
    variants = max(2, int(variants))
    failures = 0.0
    for in_sample_rank, out_of_sample_rank in rank_pairs:
        if out_of_sample_rank > variants / 2:
            failures += 1.0
        elif out_of_sample_rank > in_sample_rank:
            failures += 0.25
    return round(min(1.0, failures / len(rank_pairs)), 8)


def evaluate_strategy_robustness(
    evidence: dict,
    *,
    min_sample_size: int = 300,
    max_drawdown: float = -25.0,
    max_overfitting_probability: float = 0.5,
    min_deflated_sharpe_probability: float = 0.9,
    min_stability: float = 55.0,
    max_asset_contribution: float = 0.5,
    seed: int = 7,
) -> StrategyRobustnessResult:
    sample_size = int(evidence.get("sample_size") or 0)
    returns = [float(value) for value in evidence.get("returns_r") or []]
    excess_returns = [float(value) for value in evidence.get("benchmark_excess_returns") or []]
    bootstrap = block_bootstrap_interval(returns, iterations=800, block_size=max(2, min(10, len(returns) // 20 or 2)), seed=seed)
    net_expectancy = float(np.mean(returns)) if returns else float(evidence.get("expectancy_r") or 0.0)
    benchmark_excess = float(np.mean(excess_returns)) if excess_returns else float(evidence.get("benchmark_excess") or 0.0)
    measured_overfitting = evidence.get("overfitting_probability")
    overfitting_probability = 1.0 if measured_overfitting is None else float(measured_overfitting)
    measured_dsr = evidence.get("deflated_sharpe_probability")
    dsr_probability = (
        deflated_sharpe_probability(returns, trials=max(1, int(evidence.get("family_size") or 1)))
        if measured_dsr is None
        else float(measured_dsr)
    )
    contributions = [abs(float(value)) for value in (evidence.get("asset_pnl_contributions") or {}).values()]
    largest_contribution = max(contributions, default=0.0)
    complexity = max(1, int(evidence.get("complexity") or 1))
    complexity_penalty = round(log(1.0 + complexity) / sqrt(max(1, sample_size)), 8)
    windows = list(evidence.get("windows") or [])
    markets = set(evidence.get("markets") or [])
    tickers = set(evidence.get("tickers") or [])
    stability_values = [
        *[float(value) for value in evidence.get("stability_by_window") or []],
        *[float(value) for value in evidence.get("stability_by_market") or []],
        *[float(value) for value in evidence.get("stability_by_regime") or []],
    ]
    stability = min(stability_values, default=float(evidence.get("stability_score") or 0.0))
    drawdown = float(evidence.get("max_drawdown") or 0.0)
    data_quality = float(evidence.get("data_quality_score") or 0.0)
    cost_coverage = float(evidence.get("cost_coverage") or 0.0)

    if sample_size < max(300, int(min_sample_size)):
        verdict, reason = "NEEDS_MORE_EVIDENCE", f"Validated sample {sample_size} is below 300."
    elif len(windows) < 2 or len(tickers) < 2:
        verdict, reason = "REJECTED_UNSTABLE", "Multiple independent windows and tickers are required."
    elif cost_coverage < 1.0 or data_quality < 70.0:
        verdict, reason = "REJECTED_DATA_QUALITY", "Execution-cost or point-in-time data coverage is incomplete."
    elif net_expectancy <= 0 or benchmark_excess <= 0 or bootstrap.lower <= 0:
        verdict, reason = "REJECTED_COSTS", "Net cost-adjusted expectancy or benchmark excess is not durable."
    elif not bool(evidence.get("multiple_testing_significant")) or (
        1.0 if evidence.get("adjusted_p_value") is None else float(evidence["adjusted_p_value"])
    ) > 0.05:
        verdict, reason = "REJECTED_MULTIPLE_TESTING", "Candidate does not survive multiple-hypothesis correction."
    elif overfitting_probability > max_overfitting_probability:
        verdict, reason = "REJECTED_OVERFITTING", "Estimated probability of backtest overfitting is too high."
    elif dsr_probability < min_deflated_sharpe_probability:
        verdict, reason = "REJECTED_OVERFITTING", "Deflated Sharpe probability is below the required threshold."
    elif largest_contribution > max_asset_contribution:
        verdict, reason = "REJECTED_CONCENTRATION", "A single asset dominates strategy P/L."
    elif drawdown < max_drawdown:
        verdict, reason = "REJECTED_BAD_DRAWDOWN", "Maximum drawdown exceeds the strategy risk budget."
    elif stability < min_stability or (len(markets) < 2 and len(set(evidence.get("regimes") or [])) < 2):
        verdict, reason = "REJECTED_UNSTABLE", "Evidence is not stable across windows, regimes, and markets."
    else:
        verdict, reason = "PROMOTED_TO_PAPER", "All purged, cost, robustness, concentration, and multiple-testing gates passed."

    metrics = {
        **evidence,
        "net_expectancy_r": round(net_expectancy, 8),
        "benchmark_excess": round(benchmark_excess, 8),
        "bootstrap_lower_bound": bootstrap.lower,
        "bootstrap_upper_bound": bootstrap.upper,
        "deflated_sharpe_probability": round(dsr_probability, 8),
        "overfitting_probability": round(overfitting_probability, 8),
        "max_asset_contribution": round(largest_contribution, 8),
        "complexity_penalty": complexity_penalty,
        "stability_score": round(stability, 8),
    }
    return StrategyRobustnessResult(
        verdict=verdict,
        reason=reason,
        sample_size=sample_size,
        net_expectancy_r=round(net_expectancy, 8),
        benchmark_excess=round(benchmark_excess, 8),
        bootstrap_lower_bound=bootstrap.lower,
        bootstrap_upper_bound=bootstrap.upper,
        deflated_sharpe_probability=round(dsr_probability, 8),
        overfitting_probability=round(overfitting_probability, 8),
        max_asset_contribution=round(largest_contribution, 8),
        complexity_penalty=complexity_penalty,
        metrics=metrics,
    )
