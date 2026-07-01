from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from statistics import mean
import time
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import (
    AlphaLossAttribution,
    LearningBenchmarkComparison,
    LearningFactorImportance,
    LearningFocusPriority,
    LearningRun,
    LearningStrengthWeaknessMap,
    MissedWinner,
    ReasoningNoiseFlag,
    SelfImprovementAction,
    TradeLearningEvidence,
    TradingGameTrade,
    TradingIntelligenceMetric,
)
from app.services.dashboard_snapshots import DashboardSnapshotService


RESEARCH_PLANNER_SNAPSHOT_TYPE = "research_planner_summary"
RESEARCH_PLANNER_POLICY = (
    "Autonomous Research Planner updates stored knowledge and research priorities only. "
    "It never rewrites source code, never executes trades and never runs from frontend render."
)


class AutonomousResearchPlanner:
    """Chooses what BLUM should study next from stored evidence only."""

    def summary(self, db: Session) -> dict:
        snapshot = DashboardSnapshotService().latest(db, RESEARCH_PLANNER_SNAPSHOT_TYPE)
        if snapshot.get("payload"):
            payload = dict(snapshot["payload"])
            payload["snapshot_status"] = snapshot.get("status")
            payload["snapshot_created_at"] = snapshot.get("created_at")
            return payload
        focus = db.scalar(
            select(LearningFocusPriority)
            .where(LearningFocusPriority.status.in_(["active", "proposed"]))
            .order_by(desc(LearningFocusPriority.expected_learning_value), desc(LearningFocusPriority.created_at))
            .limit(1)
        )
        return {
            "status": "missing_snapshot",
            "current_research_objective": serialize_focus(focus) if focus else fallback_exploration_objective(),
            "why_selected": "No Research Planner snapshot is stored yet; showing latest learning focus without generating work from the frontend.",
            "expected_information_gain": safe_float(getattr(focus, "expected_learning_value", None), 10.0) if focus else 10.0,
            "queued_experiments": [serialize_focus(focus)] if focus else [fallback_exploration_objective()],
            "completed_experiments": [],
            "experiment_result": {"status": "not_available", "summary": "No stored planner result yet."},
            "next_hypothesis": "Generate a planner snapshot in the backend autonomous cycle to choose the next experiment.",
            "exploration_policy": exploration_policy(),
            "policy": RESEARCH_PLANNER_POLICY,
        }

    def generate(self, db: Session, *, persist: bool = True, limit: int = 10) -> dict:
        started = time.perf_counter()
        evidence = collect_planner_evidence(db)
        candidates = rank_candidates(build_candidates(evidence))
        selected = choose_next_experiment(candidates)
        queued = candidates[: max(1, limit)]
        completed = completed_experiments(evidence)
        result = experiment_result(evidence)
        payload = {
            "status": "ready",
            "generated_at": datetime.utcnow().isoformat(),
            "current_research_objective": candidate_to_focus_payload(selected),
            "why_selected": selected.get("reason"),
            "expected_information_gain": selected.get("expected_information_gain"),
            "queued_experiments": [candidate_to_focus_payload(row) for row in queued],
            "completed_experiments": completed,
            "experiment_result": result,
            "next_hypothesis": next_hypothesis(selected),
            "exploration_policy": exploration_policy(),
            "evidence_inputs": evidence["counts"],
            "known_limitations": planner_limitations(evidence, candidates),
            "policy": RESEARCH_PLANNER_POLICY,
        }
        if persist:
            self._persist_priorities(db, queued, selected)
            DashboardSnapshotService().write(
                db,
                RESEARCH_PLANNER_SNAPSHOT_TYPE,
                payload,
                source_modules={"planner": "AutonomousResearchPlanner", "writes": ["LearningFocusPriority", "DashboardSnapshot"]},
                ttl_seconds=1800,
                warnings=payload["known_limitations"],
                computation_duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
        return payload

    def _persist_priorities(self, db: Session, candidates: list[dict], selected: dict) -> None:
        for candidate in candidates:
            if focus_exists(db, candidate):
                continue
            db.add(
                LearningFocusPriority(
                    priority_type=candidate["priority_type"],
                    target=candidate["target"],
                    reason=candidate["reason"],
                    expected_learning_value=candidate["expected_learning_value"],
                    urgency=candidate["urgency"],
                    sample_gap=candidate.get("sample_gap", 0),
                    linked_alpha_loss_id=candidate.get("linked_alpha_loss_id"),
                    linked_factor_importance_id=candidate.get("linked_factor_importance_id"),
                    linked_recovery_action_id=candidate.get("linked_recovery_action_id"),
                    status="active" if candidate["priority_type"] == selected["priority_type"] and candidate["target"] == selected["target"] else "proposed",
                    notes_json={
                        "source": "autonomous_research_planner",
                        "expected_information_gain": candidate["expected_information_gain"],
                        "experiment": candidate.get("experiment"),
                        "exploration_preserved": candidate.get("exploration", False),
                        "evidence": candidate.get("evidence", {}),
                    },
                )
            )
        db.flush()


def collect_planner_evidence(db: Session) -> dict:
    trades = db.scalars(select(TradingGameTrade).order_by(desc(TradingGameTrade.created_at)).limit(320)).all()
    metrics = db.scalars(select(TradingIntelligenceMetric).order_by(desc(TradingIntelligenceMetric.calculated_at)).limit(30)).all()
    benchmarks = db.scalars(select(LearningBenchmarkComparison).order_by(desc(LearningBenchmarkComparison.calculated_at)).limit(40)).all()
    weaknesses = db.scalars(select(LearningStrengthWeaknessMap).where(LearningStrengthWeaknessMap.status.in_(["open", "active", "proposed"])).order_by(desc(LearningStrengthWeaknessMap.weakness_score)).limit(40)).all()
    alpha_loss = db.scalars(select(AlphaLossAttribution).order_by(desc(AlphaLossAttribution.created_at)).limit(80)).all()
    missed_winners = db.scalars(select(MissedWinner).order_by(desc(MissedWinner.benchmark_relative_return), desc(MissedWinner.created_at)).limit(80)).all()
    noise = db.scalars(select(ReasoningNoiseFlag).where(ReasoningNoiseFlag.status == "open").order_by(desc(ReasoningNoiseFlag.created_at)).limit(40)).all()
    actions = db.scalars(select(SelfImprovementAction).where(SelfImprovementAction.status.in_(["proposed", "testing", "applied"])).order_by(desc(SelfImprovementAction.created_at)).limit(40)).all()
    lessons = db.scalars(select(TradeLearningEvidence).order_by(desc(TradeLearningEvidence.created_at)).limit(80)).all()
    factors = db.scalars(select(LearningFactorImportance).order_by(desc(LearningFactorImportance.calculated_at)).limit(80)).all()
    runs = db.scalars(select(LearningRun).order_by(desc(LearningRun.started_at)).limit(20)).all()
    return {
        "trades": trades,
        "metrics": metrics,
        "benchmarks": benchmarks,
        "weaknesses": weaknesses,
        "alpha_loss": alpha_loss,
        "missed_winners": missed_winners,
        "noise": noise,
        "actions": actions,
        "lessons": lessons,
        "factors": factors,
        "runs": runs,
        "counts": {
            "trades": len(trades),
            "metrics": len(metrics),
            "benchmarks": len(benchmarks),
            "weaknesses": len(weaknesses),
            "alpha_loss": len(alpha_loss),
            "missed_winners": len(missed_winners),
            "noise_flags": len(noise),
            "lessons": len(lessons),
            "factor_importance": len(factors),
            "learning_runs": len(runs),
        },
    }


def build_candidates(evidence: dict) -> list[dict]:
    candidates: list[dict] = []
    candidates.extend(candidates_from_weaknesses(evidence["weaknesses"]))
    candidates.extend(candidates_from_trades(evidence["trades"]))
    candidates.extend(candidates_from_metrics(evidence["metrics"]))
    candidates.extend(candidates_from_benchmarks(evidence["benchmarks"]))
    candidates.extend(candidates_from_alpha_loss(evidence["alpha_loss"]))
    candidates.extend(candidates_from_missed_winners(evidence["missed_winners"]))
    candidates.extend(candidates_from_noise(evidence["noise"]))
    candidates.extend(candidates_from_lessons(evidence["lessons"]))
    candidates.extend(candidates_from_factors(evidence["factors"]))
    candidates.extend(candidates_from_actions(evidence["actions"]))
    candidates.append(exploration_candidate(evidence))
    return dedupe_candidates(candidates)


def candidates_from_weaknesses(rows: list[LearningStrengthWeaknessMap]) -> list[dict]:
    output = []
    for row in rows[:12]:
        promising = row.strength_score >= 35 or row.sample_size < 50
        output.append(candidate(
            "weak_promising_setup" if promising else "weakness_replay",
            row.entity,
            row.main_problem or f"{row.dimension} weakness needs study.",
            row.weakness_score + (15 if promising else 0),
            sample_gap=max(0, 50 - row.sample_size),
            urgency=row.priority,
            experiment=f"Replay {row.dimension}={row.entity} and compare current trigger against alternative confirmation logic.",
            evidence={"dimension": row.dimension, "strength_score": row.strength_score, "weakness_score": row.weakness_score, "sample_size": row.sample_size},
        ))
    return output


def candidates_from_trades(rows: list[TradingGameTrade]) -> list[dict]:
    output: list[dict] = []
    if not rows:
        return output
    high_conf_failures = [row for row in rows if safe_float(row.confidence_at_entry) >= 70 and (safe_float(row.realized_r_multiple) < 0 or safe_float(row.excess_return_vs_benchmark) < 0)]
    if high_conf_failures:
        setup = most_common([row.setup_type for row in high_conf_failures])
        output.append(candidate(
            "high_confidence_failure_replay",
            setup,
            f"{len(high_conf_failures)} high-confidence failures suggest overconfidence or missing contradiction checks.",
            min(100, 55 + len(high_conf_failures) * 7),
            sample_gap=max(0, 30 - len(high_conf_failures)),
            urgency="high",
            experiment=f"Replay failed {setup} decisions and test lower confidence caps before similar entries.",
            evidence={"failures": len(high_conf_failures), "tickers": dict(Counter(row.ticker for row in high_conf_failures).most_common(5))},
        ))
    missed = [row for row in rows if row.missed_entry or row.outcome_label in {"missed_entry", "no_trade_missed_opportunity"}]
    if len(missed) >= 2:
        setup = most_common([row.setup_type for row in missed])
        output.append(candidate(
            "missed_entry_replay",
            setup,
            f"{len(missed)} missed entries indicate trigger timing may be too strict or late.",
            min(100, 50 + len(missed) * 6),
            sample_gap=max(0, 40 - len(missed)),
            urgency="high",
            experiment=f"Compare breakout-close, pullback-retest and earlier confirmation for {setup}.",
            evidence={"missed_entries": len(missed), "avg_opportunity_gap": average([safe_float(row.excess_return_vs_benchmark) for row in missed])},
        ))
    stop_hits = [row for row in rows if row.stop_hit or row.outcome_label in {"stopped_out", "stop_hit"}]
    if len(stop_hits) >= 2:
        setup = most_common([row.setup_type for row in stop_hits])
        output.append(candidate(
            "false_positive_reduction",
            setup,
            f"{len(stop_hits)} stop hits suggest false positives or invalidation placement problems.",
            min(95, 45 + len(stop_hits) * 5),
            sample_gap=max(0, 35 - len(stop_hits)),
            urgency="medium",
            experiment=f"Test stronger confirmation filters and ATR-aware invalidation for {setup}.",
            evidence={"stop_hits": len(stop_hits)},
        ))
    sectors = Counter(row.sector or "unknown" for row in rows)
    top_sector, top_count = sectors.most_common(1)[0]
    concentration = top_count / max(1, len(rows))
    if concentration >= 0.45 and len(rows) >= 8:
        output.append(candidate(
            "portfolio_concentration_research",
            top_sector,
            f"{top_sector} represents {concentration:.0%} of recent trade evidence; portfolio concentration may distort learning.",
            min(90, concentration * 100),
            sample_gap=max(0, 40 - len(rows)),
            urgency="medium",
            experiment=f"Replay non-{top_sector} setups and compare alpha stability versus concentrated exposure.",
            evidence={"top_sector": top_sector, "concentration": round(concentration, 4), "trade_count": len(rows)},
        ))
    regimes: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        regimes[row.market_regime_at_entry or "unknown"].append(safe_float(row.realized_r_multiple))
    unstable = [
        (regime, values)
        for regime, values in regimes.items()
        if len(values) >= 4 and any(value > 0 for value in values) and any(value < 0 for value in values)
    ]
    if unstable:
        regime, values = max(unstable, key=lambda item: len(item[1]))
        output.append(candidate(
            "unstable_regime_replay",
            regime,
            f"{regime} has mixed outcomes; setup reliability is regime-unstable.",
            min(88, 40 + len(values) * 4),
            sample_gap=max(0, 50 - len(values)),
            urgency="medium",
            experiment=f"Split {regime} trades by setup, volatility and sector confirmation before changing weights.",
            evidence={"regime": regime, "sample": len(values), "average_r": average(values)},
        ))
    return output


def candidates_from_metrics(rows: list[TradingIntelligenceMetric]) -> list[dict]:
    if not rows:
        return []
    latest = rows[0]
    output = []
    if safe_float(latest.missed_entry_rate) >= 0.25:
        output.append(candidate("repeated_missed_entries", latest.scope_id or "global", "Missed-entry rate is elevated in the latest intelligence metrics.", safe_float(latest.missed_entry_rate) * 100, sample_gap=50 - min(50, latest.trades_count), urgency="high", experiment="Replay missed entries and compare earlier trigger variants.", evidence={"missed_entry_rate": latest.missed_entry_rate, "trades_count": latest.trades_count}))
    if safe_float(latest.exit_timing_score, 100) < 55:
        output.append(candidate("repeated_poor_exits", latest.scope_id or "global", "Exit timing quality is weak; BLUM may be giving back R after entry.", 100 - safe_float(latest.exit_timing_score), sample_gap=50 - min(50, latest.trades_count), urgency="high", experiment="Replay closed trades and compare target, time-stop and momentum-decay exits.", evidence={"exit_timing_score": latest.exit_timing_score}))
    if safe_float(latest.sizing_quality_score, 100) < 55:
        output.append(candidate("poor_sizing_research", latest.scope_id or "global", "Sizing quality is weak; position risk may be misallocated.", 100 - safe_float(latest.sizing_quality_score), sample_gap=50 - min(50, latest.trades_count), urgency="medium", experiment="Compare fixed-fractional, volatility-adjusted and drawdown-aware sizing.", evidence={"sizing_quality_score": latest.sizing_quality_score}))
    if safe_float(latest.benchmark_excess) < 0:
        output.append(candidate("benchmark_underperformance_replay", latest.scope_id or "global", "Latest intelligence metrics are benchmark-negative.", abs(safe_float(latest.benchmark_excess)) + 35, sample_gap=50 - min(50, latest.trades_count), urgency="high", experiment="Replay the underperforming window against SPY/QQQ and identify missed leaders.", evidence={"benchmark_excess": latest.benchmark_excess}))
    return output


def candidates_from_benchmarks(rows: list[LearningBenchmarkComparison]) -> list[dict]:
    output = []
    for row in rows[:8]:
        if row.result_label == "underperforming" or safe_float(row.excess_return) < 0:
            output.append(candidate(
                "benchmark_underperformance_replay",
                row.benchmark_name,
                f"BLUM is underperforming {row.benchmark_name}; planner should study opportunity selection and allocation against this baseline.",
                min(100, abs(safe_float(row.excess_return)) + 45),
                sample_gap=max(0, 50 - row.sample_size),
                urgency="high",
                experiment=f"Replay decisions from the {row.benchmark_name} comparison period and test whether simple benchmark exposure beat BLUM.",
                evidence={"benchmark": row.benchmark_name, "excess_return": row.excess_return, "sample_size": row.sample_size, "result_label": row.result_label},
            ))
    return output


def candidates_from_alpha_loss(rows: list[AlphaLossAttribution]) -> list[dict]:
    output = []
    for row in rows[:10]:
        output.append(candidate(
            "alpha_loss_replay",
            row.ticker or row.setup_type or row.category,
            row.explanation or f"Alpha-loss category {row.category} needs replay.",
            min(100, abs(safe_float(row.contribution_value)) + 40),
            sample_gap=max(0, 50 - row.sample_size),
            urgency="high" if abs(safe_float(row.contribution_value)) > 5 else "medium",
            experiment=f"Replay {row.category} cases and test whether rule, entry, exit or allocation changes would reduce alpha loss.",
            evidence={"category": row.category, "benchmark": row.benchmark_name, "contribution_value": row.contribution_value, "sample_size": row.sample_size},
            linked_alpha_loss_id=row.id,
        ))
    return output


def candidates_from_missed_winners(rows: list[MissedWinner]) -> list[dict]:
    if not rows:
        return []
    tickers = Counter(row.ticker for row in rows)
    top_ticker, count = tickers.most_common(1)[0]
    avg_return = average([safe_float(row.benchmark_relative_return) for row in rows if row.ticker == top_ticker])
    return [candidate(
        "missed_winner_replay",
        top_ticker,
        f"{count} missed or rejected winners are stored for {top_ticker}; opportunity recall needs study.",
        min(100, avg_return + 45 + count * 4),
        sample_gap=max(0, 40 - count),
        urgency="high",
        experiment=f"Replay {top_ticker} missed-winner evidence and test sector-relative momentum, business quality and trigger looseness.",
        evidence={"ticker": top_ticker, "count": count, "average_benchmark_relative_return": avg_return},
    )]


def candidates_from_noise(rows: list[ReasoningNoiseFlag]) -> list[dict]:
    output = []
    for row in rows[:8]:
        output.append(candidate(
            "overconfidence_noise_replay" if "confidence" in row.noise_type else "reasoning_noise_replay",
            row.factor_name,
            row.explanation or f"{row.factor_name} has an open noise flag.",
            severity_score(row.severity) + min(30, row.sample_size),
            sample_gap=max(0, 50 - row.sample_size),
            urgency="high" if row.severity == "high" else "medium",
            experiment=f"Replay {row.factor_name} decisions and require contradiction checks before increasing trust.",
            evidence={"noise_type": row.noise_type, "severity": row.severity, "sample_size": row.sample_size},
        ))
    return output


def candidates_from_lessons(rows: list[TradeLearningEvidence]) -> list[dict]:
    output = []
    by_type = Counter(row.lesson_type for row in rows)
    for lesson_type, count in by_type.most_common(8):
        if count < 2:
            continue
        if lesson_type in {"entry_timing_bad", "exit_logic_failed", "sizing_too_aggressive", "setup_failed", "overconfidence_detected"} or "false" in lesson_type:
            target = most_common([row.setup_type for row in rows if row.lesson_type == lesson_type])
            output.append(candidate(
                "lesson_replay",
                target,
                f"Repeated lesson {lesson_type} appeared {count} times.",
                min(95, 35 + count * 8),
                sample_gap=max(0, 30 - count),
                urgency="medium",
                experiment=f"Replay {target} cases linked to {lesson_type} and evaluate a corrective rule.",
                evidence={"lesson_type": lesson_type, "count": count},
            ))
    return output


def candidates_from_factors(rows: list[LearningFactorImportance]) -> list[dict]:
    output = []
    for row in rows[:12]:
        if row.sample_size < 50 or row.noise_score > 65 or row.alpha_loss_contribution > row.alpha_contribution:
            output.append(candidate(
                "low_sample_edge_research" if row.sample_size < 50 else "factor_reliability_research",
                row.factor_name,
                row.explanation or f"{row.factor_name} needs more evidence before weight changes.",
                max(row.noise_score, row.alpha_loss_contribution, 50 - row.sample_size),
                sample_gap=max(0, 50 - row.sample_size),
                urgency="medium",
                experiment=f"Increase sample coverage for {row.factor_name} and test reliability by regime before changing weights.",
                evidence={"sample_size": row.sample_size, "noise_score": row.noise_score, "alpha_loss_contribution": row.alpha_loss_contribution},
                linked_factor_importance_id=row.id,
            ))
    return output


def candidates_from_actions(rows: list[SelfImprovementAction]) -> list[dict]:
    output = []
    for row in rows[:8]:
        output.append(candidate(
            "self_improvement_validation",
            row.affected_module,
            row.detected_problem or "Validate whether the proposed improvement actually improves decisions.",
            priority_score(row.priority) + abs(safe_float(row.before_metric)),
            sample_gap=50,
            urgency=row.priority,
            experiment=row.recommended_action or "Validate before/after metrics and rollback if no improvement.",
            evidence={"source_metric": row.source_metric, "status": row.status, "expected_impact": row.expected_impact},
        ))
    return output


def exploration_candidate(evidence: dict) -> dict:
    low_sample_reason = "Preserve exploration so BLUM does not overfit known strategies."
    if evidence["counts"]["trades"] < 50:
        low_sample_reason = "Trade sample is still small; broad random coverage is mandatory before exploiting narrow edges."
    return candidate(
        "broad_exploration",
        "under_sampled_market_coverage",
        low_sample_reason,
        32 if evidence["counts"]["trades"] >= 50 else 65,
        sample_gap=max(0, 100 - evidence["counts"]["trades"]),
        urgency="medium",
        experiment="Run broad random historical samples across tickers, sectors, regimes and horizons.",
        evidence={"exploration_ratio": 0.40, "trade_sample": evidence["counts"]["trades"]},
        exploration=True,
    )


def candidate(priority_type: str, target: Any, reason: str, information_gain: float, *, sample_gap: int = 0, urgency: str = "medium", experiment: str = "", evidence: dict | None = None, exploration: bool = False, linked_alpha_loss_id: int | None = None, linked_factor_importance_id: int | None = None, linked_recovery_action_id: int | None = None) -> dict:
    score = max(0.0, min(100.0, safe_float(information_gain)))
    return {
        "priority_type": priority_type,
        "target": str(target or "global"),
        "reason": reason,
        "expected_information_gain": round(score, 4),
        "expected_learning_value": round(score, 4),
        "urgency": normalize_urgency(urgency),
        "sample_gap": max(0, int(sample_gap or 0)),
        "experiment": experiment,
        "evidence": evidence or {},
        "exploration": exploration,
        "linked_alpha_loss_id": linked_alpha_loss_id,
        "linked_factor_importance_id": linked_factor_importance_id,
        "linked_recovery_action_id": linked_recovery_action_id,
    }


def choose_next_experiment(candidates: list[dict]) -> dict:
    if not candidates:
        return exploration_candidate({"counts": {"trades": 0}})
    top = candidates[0]
    exploration = next((row for row in candidates if row.get("exploration")), None)
    if top.get("expected_information_gain", 0) < 55 and exploration:
        return exploration
    return top


def rank_candidates(rows: list[dict]) -> list[dict]:
    urgency_weight = {"high": 12, "medium": 6, "low": 0}
    return sorted(rows, key=lambda row: (row["expected_information_gain"] + urgency_weight.get(row["urgency"], 0), row["sample_gap"]), reverse=True)


def dedupe_candidates(rows: list[dict]) -> list[dict]:
    best: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row["priority_type"], row["target"])
        previous = best.get(key)
        if previous is None or row["expected_information_gain"] > previous["expected_information_gain"]:
            best[key] = row
    return list(best.values())


