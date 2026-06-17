from __future__ import annotations

from datetime import datetime
import json
import os

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from app.ai.orchestrator import AIOrchestrator
from app.ai.financial_brain import FinancialBrainModel
from app.core.config import get_settings
from app.core.database import get_db
from app.ingestion.news_ingestor import NewsIngestor
from app.models import (
    AIInsight,
    AccuracySnapshot,
    Asset,
    BlumDatasetExport,
    BlumKnowledgeGraphEdge,
    BlumKnowledgeGraphNode,
    BlumKnowledgeRecord,
    BlumModelTrainingJob,
    BlumNarrativeMemory,
    BlumReasoningMemory,
    BlumRegimeMemory,
    BlumSelfCritique,
    BlumThesisOutcome,
    BlumThesisQualityScore,
    BlumTrainingExample,
    ChartAnalysis,
    ChartPatternMemory,
    ConfidenceAdjustment,
    EmbeddingVector,
    FundamentalSnapshot,
    HistoricalSimilarityCase,
    IntelligenceReport,
    LearningEvent,
    MacroSnapshot,
    ModelWeightVersion,
    NewsArticle,
    NewsAssetLink,
    PortfolioScenario,
    PriceHistory,
    PriceProviderCheck,
    SectorAccuracyProfile,
    SentimentAnalysis,
    SignalEvaluation,
    SignalOutcome,
    SignalSnapshot,
    SourceReliabilityScore,
    TechnicalLevel,
    TechnicalSignal,
    TickerAccuracyProfile,
    WatchlistItem,
)
from app.schemas import AssetOut, MarketUpdateRequest, NewsOut, NewsUpdateRequest, SemanticSearchRequest, SignalRunRequest
from app.services.accuracy import asset_accuracy_profile, latest_accuracy_snapshot, market_accuracy_overview, run_accuracy_audit, signal_validation_report
from app.services.blum_financial_model import (
    build_training_dataset,
    capture_ai_insight_reasoning,
    capture_latest_asset_reasoning,
    create_training_job_plan,
    evaluate_thesis_outcomes,
    export_training_jsonl,
    get_knowledge_record,
    graph_snapshot,
    list_knowledge_records,
    model_status,
    narrative_memory,
    quality_overview,
    regime_memory,
    run_model_learning_cycle,
    self_critique_for_record,
    semantic_reasoning_search,
    training_manifest,
)
from app.services.dashboard import dashboard_overview, signal_payload
from app.services.data_continuity import data_coverage_report, repair_data_gaps
from app.services.etf import list_etf_trends, update_etf_trends
from app.services.fundamentals import fundamentals_for_asset, update_fundamentals
from app.services.chart_vision_engine import ChartVisionEngine
from app.services.financial_brain_learning import (
    brain_accuracy,
    brain_asset_memory,
    brain_confidence_history,
    brain_learning_events,
    brain_signal_evaluations,
    brain_status,
    evaluate_signals_for_learning,
    recalculate_model_weights,
    run_learning_cycle,
)
from app.services.hybrid_chart_intelligence import HybridChartIntelligence
from app.services.ipo import ipo_radar, sec_company_submissions, update_ipo_radar
from app.services.live import live_news, market_sentiment
from app.services.macro import macro_overview, update_macro_snapshots
from app.services.market_brain import build_market_brain, latest_market_brain, market_brain_history
from app.services.market_data import MarketDataService, market_snapshot_for_asset
from app.services.pipeline import PipelineService
from app.services.realtime import realtime_status
from app.services.semantic import SemanticService
from app.services.stock import stock_radar, update_stock_radar
from app.services.strategic_intelligence import (
    add_watchlist_item,
    asset_intelligence_report,
    community_sentiment,
    executive_dashboard,
    market_narrative,
    opportunity_radar,
    portfolio_scenario,
    similar_cases_backtest,
    list_watchlist,
)
from app.services.thesis_engine import build_asset_thesis
from app.signals.backtest import run_simple_backtest
from app.signals.engine import SignalEngine


router = APIRouter()
settings = get_settings()


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "blum-ai-financial-intelligence"}


