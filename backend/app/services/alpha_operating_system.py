from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from statistics import mean
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import (
    AlphaLossAttribution,
    AlphaRecoveryAction,
    BackgroundJobState,
    BlumTradingPowerScore,
    BusinessQualityScore,
    DashboardSnapshot,
    DecisionSuperiorityScore,
    EquityCurveSnapshot,
    LearningBenchmarkComparison,
    LearningFocusPriority,
    LearningRun,
    LearningStrengthWeaknessMap,
    PaperCopyOrder,
    PaperCopyPortfolio,
    PaperCopyPortfolioSnapshot,
    PaperCopyPosition,
    PaperCopyStrategy,
    PortfolioQualityScore,
    SniperScore,
    TradeLearningEvidence,
    TradePlan,
    TradingGame,
    TradingGameLedgerSnapshot,
    TradingGameReadinessSnapshot,
    TradingGameTrade,
    TradingIntelligenceMetric,
)
from app.services.copy_trading_intelligence import COPY_TRADING_POLICY, CopyTradingIntelligenceService
from app.services.dashboard_snapshots import DashboardSnapshotService
from app.services.learning_summary import LearningSummaryService


V1_VERSION = "1.0.0"
V1_FEATURE_SET = "alpha-operating-system"
READINESS_METHODOLOGY = "trading-game-readiness-v1"
ALPHA_METHODOLOGY = "alpha-readiness-v1"


