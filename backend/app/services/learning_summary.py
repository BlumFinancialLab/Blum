from __future__ import annotations

from datetime import datetime
import time

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import (
    BlumTradingPowerScore,
    DashboardSnapshot,
    LearningBenchmarkComparison,
    LearningRun,
    LearningStrengthWeaknessMap,
    TradingCapitalCycle,
    TradingGame,
    TradingIntelligenceMetric,
    TradeLearningEvidence,
)
from app.services.dashboard_snapshots import DashboardSnapshotService
from app.services.performance import performance_recorder


class LearningSummaryService:
    """Fast first-paint summary for the Learning dashboard.

    This service reads latest/precomputed rows only. It must not trigger benchmark
    recalculation, decision intelligence recalculation, trading-game execution or
    model learning.
    """

    def summary(self, db: Session) -> dict:
        started = time.perf_counter()
        missing_sections: list[str] = []
        warnings: list[str] = []
        snapshot_types = [
            "learning_summary",
            "trading_game_summary",
            "benchmark_summary",
            "intelligence_growth_summary",
            "truth_panel_summary",
        ]
        snapshots = {snapshot_type: DashboardSnapshotService().latest(db, snapshot_type) for snapshot_type in snapshot_types}
        stale_snapshots = [snapshot_type for snapshot_type, payload in snapshots.items() if payload.get("status") == "stale"]
        missing_snapshots = [snapshot_type for snapshot_type, payload in snapshots.items() if payload.get("status") == "missing"]
        if stale_snapshots:
            warnings.append(f"Using stale dashboard snapshots for: {', '.join(stale_snapshots)}.")
        if missing_snapshots:
            warnings.append(f"Dashboard snapshots not available yet for: {', '.join(missing_snapshots)}.")

        power = db.scalar(select(BlumTradingPowerScore).order_by(desc(BlumTradingPowerScore.calculated_at)).limit(1))
        if power is None:
            missing_sections.append("trading_power_score")
            warnings.append("Trading Power Score has not been precomputed yet.")

        game = db.scalar(select(TradingGame).order_by(desc(TradingGame.updated_at)).limit(1))
        if game is None:
            missing_sections.append("trading_game")
            warnings.append("No trading game is available yet.")

        current_cycle = None
        if game is not None:
            current_cycle = db.scalar(
                select(TradingCapitalCycle)
                .where(TradingCapitalCycle.game_id == game.id)
                .order_by(desc(TradingCapitalCycle.started_at))
                .limit(1)
            )

        latest_run = db.scalar(select(LearningRun).order_by(desc(LearningRun.started_at)).limit(1))
        if latest_run is None:
            missing_sections.append("latest_learning_run")

        latest_metric = db.scalar(select(TradingIntelligenceMetric).order_by(desc(TradingIntelligenceMetric.calculated_at)).limit(1))
        if latest_metric is None:
            missing_sections.append("trading_intelligence_metrics")

        top_weakness = db.scalar(select(LearningStrengthWeaknessMap).order_by(desc(LearningStrengthWeaknessMap.weakness_score), desc(LearningStrengthWeaknessMap.calculated_at)).limit(1))
        latest_lesson = db.scalar(select(TradeLearningEvidence).order_by(desc(TradeLearningEvidence.created_at)).limit(1))

        benchmarks = list(db.scalars(select(LearningBenchmarkComparison).order_by(desc(LearningBenchmarkComparison.calculated_at)).limit(24)).all())
        benchmark_summary = summarize_benchmarks(benchmarks)
        if not benchmarks:
            missing_sections.append("benchmark_summary")

        live_snapshot = DashboardSnapshotService().latest(db, "live_vs_historical_summary")
        if live_snapshot["status"] == "missing":
            warnings.append("Live vs historical summary snapshot is missing.")

        current_capital = getattr(current_cycle, "final_capital", None) if current_cycle else getattr(game, "current_capital", None)
        target_capital = getattr(current_cycle, "target_capital", None) if current_cycle else getattr(game, "target_capital", None)
        target_progress = safe_progress(current_capital, target_capital)
        current_cycle_payload = serialize_cycle(current_cycle)
        truth_panel_lines = build_truth_panel(power, benchmark_summary, warnings, benchmarks)
        truth_snapshot = snapshots.get("truth_panel_summary", {})
        truth_snapshot_payload = truth_snapshot.get("payload") or {}
        if truth_snapshot_payload.get("truth_panel"):
            truth_panel_lines = truth_snapshot_payload["truth_panel"]
        last_snapshot_timestamp = latest_snapshot_timestamp(snapshots)
        backend_training_status = training_status(latest_run, snapshots)
        payload = {
            "status": "initializing" if missing_sections else "ready",
            "generated_at": datetime.utcnow().isoformat(),
            "summary_duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "learning_loop_status": getattr(latest_run, "status", None) or "not_started",
            "trading_power_score": power.score if power else None,
            "trading_power_classification": power.classification if power else "initializing",
            "current_capital_cycle": current_cycle_payload,
            "current_capital": current_capital,
            "target_capital": target_capital,
            "target_progress": target_progress,
            "win_rate": first_not_none(getattr(latest_metric, "win_rate", None), getattr(game, "win_rate", None)),
            "expectancy_r": first_not_none(getattr(latest_metric, "expectancy_r", None), getattr(current_cycle, "expectancy_r", None), getattr(game, "expectancy_r", None)),
            "completed_target_cycles": getattr(game, "target_cycles_completed", 0) if game else 0,
            "bankrupt_cycles": getattr(game, "bankrupt_cycles", 0) if game else 0,
            "latest_learning_run_status": getattr(latest_run, "status", None) or "not_started",
            "latest_learning_run_at": latest_run.started_at.isoformat() if latest_run and latest_run.started_at else None,
            "benchmark_summary": benchmark_summary,
            "live_vs_historical_summary": live_snapshot,
            "live_vs_historical_status": live_snapshot.get("status", "missing"),
            "top_weakness": serialize_weakness(top_weakness),
            "latest_lesson_learned": serialize_lesson(latest_lesson),
            "truth_panel": truth_panel_lines,
            "backend_training_status": backend_training_status,
            "last_snapshot_timestamp": last_snapshot_timestamp,
            "snapshots": summarize_snapshots(snapshots),
            "warnings": warnings,
            "missing_sections": missing_sections,
            "data_freshness": {
                "trading_power_calculated_at": power.calculated_at.isoformat() if power and power.calculated_at else None,
                "game_updated_at": game.updated_at.isoformat() if game and game.updated_at else None,
                "learning_run_started_at": latest_run.started_at.isoformat() if latest_run and latest_run.started_at else None,
                "benchmark_calculated_at": max((row.calculated_at for row in benchmarks if row.calculated_at), default=None).isoformat() if benchmarks else None,
                "trading_intelligence_calculated_at": latest_metric.calculated_at.isoformat() if latest_metric and latest_metric.calculated_at else None,
                "last_snapshot_timestamp": last_snapshot_timestamp,
            },
            "is_recalculation_running": backend_training_status["is_recalculation_running"],
            "suggested_next_step": "Use background workers or explicit recalculation buttons to refresh missing summaries." if missing_sections else "Summary is ready.",
            "performance": {
                "budget_ms": 300,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "source": "snapshots_first_latest_precomputed_rows_only",
            },
        }
        performance_recorder.record_dashboard_widget(
            "learning.summary_endpoint",
            payload["performance"]["duration_ms"],
            {"status": payload["status"], "missing": len(missing_sections)},
        )
        return payload


