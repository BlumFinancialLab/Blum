from __future__ import annotations

from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.analyst.dataset_pipeline import BlumAnalystDatasetPipeline
from app.engine.agents.contracts import AgentEvidence
from app.engine.brain.trader_brain import TraderBrainService
from app.models import (
    AlphaGateSnapshot,
    AlphaRecoveryAction,
    Asset,
    BusinessQualityScore,
    CapitalAllocationSnapshot,
    DashboardSnapshot,
    FundamentalAlphaPattern,
    FundamentalSnapshot,
    HistoricalSimilarityCase,
    LearningBenchmarkComparison,
    LearningFocusPriority,
    LearningRun,
    MetaCognitionEvent,
    NewsArticle,
    PortfolioAlphaScore,
    PortfolioQualityScore,
    PriceHistory,
    ReasoningNoiseFlag,
    SentimentAnalysis,
    SignalSnapshot,
    TechnicalIndicator,
    ThemeCluster,
    TradeLearningEvidence,
)
from app.services.learning_summary import LearningSummaryService


class BaseEvidenceAgent:
    name: str
    display_name: str
    responsibility: str
    evidence_type: str

    def evidence(
        self,
        *,
        status: str,
        payload: dict[str, Any],
        confidence: float | None = None,
        sample_size: int | None = None,
        warnings: list[str] | None = None,
    ) -> AgentEvidence:
        return AgentEvidence(
            agent=self.name,  # type: ignore[arg-type]
            responsibility=self.responsibility,
            evidence_type=self.evidence_type,
            status=status,
            payload=payload,
            confidence=confidence,
            sample_size=sample_size,
            warnings=warnings or [],
        )


class MarketAgent(BaseEvidenceAgent):
    name = "market_agent"
    display_name = "Market Agent"
    responsibility = "Own market coverage evidence: asset universe, price history and macro snapshot coverage."
    evidence_type = "market_coverage"

    def collect(self, db: Session, *, limit: int = 8) -> AgentEvidence:
        asset_count = db.scalar(select(func.count()).select_from(Asset)) or 0
        active_assets = db.scalar(select(func.count()).select_from(Asset).where(Asset.is_active.is_(True))) or 0
        price_rows = db.scalar(select(func.count()).select_from(PriceHistory)) or 0
        latest_price_date = db.scalar(select(func.max(PriceHistory.date)))
        latest_assets = db.scalars(select(Asset).order_by(desc(Asset.updated_at)).limit(limit)).all()
        return self.evidence(
            status="ready" if price_rows else "insufficient_evidence",
            sample_size=int(price_rows),
            payload={
                "asset_count": int(asset_count),
                "active_assets": int(active_assets),
                "price_rows": int(price_rows),
                "latest_price_date": latest_price_date.isoformat() if latest_price_date else None,
                "latest_assets": [
                    {"ticker": row.ticker, "name": row.name, "asset_type": row.asset_type, "sector": row.sector}
                    for row in latest_assets
                ],
            },
        )


class NewsAgent(BaseEvidenceAgent):
    name = "news_agent"
    display_name = "News Agent"
    responsibility = "Own news, sentiment and narrative coverage evidence."
    evidence_type = "news_sentiment_coverage"

    def collect(self, db: Session, *, limit: int = 8) -> AgentEvidence:
        news_count = db.scalar(select(func.count()).select_from(NewsArticle)) or 0
        sentiment_count = db.scalar(select(func.count()).select_from(SentimentAnalysis)) or 0
        theme_count = db.scalar(select(func.count()).select_from(ThemeCluster)) or 0
        latest_news = db.scalars(select(NewsArticle).order_by(desc(NewsArticle.published_at)).limit(limit)).all()
        return self.evidence(
            status="ready" if news_count else "insufficient_evidence",
            sample_size=int(news_count),
            payload={
                "news_count": int(news_count),
                "sentiment_rows": int(sentiment_count),
                "theme_clusters": int(theme_count),
                "latest_news": [
                    {
                        "title": row.title,
                        "source": row.source,
                        "published_at": row.published_at.isoformat() if row.published_at else None,
                        "quality_score": row.quality_score,
                    }
                    for row in latest_news
                ],
            },
        )