class TradingGameReadinessService:
    """Explains why the Trading Game can or cannot render usable evidence.

    GET endpoints call `readiness`, which is bounded and read-only. Snapshot
    producer jobs may call `snapshot_payload` and persist it through the generic
    dashboard snapshot table.
    """

    def readiness(self, db: Session) -> dict:
        game = latest_game(db)
        ledger = latest_row(db, TradingGameLedgerSnapshot)
        equity = latest_row(db, EquityCurveSnapshot)
        latest_trade = db.scalar(select(TradingGameTrade).order_by(desc(TradingGameTrade.created_at)).limit(1))
        source_decision_count = int(db.scalar(select(func.count(TradePlan.id))) or 0)
        source_sniper_count = int(db.scalar(select(func.count(SniperScore.id))) or 0)
        source_trade_count = int(db.scalar(select(func.count(TradingGameTrade.id))) or 0)
        completed_trade_count = int(db.scalar(select(func.count(TradingGameTrade.id)).where(TradingGameTrade.exit_date.is_not(None))) or 0)
        open_trade_count = int(db.scalar(select(func.count(TradingGameTrade.id)).where(TradingGameTrade.exit_date.is_(None))) or 0)
        eligible_trade_count = int(
            db.scalar(
                select(func.count(TradingGameTrade.id)).where(
                    TradingGameTrade.entry_price.is_not(None),
                    TradingGameTrade.position_size > 0,
                    TradingGameTrade.invalidation_level.is_not(None),
                )
            )
            or 0
        )
        latest_job = latest_background_job(db, "blum_trading_game")
        latest_snapshot_job = latest_background_job(db, "snapshot_producer")
        ledger_status = snapshot_status(ledger)
        equity_status = snapshot_status(equity)
        warnings: list[str] = []
        blocker = ""
        next_action = "Backend learning and snapshot workers can continue normally."

        if game is None:
            status = "WAITING_FOR_SOURCE_DATA"
            blocker = "No TradingGame row exists yet."
            next_action = "Let the backend Trading Game worker create the first paper game."
        elif source_trade_count == 0 and source_decision_count == 0 and source_sniper_count == 0:
            status = "WAITING_FOR_SOURCE_DATA"
            blocker = "No source decisions, sniper scores or trades exist yet."
            next_action = "Let Market Sniper and Learning Loop generate source decisions."
        elif source_trade_count == 0:
            status = "BUILDING"
            blocker = "Trade plans or sniper evidence exist, but no paper trades are stored yet."
            next_action = "Let the Trading Game worker convert eligible decisions into paper trades."
        elif ledger is None or equity is None:
            status = "BUILDING"
            blocker = "Trading Game rows exist, but ledger/equity snapshots are not ready."
            next_action = "Run the snapshot producer in background; do not block the UI."
            warnings.append("Trading evidence exists but snapshots are missing.")
        elif ledger_status == "failed" or equity_status == "failed":
            status = "FAILED"
            blocker = "A required Trading Game snapshot is marked failed."
            next_action = "Check snapshot producer logs and rebuild the affected snapshot."
        elif ledger_status == "stale" or equity_status == "stale":
            status = "STALE_BUT_USABLE"
            warnings.append("Trading Game snapshot is stale; UI can render while refresh catches up.")
        elif eligible_trade_count < 3:
            status = "INSUFFICIENT_EVIDENCE"
            blocker = "Fewer than three eligible trades have full risk plan evidence."
            next_action = "Keep collecting paper trades before drawing performance conclusions."
        else:
            status = "READY"

        data_quality_blockers = []
        if source_trade_count and eligible_trade_count == 0:
            data_quality_blockers.append("stored trades lack entry/risk/invalidation fields")
        if data_quality_blockers:
            status = "DATA_QUALITY_BLOCKED"
            blocker = "; ".join(data_quality_blockers)
            next_action = "Repair trade transparency enrichment before evaluating performance."

        evidence_grade = evidence_grade_for(completed_trade_count, live_trade_count=db_live_trade_count(db), has_benchmark=has_benchmark_rows(db))
        payload = {
            "status": status,
            "generated_at": datetime.utcnow().isoformat(),
            "methodology_version": READINESS_METHODOLOGY,
            "game_id": game.game_id if game else None,
            "game_pk": game.id if game else None,
            "source_decision_count": source_decision_count + source_sniper_count,
            "source_trade_plan_count": source_decision_count,
            "source_sniper_score_count": source_sniper_count,
            "source_trade_count": source_trade_count,
            "completed_trade_count": completed_trade_count,
            "open_trade_count": open_trade_count,
            "eligible_trade_count": eligible_trade_count,
            "ledger_snapshot_status": ledger_status,
            "equity_snapshot_status": equity_status,
            "benchmark_snapshot_status": benchmark_snapshot_status(db),
            "last_trade_at": latest_trade.created_at.isoformat() if latest_trade and latest_trade.created_at else None,
            "last_ledger_snapshot_at": ledger.created_at.isoformat() if ledger and ledger.created_at else None,
            "last_equity_snapshot_at": equity.created_at.isoformat() if equity and equity.created_at else None,
            "worker_status": {
                "trading_game": serialize_job(latest_job),
                "snapshot_producer": serialize_job(latest_snapshot_job),
            },
            "worker_phase": latest_job.stage_name if latest_job else None,
            "blocker": blocker,
            "next_required_action": next_action,
            "evidence_grade": evidence_grade,
            "warnings": warnings,
            "ui_state_policy": "Never show permanent generic loading. Render one of READY, BUILDING, WAITING_FOR_SOURCE_DATA, STALE_BUT_USABLE, FAILED, INSUFFICIENT_EVIDENCE, DATA_QUALITY_BLOCKED.",
        }
        return payload

    def latest_snapshot(self, db: Session) -> dict:
        row = latest_row(db, TradingGameReadinessSnapshot)
        if row is None:
            return {"status": "missing", "payload": None}
        return {
            "status": "stale" if is_stale(row) else "ready",
            "payload": row.payload_json or {},
            "created_at": row.generated_at.isoformat() if row.generated_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "warnings": row.warnings_json or [],
        }


