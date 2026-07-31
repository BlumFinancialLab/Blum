from __future__ import annotations

import pytest

from app.analyst.hf_training import EvaluationGate, assert_promotion_allowed, build_promotion_request


def passing_metrics() -> dict:
    return {
        "candidate": {
            "aggregate_contract_score": 0.97,
            "structured_validity": 1.0,
            "no_fabrication": 0.95,
            "directional_accounting": 1.0,
            "critical_regressions": 0,
        },
        "champion": {
            "aggregate_contract_score": 0.96,
            "structured_validity": 1.0,
            "no_fabrication": 0.93,
        },
        "temporal_leakage": 0,
    }


def test_promotion_gate_accepts_non_regressing_candidate() -> None:
    result = assert_promotion_allowed(passing_metrics(), EvaluationGate())
    assert result.eligible is True


def test_promotion_gate_rejects_fabrication_regression() -> None:
    metrics = passing_metrics()
    metrics["candidate"]["no_fabrication"] = 0.80
    with pytest.raises(ValueError, match="no_fabrication_regression"):
        assert_promotion_allowed(metrics, EvaluationGate())


def test_promotion_job_never_uses_unapproved_candidate() -> None:
    request = build_promotion_request(
        metrics=passing_metrics(),
        admin_key="correct",
        supplied_admin_key="correct",
        champion_repository="Italianhype/Blum-Finance-4B",
        champion_revision="old-champion-sha",
        challenger_repository="Italianhype/Blum-Finance-4B-Challenger",
        candidate_revision="candidate-abc",
    )
    assert request.job_kind == "promotion"
    assert request.source_revision == "candidate-abc"
    assert request.backup_tag.startswith("champion-backup-")


def test_promotion_requires_admin_key() -> None:
    with pytest.raises(PermissionError):
        build_promotion_request(
            metrics=passing_metrics(),
            admin_key="correct",
            supplied_admin_key="wrong",
            champion_repository="Italianhype/Blum-Finance-4B",
            champion_revision="old",
            challenger_repository="Italianhype/Blum-Finance-4B-Challenger",
            candidate_revision="candidate",
        )
