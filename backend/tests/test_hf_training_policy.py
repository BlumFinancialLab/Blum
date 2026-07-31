from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.analyst.hf_training import TrainingPolicy, TrainingStats, evaluate_readiness


def policy() -> TrainingPolicy:
    return TrainingPolicy(
        enabled=True,
        minimum_examples=250,
        minimum_matured_ratio=0.80,
        minimum_days_between_runs=30,
        minimum_quality=70.0,
    )


def test_readiness_passes_only_when_every_gate_passes() -> None:
    now = datetime(2026, 7, 31, tzinfo=timezone.utc)
    result = evaluate_readiness(
        TrainingStats(
            approved_examples=300,
            matured_examples=270,
            active_jobs=0,
            critical_quality_failures=0,
            last_launched_at=now - timedelta(days=31),
            token_configured=True,
        ),
        policy(),
        now=now,
    )
    assert result.eligible is True
    assert result.blockers == ()


def test_readiness_reports_all_blockers() -> None:
    now = datetime(2026, 7, 31, tzinfo=timezone.utc)
    result = evaluate_readiness(
        TrainingStats(
            approved_examples=100,
            matured_examples=40,
            active_jobs=1,
            critical_quality_failures=2,
            last_launched_at=now - timedelta(days=5),
            token_configured=False,
        ),
        policy(),
        now=now,
    )
    assert result.eligible is False
    assert set(result.blockers) == {
        "feature_disabled_or_token_missing",
        "insufficient_approved_examples",
        "insufficient_matured_outcomes",
        "training_job_already_active",
        "critical_quality_gate_failure",
        "training_cooldown_active",
    }


def test_disabled_policy_never_launches() -> None:
    disabled = TrainingPolicy(
        enabled=False,
        minimum_examples=1,
        minimum_matured_ratio=0,
        minimum_days_between_runs=0,
        minimum_quality=0,
    )
    result = evaluate_readiness(
        TrainingStats(1, 1, 0, 0, None, True),
        disabled,
        now=datetime(2026, 7, 31, tzinfo=timezone.utc),
    )
    assert result.eligible is False
    assert "feature_disabled_or_token_missing" in result.blockers