def completed_experiments(evidence: dict) -> list[dict]:
    output = []
    for row in evidence["runs"][:5]:
        output.append({
            "type": "learning_run",
            "id": row.id,
            "status": row.status,
            "trigger": row.trigger,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "result": f"predictions {row.predictions_created or 0}, outcomes {row.outcomes_evaluated or 0}, memory {row.memory_updates or 0}",
        })
    for row in evidence["lessons"][:5]:
        output.append({
            "type": "lesson",
            "id": row.id,
            "status": row.lesson_type,
            "target": row.ticker or row.setup_type,
            "completed_at": row.created_at.isoformat() if row.created_at else None,
            "result": row.observation,
        })
    return output[:8]


def experiment_result(evidence: dict) -> dict:
    if evidence["lessons"]:
        row = evidence["lessons"][0]
        return {
            "status": row.lesson_type,
            "target": row.ticker or row.setup_type,
            "summary": row.observation,
            "confidence": row.confidence,
            "sample_size": row.sample_size,
        }
    if evidence["runs"]:
        row = evidence["runs"][0]
        return {
            "status": row.status,
            "target": row.trigger,
            "summary": f"Last run created {row.predictions_created or 0} predictions and evaluated {row.outcomes_evaluated or 0} outcomes.",
            "sample_size": row.outcomes_evaluated,
        }
    return {"status": "insufficient_evidence", "summary": "No completed experiment result is stored yet."}