def summarize_benchmarks(rows: list[LearningBenchmarkComparison]) -> dict:
    latest_by_name: dict[str, LearningBenchmarkComparison] = {}
    for row in rows:
        latest_by_name.setdefault(row.benchmark_name, row)
    important = {}
    for name in ["SPY", "QQQ", "VTI"]:
        row = latest_by_name.get(name)
        important[name] = {
            "result_label": row.result_label if row else "insufficient_sample",
            "excess_return": row.excess_return if row else None,
            "sample_size": row.sample_size if row else 0,
            "statistical_confidence": row.statistical_confidence if row else "very low evidence",
        }
    outperforming = sum(1 for row in latest_by_name.values() if row.result_label == "outperforming")
    underperforming = sum(1 for row in latest_by_name.values() if row.result_label == "underperforming")
    return {
        "status": "ready" if latest_by_name else "initializing",
        "tracked_benchmarks": len(latest_by_name),
        "outperforming_count": outperforming,
        "underperforming_count": underperforming,
        "major_benchmarks": important,
    }


def build_truth_panel(power: BlumTradingPowerScore | None, benchmark_summary: dict, warnings: list[str], rows: list[LearningBenchmarkComparison]) -> list[str]:
    output = []
    if power is None:
        output.append("Not enough precomputed evidence yet to rate BLUM Trading Power.")
    else:
        output.append(f"Trading Power Score is {power.score:.1f}/100: {power.classification}.")
    for name, item in benchmark_summary.get("major_benchmarks", {}).items():
        label = item.get("result_label")
        excess = item.get("excess_return")
        if label == "outperforming":
            output.append(f"BLUM is outperforming {name} on stored evidence, excess {format_number(excess)}%.")
        elif label == "underperforming":
            output.append(f"BLUM is underperforming {name} on stored evidence, excess {format_number(excess)}%.")
        else:
            output.append(f"BLUM vs {name}: {label}; no strong conclusion.")
    output.extend(warnings[:3])
    return output[:7]