class BrainCommandSummaryService:
    """Compact status of BLUM's brain for the Command page."""

    def summary(self, db: Session) -> dict:
        learning = LearningSummaryService().summary(db)
        readiness = TradingGameReadinessService().readiness(db)
        alpha = AlphaReadinessEngine().readiness(db)
        paper = PaperCopyTradingService().summary(db, limit=8)
        latest_power = latest_row(db, BlumTradingPowerScore)
        latest_decision = latest_row(db, DecisionSuperiorityScore)
        latest_business = latest_row(db, BusinessQualityScore)
        latest_portfolio = latest_row(db, PortfolioQualityScore)
        latest_metric = latest_row(db, TradingIntelligenceMetric)
        latest_run = latest_row(db, LearningRun)
        weakness = db.scalar(select(LearningStrengthWeaknessMap).order_by(desc(LearningStrengthWeaknessMap.weakness_score), desc(LearningStrengthWeaknessMap.calculated_at)).limit(1))
        focus = db.scalar(
            select(LearningFocusPriority)
            .where(LearningFocusPriority.status.in_(["active", "proposed"]))
            .order_by(desc(LearningFocusPriority.expected_learning_value), desc(LearningFocusPriority.created_at))
            .limit(1)
        )
        capabilities = capability_matrix(
            trading_power=latest_power,
            decision=latest_decision,
            business=latest_business,
            portfolio=latest_portfolio,
            metric=latest_metric,
            readiness=readiness,
            alpha=alpha,
            paper=paper,
        )
        score_values = [item["score"] for item in capabilities if item["score"] is not None]
        brain_score = round(mean(score_values), 2) if score_values else None
        warnings = list(learning.get("warnings") or [])[:3] + alpha.get("warnings", [])[:3] + paper.get("warnings", [])[:3]
        return {
            "status": "ready" if brain_score is not None else "initializing",
            "version": V1_VERSION,
            "feature_set": V1_FEATURE_SET,
            "generated_at": datetime.utcnow().isoformat(),
            "brain_capability_score": brain_score,
            "brain_classification": classify_brain_score(brain_score),
            "brain_status_strip": {
                "learning_status": learning.get("learning_loop_status"),
                "trading_game_readiness": readiness.get("status"),
                "alpha_readiness": alpha.get("status"),
                "paper_copy_readiness": paper.get("readiness", {}).get("status"),
                "latest_run_at": learning.get("latest_learning_run_at"),
            },
            "learning_evolution": {
                "latest_run_status": getattr(latest_run, "status", None) if latest_run else learning.get("latest_learning_run_status"),
                "win_rate": learning.get("win_rate"),
                "expectancy_r": learning.get("expectancy_r"),
                "target_progress": learning.get("target_progress"),
                "trading_power_score": learning.get("trading_power_score"),
                "trading_power_classification": learning.get("trading_power_classification"),
            },
            "capability_matrix": capabilities,
            "benchmark_truth": learning.get("benchmark_summary"),
            "improvement_regression": {
                "top_weakness": serialize_weakness(weakness),
                "next_focus": serialize_focus(focus),
                "latest_lesson": learning.get("latest_lesson_learned"),
                "truth_panel": learning.get("truth_panel") or [],
            },
            "copy_readiness": paper.get("readiness"),
            "warnings": dedupe(warnings),
            "data_freshness": {
                "learning_summary": learning.get("generated_at"),
                "trading_game_readiness": readiness.get("generated_at"),
                "alpha_readiness": alpha.get("generated_at"),
                "paper_copy": paper.get("generated_at"),
            },
            "policy": "Command reads compact evidence summaries only. It does not trigger learning, recalculation, trading or broker execution.",
        }

    def capabilities(self, db: Session) -> dict:
        summary = self.summary(db)
        return {"status": summary["status"], "rows": summary["capability_matrix"], "generated_at": summary["generated_at"]}

    def evolution(self, db: Session) -> dict:
        rows = db.scalars(select(BlumTradingPowerScore).order_by(desc(BlumTradingPowerScore.calculated_at)).limit(30)).all()
        return {
            "status": "ready" if rows else "insufficient_evidence",
            "rows": [
                {
                    "calculated_at": row.calculated_at.isoformat() if row.calculated_at else None,
                    "score": row.score,
                    "classification": row.classification,
                    "benchmark_relative_score": row.benchmark_relative_score,
                    "learning_velocity_score": row.learning_velocity_score,
                }
                for row in rows
            ],
            "policy": "Evolution uses stored Trading Power snapshots only.",
        }


