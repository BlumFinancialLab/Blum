from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ELIGIBLE_PILOT_STATUSES = {
    "ELIGIBLE_FOR_SHADOW_PILOT",
    "ELIGIBLE_FOR_LIMITED_PILOT",
}


@dataclass(frozen=True)
class PilotPolicyThresholds:
    global_forward_trades: int = 500
    strategy_forward_trades: int = 150
    observation_days: int = 270
    max_evidence_drawdown_pct: float = 10.0
    max_replay_forward_decay_pct: float = 20.0
    min_tickers: int = 10
    min_regimes: int = 3
    max_ticker_concentration: float = 0.30
    max_market_concentration: float = 0.60
    max_capital_percent: float = 5.0
    max_risk_per_trade_percent: float = 0.25
    max_aggregate_open_risk_percent: float = 1.0
    max_correlated_theme_risk_percent: float = 0.50
    max_open_positions: int = 5
    max_daily_loss_percent: float = 1.0
    max_pilot_drawdown_percent: float = 5.0


@dataclass(frozen=True)
class PilotReadinessContext:
    copy_readiness_status: str
    real_capital_eligibility: str
    global_forward_trades: int | None = None
    strategy_forward_trades: int | None = None
    observation_days: int | None = None
    promoted_strategy_count: int | None = None
    exact_fingerprint_match: bool | None = None
    evidence_fresh: bool | None = None
    benchmark_methodology_valid: bool | None = None
    costs_available: bool | None = None
    slippage_available: bool | None = None
    data_quality_available: bool | None = None
    runtime_healthy: bool | None = None
    persistence_healthy: bool | None = None
    net_expectancy: float | None = None
    benchmark_excess: float | None = None
    evidence_max_drawdown_pct: float | None = None
    replay_forward_decay_pct: float | None = None
    ticker_count: int | None = None
    regime_count: int | None = None
    ticker_concentration: float | None = None
    market_concentration: float | None = None
    daily_loss_pct: float | None = None
    pilot_drawdown_pct: float | None = None
    aggregate_open_risk_pct: float | None = None
    strategy_operational_status: str | None = None
    previous_pilot_status: str | None = None


@dataclass(frozen=True)
class PilotReadinessDecision:
    status: str
    readiness_score: float
    passed_gates: tuple[str, ...]
    failed_gates: tuple[str, ...]
    blockers: tuple[str, ...]
    next_milestone: str | None
    kill_switch: dict[str, Any]
    capital_envelope: dict[str, float | int]

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "readiness_score": self.readiness_score,
            "passed_gates": list(self.passed_gates),
            "failed_gates": list(self.failed_gates),
            "blockers": list(self.blockers),
            "next_milestone": self.next_milestone,
            "kill_switch": {
                "active": bool(self.kill_switch["active"]),
                "triggers": list(self.kill_switch["triggers"]),
                "required_recovery_evidence": list(self.kill_switch["required_recovery_evidence"]),
            },
            "capital_envelope": dict(self.capital_envelope),
            "policy": (
                "Eligibility means controlled external validation under explicit limits. "
                "It is not a profit guarantee or an execution instruction."
            ),
        }


def evaluate_pilot_readiness(
    context: PilotReadinessContext,
    thresholds: PilotPolicyThresholds,
) -> PilotReadinessDecision:
    gate_results = _gate_results(context, thresholds)
    passed = tuple(name for name, result in gate_results if result)
    failed = tuple(name for name, result in gate_results if not result)
    triggers = _kill_switch_triggers(context, thresholds)
    kill_switch = {
        "active": bool(triggers),
        "triggers": triggers,
        "required_recovery_evidence": tuple(_recovery_requirement(trigger) for trigger in triggers),
    }

    if triggers:
        previously_eligible = context.previous_pilot_status in ELIGIBLE_PILOT_STATUSES
        currently_capital_eligible = (
            context.real_capital_eligibility == "ELIGIBLE_FOR_LIMITED_EXTERNAL_VALIDATION"
        )
        status = "SUSPENDED" if previously_eligible or currently_capital_eligible else "NOT_ELIGIBLE"
    elif not failed:
        status = "ELIGIBLE_FOR_LIMITED_PILOT"
    elif _shadow_ready(context):
        status = "ELIGIBLE_FOR_SHADOW_PILOT"
    elif _has_any_evidence(context):
        status = "EVIDENCE_BUILDING"
    else:
        status = "NOT_ELIGIBLE"

    readiness_score = round(100.0 * len(passed) / len(gate_results), 2)
    blockers = tuple(dict.fromkeys((*triggers, *failed)))
    return PilotReadinessDecision(
        status=status,
        readiness_score=readiness_score,
        passed_gates=passed,
        failed_gates=failed,
        blockers=blockers,
        next_milestone=None if not blockers else _milestone(blockers[0], thresholds),
        kill_switch=kill_switch,
        capital_envelope=_capital_envelope(status, thresholds),
    )


