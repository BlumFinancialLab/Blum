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
from app.analyst.dataset_pipeline import BlumAnalystDatasetPipeline
from app.engine.facade import BlumEngineFacade
from app.ingestion.news_ingestor import NewsIngestor
from app.runtime.facade import BlumRuntimeFacade
from app.models import (
    AIInsight,
    AccuracySnapshot,
    AllocationEfficiencyAudit,
    AlphaLossAttribution,
    AlphaRecoveryAction,
    AlphaCaptureMetric,
    Asset,
    AutonomousEngineRun,
    BenchmarkRelativeOutcome,
    BenchmarkMethodologyValidation,
    BlumDatasetExport,
    BlumKnowledgeGraphEdge,
    BlumKnowledgeGraphNode,
    BlumKnowledgeRecord,
    BlumModelTrainingJob,
    BlumNarrativeMemory,
    BlumReasoningMemory,
    BlumRegimeMemory,
    BlumSelfCritique,
    BlumTradingPowerScore,
    BlumThesisOutcome,
    BlumThesisQualityScore,
    BlumTrainingExample,
    BusinessQualityProfile,
    BusinessQualityScore,
    CapitalAllocationSnapshot,
    CapitalInteractionRisk,
    CapitalPreservationAlpha,
    CashAllocationDecision,
    ChartAnalysis,
    ChartPatternMemory,
    ChatMessage,
    ChatSession,
    CompetingThesis,
    ConfidenceCalibrationBucket,
    ConfidenceAdjustment,
    DecisionSuperiorityScore,
    DecisionUniverseSnapshot,
    DashboardSnapshot,
    EmbeddingVector,
    EngineVote,
    EnsembleWeightVersion,
    ExternalDatasetSource,
    FundamentalAlphaPattern,
    FundamentalSnapshot,
    HistoricalPrediction,
    HistoricalSimilarityCase,
    IntelligenceReport,
    LearningEvent,
    LearningMetric,
    LearningRun,
    MarketRegimeSnapshot,
    MacroSnapshot,
    MistakeAnalysis,
    ModelWeightVersion,
    ModelVersion,
    ModelReliabilityMatrix,
    ModelReliabilityByRegime,
    NewsArticle,
    NewsAssetLink,
    PortfolioScenario,
    PredictionOutcome,
    PriceHistory,
    PriceProviderCheck,
    RMultipleMetric,
    SectorAccuracyProfile,
    SentimentAnalysis,
    SignalEvaluation,
    SignalOutcome,
    SignalPerformance,
    SignalReliabilityMatrix,
    SignalSnapshot,
    SniperScore,
    SourceReliabilityScore,
    StrategyMemory,
    TechnicalLevel,
    TechnicalSignal,
    TickerAccuracyProfile,
    TradingGame,
    TradingGameEquityCurve,
    TradingGameFailure,
    TradingGameTrade,
    TradeEngineAttribution,
    TradeLearningEvidence,
    TradeQualityScore,
    TradingGameRealityCheck,
    TradingCapitalCycle,
    TradingIntelligenceMetric,
    LiveForwardPaperGame,
    LiveForwardPaperPosition,
    HistoricalLiveComparison,
    EquityCurveAnnotation,
    LearningBenchmarkComparison,
    LearningFactorImportance,
    LearningFocusPriority,
    MetaCognitionEvent,
    MetaLearningEvent,
    LearningProgressSnapshot,
    LearningStrengthWeaknessMap,
    ManagementQualityProfile,
    MissedWinner,
    OpportunityPrecisionMetric,
    OpportunityRecallMetric,
    OpportunityCapitalScore,
    PortfolioAlphaScore,
    PortfolioContribution,
    PortfolioCorrelation,
    PortfolioQualityScore,
    PositionSizingOutcome,
    SizingLogicAllocation,
    RankingAccuracyMetric,
    SelfImprovementAction,
    ReasoningNoiseFlag,
    ThesisCompetition,
    ThesisConvictionHistory,
    ThesisLifecycleEvent,
    ThesisSurvivalMetric,
    TrainingExampleQualityScore,
    WatchlistItem,
)
from app.schemas import AssetOut, FinancialChatRequest, MarketUpdateRequest, NewsOut, NewsUpdateRequest, SemanticSearchRequest, SignalRunRequest
from app.services.accuracy import asset_accuracy_profile, latest_accuracy_snapshot, market_accuracy_overview, run_accuracy_audit, signal_validation_report
from app.services.alpha_recovery import (
    AlphaLossAttributionEngine,
    AlphaRecoveryActionEngine,
    AlphaRecoveryDashboardService,
    BenchmarkMethodologyValidator,
    MissedWinnersEngine,
)
from app.services.alpha_operating_system import (
    AlphaGateService,
    AlphaReadinessEngine,
    BrainCommandSummaryService,
    EdgeMapService,
    PaperCopyTradingService,
    TradingGameReadinessService,
    V1_FEATURE_SET,
)
from app.services.autonomous_engine import AutonomousResearchEngine, latest_autonomous_status
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
from app.services.dashboard_snapshots import DashboardSnapshotService
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
from app.services.financial_chat import asset_context as chat_asset_context
from app.services.financial_chat import chat_context_overview, chat_history, financial_chat_response
from app.services.hybrid_chart_intelligence import HybridChartIntelligence
from app.services.huggingface_datasets import dataset_catalog_status, refresh_huggingface_dataset_catalog
from app.services.ipo import ipo_radar, sec_company_submissions, update_ipo_radar
from app.services.learning_loop import LearningDashboardService, LearningLoopService
from app.services.learning_intelligence import (
    BenchmarkComparisonService,
    BlumTradingPowerScoreService,
    LearningIntelligenceDashboardService,
    LearningProgressEvaluator,
    LearningWeaknessMapService,
    SelfImprovementActionEngine,
)
from app.services.learning_summary import LearningSummaryService
from app.services.decision_intelligence import (
    BusinessQualityEngine,
    DecisionIntelligenceDashboardService,
    DecisionSuperiorityEngine,
    PortfolioIntelligenceEngine,
)
from app.services.capital_allocation import AdaptiveCapitalAllocationEngine
from app.services.central_brain_runtime import (
    CentralBrainRuntime,
    LearningHealthService,
    SnapshotProducerService,
    SnapshotWatchdogService,
)
from app.services.copy_trading_intelligence import CopyTradingIntelligenceService
from app.services.live import live_news, market_sentiment
from app.services.macro import macro_overview, update_macro_snapshots
from app.services.market_brain import build_market_brain, latest_market_brain, market_brain_history
from app.services.market_data import MarketDataService, market_snapshot_for_asset
from app.services.market_sniper import MarketSniperEngine
from app.services.meta_cognition import (
    CapitalPreservationAlphaEngine,
    LearningFocusOptimizer,
    LearningImportanceEngine,
    MetaCognitionEngine,
    ReasoningNoiseDetector,
)
from app.services.persistence import backup_embedded_postgres_if_configured, database_persistence_status
from app.services.pipeline import PipelineService
from app.services.realtime import realtime_status
from app.services.reasoning_core import (
    confidence_calibration_overview,
    meta_learning_event_list,
    model_reliability_overview,
    reasoning_core_status,
    thesis_lifecycle_records,
)
from app.services.reasoning_precision import (
    BenchmarkRelativeEvaluator,
    ConvictionDecayEngine,
    EnsembleEvolutionEngine,
    ReasoningCoreOrchestrator,
    ReliabilityByRegimeEngine,
    ThesisCompetitionEngine,
    ThesisSurvivalEngine,
    TrainingDatasetQualityService,
)
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
from app.services.trading_game import TradingGameSimulator
from app.services.trade_transparency import (
    EquityCurveAnnotationService,
    PnLBreakdownService,
    TradeAttributionService,
    TradeLedgerService,
    TradeLearningEvidenceService,
    TradeQualityEvaluator,
    TradingGameRealityCheckService,
)
from app.services.trading_intelligence_lab import (
    AdvancedTradeLedgerAnalyticsService,
    HistoricalLiveComparisonService,
    LiveForwardPaperTradingService,
    TradingCapitalCycleService,
    TradingIntelligenceMetricsService,
)
from app.services.performance import performance_recorder
from app.services.trader_brain import TraderBrainService
from app.signals.backtest import run_simple_backtest
from app.signals.engine import SignalEngine


router = APIRouter()
settings = get_settings()


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "blum-ai-financial-intelligence"}


@router.get("/performance/diagnostics")
@router.get("/api/performance/diagnostics")
def performance_diagnostics(db: Session = Depends(get_db)) -> dict:
    payload = performance_recorder.diagnostics()
    payload["dashboard_snapshots"] = latest_dashboard_snapshot_status(db)
    return payload