@router.get("/system/status")
def system_status(db: Session = Depends(get_db)) -> dict:
    latest_brain = db.scalar(select(func.max(NewsArticle.created_at))) if db is not None else None
    return {
        "service": "blum-ai-financial-intelligence",
        "app_version": settings.app_version,
        "feature_set": "persistent-autonomous-blum-financial-model-v0.7.1",
        "environment": settings.environment,
        "generated_at": datetime.utcnow().isoformat(),
        "hugging_face": {
            "space_id": os.getenv("SPACE_ID") or os.getenv("HF_SPACE_ID"),
            "space_author": os.getenv("SPACE_AUTHOR_NAME") or os.getenv("HF_SPACE_AUTHOR_NAME"),
            "space_repo": os.getenv("SPACE_REPO_NAME") or os.getenv("HF_SPACE_REPO_NAME"),
            "commit_sha": os.getenv("SPACE_COMMIT_SHA") or os.getenv("HF_SPACE_COMMIT_SHA") or os.getenv("GIT_COMMIT_SHA"),
        },
        "runtime_flags": {
            "model_loading_enabled": settings.enable_model_loading,
            "financial_brain_model_enabled": settings.enable_financial_brain_model,
            "live_startup_enabled": settings.enable_live_startup,
            "yfinance_fallback_enabled": settings.enable_yfinance_fallback,
            "historical_price_seed_enabled": settings.seed_historical_prices_on_startup,
            "startup_signal_seed_enabled": settings.seed_signals_on_startup,
            "startup_accuracy_seed_enabled": settings.seed_accuracy_on_startup,
            "data_gap_repair_minutes": settings.data_gap_repair_minutes,
            "accuracy_audit_minutes": settings.accuracy_audit_minutes,
            "learning_loop_enabled": settings.enable_learning_loop,
            "learning_loop_minutes": settings.learning_loop_minutes,
            "blum_model_cycle_minutes": settings.blum_model_cycle_minutes,
            "blum_model_cycle_limit": settings.blum_model_cycle_limit,
            "chart_vision_mode": settings.chart_vision_mode,
            "chart_vision_min_confidence": settings.chart_vision_min_confidence,
            "fundamentals_refresh_minutes": settings.fundamentals_refresh_minutes,
            "macro_refresh_minutes": settings.macro_refresh_minutes,
        },
        "persistence": database_persistence_status(),
        "active_models": {
            "finbert": settings.finbert_model,
            "embeddings": settings.embedding_model,
            "reasoning_llm": settings.llm_model,
            "financial_brain_configured": settings.financial_brain_model,
            "financial_brain_runtime": FinancialBrainModel().status(),
            "chart_vision": ChartVisionEngine().status(),
        },
        "feature_visibility": {
            "market_brain_page": True,
            "financial_brain_panel": True,
            "ipo_radar_page": True,
            "stock_radar_page": True,
            "theme_detail": True,
            "signal_lifecycle": True,
            "sec_submissions": True,
            "accuracy_confidence_layer": True,
            "macro_fundamental_context": True,
            "strategic_intelligence_layer": True,
            "self_learning_financial_brain": True,
            "chart_vision_technical_analyst": True,
            "proprietary_blum_financial_model": True,
            "reasoning_dataset_export": True,
            "financial_knowledge_graph": True,
            "portfolio_scenario": True,
            "watchlist": True,
        },
        "database_counts": {
            "assets": int(db.scalar(select(func.count(Asset.id))) or 0),
            "news_articles": int(db.scalar(select(func.count(NewsArticle.id))) or 0),
            "signals": int(db.scalar(select(func.count(SignalSnapshot.id))) or 0),
            "embeddings": int(db.scalar(select(func.count(EmbeddingVector.id))) or 0),
            "accuracy_snapshots": int(db.scalar(select(func.count(AccuracySnapshot.id))) or 0),
            "fundamental_snapshots": int(db.scalar(select(func.count(FundamentalSnapshot.id))) or 0),
            "macro_snapshots": int(db.scalar(select(func.count(MacroSnapshot.id))) or 0),
            "price_provider_checks": int(db.scalar(select(func.count(PriceProviderCheck.id))) or 0),
            "watchlist_items": int(db.scalar(select(func.count(WatchlistItem.id))) or 0),
            "intelligence_reports": int(db.scalar(select(func.count(IntelligenceReport.id))) or 0),
            "portfolio_scenarios": int(db.scalar(select(func.count(PortfolioScenario.id))) or 0),
            "signal_evaluations": int(db.scalar(select(func.count(SignalEvaluation.id))) or 0),
            "signal_outcomes": int(db.scalar(select(func.count(SignalOutcome.id))) or 0),
            "learning_events": int(db.scalar(select(func.count(LearningEvent.id))) or 0),
            "model_weight_versions": int(db.scalar(select(func.count(ModelWeightVersion.id))) or 0),
            "historical_similarity_cases": int(db.scalar(select(func.count(HistoricalSimilarityCase.id))) or 0),
            "confidence_adjustments": int(db.scalar(select(func.count(ConfidenceAdjustment.id))) or 0),
            "source_reliability_scores": int(db.scalar(select(func.count(SourceReliabilityScore.id))) or 0),
            "ticker_accuracy_profiles": int(db.scalar(select(func.count(TickerAccuracyProfile.id))) or 0),
            "sector_accuracy_profiles": int(db.scalar(select(func.count(SectorAccuracyProfile.id))) or 0),
            "chart_analyses": int(db.scalar(select(func.count(ChartAnalysis.id))) or 0),
            "technical_levels": int(db.scalar(select(func.count(TechnicalLevel.id))) or 0),
            "technical_signals": int(db.scalar(select(func.count(TechnicalSignal.id))) or 0),
            "chart_pattern_memory": int(db.scalar(select(func.count(ChartPatternMemory.id))) or 0),
            "blum_knowledge_records": int(db.scalar(select(func.count(BlumKnowledgeRecord.id))) or 0),
            "blum_thesis_outcomes": int(db.scalar(select(func.count(BlumThesisOutcome.id))) or 0),
            "blum_reasoning_memory": int(db.scalar(select(func.count(BlumReasoningMemory.id))) or 0),
            "blum_training_examples": int(db.scalar(select(func.count(BlumTrainingExample.id))) or 0),
            "blum_quality_scores": int(db.scalar(select(func.count(BlumThesisQualityScore.id))) or 0),
            "blum_self_critiques": int(db.scalar(select(func.count(BlumSelfCritique.id))) or 0),
            "blum_narrative_memory": int(db.scalar(select(func.count(BlumNarrativeMemory.id))) or 0),
            "blum_regime_memory": int(db.scalar(select(func.count(BlumRegimeMemory.id))) or 0),
            "blum_graph_nodes": int(db.scalar(select(func.count(BlumKnowledgeGraphNode.id))) or 0),
            "blum_graph_edges": int(db.scalar(select(func.count(BlumKnowledgeGraphEdge.id))) or 0),
            "blum_dataset_exports": int(db.scalar(select(func.count(BlumDatasetExport.id))) or 0),
            "blum_training_jobs": int(db.scalar(select(func.count(BlumModelTrainingJob.id))) or 0),
        },
        "latest_news_created_at": latest_brain,
        "why_gui_can_look_unchanged": [
            "Hugging Face serves the previous image until the Docker build finishes successfully.",
            "The finance-domain 7B model is disabled by default unless BLUM_ENABLE_FINANCIAL_BRAIN_MODEL=true.",
            "Existing snapshots must be regenerated with Run brain or full pipeline after a new deployment.",
            "Browser cache can keep old static Next.js chunks; hard refresh if app_version is not 0.7.1.",
        ],
    }


