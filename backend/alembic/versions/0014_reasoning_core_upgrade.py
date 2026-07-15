from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0014_reasoning_core_upgrade"
down_revision = "0013_trading_game_engine"
branch_labels = None
depends_on = None


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "thesis_lifecycle_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("knowledge_record_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("previous_status", sa.String(length=40), nullable=False),
        sa.Column("new_status", sa.String(length=40), nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("conviction_score", sa.Float(), nullable=False),
        sa.Column("outcome_summary", json_type, nullable=False),
        sa.Column("evidence_delta", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["knowledge_record_id"], ["blum_knowledge_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name in ["knowledge_record_id", "ticker", "previous_status", "new_status", "confidence", "conviction_score", "created_at"]:
        op.create_index(f"ix_thesis_lifecycle_events_{name}", "thesis_lifecycle_events", [name])
    op.create_index("ix_thesis_lifecycle_events_ticker_status", "thesis_lifecycle_events", ["ticker", "new_status"])
    op.create_index("ix_thesis_lifecycle_events_record_created", "thesis_lifecycle_events", ["knowledge_record_id", "created_at"])

    op.create_table(
        "model_reliability_matrix",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("engine_name", sa.String(length=100), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=False),
        sa.Column("market_regime", sa.String(length=120), nullable=False),
        sa.Column("timeframe", sa.String(length=40), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("correct_count", sa.Integer(), nullable=False),
        sa.Column("wrong_count", sa.Integer(), nullable=False),
        sa.Column("neutral_count", sa.Integer(), nullable=False),
        sa.Column("inconclusive_count", sa.Integer(), nullable=False),
        sa.Column("reliability_score", sa.Float(), nullable=False),
        sa.Column("weight_adjustment", sa.Float(), nullable=False),
        sa.Column("calibration_error", sa.Float(), nullable=True),
        sa.Column("evidence", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("engine_name", "sector", "market_regime", "timeframe", name="uq_model_reliability_context"),
    )
    for name in ["engine_name", "sector", "market_regime", "timeframe", "sample_count", "reliability_score", "created_at", "updated_at"]:
        op.create_index(f"ix_model_reliability_matrix_{name}", "model_reliability_matrix", [name])
    op.create_index("ix_model_reliability_matrix_score", "model_reliability_matrix", ["reliability_score"])
    op.create_index("ix_model_reliability_matrix_engine_updated", "model_reliability_matrix", ["engine_name", "updated_at"])

    op.create_table(
        "confidence_calibration_buckets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bucket_label", sa.String(length=40), nullable=False),
        sa.Column("min_confidence", sa.Float(), nullable=False),
        sa.Column("max_confidence", sa.Float(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("average_confidence", sa.Float(), nullable=False),
        sa.Column("empirical_success_rate", sa.Float(), nullable=False),
        sa.Column("calibration_error", sa.Float(), nullable=False),
        sa.Column("suggested_adjustment", sa.Float(), nullable=False),
        sa.Column("evidence", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bucket_label", name="uq_confidence_calibration_bucket_label"),
    )
    for name in ["bucket_label", "sample_count", "calibration_error", "created_at", "updated_at"]:
        op.create_index(f"ix_confidence_calibration_buckets_{name}", "confidence_calibration_buckets", [name])
    op.create_index("ix_confidence_calibration_buckets_error", "confidence_calibration_buckets", ["calibration_error"])
    op.create_index("ix_confidence_calibration_buckets_updated", "confidence_calibration_buckets", ["updated_at"])

    op.create_table(
        "meta_learning_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("engine_name", sa.String(length=100), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=True),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("lesson", sa.Text(), nullable=False),
        sa.Column("root_cause", sa.String(length=160), nullable=False),
        sa.Column("proposed_change", json_type, nullable=False),
        sa.Column("trigger_payload", json_type, nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for name in ["event_type", "engine_name", "ticker", "severity", "root_cause", "status", "created_at"]:
        op.create_index(f"ix_meta_learning_events_{name}", "meta_learning_events", [name])
    op.create_index("ix_meta_learning_events_type_created", "meta_learning_events", ["event_type", "created_at"])
    op.create_index("ix_meta_learning_events_engine_status", "meta_learning_events", ["engine_name", "status"])


def downgrade() -> None:
    op.drop_table("meta_learning_events")
    op.drop_table("confidence_calibration_buckets")
    op.drop_table("model_reliability_matrix")
    op.drop_table("thesis_lifecycle_events")