class AlphaReadinessEngine:
    """Strict alpha readiness summary from stored evidence only."""

    def readiness(self, db: Session) -> dict:
        power = latest_row(db, BlumTradingPowerScore)
        decision = latest_row(db, DecisionSuperiorityScore)
        portfolio = latest_row(db, PortfolioQualityScore)
        benchmark_rows = db.scalars(select(LearningBenchmarkComparison).order_by(desc(LearningBenchmarkComparison.calculated_at)).limit(20)).all()
        trade_count = int(db.scalar(select(func.count(TradingGameTrade.id))) or 0)
        live_count = db_live_trade_count(db)
        warnings: list[str] = []
        components = {
            "trading_power": getattr(power, "score", None),
            "decision_superiority": getattr(decision, "score", None),
            "portfolio_quality": getattr(portfolio, "portfolio_quality_score", None),
            "benchmark_evidence": benchmark_component(benchmark_rows),
            "sample_depth": sample_depth_score(trade_count),
            "live_validation": sample_depth_score(live_count),
        }
        values = [value for value in components.values() if value is not None]
        score = round(mean(values), 2) if values else 0.0
        if trade_count < 30:
            score = min(score, 60.0)
            warnings.append("insufficient_trade_sample_caps_alpha_readiness_at_60")
        if live_count < 10:
            score = min(score, 75.0)
            warnings.append("live_forward_evidence_is_not_mature")
        if not benchmark_rows:
            score = min(score, 50.0)
            warnings.append("benchmark_comparison_missing")
        evidence_grade = evidence_grade_for(trade_count, live_count, bool(benchmark_rows))
        status = "READY_FOR_RESEARCH" if score >= 60 and evidence_grade not in {"insufficient", "very_low"} else "INSUFFICIENT_EVIDENCE"
        return {
            "status": status,
            "generated_at": datetime.utcnow().isoformat(),
            "methodology_version": ALPHA_METHODOLOGY,
            "alpha_readiness_score": score,
            "classification": classify_alpha_score(score),
            "evidence_grade": evidence_grade,
            "components": components,
            "benchmark_summary": benchmark_truth(benchmark_rows),
            "sample": {"trades": trade_count, "live_forward_trades": live_count, "benchmarks": len(benchmark_rows)},
            "warnings": dedupe(warnings),
            "truth_layer": alpha_truth(score, benchmark_rows, trade_count, live_count),
            "policy": "No alpha claim is valid without benchmark-relative evidence, sample size and live paper validation.",
        }


class EdgeMapService:
    """Lightweight map of where stored Trading Game evidence appears strongest/weakest."""

    def edge_map(self, db: Session, limit: int = 12) -> dict:
        rows = db.scalars(select(TradingGameTrade).order_by(desc(TradingGameTrade.created_at)).limit(500)).all()
        by_setup = aggregate_edges(rows, "setup_type")
        by_sector = aggregate_edges(rows, "sector")
        by_regime = aggregate_edges(rows, "market_regime_at_entry")
        return {
            "status": "ready" if rows else "insufficient_evidence",
            "generated_at": datetime.utcnow().isoformat(),
            "sample_size": len(rows),
            "evidence_grade": evidence_grade_for(len(rows), db_live_trade_count(db), has_benchmark_rows(db)),
            "best_setups": sorted(by_setup, key=lambda item: item["edge_score"], reverse=True)[:limit],
            "weakest_setups": sorted(by_setup, key=lambda item: item["edge_score"])[:limit],
            "best_sectors": sorted(by_sector, key=lambda item: item["edge_score"], reverse=True)[:limit],
            "weakest_sectors": sorted(by_sector, key=lambda item: item["edge_score"])[:limit],
            "regimes": sorted(by_regime, key=lambda item: item["edge_score"], reverse=True)[:limit],
            "warnings": ["sample_size_low"] if len(rows) < 50 else [],
            "policy": "Edge map is descriptive stored evidence, not a prediction or guarantee.",
        }


class AlphaGateService:
    """Converts evidence into transparent gates before BLUM can call a setup copyable."""

    def gates(self, db: Session) -> dict:
        alpha = AlphaReadinessEngine().readiness(db)
        readiness = TradingGameReadinessService().readiness(db)
        paper = PaperCopyTradingService().summary(db, limit=5)
        gates = [
            gate("sample_depth", alpha["sample"]["trades"] >= 30, alpha["sample"]["trades"], ">= 30 stored paper trades"),
            gate("live_validation", alpha["sample"]["live_forward_trades"] >= 10, alpha["sample"]["live_forward_trades"], ">= 10 live forward paper trades"),
            gate("benchmark_evidence", alpha["sample"]["benchmarks"] > 0, alpha["sample"]["benchmarks"], "benchmark rows exist"),
            gate("trading_game_renderable", readiness["status"] in {"READY", "STALE_BUT_USABLE", "INSUFFICIENT_EVIDENCE"}, readiness["status"], "Trading Game evidence can render"),
            gate("paper_copy_guardrails", paper["paper_only"] and paper["no_broker_execution"], "paper_only", "no broker execution"),
        ]
        return {
            "status": "ready",
            "generated_at": datetime.utcnow().isoformat(),
            "alpha_readiness_score": alpha["alpha_readiness_score"],
            "all_required_gates_passed": all(item["passed"] for item in gates if item["required"]),
            "rows": gates,
            "policy": "Gates are pre-trade research controls. They do not authorize real trading.",
        }


