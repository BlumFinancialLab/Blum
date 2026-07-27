"""Add trading ML champion/challenger persistence.

Revision ID: 0040_trading_ml_champion
Revises: 0039_forex_hierarchical_rl
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0040_trading_ml_champion"
down_revision = "0039_forex_hierarchical_rl"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.create_table(
        "trading_ml_model_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_uid", sa.String(160), nullable=False),
        sa.Column("market_family", sa.String(32), nullable=False),
        sa.Column("algorithm", sa.String(80), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="SHADOW"),
        sa.Column("feature_schema_version", sa.String(80), nullable=False),
        sa.Column("feature_schema_hash", sa.String(64), nullable=False),
        sa.Column("dataset_hash", sa.String(64), nullable=False),
        sa.Column("evidence_lane_counts_json", JSON_TYPE, nullable=False),
        sa.Column("training_window_json", JSON_TYPE, nullable=False),
        sa.Column("validation_window_json", JSON_TYPE, nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("asset_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("regime_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("setup_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("training_metrics_json", JSON_TYPE, nullable=False),
        sa.Column("validation_metrics_json", JSON_TYPE, nullable=False),
        sa.Column("baseline_metrics_json", JSON_TYPE, nullable=False),
        sa.Column("promotion_gates_json", JSON_TYPE, nullable=False),
        sa.Column("promotion_decision", sa.String(80)),
        sa.Column("artifact_path", sa.Text(), nullable=False),
        sa.Column("artifact_sha256", sa.String(64), nullable=False),
        sa.Column("artifact_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "parent_model_version_id",
            sa.Integer(),
            sa.ForeignKey("trading_ml_model_versions.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "champion_model_version_id",
            sa.Integer(),
            sa.ForeignKey("trading_ml_model_versions.id", ondelete="SET NULL"),
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("activated_at", sa.DateTime()),
        sa.Column("degraded_at", sa.DateTime()),
        sa.Column("rolled_back_at", sa.DateTime()),
        sa.Column("warnings_json", JSON_TYPE, nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint("model_uid", name="uq_trading_ml_model_uid"),
    )
    op.create_index(
        "ix_trading_ml_models_market_status",
        "trading_ml_model_versions",
        ["market_family", "status"],
    )

    op.create_table(
        "trading_ml_training_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_uid", sa.String(160), nullable=False, unique=True),
        sa.Column("market_family", sa.String(32), nullable=False),
        sa.Column("trigger", sa.String(80), nullable=False),
        sa.Column("cursor_json", JSON_TYPE, nullable=False),
        sa.Column("resource_limits_json", JSON_TYPE, nullable=False),
        sa.Column("rows_considered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_accepted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejection_reasons_json", JSON_TYPE, nullable=False),
        sa.Column("split_metadata_json", JSON_TYPE, nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="RUNNING"),
        sa.Column("duration_seconds", sa.Float()),
        sa.Column(
            "candidate_model_version_id",
            sa.Integer(),
            sa.ForeignKey("trading_ml_model_versions.id", ondelete="SET NULL"),
        ),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
    )
    op.create_index(
        "ix_trading_ml_runs_market_started",
        "trading_ml_training_runs",
        ["market_family", "started_at"],
    )

    op.create_table(
        "trading_ml_predictions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_object_type", sa.String(80), nullable=False),
        sa.Column("source_object_id", sa.String(160), nullable=False),
        sa.Column(
            "model_version_id",
            sa.Integer(),
            sa.ForeignKey("trading_ml_model_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("market_family", sa.String(32), nullable=False),
        sa.Column("feature_hash", sa.String(64), nullable=False),
        sa.Column("probability_positive_r", sa.Float()),
        sa.Column("predicted_net_r", sa.Float()),
        sa.Column("uncertainty", sa.Float()),
        sa.Column("baseline_output_json", JSON_TYPE, nullable=False),
        sa.Column("proposed_confidence_adjustment", sa.Float(), nullable=False, server_default="0"),
        sa.Column("applied_confidence_adjustment", sa.Float(), nullable=False, server_default="0"),
        sa.Column("guardrails_json", JSON_TYPE, nullable=False),
        sa.Column("explanation_json", JSON_TYPE, nullable=False),
        sa.Column("realized_outcome_json", JSON_TYPE, nullable=False),
        sa.Column("evaluated_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "source_object_type",
            "source_object_id",
            "model_version_id",
            name="uq_trading_ml_prediction_source_model",
        ),
    )
    op.create_index(
        "ix_trading_ml_predictions_market_created",
        "trading_ml_predictions",
        ["market_family", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("trading_ml_predictions")
    op.drop_table("trading_ml_training_runs")
    op.drop_table("trading_ml_model_versions")