class TechnicalAgent(BaseEvidenceAgent):
    name = "technical_agent"
    display_name = "Technical Agent"
    responsibility = "Own technical indicator and signal snapshot evidence."
    evidence_type = "technical_signal_coverage"

    def collect(self, db: Session, *, limit: int = 8) -> AgentEvidence:
        indicator_count = db.scalar(select(func.count()).select_from(TechnicalIndicator)) or 0
        signal_count = db.scalar(select(func.count()).select_from(SignalSnapshot)) or 0
        latest_signals = db.scalars(select(SignalSnapshot).order_by(desc(SignalSnapshot.created_at)).limit(limit)).all()
        return self.evidence(
            status="ready" if signal_count else "insufficient_evidence",
            sample_size=int(signal_count),
            payload={
                "technical_indicator_rows": int(indicator_count),
                "signal_snapshots": int(signal_count),
                "latest_signals": [
                    {
                        "ticker": row.ticker,
                        "classification": row.classification,
                        "blum_score": row.blum_score,
                        "confidence_score": row.confidence_score,
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                    }
                    for row in latest_signals
                ],
            },
        )


class FundamentalAgent(BaseEvidenceAgent):
    name = "fundamental_agent"
    display_name = "Fundamental Agent"
    responsibility = "Own fundamental, business quality and fundamental-alpha evidence."
    evidence_type = "fundamental_quality_coverage"

    def collect(self, db: Session, *, limit: int = 8) -> AgentEvidence:
        fundamentals = db.scalar(select(func.count()).select_from(FundamentalSnapshot)) or 0
        quality_scores = db.scalar(select(func.count()).select_from(BusinessQualityScore)) or 0
        patterns = db.scalar(select(func.count()).select_from(FundamentalAlphaPattern)) or 0
        top_quality = db.scalars(
            select(BusinessQualityScore).order_by(desc(BusinessQualityScore.business_quality_score)).limit(limit)
        ).all()
        return self.evidence(
            status="ready" if fundamentals or quality_scores else "insufficient_evidence",
            sample_size=int(fundamentals or quality_scores),
            payload={
                "fundamental_snapshots": int(fundamentals),
                "business_quality_scores": int(quality_scores),
                "fundamental_alpha_patterns": int(patterns),
                "top_quality_companies": [
                    {
                        "ticker": row.ticker,
                        "sector": row.sector,
                        "business_quality_score": row.business_quality_score,
                        "data_quality_score": row.data_quality_score,
                    }
                    for row in top_quality
                ],
            },
        )


class PatternAgent(BaseEvidenceAgent):
    name = "pattern_agent"
    display_name = "Pattern Agent"
    responsibility = "Own historical pattern and setup-memory evidence."
    evidence_type = "pattern_memory"

    def collect(self, db: Session, *, limit: int = 8) -> AgentEvidence:
        cases = db.scalar(select(func.count()).select_from(HistoricalSimilarityCase)) or 0
        lessons = db.scalar(select(func.count()).select_from(TradeLearningEvidence)) or 0
        latest_lessons = db.scalars(
            select(TradeLearningEvidence).order_by(desc(TradeLearningEvidence.created_at)).limit(limit)
        ).all()
        return self.evidence(
            status="ready" if cases or lessons else "insufficient_evidence",
            sample_size=int(cases or lessons),
            payload={
                "historical_similarity_cases": int(cases),
                "trade_learning_lessons": int(lessons),
                "latest_patterns": [
                    {
                        "ticker": row.ticker,
                        "setup_type": row.setup_type,
                        "regime": row.regime,
                        "lesson_type": row.lesson_type,
                        "confidence": row.confidence,
                    }
                    for row in latest_lessons
                ],
            },
        )