class PaperCopyTradingService:
    """Paper-only copy trading operating layer.

    This wraps existing CopyTradingIntelligenceService evidence and exposes
    durable portfolio/strategy state when present. It never connects to brokers.
    """

    def readiness(self, db: Session) -> dict:
        candidate_payload = CopyTradingIntelligenceService().candidates(db, limit=20)
        strategy_count = int(db.scalar(select(func.count(PaperCopyStrategy.id))) or 0)
        portfolio_count = int(db.scalar(select(func.count(PaperCopyPortfolio.id))) or 0)
        position_count = int(db.scalar(select(func.count(PaperCopyPosition.id))) or 0)
        order_count = int(db.scalar(select(func.count(PaperCopyOrder.id))) or 0)
        copyable = [row for row in candidate_payload.get("rows", []) if row.get("copy_readiness") in {"copy_ready_if_triggered", "wait_for_trigger"}]
        status = "READY_FOR_PAPER_MONITORING" if copyable else "WAITING_FOR_COPYABLE_SETUPS"
        warnings = []
        if not strategy_count:
            warnings.append("no_durable_paper_copy_strategy_created_yet")
        if not portfolio_count:
            warnings.append("no_durable_paper_copy_portfolio_created_yet")
        return {
            "status": status,
            "candidate_count": len(candidate_payload.get("rows", [])),
            "copyable_candidate_count": len(copyable),
            "strategy_count": strategy_count,
            "portfolio_count": portfolio_count,
            "open_position_count": position_count,
            "pending_order_count": order_count,
            "warnings": warnings,
        }

    def summary(self, db: Session, limit: int = 12) -> dict:
        dashboard = CopyTradingIntelligenceService().dashboard(db, limit=limit)
        readiness = self.readiness(db)
        latest_strategy = latest_row(db, PaperCopyStrategy)
        latest_portfolio = latest_row(db, PaperCopyPortfolio)
        latest_snapshot = latest_row(db, PaperCopyPortfolioSnapshot)
        return {
            "status": dashboard.get("status", "ok"),
            "generated_at": datetime.utcnow().isoformat(),
            "mode": "paper_copy_operating_system",
            "paper_only": True,
            "no_broker_execution": True,
            "readiness": readiness,
            "summary": dashboard.get("summary", {}),
            "rows": dashboard.get("rows", []),
            "strategy": serialize_paper_strategy(latest_strategy),
            "portfolio": serialize_paper_portfolio(latest_portfolio),
            "portfolio_snapshot": serialize_paper_snapshot(latest_snapshot),
            "guardrails": dashboard.get("guardrails", []),
            "truth_layer": dashboard.get("truth_layer", []),
            "warnings": readiness.get("warnings", []),
            "policy": COPY_TRADING_POLICY,
        }

    def strategies(self, db: Session, limit: int = 40) -> dict:
        rows = db.scalars(select(PaperCopyStrategy).order_by(desc(PaperCopyStrategy.created_at)).limit(limit)).all()
        if not rows:
            summary = self.summary(db, limit=8)
            return {
                "status": "no_durable_strategy_yet",
                "rows": [],
                "candidate_strategy": strategy_candidate_from_summary(summary),
                "policy": COPY_TRADING_POLICY,
            }
        return {"status": "ready", "rows": [serialize_paper_strategy(row) for row in rows], "policy": COPY_TRADING_POLICY}

    def positions(self, db: Session, limit: int = 80) -> dict:
        rows = db.scalars(select(PaperCopyPosition).order_by(desc(PaperCopyPosition.opened_at)).limit(limit)).all()
        return {"status": "ready" if rows else "empty", "rows": [serialize_paper_position(row) for row in rows], "policy": COPY_TRADING_POLICY}

    def portfolio(self, db: Session, portfolio_id: str) -> dict:
        row = db.scalar(select(PaperCopyPortfolio).where(PaperCopyPortfolio.portfolio_id == portfolio_id).limit(1))
        if row is None:
            return {"status": "not_found", "portfolio_id": portfolio_id, "policy": COPY_TRADING_POLICY}
        positions = db.scalars(select(PaperCopyPosition).where(PaperCopyPosition.portfolio_id == row.id).order_by(desc(PaperCopyPosition.opened_at)).limit(80)).all()
        snapshots = db.scalars(select(PaperCopyPortfolioSnapshot).where(PaperCopyPortfolioSnapshot.portfolio_id == row.id).order_by(desc(PaperCopyPortfolioSnapshot.created_at)).limit(80)).all()
        return {
            "status": "ready",
            "portfolio": serialize_paper_portfolio(row),
            "positions": [serialize_paper_position(item) for item in positions],
            "snapshots": [serialize_paper_snapshot(item) for item in snapshots],
            "policy": COPY_TRADING_POLICY,
        }


