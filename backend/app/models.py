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