def _gate_results(
    context: PilotReadinessContext,
    thresholds: PilotPolicyThresholds,
) -> tuple[tuple[str, bool], ...]:
    return (
        (
            "capital_evidence_eligibility",
            context.real_capital_eligibility == "ELIGIBLE_FOR_LIMITED_EXTERNAL_VALIDATION",
        ),
        ("global_forward_trades", _at_least(context.global_forward_trades, thresholds.global_forward_trades)),
        (
            "strategy_forward_trades",
            _at_least(context.strategy_forward_trades, thresholds.strategy_forward_trades),
        ),
        ("observation_days", _at_least(context.observation_days, thresholds.observation_days)),
        ("promoted_strategy", _at_least(context.promoted_strategy_count, 1)),
        ("exact_strategy_fingerprint", context.exact_fingerprint_match is True),
        ("fresh_evidence", context.evidence_fresh is True),
        ("benchmark_methodology", context.benchmark_methodology_valid is True),
        ("cost_evidence", context.costs_available is True),
        ("slippage_evidence", context.slippage_available is True),
        ("data_quality_evidence", context.data_quality_available is True),
        ("runtime_health", context.runtime_healthy is True),
        ("persistence_health", context.persistence_healthy is True),
        ("positive_forward_expectancy", _positive(context.net_expectancy)),
        ("positive_benchmark_excess", _positive(context.benchmark_excess)),
        (
            "evidence_drawdown",
            _at_most_abs(context.evidence_max_drawdown_pct, thresholds.max_evidence_drawdown_pct),
        ),
        (
            "replay_forward_decay",
            _at_most(context.replay_forward_decay_pct, thresholds.max_replay_forward_decay_pct),
        ),
        ("ticker_coverage", _at_least(context.ticker_count, thresholds.min_tickers)),
        ("regime_coverage", _at_least(context.regime_count, thresholds.min_regimes)),
        (
            "ticker_concentration",
            _at_most(context.ticker_concentration, thresholds.max_ticker_concentration),
        ),
        (
            "market_concentration",
            _at_most(context.market_concentration, thresholds.max_market_concentration),
        ),
        ("strategy_operational", _strategy_is_operational(context.strategy_operational_status)),
    )


def _kill_switch_triggers(
    context: PilotReadinessContext,
    thresholds: PilotPolicyThresholds,
) -> tuple[str, ...]:
    triggers: list[str] = []
    if context.evidence_fresh is not True:
        triggers.append("stale_or_missing_evidence")
    if context.benchmark_methodology_valid is False:
        triggers.append("invalid_benchmark_methodology")
    if _count(context.promoted_strategy_count) > 0 and context.exact_fingerprint_match is False:
        triggers.append("strategy_fingerprint_mismatch")
    if context.runtime_healthy is False:
        triggers.append("runtime_unhealthy")
    if context.persistence_healthy is False:
        triggers.append("persistence_unhealthy")
    if _at_least(context.daily_loss_pct, thresholds.max_daily_loss_percent):
        triggers.append("daily_loss_limit")
    if _at_least(context.pilot_drawdown_pct, thresholds.max_pilot_drawdown_percent):
        triggers.append("pilot_drawdown_limit")
    if _greater_than(context.aggregate_open_risk_pct, thresholds.max_aggregate_open_risk_percent):
        triggers.append("aggregate_open_risk_limit")
    if context.net_expectancy is not None and context.net_expectancy <= 0:
        triggers.append("non_positive_forward_expectancy")
    if context.benchmark_excess is not None and context.benchmark_excess < 0:
        triggers.append("negative_benchmark_excess")
    if _greater_than(context.replay_forward_decay_pct, thresholds.max_replay_forward_decay_pct):
        triggers.append("excessive_replay_forward_decay")
    if _greater_than_abs(context.evidence_max_drawdown_pct, thresholds.max_evidence_drawdown_pct):
        triggers.append("evidence_drawdown_limit")
    if context.strategy_operational_status is not None and not _strategy_is_operational(
        context.strategy_operational_status
    ):
        triggers.append("strategy_not_operational")
    if context.real_capital_eligibility == "ELIGIBLE_FOR_LIMITED_EXTERNAL_VALIDATION" and not all(
        value is True
        for value in (context.costs_available, context.slippage_available, context.data_quality_available)
    ):
        triggers.append("execution_evidence_missing")
    return tuple(dict.fromkeys(triggers))