def latest_game(db: Session) -> TradingGame | None:
    return db.scalar(select(TradingGame).order_by(desc(TradingGame.updated_at)).limit(1))


def latest_row(db: Session, model):
    order_column = None
    for name in ["created_at", "generated_at", "calculated_at", "updated_at"]:
        if hasattr(model, name):
            order_column = getattr(model, name)
            break
    if order_column is None:
        return db.scalar(select(model).limit(1))
    return db.scalar(select(model).order_by(desc(order_column)).limit(1))


def latest_background_job(db: Session, job_name: str) -> BackgroundJobState | None:
    return db.scalar(select(BackgroundJobState).where(BackgroundJobState.job_name == job_name).order_by(desc(BackgroundJobState.last_started_at)).limit(1))


def snapshot_status(row: Any | None) -> str:
    if row is None:
        return "missing"
    if getattr(row, "is_stale", False):
        return "stale"
    expires = getattr(row, "expires_at", None)
    if expires and expires < datetime.utcnow():
        return "stale"
    if (getattr(row, "payload_json", None) or {}).get("status") == "failed":
        return "failed"
    return "ready"


def benchmark_snapshot_status(db: Session) -> str:
    snapshot = db.scalar(select(DashboardSnapshot).where(DashboardSnapshot.snapshot_type == "benchmark_summary").order_by(desc(DashboardSnapshot.created_at)).limit(1))
    if snapshot is None:
        return "missing"
    return "stale" if is_stale(snapshot) else "ready"


def is_stale(row: Any) -> bool:
    expires = getattr(row, "expires_at", None)
    return bool(getattr(row, "is_stale", False) or (expires is not None and expires < datetime.utcnow()))


def db_live_trade_count(db: Session) -> int:
    return int(db.scalar(select(func.count(TradingGameTrade.id)).where(TradingGameTrade.mode.like("%live%"))) or 0)


def has_benchmark_rows(db: Session) -> bool:
    return bool(db.scalar(select(LearningBenchmarkComparison.id).limit(1)))


def evidence_grade_for(trades: int, live_trade_count: int, has_benchmark: bool) -> str:
    if trades < 10:
        return "insufficient"
    if trades < 30:
        return "very_low"
    if trades < 100:
        return "low" if not has_benchmark else "medium_low"
    if live_trade_count < 30:
        return "medium"
    return "strong"


def benchmark_component(rows: list[LearningBenchmarkComparison]) -> float | None:
    if not rows:
        return None
    values = []
    for row in rows:
        excess = row.excess_return
        if excess is None:
            continue
        values.append(max(0.0, min(100.0, 50.0 + float(excess))))
    return round(mean(values), 2) if values else None


def sample_depth_score(count: int) -> float:
    if count <= 0:
        return 0.0
    if count >= 250:
        return 100.0
    return round(min(100.0, count / 2.5), 2)


def benchmark_truth(rows: list[LearningBenchmarkComparison]) -> dict:
    latest: dict[str, LearningBenchmarkComparison] = {}
    for row in rows:
        latest.setdefault(row.benchmark_name, row)
    return {
        name: {
            "result_label": row.result_label,
            "excess_return": row.excess_return,
            "sample_size": row.sample_size,
            "statistical_confidence": row.statistical_confidence,
        }
        for name, row in latest.items()
    }