def next_hypothesis(selected: dict) -> str:
    return (
        f"If BLUM studies {selected.get('target')} via {selected.get('experiment')}, "
        f"decision quality should improve by reducing {selected.get('priority_type').replace('_', ' ')}."
    )


def candidate_to_focus_payload(row: dict | None) -> dict:
    if row is None:
        return fallback_exploration_objective()
    return {
        "priority_type": row.get("priority_type"),
        "target": row.get("target"),
        "reason": row.get("reason"),
        "expected_learning_value": row.get("expected_learning_value"),
        "expected_information_gain": row.get("expected_information_gain"),
        "urgency": row.get("urgency"),
        "sample_gap": row.get("sample_gap"),
        "experiment": row.get("experiment"),
        "exploration": row.get("exploration", False),
        "evidence": row.get("evidence", {}),
    }


def serialize_focus(row: LearningFocusPriority | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "priority_type": row.priority_type,
        "target": row.target,
        "reason": row.reason,
        "expected_learning_value": row.expected_learning_value,
        "expected_information_gain": row.expected_learning_value,
        "urgency": row.urgency,
        "sample_gap": row.sample_gap,
        "status": row.status,
        "experiment": (row.notes_json or {}).get("experiment"),
        "exploration": bool((row.notes_json or {}).get("exploration_preserved")),
        "evidence": (row.notes_json or {}).get("evidence", {}),
    }


