from dataclasses import replace

import pytest

from app.services.institutional_pilot import (
    PilotPolicyThresholds,
    PilotReadinessContext,
    evaluate_pilot_readiness,
)


def empty_context(**overrides) -> PilotReadinessContext:
    values = {
        "copy_readiness_status": "NOT_READY",
        "real_capital_eligibility": "NOT_ELIGIBLE",
    }
    values.update(overrides)
    return PilotReadinessContext(**values)


def eligible_context(**overrides) -> PilotReadinessContext:
    values = {
        "copy_readiness_status": "COPY_READY_HIGH_CONFIDENCE",
        "real_capital_eligibility": "ELIGIBLE_FOR_LIMITED_EXTERNAL_VALIDATION",
        "global_forward_trades": 500,
        "strategy_forward_trades": 150,
        "observation_days": 270,
        "promoted_strategy_count": 1,
        "exact_fingerprint_match": True,
        "evidence_fresh": True,
        "benchmark_methodology_valid": True,
        "costs_available": True,
        "slippage_available": True,
        "data_quality_available": True,
        "runtime_healthy": True,
        "persistence_healthy": True,
        "net_expectancy": 0.18,
        "benchmark_excess": 0.09,
        "evidence_max_drawdown_pct": 7.0,
        "replay_forward_decay_pct": 12.0,
        "ticker_count": 12,
        "regime_count": 4,
        "ticker_concentration": 0.22,
        "market_concentration": 0.55,
        "daily_loss_pct": 0.0,
        "pilot_drawdown_pct": 0.0,
        "aggregate_open_risk_pct": 0.5,
        "strategy_operational_status": "PROMOTED",
    }
    values.update(overrides)
    return PilotReadinessContext(**values)


def test_missing_evidence_fails_closed_with_zero_eligible_capital() -> None:
    decision = evaluate_pilot_readiness(empty_context(), PilotPolicyThresholds())

    assert decision.status == "NOT_ELIGIBLE"
    assert decision.capital_envelope["eligible_capital_percent"] == 0.0
    assert "capital_evidence_eligibility" in decision.failed_gates
    assert "promoted_strategy" in decision.failed_gates
    assert decision.kill_switch["active"] is True
    assert "stale_or_missing_evidence" in decision.kill_switch["triggers"]


def test_replay_only_evidence_cannot_authorize_limited_capital() -> None:
    decision = evaluate_pilot_readiness(
        empty_context(
            copy_readiness_status="REPLAY_ONLY",
            global_forward_trades=0,
            strategy_forward_trades=0,
            evidence_fresh=True,
            runtime_healthy=True,
            persistence_healthy=True,
        ),
        PilotPolicyThresholds(),
    )

    assert decision.status == "EVIDENCE_BUILDING"
    assert decision.capital_envelope["eligible_capital_percent"] == 0.0
    assert "capital_evidence_eligibility" in decision.failed_gates


def test_promoted_strategy_with_valid_execution_can_enter_shadow_pilot_only() -> None:
    decision = evaluate_pilot_readiness(
        empty_context(
            copy_readiness_status="FORWARD_EVIDENCE_GROWING",
            global_forward_trades=80,
            strategy_forward_trades=25,
            observation_days=70,
            promoted_strategy_count=1,
            exact_fingerprint_match=True,
            evidence_fresh=True,
            benchmark_methodology_valid=True,
            costs_available=True,
            slippage_available=True,
            data_quality_available=True,
            runtime_healthy=True,
            persistence_healthy=True,
            net_expectancy=0.12,
            benchmark_excess=0.04,
            evidence_max_drawdown_pct=6.0,
            replay_forward_decay_pct=15.0,
            ticker_count=8,
            regime_count=3,
            ticker_concentration=0.25,
            market_concentration=0.55,
            daily_loss_pct=0.0,
            pilot_drawdown_pct=0.0,
            aggregate_open_risk_pct=0.0,
            strategy_operational_status="PROMOTED",
        ),
        PilotPolicyThresholds(),
    )

    assert decision.status == "ELIGIBLE_FOR_SHADOW_PILOT"
    assert decision.capital_envelope["eligible_capital_percent"] == 0.0


def test_all_strict_gates_authorize_only_a_conservative_limited_pilot() -> None:
    decision = evaluate_pilot_readiness(eligible_context(), PilotPolicyThresholds())

    assert decision.status == "ELIGIBLE_FOR_LIMITED_PILOT"
    assert decision.failed_gates == ()
    assert decision.kill_switch == {"active": False, "triggers": (), "required_recovery_evidence": ()}
    assert decision.capital_envelope == {
        "eligible_capital_percent": 5.0,
        "max_capital_percent": 5.0,
        "max_risk_per_trade_percent": 0.25,
        "max_aggregate_open_risk_percent": 1.0,
        "max_correlated_theme_risk_percent": 0.5,
        "max_open_positions": 5,
    }


@pytest.mark.parametrize(
    ("changes", "expected_trigger"),
    [
        ({"evidence_fresh": False}, "stale_or_missing_evidence"),
        ({"benchmark_methodology_valid": False}, "invalid_benchmark_methodology"),
        ({"exact_fingerprint_match": False}, "strategy_fingerprint_mismatch"),
        ({"runtime_healthy": False}, "runtime_unhealthy"),
        ({"persistence_healthy": False}, "persistence_unhealthy"),
        ({"daily_loss_pct": 1.0}, "daily_loss_limit"),
        ({"pilot_drawdown_pct": 5.0}, "pilot_drawdown_limit"),
        ({"aggregate_open_risk_pct": 1.01}, "aggregate_open_risk_limit"),
        ({"net_expectancy": 0.0}, "non_positive_forward_expectancy"),
        ({"benchmark_excess": -0.01}, "negative_benchmark_excess"),
        ({"replay_forward_decay_pct": 20.01}, "excessive_replay_forward_decay"),
        ({"strategy_operational_status": "DEGRADED"}, "strategy_not_operational"),
    ],
)
def test_any_critical_trigger_suspends_a_previously_eligible_pilot(changes, expected_trigger) -> None:
    context = replace(eligible_context(), previous_pilot_status="ELIGIBLE_FOR_LIMITED_PILOT", **changes)

    decision = evaluate_pilot_readiness(context, PilotPolicyThresholds())

    assert decision.status == "SUSPENDED"
    assert decision.capital_envelope["eligible_capital_percent"] == 0.0
    assert decision.kill_switch["active"] is True
    assert expected_trigger in decision.kill_switch["triggers"]
    assert decision.kill_switch["required_recovery_evidence"]