def alpha_truth(score: float, rows: list[LearningBenchmarkComparison], trade_count: int, live_count: int) -> list[str]:
    lines = [f"Alpha Readiness is {score:.1f}/100 from stored evidence only."]
    if not rows:
        lines.append("Benchmark evidence is missing, so no outperformance claim is valid.")
    if trade_count < 30:
        lines.append("Trade sample is too small for durable conclusions.")
    if live_count < 10:
        lines.append("Live paper validation is not mature yet.")
    under = [row for row in rows if row.result_label == "underperforming"]
    if under:
        lines.append(f"BLUM is underperforming {under[0].benchmark_name} on the latest stored comparison.")
    return lines[:5]


def classify_alpha_score(score: float) -> str:
    if score < 25:
        return "not_ready"
    if score < 50:
        return "experimental"
    if score < 70:
        return "research_candidate"
    if score < 85:
        return "paper_evidence_promising"
    return "requires_external_validation"


def classify_brain_score(score: float | None) -> str:
    if score is None:
        return "initializing"
    if score < 25:
        return "evidence poor"
    if score < 50:
        return "learning but weak"
    if score < 70:
        return "research grade"
    if score < 85:
        return "strong paper evidence"
    return "advanced, needs external validation"


def capability_matrix(
    *,
    trading_power: BlumTradingPowerScore | None,
    decision: DecisionSuperiorityScore | None,
    business: BusinessQualityScore | None,
    portfolio: PortfolioQualityScore | None,
    metric: TradingIntelligenceMetric | None,
    readiness: dict,
    alpha: dict,
    paper: dict,
) -> list[dict]:
    return [
        capability("Trading Intelligence", getattr(trading_power, "score", None), getattr(trading_power, "classification", None), sample_from_metric(metric), "paper P/L, expectancy, benchmark context"),
        capability("Decision Superiority", getattr(decision, "score", None), getattr(decision, "classification", None), None, "opportunity recall, precision and ranking accuracy"),
        capability("Business Quality", getattr(business, "business_quality_score", None), getattr(business, "ticker", None), None, "fundamental quality evidence"),
        capability("Portfolio Intelligence", getattr(portfolio, "portfolio_quality_score", None), None, None, "risk contribution, concentration and capital efficiency"),
        capability("Trading Game Readiness", readiness_score(readiness.get("status")), readiness.get("status"), readiness.get("completed_trade_count"), "ledger, equity and benchmark renderability"),
        capability("Alpha Readiness", alpha.get("alpha_readiness_score"), alpha.get("classification"), alpha.get("sample", {}).get("trades"), "strict capped alpha evidence"),
        capability("Paper Copy Readiness", copy_score_from_summary(paper), paper.get("readiness", {}).get("status"), paper.get("readiness", {}).get("candidate_count"), "paper-only mirror candidates"),
    ]


def capability(name: str, score: float | None, status: str | None, sample_size: int | None, evidence: str) -> dict:
    return {
        "name": name,
        "score": round(float(score), 2) if score is not None else None,
        "status": status or "initializing",
        "sample_size": sample_size,
        "evidence": evidence,
        "warning": "insufficient evidence" if sample_size is not None and sample_size < 30 else "",
    }


def readiness_score(status: str | None) -> float:
    return {
        "READY": 82.0,
        "STALE_BUT_USABLE": 68.0,
        "INSUFFICIENT_EVIDENCE": 45.0,
        "BUILDING": 35.0,
        "WAITING_FOR_SOURCE_DATA": 20.0,
        "DATA_QUALITY_BLOCKED": 15.0,
        "FAILED": 0.0,
    }.get(status or "", 20.0)


def copy_score_from_summary(summary: dict) -> float | None:
    value = (summary.get("summary") or {}).get("average_readiness_score")
    return float(value) if value is not None else None


def sample_from_metric(metric: TradingIntelligenceMetric | None) -> int | None:
    return metric.trades_count if metric else None


def aggregate_edges(rows: list[TradingGameTrade], attr: str) -> list[dict]:
    groups: dict[str, list[TradingGameTrade]] = defaultdict(list)
    for row in rows:
        key = getattr(row, attr, None) or "unknown"
        groups[str(key)].append(row)
    output = []
    for key, group in groups.items():
        r_values = [float(row.realized_r_multiple) for row in group if row.realized_r_multiple is not None]
        excess_values = [float(row.excess_return_vs_benchmark) for row in group if row.excess_return_vs_benchmark is not None]
        wins = sum(1 for row in group if (row.realized_r_multiple or 0) > 0 or row.outcome_label in {"win", "target_hit"})
        sample = len(group)
        avg_r = mean(r_values) if r_values else 0.0
        avg_excess = mean(excess_values) if excess_values else 0.0
        edge_score = max(0.0, min(100.0, 50.0 + avg_r * 12.0 + avg_excess * 0.8 + (wins / max(1, sample) - 0.5) * 30.0))
        output.append(
            {
                "entity": key,
                "sample_size": sample,
                "win_rate": round(wins / max(1, sample), 4),
                "average_r": round(avg_r, 4),
                "average_excess_return": round(avg_excess, 4),
                "edge_score": round(edge_score, 2),
                "evidence_grade": "weak" if sample < 20 else "medium" if sample < 80 else "strong",
            }
        )
    return output


