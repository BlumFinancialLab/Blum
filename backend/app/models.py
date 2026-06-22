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


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        UniqueConstraint("session_key", name="uq_chat_session_key"),
        Index("ix_chat_sessions_updated", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_key: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(220), default="Blum Chat Session")
    language: Mapped[str] = mapped_column(String(12), default="en", index=True)
    horizon: Mapped[str] = mapped_column(String(80), default="multi-horizon", index=True)
    risk_profile: Mapped[str] = mapped_column(String(80), default="balanced", index=True)
    metadata_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_session_created", "session_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(24), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(12), default="en", index=True)
    response_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    session = relationship("ChatSession")


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


class ChartAnalysis(Base):
    __tablename__ = "chart_analyses"
    __table_args__ = (
        Index("ix_chart_analyses_ticker_timeframe_created", "ticker", "timeframe", "created_at"),
        Index("ix_chart_analyses_image_hash", "image_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), default="6M", index=True)
    period: Mapped[str] = mapped_column(String(40), default="1y", index=True)
    image_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    model_used: Mapped[str] = mapped_column(String(180), default="deterministic_technical_analysis", index=True)
    visual_analysis_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    deterministic_analysis_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    hybrid_analysis_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    chart_image: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")


class TechnicalLevel(Base):
    __tablename__ = "technical_levels"
    __table_args__ = (
        UniqueConstraint("ticker", "timeframe", name="uq_technical_levels_ticker_timeframe"),
        Index("ix_technical_levels_ticker_updated", "ticker", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), default="6M", index=True)
    support_levels_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    resistance_levels_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    breakout_level: Mapped[float | None] = mapped_column(Float)
    breakdown_level: Mapped[float | None] = mapped_column(Float)
    invalidation_level: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    asset = relationship("Asset")


class TechnicalSignal(Base):
    __tablename__ = "technical_signals"
    __table_args__ = (Index("ix_technical_signals_ticker_timeframe_created", "ticker", "timeframe", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), default="6M", index=True)
    signal_type: Mapped[str] = mapped_column(String(120), index=True)
    direction: Mapped[str] = mapped_column(String(40), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    invalidation_level: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")


class ChartPatternMemory(Base):
    __tablename__ = "chart_pattern_memory"
    __table_args__ = (Index("ix_chart_pattern_memory_ticker_pattern_created", "ticker", "pattern_type", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), default="6M", index=True)
    pattern_type: Mapped[str] = mapped_column(String(120), index=True)
    setup_embedding: Mapped[dict] = mapped_column(JsonType, default=dict)
    outcome_1d: Mapped[float | None] = mapped_column(Float)
    outcome_7d: Mapped[float | None] = mapped_column(Float)
    outcome_30d: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    success: Mapped[bool | None] = mapped_column(Boolean, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")


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


class BlumKnowledgeRecord(Base):
    __tablename__ = "blum_knowledge_records"
    __table_args__ = (
        UniqueConstraint("reasoning_hash", name="uq_blum_knowledge_reasoning_hash"),
        Index("ix_blum_knowledge_ticker_created", "ticker", "created_at"),
        Index("ix_blum_knowledge_regime_created", "market_regime", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signal_snapshots.id", ondelete="SET NULL"), index=True)
    ai_insight_id: Mapped[int | None] = mapped_column(ForeignKey("ai_insights.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    sector: Mapped[str] = mapped_column(String(120), default="", index=True)
    industry: Mapped[str] = mapped_column(String(160), default="")
    source_type: Mapped[str] = mapped_column(String(80), default="signal_snapshot", index=True)
    reasoning_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    market_regime: Mapped[str] = mapped_column(String(120), default="Sideways", index=True)
    volatility_regime: Mapped[str] = mapped_column(String(80), default="Unknown", index=True)
    risk_sentiment: Mapped[str] = mapped_column(String(80), default="Unknown", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    conviction_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    market_context: Mapped[dict] = mapped_column(JsonType, default=dict)
    asset_context: Mapped[dict] = mapped_column(JsonType, default=dict)
    blum_reasoning: Mapped[dict] = mapped_column(JsonType, default=dict)
    prediction_horizons: Mapped[dict] = mapped_column(JsonType, default=dict)
    quality_scores: Mapped[dict] = mapped_column(JsonType, default=dict)
    self_critique: Mapped[dict] = mapped_column(JsonType, default=dict)
    training_sample: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    asset = relationship("Asset")
    signal = relationship("SignalSnapshot")
    ai_insight = relationship("AIInsight")


class BlumThesisOutcome(Base):
    __tablename__ = "blum_thesis_outcomes"
    __table_args__ = (
        UniqueConstraint("knowledge_record_id", "horizon_days", name="uq_blum_thesis_outcome_record_horizon"),
        Index("ix_blum_thesis_outcomes_ticker_horizon", "ticker", "horizon_days"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    knowledge_record_id: Mapped[int] = mapped_column(ForeignKey("blum_knowledge_records.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    horizon_days: Mapped[int] = mapped_column(Integer, index=True)
    expected_direction: Mapped[str] = mapped_column(String(80), default="up_or_resilient", index=True)
    price_at_thesis: Mapped[float | None] = mapped_column(Float)
    price_after_horizon: Mapped[float | None] = mapped_column(Float)
    realized_return: Mapped[float | None] = mapped_column(Float, index=True)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    max_upside: Mapped[float | None] = mapped_column(Float)
    realized_volatility: Mapped[float | None] = mapped_column(Float)
    outcome: Mapped[str] = mapped_column(String(40), default="inconclusive", index=True)
    success: Mapped[bool | None] = mapped_column(Boolean, index=True)
    outcome_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    knowledge_record = relationship("BlumKnowledgeRecord")
    asset = relationship("Asset")


class BlumReasoningMemory(Base):
    __tablename__ = "blum_reasoning_memory"
    __table_args__ = (Index("ix_blum_reasoning_memory_ticker_type_created", "ticker", "memory_type", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    knowledge_record_id: Mapped[int | None] = mapped_column(ForeignKey("blum_knowledge_records.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    memory_type: Mapped[str] = mapped_column(String(80), default="asset_thesis", index=True)
    embedding_model: Mapped[str] = mapped_column(String(160), default="", index=True)
    embedding: Mapped[dict] = mapped_column(JsonType, default=dict)
    memory_text: Mapped[str] = mapped_column(Text, default="")
    metadata_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    outcome_label: Mapped[str] = mapped_column(String(80), default="pending", index=True)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    knowledge_record = relationship("BlumKnowledgeRecord")
    asset = relationship("Asset")


class BlumTrainingExample(Base):
    __tablename__ = "blum_training_examples"
    __table_args__ = (
        UniqueConstraint("knowledge_record_id", "task_type", name="uq_blum_training_record_task"),
        Index("ix_blum_training_examples_ready_created", "export_ready", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    knowledge_record_id: Mapped[int | None] = mapped_column(ForeignKey("blum_knowledge_records.id", ondelete="CASCADE"), index=True)
    task_type: Mapped[str] = mapped_column(String(100), default="financial_thesis_generation", index=True)
    dataset_split: Mapped[str] = mapped_column(String(40), default="train", index=True)
    base_model_family: Mapped[str] = mapped_column(String(80), default="qwen_llama_mistral", index=True)
    input_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    output_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    messages: Mapped[dict] = mapped_column(JsonType, default=dict)
    quality_scores: Mapped[dict] = mapped_column(JsonType, default=dict)
    preference_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    export_ready: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    knowledge_record = relationship("BlumKnowledgeRecord")


class BlumThesisQualityScore(Base):
    __tablename__ = "blum_thesis_quality_scores"
    __table_args__ = (UniqueConstraint("knowledge_record_id", name="uq_blum_quality_record"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    knowledge_record_id: Mapped[int] = mapped_column(ForeignKey("blum_knowledge_records.id", ondelete="CASCADE"), index=True)
    reasoning_depth: Mapped[float] = mapped_column(Float, default=0.0)
    consistency: Mapped[float] = mapped_column(Float, default=0.0)
    contradiction_handling: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_calibration: Mapped[float] = mapped_column(Float, default=0.0)
    historical_alignment: Mapped[float] = mapped_column(Float, default=0.0)
    narrative_quality: Mapped[float] = mapped_column(Float, default=0.0)
    explainability_quality: Mapped[float] = mapped_column(Float, default=0.0)
    overall_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    evaluator_version: Mapped[str] = mapped_column(String(80), default="blum-quality-v0.1", index=True)
    quality_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    knowledge_record = relationship("BlumKnowledgeRecord")


class BlumSelfCritique(Base):
    __tablename__ = "blum_self_critiques"
    __table_args__ = (UniqueConstraint("knowledge_record_id", name="uq_blum_self_critique_record"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    knowledge_record_id: Mapped[int] = mapped_column(ForeignKey("blum_knowledge_records.id", ondelete="CASCADE"), index=True)
    analyst_view: Mapped[dict] = mapped_column(JsonType, default=dict)
    skeptic_view: Mapped[dict] = mapped_column(JsonType, default=dict)
    historical_view: Mapped[dict] = mapped_column(JsonType, default=dict)
    final_view: Mapped[dict] = mapped_column(JsonType, default=dict)
    critique_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    knowledge_record = relationship("BlumKnowledgeRecord")


class BlumNarrativeMemory(Base):
    __tablename__ = "blum_narrative_memory"
    __table_args__ = (Index("ix_blum_narrative_stage_updated", "lifecycle_stage", "updated_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    narrative: Mapped[str] = mapped_column(String(160), index=True)
    lifecycle_stage: Mapped[str] = mapped_column(String(80), default="Emerging", index=True)
    intensity: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    velocity: Mapped[float] = mapped_column(Float, default=0.0)
    saturation: Mapped[float] = mapped_column(Float, default=0.0)
    crowding: Mapped[float] = mapped_column(Float, default=0.0)
    linked_assets: Mapped[dict] = mapped_column(JsonType, default=dict)
    sectors: Mapped[dict] = mapped_column(JsonType, default=dict)
    outcome_summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class BlumRegimeMemory(Base):
    __tablename__ = "blum_regime_memory"
    __table_args__ = (Index("ix_blum_regime_memory_regime_updated", "market_regime", "updated_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_regime: Mapped[str] = mapped_column(String(120), index=True)
    volatility_regime: Mapped[str] = mapped_column(String(80), default="Unknown", index=True)
    liquidity_regime: Mapped[str] = mapped_column(String(80), default="Unknown", index=True)
    macro_context: Mapped[dict] = mapped_column(JsonType, default=dict)
    reasoning_patterns: Mapped[dict] = mapped_column(JsonType, default=dict)
    outcome_summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class ThesisLifecycleEvent(Base):
    __tablename__ = "thesis_lifecycle_events"
    __table_args__ = (
        Index("ix_thesis_lifecycle_events_ticker_status", "ticker", "new_status"),
        Index("ix_thesis_lifecycle_events_record_created", "knowledge_record_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    knowledge_record_id: Mapped[int] = mapped_column(ForeignKey("blum_knowledge_records.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    previous_status: Mapped[str] = mapped_column(String(40), default="NEW", index=True)
    new_status: Mapped[str] = mapped_column(String(40), default="ACTIVE", index=True)
    status_reason: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    conviction_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    outcome_summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    evidence_delta: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    knowledge_record = relationship("BlumKnowledgeRecord")


class ModelReliabilityMatrix(Base):
    __tablename__ = "model_reliability_matrix"
    __table_args__ = (
        UniqueConstraint("engine_name", "sector", "market_regime", "timeframe", name="uq_model_reliability_context"),
        Index("ix_model_reliability_matrix_score", "reliability_score"),
        Index("ix_model_reliability_matrix_engine_updated", "engine_name", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    engine_name: Mapped[str] = mapped_column(String(100), index=True)
    sector: Mapped[str] = mapped_column(String(120), default="All", index=True)
    market_regime: Mapped[str] = mapped_column(String(120), default="All", index=True)
    timeframe: Mapped[str] = mapped_column(String(40), default="All", index=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, default=0)
    neutral_count: Mapped[int] = mapped_column(Integer, default=0)
    inconclusive_count: Mapped[int] = mapped_column(Integer, default=0)
    reliability_score: Mapped[float] = mapped_column(Float, default=50.0, index=True)
    weight_adjustment: Mapped[float] = mapped_column(Float, default=0.0)
    calibration_error: Mapped[float | None] = mapped_column(Float)
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class ConfidenceCalibrationBucket(Base):
    __tablename__ = "confidence_calibration_buckets"
    __table_args__ = (
        UniqueConstraint("bucket_label", name="uq_confidence_calibration_bucket_label"),
        Index("ix_confidence_calibration_buckets_error", "calibration_error"),
        Index("ix_confidence_calibration_buckets_updated", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bucket_label: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    min_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    max_confidence: Mapped[float] = mapped_column(Float, default=100.0)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    average_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    empirical_success_rate: Mapped[float] = mapped_column(Float, default=0.0)
    calibration_error: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    suggested_adjustment: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class MetaLearningEvent(Base):
    __tablename__ = "meta_learning_events"
    __table_args__ = (
        Index("ix_meta_learning_events_type_created", "event_type", "created_at"),
        Index("ix_meta_learning_events_engine_status", "engine_name", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    engine_name: Mapped[str | None] = mapped_column(String(100), index=True)
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(40), default="Info", index=True)
    lesson: Mapped[str] = mapped_column(Text, default="")
    root_cause: Mapped[str] = mapped_column(String(160), default="", index=True)
    proposed_change: Mapped[dict] = mapped_column(JsonType, default=dict)
    trigger_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class BlumKnowledgeGraphNode(Base):
    __tablename__ = "blum_knowledge_graph_nodes"
    __table_args__ = (UniqueConstraint("canonical_key", name="uq_blum_graph_node_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_type: Mapped[str] = mapped_column(String(80), index=True)
    label: Mapped[str] = mapped_column(String(220), index=True)
    canonical_key: Mapped[str] = mapped_column(String(260), unique=True, index=True)
    properties: Mapped[dict] = mapped_column(JsonType, default=dict)
    embedding: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class BlumKnowledgeGraphEdge(Base):
    __tablename__ = "blum_knowledge_graph_edges"
    __table_args__ = (
        UniqueConstraint("source_node_id", "target_node_id", "relation_type", name="uq_blum_graph_edge"),
        Index("ix_blum_graph_edges_relation_created", "relation_type", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_node_id: Mapped[int] = mapped_column(ForeignKey("blum_knowledge_graph_nodes.id", ondelete="CASCADE"), index=True)
    target_node_id: Mapped[int] = mapped_column(ForeignKey("blum_knowledge_graph_nodes.id", ondelete="CASCADE"), index=True)
    relation_type: Mapped[str] = mapped_column(String(100), index=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0, index=True)
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    source_node = relationship("BlumKnowledgeGraphNode", foreign_keys=[source_node_id])
    target_node = relationship("BlumKnowledgeGraphNode", foreign_keys=[target_node_id])


class BlumDatasetExport(Base):
    __tablename__ = "blum_dataset_exports"
    __table_args__ = (Index("ix_blum_dataset_exports_status_created", "status", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    export_name: Mapped[str] = mapped_column(String(180), index=True)
    format: Mapped[str] = mapped_column(String(40), default="jsonl", index=True)
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    file_path: Mapped[str] = mapped_column(Text, default="")
    filters: Mapped[dict] = mapped_column(JsonType, default=dict)
    status: Mapped[str] = mapped_column(String(80), default="created", index=True)
    payload_summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class BlumModelTrainingJob(Base):
    __tablename__ = "blum_model_training_jobs"
    __table_args__ = (Index("ix_blum_training_jobs_status_created", "status", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_name: Mapped[str] = mapped_column(String(180), index=True)
    model_family: Mapped[str] = mapped_column(String(80), index=True)
    base_model: Mapped[str] = mapped_column(String(180), index=True)
    method: Mapped[str] = mapped_column(String(80), index=True)
    dataset_export_id: Mapped[int | None] = mapped_column(ForeignKey("blum_dataset_exports.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(80), default="planned", index=True)
    training_config: Mapped[dict] = mapped_column(JsonType, default=dict)
    metrics: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    dataset_export = relationship("BlumDatasetExport")


class ExternalDatasetSource(Base):
    __tablename__ = "external_dataset_sources"
    __table_args__ = (
        UniqueConstraint("dataset_id", name="uq_external_dataset_source_dataset_id"),
        Index("ix_external_dataset_sources_status_priority", "status", "priority"),
        Index("ix_external_dataset_sources_domain_updated", "primary_domain", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(80), default="hugging_face", index=True)
    title: Mapped[str] = mapped_column(String(260), default="")
    primary_domain: Mapped[str] = mapped_column(String(80), default="market_data", index=True)
    data_domains: Mapped[dict] = mapped_column(JsonType, default=dict)
    license: Mapped[str] = mapped_column(String(80), default="unknown", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=50, index=True)
    ingestion_mode: Mapped[str] = mapped_column(String(80), default="catalog_only", index=True)
    status: Mapped[str] = mapped_column(String(80), default="discovered", index=True)
    dataset_url: Mapped[str] = mapped_column(Text, default="")
    viewer_status: Mapped[dict] = mapped_column(JsonType, default=dict)
    parquet_files: Mapped[dict] = mapped_column(JsonType, default=dict)
    size_summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    usage_policy: Mapped[dict] = mapped_column(JsonType, default=dict)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class AutonomousEngineRun(Base):
    __tablename__ = "autonomous_engine_runs"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_autonomous_engine_run_id"),
        Index("ix_autonomous_engine_runs_status_started", "status", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    trigger: Mapped[str] = mapped_column(String(80), default="scheduled", index=True)
    status: Mapped[str] = mapped_column(String(80), default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    stage_results: Mapped[dict] = mapped_column(JsonType, default=dict)
    readiness_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    data_coverage_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    reasoning_memory_created: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    error_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class LearningRun(Base):
    __tablename__ = "learning_runs"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_learning_run_id"),
        Index("ix_learning_runs_status_started", "status", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    trigger: Mapped[str] = mapped_column(String(80), default="scheduled", index=True)
    status: Mapped[str] = mapped_column(String(80), default="running", index=True)
    evaluation_mode: Mapped[str] = mapped_column(String(80), default="walk_forward", index=True)
    asset_universe: Mapped[str] = mapped_column(String(120), default="stocks,etfs", index=True)
    batch_size: Mapped[int] = mapped_column(Integer, default=0)
    predictions_created: Mapped[int] = mapped_column(Integer, default=0)
    outcomes_evaluated: Mapped[int] = mapped_column(Integer, default=0)
    mistakes_found: Mapped[int] = mapped_column(Integer, default=0)
    memory_updates: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    anti_overfitting_report: Mapped[dict] = mapped_column(JsonType, default=dict)
    error_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class HistoricalPrediction(Base):
    __tablename__ = "historical_predictions"
    __table_args__ = (
        Index("ix_historical_predictions_ticker_date", "ticker", "analysis_date"),
        Index("ix_historical_predictions_run_created", "learning_run_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    learning_run_id: Mapped[int | None] = mapped_column(ForeignKey("learning_runs.id", ondelete="SET NULL"), index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    asset_type: Mapped[str] = mapped_column(String(40), default="", index=True)
    sector: Mapped[str] = mapped_column(String(120), default="", index=True)
    market: Mapped[str] = mapped_column(String(80), default="", index=True)
    market_regime: Mapped[str] = mapped_column(String(120), default="Unknown", index=True)
    volatility_regime: Mapped[str] = mapped_column(String(80), default="Unknown", index=True)
    analysis_date: Mapped[datetime] = mapped_column(Date, index=True)
    initial_price: Mapped[float | None] = mapped_column(Float)
    prediction_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    point_in_time_context: Mapped[dict] = mapped_column(JsonType, default=dict)
    expected_direction: Mapped[str] = mapped_column(String(40), default="neutral", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    model_version: Mapped[str] = mapped_column(String(80), default="blum-learning-loop-v1", index=True)
    data_quality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    learning_run = relationship("LearningRun")
    asset = relationship("Asset")


class PredictionOutcome(Base):
    __tablename__ = "prediction_outcomes"
    __table_args__ = (
        UniqueConstraint("prediction_id", "timeframe", name="uq_prediction_outcome_prediction_timeframe"),
        Index("ix_prediction_outcomes_ticker_timeframe", "ticker", "timeframe"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("historical_predictions.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), index=True)
    horizon_days: Mapped[int] = mapped_column(Integer, index=True)
    evaluation_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    price_at_evaluation: Mapped[float | None] = mapped_column(Float)
    realized_return: Mapped[float | None] = mapped_column(Float, index=True)
    max_favorable_excursion: Mapped[float | None] = mapped_column(Float)
    max_adverse_excursion: Mapped[float | None] = mapped_column(Float)
    drawdown: Mapped[float | None] = mapped_column(Float)
    time_to_target: Mapped[int | None] = mapped_column(Integer)
    time_to_invalidation: Mapped[int | None] = mapped_column(Integer)
    target_hit: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    invalidation_hit: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    direction_correct: Mapped[bool | None] = mapped_column(Boolean, index=True)
    false_positive: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    false_negative: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    missed_opportunity: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    outcome_label: Mapped[str] = mapped_column(String(40), default="inconclusive", index=True)
    confidence_calibration_error: Mapped[float | None] = mapped_column(Float)
    metrics_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    prediction = relationship("HistoricalPrediction")


class MistakeAnalysis(Base):
    __tablename__ = "mistake_analysis"
    __table_args__ = (Index("ix_mistake_analysis_error_created", "error_type", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prediction_id: Mapped[int | None] = mapped_column(ForeignKey("historical_predictions.id", ondelete="CASCADE"), index=True)
    outcome_id: Mapped[int | None] = mapped_column(ForeignKey("prediction_outcomes.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), index=True)
    error_type: Mapped[str] = mapped_column(String(100), index=True)
    severity: Mapped[str] = mapped_column(String(40), default="Info", index=True)
    predicted: Mapped[dict] = mapped_column(JsonType, default=dict)
    actual: Mapped[dict] = mapped_column(JsonType, default=dict)
    misleading_signal: Mapped[str] = mapped_column(Text, default="")
    signal_to_weight_more: Mapped[str] = mapped_column(Text, default="")
    rule_adjustment: Mapped[str] = mapped_column(Text, default="")
    future_impact: Mapped[str] = mapped_column(Text, default="")
    explanation: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    prediction = relationship("HistoricalPrediction")
    outcome = relationship("PredictionOutcome")


class SignalPerformance(Base):
    __tablename__ = "signal_performance"
    __table_args__ = (
        UniqueConstraint("signal_name", "timeframe", "market_regime", name="uq_signal_performance_signal_timeframe_regime"),
        Index("ix_signal_performance_reliability", "reliability_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_name: Mapped[str] = mapped_column(String(120), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), index=True)
    market_regime: Mapped[str] = mapped_column(String(120), default="All", index=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    false_positive_count: Mapped[int] = mapped_column(Integer, default=0)
    false_negative_count: Mapped[int] = mapped_column(Integer, default=0)
    average_return: Mapped[float | None] = mapped_column(Float)
    average_drawdown: Mapped[float | None] = mapped_column(Float)
    profit_factor: Mapped[float | None] = mapped_column(Float)
    reliability_score: Mapped[float] = mapped_column(Float, default=50.0, index=True)
    weight_adjustment: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class StrategyMemory(Base):
    __tablename__ = "strategy_memory"
    __table_args__ = (
        UniqueConstraint("memory_key", name="uq_strategy_memory_key"),
        Index("ix_strategy_memory_category_reliability", "category", "reliability_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    memory_key: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(100), index=True)
    lesson: Mapped[str] = mapped_column(Text, default="")
    conditions: Mapped[dict] = mapped_column(JsonType, default=dict)
    reliability_score: Mapped[float] = mapped_column(Float, default=50.0, index=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    positive_count: Mapped[int] = mapped_column(Integer, default=0)
    negative_count: Mapped[int] = mapped_column(Integer, default=0)
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (Index("ix_model_versions_active_created", "is_active", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    model_name: Mapped[str] = mapped_column(String(160), default="BLUM Learning Loop", index=True)
    weights: Mapped[dict] = mapped_column(JsonType, default=dict)
    previous_weights: Mapped[dict] = mapped_column(JsonType, default=dict)
    training_window: Mapped[dict] = mapped_column(JsonType, default=dict)
    validation_metrics: Mapped[dict] = mapped_column(JsonType, default=dict)
    anti_overfitting_report: Mapped[dict] = mapped_column(JsonType, default=dict)
    change_log: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class LearningMetric(Base):
    __tablename__ = "learning_metrics"
    __table_args__ = (Index("ix_learning_metrics_name_timeframe_created", "metric_name", "timeframe", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_name: Mapped[str] = mapped_column(String(120), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), default="all", index=True)
    market_regime: Mapped[str] = mapped_column(String(120), default="all", index=True)
    metric_value: Mapped[float | None] = mapped_column(Float)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class MarketRegimeSnapshot(Base):
    __tablename__ = "market_regime_snapshots"
    __table_args__ = (Index("ix_market_regime_snapshots_date_created", "date", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[datetime] = mapped_column(Date, index=True)
    regime_primary: Mapped[str] = mapped_column(String(80), default="range_bound", index=True)
    regime_secondary: Mapped[str] = mapped_column(String(80), default="low_volatility", index=True)
    volatility_state: Mapped[str] = mapped_column(String(80), default="normal", index=True)
    breadth_state: Mapped[str] = mapped_column(String(80), default="unknown", index=True)
    risk_appetite_score: Mapped[float] = mapped_column(Float, default=50.0, index=True)
    sector_rotation_score: Mapped[float] = mapped_column(Float, default=50.0, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    data_sources: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class SetupLibrary(Base):
    __tablename__ = "setup_library"
    __table_args__ = (
        UniqueConstraint("setup_type", name="uq_setup_library_setup_type"),
        Index("ix_setup_library_quality_reliability", "setup_quality_score", "historical_reliability"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    setup_type: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    setup_quality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    setup_maturity: Mapped[str] = mapped_column(String(80), default="developing", index=True)
    required_confirmation: Mapped[str] = mapped_column(Text, default="")
    invalidation_logic: Mapped[str] = mapped_column(Text, default="")
    best_timeframe: Mapped[str] = mapped_column(String(80), default="short/medium", index=True)
    historical_reliability: Mapped[float] = mapped_column(Float, default=50.0, index=True)
    regime_sensitivity: Mapped[dict] = mapped_column(JsonType, default=dict)
    common_failure_modes: Mapped[dict] = mapped_column(JsonType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class SniperScore(Base):
    __tablename__ = "sniper_scores"
    __table_args__ = (Index("ix_sniper_scores_ticker_created", "ticker", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    setup_type: Mapped[str] = mapped_column(String(100), default="avoid_no_edge", index=True)
    sniper_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    actionability: Mapped[str] = mapped_column(String(80), default="avoid", index=True)
    components: Mapped[dict] = mapped_column(JsonType, default=dict)
    explanation: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    data_quality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")


class TradePlan(Base):
    __tablename__ = "trade_plans"
    __table_args__ = (Index("ix_trade_plans_ticker_created", "ticker", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    sniper_score_id: Mapped[int | None] = mapped_column(ForeignKey("sniper_scores.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    setup_type: Mapped[str] = mapped_column(String(100), index=True)
    actionability: Mapped[str] = mapped_column(String(80), default="watch", index=True)
    timeframe: Mapped[str] = mapped_column(String(80), default="short/medium", index=True)
    entry_zone: Mapped[dict] = mapped_column(JsonType, default=dict)
    entry_trigger: Mapped[str] = mapped_column(Text, default="")
    confirmation_condition: Mapped[str] = mapped_column(Text, default="")
    invalidation_level: Mapped[float | None] = mapped_column(Float)
    stop_logic: Mapped[str] = mapped_column(Text, default="")
    target_1: Mapped[float | None] = mapped_column(Float)
    target_2: Mapped[float | None] = mapped_column(Float)
    trailing_exit_logic: Mapped[str] = mapped_column(Text, default="")
    partial_exit_logic: Mapped[str] = mapped_column(Text, default="")
    no_trade_conditions: Mapped[dict] = mapped_column(JsonType, default=dict)
    expected_holding_period: Mapped[str] = mapped_column(String(80), default="")
    risk_reward_estimate: Mapped[dict] = mapped_column(JsonType, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    historical_setup_reliability: Mapped[float] = mapped_column(Float, default=50.0)
    disclaimer: Mapped[str] = mapped_column(Text, default="Informational trading scenario, not financial advice.")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")
    sniper_score = relationship("SniperScore")


class TradePlanOutcome(Base):
    __tablename__ = "trade_plan_outcomes"
    __table_args__ = (Index("ix_trade_plan_outcomes_ticker_timeframe", "ticker", "timeframe"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_plan_id: Mapped[int | None] = mapped_column(ForeignKey("trade_plans.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    setup_type: Mapped[str] = mapped_column(String(100), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), default="short", index=True)
    entry_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    exit_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    entry_price: Mapped[float | None] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float)
    realized_r_multiple: Mapped[float | None] = mapped_column(Float, index=True)
    max_adverse_excursion: Mapped[float | None] = mapped_column(Float)
    max_favorable_excursion: Mapped[float | None] = mapped_column(Float)
    outcome_label: Mapped[str] = mapped_column(String(80), default="inconclusive", index=True)
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    trade_plan = relationship("TradePlan")


class ExecutionSimulation(Base):
    __tablename__ = "execution_simulations"
    __table_args__ = (Index("ix_execution_simulations_ticker_created", "ticker", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_plan_id: Mapped[int | None] = mapped_column(ForeignKey("trade_plans.id", ondelete="SET NULL"), index=True)
    prediction_id: Mapped[int | None] = mapped_column(ForeignKey("historical_predictions.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    setup_type: Mapped[str] = mapped_column(String(100), index=True)
    simulation_mode: Mapped[str] = mapped_column(String(80), default="historical_trigger", index=True)
    entry_model: Mapped[str] = mapped_column(String(80), default="conditional", index=True)
    exit_model: Mapped[str] = mapped_column(String(80), default="risk_managed", index=True)
    realized_r_multiple: Mapped[float | None] = mapped_column(Float, index=True)
    max_adverse_excursion: Mapped[float | None] = mapped_column(Float)
    max_favorable_excursion: Mapped[float | None] = mapped_column(Float)
    time_in_trade: Mapped[int | None] = mapped_column(Integer)
    stop_hit: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    target_hit: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    trailing_exit_hit: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    missed_entry: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    false_breakout: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    failed_confirmation: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    opportunity_cost: Mapped[float | None] = mapped_column(Float)
    simulation_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    trade_plan = relationship("TradePlan")
    prediction = relationship("HistoricalPrediction")


class RMultipleMetric(Base):
    __tablename__ = "r_multiple_metrics"
    __table_args__ = (
        UniqueConstraint("setup_type", "timeframe", "market_regime", "sector", name="uq_r_metric_setup_timeframe_regime_sector"),
        Index("ix_r_multiple_metrics_expectancy", "expectancy_r"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    setup_type: Mapped[str] = mapped_column(String(100), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), default="all", index=True)
    market_regime: Mapped[str] = mapped_column(String(80), default="all", index=True)
    sector: Mapped[str] = mapped_column(String(120), default="all", index=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    hit_rate: Mapped[float | None] = mapped_column(Float)
    average_r: Mapped[float | None] = mapped_column(Float)
    median_r: Mapped[float | None] = mapped_column(Float)
    max_drawdown_r: Mapped[float | None] = mapped_column(Float)
    profit_factor: Mapped[float | None] = mapped_column(Float)
    payoff_ratio: Mapped[float | None] = mapped_column(Float)
    expectancy_r: Mapped[float | None] = mapped_column(Float, index=True)
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class SignalReliabilityMatrix(Base):
    __tablename__ = "signal_reliability_matrix"
    __table_args__ = (
        UniqueConstraint("signal_name", "setup_type", "timeframe", "sector", "market_regime", "volatility_state", "asset_class", "liquidity_bucket", name="uq_signal_reliability_context"),
        Index("ix_signal_reliability_matrix_score", "reliability_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_name: Mapped[str] = mapped_column(String(120), index=True)
    setup_type: Mapped[str] = mapped_column(String(100), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), default="all", index=True)
    sector: Mapped[str] = mapped_column(String(120), default="all", index=True)
    market_regime: Mapped[str] = mapped_column(String(80), default="all", index=True)
    volatility_state: Mapped[str] = mapped_column(String(80), default="all", index=True)
    asset_class: Mapped[str] = mapped_column(String(40), default="all", index=True)
    liquidity_bucket: Mapped[str] = mapped_column(String(80), default="all", index=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    false_positive_count: Mapped[int] = mapped_column(Integer, default=0)
    average_r: Mapped[float | None] = mapped_column(Float)
    expectancy_r: Mapped[float | None] = mapped_column(Float, index=True)
    reliability_score: Mapped[float] = mapped_column(Float, default=50.0, index=True)
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class NoTradeDecision(Base):
    __tablename__ = "no_trade_decisions"
    __table_args__ = (Index("ix_no_trade_decisions_ticker_created", "ticker", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    trade_plan_id: Mapped[int | None] = mapped_column(ForeignKey("trade_plans.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    setup_type: Mapped[str] = mapped_column(String(100), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(40), default="medium", index=True)
    conditions: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")
    trade_plan = relationship("TradePlan")


class ExitSignal(Base):
    __tablename__ = "exit_signals"
    __table_args__ = (Index("ix_exit_signals_ticker_created", "ticker", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), index=True)
    trade_plan_id: Mapped[int | None] = mapped_column(ForeignKey("trade_plans.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    exit_type: Mapped[str] = mapped_column(String(100), index=True)
    action: Mapped[str] = mapped_column(String(80), default="hold_review", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    asset = relationship("Asset")
    trade_plan = relationship("TradePlan")


class PortfolioRiskContext(Base):
    __tablename__ = "portfolio_risk_context"
    __table_args__ = (Index("ix_portfolio_risk_context_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    context_name: Mapped[str] = mapped_column(String(120), default="default_research_book", index=True)
    sector_concentration: Mapped[dict] = mapped_column(JsonType, default=dict)
    factor_concentration: Mapped[dict] = mapped_column(JsonType, default=dict)
    correlation: Mapped[dict] = mapped_column(JsonType, default=dict)
    beta: Mapped[dict] = mapped_column(JsonType, default=dict)
    volatility_contribution: Mapped[dict] = mapped_column(JsonType, default=dict)
    overlapping_etf_exposure: Mapped[dict] = mapped_column(JsonType, default=dict)
    max_simultaneous_setups: Mapped[int] = mapped_column(Integer, default=8)
    risk_per_theme: Mapped[dict] = mapped_column(JsonType, default=dict)
    risk_per_regime: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class TradingGame(Base):
    __tablename__ = "trading_games"
    __table_args__ = (Index("ix_trading_games_status_started", "status", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    mode: Mapped[str] = mapped_column(String(80), default="paper_pl_learning", index=True)
    starting_capital: Mapped[float] = mapped_column(Float, default=100.0)
    current_capital: Mapped[float] = mapped_column(Float, default=100.0, index=True)
    cash: Mapped[float] = mapped_column(Float, default=100.0)
    exposure: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pl: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pl: Mapped[float] = mapped_column(Float, default=0.0)
    peak_capital: Mapped[float] = mapped_column(Float, default=100.0)
    max_drawdown: Mapped[float] = mapped_column(Float, default=0.0)
    benchmark_ticker: Mapped[str] = mapped_column(String(32), default="SPY", index=True)
    benchmark_start_price: Mapped[float | None] = mapped_column(Float)
    benchmark_end_price: Mapped[float | None] = mapped_column(Float)
    benchmark_return: Mapped[float | None] = mapped_column(Float)
    alpha: Mapped[float | None] = mapped_column(Float)
    beta: Mapped[float | None] = mapped_column(Float)
    trade_count: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[float | None] = mapped_column(Float)
    expectancy_r: Mapped[float | None] = mapped_column(Float)
    profit_factor: Mapped[float | None] = mapped_column(Float)
    average_r: Mapped[float | None] = mapped_column(Float)
    sharpe: Mapped[float | None] = mapped_column(Float)
    sortino: Mapped[float | None] = mapped_column(Float)
    risk_per_trade: Mapped[float] = mapped_column(Float, default=1.0)
    risk_of_ruin: Mapped[float | None] = mapped_column(Float)
    max_consecutive_losses: Mapped[int] = mapped_column(Integer, default=0)
    time_to_double_days: Mapped[int | None] = mapped_column(Integer)
    time_to_ruin_days: Mapped[int | None] = mapped_column(Integer)
    configuration: Mapped[dict] = mapped_column(JsonType, default=dict)
    failure_report: Mapped[dict] = mapped_column(JsonType, default=dict)
    success_report: Mapped[dict] = mapped_column(JsonType, default=dict)
    lessons: Mapped[dict] = mapped_column(JsonType, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class TradingGameTrade(Base):
    __tablename__ = "trading_game_trades"
    __table_args__ = (Index("ix_trading_game_trades_game_created", "game_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("trading_games.id", ondelete="CASCADE"), index=True)
    execution_simulation_id: Mapped[int | None] = mapped_column(ForeignKey("execution_simulations.id", ondelete="SET NULL"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    setup_type: Mapped[str] = mapped_column(String(100), index=True)
    timeframe: Mapped[str] = mapped_column(String(40), default="daily", index=True)
    decision_state: Mapped[str] = mapped_column(String(80), default="wait_for_trigger", index=True)
    entry_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    exit_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    entry_price: Mapped[float | None] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float)
    position_size: Mapped[float] = mapped_column(Float, default=0.0)
    risk_amount: Mapped[float] = mapped_column(Float, default=0.0)
    risk_percent: Mapped[float] = mapped_column(Float, default=0.0)
    realized_r_multiple: Mapped[float | None] = mapped_column(Float, index=True)
    realized_pl: Mapped[float] = mapped_column(Float, default=0.0)
    capital_before: Mapped[float] = mapped_column(Float, default=0.0)
    capital_after: Mapped[float] = mapped_column(Float, default=0.0)
    stop_hit: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    target_hit: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    missed_entry: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    false_breakout: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    slippage_bps: Mapped[float] = mapped_column(Float, default=8.0)
    spread_bps: Mapped[float] = mapped_column(Float, default=6.0)
    reproducibility_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    benchmark_return: Mapped[float | None] = mapped_column(Float)
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    game = relationship("TradingGame")
    execution_simulation = relationship("ExecutionSimulation")


class TradingGameEquityCurve(Base):
    __tablename__ = "trading_game_equity_curve"
    __table_args__ = (Index("ix_trading_game_equity_game_date", "game_id", "equity_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("trading_games.id", ondelete="CASCADE"), index=True)
    equity_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    equity: Mapped[float] = mapped_column(Float, default=100.0, index=True)
    cash: Mapped[float] = mapped_column(Float, default=100.0)
    exposure: Mapped[float] = mapped_column(Float, default=0.0)
    drawdown: Mapped[float] = mapped_column(Float, default=0.0)
    benchmark_equity: Mapped[float | None] = mapped_column(Float)
    benchmark_return: Mapped[float | None] = mapped_column(Float)
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    game = relationship("TradingGame")


class TradingGameFailure(Base):
    __tablename__ = "trading_game_failures"
    __table_args__ = (Index("ix_trading_game_failures_game_created", "game_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int | None] = mapped_column(ForeignKey("trading_games.id", ondelete="SET NULL"), index=True)
    category: Mapped[str] = mapped_column(String(100), index=True)
    severity: Mapped[str] = mapped_column(String(40), default="medium", index=True)
    report: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    game = relationship("TradingGame")


class CapitalManagementLesson(Base):
    __tablename__ = "capital_management_lessons"
    __table_args__ = (Index("ix_capital_management_lessons_category_updated", "category", "updated_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(100), index=True)
    lesson: Mapped[str] = mapped_column(Text, default="")
    reliability_score: Mapped[float] = mapped_column(Float, default=50.0, index=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
