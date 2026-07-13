from __future__ import annotations

import pytest

from app.services.copy_readiness_metrics import (
    ReadinessContext,
    ReadinessThresholds,
    canonical_evidence_class,
    concentration,
    evaluate_capital_eligibility,
    evaluate_copy_readiness,
    evaluate_decay,
    wilson_interval,
)


def context_fixture(**overrides) -> ReadinessContext:
    values = {
        "replay_sample": 500,
        "global_forward_sample": 120,
        "forward_sample": 40,
        "observation_days": 120,
        "net_expectancy": 0.25,
        "benchmark_excess": 1.2,
        "max_drawdown": 8.0,
        "decay_status": "CONSISTENT",
        "decay_pct": 10.0,
        "ticker_count": 8,
        "regime_count": 3,
        "ticker_concentration": 0.25,
        "market_concentration": 0.60,
        "costs_available": True,
        "slippage_available": True,
        "data_quality_available": True,
        "previous_status": None,
    }
    values.update(overrides)
    return ReadinessContext(**values)


@pytest.mark.parametrize(
    ("value", "trading_mode", "expected"),
    [
        ("REPLAY_EVIDENCE", None, "REPLAY_EVIDENCE"),
        ("walk forward evidence", None, "WALK_FORWARD_EVIDENCE"),
        ("PAPER_FORWARD_INTRADAY", None, "INTRADAY_FORWARD_EVIDENCE"),
        (None, "INTRADAY_PAPER_FORWARD", "INTRADAY_FORWARD_EVIDENCE"),
        (None, "PAPER_FORWARD", "PAPER_FORWARD_EVIDENCE"),
    ],
)
def test_canonical_evidence_class_normalizes_legacy_and_mode_values(value, trading_mode, expected):
    assert canonical_evidence_class(value, trading_mode) == expected


def test_wilson_interval_is_null_for_an_empty_sample():
    assert wilson_interval(0, 0) is None


def test_wilson_interval_reports_a_95_percent_interval():
    interval = wilson_interval(5, 10)

    assert interval is not None
    assert interval["point_estimate"] == 0.5
    assert interval["lower"] == pytest.approx(0.2366, abs=0.0001)
    assert interval["upper"] == pytest.approx(0.7634, abs=0.0001)


def test_concentration_reports_dominant_value_share_and_cardinality():
    result = concentration(["NVDA", "AAPL", "NVDA"])

    assert result == {
        "top_value": "NVDA",
        "top_share": pytest.approx(2 / 3),
        "distinct_count": 2,
    }


def test_concentration_keeps_missing_values_unavailable():
    assert concentration([]) == {
        "top_value": None,
        "top_share": None,
        "distinct_count": 0,
    }


def test_decay_does_not_fabricate_a_comparison_when_evidence_is_missing():
    result = evaluate_decay({"net_expectancy": 0.5}, None, ReadinessThresholds())

    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["performance_decay_pct"] is None


def test_decay_classifies_material_forward_loss_as_failure():
    result = evaluate_decay(
        {"net_expectancy": 0.5, "profit_factor": 2.0, "max_drawdown": 5.0},
        {"net_expectancy": -0.1, "profit_factor": 0.8, "max_drawdown": 8.0},
        ReadinessThresholds(),
    )

    assert result["status"] == "FORWARD_FAILURE"


def test_decay_classifies_expectancy_degradation_against_thresholds():
    result = evaluate_decay(
        {"net_expectancy": 1.0},
        {"net_expectancy": 0.6},
        ReadinessThresholds(max_decay_pct=35.0),
    )

    assert result["performance_decay_pct"] == pytest.approx(40.0)
    assert result["status"] == "HIGH_DECAY"


def test_replay_only_cannot_be_copy_ready():
    context = context_fixture(global_forward_sample=0, forward_sample=0)

    decision = evaluate_copy_readiness(context, ReadinessThresholds())

    assert decision.status == "REPLAY_ONLY"


def test_fewer_than_ten_terminal_forward_trades_is_low_evidence():
    decision = evaluate_copy_readiness(
        context_fixture(global_forward_sample=9, forward_sample=9),
        ReadinessThresholds(),
    )

    assert decision.status == "FORWARD_EVIDENCE_LOW"


