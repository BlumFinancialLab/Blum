from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_chart_vision"
down_revision = "0006_financial_brain_learning"
branch_labels = None
depends_on = None


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "chart_analyses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=True),
        sa.Column("timeframe", sa.String(length=40), nullable=False),
        sa.Column("period", sa.String(length=40), nullable=False),
        sa.Column("image_hash", sa.String(length=128), nullable=True),
        sa.Column("model_used", sa.String(length=180), nullable=False),
        sa.Column("visual_analysis_json", json_type, nullable=False),
        sa.Column("deterministic_analysis_json", json_type, nullable=False),
        sa.Column("hybrid_analysis_json", json_type, nullable=False),
        sa.Column("chart_image", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chart_analyses_asset_id", "chart_analyses", ["asset_id"])
    op.create_index("ix_chart_analyses_ticker", "chart_analyses", ["ticker"])
    op.create_index("ix_chart_analyses_timeframe", "chart_analyses", ["timeframe"])
    op.create_index("ix_chart_analyses_period", "chart_analyses", ["period"])
    op.create_index("ix_chart_analyses_image_hash", "chart_analyses", ["image_hash"])
    op.create_index("ix_chart_analyses_model_used", "chart_analyses", ["model_used"])
    op.create_index("ix_chart_analyses_confidence", "chart_analyses", ["confidence"])
    op.create_index("ix_chart_analyses_created_at", "chart_analyses", ["created_at"])
    op.create_index("ix_chart_analyses_ticker_timeframe_created", "chart_analyses", ["ticker", "timeframe", "created_at"])

    op.create_table(
        "technical_levels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=40), nullable=False),
        sa.Column("support_levels_json", json_type, nullable=False),
        sa.Column("resistance_levels_json", json_type, nullable=False),
        sa.Column("breakout_level", sa.Float(), nullable=True),
        sa.Column("breakdown_level", sa.Float(), nullable=True),
        sa.Column("invalidation_level", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", "timeframe", name="uq_technical_levels_ticker_timeframe"),
    )
    op.create_index("ix_technical_levels_asset_id", "technical_levels", ["asset_id"])
    op.create_index("ix_technical_levels_ticker", "technical_levels", ["ticker"])
    op.create_index("ix_technical_levels_timeframe", "technical_levels", ["timeframe"])
    op.create_index("ix_technical_levels_updated_at", "technical_levels", ["updated_at"])
    op.create_index("ix_technical_levels_ticker_updated", "technical_levels", ["ticker", "updated_at"])

    op.create_table(
        "technical_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=40), nullable=False),
        sa.Column("signal_type", sa.String(length=120), nullable=False),
        sa.Column("direction", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_json", json_type, nullable=False),
        sa.Column("invalidation_level", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_technical_signals_asset_id", "technical_signals", ["asset_id"])
    op.create_index("ix_technical_signals_ticker", "technical_signals", ["ticker"])
    op.create_index("ix_technical_signals_timeframe", "technical_signals", ["timeframe"])
    op.create_index("ix_technical_signals_signal_type", "technical_signals", ["signal_type"])
    op.create_index("ix_technical_signals_direction", "technical_signals", ["direction"])
    op.create_index("ix_technical_signals_confidence", "technical_signals", ["confidence"])
    op.create_index("ix_technical_signals_created_at", "technical_signals", ["created_at"])
    op.create_index("ix_technical_signals_ticker_timeframe_created", "technical_signals", ["ticker", "timeframe", "created_at"])

    op.create_table(
        "chart_pattern_memory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=40), nullable=False),
        sa.Column("pattern_type", sa.String(length=120), nullable=False),
        sa.Column("setup_embedding", json_type, nullable=False),
        sa.Column("outcome_1d", sa.Float(), nullable=True),
        sa.Column("outcome_7d", sa.Float(), nullable=True),
        sa.Column("outcome_30d", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chart_pattern_memory_asset_id", "chart_pattern_memory", ["asset_id"])
    op.create_index("ix_chart_pattern_memory_ticker", "chart_pattern_memory", ["ticker"])
    op.create_index("ix_chart_pattern_memory_timeframe", "chart_pattern_memory", ["timeframe"])
    op.create_index("ix_chart_pattern_memory_pattern_type", "chart_pattern_memory", ["pattern_type"])
    op.create_index("ix_chart_pattern_memory_success", "chart_pattern_memory", ["success"])
    op.create_index("ix_chart_pattern_memory_created_at", "chart_pattern_memory", ["created_at"])
    op.create_index("ix_chart_pattern_memory_ticker_pattern_created", "chart_pattern_memory", ["ticker", "pattern_type", "created_at"])


def downgrade() -> None:
    op.drop_table("chart_pattern_memory")
    op.drop_table("technical_signals")
    op.drop_table("technical_levels")
    op.drop_table("chart_analyses")
