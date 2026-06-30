from __future__ import annotations

from datetime import datetime
from statistics import mean
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.engine.contracts import ENGINE_VERSION, PROJECT_FEATURE_SET
from app.models import (
    AlphaRecoveryAction,
    BlumTradingPowerScore,
    DashboardSnapshot,
    DecisionSuperiorityScore,
    LearningBenchmarkComparison,
    LearningFocusPriority,
    LearningRun,
    LearningStrengthWeaknessMap,
    MetaCognitionEvent,
    ReasoningNoiseFlag,
    SelfImprovementAction,
    TradeLearningEvidence,
    TradingCapitalCycle,
    TradingGame,
    TradingGameTrade,
    TradingIntelligenceMetric,
)
from app.services.alpha_operating_system import (
    AlphaGateService,
    AlphaReadinessEngine,
    EdgeMapService,
    PaperCopyTradingService,
    TradingGameReadinessService,
)
from app.services.learning_summary import LearningSummaryService


TRADER_BRAIN_VERSION = ENGINE_VERSION
TRADER_BRAIN_FEATURE_SET = PROJECT_FEATURE_SET


class TraderBrainService:
    """Trader-focused read model built from stored evidence only.

    This service is intentionally thin: it does not run the Learning Loop,
    recalculate benchmarks, create trades, or modify weights. It turns the
    existing BLUM subsystems into four product-grade read surfaces.
    """

    def brain(self, db: Session) -> dict:
        learning = LearningSummaryService().summary(db)
        readiness = TradingGameReadinessService().readiness(db)
        alpha = AlphaReadinessEngine().readiness(db)
        latest_power = latest_row(db, BlumTradingPowerScore)
        latest_decision = latest_row(db, DecisionSuperiorityScore)
        latest_metric = latest_row(db, TradingIntelligenceMetric)
        latest_run = latest_row(db, LearningRun)
        latest_lesson = latest_row(db, TradeLearningEvidence)
        latest_regression = latest_row(db, ReasoningNoiseFlag)
        latest_improvement = latest_row(db, SelfImprovementAction)
        weakness = db.scalar(
            select(LearningStrengthWeaknessMap)
            .order_by(desc(LearningStrengthWeaknessMap.weakness_score), desc(LearningStrengthWeaknessMap.calculated_at))
            .limit(1)
        )
        strength = db.scalar(
            select(LearningStrengthWeaknessMap)
            .order_by(desc(LearningStrengthWeaknessMap.strength_score), desc(LearningStrengthWeaknessMap.calculated_at))
            .limit(1)
        )
        focus = db.scalar(
            select(LearningFocusPriority)
            .where(LearningFocusPriority.status.in_(["active", "proposed"]))
            .order_by(desc(LearningFocusPriority.expected_learning_value), desc(LearningFocusPriority.created_at))
            .limit(1)
        )
        benchmarks = latest_benchmarks(db)
        decision_quality = decision_quality_score(latest_decision, latest_metric)
        evidence_quality = evidence_quality_score(readiness, alpha, benchmarks)
        calibration = safe_float(getattr(latest_power, "statistical_confidence_score", None), None)
        learning_velocity = safe_float(getattr(latest_power, "learning_velocity_score", None), None)
        knowledge_quality = knowledge_quality_score(db)
        risk_management = safe_float(getattr(latest_power, "risk_management_score", None), None)
        alpha_readiness = safe_float(alpha.get("alpha_readiness_score"), None)
        reproducibility = safe_float(getattr(latest_power, "reproducibility_score", None), None)
        explainability = explainability_score(db)
        market_coverage = market_coverage_score(db)
        portfolio_intelligence = safe_float(getattr(latest_power, "regime_robustness_score", None), None)
        components = {
            "decision_quality": decision_quality,
            "evidence_quality": evidence_quality,
            "calibration": calibration,
            "learning_stability": stability_score(latest_metric),
            "risk_management": risk_management,
            "alpha_readiness": alpha_readiness,
            "reproducibility": reproducibility,
            "explainability": explainability,
            "market_coverage": market_coverage,
            "portfolio_intelligence": portfolio_intelligence,
            "knowledge_quality": knowledge_quality,
        }
        brain_score = weighted_average(components)
        return {
            "status": "ready" if brain_score is not None else "insufficient_evidence",
            "version": TRADER_BRAIN_VERSION,
            "feature_set": TRADER_BRAIN_FEATURE_SET,
            "generated_at": datetime.utcnow().isoformat(),
            "brain_score": brain_score,
            "brain_classification": classify_brain_score(brain_score),
            "decision_quality": decision_quality,
            "alpha_readiness": alpha_readiness,
            "learning_progress": {
                "latest_run_status": learning.get("latest_learning_run_status"),
                "latest_run_at": learning.get("latest_learning_run_at"),
                "last_cycle_status": getattr(latest_run, "status", None) if latest_run else None,
                "learning_velocity": learning_velocity,
                "target_progress": learning.get("target_progress"),
            },
            "current_learning_objective": focus_payload(focus),
            "current_learning_phase": phase_from_run(latest_run, readiness),
            "last_validated_improvement": improvement_payload(latest_improvement),
            "latest_regression": noise_payload(latest_regression),
            "current_weakness": weakness_payload(weakness),
            "current_strength": weakness_payload(strength),
            "evidence_quality": evidence_quality,
            "learning_velocity": learning_velocity,
            "knowledge_quality": knowledge_quality,
            "brain_status": status_line(brain_score, alpha, readiness),
            "last_learning_cycle": run_payload(latest_run),
            "next_planned_experiment": focus_payload(focus),
            "learning_chart": learning_chart(db),
            "truth": truth_lines(brain_score, learning, alpha, benchmarks),
            "component_scores": components,
            "readiness": {
                "trading_game": readiness.get("status"),
                "alpha": alpha.get("status"),
                "evidence_grade": alpha.get("evidence_grade") or readiness.get("evidence_grade"),
            },
            "latest_lesson": lesson_payload(latest_lesson),
            "policy": "Trader Brain is read-only. It observes stored evidence and never triggers training, trading or recalculation during page render.",
        }

    def training_ground(self, db: Session) -> dict:
        latest_run = latest_row(db, LearningRun)
        lessons = db.scalars(select(TradeLearningEvidence).order_by(desc(TradeLearningEvidence.created_at)).limit(16)).all()
        focus = db.scalars(
            select(LearningFocusPriority)
            .where(LearningFocusPriority.status.in_(["active", "proposed"]))
            .order_by(desc(LearningFocusPriority.expected_learning_value), desc(LearningFocusPriority.created_at))
            .limit(8)
        ).all()
        improvements = db.scalars(select(SelfImprovementAction).order_by(desc(SelfImprovementAction.created_at)).limit(8)).all()
        noise = db.scalars(select(ReasoningNoiseFlag).order_by(desc(ReasoningNoiseFlag.created_at)).limit(8)).all()
        latest_trade = latest_row(db, TradingGameTrade)
        return {
            "status": "ready",
            "version": TRADER_BRAIN_VERSION,
            "generated_at": datetime.utcnow().isoformat(),
            "current_experiment": experiment_from_focus(focus[0] if focus else None, latest_run),
            "current_hypothesis": hypothesis_from_focus(focus[0] if focus else None),
            "current_validation": validation_from_run(latest_run),
            "trades_being_analyzed": trade_analysis_payload(db),
            "patterns_discovered": [lesson_payload(row) for row in lessons if row.lesson_type not in ["setup_failed", "entry_timing_bad"]][:8],
            "patterns_rejected": [lesson_payload(row) for row in lessons if row.lesson_type in ["setup_failed", "entry_timing_bad"]][:8],
            "knowledge_gained": [lesson_payload(row) for row in lessons[:10]],
            "confidence_updated": latest_confidence_update(db),
            "why_model_changed": [improvement_payload(row) for row in improvements],
            "learning_timeline": learning_timeline(db),
            "active_focus": [focus_payload(row) for row in focus],
            "noise_flags": [noise_payload(row) for row in noise],
            "latest_trade": trade_payload(latest_trade),
            "policy": "Training Ground observes the autonomous Learning Loop. It does not start experiments from the frontend.",
        }

    def paper_trading(self, db: Session, limit: int = 20) -> dict:
        copy = PaperCopyTradingService().summary(db, limit=limit)
        ledger = db.scalars(select(TradingGameTrade).order_by(desc(TradingGameTrade.created_at)).limit(limit)).all()
        return {
            "status": copy.get("status", "ok"),
            "version": TRADER_BRAIN_VERSION,
            "generated_at": datetime.utcnow().isoformat(),
            "mode": "paper_only",
            "no_broker_execution": True,
            "copy_readiness": copy.get("readiness"),
            "decisions": [paper_decision(row) for row in copy.get("rows", [])],
            "completed_decisions": [completed_trade_decision(row) for row in ledger if row.exit_date is not None][:limit],
            "open_decisions": [completed_trade_decision(row) for row in ledger if row.exit_date is None][:limit],
            "truth_layer": copy.get("truth_layer") or ["Paper trading evidence is informational only."],
            "policy": "No brokers, no live execution, no financial advice. Copyability increases only with stored paper evidence.",
        }

    def alpha(self, db: Session) -> dict:
        alpha = AlphaReadinessEngine().readiness(db)
        edge = EdgeMapService().edge_map(db, limit=8)
        gates = AlphaGateService().gates(db)
        game = latest_row(db, TradingGame)
        metric = latest_row(db, TradingIntelligenceMetric)
        cycle = latest_row(db, TradingCapitalCycle)
        benchmarks = latest_benchmarks(db)
        return {
            "status": alpha.get("status"),
            "version": TRADER_BRAIN_VERSION,
            "generated_at": datetime.utcnow().isoformat(),
            "blum_return": return_percent(game, cycle),
            "benchmark_return": best_benchmark_return(benchmarks),
            "alpha": best_benchmark_excess(benchmarks),
            "sharpe": safe_float(getattr(metric, "sharpe_proxy", None), None),
            "sortino": safe_float(getattr(metric, "sortino_proxy", None), None),
            "drawdown": first_not_none(safe_float(getattr(metric, "max_drawdown", None), None), safe_float(getattr(game, "max_drawdown", None), None)),
            "win_rate": first_not_none(safe_float(getattr(metric, "win_rate", None), None), safe_float(getattr(game, "win_rate", None), None)),
            "expectancy": first_not_none(safe_float(getattr(metric, "expectancy_r", None), None), safe_float(getattr(game, "expectancy_r", None), None)),
            "profit_factor": safe_float(getattr(game, "profit_factor", None), None),
            "sample_size": alpha.get("trade_count"),
            "evidence_grade": alpha.get("evidence_grade"),
            "historical": evidence_slice(benchmarks, mode="historical_simulation"),
            "walk_forward": evidence_slice(benchmarks, mode="walk_forward"),
            "paper_forward": evidence_slice(benchmarks, mode="paper_pl_learning"),
            "live_forward": evidence_slice(benchmarks, mode="live_forward_paper"),
            "current_alpha_readiness": alpha,
            "edge_map": edge,
            "gates": gates,
            "truth": alpha.get("truth_layer") or alpha.get("warnings") or ["Insufficient evidence."],
            "policy": "Alpha page reports benchmark-relative evidence. It never hides underperformance and never claims market beating without sufficient samples.",
        }