def test_larger_immature_forward_sample_is_growing_evidence():
    decision = evaluate_copy_readiness(
        context_fixture(global_forward_sample=50, forward_sample=20),
        ReadinessThresholds(),
    )

    assert decision.status == "FORWARD_EVIDENCE_GROWING"


def test_terminal_forward_evidence_can_reach_copy_ready():
    context = context_fixture(
        global_forward_sample=120,
        forward_sample=40,
        observation_days=120,
        net_expectancy=0.25,
        benchmark_excess=1.2,
        max_drawdown=8.0,
        decay_status="CONSISTENT",
        ticker_count=8,
        regime_count=3,
        ticker_concentration=0.25,
        market_concentration=0.60,
        costs_available=True,
    )

    decision = evaluate_copy_readiness(context, ReadinessThresholds())

    assert decision.status == "COPY_READY_PAPER_ONLY"
    assert decision.maturity_score == 100.0


def test_forward_failure_suspends_readiness():
    context = context_fixture(forward_sample=40, net_expectancy=-0.1, benchmark_excess=-1.0)

    assert evaluate_copy_readiness(context, ReadinessThresholds()).status == "SUSPENDED"


def test_missing_benchmark_stays_missing_and_blocks_promotion():
    context = context_fixture(benchmark_excess=None)

    decision = evaluate_copy_readiness(context, ReadinessThresholds())

    assert "benchmark_excess_unavailable" in decision.failed_gates
    assert decision.status == "FORWARD_EVIDENCE_GROWING"


@pytest.mark.parametrize(
    "field",
    ["costs_available", "slippage_available", "data_quality_available"],
)
def test_missing_required_evidence_blocks_promotion(field):
    decision = evaluate_copy_readiness(context_fixture(**{field: False}), ReadinessThresholds())

    assert decision.status == "FORWARD_EVIDENCE_GROWING"
    assert field.removesuffix("_available") + "_unavailable" in decision.failed_gates


def test_non_material_deterioration_of_a_ready_strategy_is_degraded():
    decision = evaluate_copy_readiness(
        context_fixture(previous_status="COPY_READY_PAPER_ONLY", ticker_count=4),
        ReadinessThresholds(),
    )

    assert decision.status == "DEGRADED"


def test_stricter_thresholds_promote_high_confidence_only_when_all_gates_pass():
    thresholds = ReadinessThresholds(
        high_confidence_global_forward_trades=120,
        high_confidence_strategy_forward_trades=40,
        high_confidence_observation_days=120,
        high_confidence_max_drawdown=8.0,
        high_confidence_max_decay_pct=10.0,
        high_confidence_min_tickers=8,
        high_confidence_min_regimes=3,
        high_confidence_max_ticker_concentration=0.25,
        high_confidence_max_market_concentration=0.60,
    )

    decision = evaluate_copy_readiness(context_fixture(), thresholds)

    assert decision.status == "COPY_READY_HIGH_CONFIDENCE"


def test_capital_eligibility_is_autonomous_and_requires_all_stricter_gates():
    thresholds = ReadinessThresholds(
        high_confidence_global_forward_trades=500,
        high_confidence_strategy_forward_trades=150,
        high_confidence_observation_days=270,
        high_confidence_max_drawdown=10.0,
        high_confidence_max_decay_pct=20.0,
        high_confidence_min_tickers=10,
        high_confidence_min_regimes=3,
        high_confidence_max_ticker_concentration=0.30,
        high_confidence_max_market_concentration=0.60,
    )
    context = context_fixture(
        global_forward_sample=500,
        forward_sample=150,
        observation_days=270,
        max_drawdown=10.0,
        decay_pct=20.0,
        ticker_count=10,
        ticker_concentration=0.30,
    )
    decision = evaluate_copy_readiness(context, thresholds)

    assert decision.status == "COPY_READY_HIGH_CONFIDENCE"
    assert evaluate_capital_eligibility(context, decision, thresholds) == "ELIGIBLE_FOR_LIMITED_EXTERNAL_VALIDATION"


def test_capital_eligibility_is_revoked_when_readiness_is_suspended():
    context = context_fixture(net_expectancy=-0.1)
    decision = evaluate_copy_readiness(context, ReadinessThresholds())

    assert evaluate_capital_eligibility(context, decision, ReadinessThresholds()) == "NOT_ELIGIBLE"
