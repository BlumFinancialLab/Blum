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
    TradingCapitalCycle,
    TradingGame,
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
        truth_panel_lines = build_truth_panel(power, benchmark_summary, warnings, benchmarks)
        payload = {
            "status": "initializing" if missing_sections else "ready",
            "generated_at": datetime.utcnow().isoformat(),
            "summary_duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "trading_power_score": power.score if power else None,
            "trading_power_classification": power.classification if power else "initializing",
            "current_capital": current_capital,
            "target_capital": target_capital,
            "target_progress": target_progress,
            "completed_target_cycles": getattr(game, "target_cycles_completed", 0) if game else 0,
            "bankrupt_cycles": getattr(game, "bankrupt_cycles", 0) if game else 0,
            "latest_learning_run_status": getattr(latest_run, "status", None) or "not_started",
            "latest_learning_run_at": latest_run.started_at.isoformat() if latest_run and latest_run.started_at else None,
            "benchmark_summary": benchmark_summary,
            "live_vs_historical_summary": live_snapshot,
            "truth_panel": truth_panel_lines,
            "warnings": warnings,
            "missing_sections": missing_sections,
            "data_freshness": {
                "trading_power_calculated_at": power.calculated_at.isoformat() if power and power.calculated_at else None,
                "game_updated_at": game.updated_at.isoformat() if game and game.updated_at else None,
                "learning_run_started_at": latest_run.started_at.isoformat() if latest_run and latest_run.started_at else None,
                "benchmark_calculated_at": max((row.calculated_at for row in benchmarks if row.calculated_at), default=None).isoformat() if benchmarks else None,
            },
            "is_recalculation_running": False,
            "suggested_next_step": "Use background workers or explicit recalculation buttons to refresh missing summaries." if missing_sections else "Summary is ready.",
            "performance": {
                "budget_ms": 300,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "source": "latest_precomputed_rows_only",
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