def latest_row(db: Session, model):
    order_attr = None
    for name in ("calculated_at", "created_at", "updated_at", "started_at", "generated_at"):
        if hasattr(model, name):
            order_attr = getattr(model, name)
            break
    if order_attr is None:
        order_attr = getattr(model, "id")
    return db.scalar(select(model).order_by(desc(order_attr)).limit(1))


def latest_benchmarks(db: Session) -> list[LearningBenchmarkComparison]:
    rows = db.scalars(select(LearningBenchmarkComparison).order_by(desc(LearningBenchmarkComparison.calculated_at)).limit(60)).all()
    latest: dict[str, LearningBenchmarkComparison] = {}
    for row in rows:
        latest.setdefault(row.benchmark_name, row)
    return list(latest.values())


def decision_quality_score(decision: DecisionSuperiorityScore | None, metric: TradingIntelligenceMetric | None) -> float | None:
    values = [
        safe_float(getattr(decision, "score", None), None),
        safe_float(getattr(metric, "trade_quality_score", None), None),
        safe_float(getattr(metric, "risk_reward_quality_score", None), None),
        safe_float(getattr(metric, "entry_timing_score", None), None),
        safe_float(getattr(metric, "exit_timing_score", None), None),
    ]
    return average_present(values)


def evidence_quality_score(readiness: dict, alpha: dict, benchmarks: list[LearningBenchmarkComparison]) -> float | None:
    grade = str(alpha.get("evidence_grade") or readiness.get("evidence_grade") or "insufficient").lower()
    grade_score = {"strong": 82.0, "medium": 62.0, "low": 42.0, "weak": 34.0, "insufficient": 20.0}.get(grade, 35.0)
    benchmark_score = min(100.0, len(benchmarks) * 18.0)
    trade_score = min(100.0, safe_float(alpha.get("trade_count"), 0.0) / 5.0)
    return round((grade_score * 0.45) + (benchmark_score * 0.25) + (trade_score * 0.30), 2)