@router.post("/performance/frontend-widget")
@router.post("/api/performance/frontend-widget")
def performance_frontend_widget(payload: dict) -> dict:
    status = str(payload.get("status") or "")
    performance_recorder.record_frontend_widget(
        str(payload.get("name") or "unknown_frontend_widget"),
        float(payload.get("duration_ms") or 0),
        {
            "status": status,
            "source": payload.get("source", "browser"),
            "detail": payload.get("detail"),
        },
    )
    if status in {"cache", "cache_hit"}:
        performance_recorder.record_cache_event("frontend_fetch", hit=True, metadata={"source": payload.get("source", "browser")})
    elif status in {"ok", "error"} or status.startswith("http_"):
        performance_recorder.record_cache_event("frontend_fetch", hit=False, metadata={"source": payload.get("source", "browser"), "status": status})
    return {"status": "recorded"}


@router.get("/startup/status")
def startup_status() -> dict:
    return performance_recorder.startup_status()


@router.get("/brain/runtime-state")
def brain_runtime_state(db: Session = Depends(get_db)) -> dict:
    return CentralBrainRuntime().state(db)


@router.get("/engine/status")
@router.get("/api/engine/status")
def engine_status(db: Session = Depends(get_db)) -> dict:
    return BlumEngineFacade().status(db)


@router.get("/engine/contracts")
@router.get("/api/engine/contracts")
def engine_contracts() -> dict:
    return BlumEngineFacade().contract()


@router.get("/runtime/status")
@router.get("/api/runtime/status")
def runtime_status(db: Session = Depends(get_db)) -> dict:
    return BlumRuntimeFacade().status(db)


@router.get("/runtime/contracts")
@router.get("/api/runtime/contracts")
def runtime_contracts() -> dict:
    return BlumRuntimeFacade().contract()


@router.get("/analyst/status")
@router.get("/api/analyst/status")
def analyst_status(db: Session = Depends(get_db)) -> dict:
    return BlumAnalystDatasetPipeline().status(db)


@router.get("/architecture/contracts")
@router.get("/api/architecture/contracts")
def architecture_contracts() -> dict:
    return {
        "version": settings.app_version,
        "feature_set": V1_FEATURE_SET,
        "engine": BlumEngineFacade().contract(),
        "runtime": BlumRuntimeFacade().contract(),
        "analyst": BlumAnalystDatasetPipeline().contract(),
        "policy": "Engine owns truth, Analyst learns reasoning, Runtime observes and renders.",
    }


@router.get("/brain/command-summary")
def brain_command_summary(db: Session = Depends(get_db)) -> dict:
    return BrainCommandSummaryService().summary(db)


@router.get("/brain/capabilities")
def brain_capabilities(db: Session = Depends(get_db)) -> dict:
    return BrainCommandSummaryService().capabilities(db)


@router.get("/brain/evolution")
def brain_evolution(db: Session = Depends(get_db)) -> dict:
    return BrainCommandSummaryService().evolution(db)


@router.get("/trader-brain/brain")
@router.get("/api/trader-brain/brain")
def trader_brain(db: Session = Depends(get_db)) -> dict:
    return TraderBrainService().brain(db)


@router.get("/trader-brain/training-ground")
@router.get("/api/trader-brain/training-ground")
def trader_brain_training_ground(db: Session = Depends(get_db)) -> dict:
    return TraderBrainService().training_ground(db)


@router.get("/trader-brain/paper-trading")
@router.get("/api/trader-brain/paper-trading")
def trader_brain_paper_trading(
    limit: int = Query(default=20, ge=1, le=80),
    db: Session = Depends(get_db),
) -> dict:
    return TraderBrainService().paper_trading(db, limit=limit)


@router.get("/trader-brain/alpha")
@router.get("/api/trader-brain/alpha")
def trader_brain_alpha(db: Session = Depends(get_db)) -> dict:
    return TraderBrainService().alpha(db)


@router.get("/snapshots/health")
def snapshots_health(db: Session = Depends(get_db)) -> dict:
    return SnapshotWatchdogService().health(db, queue_rebuild=False)