class DecisionAgent(BaseEvidenceAgent):
    name = "decision_agent"
    display_name = "Decision Agent"
    responsibility = "Own final decision-quality evidence from the trader brain read model."
    evidence_type = "decision_quality"

    def collect(self, db: Session, *, limit: int = 8) -> AgentEvidence:
        brain = TraderBrainService().brain(db)
        return self.evidence(
            status=brain.get("status") or "unknown",
            confidence=brain.get("evidence_quality"),
            sample_size=None,
            payload={
                "brain_score": brain.get("brain_score"),
                "decision_quality": brain.get("decision_quality"),
                "alpha_readiness": brain.get("alpha_readiness"),
                "current_strength": brain.get("current_strength"),
                "current_weakness": brain.get("current_weakness"),
                "latest_lesson": brain.get("latest_lesson"),
            },
        )


class RiskAgent(BaseEvidenceAgent):
    name = "risk_agent"
    display_name = "Risk Agent"
    responsibility = "Own risk gates, noise flags and capital risk evidence."
    evidence_type = "risk_evidence"

    def collect(self, db: Session, *, limit: int = 8) -> AgentEvidence:
        alpha_gates = db.scalar(select(func.count()).select_from(AlphaGateSnapshot)) or 0
        noise_flags = db.scalar(select(func.count()).select_from(ReasoningNoiseFlag)) or 0
        latest_gates = db.scalars(select(AlphaGateSnapshot).order_by(desc(AlphaGateSnapshot.generated_at)).limit(limit)).all()
        latest_noise = db.scalars(select(ReasoningNoiseFlag).order_by(desc(ReasoningNoiseFlag.created_at)).limit(limit)).all()
        return self.evidence(
            status="ready" if alpha_gates or noise_flags else "insufficient_evidence",
            sample_size=int(alpha_gates + noise_flags),
            payload={
                "alpha_gate_snapshots": int(alpha_gates),
                "reasoning_noise_flags": int(noise_flags),
                "latest_gates": [
                    {
                        "gate_name": row.gate_name,
                        "status": row.status,
                        "score": row.score,
                        "warnings": row.warnings_json,
                    }
                    for row in latest_gates
                ],
                "latest_noise_flags": [
                    {
                        "factor_name": row.factor_name,
                        "module_name": row.module_name,
                        "noise_type": row.noise_type,
                        "severity": row.severity,
                    }
                    for row in latest_noise
                ],
            },
        )


class PortfolioAgent(BaseEvidenceAgent):
    name = "portfolio_agent"
    display_name = "Portfolio Agent"
    responsibility = "Own portfolio quality, portfolio alpha and capital allocation evidence."
    evidence_type = "portfolio_intelligence"

    def collect(self, db: Session, *, limit: int = 8) -> AgentEvidence:
        portfolio_scores = db.scalar(select(func.count()).select_from(PortfolioQualityScore)) or 0
        portfolio_alpha = db.scalar(select(func.count()).select_from(PortfolioAlphaScore)) or 0
        allocation_rows = db.scalar(select(func.count()).select_from(CapitalAllocationSnapshot)) or 0
        latest_quality = db.scalar(select(PortfolioQualityScore).order_by(desc(PortfolioQualityScore.calculated_at)).limit(1))
        latest_allocation = db.scalar(
            select(CapitalAllocationSnapshot).order_by(desc(CapitalAllocationSnapshot.calculated_at)).limit(1)
        )
        return self.evidence(
            status="ready" if portfolio_scores or allocation_rows else "insufficient_evidence",
            sample_size=int(portfolio_scores + portfolio_alpha + allocation_rows),
            payload={
                "portfolio_quality_scores": int(portfolio_scores),
                "portfolio_alpha_scores": int(portfolio_alpha),
                "capital_allocation_snapshots": int(allocation_rows),
                "latest_portfolio_quality": serialize_row(
                    latest_quality,
                    ["portfolio_quality_score", "diversification", "concentration_risk", "benchmark_excess"],
                    "calculated_at",
                ),
                "latest_capital_allocation": serialize_row(
                    latest_allocation,
                    ["mode", "total_capital", "cash_reserve_percent", "allocation_quality_score"],
                    "calculated_at",
                ),
            },
        )


