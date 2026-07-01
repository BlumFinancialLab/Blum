from __future__ import annotations

from datetime import datetime, timedelta
import traceback
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ingestion.news_ingestor import NewsIngestor
from app.models import (
    Asset,
    AutonomousEngineRun,
    BlumKnowledgeRecord,
    ExternalDatasetSource,
    LearningEvent,
    NewsArticle,
    PriceHistory,
    SignalSnapshot,
    SniperScore,
    TradingGame,
    TradingGameTrade,
)
from app.services.accuracy import run_accuracy_audit
from app.services.blum_financial_model import run_model_learning_cycle
from app.services.data_continuity import repair_data_gaps
from app.services.etf import update_etf_trends
from app.services.fundamentals import update_fundamentals
from app.services.huggingface_datasets import dataset_catalog_status, refresh_huggingface_dataset_catalog
from app.services.ipo import update_ipo_radar
from app.services.learning_loop import LearningLoopService
from app.services.macro import update_macro_snapshots
from app.services.market_data import MarketDataService
from app.services.market_sniper import MarketSniperEngine
from app.services.persistence import backup_embedded_postgres_if_configured
from app.services.trading_game import TradingGameSimulator
from app.signals.engine import SignalEngine


settings = get_settings()


class AutonomousResearchEngine:
    """Runs Blum's server-side intelligence cycle in a strict, auditable sequence."""

    def __init__(self, progress_callback=None):
        self.progress_callback = progress_callback

    def run_cycle(self, db: Session, trigger: str = "scheduled") -> dict:
        run_id = f"auto-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
        stage_results: dict[str, dict] = {}
        started_at = datetime.utcnow()

        def stage(name: str, work) -> dict:
            stage_started = datetime.utcnow()
            self._progress(name, "running", stage_started, None, stage_results)
            try:
                result = work()
                payload = {
                    "status": "ok",
                    "started_at": stage_started.isoformat(),
                    "completed_at": datetime.utcnow().isoformat(),
                    "result": result or {},
                }
            except Exception as exc:
                payload = {
                    "status": "error",
                    "started_at": stage_started.isoformat(),
                    "completed_at": datetime.utcnow().isoformat(),
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(limit=4),
                }
            stage_results[name] = payload
            self._progress(name, payload["status"], stage_started, datetime.utcnow(), stage_results)
            return payload

        stage("hf_dataset_catalog", lambda: self.refresh_dataset_catalog_if_needed(db))
        stage("macro_context", lambda: update_macro_snapshots(db))
        stage("fundamentals", lambda: update_fundamentals(db, limit=min(settings.max_update_assets, 32)))
        stage("historical_memory_repair", lambda: repair_data_gaps(db, limit=min(settings.max_update_assets, settings.autonomous_repair_limit)))
        stage("incremental_price_refresh", lambda: MarketDataService().update_prices(db, period=settings.refresh_price_period, limit=settings.max_update_assets))
        stage("news_sentiment", lambda: NewsIngestor().update_news(db, lookback_hours=96, limit_per_feed=45))
        stage("signals", lambda: SignalEngine().run(db, limit=settings.max_update_assets))
        stage("etf_intelligence", lambda: update_etf_trends(db))
        stage("ipo_radar", lambda: update_ipo_radar(db, limit_per_form=55))
        stage("accuracy_audit", lambda: run_accuracy_audit(db, limit=settings.max_update_assets))
        if settings.enable_learning_loop:
            stage("blum_financial_model", lambda: run_model_learning_cycle(db, limit=settings.blum_model_cycle_limit))
            stage("blum_learning_loop", lambda: LearningLoopService().run_batch(db, batch_size=settings.learning_batch_size, trigger="autonomous_engine"))
        stage("market_sniper_engine", lambda: MarketSniperEngine().evaluate(db, limit=min(settings.max_update_assets, 48)))
        if settings.trading_game_enabled:
            stage("trading_game_pl_learning", lambda: TradingGameSimulator().run(db, batch_size=settings.trading_game_batch_size))
        stage("persistence_backup", lambda: backup_embedded_postgres_if_configured(reason="autonomous_engine_cycle"))

        readiness = self.readiness(db, stage_results)
        status = "ok" if readiness["warning_count"] == 0 else "degraded"
        if any(item.get("status") == "error" for item in stage_results.values()):
            status = "degraded"
        run = AutonomousEngineRun(
            run_id=run_id,
            trigger=trigger,
            status=status,
            started_at=started_at,
            completed_at=datetime.utcnow(),
            stage_results=stage_results,
            readiness_score=readiness["readiness_score"],
            data_coverage_score=readiness["data_coverage_score"],
            reasoning_memory_created=readiness["reasoning_memory_created"],
            warning_count=readiness["warning_count"],
            error_payload=readiness["errors"],
        )
        db.add(run)
        db.add(
            LearningEvent(
                event_type="autonomous_research_engine_cycle",
                severity="Info" if status == "ok" else "Warning",
                title="Autonomous Blum research cycle completed",
                description="Blum executed the full research pipeline without manual input.",
                payload={"run_id": run_id, "trigger": trigger, "status": status, "readiness": readiness, "stage_results": stage_results},
            )
        )
        db.commit()
        return {"run_id": run_id, "trigger": trigger, "status": status, "readiness": readiness, "stage_results": stage_results}

    def _progress(self, stage_name: str, status: str, started_at: datetime, completed_at: datetime | None, stage_results: dict) -> None:
        if not self.progress_callback:
            return
        self.progress_callback(
            {
                "stage": stage_name,
                "status": status,
                "stage_started_at": started_at.isoformat(),
                "stage_completed_at": completed_at.isoformat() if completed_at else None,
                "completed_stages": [name for name, result in stage_results.items() if result.get("status") in {"ok", "error"}],
                "stage_results": stage_results,
            }
        )

    def refresh_dataset_catalog_if_needed(self, db: Session) -> dict:
        if not settings.enable_hf_dataset_catalog:
            return {"status": "disabled"}
        latest = db.scalar(select(func.max(ExternalDatasetSource.updated_at)))
        if latest and latest >= datetime.utcnow() - timedelta(hours=settings.hf_dataset_refresh_hours):
            return {"status": "fresh", "catalog": dataset_catalog_status(db, limit=settings.hf_dataset_max_sources)}
        return refresh_huggingface_dataset_catalog(db, validate=True)

    def price_period(self, db: Session, trigger: str) -> str:
        active_assets = int(db.scalar(select(func.count(Asset.id)).where(Asset.is_active.is_(True))) or 0)
        priced_assets = int(db.scalar(select(func.count(func.distinct(PriceHistory.asset_id)))) or 0)
        price_rows = int(db.scalar(select(func.count(PriceHistory.id))) or 0)
        has_usable_history = active_assets > 0 and priced_assets / active_assets >= 0.65 and price_rows >= active_assets * settings.minimum_history_rows
        if trigger in {"startup", "manual"} and not has_usable_history:
            return settings.historical_price_period
        return settings.refresh_price_period

    def readiness(self, db: Session, stage_results: dict) -> dict:
        active_assets = int(db.scalar(select(func.count(Asset.id)).where(Asset.is_active.is_(True))) or 0)
        priced_assets = int(db.scalar(select(func.count(func.distinct(PriceHistory.asset_id)))) or 0)
        signal_count = int(db.scalar(select(func.count(SignalSnapshot.id))) or 0)
        news_count = int(db.scalar(select(func.count(NewsArticle.id))) or 0)
        reasoning_records = int(db.scalar(select(func.count(BlumKnowledgeRecord.id))) or 0)
        dataset_sources = int(db.scalar(select(func.count(ExternalDatasetSource.id))) or 0)
        learning_stage = stage_results.get("blum_learning_loop", {}).get("result", {})
        sniper_count = int(db.scalar(select(func.count(SniperScore.id))) or 0)
        trading_games = int(db.scalar(select(func.count(TradingGame.id))) or 0)
        trading_trades = int(db.scalar(select(func.count(TradingGameTrade.id))) or 0)
        coverage = (priced_assets / active_assets * 100) if active_assets else 0.0
        evidence_components = [
            min(100.0, coverage),
            100.0 if signal_count > 0 else 0.0,
            min(100.0, news_count / 100 * 100),
            min(100.0, reasoning_records / 100 * 100),
            min(100.0, dataset_sources / max(1, settings.hf_dataset_max_sources) * 100),
            min(100.0, sniper_count / max(1, active_assets) * 100),
            min(100.0, trading_trades / max(1, active_assets) * 100),
        ]
        errors = {name: result for name, result in stage_results.items() if result.get("status") == "error"}
        warnings = sum(1 for result in stage_results.values() if result.get("status") != "ok")
        model_stage = stage_results.get("blum_financial_model", {}).get("result", {})
        return {
            "active_assets": active_assets,
            "priced_assets": priced_assets,
            "signal_count": signal_count,
            "news_count": news_count,
            "reasoning_records": reasoning_records,
            "dataset_sources": dataset_sources,
            "sniper_scores": sniper_count,
            "trading_games": trading_games,
            "trading_game_trades": trading_trades,
            "data_coverage_score": round(coverage, 2),
            "readiness_score": round(sum(evidence_components) / len(evidence_components), 2),
            "reasoning_memory_created": int(model_stage.get("knowledge_records_created", 0) or 0),
            "learning_reports_created": int(learning_stage.get("reports_created", 0) or 0),
            "warning_count": warnings,
            "errors": errors,
            "policy": "Autonomous research improves evidence quality and calibration; it does not guarantee market outperformance or execute trades.",
        }


def latest_autonomous_status(db: Session) -> dict:
    latest = db.scalar(select(AutonomousEngineRun).order_by(AutonomousEngineRun.started_at.desc()).limit(1))
    runs = db.scalars(select(AutonomousEngineRun).order_by(AutonomousEngineRun.started_at.desc()).limit(20)).all()
    return {
        "enabled": settings.enable_autonomous_engine,
        "cycle_minutes": settings.autonomous_cycle_minutes,
        "latest_run": serialize_run(latest) if latest else None,
        "recent_runs": [serialize_run(run) for run in runs],
        "dataset_catalog": dataset_catalog_status(db, limit=settings.hf_dataset_max_sources),
        "policy": "Blum runs sequential server-side research cycles. Manual buttons are optional diagnostics, not required for normal operation.",
    }


def serialize_run(run: AutonomousEngineRun) -> dict:
    return {
        "run_id": run.run_id,
        "trigger": run.trigger,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "readiness_score": run.readiness_score,
        "data_coverage_score": run.data_coverage_score,
        "reasoning_memory_created": run.reasoning_memory_created,
        "warning_count": run.warning_count,
        "stage_results": run.stage_results,
        "error_payload": run.error_payload,
    }
