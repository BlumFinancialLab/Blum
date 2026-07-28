from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.trading_ml.contracts import FeatureSchema, TradingMLExample
from app.services.trading_ml.training import (
    BoundedOptunaChallengerSearch,
    OnlineShadowTrainer,
    SklearnTradingModelTrainer,
)


def examples(count: int = 48) -> tuple[TradingMLExample, ...]:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    return tuple(
        TradingMLExample(
            source_object_type="test",
            source_object_id=str(index),
            market_family="equity",
            evidence_lane="REPLAY_EVIDENCE",
            decision_timestamp=start + timedelta(days=index),
            outcome_timestamp=start + timedelta(days=index + 1),
            asset_key=f"A{index % 6}",
            setup_type="momentum" if index % 2 else "pullback",
            regime="risk_on" if index % 3 else "risk_off",
            features={
                name: (
                    "equity" if name == "market_family"
                    else "momentum" if name == "setup_type"
                    else "risk_on" if name == "regime"
                    else "regular" if name == "session"
                    else "LONG" if name == "direction"
                    else "daily" if name == "timeframe"
                    else "technology" if name == "sector_or_currency_family"
                    else float((index * 7 + offset) % 100)
                )
                for offset, name in enumerate(FeatureSchema.current().feature_names)
            },
            realized_net_r=1.0 if index % 2 else -0.6,
            label_positive_r=index % 2,
            benchmark_excess=0.2 if index % 2 else -0.1,
            sample_weight=1.0,
        )
        for index in range(count)
    )


def test_online_update_remains_shadow_only(tmp_path):
    result = OnlineShadowTrainer(tmp_path).partial_fit(examples())
    assert result.status == "SHADOW"
    assert result.decision_authority is False


def test_batch_training_is_deterministic_for_fixed_seed():
    first = SklearnTradingModelTrainer(seed=17).fit(examples())
    second = SklearnTradingModelTrainer(seed=17).fit(examples())
    assert first.validation_metrics == second.validation_metrics
    assert first.artifact_sha256 == second.artifact_sha256


def test_batch_metrics_preserve_expected_and_realized_r():
    result = SklearnTradingModelTrainer(seed=17).fit(examples())
    assert "expected_net_r" in result.validation_metrics
    assert "net_expectancy" in result.validation_metrics
    assert len(result.validation_metrics["folds"]) == 3


def test_optuna_search_is_bounded():
    result = BoundedOptunaChallengerSearch(max_trials=2, timeout_seconds=20).search(examples())
    assert 1 <= result.trials_completed <= 2
    assert set(result.parameters) == {"learning_rate", "max_leaf_nodes", "max_iter", "l2_regularization"}