class PaperTradingAgent(BaseEvidenceAgent):
    name = "paper_trading_agent"
    display_name = "Paper Trading Agent"
    responsibility = "Own paper-only trading decisions and completed outcome evidence."
    evidence_type = "paper_trading_evidence"

    def collect(self, db: Session, *, limit: int = 8) -> AgentEvidence:
        payload = TraderBrainService().paper_trading(db, limit=limit)
        decisions = payload.get("decisions") or []
        completed = payload.get("completed_decisions") or []
        return self.evidence(
            status=payload.get("status") or "unknown",
            sample_size=len(decisions) + len(completed),
            payload={
                "mode": payload.get("mode"),
                "no_broker_execution": payload.get("no_broker_execution"),
                "decision_count": len(decisions),
                "completed_decision_count": len(completed),
                "copyability_policy": payload.get("copyability_policy"),
                "recent_decisions": decisions[:limit],
                "completed_decisions": completed[:limit],
            },
        )


class LearningAgent(BaseEvidenceAgent):
    name = "learning_agent"
    display_name = "Learning Agent"
    responsibility = "Own learning-cycle progress, validation and memory-update evidence."
    evidence_type = "learning_progress"

    def collect(self, db: Session, *, limit: int = 8) -> AgentEvidence:
        training = TraderBrainService().training_ground(db)
        validation = training.get("current_validation") or {}
        evidence_total = validation.get("evidence_total") or {}
        return self.evidence(
            status=training.get("status") or "unknown",
            sample_size=evidence_total.get("outcomes_evaluated"),
            payload={
                "current_experiment": training.get("current_experiment"),
                "current_hypothesis": training.get("current_hypothesis"),
                "current_validation": validation,
                "confidence_updated": training.get("confidence_updated"),
                "why_model_changed": training.get("why_model_changed"),
                "knowledge_gained": (training.get("knowledge_gained") or [])[:limit],
            },
        )


class ResearchAgent(BaseEvidenceAgent):
    name = "research_agent"
    display_name = "Research Agent"
    responsibility = "Own research priorities, recovery actions and next-learning focus evidence."
    evidence_type = "research_priorities"

    def collect(self, db: Session, *, limit: int = 8) -> AgentEvidence:
        priorities = db.scalars(
            select(LearningFocusPriority)
            .where(LearningFocusPriority.status.in_(["active", "proposed"]))
            .order_by(desc(LearningFocusPriority.expected_learning_value), desc(LearningFocusPriority.created_at))
            .limit(limit)
        ).all()
        actions = db.scalars(
            select(AlphaRecoveryAction)
            .where(AlphaRecoveryAction.status.in_(["proposed", "testing", "applied"]))
            .order_by(desc(AlphaRecoveryAction.created_at))
            .limit(limit)
        ).all()
        return self.evidence(
            status="ready" if priorities or actions else "insufficient_evidence",
            sample_size=len(priorities) + len(actions),
            payload={
                "active_priorities": [
                    {
                        "priority_type": row.priority_type,
                        "target": row.target,
                        "expected_learning_value": row.expected_learning_value,
                        "urgency": row.urgency,
                        "reason": row.reason,
                    }
                    for row in priorities
                ],
                "recovery_actions": [
                    {
                        "action_type": row.action_type,
                        "detected_problem": row.detected_problem,
                        "affected_module": row.affected_module,
                        "status": row.status,
                        "priority": row.priority,
                    }
                    for row in actions
                ],
            },
        )