@router.post("/snapshots/produce")
def snapshots_produce(
    snapshot_type: str | None = Query(default=None),
    max_items: int = Query(default=settings.blum_autonomous_max_items_per_job, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict:
    if snapshot_type:
        return SnapshotProducerService().produce(db, snapshot_type)
    return SnapshotProducerService().produce_many(db, max_items=max_items)


@router.get("/learning/health")
def learning_health(db: Session = Depends(get_db)) -> dict:
    snapshot_health = SnapshotWatchdogService().health(db, queue_rebuild=False)
    return LearningHealthService().health(db, snapshot_health=snapshot_health)


@router.get("/api/learning-intelligence/summary")
def learning_intelligence_summary(db: Session = Depends(get_db)) -> dict:
    return LearningSummaryService().summary(db)


@router.get("/api/dashboard-snapshots/{snapshot_type}")
def dashboard_snapshot(snapshot_type: str, db: Session = Depends(get_db)) -> dict:
    return DashboardSnapshotService().latest(db, snapshot_type=snapshot_type)


def latest_dashboard_snapshot_status(db: Session) -> dict:
    rows = db.scalars(select(DashboardSnapshot).order_by(DashboardSnapshot.snapshot_type, desc(DashboardSnapshot.created_at)).limit(120)).all()
    latest_by_type: dict[str, dict] = {}
    now = datetime.utcnow()
    for row in rows:
        if row.snapshot_type in latest_by_type:
            continue
        is_stale = bool(row.is_stale or (row.expires_at is not None and row.expires_at < now))
        latest_by_type[row.snapshot_type] = {
            "snapshot_type": row.snapshot_type,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "is_stale": is_stale,
            "age_seconds": round((now - row.created_at).total_seconds(), 3) if row.created_at else None,
            "computation_duration_ms": row.computation_duration_ms,
            "missing_sections": getattr(row, "missing_sections_json", None) or [],
            "warnings": row.warnings_json or [],
        }
    stale_count = sum(1 for item in latest_by_type.values() if item["is_stale"])
    return {
        "snapshot_count": len(latest_by_type),
        "stale_count": stale_count,
        "fresh_count": len(latest_by_type) - stale_count,
        "latest_by_type": latest_by_type,
        "policy": "Dashboards may render stale snapshots while background refresh catches up.",
    }


@router.get("/system/status")
def system_status(db: Session = Depends(get_db)) -> dict:
    latest_brain = db.scalar(select(func.max(NewsArticle.created_at))) if db is not None else None
    return {
        "service": "blum-ai-financial-intelligence",
        "app_version": settings.app_version,
        "feature_set": V1_FEATURE_SET,
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
            "startup_run_full_autonomous": settings.startup_run_full_autonomous,
            "autonomous_engine_enabled": settings.enable_autonomous_engine,
            "autonomous_max_seconds_per_job": settings.blum_autonomous_max_seconds_per_job,
            "autonomous_max_items_per_job": settings.blum_autonomous_max_items_per_job,
            "autonomous_cycle_minutes": settings.autonomous_cycle_minutes,
            "autonomous_repair_limit": settings.autonomous_repair_limit,
            "yfinance_fallback_enabled": settings.enable_yfinance_fallback,
            "historical_price_seed_enabled": settings.seed_historical_prices_on_startup,
            "startup_signal_seed_enabled": settings.seed_signals_on_startup,
            "startup_accuracy_seed_enabled": settings.seed_accuracy_on_startup,
            "data_gap_repair_minutes": settings.data_gap_repair_minutes,
            "accuracy_audit_minutes": settings.accuracy_audit_minutes,
            "learning_loop_enabled": settings.enable_learning_loop,
            "learning_loop_minutes": settings.learning_loop_minutes,
            "learning_batch_size": settings.learning_batch_size,
            "learning_max_daily_runs": settings.learning_max_daily_runs,
            "learning_min_history_years": settings.learning_min_history_years,
            "learning_asset_universe": settings.learning_asset_universe,
            "learning_evaluation_mode": settings.learning_evaluation_mode,
            "trading_game_enabled": settings.trading_game_enabled,
            "trading_min_timeframe": settings.trading_min_timeframe,
            "trading_default_timeframe": settings.trading_default_timeframe,
            "trading_allow_microscalping": settings.trading_allow_microscalping,
            "trading_game_initial_capital": settings.trading_game_initial_capital,
            "trading_game_target_capital": settings.trading_game_target_capital,
            "trading_game_reset_on_target": settings.trading_game_reset_on_target,
            "trading_game_reset_on_bankruptcy": settings.trading_game_reset_on_bankruptcy,
            "trading_game_batch_size": settings.trading_game_batch_size,
            "live_trading_game_enabled": settings.live_trading_game_enabled,
            "live_trading_game_initial_capital": settings.live_trading_game_initial_capital,
            "live_trading_game_target_capital": settings.live_trading_game_target_capital,
            "live_trading_game_max_open_positions": settings.live_trading_game_max_open_positions,
            "blum_model_cycle_minutes": settings.blum_model_cycle_minutes,
            "blum_model_cycle_limit": settings.blum_model_cycle_limit,
            "chart_vision_mode": settings.chart_vision_mode,
            "chart_vision_min_confidence": settings.chart_vision_min_confidence,
            "fundamentals_refresh_minutes": settings.fundamentals_refresh_minutes,
            "macro_refresh_minutes": settings.macro_refresh_minutes,
            "hf_dataset_catalog_enabled": settings.enable_hf_dataset_catalog,
            "hf_dataset_refresh_hours": settings.hf_dataset_refresh_hours,
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
            "reasoning_core_lifecycle_calibration": True,
            "reasoning_precision_core": True,
            "thesis_survival_engine": True,
            "conviction_decay_engine": True,
            "regime_aware_reliability": True,
            "thesis_competition_engine": True,
            "ensemble_evolution_engine": True,
            "benchmark_relative_intelligence": True,
            "portfolio_scenario": True,
            "watchlist": True,
            "multilingual_financial_chat": True,
            "autonomous_research_engine": True,
            "huggingface_dataset_catalog": True,
            "blum_learning_loop": True,
            "market_sniper_engine": True,
            "reproducible_trading_game": True,
            "trading_game_transparency": True,
            "trade_ledger": True,
            "trade_replay": True,
            "trade_attribution": True,
            "trade_quality_score": True,
            "annotated_equity_curve": True,
            "trading_game_reality_check": True,
            "trading_intelligence_lab": True,
            "capital_cycles": True,
            "intelligence_growth_metrics": True,
            "live_forward_paper_trading": True,
            "historical_vs_live_comparison": True,
            "learning_intelligence_dashboard": True,
            "blum_trading_power_score": True,
            "official_benchmark_comparison": True,
            "learning_weakness_map": True,
            "self_improvement_action_engine": True,
            "decision_superiority_engine": True,
            "business_quality_engine": True,
            "portfolio_intelligence_engine": True,
            "performance_diagnostics": True,
            "learning_performance_architecture": True,
            "dashboard_snapshots": True,
            "adaptive_capital_allocation_engine": True,
            "cash_allocation_policy": True,
            "allocation_efficiency_audit": True,
            "sizing_logic_capital_learning": True,
            "capital_interaction_risk": True,
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
            "learning_runs": int(db.scalar(select(func.count(LearningRun.id))) or 0),
            "historical_predictions": int(db.scalar(select(func.count(HistoricalPrediction.id))) or 0),
            "prediction_outcomes": int(db.scalar(select(func.count(PredictionOutcome.id))) or 0),
            "mistake_analysis": int(db.scalar(select(func.count(MistakeAnalysis.id))) or 0),
            "signal_performance": int(db.scalar(select(func.count(SignalPerformance.id))) or 0),
            "strategy_memory": int(db.scalar(select(func.count(StrategyMemory.id))) or 0),
            "model_versions": int(db.scalar(select(func.count(ModelVersion.id))) or 0),
            "learning_metrics": int(db.scalar(select(func.count(LearningMetric.id))) or 0),
            "market_regime_snapshots": int(db.scalar(select(func.count(MarketRegimeSnapshot.id))) or 0),
            "sniper_scores": int(db.scalar(select(func.count(SniperScore.id))) or 0),
            "r_multiple_metrics": int(db.scalar(select(func.count(RMultipleMetric.id))) or 0),
            "signal_reliability_matrix": int(db.scalar(select(func.count(SignalReliabilityMatrix.id))) or 0),
            "trading_games": int(db.scalar(select(func.count(TradingGame.id))) or 0),
            "trading_game_trades": int(db.scalar(select(func.count(TradingGameTrade.id))) or 0),
            "trading_game_equity_curve": int(db.scalar(select(func.count(TradingGameEquityCurve.id))) or 0),
            "trading_game_failures": int(db.scalar(select(func.count(TradingGameFailure.id))) or 0),
            "trade_engine_attributions": int(db.scalar(select(func.count(TradeEngineAttribution.id))) or 0),
            "trade_quality_scores": int(db.scalar(select(func.count(TradeQualityScore.id))) or 0),
            "trade_learning_evidence": int(db.scalar(select(func.count(TradeLearningEvidence.id))) or 0),
            "trading_game_reality_checks": int(db.scalar(select(func.count(TradingGameRealityCheck.id))) or 0),
            "equity_curve_annotations": int(db.scalar(select(func.count(EquityCurveAnnotation.id))) or 0),
            "trading_capital_cycles": int(db.scalar(select(func.count(TradingCapitalCycle.id))) or 0),
            "trading_intelligence_metrics": int(db.scalar(select(func.count(TradingIntelligenceMetric.id))) or 0),
            "live_forward_paper_games": int(db.scalar(select(func.count(LiveForwardPaperGame.id))) or 0),
            "live_forward_paper_positions": int(db.scalar(select(func.count(LiveForwardPaperPosition.id))) or 0),
            "historical_live_comparisons": int(db.scalar(select(func.count(HistoricalLiveComparison.id))) or 0),
            "blum_trading_power_scores": int(db.scalar(select(func.count(BlumTradingPowerScore.id))) or 0),
            "learning_benchmark_comparisons": int(db.scalar(select(func.count(LearningBenchmarkComparison.id))) or 0),
            "learning_progress_snapshots": int(db.scalar(select(func.count(LearningProgressSnapshot.id))) or 0),
            "learning_strength_weakness_map": int(db.scalar(select(func.count(LearningStrengthWeaknessMap.id))) or 0),
            "self_improvement_actions": int(db.scalar(select(func.count(SelfImprovementAction.id))) or 0),
            "decision_universe_snapshots": int(db.scalar(select(func.count(DecisionUniverseSnapshot.id))) or 0),
            "opportunity_recall_metrics": int(db.scalar(select(func.count(OpportunityRecallMetric.id))) or 0),
            "opportunity_precision_metrics": int(db.scalar(select(func.count(OpportunityPrecisionMetric.id))) or 0),
            "alpha_capture_metrics": int(db.scalar(select(func.count(AlphaCaptureMetric.id))) or 0),
            "ranking_accuracy_metrics": int(db.scalar(select(func.count(RankingAccuracyMetric.id))) or 0),
            "decision_superiority_scores": int(db.scalar(select(func.count(DecisionSuperiorityScore.id))) or 0),
            "business_quality_profiles": int(db.scalar(select(func.count(BusinessQualityProfile.id))) or 0),
            "management_quality_profiles": int(db.scalar(select(func.count(ManagementQualityProfile.id))) or 0),
            "fundamental_alpha_patterns": int(db.scalar(select(func.count(FundamentalAlphaPattern.id))) or 0),
            "business_quality_scores": int(db.scalar(select(func.count(BusinessQualityScore.id))) or 0),
            "portfolio_contributions": int(db.scalar(select(func.count(PortfolioContribution.id))) or 0),
            "portfolio_correlations": int(db.scalar(select(func.count(PortfolioCorrelation.id))) or 0),
            "portfolio_alpha_scores": int(db.scalar(select(func.count(PortfolioAlphaScore.id))) or 0),
            "position_sizing_outcomes": int(db.scalar(select(func.count(PositionSizingOutcome.id))) or 0),
            "portfolio_quality_scores": int(db.scalar(select(func.count(PortfolioQualityScore.id))) or 0),
            "dashboard_snapshots": int(db.scalar(select(func.count(DashboardSnapshot.id))) or 0),
            "capital_allocation_snapshots": int(db.scalar(select(func.count(CapitalAllocationSnapshot.id))) or 0),
            "opportunity_capital_scores": int(db.scalar(select(func.count(OpportunityCapitalScore.id))) or 0),
            "cash_allocation_decisions": int(db.scalar(select(func.count(CashAllocationDecision.id))) or 0),
            "allocation_efficiency_audits": int(db.scalar(select(func.count(AllocationEfficiencyAudit.id))) or 0),
            "sizing_logic_allocations": int(db.scalar(select(func.count(SizingLogicAllocation.id))) or 0),
            "capital_interaction_risks": int(db.scalar(select(func.count(CapitalInteractionRisk.id))) or 0),
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
            "thesis_lifecycle_events": int(db.scalar(select(func.count(ThesisLifecycleEvent.id))) or 0),
            "model_reliability_matrix": int(db.scalar(select(func.count(ModelReliabilityMatrix.id))) or 0),
            "confidence_calibration_buckets": int(db.scalar(select(func.count(ConfidenceCalibrationBucket.id))) or 0),
            "meta_learning_events": int(db.scalar(select(func.count(MetaLearningEvent.id))) or 0),
            "thesis_survival_metrics": int(db.scalar(select(func.count(ThesisSurvivalMetric.id))) or 0),
            "thesis_conviction_history": int(db.scalar(select(func.count(ThesisConvictionHistory.id))) or 0),
            "model_reliability_by_regime": int(db.scalar(select(func.count(ModelReliabilityByRegime.id))) or 0),
            "thesis_competitions": int(db.scalar(select(func.count(ThesisCompetition.id))) or 0),
            "competing_theses": int(db.scalar(select(func.count(CompetingThesis.id))) or 0),
            "engine_votes": int(db.scalar(select(func.count(EngineVote.id))) or 0),
            "ensemble_weight_versions": int(db.scalar(select(func.count(EnsembleWeightVersion.id))) or 0),
            "training_example_quality_scores": int(db.scalar(select(func.count(TrainingExampleQualityScore.id))) or 0),
            "benchmark_relative_outcomes": int(db.scalar(select(func.count(BenchmarkRelativeOutcome.id))) or 0),
            "blum_graph_nodes": int(db.scalar(select(func.count(BlumKnowledgeGraphNode.id))) or 0),
            "blum_graph_edges": int(db.scalar(select(func.count(BlumKnowledgeGraphEdge.id))) or 0),
            "blum_dataset_exports": int(db.scalar(select(func.count(BlumDatasetExport.id))) or 0),
            "blum_training_jobs": int(db.scalar(select(func.count(BlumModelTrainingJob.id))) or 0),
            "external_dataset_sources": int(db.scalar(select(func.count(ExternalDatasetSource.id))) or 0),
            "autonomous_engine_runs": int(db.scalar(select(func.count(AutonomousEngineRun.id))) or 0),
            "chat_sessions": int(db.scalar(select(func.count(ChatSession.id))) or 0),
            "chat_messages": int(db.scalar(select(func.count(ChatMessage.id))) or 0),
        },
        "latest_news_created_at": latest_brain,
        "why_gui_can_look_unchanged": [
            "Hugging Face serves the previous image until the Docker build finishes successfully.",
            "The finance-domain 7B model is disabled by default unless BLUM_ENABLE_FINANCIAL_BRAIN_MODEL=true.",
            "Existing snapshots are refreshed by the autonomous engine after a successful deployment.",
            "Browser cache can keep old static Next.js chunks; hard refresh if app_version is not 2.0.0.",
        ],
    }


@router.post("/system/persistence/backup")
def trigger_database_backup() -> dict:
    return backup_embedded_postgres_if_configured(reason="manual_api_trigger")


@router.get("/autonomous/status")
def autonomous_status(db: Session = Depends(get_db)) -> dict:
    return latest_autonomous_status(db)


@router.post("/autonomous/run")
def autonomous_run(db: Session = Depends(get_db)) -> dict:
    return AutonomousResearchEngine().run_cycle(db, trigger="manual_diagnostic")


@router.get("/datasets/sources")
def datasets_sources(limit: int = Query(default=80, ge=1, le=200), db: Session = Depends(get_db)) -> dict:
    return dataset_catalog_status(db, limit=limit)


@router.post("/datasets/refresh")
def datasets_refresh(db: Session = Depends(get_db)) -> dict:
    return refresh_huggingface_dataset_catalog(db, validate=True)


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


@router.get("/learning/status")
def blum_learning_status(db: Session = Depends(get_db)) -> dict:
    return LearningDashboardService().dashboard(db)


@router.get("/learning/dashboard")
def blum_learning_dashboard(db: Session = Depends(get_db)) -> dict:
    return LearningDashboardService().dashboard(db)


@router.get("/learning/runs")
def blum_learning_runs(limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)) -> list[dict]:
    return LearningDashboardService().runs(db, limit=limit)


