from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_accuracy_confidence_layer"
down_revision = "0003_signal_metadata"
branch_labels = None
depends_on = None


json_type = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "price_provider_checks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("provider_count", sa.Integer(), nullable=False),
        sa.Column("reference_close", sa.Float(), nullable=True),
        sa.Column("max_divergence_pct", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("observations", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "date", name="uq_price_provider_check_asset_date"),
    )
    op.create_index("ix_price_provider_checks_asset_id", "price_provider_checks", ["asset_id"])
    op.create_index("ix_price_provider_checks_ticker", "price_provider_checks", ["ticker"])
    op.create_index("ix_price_provider_checks_date", "price_provider_checks", ["date"])
    op.create_index("ix_price_provider_checks_provider_count", "price_provider_checks", ["provider_count"])
    op.create_index("ix_price_provider_checks_max_divergence_pct", "price_provider_checks", ["max_divergence_pct"])
    op.create_index("ix_price_provider_checks_status", "price_provider_checks", ["status"])
    op.create_index("ix_price_provider_checks_created_at", "price_provider_checks", ["created_at"])
    op.create_index("ix_price_provider_checks_ticker_date", "price_provider_checks", ["ticker", "date"])

    op.create_table(
        "accuracy_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=True),
        sa.Column("scope", sa.String(length=80), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("confidence_label", sa.String(length=40), nullable=False),
        sa.Column("components", json_type, nullable=False),
        sa.Column("issues", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_accuracy_snapshots_asset_id", "accuracy_snapshots", ["asset_id"])
    op.create_index("ix_accuracy_snapshots_ticker", "accuracy_snapshots", ["ticker"])
    op.create_index("ix_accuracy_snapshots_scope", "accuracy_snapshots", ["scope"])
    op.create_index("ix_accuracy_snapshots_score", "accuracy_snapshots", ["score"])
    op.create_index("ix_accuracy_snapshots_confidence_label", "accuracy_snapshots", ["confidence_label"])
    op.create_index("ix_accuracy_snapshots_created_at", "accuracy_snapshots", ["created_at"])
    op.create_index("ix_accuracy_snapshots_scope_created", "accuracy_snapshots", ["scope", "created_at"])

    op.create_table(
        "corporate_action_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("action_type", sa.String(length=80), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("details", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "action_type", "effective_date", "source", name="uq_corporate_action_event"),
    )
    op.create_index("ix_corporate_action_events_asset_id", "corporate_action_events", ["asset_id"])
    op.create_index("ix_corporate_action_events_ticker", "corporate_action_events", ["ticker"])
    op.create_index("ix_corporate_action_events_action_type", "corporate_action_events", ["action_type"])
    op.create_index("ix_corporate_action_events_effective_date", "corporate_action_events", ["effective_date"])
    op.create_index("ix_corporate_action_events_source", "corporate_action_events", ["source"])
    op.create_index("ix_corporate_action_events_created_at", "corporate_action_events", ["created_at"])
    op.create_index("ix_corporate_action_events_ticker_date", "corporate_action_events", ["ticker", "effective_date"])

    op.create_table(
        "fundamental_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=120), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("fiscal_period", sa.String(length=40), nullable=False),
        sa.Column("metrics", json_type, nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "provider", "period_end", name="uq_fundamental_asset_provider_period"),
    )
    op.create_index("ix_fundamental_snapshots_asset_id", "fundamental_snapshots", ["asset_id"])
    op.create_index("ix_fundamental_snapshots_ticker", "fundamental_snapshots", ["ticker"])
    op.create_index("ix_fundamental_snapshots_provider", "fundamental_snapshots", ["provider"])
    op.create_index("ix_fundamental_snapshots_period_end", "fundamental_snapshots", ["period_end"])
    op.create_index("ix_fundamental_snapshots_quality_score", "fundamental_snapshots", ["quality_score"])
    op.create_index("ix_fundamental_snapshots_created_at", "fundamental_snapshots", ["created_at"])
    op.create_index("ix_fundamental_snapshots_ticker_created", "fundamental_snapshots", ["ticker", "created_at"])

    op.create_table(
        "macro_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("indicator", sa.String(length=80), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("provider", sa.String(length=120), nullable=False),
        sa.Column("details", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("indicator", "date", "provider", name="uq_macro_indicator_date_provider"),
    )
    op.create_index("ix_macro_snapshots_indicator", "macro_snapshots", ["indicator"])
    op.create_index("ix_macro_snapshots_date", "macro_snapshots", ["date"])
    op.create_index("ix_macro_snapshots_provider", "macro_snapshots", ["provider"])
    op.create_index("ix_macro_snapshots_created_at", "macro_snapshots", ["created_at"])
    op.create_index("ix_macro_snapshots_indicator_created", "macro_snapshots", ["indicator", "created_at"])


def downgrade() -> None:
    op.drop_table("macro_snapshots")
    op.drop_table("fundamental_snapshots")
    op.drop_table("corporate_action_events")
    op.drop_table("accuracy_snapshots")
    op.drop_table("price_provider_checks")