def knowledge_quality_score(db: Session) -> float | None:
    lessons = int(db.scalar(select(func.count(TradeLearningEvidence.id))) or 0)
    meta = int(db.scalar(select(func.count(MetaCognitionEvent.id))) or 0)
    focus = int(db.scalar(select(func.count(LearningFocusPriority.id))) or 0)
    total = lessons + meta + focus
    if total == 0:
        return None
    return round(min(100.0, 20.0 + lessons * 0.4 + meta * 1.2 + focus * 1.5), 2)


def explainability_score(db: Session) -> float | None:
    with_lessons = int(db.scalar(select(func.count(TradeLearningEvidence.id))) or 0)
    trades = int(db.scalar(select(func.count(TradingGameTrade.id))) or 0)
    if trades == 0:
        return None
    return round(min(100.0, 35.0 + (with_lessons / max(1, min(trades, 500))) * 100.0), 2)


def market_coverage_score(db: Session) -> float | None:
    tickers = int(db.scalar(select(func.count(func.distinct(TradingGameTrade.ticker)))) or 0)
    sectors = int(db.scalar(select(func.count(func.distinct(TradingGameTrade.sector)))) or 0)
    if tickers == 0:
        return None
    return round(min(100.0, tickers * 1.5 + sectors * 5.0), 2)


