from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=220), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=False),
        sa.Column("industry", sa.String(length=160), nullable=False),
        sa.Column("country", sa.String(length=80), nullable=False),
        sa.Column("asset_type", sa.String(length=24), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("exchange", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_assets_ticker", "assets", ["ticker"], unique=True)
    op.create_index("ix_assets_sector", "assets", ["sector"])
    op.create_index("ix_assets_country", "assets", ["country"])
    op.create_index("ix_assets_asset_type", "assets", ["asset_type"])

    op.create_table(
        "price_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open", sa.Float()),
        sa.Column("high", sa.Float()),
        sa.Column("low", sa.Float()),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float()),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("asset_id", "date", name="uq_price_asset_date"),
    )
    op.create_index("ix_price_asset_date", "price_history", ["asset_id", "date"])

    op.create_table(
        "news_articles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=160), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime()),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("canonical_key", sa.String(length=260), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("theme_tags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("url"),
    )
    op.create_index("ix_news_articles_canonical_key", "news_articles", ["canonical_key"], unique=True)
    op.create_index("ix_news_articles_source", "news_articles", ["source"])
    op.create_index("ix_news_articles_published_at", "news_articles", ["published_at"])

    op.create_table(
        "news_asset_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("news_articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relevance_score", sa.Float(), nullable=False),
        sa.UniqueConstraint("article_id", "asset_id", name="uq_news_asset"),
    )
    op.create_index("ix_news_asset_links_article_id", "news_asset_links", ["article_id"])
    op.create_index("ix_news_asset_links_asset_id", "news_asset_links", ["asset_id"])

    op.create_table(
        "sentiment_analysis",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("news_articles.id", ondelete="CASCADE")),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE")),
        sa.Column("model_name", sa.String(length=120), nullable=False),
        sa.Column("label", sa.String(length=40), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("baseline_vader", sa.Float()),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sentiment_analysis_article_id", "sentiment_analysis", ["article_id"])
    op.create_index("ix_sentiment_analysis_asset_id", "sentiment_analysis", ["asset_id"])

    op.create_table(
        "technical_indicators",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("indicators", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("asset_id", "date", name="uq_indicator_asset_date"),
    )
    op.create_index("ix_technical_indicators_asset_id", "technical_indicators", ["asset_id"])
    op.create_index("ix_technical_indicators_date", "technical_indicators", ["date"])

    op.create_table(
        "signal_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("classification", sa.String(length=80), nullable=False),
        sa.Column("blum_score", sa.Float(), nullable=False),
        sa.Column("risk_level", sa.String(length=40), nullable=False),
        sa.Column("time_horizon", sa.String(length=80), nullable=False),
        sa.Column("score_breakdown", sa.JSON(), nullable=False),
        sa.Column("technical_summary", sa.JSON(), nullable=False),
        sa.Column("narrative_summary", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("watch_points", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_signal_snapshots_asset_id", "signal_snapshots", ["asset_id"])
    op.create_index("ix_signal_snapshots_ticker", "signal_snapshots", ["ticker"])
    op.create_index("ix_signal_snapshots_classification", "signal_snapshots", ["classification"])
    op.create_index("ix_signal_snapshots_blum_score", "signal_snapshots", ["blum_score"])
    op.create_index("ix_signal_snapshots_risk_level", "signal_snapshots", ["risk_level"])
    op.create_index("ix_signal_snapshots_created_at", "signal_snapshots", ["created_at"])

    op.create_table(
        "theme_clusters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("article_ids", sa.JSON(), nullable=False),
        sa.Column("asset_tickers", sa.JSON(), nullable=False),
        sa.Column("centroid", sa.JSON(), nullable=False),
        sa.Column("sentiment_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_theme_clusters_label", "theme_clusters", ["label"])
    op.create_index("ix_theme_clusters_created_at", "theme_clusters", ["created_at"])

    op.create_table(
        "embedding_vectors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("news_articles.id", ondelete="CASCADE")),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE")),
        sa.Column("model_name", sa.String(length=160), nullable=False),
        sa.Column("vector", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_embedding_vectors_article_id", "embedding_vectors", ["article_id"])
    op.create_index("ix_embedding_vectors_asset_id", "embedding_vectors", ["asset_id"])
    op.create_index("ix_embedding_vectors_model_name", "embedding_vectors", ["model_name"])

    op.create_table(
        "ai_insights",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_name", sa.String(length=160), nullable=False),
        sa.Column("insight_type", sa.String(length=80), nullable=False),
        sa.Column("structured_output", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ai_insights_asset_id", "ai_insights", ["asset_id"])
    op.create_index("ix_ai_insights_model_name", "ai_insights", ["model_name"])
    op.create_index("ix_ai_insights_created_at", "ai_insights", ["created_at"])

    op.create_table(
        "etf_trends",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("momentum_score", sa.Float(), nullable=False),
        sa.Column("thematic_score", sa.Float(), nullable=False),
        sa.Column("confirmation_score", sa.Float(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_etf_trends_asset_id", "etf_trends", ["asset_id"])
    op.create_index("ix_etf_trends_ticker", "etf_trends", ["ticker"])
    op.create_index("ix_etf_trends_category", "etf_trends", ["category"])
    op.create_index("ix_etf_trends_created_at", "etf_trends", ["created_at"])

    op.create_table(
        "backtest_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_name", sa.String(length=160), nullable=False),
        sa.Column("benchmark", sa.String(length=32), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_backtest_results_run_name", "backtest_results", ["run_name"])
    op.create_index("ix_backtest_results_created_at", "backtest_results", ["created_at"])


def downgrade() -> None:
    for table in [
        "backtest_results",
        "etf_trends",
        "ai_insights",
        "embedding_vectors",
        "theme_clusters",
        "signal_snapshots",
        "technical_indicators",
        "sentiment_analysis",
        "news_asset_links",
        "news_articles",
        "price_history",
        "assets",
    ]:
        op.drop_table(table)