def fallback_exploration_objective() -> dict:
    return {
        "priority_type": "broad_exploration",
        "target": "under_sampled_market_coverage",
        "reason": "No stronger stored priority is available; preserve exploration instead of overfitting known strategies.",
        "expected_learning_value": 10.0,
        "expected_information_gain": 10.0,
        "urgency": "medium",
        "sample_gap": 100,
        "experiment": "Run broad random historical samples across tickers, sectors, regimes and horizons.",
        "exploration": True,
    }


def planner_limitations(evidence: dict, candidates: list[dict]) -> list[str]:
    warnings = []
    if evidence["counts"]["trades"] < 50:
        warnings.append("low_trade_sample_size")
    if evidence["counts"]["benchmarks"] == 0:
        warnings.append("missing_benchmark_comparisons")
    if evidence["counts"]["alpha_loss"] == 0:
        warnings.append("missing_alpha_loss_attribution")
    if not candidates:
        warnings.append("no_research_candidates_generated")
    return warnings


def exploration_policy() -> dict:
    return {
        "broad_random_coverage": 0.40,
        "weakness_replay": 0.30,
        "active_market_relevance": 0.20,
        "failure_replay": 0.10,
        "rule": "Preserve exploration; do not always exploit known strategies.",
    }


def focus_exists(db: Session, payload: dict) -> bool:
    return bool(
        db.scalar(
            select(LearningFocusPriority.id)
            .where(
                LearningFocusPriority.priority_type == payload["priority_type"],
                LearningFocusPriority.target == payload["target"],
                LearningFocusPriority.status.in_(["proposed", "active"]),
            )
            .limit(1)
        )
    )


def most_common(values: list[Any]) -> str:
    cleaned = [str(value) for value in values if value]
    return Counter(cleaned).most_common(1)[0][0] if cleaned else "global"


def average(values: list[float]) -> float:
    cleaned = [safe_float(value) for value in values if value is not None]
    return round(mean(cleaned), 4) if cleaned else 0.0


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_urgency(value: str | None) -> str:
    normalized = str(value or "medium").lower()
    return normalized if normalized in {"high", "medium", "low"} else "medium"


def severity_score(value: str | None) -> float:
    return {"high": 75.0, "medium": 55.0, "low": 35.0}.get(str(value or "").lower(), 40.0)


def priority_score(value: str | None) -> float:
    return {"high": 70.0, "medium": 50.0, "low": 30.0}.get(str(value or "").lower(), 40.0)