def database_persistence_status() -> dict:
    backup_file = os.getenv("BLUM_EMBEDDED_POSTGRES_BACKUP_FILE")
    backup_exists = bool(backup_file and os.path.exists(backup_file))
    backup_size = os.path.getsize(backup_file) if backup_exists and backup_file else 0
    uses_external_database = bool(os.getenv("DATABASE_URL")) and not backup_file
    mode = "external_postgres" if uses_external_database else "embedded_postgres"
    return {
        "mode": mode,
        "external_database_configured": uses_external_database,
        "embedded_backup_file": backup_file,
        "embedded_backup_exists": backup_exists,
        "embedded_backup_size_bytes": backup_size,
        "embedded_backup_interval_seconds": int(os.getenv("BLUM_DB_BACKUP_SECONDS", "300")),
        "persistent_dir": os.getenv("BLUM_PERSIST_DIR", "/data/blum"),
        "strict_no_reset_mode": uses_external_database,
        "durability_note": (
            "External DATABASE_URL is the strict no-reset mode. Embedded PostgreSQL backup can recover learning state only "
            "when Hugging Face persistent storage is enabled for the /data mount."
        ),
    }


@router.get("/brain/status")
def financial_brain_status(db: Session = Depends(get_db)) -> dict:
    return brain_status(db)


@router.get("/brain/accuracy")
def financial_brain_accuracy(db: Session = Depends(get_db)) -> dict:
    return brain_accuracy(db)


@router.get("/brain/learning-events")
def financial_brain_learning_events(limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)) -> list[dict]:
    return brain_learning_events(db, limit=limit)