class MemoryAgent(BaseEvidenceAgent):
    name = "memory_agent"
    display_name = "Memory Agent"
    responsibility = "Own durable learning memory and meta-cognition event evidence."
    evidence_type = "memory_evidence"

    def collect(self, db: Session, *, limit: int = 8) -> AgentEvidence:
        lessons = db.scalar(select(func.count()).select_from(TradeLearningEvidence)) or 0
        meta_events = db.scalar(select(func.count()).select_from(MetaCognitionEvent)) or 0
        learning_runs = db.scalar(select(func.count()).select_from(LearningRun)) or 0
        latest_lessons = db.scalars(
            select(TradeLearningEvidence).order_by(desc(TradeLearningEvidence.created_at)).limit(limit)
        ).all()
        return self.evidence(
            status="ready" if lessons or meta_events else "insufficient_evidence",
            sample_size=int(lessons + meta_events),
            payload={
                "learning_runs": int(learning_runs),
                "trade_learning_lessons": int(lessons),
                "meta_cognition_events": int(meta_events),
                "latest_lessons": [
                    {
                        "ticker": row.ticker,
                        "setup_type": row.setup_type,
                        "lesson_type": row.lesson_type,
                        "affected_module": row.affected_module,
                        "action_taken": row.action_taken,
                        "confidence": row.confidence,
                    }
                    for row in latest_lessons
                ],
            },
        )


class AlphaAgent(BaseEvidenceAgent):
    name = "alpha_agent"
    display_name = "Alpha Agent"
    responsibility = "Own alpha readiness, benchmark truth and evidence-grade output."
    evidence_type = "alpha_validation"

    def collect(self, db: Session, *, limit: int = 8) -> AgentEvidence:
        alpha = TraderBrainService().alpha(db)
        return self.evidence(
            status=alpha.get("status") or "unknown",
            confidence=alpha.get("alpha_readiness"),
            sample_size=alpha.get("sample_size"),
            payload={
                "alpha": alpha.get("alpha"),
                "benchmark_return": alpha.get("benchmark_return"),
                "evidence_grade": alpha.get("evidence_grade"),
                "truth": alpha.get("truth"),
                "warnings": alpha.get("warnings"),
            },
            warnings=alpha.get("warnings") or [],
        )


class ValidationAgent(BaseEvidenceAgent):
    name = "validation_agent"
    display_name = "Validation Agent"
    responsibility = "Own benchmark, truth-panel and reliability warning evidence."
    evidence_type = "validation_truth"

    def collect(self, db: Session, *, limit: int = 8) -> AgentEvidence:
        summary = LearningSummaryService().summary(db)
        benchmarks = db.scalar(select(func.count()).select_from(LearningBenchmarkComparison)) or 0
        return self.evidence(
            status=summary.get("status") or "unknown",
            sample_size=int(benchmarks),
            payload={
                "benchmark_summary": summary.get("benchmark_summary"),
                "truth_panel": summary.get("truth_panel"),
                "warnings": summary.get("warnings"),
                "data_freshness": summary.get("data_freshness"),
                "last_snapshot_timestamp": summary.get("last_snapshot_timestamp"),
            },
            warnings=summary.get("warnings") or [],
        )


class DatasetAgent(BaseEvidenceAgent):
    name = "dataset_agent"
    display_name = "Dataset Agent"
    responsibility = "Own BLUM Analyst dataset readiness and export-manifest evidence."
    evidence_type = "analyst_dataset_readiness"

    def collect(self, db: Session, *, limit: int = 8) -> AgentEvidence:
        status = BlumAnalystDatasetPipeline().status(db)
        manifest = status.get("training_manifest") or {}
        sample_size = manifest.get("training_examples") or manifest.get("examples") or manifest.get("rows")
        return self.evidence(
            status=status.get("status") or "unknown",
            sample_size=sample_size if isinstance(sample_size, int) else None,
            payload={
                "model_repository": status.get("model_repository"),
                "automatic_training_enabled": status.get("automatic_training_enabled"),
                "training_manifest": manifest,
                "supported_training_modes": (status.get("contract") or {}).get("supported_training_modes"),
            },
        )


def serialize_row(row: Any | None, fields: list[str], date_field: str) -> dict[str, Any] | None:
    if row is None:
        return None
    payload = {field: getattr(row, field, None) for field in fields}
    value = getattr(row, date_field, None)
    payload[date_field] = value.isoformat() if value else None
    return payload