def gate(name: str, passed: bool, observed: Any, requirement: str, required: bool = True) -> dict:
    return {
        "gate": name,
        "passed": bool(passed),
        "required": required,
        "observed": observed,
        "requirement": requirement,
        "status": "pass" if passed else "blocked",
    }


def serialize_job(row: BackgroundJobState | None) -> dict | None:
    if row is None:
        return None
    return {
        "job_name": row.job_name,
        "stage_name": row.stage_name,
        "status": row.status,
        "last_started_at": row.last_started_at.isoformat() if row.last_started_at else None,
        "last_completed_at": row.last_completed_at.isoformat() if row.last_completed_at else None,
        "duration_ms": row.duration_ms,
        "items_processed": row.items_processed,
        "error_message": row.error_message,
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
    }


def serialize_focus(row: LearningFocusPriority | None) -> dict | None:
    if row is None:
        return None
    return {
        "priority_type": row.priority_type,
        "target": row.target,
        "reason": row.reason,
        "expected_learning_value": row.expected_learning_value,
        "urgency": row.urgency,
        "status": row.status,
    }


def serialize_paper_strategy(row: PaperCopyStrategy | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "strategy_id": row.strategy_id,
        "name": row.name,
        "status": row.status,
        "strategy_type": row.strategy_type,
        "copyability_score": row.copyability_score,
        "risk_budget_percent": row.risk_budget_percent,
        "max_open_positions": row.max_open_positions,
        "paper_only": row.paper_only,
        "no_broker_execution": row.no_broker_execution,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def serialize_paper_portfolio(row: PaperCopyPortfolio | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "portfolio_id": row.portfolio_id,
        "status": row.status,
        "starting_capital": row.starting_capital,
        "current_capital": row.current_capital,
        "cash": row.cash,
        "exposure": row.exposure,
        "realized_pnl": row.realized_pnl,
        "unrealized_pnl": row.unrealized_pnl,
        "benchmark_ticker": row.benchmark_ticker,
        "risk_state": row.risk_state,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def serialize_paper_position(row: PaperCopyPosition) -> dict:
    return {
        "id": row.id,
        "ticker": row.ticker,
        "status": row.status,
        "quantity": row.quantity,
        "entry_price": row.entry_price,
        "current_price": row.current_price,
        "market_value": row.market_value,
        "unrealized_pnl": row.unrealized_pnl,
        "realized_pnl": row.realized_pnl,
        "invalidation_level": row.invalidation_level,
        "target_1": row.target_1,
        "target_2": row.target_2,
        "opened_at": row.opened_at.isoformat() if row.opened_at else None,
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
    }


def serialize_paper_snapshot(row: PaperCopyPortfolioSnapshot | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "capital": row.capital,
        "exposure": row.exposure,
        "open_positions": row.open_positions,
        "pending_orders": row.pending_orders,
        "copyability_score": row.copyability_score,
        "evidence_grade": row.evidence_grade,
        "payload": row.payload_json or {},
        "warnings": row.warnings_json or [],
    }


def strategy_candidate_from_summary(summary: dict) -> dict:
    rows = summary.get("rows") or []
    scores = [row.get("copy_readiness_score") for row in rows if row.get("copy_readiness_score") is not None]
    return {
        "name": "BLUM Paper Copy Strategy Candidate",
        "strategy_type": "conditional_copy_watchlist",
        "copyability_score": round(mean(scores), 2) if scores else 0.0,
        "candidate_count": len(rows),
        "rules": [
            "paper only",
            "copy only if trigger and invalidation exist",
            "risk budget remains educational and capped",
            "no broker execution",
        ],
    }


def dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys([str(item) for item in items if item]))