@router.get("/brain/signal-evaluations")
def financial_brain_signal_evaluations(
    ticker: str | None = Query(default=None),
    limit: int = Query(default=120, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[dict]:
    return brain_signal_evaluations(db, ticker=ticker, limit=limit)


@router.get("/brain/asset-memory/{ticker}")
def financial_brain_asset_memory(ticker: str, db: Session = Depends(get_db)) -> dict:
    asset = require_asset(db, ticker)
    return brain_asset_memory(db, asset)


@router.get("/brain/confidence-history/{ticker}")
def financial_brain_confidence_history(ticker: str, db: Session = Depends(get_db)) -> dict:
    asset = require_asset(db, ticker)
    return brain_confidence_history(db, asset)


@router.post("/brain/evaluate-signals")
def financial_brain_evaluate_signals(limit: int = Query(default=240, ge=1, le=1000), db: Session = Depends(get_db)) -> dict:
    return evaluate_signals_for_learning(db, limit=limit)


@router.post("/brain/recalculate-weights")
def financial_brain_recalculate_weights(db: Session = Depends(get_db)) -> dict:
    return recalculate_model_weights(db)


@router.post("/brain/run-learning-cycle")
def financial_brain_run_learning_cycle(limit: int = Query(default=240, ge=1, le=1000), db: Session = Depends(get_db)) -> dict:
    return run_learning_cycle(db, limit=limit)


@router.get("/model/status")
def blum_model_status(db: Session = Depends(get_db)) -> dict:
    return model_status(db)


@router.post("/model/capture/{ticker}")
def blum_model_capture_asset(ticker: str, db: Session = Depends(get_db)) -> dict:
    asset = require_asset(db, ticker)
    return capture_latest_asset_reasoning(db, asset, source_type="manual_model_capture")


@router.post("/model/capture-all")
def blum_model_capture_all(limit: int = Query(default=80, ge=1, le=500), db: Session = Depends(get_db)) -> dict:
    assets = db.scalars(select(Asset).where(Asset.is_active.is_(True)).order_by(Asset.ticker).limit(limit)).all()
    records = []
    for asset in assets:
        records.append(capture_latest_asset_reasoning(db, asset, source_type="manual_model_capture_all"))
    return {"status": "ok", "assets_seen": len(assets), "records": records}


@router.post("/model/evaluate-outcomes")
def blum_model_evaluate_outcomes(limit: int = Query(default=250, ge=1, le=2000), db: Session = Depends(get_db)) -> dict:
    return evaluate_thesis_outcomes(db, limit=limit)


@router.post("/model/run-learning-cycle")
def blum_model_run_learning_cycle(limit: int = Query(default=120, ge=1, le=2000), db: Session = Depends(get_db)) -> dict:
    return run_model_learning_cycle(db, limit=limit)


@router.get("/model/knowledge")
def blum_model_knowledge_records(
    ticker: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[dict]:
    return list_knowledge_records(db, ticker=ticker, limit=limit)


@router.get("/model/knowledge/{record_id}")
def blum_model_knowledge_record(record_id: int, db: Session = Depends(get_db)) -> dict:
    record = get_knowledge_record(db, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Unknown Blum knowledge record: {record_id}")
    return record


@router.get("/model/memory/search")
def blum_model_memory_search(
    q: str = Query(..., min_length=2),
    limit: int = Query(default=12, ge=1, le=50),
    db: Session = Depends(get_db),
) -> list[dict]:
    return semantic_reasoning_search(db, q, limit=limit)


@router.post("/model/dataset/build")
def blum_model_dataset_build(
    limit: int = Query(default=500, ge=1, le=5000),
    min_quality: float = Query(default=55.0, ge=0, le=100),
    db: Session = Depends(get_db),
) -> dict:
    return build_training_dataset(db, limit=limit, min_quality=min_quality)


@router.post("/model/training/export")
def blum_model_training_export(
    limit: int = Query(default=1000, ge=1, le=10000),
    min_quality: float = Query(default=60.0, ge=0, le=100),
    export_name: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    return export_training_jsonl(db, limit=limit, min_quality=min_quality, export_name=export_name)


@router.get("/model/training/manifest")
def blum_model_training_manifest() -> dict:
    return training_manifest()


@router.post("/model/training/jobs")
def blum_model_training_job_plan(
    job_name: str = Query(default="blum-analyst-lora-plan"),
    model_family: str = Query(default="qwen"),
    base_model: str = Query(default="Qwen/Qwen2.5-0.5B-Instruct"),
    method: str = Query(default="lora"),
    dataset_export_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    return create_training_job_plan(
        db,
        job_name=job_name,
        model_family=model_family,
        base_model=base_model,
        method=method,
        dataset_export_id=dataset_export_id,
    )


@router.get("/model/quality")
def blum_model_quality(limit: int = Query(default=80, ge=1, le=500), db: Session = Depends(get_db)) -> dict:
    return quality_overview(db, limit=limit)


@router.get("/model/self-critique/{record_id}")
def blum_model_self_critique(record_id: int, db: Session = Depends(get_db)) -> dict:
    critique = self_critique_for_record(db, record_id)
    if critique is None:
        raise HTTPException(status_code=404, detail=f"No self-critique for Blum knowledge record: {record_id}")
    return critique


@router.get("/model/narratives")
def blum_model_narratives(limit: int = Query(default=80, ge=1, le=500), db: Session = Depends(get_db)) -> list[dict]:
    return narrative_memory(db, limit=limit)


@router.get("/model/regimes")
def blum_model_regimes(limit: int = Query(default=80, ge=1, le=500), db: Session = Depends(get_db)) -> list[dict]:
    return regime_memory(db, limit=limit)


@router.get("/model/graph")
def blum_model_graph(limit: int = Query(default=160, ge=10, le=1000), db: Session = Depends(get_db)) -> dict:
    return graph_snapshot(db, limit=limit)


@router.post("/chart/analyze-image")
async def chart_analyze_image(
    image: UploadFile = File(...),
    ticker: str | None = Form(default=None),
    timeframe: str = Form(default="unknown"),
    ohlcv_data: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> dict:
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Uploaded chart image is empty.")
    parsed_ohlcv = parse_ohlcv_payload(ohlcv_data)
    return HybridChartIntelligence().analyze_uploaded_image(
        db,
        image_bytes=image_bytes,
        ticker=ticker.upper() if ticker else None,
        timeframe=timeframe,
        ohlcv_rows=parsed_ohlcv,
        persist=bool(ticker),
    )


@router.post("/chart/analyze-ticker")
def chart_analyze_ticker(
    ticker: str = Query(...),
    timeframe: str = Query(default="6M"),
    period: str = Query(default="1y"),
    include_visual: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    asset = require_asset(db, ticker)
    return HybridChartIntelligence().analyze_ticker(db, asset, timeframe=timeframe, period=period, include_visual=include_visual, persist=True)


@router.get("/chart/technical-report/{ticker}")
def chart_technical_report(ticker: str, timeframe: str = Query(default="6M"), db: Session = Depends(get_db)) -> dict:
    asset = require_asset(db, ticker)
    return HybridChartIntelligence().latest_report(db, asset, timeframe=timeframe)


@router.get("/chart/levels/{ticker}")
def chart_levels(ticker: str, timeframe: str = Query(default="6M"), db: Session = Depends(get_db)) -> dict:
    asset = require_asset(db, ticker)
    return HybridChartIntelligence().levels(db, asset, timeframe=timeframe)


@router.get("/chart/signals/{ticker}")
def chart_signals(ticker: str, timeframe: str = Query(default="6M"), limit: int = Query(default=30, ge=1, le=120), db: Session = Depends(get_db)) -> list[dict]:
    asset = require_asset(db, ticker)
    return HybridChartIntelligence().signals(db, asset, timeframe=timeframe, limit=limit)


@router.get("/chart/history/{ticker}")
def chart_history(ticker: str, limit: int = Query(default=30, ge=1, le=120), db: Session = Depends(get_db)) -> list[dict]:
    asset = require_asset(db, ticker)
    return HybridChartIntelligence().history(db, asset, limit=limit)


@router.get("/assets")
def list_assets(
    asset_type: str | None = Query(default=None),
    country: str | None = Query(default=None),
    sector: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = select(Asset).where(Asset.is_active.is_(True)).order_by(Asset.asset_type, Asset.sector, Asset.ticker)
    if asset_type:
        query = query.where(Asset.asset_type.ilike(asset_type))
    if country:
        query = query.where(Asset.country.ilike(country))
    if sector:
        query = query.where(Asset.sector.ilike(f"%{sector}%"))
    assets = db.scalars(query).all()
    return [asset_payload(db, asset) for asset in assets]


@router.get("/assets/{ticker}")
def get_asset(ticker: str, db: Session = Depends(get_db)):
    asset = require_asset(db, ticker)
    prices = db.scalars(select(PriceHistory).where(PriceHistory.asset_id == asset.id).order_by(PriceHistory.date.desc()).limit(420)).all()
    signal = latest_signal(db, asset.id)
    linked = related_news_for_asset(db, asset.id, limit=12)
    return {
        "asset": AssetOut.model_validate(asset),
        "market_snapshot": market_snapshot_for_asset(db, asset),
        "prices": [
            {"date": str(row.date), "open": row.open, "high": row.high, "low": row.low, "close": row.close, "volume": row.volume}
            for row in reversed(prices)
        ],
        "latest_signal": signal_payload(signal, db) if signal else None,
        "related_news": linked,
    }


@router.post("/market/update")
def market_update(payload: MarketUpdateRequest, db: Session = Depends(get_db)):
    return MarketDataService().update_prices(db, tickers=payload.tickers, period=payload.period, limit=payload.limit)


@router.get("/data/coverage")
def data_coverage(db: Session = Depends(get_db)):
    return data_coverage_report(db)


@router.post("/data/repair")
def data_repair(limit: int = Query(default=36, ge=1, le=120), db: Session = Depends(get_db)):
    return repair_data_gaps(db, limit=limit)


@router.get("/accuracy/overview")
def accuracy_overview(db: Session = Depends(get_db)):
    return market_accuracy_overview(db, persist=False)


@router.post("/accuracy/run")
def accuracy_run(limit: int = Query(default=80, ge=1, le=160), db: Session = Depends(get_db)):
    return run_accuracy_audit(db, limit=limit)


@router.get("/accuracy/{ticker}")
def accuracy_for_ticker(ticker: str, db: Session = Depends(get_db)):
    asset = require_asset(db, ticker)
    latest = latest_accuracy_snapshot(db, ticker=asset.ticker, scope="asset")
    profile = asset_accuracy_profile(db, asset, persist=False)
    profile["latest_persisted_snapshot"] = latest
    return profile


@router.get("/validation/signals")
def validation_signals(limit: int = Query(default=240, ge=20, le=1000), db: Session = Depends(get_db)):
    return signal_validation_report(db, limit=limit)


@router.get("/macro/overview")
def macro_context(db: Session = Depends(get_db)):
    return macro_overview(db)


@router.post("/macro/update")
def macro_update(db: Session = Depends(get_db)):
    return update_macro_snapshots(db)


@router.get("/fundamentals/{ticker}")
def fundamentals_for_ticker(ticker: str, db: Session = Depends(get_db)):
    asset = require_asset(db, ticker)
    return fundamentals_for_asset(db, asset)


@router.post("/fundamentals/update")
def fundamentals_update(limit: int = Query(default=24, ge=1, le=80), db: Session = Depends(get_db)):
    return update_fundamentals(db, limit=limit)


@router.get("/intelligence/executive")
def intelligence_executive(db: Session = Depends(get_db)):
    return executive_dashboard(db)


@router.get("/intelligence/opportunities")
def intelligence_opportunities(limit: int = Query(default=30, ge=5, le=100), db: Session = Depends(get_db)):
    return opportunity_radar(db, limit=limit)


@router.get("/intelligence/narrative")
def intelligence_narrative(db: Session = Depends(get_db)):
    return market_narrative(db)


@router.get("/intelligence/community")
def intelligence_community(db: Session = Depends(get_db)):
    return community_sentiment(db)


@router.get("/intelligence/watchlist")
def intelligence_watchlist(db: Session = Depends(get_db)):
    return list_watchlist(db)


@router.post("/intelligence/watchlist/{ticker}")
def intelligence_watchlist_add(ticker: str, thesis: str = Query(default=""), db: Session = Depends(get_db)):
    asset = require_asset(db, ticker)
    return add_watchlist_item(db, asset, thesis=thesis)


@router.get("/intelligence/portfolio-scenario")
def intelligence_portfolio_scenario(risk_profile: str = Query(default="balanced"), persist: bool = Query(default=False), db: Session = Depends(get_db)):
    return portfolio_scenario(db, risk_profile=risk_profile, persist=persist)


@router.get("/intelligence/reports/{ticker}")
def intelligence_asset_report(ticker: str, persist: bool = Query(default=False), db: Session = Depends(get_db)):
    asset = require_asset(db, ticker)
    return asset_intelligence_report(db, asset, persist=persist)


@router.get("/intelligence/backtest/{ticker}")
def intelligence_similar_backtest(ticker: str, db: Session = Depends(get_db)):
    asset = require_asset(db, ticker)
    return similar_cases_backtest(db, asset)


@router.post("/news/update")
def news_update(payload: NewsUpdateRequest, db: Session = Depends(get_db)):
    return NewsIngestor().update_news(db, lookback_hours=payload.lookback_hours, limit_per_feed=payload.limit_per_feed)


@router.get("/news/live")
def news_live(limit: int = Query(default=60, ge=1, le=200), db: Session = Depends(get_db)):
    return live_news(db, limit=limit)


@router.get("/sentiment/market")
def sentiment_market(hours: int = Query(default=48, ge=1, le=720), db: Session = Depends(get_db)):
    return market_sentiment(db, hours=hours)


@router.post("/signals/run")
def signals_run(payload: SignalRunRequest, db: Session = Depends(get_db)):
    if payload.refresh_prices:
        MarketDataService().update_prices(db, tickers=payload.tickers, period=settings.historical_price_period, limit=payload.limit)
    result = SignalEngine().run(db, tickers=payload.tickers, limit=payload.limit)
    result.update(update_etf_trends(db))
    if settings.enable_learning_loop:
        result["financial_brain_learning"] = run_learning_cycle(db, limit=max(payload.limit, settings.max_update_assets) * 3)
    return result


@router.post("/pipeline/run")
def pipeline_run(payload: SignalRunRequest, db: Session = Depends(get_db)):
    result = PipelineService().run(db, tickers=payload.tickers, limit=payload.limit, period=settings.historical_price_period)
    if settings.enable_learning_loop:
        result["financial_brain_learning"] = run_learning_cycle(db, limit=max(payload.limit, settings.max_update_assets) * 3)
    return result


@router.get("/pipeline/status")
def pipeline_status():
    return realtime_status()


@router.get("/signals/top")
def signals_top(
    classification: str | None = Query(default=None),
    asset_type: str | None = Query(default=None),
    risk_level: str | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = select(SignalSnapshot, Asset).join(Asset, Asset.id == SignalSnapshot.asset_id).order_by(desc(SignalSnapshot.created_at), desc(SignalSnapshot.blum_score))
    if classification:
        query = query.where(SignalSnapshot.classification == classification)
    if asset_type:
        query = query.where(Asset.asset_type == asset_type)
    if risk_level:
        query = query.where(SignalSnapshot.risk_level == risk_level)
    rows = db.execute(query.limit(limit * 3)).all()
    seen = set()
    output = []
    for signal, asset in rows:
        if signal.ticker in seen:
            continue
        seen.add(signal.ticker)
        item = signal_payload(signal, db)
        item["asset"] = AssetOut.model_validate(asset)
        item["market_snapshot"] = market_snapshot_for_asset(db, asset)
        output.append(item)
        if len(output) >= limit:
            break
    return output


@router.get("/signals/{ticker}")
def signal_detail(ticker: str, db: Session = Depends(get_db)):
    asset = require_asset(db, ticker)
    signal = latest_signal(db, asset.id)
    if not signal:
        raise HTTPException(status_code=404, detail="No signal available. Run /signals/run first.")
    return signal_payload(signal, db)


@router.get("/sentiment/{ticker}")
def sentiment_for_ticker(ticker: str, db: Session = Depends(get_db)):
    asset = require_asset(db, ticker)
    linked_ids = [row[0] for row in db.execute(select(NewsAssetLink.article_id).where(NewsAssetLink.asset_id == asset.id)).all()]
    rows = []
    if linked_ids:
        rows = db.execute(
            select(SentimentAnalysis, NewsArticle)
            .join(NewsArticle, NewsArticle.id == SentimentAnalysis.article_id)
            .where(SentimentAnalysis.article_id.in_(linked_ids))
            .order_by(desc(SentimentAnalysis.created_at))
            .limit(80)
        ).all()
    return [
        {
            "title": article.title,
            "source": article.source,
            "published_at": article.published_at,
            "model_name": sentiment.model_name,
            "label": sentiment.label,
            "score": sentiment.score,
            "confidence": sentiment.confidence,
            "baseline_vader": sentiment.baseline_vader,
        }
        for sentiment, article in rows
    ]


@router.post("/semantic-search")
def semantic_search(payload: SemanticSearchRequest, db: Session = Depends(get_db)):
    return SemanticService().search(db, query=payload.query, limit=payload.limit)


@router.get("/related-news")
def related_news(ticker: str, limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db)):
    asset = require_asset(db, ticker)
    return related_news_for_asset(db, asset.id, limit=limit)


@router.get("/themes")
def themes(db: Session = Depends(get_db)):
    return SemanticService().themes(db)


@router.get("/themes/{label}")
def theme_detail(label: str, limit: int = Query(default=60, ge=1, le=160), db: Session = Depends(get_db)):
    return SemanticService().theme_detail(db, label=label, limit=limit)


@router.get("/etf-trends")
def etf_trends(db: Session = Depends(get_db)):
    return list_etf_trends(db)


@router.get("/stock-radar")
def stock_radar_endpoint(limit: int = Query(default=80, ge=1, le=120), db: Session = Depends(get_db)):
    return stock_radar(db, limit=limit)


@router.post("/stock-radar/update")
def stock_radar_update(limit: int = Query(default=36, ge=1, le=80), db: Session = Depends(get_db)):
    return update_stock_radar(db, limit=limit)


@router.get("/ipo-radar")
def ipo_radar_endpoint(limit: int = Query(default=80, ge=1, le=160), db: Session = Depends(get_db)):
    return ipo_radar(db, limit=limit)


@router.post("/ipo-radar/update")
def ipo_radar_update(limit_per_form: int = Query(default=50, ge=10, le=120), db: Session = Depends(get_db)):
    return update_ipo_radar(db, limit_per_form=limit_per_form)


@router.get("/ipo-radar/sec-submissions/{cik}")
def ipo_sec_submissions(cik: str, persist: bool = Query(default=False), db: Session = Depends(get_db)):
    return sec_company_submissions(db, cik=cik, persist=persist)


@router.get("/market-brain")
def market_brain_endpoint(db: Session = Depends(get_db)):
    return build_market_brain(db, persist=False)


@router.get("/market-brain/latest")
def market_brain_latest_endpoint(db: Session = Depends(get_db)):
    return latest_market_brain(db)


@router.get("/market-brain/history")
def market_brain_history_endpoint(limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db)):
    return market_brain_history(db, limit=limit)


@router.post("/market-brain/run")
def market_brain_run(
    refresh_pipeline: bool = Query(default=False),
    refresh_sec: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    updates = {}
    if refresh_pipeline:
        updates["pipeline"] = PipelineService().run(db, limit=settings.startup_pipeline_limit, period=settings.historical_price_period)
    elif refresh_sec:
        updates["ipo_update"] = update_ipo_radar(db, limit_per_form=50)
    brain = build_market_brain(db, persist=True)
    brain["update_diagnostics"] = updates
    return brain


@router.get("/ai/models/status")
def ai_model_status(db: Session = Depends(get_db)):
    sentiment_models = db.execute(
        select(SentimentAnalysis.model_name, func.count(SentimentAnalysis.id))
        .group_by(SentimentAnalysis.model_name)
        .order_by(func.count(SentimentAnalysis.id).desc())
    ).all()
    insight_models = db.execute(
        select(AIInsight.model_name, func.count(AIInsight.id))
        .group_by(AIInsight.model_name)
        .order_by(func.count(AIInsight.id).desc())
    ).all()
    embedding_models = db.execute(
        select(EmbeddingVector.model_name, func.count(EmbeddingVector.id))
        .group_by(EmbeddingVector.model_name)
        .order_by(func.count(EmbeddingVector.id).desc())
    ).all()
    return {
        "model_loading_enabled": settings.enable_model_loading,
        "configured_models": {
            "financial_sentiment": settings.finbert_model,
            "embeddings": settings.embedding_model,
            "reasoning_llm": settings.llm_model,
            "financial_brain": settings.financial_brain_model,
            "chart_vision_primary": settings.chart_vision_model,
            "chart_vision_fallback": settings.chart_vision_fallback_model,
            "time_series": "statistical-fallback with adapter-ready interface",
        },
        "financial_brain": FinancialBrainModel().status(),
        "chart_vision": ChartVisionEngine().status(),
        "observed_models": {
            "sentiment": [{"model_name": model, "records": int(count)} for model, count in sentiment_models],
            "embeddings": [{"model_name": model, "records": int(count)} for model, count in embedding_models],
            "insights": [{"model_name": model, "records": int(count)} for model, count in insight_models],
        },
        "fallback_policy": {
            "sentiment": "FinBERT primary when loadable; VADER baseline/fallback is labeled in stored records.",
            "embeddings": "sentence-transformers primary when loadable; deterministic embedding fallback is explicit in code path.",
            "reasoning": "Configured LLM when loadable; deterministic evidence reasoner fallback never invents data.",
            "time_series": "Transparent statistical fallback until Chronos, TimesFM or PatchTST adapter is enabled.",
            "chart_vision": "Qwen3-VL primary when remote/local vision is configured; InternVL3 fallback; deterministic OHLCV analysis remains active if VLM is unavailable.",
        },
    }


@router.get("/dashboard/overview")
def overview(db: Session = Depends(get_db)):
    return dashboard_overview(db)


@router.get("/ai/explain/{ticker}")
def ai_explain(ticker: str, db: Session = Depends(get_db)):
    asset = require_asset(db, ticker)
    signal = latest_signal(db, asset.id)
    hydration = {}
    if not signal:
        hydration = hydrate_asset_evidence(db, asset)
        signal = latest_signal(db, asset.id)
    news = related_news_for_asset(db, asset.id, limit=8)
    if not signal:
        insight = insufficient_evidence_insight(db, asset, news, hydration)
        insight_model = AIInsight(
            asset_id=asset.id,
            model_name=insight["models_used"]["reasoning"],
            insight_type="asset_explanation_incomplete",
            structured_output=insight,
            explanation=insight["reason"],
        )
        db.add(insight_model)
        db.flush()
        capture_ai_insight_reasoning(db, asset, insight_model, signal=None)
        db.commit()
        return insight
    historical = similar_cases_backtest(db, asset)
    accuracy = asset_accuracy_profile(db, asset, persist=False)
    market_context = {"regime": "Sideways"}
    try:
        latest_brain = latest_market_brain(db)
        market_context = {
            "regime": latest_brain.get("regime", "Sideways"),
            "brain_score": latest_brain.get("brain_score"),
            "summary": latest_brain.get("summary"),
        }
    except Exception as exc:
        market_context = {"regime": "Sideways", "context_warning": f"Market Brain context unavailable: {exc}"}
    insight = AIOrchestrator().generate_asset_insight(
        ticker=asset.ticker,
        signal=signal_payload(signal, db),
        technical=signal.technical_summary,
        narrative=signal.narrative_summary,
        related_news=news,
        market_context=market_context,
        historical_similarity=historical,
        accuracy=accuracy,
    )
    insight["evidence_status"] = "ready"
    insight["auto_hydration"] = hydration
    insight_model = AIInsight(asset_id=asset.id, model_name=insight["models_used"]["reasoning"], structured_output=insight, explanation=insight["reason"])
    db.add(insight_model)
    db.flush()
    capture_ai_insight_reasoning(db, asset, insight_model, signal=signal)
    db.commit()
    return insight


@router.post("/backtest/{ticker}")
def backtest(ticker: str, db: Session = Depends(get_db)):
    asset = require_asset(db, ticker)
    return run_simple_backtest(db, asset.id, asset.ticker)


def parse_ohlcv_payload(raw: str | None) -> list[dict] | None:
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid ohlcv_data JSON: {exc.msg}") from exc
    rows = payload.get("rows") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="ohlcv_data must be a JSON array or an object with a rows array.")
    normalized = []
    for row in rows:
        if not isinstance(row, dict) or "close" not in row:
            continue
        normalized.append(
            {
                "date": row.get("date"),
                "open": row.get("open", row.get("close")),
                "high": row.get("high", row.get("close")),
                "low": row.get("low", row.get("close")),
                "close": row.get("close"),
                "volume": row.get("volume", 0),
            }
        )
    return normalized


def require_asset(db: Session, ticker: str) -> Asset:
    asset = db.scalar(select(Asset).where(Asset.ticker == ticker.upper()))
    if not asset:
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {ticker}")
    return asset


def asset_payload(db: Session, asset: Asset) -> dict:
    payload = AssetOut.model_validate(asset).model_dump()
    payload["market_snapshot"] = market_snapshot_for_asset(db, asset)
    return payload


def latest_signal(db: Session, asset_id: int) -> SignalSnapshot | None:
    return db.scalar(select(SignalSnapshot).where(SignalSnapshot.asset_id == asset_id).order_by(desc(SignalSnapshot.created_at)).limit(1))


def hydrate_asset_evidence(db: Session, asset: Asset) -> dict:
    tickers = [asset.ticker]
    benchmark = settings.default_benchmark.upper()
    if benchmark != asset.ticker:
        tickers.append(benchmark)
    market = MarketDataService().update_prices(db, tickers=tickers, period=settings.historical_price_period, limit=len(tickers))
    news = NewsIngestor().update_news(db, lookback_hours=168, limit_per_feed=20, tickers=[asset.ticker])
    signals = SignalEngine().run(db, tickers=[asset.ticker], limit=1)
    etf = update_etf_trends(db)
    return {
        "mode": "on_demand_real_data_hydration",
        "market_update": market,
        "news_update": news,
        "signal_run": signals,
        "etf_update": etf,
    }


def insufficient_evidence_insight(db: Session, asset: Asset, news: list[dict], hydration: dict) -> dict:
    price_rows = int(db.scalar(select(func.count(PriceHistory.id)).where(PriceHistory.asset_id == asset.id)) or 0)
    market = hydration.get("market_update", {})
    news_update = hydration.get("news_update", {})
    missing_assets = market.get("missing_assets", [])
    provider_report = market.get("provider_report", [])
    reason = (
        f"{asset.ticker} does not have enough verified public market data to create a full Blum Intelligence Score yet. "
        f"The backend attempted on-demand real-data hydration, stored {price_rows} OHLCV rows and found {len(news)} linked news items. "
        "No synthetic prices, headlines, sentiment or signal evidence were generated."
    )
    if missing_assets:
        reason += f" Public price providers did not return usable data for: {', '.join(missing_assets[:6])}."
    thesis = build_asset_thesis(
        asset=asset,
        signal={
            "classification": "Insufficient Evidence",
            "blum_score": 0,
            "confidence_score": 0,
            "risk_level": "Not Rated",
            "time_horizon": "Not Rated",
            "score_breakdown": {},
        },
        technical={"price_rows": price_rows},
        narrative={"news_count_7d": len(news), "news_count_30d": len(news), "sentiment_7d": 0},
        related_news=news,
        market_context={"regime": "Sideways"},
        historical_similarity={"data_mode": "missing", "case_count": 0},
        accuracy={"blum_confidence_score": 0},
    )
    return {
        "ticker": asset.ticker,
        "classification": "Insufficient Evidence",
        "blum_score": 0,
        "reason": reason,
        "thesis": thesis,
        "executive_thesis": thesis["executive_thesis"],
        "conviction_score": thesis["conviction_score"],
        "supporting_evidence": thesis["supporting_evidence"],
        "contradicting_evidence": thesis["contradicting_evidence"],
        "what_the_market_may_be_missing": thesis["what_the_market_may_be_missing"],
        "final_blum_view": thesis["final_blum_view"],
        "watch_points": [
            "Keep the live worker running until public OHLCV providers return sufficient historical rows.",
            "Review source diagnostics to identify blocked, empty or rate-limited public feeds.",
            "Use the live news tape as narrative evidence while the quantitative signal waits for price history.",
        ],
        "risk_level": "Not Rated",
        "time_horizon": "Not Rated",
        "monitor_next": ["public OHLCV availability", "linked news count", "source diagnostics", "signal snapshot creation"],
        "evidence_status": "insufficient_real_data",
        "data_diagnostics": {
            "price_rows": price_rows,
            "linked_news": len(news),
            "market_update": {
                "data_mode": market.get("data_mode"),
                "updated_assets": market.get("updated_assets", 0),
                "price_rows": market.get("price_rows", 0),
                "missing_assets": missing_assets,
                "provider_report": provider_report,
            },
            "news_update": {
                "mode": news_update.get("mode"),
                "sources_requested": news_update.get("sources_requested", 0),
                "sources_ok": news_update.get("sources_ok", 0),
                "inserted_articles": news_update.get("inserted_articles", 0),
                "linked_assets": news_update.get("linked_assets", 0),
                "source_errors": news_update.get("source_errors", [])[:8],
            },
        },
        "models_used": {
            "sentiment": settings.finbert_model,
            "embeddings": settings.embedding_model,
            "reasoning": "evidence-readiness-engine",
            "time_series": "statistical-regime-engine",
        },
    }


def related_news_for_asset(db: Session, asset_id: int, limit: int = 20) -> list[dict]:
    rows = db.execute(
        select(NewsArticle, NewsAssetLink)
        .join(NewsAssetLink, NewsAssetLink.article_id == NewsArticle.id)
        .where(NewsAssetLink.asset_id == asset_id)
        .order_by(desc(NewsArticle.published_at), desc(NewsArticle.created_at))
        .limit(limit)
    ).all()
    return [
        {
            "id": article.id,
            "title": article.title,
            "summary": article.summary,
            "source": article.source,
            "published_at": article.published_at,
            "url": article.url,
            "quality_score": article.quality_score,
            "theme_tags": article.theme_tags,
            "relevance_score": link.relevance_score,
        }
        for article, link in rows
    ]