def stability_score(metric: TradingIntelligenceMetric | None) -> float | None:
    if metric is None:
        return None
    drawdown = abs(safe_float(getattr(metric, "max_drawdown", None), 0.0))
    profit_factor = safe_float(getattr(metric, "profit_factor", None), 0.0)
    score = 55.0 + min(25.0, profit_factor * 5.0) - min(35.0, drawdown)
    return round(max(0.0, min(100.0, score)), 2)


def weighted_average(values: dict[str, float | None]) -> float | None:
    present = [value for value in values.values() if value is not None]
    if not present:
        return None
    return round(mean(present), 2)


def learning_chart(db: Session) -> list[dict]:
    rows = db.scalars(select(BlumTradingPowerScore).order_by(desc(BlumTradingPowerScore.calculated_at)).limit(30)).all()
    return [
        {
            "timestamp": row.calculated_at.isoformat() if row.calculated_at else None,
            "brain_score": row.score,
            "decision_quality": row.decision_quality_score,
            "learning_velocity": row.learning_velocity_score,
            "classification": row.classification,
        }
        for row in reversed(rows)
    ]


def truth_lines(brain_score: float | None, learning: dict, alpha: dict, benchmarks: list[LearningBenchmarkComparison]) -> list[str]:
    lines: list[str] = []
    if brain_score is None:
        lines.append("Not enough stored evidence to score the Trader Brain yet.")
    else:
        lines.append(f"Trader Brain Score is {brain_score:.1f}/100: {classify_brain_score(brain_score)}.")
    if alpha.get("status") in {"INSUFFICIENT_EVIDENCE", "DATA_QUALITY_BLOCKED"}:
        lines.append("Alpha evidence is not mature enough for trust.")
    for row in benchmarks[:3]:
        label = row.result_label or "inconclusive"
        lines.append(f"BLUM vs {row.benchmark_name}: {label}, excess {format_pct(row.excess_return)}; sample {row.sample_size or 0}.")
    for warning in (learning.get("warnings") or [])[:2]:
        lines.append(str(warning))
    return lines[:6]


def classify_brain_score(score: float | None) -> str:
    if score is None:
        return "insufficient evidence"
    if score < 25:
        return "not trader-ready"
    if score < 45:
        return "amateur learning"
    if score < 60:
        return "research grade"
    if score < 75:
        return "promising trader brain"
    if score < 88:
        return "strong paper-trading brain"
    return "external validation required"


def status_line(score: float | None, alpha: dict, readiness: dict) -> str:
    if readiness.get("status") not in {"READY", "STALE_BUT_USABLE"}:
        return f"training evidence not renderable: {readiness.get('status')}"
    if alpha.get("status") == "INSUFFICIENT_EVIDENCE":
        return "learning, but alpha evidence remains insufficient"
    return classify_brain_score(score)


def phase_from_run(row: LearningRun | None, readiness: dict) -> str:
    if readiness.get("status") not in {"READY", "STALE_BUT_USABLE"}:
        return "evidence construction"
    if row is None:
        return "waiting for first learning cycle"
    if row.status in {"running", "started"}:
        return "experiment running"
    if row.status in {"completed", "ok"}:
        return "post-experiment evaluation"
    return row.status or "unknown"


