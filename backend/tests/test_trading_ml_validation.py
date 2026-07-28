from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import sqrt

import pytest

from app.services.trading_ml.contracts import TradingMLExample
from app.services.trading_ml.validation import FoldPrediction, PurgedWalkForwardEvaluator


def rows() -> tuple[TradingMLExample, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return tuple(
        TradingMLExample(
            source_object_type="test_trade",
            source_object_id=str(index),
            market_family="equity",
            evidence_lane="REPLAY_EVIDENCE",
            decision_timestamp=start + timedelta(days=index),
            outcome_timestamp=start + timedelta(days=index + 1),
            asset_key=("AAA", "BBB", "CCC")[index % 3],
            setup_type="momentum_breakout",
            regime=("risk_on", "risk_off")[index % 2],
            features={"confidence": 50.0},
            realized_net_r=1.0 if index % 2 else -1.0,
            label_positive_r=1 if index % 2 else 0,
            benchmark_excess=0.2 if index % 2 else -0.1,
            sample_weight=1.0,
        )
        for index in range(24)
    )


class DeterministicScorer:
    def __init__(self, *, correct_probability: float, actionable: bool = True) -> None:
        self.correct_probability = correct_probability
        self.actionable = actionable
        self.calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    def predict(
        self,
        train: tuple[TradingMLExample, ...],
        validation: tuple[TradingMLExample, ...],
    ) -> tuple[FoldPrediction, ...]:
        self.calls.append(
            (
                tuple(f"{row.source_object_type}:{row.source_object_id}" for row in train),
                tuple(f"{row.source_object_type}:{row.source_object_id}" for row in validation),
            )
        )
        return tuple(
            FoldPrediction(
                source_uid=f"{row.source_object_type}:{row.source_object_id}",
                probability_positive_r=(
                    self.correct_probability if row.label_positive_r else 1.0 - self.correct_probability
                ),
                predicted_net_r=0.5,
                actionable=self.actionable,
            )
            for row in validation
        )


def evaluator() -> PurgedWalkForwardEvaluator:
    return PurgedWalkForwardEvaluator(min_folds=3, embargo_days=2)


def test_purged_folds_never_overlap_outcome_horizons() -> None:
    folds = evaluator().split(rows())

    assert len(folds) == 3
    for fold in folds:
        latest_train_outcome = max(row.outcome_timestamp for row in fold.train)
        earliest_validation_decision = min(row.decision_timestamp for row in fold.validation)
        assert latest_train_outcome < earliest_validation_decision
        assert latest_train_outcome < earliest_validation_decision - timedelta(days=2)


def test_evaluator_compares_candidate_and_baseline_on_identical_rows() -> None:
    candidate = DeterministicScorer(correct_probability=0.8)
    baseline = DeterministicScorer(correct_probability=1.0 - sqrt(0.14))

    result = evaluator().evaluate(candidate, baseline, rows())

    assert result.candidate.sample_size == result.baseline.sample_size
    assert result.brier_improvement == pytest.approx(0.1)
    assert candidate.calls == baseline.calls
    for fold in result.folds:
        assert fold.candidate.source_uids == fold.baseline.source_uids


def test_metrics_include_process_and_concentration_signals() -> None:
    result = evaluator().evaluate(
        DeterministicScorer(correct_probability=0.8),
        DeterministicScorer(correct_probability=0.6),
        rows(),
    )

    assert result.candidate.log_loss is not None
    assert result.candidate.balanced_accuracy == pytest.approx(1.0)
    assert result.candidate.net_expectancy == pytest.approx(0.0)
    assert result.candidate.expected_net_r == pytest.approx(0.5)
    assert result.candidate.max_drawdown == pytest.approx(-1.0)
    assert result.candidate.asset_concentration == pytest.approx(1 / 3)
    assert result.candidate.regime_concentration == pytest.approx(1.0)
    assert result.candidate.asset_selection_concentration == pytest.approx(1 / 3)
    assert result.candidate.regime_selection_concentration == pytest.approx(0.5)
    assert len(result.candidate.per_asset) == 3
    assert len(result.candidate.per_regime) == 2


def test_evaluator_rejects_missing_or_extra_predictions() -> None:
    class InvalidScorer:
        def predict(self, _train, validation):
            return (
                FoldPrediction(
                    source_uid="unknown:record",
                    probability_positive_r=0.5,
                    predicted_net_r=0.0,
                ),
            )

    with pytest.raises(ValueError, match="exactly one prediction"):
        evaluator().evaluate(InvalidScorer(), DeterministicScorer(correct_probability=0.6), rows())


def test_source_keyed_baseline_can_contain_outputs_for_later_folds() -> None:
    baseline = {
        f"{row.source_object_type}:{row.source_object_id}": FoldPrediction(
            source_uid=f"{row.source_object_type}:{row.source_object_id}",
            probability_positive_r=0.6,
            predicted_net_r=0.0,
        )
        for row in rows()
    }

    result = evaluator().evaluate(DeterministicScorer(correct_probability=0.8), baseline, rows())

    assert result.baseline.sample_size == 18


def test_drawdown_uses_realized_outcome_order() -> None:
    base = list(rows())
    returns = (4.0, -3.0, 2.0, -2.0)
    outcome_offsets = (1, 4, 2, 3)
    for index, (realized, outcome_offset) in enumerate(zip(returns, outcome_offsets), start=6):
        row = base[index]
        base[index] = replace(
            row,
            outcome_timestamp=row.decision_timestamp + timedelta(days=outcome_offset),
            realized_net_r=realized,
            label_positive_r=int(realized > 0),
        )
    result = evaluator().evaluate(
        DeterministicScorer(correct_probability=0.8),
        DeterministicScorer(correct_probability=0.6),
        tuple(base),
    )
    assert result.candidate.max_drawdown <= -5.0


def test_zero_weight_benchmark_rows_do_not_abort_evaluation() -> None:
    base = list(rows())
    for index, row in enumerate(base):
        base[index] = replace(
            row,
            benchmark_excess=0.3 if index == 6 else None,
            sample_weight=0.0 if index == 6 else 1.0,
        )
    result = evaluator().evaluate(
        DeterministicScorer(correct_probability=0.8),
        DeterministicScorer(correct_probability=0.6),
        tuple(base),
    )
    assert result.candidate.benchmark_excess is None
