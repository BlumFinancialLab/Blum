from datetime import datetime
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.database import Base


JsonType = JSON().with_variant(JSONB, "postgresql")


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(220))
    category: Mapped[str] = mapped_column(String(80), index=True)
    sector: Mapped[str] = mapped_column(String(120), index=True)
    industry: Mapped[str] = mapped_column(String(160), default="")
    country: Mapped[str] = mapped_column(String(80), index=True)
    asset_type: Mapped[str] = mapped_column(String(24), index=True)
    currency: Mapped[str] = mapped_column(String(16), default="USD")
    exchange: Mapped[str] = mapped_column(String(40), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    prices = relationship("PriceHistory", back_populates="asset", cascade="all, delete-orphan")
    signals = relationship("SignalSnapshot", back_populates="asset", cascade="all, delete-orphan")


class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint("asset_id", "date", name="uq_price_asset_date"),
        Index("ix_price_asset_date", "asset_id", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    date: Mapped[datetime] = mapped_column(Date, index=True)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    provider: Mapped[str] = mapped_column(String(40), default="yfinance")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    asset = relationship("Asset", back_populates="prices")


class PriceProviderCheck(Base):
    __tablename__ = "price_provider_checks"
    __table_args__ = (
        UniqueConstraint("asset_id", "date", name="uq_price_provider_check_asset_date"),
        Index("ix_price_provider_checks_ticker_date", "ticker", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    date: Mapped[datetime] = mapped_column(Date, index=True)
    provider_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    reference_close: Mapped[float | None] = mapped_column(Float)
    max_divergence_pct: Mapped[float | None] = mapped_column(Float, index=True)
    status: Mapped[str] = mapped_column(String(80), default="not_checked", index=True)
    observations: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(160), index=True)
    source_url: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, unique=True)
    canonical_key: Mapped[str] = mapped_column(String(260), unique=True, index=True)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    theme_tags: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    links = relationship("NewsAssetLink", back_populates="article", cascade="all, delete-orphan")
    sentiments = relationship("SentimentAnalysis", back_populates="article", cascade="all, delete-orphan")


class NewsAssetLink(Base):
    __tablename__ = "news_asset_links"
    __table_args__ = (UniqueConstraint("article_id", "asset_id", name="uq_news_asset"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("news_articles.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)

    article = relationship("NewsArticle", back_populates="links")
    asset = relationship("Asset")


class SentimentAnalysis(Base):
    __tablename__ = "sentiment_analysis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int | None] = mapped_column(ForeignKey("news_articles.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    model_name: Mapped[str] = mapped_column(String(120), index=True)
    label: Mapped[str] = mapped_column(String(40), index=True)
    score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    baseline_vader: Mapped[float | None] = mapped_column(Float)
    raw_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    article = relationship("NewsArticle", back_populates="sentiments")
    asset = relationship("Asset")


class TechnicalIndicator(Base):
    __tablename__ = "technical_indicators"
    __table_args__ = (UniqueConstraint("asset_id", "date", name="uq_indicator_asset_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    date: Mapped[datetime] = mapped_column(Date, index=True)
    indicators: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    asset = relationship("Asset")


class SignalSnapshot(Base):
    __tablename__ = "signal_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    classification: Mapped[str] = mapped_column(String(80), index=True)
    blum_score: Mapped[float] = mapped_column(Float, index=True)
    risk_level: Mapped[str] = mapped_column(String(40), index=True)
    time_horizon: Mapped[str] = mapped_column(String(80), default="Short/Medium term")
    score_version: Mapped[str] = mapped_column(String(40), default="blum-score-v0.4", index=True)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    lifecycle_state: Mapped[str] = mapped_column(String(40), default="new", index=True)
    score_breakdown: Mapped[dict] = mapped_column(JsonType, default=dict)
    technical_summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    narrative_summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    explanation: Mapped[str] = mapped_column(Text, default="")
    watch_points: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset", back_populates="signals")


class ThemeCluster(Base):
    __tablename__ = "theme_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(120), index=True)
    keywords: Mapped[dict] = mapped_column(JsonType, default=dict)
    article_ids: Mapped[dict] = mapped_column(JsonType, default=dict)
    asset_tickers: Mapped[dict] = mapped_column(JsonType, default=dict)
    centroid: Mapped[dict] = mapped_column(JsonType, default=dict)
    sentiment_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class EmbeddingVector(Base):
    __tablename__ = "embedding_vectors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int | None] = mapped_column(ForeignKey("news_articles.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    model_name: Mapped[str] = mapped_column(String(160), index=True)
    vector: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AIInsight(Base):
    __tablename__ = "ai_insights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    model_name: Mapped[str] = mapped_column(String(160), index=True)
    insight_type: Mapped[str] = mapped_column(String(80), default="asset_explanation")
    structured_output: Mapped[dict] = mapped_column(JsonType, default=dict)
    explanation: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ETFTrend(Base):
    __tablename__ = "etf_trends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    category: Mapped[str] = mapped_column(String(120), index=True)
    momentum_score: Mapped[float] = mapped_column(Float, default=0.0)
    thematic_score: Mapped[float] = mapped_column(Float, default=0.0)
    confirmation_score: Mapped[float] = mapped_column(Float, default=0.0)
    details: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class BacktestResult(Base):
    __tablename__ = "backtest_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_name: Mapped[str] = mapped_column(String(160), index=True)
    benchmark: Mapped[str] = mapped_column(String(32), default="SPY")
    parameters: Mapped[dict] = mapped_column(JsonType, default=dict)
    metrics: Mapped[dict] = mapped_column(JsonType, default=dict)
    results: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("ticker", "watchlist_name", name="uq_watchlist_ticker_name"),
        Index("ix_watchlist_items_name_created", "watchlist_name", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    watchlist_name: Mapped[str] = mapped_column(String(120), default="Strategic Watchlist", index=True)
    status: Mapped[str] = mapped_column(String(80), default="active", index=True)
    thesis: Mapped[str] = mapped_column(Text, default="")
    alert_rules: Mapped[dict] = mapped_column(JsonType, default=dict)
    last_score: Mapped[float | None] = mapped_column(Float)
    metadata_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    asset = relationship("Asset")


class IntelligenceReport(Base):
    __tablename__ = "intelligence_reports"
    __table_args__ = (Index("ix_intelligence_reports_ticker_created", "ticker", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    report_type: Mapped[str] = mapped_column(String(80), default="asset_intelligence", index=True)
    title: Mapped[str] = mapped_column(String(260))
    summary: Mapped[str] = mapped_column(Text, default="")
    structured_output: Mapped[dict] = mapped_column(JsonType, default=dict)
    data_mode: Mapped[str] = mapped_column(String(80), default="real_public_data", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")


class PortfolioScenario(Base):
    __tablename__ = "portfolio_scenarios"
    __table_args__ = (Index("ix_portfolio_scenarios_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario_name: Mapped[str] = mapped_column(String(160), index=True)
    risk_profile: Mapped[str] = mapped_column(String(80), default="balanced", index=True)
    allocation: Mapped[dict] = mapped_column(JsonType, default=dict)
    rationale: Mapped[dict] = mapped_column(JsonType, default=dict)
    disclaimer: Mapped[str] = mapped_column(Text, default="")
    data_mode: Mapped[str] = mapped_column(String(80), default="real_public_data", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class SignalEvaluation(Base):
    __tablename__ = "signal_evaluations"
    __table_args__ = (
        UniqueConstraint("signal_id", "horizon_days", name="uq_signal_evaluation_signal_horizon"),
        Index("ix_signal_evaluations_ticker_horizon", "ticker", "horizon_days"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signal_snapshots.id", ondelete="SET NULL"), index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    sector: Mapped[str] = mapped_column(String(120), default="", index=True)
    signal_type: Mapped[str] = mapped_column(String(80), index=True)
    expected_direction: Mapped[str] = mapped_column(String(40), default="up_or_resilient", index=True)
    time_horizon: Mapped[str] = mapped_column(String(80), default="")
    horizon_days: Mapped[int] = mapped_column(Integer, index=True)
    signal_created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    initial_confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    initial_sentiment: Mapped[float] = mapped_column(Float, default=0.0)
    initial_momentum: Mapped[float] = mapped_column(Float, default=0.0)
    news_evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    price_at_signal: Mapped[float | None] = mapped_column(Float)
    price_after_horizon: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    max_upside: Mapped[float | None] = mapped_column(Float)
    realized_return: Mapped[float | None] = mapped_column(Float, index=True)
    volatility_after_signal: Mapped[float | None] = mapped_column(Float)
    outcome: Mapped[str] = mapped_column(String(40), default="inconclusive", index=True)
    explanation_quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    data_quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    evaluation_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    signal = relationship("SignalSnapshot")
    asset = relationship("Asset")


class SignalOutcome(Base):
    __tablename__ = "signal_outcomes"
    __table_args__ = (
        UniqueConstraint("signal_id", name="uq_signal_outcome_signal"),
        Index("ix_signal_outcomes_ticker_created", "ticker", "signal_created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signal_snapshots.id", ondelete="SET NULL"), index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    sector: Mapped[str] = mapped_column(String(120), default="", index=True)
    signal_type: Mapped[str] = mapped_column(String(80), index=True)
    signal_created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    initial_score: Mapped[float] = mapped_column(Float, default=0.0)
    initial_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    final_outcome: Mapped[str] = mapped_column(String(40), default="inconclusive", index=True)
    best_horizon_days: Mapped[int | None] = mapped_column(Integer)
    worst_horizon_days: Mapped[int | None] = mapped_column(Integer)
    average_realized_return: Mapped[float | None] = mapped_column(Float)
    outcome_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    signal = relationship("SignalSnapshot")
    asset = relationship("Asset")


class ModelWeightVersion(Base):
    __tablename__ = "model_weight_versions"
    __table_args__ = (Index("ix_model_weight_versions_active_created", "is_active", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    weights: Mapped[dict] = mapped_column(JsonType, default=dict)
    previous_weights: Mapped[dict] = mapped_column(JsonType, default=dict)
    calibration_metrics: Mapped[dict] = mapped_column(JsonType, default=dict)
    change_reason: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class LearningEvent(Base):
    __tablename__ = "learning_events"
    __table_args__ = (Index("ix_learning_events_type_created", "event_type", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    severity: Mapped[str] = mapped_column(String(40), default="Info", index=True)
    title: Mapped[str] = mapped_column(String(260))
    description: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class HistoricalSimilarityCase(Base):
    __tablename__ = "historical_similarity_cases"
    __table_args__ = (Index("ix_similarity_cases_ticker_created", "ticker", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    reference_signal_id: Mapped[int | None] = mapped_column(ForeignKey("signal_snapshots.id", ondelete="SET NULL"), index=True)
    case_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    similarity_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    features: Mapped[dict] = mapped_column(JsonType, default=dict)
    outcome_summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")
    reference_signal = relationship("SignalSnapshot")


class ConfidenceAdjustment(Base):
    __tablename__ = "confidence_adjustments"
    __table_args__ = (Index("ix_confidence_adjustments_ticker_created", "ticker", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    sector: Mapped[str | None] = mapped_column(String(120), index=True)
    signal_type: Mapped[str | None] = mapped_column(String(80), index=True)
    base_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    adjusted_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    adjustment: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")


class SourceReliabilityScore(Base):
    __tablename__ = "source_reliability_scores"
    __table_args__ = (
        UniqueConstraint("source", name="uq_source_reliability_source"),
        Index("ix_source_reliability_score", "reliability_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(160), index=True)
    article_count: Mapped[int] = mapped_column(Integer, default=0)
    linked_signal_count: Mapped[int] = mapped_column(Integer, default=0)
    correct_signal_rate: Mapped[float | None] = mapped_column(Float)
    false_positive_rate: Mapped[float | None] = mapped_column(Float)
    reliability_score: Mapped[float] = mapped_column(Float, default=50.0, index=True)
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class TickerAccuracyProfile(Base):
    __tablename__ = "ticker_accuracy_profiles"
    __table_args__ = (
        UniqueConstraint("ticker", name="uq_ticker_accuracy_profile"),
        Index("ix_ticker_accuracy_profiles_score", "accuracy_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    evaluated_signals: Mapped[int] = mapped_column(Integer, default=0)
    correct_rate: Mapped[float | None] = mapped_column(Float)
    neutral_rate: Mapped[float | None] = mapped_column(Float)
    average_return: Mapped[float | None] = mapped_column(Float)
    average_drawdown: Mapped[float | None] = mapped_column(Float)
    accuracy_score: Mapped[float] = mapped_column(Float, default=50.0, index=True)
    profile_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    asset = relationship("Asset")


class SectorAccuracyProfile(Base):
    __tablename__ = "sector_accuracy_profiles"
    __table_args__ = (
        UniqueConstraint("sector", name="uq_sector_accuracy_profile"),
        Index("ix_sector_accuracy_profiles_score", "accuracy_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sector: Mapped[str] = mapped_column(String(120), index=True)
    evaluated_signals: Mapped[int] = mapped_column(Integer, default=0)
    correct_rate: Mapped[float | None] = mapped_column(Float)
    neutral_rate: Mapped[float | None] = mapped_column(Float)
    average_return: Mapped[float | None] = mapped_column(Float)
    average_drawdown: Mapped[float | None] = mapped_column(Float)
    accuracy_score: Mapped[float] = mapped_column(Float, default=50.0, index=True)
    profile_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class AccuracySnapshot(Base):
    __tablename__ = "accuracy_snapshots"
    __table_args__ = (Index("ix_accuracy_snapshots_scope_created", "scope", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    scope: Mapped[str] = mapped_column(String(80), default="asset", index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    confidence_label: Mapped[str] = mapped_column(String(40), default="Low", index=True)
    components: Mapped[dict] = mapped_column(JsonType, default=dict)
    issues: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")


class CorporateActionEvent(Base):
    __tablename__ = "corporate_action_events"
    __table_args__ = (
        UniqueConstraint("asset_id", "action_type", "effective_date", "source", name="uq_corporate_action_event"),
        Index("ix_corporate_action_events_ticker_date", "ticker", "effective_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    action_type: Mapped[str] = mapped_column(String(80), index=True)
    effective_date: Mapped[datetime] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(120), default="price_anomaly_detector", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    details: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")


class FundamentalSnapshot(Base):
    __tablename__ = "fundamental_snapshots"
    __table_args__ = (
        UniqueConstraint("asset_id", "provider", "period_end", name="uq_fundamental_asset_provider_period"),
        Index("ix_fundamental_snapshots_ticker_created", "ticker", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    provider: Mapped[str] = mapped_column(String(120), default="sec_companyfacts", index=True)
    period_end: Mapped[datetime | None] = mapped_column(Date, index=True)
    fiscal_period: Mapped[str] = mapped_column(String(40), default="")
    metrics: Mapped[dict] = mapped_column(JsonType, default=dict)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")


class MacroSnapshot(Base):
    __tablename__ = "macro_snapshots"
    __table_args__ = (
        UniqueConstraint("indicator", "date", "provider", name="uq_macro_indicator_date_provider"),
        Index("ix_macro_snapshots_indicator_created", "indicator", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    indicator: Mapped[str] = mapped_column(String(80), index=True)
    date: Mapped[datetime] = mapped_column(Date, index=True)
    value: Mapped[float | None] = mapped_column(Float)
    provider: Mapped[str] = mapped_column(String(120), default="fred", index=True)
    details: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class IPOCompany(Base):
    __tablename__ = "ipo_companies"
    __table_args__ = (
        UniqueConstraint("cik", "name", name="uq_ipo_company_cik_name"),
        Index("ix_ipo_companies_last_seen", "last_seen_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cik: Mapped[str | None] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(260), index=True)
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    exchange: Mapped[str | None] = mapped_column(String(80), index=True)
    country: Mapped[str] = mapped_column(String(80), default="Unknown", index=True)
    sector: Mapped[str] = mapped_column(String(120), default="Unknown", index=True)
    industry: Mapped[str] = mapped_column(String(160), default="Unknown")
    status: Mapped[str] = mapped_column(String(80), default="filing_observed", index=True)
    company_metadata: Mapped[dict] = mapped_column(JsonType, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    filings = relationship("IPOFiling", back_populates="company", cascade="all, delete-orphan")
    scores = relationship("IPOScore", back_populates="company", cascade="all, delete-orphan")


class IPOFiling(Base):
    __tablename__ = "ipo_filings"
    __table_args__ = (
        UniqueConstraint("accession_number", name="uq_ipo_filing_accession"),
        Index("ix_ipo_filings_company_form_date", "company_id", "form_type", "filing_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("ipo_companies.id", ondelete="CASCADE"), index=True)
    cik: Mapped[str | None] = mapped_column(String(20), index=True)
    company_name: Mapped[str] = mapped_column(String(260), index=True)
    form_type: Mapped[str] = mapped_column(String(40), index=True)
    filing_date: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    accession_number: Mapped[str] = mapped_column(String(80), index=True)
    source: Mapped[str] = mapped_column(String(120), default="SEC EDGAR", index=True)
    raw_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    company = relationship("IPOCompany", back_populates="filings")
    scores = relationship("IPOScore", back_populates="filing")


class IPOScore(Base):
    __tablename__ = "ipo_scores"
    __table_args__ = (Index("ix_ipo_scores_company_created", "company_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("ipo_companies.id", ondelete="CASCADE"), index=True)
    filing_id: Mapped[int | None] = mapped_column(ForeignKey("ipo_filings.id", ondelete="SET NULL"), index=True)
    readiness_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    listing_probability_score: Mapped[float] = mapped_column(Float, default=0.0)
    narrative_heat_score: Mapped[float] = mapped_column(Float, default=0.0)
    valuation_risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    opportunity_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    classification: Mapped[str] = mapped_column(String(80), index=True)
    time_horizon: Mapped[str] = mapped_column(String(80), default="IPO watch")
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    explanation: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    company = relationship("IPOCompany", back_populates="scores")
    filing = relationship("IPOFiling", back_populates="scores")


class MarketBrainSnapshot(Base):
    __tablename__ = "market_brain_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    brain_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    regime: Mapped[str] = mapped_column(String(120), index=True)
    horizon: Mapped[str] = mapped_column(String(80), default="Multi-horizon")
    summary: Mapped[str] = mapped_column(Text, default="")
    structured_output: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