def _shadow_ready(context: PilotReadinessContext) -> bool:
    return (
        _count(context.promoted_strategy_count) > 0
        and context.exact_fingerprint_match is True
        and context.evidence_fresh is True
        and context.benchmark_methodology_valid is True
        and context.costs_available is True
        and context.slippage_available is True
        and context.data_quality_available is True
        and context.runtime_healthy is True
        and context.persistence_healthy is True
        and _positive(context.net_expectancy)
        and _positive(context.benchmark_excess)
        and _strategy_is_operational(context.strategy_operational_status)
    )


def _has_any_evidence(context: PilotReadinessContext) -> bool:
    return (
        context.copy_readiness_status not in {"", "NOT_READY", "UNKNOWN"}
        or _count(context.global_forward_trades) > 0
        or _count(context.strategy_forward_trades) > 0
        or _count(context.promoted_strategy_count) > 0
    )


def _capital_envelope(status: str, thresholds: PilotPolicyThresholds) -> dict[str, float | int]:
    return {
        "eligible_capital_percent": (
            thresholds.max_capital_percent if status == "ELIGIBLE_FOR_LIMITED_PILOT" else 0.0
        ),
        "max_capital_percent": thresholds.max_capital_percent,
        "max_risk_per_trade_percent": thresholds.max_risk_per_trade_percent,
        "max_aggregate_open_risk_percent": thresholds.max_aggregate_open_risk_percent,
        "max_correlated_theme_risk_percent": thresholds.max_correlated_theme_risk_percent,
        "max_open_positions": thresholds.max_open_positions,
    }


def _recovery_requirement(trigger: str) -> str:
    requirements = {
        "stale_or_missing_evidence": "Refresh and revalidate all decision evidence.",
        "invalid_benchmark_methodology": "Persist a valid matched-period benchmark assessment.",
        "strategy_fingerprint_mismatch": "Re-establish exact replay-to-forward strategy identity.",
        "runtime_unhealthy": "Restore healthy workers and complete a clean health cycle.",
        "persistence_unhealthy": "Restore verified persistence before any pilot decision.",
        "daily_loss_limit": "Complete the configured cooling-off period and risk review.",
        "pilot_drawdown_limit": "Recover below the drawdown gate with new forward evidence.",
        "aggregate_open_risk_limit": "Reduce aggregate open risk below the policy limit.",
        "non_positive_forward_expectancy": "Demonstrate positive net forward expectancy.",
        "negative_benchmark_excess": "Demonstrate positive matched benchmark excess.",
        "excessive_replay_forward_decay": "Reduce replay-to-forward performance decay.",
        "evidence_drawdown_limit": "Demonstrate drawdown within the strict evidence limit.",
        "strategy_not_operational": "Restore a promoted, non-degraded strategy state.",
        "execution_evidence_missing": "Persist complete cost, slippage, and data-quality evidence.",
    }
    return requirements.get(trigger, f"Resolve {trigger} with new persisted evidence.")


def _milestone(blocker: str, thresholds: PilotPolicyThresholds) -> str:
    milestones = {
        "capital_evidence_eligibility": "Satisfy every limited external validation evidence gate.",
        "global_forward_trades": f"Reach {thresholds.global_forward_trades} terminal global forward trades.",
        "strategy_forward_trades": f"Reach {thresholds.strategy_forward_trades} terminal exact-strategy forward trades.",
        "observation_days": f"Reach {thresholds.observation_days} calendar days of forward observation.",
        "promoted_strategy": "Promote one exact executable strategy through robustness validation.",
    }
    return milestones.get(blocker, f"Resolve {blocker} with verified evidence.")


def _strategy_is_operational(value: str | None) -> bool:
    return str(value or "").upper() in {"PROMOTED", "READY", "ACTIVE"}


def _count(value: int | None) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _at_least(value: int | float | None, threshold: int | float) -> bool:
    return value is not None and float(value) >= float(threshold)


def _at_most(value: int | float | None, threshold: int | float) -> bool:
    return value is not None and float(value) <= float(threshold)


def _at_most_abs(value: int | float | None, threshold: int | float) -> bool:
    return value is not None and abs(float(value)) <= float(threshold)


def _greater_than(value: int | float | None, threshold: int | float) -> bool:
    return value is not None and float(value) > float(threshold)


def _greater_than_abs(value: int | float | None, threshold: int | float) -> bool:
    return value is not None and abs(float(value)) > float(threshold)


def _positive(value: int | float | None) -> bool:
    return value is not None and float(value) > 0.0