@router.get("/learning/predictions")
def blum_learning_predictions(
    ticker: str | None = Query(default=None),
    limit: int = Query(default=80, ge=1, le=300),
    db: Session = Depends(get_db),
) -> list[dict]:
    return LearningDashboardService().predictions(db, ticker=ticker, limit=limit)


@router.get("/learning/memory")
def blum_learning_memory(limit: int = Query(default=40, ge=1, le=200), db: Session = Depends(get_db)) -> dict:
    dashboard = LearningDashboardService()
    return {
        "strategy_memory": dashboard.strategy_memory(db, limit=limit),
        "signal_performance": dashboard.signal_performance(db, limit=limit),
        "mistakes": dashboard.mistake_summary(db),
        "policy": "Memory is updated from point-in-time historical simulations and never treated as certainty.",
    }


@router.post("/learning/run-cycle")
def blum_learning_run_cycle(
    batch_size: int = Query(default=settings.learning_batch_size, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    return LearningLoopService().run_batch(db, batch_size=batch_size, trigger="manual_api_diagnostic")


@router.get("/api/sniper/status")
def sniper_status(db: Session = Depends(get_db)) -> dict:
    return MarketSniperEngine().status(db)


@router.get("/api/sniper/candidates")
def sniper_candidates(
    limit: int = Query(default=40, ge=1, le=120),
    persist: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    return MarketSniperEngine().candidates(db, limit=limit, persist=persist)


@router.get("/api/sniper/candidates/{ticker}")
def sniper_candidate(ticker: str, persist: bool = Query(default=False), db: Session = Depends(get_db)) -> dict:
    asset = require_asset(db, ticker)
    return MarketSniperEngine().evaluate_asset(db, asset, persist=persist)


@router.post("/api/sniper/evaluate")
def sniper_evaluate(
    tickers: str | None = Query(default=None),
    limit: int = Query(default=40, ge=1, le=120),
    db: Session = Depends(get_db),
) -> dict:
    parsed = [item.strip().upper() for item in tickers.split(",") if item.strip()] if tickers else None
    return MarketSniperEngine().evaluate(db, tickers=parsed, limit=limit)


@router.post("/api/sniper/simulate")
def sniper_simulate(
    ticker: str | None = Query(default=None),
    limit: int = Query(default=120, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    return MarketSniperEngine().simulate(db, ticker=ticker, limit=limit)


@router.get("/api/sniper/setups")
def sniper_setups(db: Session = Depends(get_db)) -> list[dict]:
    return MarketSniperEngine().setups(db)


@router.get("/api/sniper/regimes")
def sniper_regimes(limit: int = Query(default=80, ge=1, le=300), db: Session = Depends(get_db)) -> list[dict]:
    return MarketSniperEngine().regimes(db, limit=limit)


@router.get("/api/sniper/metrics")
def sniper_metrics(db: Session = Depends(get_db)) -> dict:
    return MarketSniperEngine().metrics(db)


@router.get("/api/sniper/lessons")
def sniper_lessons(limit: int = Query(default=40, ge=1, le=200), db: Session = Depends(get_db)) -> list[dict]:
    return MarketSniperEngine().lessons(db, limit=limit)


@router.get("/api/trading-game/status")
def trading_game_status(db: Session = Depends(get_db)) -> dict:
    return TradingGameSimulator().status(db)


@router.get("/trading-game/readiness")
@router.get("/api/trading-game/readiness")
def trading_game_readiness(db: Session = Depends(get_db)) -> dict:
    return TradingGameReadinessService().readiness(db)


@router.get("/api/copy-trading/status")
def copy_trading_status(db: Session = Depends(get_db)) -> dict:
    return CopyTradingIntelligenceService().status(db)


@router.get("/api/copy-trading/candidates")
def copy_trading_candidates(limit: int = Query(default=25, ge=1, le=100), db: Session = Depends(get_db)) -> dict:
    return CopyTradingIntelligenceService().candidates(db, limit=limit)


@router.get("/api/copy-trading/dashboard")
def copy_trading_dashboard(limit: int = Query(default=25, ge=1, le=100), db: Session = Depends(get_db)) -> dict:
    return CopyTradingIntelligenceService().dashboard(db, limit=limit)


@router.get("/alpha/readiness")
@router.get("/api/alpha/readiness")
def alpha_readiness(db: Session = Depends(get_db)) -> dict:
    return AlphaReadinessEngine().readiness(db)


@router.get("/alpha/edge-map")
@router.get("/api/alpha/edge-map")
def alpha_edge_map(limit: int = Query(default=12, ge=1, le=50), db: Session = Depends(get_db)) -> dict:
    return EdgeMapService().edge_map(db, limit=limit)


@router.get("/alpha/gates")
@router.get("/api/alpha/gates")
def alpha_gates(db: Session = Depends(get_db)) -> dict:
    return AlphaGateService().gates(db)


@router.get("/paper-copy/summary")
@router.get("/api/paper-copy/summary")
def paper_copy_summary(limit: int = Query(default=12, ge=1, le=50), db: Session = Depends(get_db)) -> dict:
    return PaperCopyTradingService().summary(db, limit=limit)


@router.get("/paper-copy/readiness")
@router.get("/api/paper-copy/readiness")
def paper_copy_readiness(db: Session = Depends(get_db)) -> dict:
    return PaperCopyTradingService().readiness(db)


@router.get("/paper-copy/strategies")
@router.get("/api/paper-copy/strategies")
def paper_copy_strategies(limit: int = Query(default=40, ge=1, le=100), db: Session = Depends(get_db)) -> dict:
    return PaperCopyTradingService().strategies(db, limit=limit)


@router.get("/paper-copy/positions")
@router.get("/api/paper-copy/positions")
def paper_copy_positions(limit: int = Query(default=80, ge=1, le=200), db: Session = Depends(get_db)) -> dict:
    return PaperCopyTradingService().positions(db, limit=limit)


@router.get("/paper-copy/portfolio/{portfolio_id}")
@router.get("/api/paper-copy/portfolio/{portfolio_id}")
def paper_copy_portfolio(portfolio_id: str, db: Session = Depends(get_db)) -> dict:
    return PaperCopyTradingService().portfolio(db, portfolio_id=portfolio_id)


@router.post("/api/trading-game/run")
def trading_game_run(
    batch_size: int = Query(default=settings.trading_game_batch_size, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    return TradingGameSimulator().run(db, batch_size=batch_size)


@router.post("/api/trading-game/reset")
def trading_game_reset(db: Session = Depends(get_db)) -> dict:
    return TradingGameSimulator().reset(db)


@router.get("/api/trading-game/equity")
def trading_game_equity(
    game_id: int | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> list[dict]:
    return TradingGameSimulator().equity(db, game_id=game_id, limit=limit)


@router.get("/api/trading-game/equity/annotated")
def trading_game_annotated_equity(
    game_id: int | None = Query(default=None),
    limit: int = Query(default=800, ge=1, le=3000),
    include_trace: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    return EquityCurveAnnotationService().annotated_equity(db, game_id=game_id, limit=limit, refresh=False, use_snapshot=True, include_trace=include_trace)


@router.get("/api/trading-game/trades")
def trading_game_trades(
    game_id: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[dict]:
    return TradingGameSimulator().trades(db, game_id=game_id, limit=limit)


@router.get("/api/trading-game/ledger")
def trading_game_ledger(
    game_id: int | None = Query(default=None),
    ticker: str | None = Query(default=None),
    setup_type: str | None = Query(default=None),
    outcome_label: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    min_r: float | None = Query(default=None),
    max_r: float | None = Query(default=None),
    only_open: bool = Query(default=False),
    only_closed: bool = Query(default=False),
    sort_by: str = Query(default="created_at_desc"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    include_trace: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    return TradeLedgerService().ledger(
        db,
        game_id=game_id,
        ticker=ticker,
        setup_type=setup_type,
        outcome_label=outcome_label,
        start_date=start_date,
        end_date=end_date,
        min_r=min_r,
        max_r=max_r,
        only_open=only_open,
        only_closed=only_closed,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
        refresh=False,
        use_snapshot=True,
        include_trace=include_trace,
    )


@router.get("/api/trading-game/ledger/summary")
def trading_game_ledger_summary(
    game_id: int | None = Query(default=None),
    ticker: str | None = Query(default=None),
    setup_type: str | None = Query(default=None),
    outcome_label: str | None = Query(default=None),
    actionability_state: str | None = Query(default=None),
    capital_cycle_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    return AdvancedTradeLedgerAnalyticsService().summary(
        db,
        game_id=game_id,
        ticker=ticker,
        setup_type=setup_type,
        outcome_label=outcome_label,
        actionability_state=actionability_state,
        capital_cycle_id=capital_cycle_id,
    )


@router.get("/api/trading-game/ledger/by-ticker/{ticker}")
def trading_game_ledger_by_ticker(
    ticker: str,
    game_id: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    return AdvancedTradeLedgerAnalyticsService().by_ticker(db, ticker=ticker, game_id=game_id, limit=limit)


@router.get("/api/trading-game/ledger/by-setup/{setup_type}")
def trading_game_ledger_by_setup(
    setup_type: str,
    game_id: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    return AdvancedTradeLedgerAnalyticsService().by_setup(db, setup_type=setup_type, game_id=game_id, limit=limit)


@router.get("/api/trading-game/ledger/by-outcome/{outcome_label}")
def trading_game_ledger_by_outcome(
    outcome_label: str,
    game_id: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    return AdvancedTradeLedgerAnalyticsService().by_outcome(db, outcome_label=outcome_label, game_id=game_id, limit=limit)


@router.get("/api/trading-game/ledger/by-cycle/{cycle_id}")
def trading_game_ledger_by_cycle(
    cycle_id: int,
    limit: int = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> dict:
    return AdvancedTradeLedgerAnalyticsService().by_cycle(db, cycle_id=cycle_id, limit=limit)


@router.get("/api/trading-game/trades/{trade_id}")
def trading_game_trade_detail(trade_id: int, db: Session = Depends(get_db)) -> dict:
    return TradeLedgerService().detail(db, trade_id)


@router.get("/api/trading-game/trades/{trade_id}/attribution")
def trading_game_trade_attribution(trade_id: int, db: Session = Depends(get_db)) -> list[dict]:
    return TradeAttributionService().for_trade(db, trade_id)


@router.get("/api/trading-game/trades/{trade_id}/quality")
def trading_game_trade_quality(trade_id: int, db: Session = Depends(get_db)) -> dict:
    return TradeQualityEvaluator().for_trade(db, trade_id)


@router.get("/api/trading-game/trades/{trade_id}/pnl-breakdown")
def trading_game_trade_pnl_breakdown(trade_id: int, db: Session = Depends(get_db)) -> dict:
    return PnLBreakdownService().trade_breakdown(db, trade_id)


@router.get("/api/trading-game/failures")
def trading_game_failures(limit: int = Query(default=80, ge=1, le=500), db: Session = Depends(get_db)) -> list[dict]:
    return TradingGameSimulator().failures(db, limit=limit)


@router.get("/api/trading-game/lessons")
def trading_game_lessons(limit: int = Query(default=50, ge=1, le=300), db: Session = Depends(get_db)) -> list[dict]:
    return TradingGameSimulator().lessons(db, limit=limit)


@router.get("/api/trading-game/benchmark")
def trading_game_benchmark(game_id: int | None = Query(default=None), db: Session = Depends(get_db)) -> dict:
    return TradingGameSimulator().benchmark(db, game_id=game_id)


@router.get("/api/trading-game/reproducibility")
def trading_game_reproducibility(limit: int = Query(default=120, ge=1, le=1000), db: Session = Depends(get_db)) -> dict:
    return TradingGameSimulator().reproducibility(db, limit=limit)


@router.get("/api/trading-game/learning-evidence")
def trading_game_learning_evidence(
    setup_type: str | None = Query(default=None),
    ticker: str | None = Query(default=None),
    regime: str | None = Query(default=None),
    lesson_type: str | None = Query(default=None),
    min_sample_size: int | None = Query(default=None, ge=0),
    affected_module: str | None = Query(default=None),
    limit: int = Query(default=120, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    return TradeLearningEvidenceService().list(
        db,
        setup_type=setup_type,
        ticker=ticker,
        regime=regime,
        lesson_type=lesson_type,
        min_sample_size=min_sample_size,
        affected_module=affected_module,
        limit=limit,
    )


@router.get("/api/trading-game/reality-check")
def trading_game_reality_check(game_id: int | None = Query(default=None), persist: bool = Query(default=False), db: Session = Depends(get_db)) -> dict:
    return TradingGameRealityCheckService().evaluate(db, game_id, persist=persist)


@router.get("/api/trading-game/pnl-breakdown")
def trading_game_pnl_breakdown(game_id: int | None = Query(default=None), db: Session = Depends(get_db)) -> dict:
    return PnLBreakdownService().game_breakdown(db, game_id=game_id)


@router.get("/api/trading-game/cycles")
def trading_game_cycles(
    game_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    return TradingCapitalCycleService().cycles(db, game_id=game_id, limit=limit)


@router.get("/api/trading-game/cycles/current")
def trading_game_current_cycle(game_id: int | None = Query(default=None), db: Session = Depends(get_db)) -> dict:
    return TradingCapitalCycleService().current(db, game_id=game_id)


@router.get("/api/trading-game/cycles/stats")
def trading_game_cycle_stats(game_id: int | None = Query(default=None), db: Session = Depends(get_db)) -> dict:
    return TradingCapitalCycleService().stats(db, game_id=game_id)


@router.get("/api/trading-game/cycles/{cycle_id}")
def trading_game_cycle_detail(cycle_id: int, db: Session = Depends(get_db)) -> dict:
    return TradingCapitalCycleService().get(db, cycle_id=cycle_id)


@router.post("/api/trading-game/cycles/reset")
def trading_game_cycle_reset(game_id: int | None = Query(default=None), db: Session = Depends(get_db)) -> dict:
    return TradingCapitalCycleService().reset(db, game_id=game_id)


@router.get("/api/trading-game/intelligence-metrics")
def trading_game_intelligence_metrics(
    game_id: int | None = Query(default=None),
    persist: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    return TradingIntelligenceMetricsService().overview(db, game_id=game_id, persist=persist)


@router.get("/api/trading-game/intelligence-metrics/rolling")
def trading_game_intelligence_metrics_rolling(game_id: int | None = Query(default=None), db: Session = Depends(get_db)) -> dict:
    return TradingIntelligenceMetricsService().rolling(db, game_id=game_id)


@router.get("/api/trading-game/intelligence-metrics/by-setup")
def trading_game_intelligence_metrics_by_setup(game_id: int | None = Query(default=None), db: Session = Depends(get_db)) -> dict:
    return TradingIntelligenceMetricsService().by_dimension(db, "setup", game_id=game_id)


@router.get("/api/trading-game/intelligence-metrics/by-regime")
def trading_game_intelligence_metrics_by_regime(game_id: int | None = Query(default=None), db: Session = Depends(get_db)) -> dict:
    return TradingIntelligenceMetricsService().by_dimension(db, "regime", game_id=game_id)


@router.get("/api/trading-game/intelligence-metrics/by-sector")
def trading_game_intelligence_metrics_by_sector(game_id: int | None = Query(default=None), db: Session = Depends(get_db)) -> dict:
    return TradingIntelligenceMetricsService().by_dimension(db, "sector", game_id=game_id)


@router.get("/api/trading-game/intelligence-metrics/by-cycle")
def trading_game_intelligence_metrics_by_cycle(game_id: int | None = Query(default=None), db: Session = Depends(get_db)) -> dict:
    return TradingIntelligenceMetricsService().by_dimension(db, "cycle", game_id=game_id)


@router.get("/api/trading-game/historical-vs-live")
def trading_game_historical_vs_live(persist: bool = Query(default=False), db: Session = Depends(get_db)) -> dict:
    return HistoricalLiveComparisonService().compare(db, persist=persist)


@router.get("/api/live-trading-game/status")
def live_trading_game_status(db: Session = Depends(get_db)) -> dict:
    return LiveForwardPaperTradingService().status(db)


@router.post("/api/live-trading-game/run-cycle")
def live_trading_game_run_cycle(db: Session = Depends(get_db)) -> dict:
    return LiveForwardPaperTradingService().run_cycle(db)


@router.get("/api/live-trading-game/positions")
def live_trading_game_positions(db: Session = Depends(get_db)) -> dict:
    return LiveForwardPaperTradingService().positions(db)


@router.get("/api/live-trading-game/trades")
def live_trading_game_trades(db: Session = Depends(get_db)) -> dict:
    return LiveForwardPaperTradingService().trades(db)


@router.get("/api/live-trading-game/ledger")
def live_trading_game_ledger(limit: int = Query(default=200, ge=1, le=1000), db: Session = Depends(get_db)) -> dict:
    return LiveForwardPaperTradingService().ledger(db, limit=limit)


@router.get("/api/live-trading-game/equity")
def live_trading_game_equity(db: Session = Depends(get_db)) -> dict:
    return LiveForwardPaperTradingService().equity(db)


@router.get("/api/live-trading-game/metrics")
def live_trading_game_metrics(db: Session = Depends(get_db)) -> dict:
    return LiveForwardPaperTradingService().metrics(db)


@router.get("/api/live-trading-game/compare-historical")
def live_trading_game_compare_historical(db: Session = Depends(get_db)) -> dict:
    return LiveForwardPaperTradingService().compare_historical(db)


@router.get("/api/learning-intelligence/dashboard")
def learning_intelligence_dashboard(db: Session = Depends(get_db)) -> dict:
    return LearningIntelligenceDashboardService().dashboard(db)


@router.get("/api/learning-intelligence/trading-power")
def learning_intelligence_trading_power(db: Session = Depends(get_db)) -> dict:
    return BlumTradingPowerScoreService().get(db)


@router.post("/api/learning-intelligence/trading-power/recalculate")
def learning_intelligence_recalculate_trading_power(db: Session = Depends(get_db)) -> dict:
    return BlumTradingPowerScoreService().recalculate(db)


@router.get("/api/learning-intelligence/benchmarks")
def learning_intelligence_benchmarks(db: Session = Depends(get_db)) -> dict:
    return BenchmarkComparisonService().comparisons(db, persist=False)


@router.get("/api/learning-intelligence/benchmarks/{benchmark_name}")
def learning_intelligence_benchmark_detail(benchmark_name: str, db: Session = Depends(get_db)) -> dict:
    return BenchmarkComparisonService().detail(db, benchmark_name=benchmark_name)


@router.post("/api/learning-intelligence/benchmarks/recalculate")
def learning_intelligence_recalculate_benchmarks(db: Session = Depends(get_db)) -> dict:
    return BenchmarkComparisonService().comparisons(db, persist=True)


@router.get("/api/learning-intelligence/progress")
def learning_intelligence_progress(db: Session = Depends(get_db)) -> dict:
    return LearningProgressEvaluator().overview(db, persist=False)


@router.get("/api/learning-intelligence/progress/rolling")
def learning_intelligence_progress_rolling(db: Session = Depends(get_db)) -> dict:
    return LearningProgressEvaluator().rolling(db)


@router.get("/api/learning-intelligence/progress/by-setup")
def learning_intelligence_progress_by_setup(db: Session = Depends(get_db)) -> dict:
    return LearningProgressEvaluator().by_dimension(db, "setup")


@router.get("/api/learning-intelligence/progress/by-regime")
def learning_intelligence_progress_by_regime(db: Session = Depends(get_db)) -> dict:
    return LearningProgressEvaluator().by_dimension(db, "regime")


@router.get("/api/learning-intelligence/weakness-map")
def learning_intelligence_weakness_map(db: Session = Depends(get_db)) -> dict:
    return LearningWeaknessMapService().map(db, persist=False)


@router.get("/api/learning-intelligence/weakness-map/by-setup")
def learning_intelligence_weakness_by_setup(db: Session = Depends(get_db)) -> dict:
    return LearningWeaknessMapService().map(db, dimension="setup", persist=False)


@router.get("/api/learning-intelligence/weakness-map/by-regime")
def learning_intelligence_weakness_by_regime(db: Session = Depends(get_db)) -> dict:
    return LearningWeaknessMapService().map(db, dimension="regime", persist=False)


@router.get("/api/learning-intelligence/weakness-map/by-sector")
def learning_intelligence_weakness_by_sector(db: Session = Depends(get_db)) -> dict:
    return LearningWeaknessMapService().map(db, dimension="sector", persist=False)


@router.get("/api/learning-intelligence/weakness-map/by-engine")
def learning_intelligence_weakness_by_engine(db: Session = Depends(get_db)) -> dict:
    return LearningWeaknessMapService().map(db, dimension="engine", persist=False)


@router.get("/api/learning-intelligence/self-improvement/actions")
def learning_intelligence_self_improvement_actions(
    limit: int = Query(default=80, ge=1, le=300),
    db: Session = Depends(get_db),
) -> dict:
    return SelfImprovementActionEngine().list(db, limit=limit)


@router.post("/api/learning-intelligence/self-improvement/generate")
def learning_intelligence_generate_self_improvement(db: Session = Depends(get_db)) -> dict:
    return SelfImprovementActionEngine().generate(db, persist=True)


@router.post("/api/learning-intelligence/self-improvement/apply/{action_id}")
def learning_intelligence_apply_self_improvement(action_id: int, db: Session = Depends(get_db)) -> dict:
    return SelfImprovementActionEngine().apply(db, action_id=action_id)


@router.post("/api/learning-intelligence/self-improvement/evaluate/{action_id}")
def learning_intelligence_evaluate_self_improvement(action_id: int, db: Session = Depends(get_db)) -> dict:
    return SelfImprovementActionEngine().evaluate(db, action_id=action_id)


@router.get("/api/alpha-recovery/dashboard")
def alpha_recovery_dashboard(db: Session = Depends(get_db)) -> dict:
    return AlphaRecoveryDashboardService().dashboard(db)


@router.post("/api/alpha-recovery/recalculate")
def alpha_recovery_recalculate(
    benchmark_name: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    return AlphaRecoveryDashboardService().recalculate(db, benchmark_name=benchmark_name)


@router.get("/api/alpha-recovery/methodology")
def alpha_recovery_methodology(limit: int = Query(default=40, ge=1, le=200), db: Session = Depends(get_db)) -> dict:
    return BenchmarkMethodologyValidator().latest(db, limit=limit)


@router.post("/api/alpha-recovery/methodology/validate")
def alpha_recovery_methodology_validate(
    benchmark_name: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    return BenchmarkMethodologyValidator().validate_latest(db, benchmark_name=benchmark_name, persist=True)


@router.get("/api/alpha-recovery/attribution")
def alpha_recovery_attribution(
    benchmark_name: str | None = Query(default=None),
    limit: int = Query(default=120, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    return AlphaLossAttributionEngine().latest(db, benchmark_name=benchmark_name, limit=limit)


@router.post("/api/alpha-recovery/attribution/calculate")
def alpha_recovery_attribution_calculate(
    benchmark_name: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    return AlphaLossAttributionEngine().calculate(db, benchmark_name=benchmark_name, persist=True)


@router.get("/api/alpha-recovery/missed-winners")
def alpha_recovery_missed_winners(limit: int = Query(default=80, ge=1, le=300), db: Session = Depends(get_db)) -> dict:
    return MissedWinnersEngine().latest(db, limit=limit)


@router.post("/api/alpha-recovery/missed-winners/detect")
def alpha_recovery_detect_missed_winners(limit: int = Query(default=80, ge=1, le=300), db: Session = Depends(get_db)) -> dict:
    return MissedWinnersEngine().detect(db, persist=True, limit=limit)


@router.get("/api/alpha-recovery/actions")
def alpha_recovery_actions(limit: int = Query(default=80, ge=1, le=300), db: Session = Depends(get_db)) -> dict:
    return AlphaRecoveryActionEngine().latest(db, limit=limit)


@router.post("/api/alpha-recovery/actions/generate")
def alpha_recovery_generate_actions(db: Session = Depends(get_db)) -> dict:
    return AlphaRecoveryActionEngine().generate(db, persist=True)


@router.get("/api/alpha-recovery/replay-priorities")
def alpha_recovery_replay_priorities(limit: int = Query(default=30, ge=1, le=100), db: Session = Depends(get_db)) -> dict:
    return AlphaRecoveryActionEngine().replay_priorities(db, limit=limit)


@router.get("/api/meta-cognition/summary")
def meta_cognition_summary(db: Session = Depends(get_db)) -> dict:
    return MetaCognitionEngine().summary(db)


@router.get("/api/meta-cognition/factor-importance")
def meta_cognition_factor_importance(limit: int = Query(default=120, ge=1, le=400), db: Session = Depends(get_db)) -> dict:
    return LearningImportanceEngine().latest(db, limit=limit)


@router.post("/api/meta-cognition/factor-importance/recalculate")
def meta_cognition_factor_importance_recalculate(db: Session = Depends(get_db)) -> dict:
    return LearningImportanceEngine().recalculate(db, persist=True)


@router.get("/api/meta-cognition/events")
def meta_cognition_events(limit: int = Query(default=120, ge=1, le=400), db: Session = Depends(get_db)) -> dict:
    return MetaCognitionEngine().events(db, limit=limit)


@router.post("/api/meta-cognition/evaluate")
def meta_cognition_evaluate(db: Session = Depends(get_db)) -> dict:
    return MetaCognitionEngine().evaluate(db, persist=True)


@router.post("/api/meta-cognition/recalculate")
def meta_cognition_recalculate(db: Session = Depends(get_db)) -> dict:
    return MetaCognitionEngine().recalculate_all(db)


@router.get("/api/meta-cognition/capital-preservation")
def meta_cognition_capital_preservation(limit: int = Query(default=120, ge=1, le=400), db: Session = Depends(get_db)) -> dict:
    return CapitalPreservationAlphaEngine().latest(db, limit=limit)


@router.post("/api/meta-cognition/capital-preservation/evaluate")
def meta_cognition_capital_preservation_evaluate(db: Session = Depends(get_db)) -> dict:
    return CapitalPreservationAlphaEngine().evaluate(db, persist=True)


@router.get("/api/meta-cognition/learning-focus")
def meta_cognition_learning_focus(limit: int = Query(default=80, ge=1, le=300), db: Session = Depends(get_db)) -> dict:
    return LearningFocusOptimizer().latest(db, limit=limit)


@router.post("/api/meta-cognition/learning-focus/generate")
def meta_cognition_learning_focus_generate(db: Session = Depends(get_db)) -> dict:
    return LearningFocusOptimizer().generate(db, persist=True)


@router.get("/api/meta-cognition/noise")
def meta_cognition_noise(limit: int = Query(default=80, ge=1, le=300), db: Session = Depends(get_db)) -> dict:
    return ReasoningNoiseDetector().latest(db, limit=limit)


@router.post("/api/meta-cognition/noise/detect")
def meta_cognition_noise_detect(db: Session = Depends(get_db)) -> dict:
    return ReasoningNoiseDetector().detect(db, persist=True)


@router.get("/api/decision-intelligence/dashboard")
def decision_intelligence_dashboard(db: Session = Depends(get_db)) -> dict:
    return DecisionIntelligenceDashboardService().dashboard(db)


@router.get("/api/decision-intelligence/superiority")
def decision_intelligence_superiority(db: Session = Depends(get_db)) -> dict:
    return DecisionSuperiorityEngine().score(db, persist=False)


@router.post("/api/decision-intelligence/superiority/recalculate")
def decision_intelligence_superiority_recalculate(db: Session = Depends(get_db)) -> dict:
    return DecisionSuperiorityEngine().score(db, persist=True)


@router.get("/api/decision-intelligence/universe-snapshots")
def decision_intelligence_universe_snapshots(db: Session = Depends(get_db)) -> dict:
    return DecisionSuperiorityEngine().universe_snapshots(db, persist=False)


@router.post("/api/decision-intelligence/universe-snapshots/recalculate")
def decision_intelligence_universe_snapshots_recalculate(db: Session = Depends(get_db)) -> dict:
    return DecisionSuperiorityEngine().universe_snapshots(db, persist=True)


@router.get("/api/decision-intelligence/missed-opportunities")
def decision_intelligence_missed_opportunities(db: Session = Depends(get_db)) -> list[dict]:
    return DecisionSuperiorityEngine().top_missed_opportunities(db)


@router.get("/api/business-quality/dashboard")
def business_quality_dashboard(db: Session = Depends(get_db)) -> dict:
    return BusinessQualityEngine().dashboard(db)


@router.get("/api/business-quality/scores")
def business_quality_scores(limit: int = Query(default=80, ge=1, le=300), db: Session = Depends(get_db)) -> dict:
    return BusinessQualityEngine().scores(db, limit=limit, persist=False)


@router.post("/api/business-quality/recalculate")
def business_quality_recalculate(limit: int = Query(default=80, ge=1, le=300), db: Session = Depends(get_db)) -> dict:
    engine = BusinessQualityEngine()
    return {
        "status": "ok",
        "scores": engine.scores(db, limit=limit, persist=True),
        "fundamental_alpha_patterns": engine.fundamental_alpha_patterns(db, persist=True),
    }


@router.get("/api/portfolio-intelligence/dashboard")
def portfolio_intelligence_dashboard(db: Session = Depends(get_db)) -> dict:
    return PortfolioIntelligenceEngine().dashboard(db)


@router.get("/api/portfolio-intelligence/quality")
def portfolio_intelligence_quality(db: Session = Depends(get_db)) -> dict:
    return PortfolioIntelligenceEngine().quality_score(db, persist=False)


@router.post("/api/portfolio-intelligence/recalculate")
def portfolio_intelligence_recalculate(db: Session = Depends(get_db)) -> dict:
    engine = PortfolioIntelligenceEngine()
    return {
        "status": "ok",
        "quality": engine.quality_score(db, persist=True),
        "contributions": engine.contributions(db, persist=True),
        "correlations": engine.correlations(db, persist=True),
        "portfolio_alpha": engine.alpha_scores(db, persist=True),
        "position_sizing": engine.position_sizing_outcomes(db, persist=True),
    }


@router.get("/api/capital-allocation/dashboard")
def capital_allocation_dashboard(db: Session = Depends(get_db)) -> dict:
    return AdaptiveCapitalAllocationEngine().dashboard(db)


@router.get("/api/capital-allocation/plan")
def capital_allocation_plan(limit: int = Query(default=12, ge=1, le=50), db: Session = Depends(get_db)) -> dict:
    return AdaptiveCapitalAllocationEngine().allocation_plan(db, persist=False, limit=limit)


@router.get("/api/capital-allocation/opportunities")
def capital_allocation_opportunities(limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)) -> dict:
    return AdaptiveCapitalAllocationEngine().opportunity_scores(db, persist=False, limit=limit)


@router.get("/api/capital-allocation/cash-policy")
def capital_allocation_cash_policy(db: Session = Depends(get_db)) -> dict:
    return AdaptiveCapitalAllocationEngine().cash_policy(db, persist=False)


@router.get("/api/capital-allocation/efficiency")
def capital_allocation_efficiency(db: Session = Depends(get_db)) -> dict:
    return AdaptiveCapitalAllocationEngine().allocation_efficiency(db, persist=False)


@router.get("/api/capital-allocation/sizing")
def capital_allocation_sizing(db: Session = Depends(get_db)) -> dict:
    return AdaptiveCapitalAllocationEngine().sizing_logic_effectiveness(db, persist=False)


@router.get("/api/capital-allocation/interactions")
def capital_allocation_interactions(db: Session = Depends(get_db)) -> dict:
    return AdaptiveCapitalAllocationEngine().interaction_risks(db, persist=False)


@router.post("/api/capital-allocation/recalculate")
def capital_allocation_recalculate(db: Session = Depends(get_db)) -> dict:
    return AdaptiveCapitalAllocationEngine().recalculate(db)


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


@router.get("/model/reasoning-core/status")
def blum_reasoning_core_status(db: Session = Depends(get_db)) -> dict:
    legacy = reasoning_core_status(db)
    precision = ReasoningCoreOrchestrator().status(db)
    return {"legacy": legacy, "precision_core": precision}


@router.post("/model/reasoning-core/run")
def blum_reasoning_core_run(limit: int = Query(default=250, ge=1, le=3000), db: Session = Depends(get_db)) -> dict:
    return ReasoningCoreOrchestrator().run(db, limit=limit)


@router.get("/model/reasoning-core/latest")
def blum_reasoning_core_latest(db: Session = Depends(get_db)) -> dict | None:
    return ReasoningCoreOrchestrator().latest(db)


@router.get("/model/reasoning-core/diagnostics")
def blum_reasoning_core_diagnostics(db: Session = Depends(get_db)) -> dict:
    return ReasoningCoreOrchestrator().diagnostics(db)


@router.get("/model/thesis-survival")
def blum_thesis_survival(
    ticker: str | None = Query(default=None),
    limit: int = Query(default=80, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    return ThesisSurvivalEngine().list(db, ticker=ticker, limit=limit)


@router.post("/model/thesis-survival/evaluate")
def blum_thesis_survival_evaluate(
    thesis_id: int | None = Query(default=None),
    limit: int = Query(default=250, ge=1, le=3000),
    db: Session = Depends(get_db),
) -> dict:
    return ThesisSurvivalEngine().evaluate(db, thesis_id=thesis_id, limit=limit)


@router.get("/model/thesis-survival/{thesis_id}")
def blum_thesis_survival_detail(thesis_id: int, db: Session = Depends(get_db)) -> dict:
    payload = ThesisSurvivalEngine().list(db, thesis_id=thesis_id, limit=1)
    if not payload["rows"]:
        raise HTTPException(status_code=404, detail=f"No thesis survival metric for thesis: {thesis_id}")
    return payload["rows"][0]


@router.get("/model/conviction-decay")
def blum_conviction_decay(
    thesis_id: int | None = Query(default=None),
    limit: int = Query(default=80, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    return ConvictionDecayEngine().list(db, thesis_id=thesis_id, limit=limit)


@router.post("/model/conviction-decay/evaluate")
def blum_conviction_decay_evaluate(
    thesis_id: int | None = Query(default=None),
    limit: int = Query(default=250, ge=1, le=3000),
    db: Session = Depends(get_db),
) -> dict:
    return ConvictionDecayEngine().evaluate(db, thesis_id=thesis_id, limit=limit)


@router.get("/model/conviction-decay/{thesis_id}")
def blum_conviction_decay_detail(thesis_id: int, db: Session = Depends(get_db)) -> dict:
    return ConvictionDecayEngine().list(db, thesis_id=thesis_id, limit=20)


@router.get("/model/reliability-by-regime")
def blum_reliability_by_regime(
    engine_name: str | None = Query(default=None),
    limit: int = Query(default=80, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    return ReliabilityByRegimeEngine().list(db, engine_name=engine_name, limit=limit)


@router.post("/model/reliability-by-regime/recalculate")
def blum_reliability_by_regime_recalculate(
    limit: int = Query(default=1000, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> dict:
    return ReliabilityByRegimeEngine().recalculate(db, limit=limit)


@router.get("/model/reliability-by-regime/{engine_name}")
def blum_reliability_by_regime_engine(
    engine_name: str,
    limit: int = Query(default=80, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    return ReliabilityByRegimeEngine().list(db, engine_name=engine_name, limit=limit)


@router.get("/model/thesis-competitions")
def blum_thesis_competitions(
    ticker: str | None = Query(default=None),
    limit: int = Query(default=60, ge=1, le=250),
    db: Session = Depends(get_db),
) -> dict:
    return ThesisCompetitionEngine().list(db, ticker=ticker, limit=limit)


@router.get("/model/thesis-competitions/{ticker}")
def blum_thesis_competitions_ticker(ticker: str, db: Session = Depends(get_db)) -> dict:
    return ThesisCompetitionEngine().list(db, ticker=ticker, limit=20)


@router.post("/model/thesis-competitions/run/{ticker}")
def blum_thesis_competitions_run(ticker: str, db: Session = Depends(get_db)) -> dict:
    return ThesisCompetitionEngine().run_for_ticker(db, ticker=ticker)


@router.post("/model/thesis-competitions/evaluate")
def blum_thesis_competitions_evaluate(
    limit: int = Query(default=120, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    return ThesisCompetitionEngine().evaluate(db, limit=limit)


@router.get("/model/ensemble/status")
def blum_ensemble_status(db: Session = Depends(get_db)) -> dict:
    return EnsembleEvolutionEngine().status(db)


@router.post("/model/ensemble/vote/{ticker}")
def blum_ensemble_vote(ticker: str, db: Session = Depends(get_db)) -> dict:
    return EnsembleEvolutionEngine().vote_ticker(db, ticker=ticker)


@router.post("/model/ensemble/recalculate")
def blum_ensemble_recalculate(
    min_sample: int = Query(default=30, ge=5, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    return EnsembleEvolutionEngine().recalculate(db, min_sample=min_sample)


@router.get("/model/ensemble/weights")
def blum_ensemble_weights(db: Session = Depends(get_db)) -> dict:
    return {"weights": EnsembleEvolutionEngine().active_weights(db)}


@router.get("/model/ensemble/disagreements")
def blum_ensemble_disagreements(
    limit: int = Query(default=80, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    return EnsembleEvolutionEngine().disagreements(db, limit=limit)


@router.post("/model/training/quality/evaluate")
def blum_training_quality_evaluate(
    limit: int = Query(default=500, ge=1, le=3000),
    db: Session = Depends(get_db),
) -> dict:
    return TrainingDatasetQualityService().evaluate(db, limit=limit)


@router.get("/model/training/quality")
def blum_training_quality(
    limit: int = Query(default=80, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    return TrainingDatasetQualityService().list(db, limit=limit)


@router.post("/model/training/export/high-quality")
def blum_training_export_high_quality(
    limit: int = Query(default=1000, ge=1, le=10000),
    min_score: float = Query(default=65.0, ge=0.0, le=100.0),
    db: Session = Depends(get_db),
) -> dict:
    return TrainingDatasetQualityService().export_high_quality(db, limit=limit, min_score=min_score)


@router.get("/model/benchmark-relative")
def blum_benchmark_relative(
    ticker: str | None = Query(default=None),
    limit: int = Query(default=80, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    return BenchmarkRelativeEvaluator().list(db, ticker=ticker, limit=limit)


@router.post("/model/benchmark-relative/evaluate")
def blum_benchmark_relative_evaluate(
    object_id: int | None = Query(default=None),
    ticker: str | None = Query(default=None),
    limit: int = Query(default=250, ge=1, le=3000),
    db: Session = Depends(get_db),
) -> dict:
    return BenchmarkRelativeEvaluator().evaluate(db, object_id=object_id, ticker=ticker, limit=limit)


@router.get("/model/benchmark-relative/{ticker}")
def blum_benchmark_relative_ticker(ticker: str, db: Session = Depends(get_db)) -> dict:
    return BenchmarkRelativeEvaluator().list(db, ticker=ticker, limit=40)


@router.get("/model/thesis-lifecycle")
def blum_thesis_lifecycle(
    ticker: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=80, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[dict]:
    return thesis_lifecycle_records(db, ticker=ticker, status=status, limit=limit)


@router.get("/model/reliability-matrix")
def blum_model_reliability_matrix(
    engine_name: str | None = Query(default=None),
    limit: int = Query(default=80, ge=1, le=500),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
) -> dict:
    return model_reliability_overview(db, engine_name=engine_name, limit=limit, order=order)


@router.get("/model/confidence-calibration")
def blum_confidence_calibration(db: Session = Depends(get_db)) -> dict:
    return confidence_calibration_overview(db)


@router.get("/model/meta-learning")
def blum_meta_learning_events(
    limit: int = Query(default=80, ge=1, le=500),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict]:
    return meta_learning_event_list(db, limit=limit, status=status)


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


@router.post("/chat/financial")
def financial_chat(payload: FinancialChatRequest, db: Session = Depends(get_db)):
    return financial_chat_response(
        db,
        message=payload.message,
        tickers=payload.tickers,
        horizon=payload.horizon,
        risk_profile=payload.risk_profile,
        include_semantic_search=payload.include_semantic_search,
        language=payload.language,
        session_id=payload.session_id,
        mode=payload.mode,
    )


@router.post("/api/chat")
def financial_chat_api(payload: FinancialChatRequest, db: Session = Depends(get_db)):
    return financial_chat(payload, db)


@router.get("/api/chat/context")
def financial_chat_context(db: Session = Depends(get_db)):
    return chat_context_overview(db)


@router.get("/api/chat/assets/{ticker}")
def financial_chat_asset_context(ticker: str, db: Session = Depends(get_db)):
    asset = require_asset(db, ticker)
    return chat_asset_context(db, asset)


@router.get("/api/chat/signals/{ticker}")
def financial_chat_signal_context(ticker: str, db: Session = Depends(get_db)):
    asset = require_asset(db, ticker)
    signal = latest_signal(db, asset.id)
    return {
        "ticker": asset.ticker,
        "latest_signal": signal_payload(signal, db) if signal else None,
        "asset_context": chat_asset_context(db, asset),
    }


@router.get("/api/chat/history")
def financial_chat_history(limit: int = Query(default=80, ge=1, le=300), db: Session = Depends(get_db)):
    return chat_history(db, limit=limit)


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