def safe_progress(capital: float | None, target: float | None) -> float | None:
    if capital is None or target is None or target <= 0:
        return None
    return round(max(0, min(1, float(capital) / float(target))), 4)


def format_number(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def first_not_none(*values):
    for value in values:
        if value is not None:
            return value
    return None


def serialize_cycle(row: TradingCapitalCycle | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "cycle_number": row.cycle_number,
        "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "start_capital": row.start_capital,
        "target_capital": row.target_capital,
        "final_capital": row.final_capital,
        "trades_count": row.trades_count,
        "wins": row.wins,
        "losses": row.losses,
        "missed_entries": row.missed_entries,
        "target_hits": row.target_hits,
        "stop_hits": row.stop_hits,
        "expectancy_r": row.expectancy_r,
        "excess_return_vs_benchmark": row.excess_return_vs_benchmark,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def serialize_weakness(row: LearningStrengthWeaknessMap | None) -> dict | None:
    if row is None:
        return None
    return {
        "dimension": row.dimension,
        "entity": row.entity,
        "weakness_score": row.weakness_score,
        "strength_score": row.strength_score,
        "sample_size": row.sample_size,
        "main_problem": row.main_problem,
        "recommended_action": row.recommended_action,
        "priority": row.priority,
        "calculated_at": row.calculated_at.isoformat() if row.calculated_at else None,
    }


def serialize_lesson(row: TradeLearningEvidence | None) -> dict | None:
    if row is None:
        return None
    return {
        "ticker": row.ticker,
        "setup_type": row.setup_type,
        "lesson_type": row.lesson_type,
        "observation": row.observation,
        "sample_size": row.sample_size,
        "affected_module": row.affected_module,
        "confidence": row.confidence,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def summarize_snapshots(snapshots: dict[str, dict]) -> dict:
    output = {}
    for snapshot_type, payload in snapshots.items():
        output[snapshot_type] = {
            "status": payload.get("status"),
            "created_at": payload.get("created_at"),
            "expires_at": payload.get("expires_at"),
            "is_stale": payload.get("is_stale"),
            "warnings": payload.get("warnings") or ([payload.get("warning")] if payload.get("warning") else []),
        }
    return output


def latest_snapshot_timestamp(snapshots: dict[str, dict]) -> str | None:
    timestamps = [payload.get("created_at") for payload in snapshots.values() if payload.get("created_at")]
    return max(timestamps) if timestamps else None


def training_status(latest_run: LearningRun | None, snapshots: dict[str, dict]) -> dict:
    running_statuses = {"running", "queued", "processing", "in_progress"}
    status = getattr(latest_run, "status", None) or "not_started"
    running = status in running_statuses
    stale_count = sum(1 for payload in snapshots.values() if payload.get("status") == "stale")
    return {
        "mode": "backend_scheduler_independent",
        "status": "running" if running else status,
        "is_recalculation_running": running,
        "frontend_policy": "read_only_snapshot_observer",
        "stale_snapshot_count": stale_count,
        "latest_run_id": getattr(latest_run, "run_id", None),
    }