def focus_payload(row: LearningFocusPriority | None) -> dict | None:
    if row is None:
        return None
    return {
        "priority_type": row.priority_type,
        "target": row.target,
        "reason": row.reason,
        "expected_learning_value": row.expected_learning_value,
        "urgency": row.urgency,
        "sample_gap": row.sample_gap,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def improvement_payload(row: SelfImprovementAction | None) -> dict | None:
    if row is None:
        return None
    return {
        "detected_problem": row.detected_problem,
        "recommended_action": row.recommended_action,
        "affected_module": row.affected_module,
        "priority": row.priority,
        "status": row.status,
        "improvement_observed": row.improvement_observed,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def noise_payload(row: ReasoningNoiseFlag | None) -> dict | None:
    if row is None:
        return None
    return {
        "factor_name": row.factor_name,
        "module_name": row.module_name,
        "noise_type": row.noise_type,
        "severity": row.severity,
        "recommended_action": row.recommended_action,
        "status": row.status,
        "explanation": row.explanation,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def weakness_payload(row: LearningStrengthWeaknessMap | None) -> dict | None:
    if row is None:
        return None
    return {
        "dimension": row.dimension,
        "entity": row.entity,
        "strength_score": row.strength_score,
        "weakness_score": row.weakness_score,
        "sample_size": row.sample_size,
        "main_problem": row.main_problem,
        "recommended_action": row.recommended_action,
        "priority": row.priority,
    }


def run_payload(row: LearningRun | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "trigger": row.trigger,
        "batch_size": row.batch_size,
        "predictions_generated": row.predictions_created,
        "outcomes_evaluated": row.outcomes_evaluated,
        "mistakes_analyzed": row.mistakes_found,
        "memory_updates": row.memory_updates,
    }


def lesson_payload(row: TradeLearningEvidence | None) -> dict | None:
    if row is None:
        return None
    return {
        "ticker": row.ticker,
        "setup_type": row.setup_type,
        "regime": row.regime,
        "lesson_type": row.lesson_type,
        "observation": row.observation,
        "sample_size": row.sample_size,
        "affected_module": row.affected_module,
        "action_taken": row.action_taken,
        "confidence": row.confidence,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def trade_payload(row: TradingGameTrade | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "ticker": row.ticker,
        "setup_type": row.setup_type,
        "entry_date": row.entry_date.isoformat() if row.entry_date else None,
        "exit_date": row.exit_date.isoformat() if row.exit_date else None,
        "outcome_label": row.outcome_label,
        "net_pnl_eur": row.net_pnl_eur,
        "r_multiple": row.realized_r_multiple,
        "lesson_generated": row.lesson_generated,
    }


def paper_decision(row: dict) -> dict:
    return {
        "ticker": row.get("ticker"),
        "side": infer_side(row),
        "entry": row.get("entry_zone") or row.get("entry_trigger"),
        "stop": row.get("invalidation_level"),
        "targets": [item for item in [row.get("target_1"), row.get("target_2")] if item is not None],
        "holding_estimate": row.get("expected_holding_period") or row.get("timeframe"),
        "expected_risk": row.get("risk_amount_eur") or row.get("risk_reward_estimate"),
        "expected_reward": row.get("risk_reward_estimate"),
        "expected_alpha": row.get("historical_reliability"),
        "decision_quality": row.get("copy_readiness_score"),
        "confidence": row.get("confidence"),
        "copyability": row.get("copy_readiness"),
        "why": row.get("paper_instruction"),
        "bull_thesis": row.get("bull_thesis") or row.get("why_now"),
        "bear_thesis": row.get("bear_thesis") or row.get("what_could_go_wrong"),
        "risk": row.get("risk") or row.get("missing_data"),
        "missing_data": row.get("missing_data") or [],
    }


def completed_trade_decision(row: TradingGameTrade) -> dict:
    return {
        "trade_id": row.id,
        "ticker": row.ticker,
        "setup_type": row.setup_type,
        "entry": row.entry_price,
        "stop": row.stop_loss or row.invalidation_level,
        "targets": [item for item in [row.initial_target_1, row.initial_target_2] if item is not None],
        "exit": row.exit_price,
        "outcome": row.outcome_label,
        "pnl": row.net_pnl_eur,
        "r_multiple": row.realized_r_multiple,
        "lesson_learned": row.lesson_generated,
        "confidence_recalibration": row.payload.get("confidence_recalibration") if isinstance(row.payload, dict) else None,
    }


def infer_side(row: dict) -> str:
    action = str(row.get("actionability") or "").lower()
    if "exit" in action or "reduce" in action:
        return "SELL"
    return "BUY"


def experiment_from_focus(row: LearningFocusPriority | None, latest_run: LearningRun | None) -> dict:
    if row:
        return {
            "name": row.priority_type,
            "target": row.target,
            "reason": row.reason,
            "status": row.status,
            "expected_learning_value": row.expected_learning_value,
        }
    return {
        "name": "background_learning_cycle",
        "target": getattr(latest_run, "trigger", None) or "stored market evidence",
        "reason": "No active focus priority is stored; scheduler continues broad coverage.",
        "status": getattr(latest_run, "status", None) or "waiting",
        "expected_learning_value": None,
    }


def hypothesis_from_focus(row: LearningFocusPriority | None) -> str:
    if row is None:
        return "BLUM is still collecting enough evidence to choose the next focused hypothesis."
    return f"If BLUM studies {row.target}, it may reduce {row.reason or 'a current decision weakness'}."


def validation_from_run(row: LearningRun | None) -> dict:
    if row is None:
        return {"status": "not_started", "summary": "No LearningRun is stored yet."}
    return {
        "status": row.status,
        "predictions_generated": row.predictions_created,
        "outcomes_evaluated": row.outcomes_evaluated,
        "mistakes_analyzed": row.mistakes_found,
        "memory_updates": row.memory_updates,
    }


def trade_analysis_payload(db: Session) -> dict:
    total = int(db.scalar(select(func.count(TradingGameTrade.id))) or 0)
    latest = db.scalar(select(func.max(TradingGameTrade.created_at)))
    open_count = int(db.scalar(select(func.count(TradingGameTrade.id)).where(TradingGameTrade.exit_date.is_(None))) or 0)
    return {"total_trades": total, "open_trades": open_count, "latest_trade_at": latest.isoformat() if latest else None}


def latest_confidence_update(db: Session) -> dict | None:
    row = latest_row(db, BlumTradingPowerScore)
    if row is None:
        return None
    return {
        "calculated_at": row.calculated_at.isoformat() if row.calculated_at else None,
        "confidence_calibration_score": row.statistical_confidence_score,
        "decision_quality_score": row.decision_quality_score,
        "learning_velocity_score": row.learning_velocity_score,
    }


def learning_timeline(db: Session) -> list[dict]:
    runs = db.scalars(select(LearningRun).order_by(desc(LearningRun.started_at)).limit(12)).all()
    return [run_payload(row) for row in runs if row is not None]


def return_percent(game: TradingGame | None, cycle: TradingCapitalCycle | None) -> float | None:
    if cycle and cycle.return_percent is not None:
        return cycle.return_percent
    if game is None or game.starting_capital in (None, 0) or game.current_capital is None:
        return None
    return round(((game.current_capital - game.starting_capital) / game.starting_capital) * 100, 4)


def best_benchmark_return(rows: list[LearningBenchmarkComparison]) -> float | None:
    values = [safe_float(row.benchmark_return, None) for row in rows if row.benchmark_return is not None]
    return average_present(values)


def best_benchmark_excess(rows: list[LearningBenchmarkComparison]) -> float | None:
    values = [safe_float(row.excess_return, None) for row in rows if row.excess_return is not None]
    return average_present(values)


def evidence_slice(rows: list[LearningBenchmarkComparison], mode: str) -> dict:
    selected = [row for row in rows if row.mode == mode]
    if not selected:
        return {"status": "insufficient_evidence", "sample_size": 0}
    return {
        "status": "ready",
        "sample_size": sum(row.sample_size or 0 for row in selected),
        "average_excess_return": average_present([row.excess_return for row in selected]),
        "results": [
            {
                "benchmark": row.benchmark_name,
                "result_label": row.result_label,
                "excess_return": row.excess_return,
                "sample_size": row.sample_size,
                "statistical_confidence": row.statistical_confidence,
            }
            for row in selected[:6]
        ],
    }


def safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def first_not_none(*values):
    for value in values:
        if value is not None:
            return value
    return None


def average_present(values: list[float | None]) -> float | None:
    present = [float(value) for value in values if value is not None]
    if not present:
        return None
    return round(mean(present), 4)


def format_pct(value: Any) -> str:
    number = safe_float(value, None)
    return "n/a" if number is None else f"{number:.2f}%"
