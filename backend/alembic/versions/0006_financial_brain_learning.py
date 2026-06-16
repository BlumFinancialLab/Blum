from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_financial_brain_learning"
down_revision = "0005_strategic_intel"
branch_labels = None
depends_on = None


json_type = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "signal_evaluations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("signal_id", sa.Integer(), nullable=True),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=False),
        sa.Column("signal_type", sa.String(length=80), nullable=False),
        sa.Column("expected_direction", sa.String(length=40), nullable=False),
        sa.Column("time_horizon", sa.String(length=80), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("signal_created_at", sa.DateTime(), nullable=False),
        sa.Column("initial_confidence", sa.Float(), nullable=False),
        sa.Column("initial_sentiment", sa.Float(), nullable=False),
        sa.Column("initial_momentum", sa.Float(), nullable=False),
        sa.Column("news_evidence", json_type, nullable=False),
        sa.Column("price_at_signal", sa.Float(), nullable=True),
        sa.Column("price_after_horizon", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("max_upside", sa.Float(), nullable=True),
        sa.Column("realized_return", sa.Float(), nullable=True),
        sa.Column("volatility_after_signal", sa.Float(), nullable=True),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("explanation_quality_score", sa.Float(), nullable=False),
        sa.Column("data_quality_score", sa.Float(), nullable=False),
        sa.Column("evaluation_payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["signal_id"], ["signal_snapshots.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("signal_id", "horizon_days", name="uq_signal_evaluation_signal_horizon"),
    )
    op.create_index("ix_signal_evaluations_signal_id", "signal_evaluations", ["signal_id"])
    op.create_index("ix_signal_evaluations_asset_id", "signal_evaluations", ["asset_id"])
    op.create_index("ix_signal_evaluations_ticker", "signal_evaluations", ["ticker"])
    op.create_index("ix_signal_evaluations_sector", "signal_evaluations", ["sector"])
    op.create_index("ix_signal_evaluations_signal_type", "signal_evaluations", ["signal_type"])
    op.create_index("ix_signal_evaluations_expected_direction", "signal_evaluations", ["expected_direction"])
    op.create_index("ix_signal_evaluations_horizon_days", "signal_evaluations", ["horizon_days"])
    op.create_index("ix_signal_evaluations_signal_created_at", "signal_evaluations", ["signal_created_at"])
    op.create_index("ix_signal_evaluations_initial_confidence", "signal_evaluations", ["initial_confidence"])
    op.create_index("ix_signal_evaluations_realized_return", "signal_evaluations", ["realized_return"])
    op.create_index("ix_signal_evaluations_outcome", "signal_evaluations", ["outcome"])
    op.create_index("ix_signal_evaluations_created_at", "signal_evaluations", ["created_at"])
    op.create_index("ix_signal_evaluations_ticker_horizon", "signal_evaluations", ["ticker", "horizon_days"])

    op.create_table(
        "signal_outcomes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("signal_id", sa.Integer(), nullable=True),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=False),
        sa.Column("signal_type", sa.String(length=80), nullable=False),
        sa.Column("signal_created_at", sa.DateTime(), nullable=False),
        sa.Column("initial_score", sa.Float(), nullable=False),
        sa.Column("initial_confidence", sa.Float(), nullable=False),
        sa.Column("final_outcome", sa.String(length=40), nullable=False),
        sa.Column("best_horizon_days", sa.Integer(), nullable=True),
        sa.Column("worst_horizon_days", sa.Integer(), nullable=True),
        sa.Column("average_realized_return", sa.Float(), nullable=True),
        sa.Column("outcome_payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["signal_id"], ["signal_snapshots.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("signal_id", name="uq_signal_outcome_signal"),
    )
    op.create_index("ix_signal_outcomes_signal_id", "signal_outcomes", ["signal_id"])
    op.create_index("ix_signal_outcomes_asset_id", "signal_outcomes", ["asset_id"])
    op.create_index("ix_signal_outcomes_ticker", "signal_outcomes", ["ticker"])
    op.create_index("ix_signal_outcomes_sector", "signal_outcomes", ["sector"])
    op.create_index("ix_signal_outcomes_signal_type", "signal_outcomes", ["signal_type"])
    op.create_index("ix_signal_outcomes_signal_created_at", "signal_outcomes", ["signal_created_at"])
    op.create_index("ix_signal_outcomes_final_outcome", "signal_outcomes", ["final_outcome"])
    op.create_index("ix_signal_outcomes_created_at", "signal_outcomes", ["created_at"])
    op.create_index("ix_signal_outcomes_ticker_created", "signal_outcomes", ["ticker", "signal_created_at"])

    op.create_table(
        "model_weight_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=80), nullable=False),
        sa.Column("weights", json_type, nullable=False),
        sa.Column("previous_weights", json_type, nullable=False),
        sa.Column("calibration_metrics", json_type, nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version"),
    )
    op.create_index("ix_model_weight_versions_version", "model_weight_versions", ["version"])
    op.create_index("ix_model_weight_versions_is_active", "model_weight_versions", ["is_active"])
    op.create_index("ix_model_weight_versions_created_at", "model_weight_versions", ["created_at"])
    op.create_index("ix_model_weight_versions_active_created", "model_weight_versions", ["is_active", "created_at"])

    op.create_table(
        "learning_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=260), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_learning_events_event_type", "learning_events", ["event_type"])
    op.create_index("ix_learning_events_severity", "learning_events", ["severity"])
    op.create_index("ix_learning_events_created_at", "learning_events", ["created_at"])
    op.create_index("ix_learning_events_type_created", "learning_events", ["event_type", "created_at"])

    op.create_table(
        "historical_similarity_cases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("reference_signal_id", sa.Integer(), nullable=True),
        sa.Column("case_date", sa.Date(), nullable=True),
        sa.Column("similarity_score", sa.Float(), nullable=False),
        sa.Column("features", json_type, nullable=False),
        sa.Column("outcome_summary", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reference_signal_id"], ["signal_snapshots.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_historical_similarity_cases_asset_id", "historical_similarity_cases", ["asset_id"])
    op.create_index("ix_historical_similarity_cases_ticker", "historical_similarity_cases", ["ticker"])
    op.create_index("ix_historical_similarity_cases_reference_signal_id", "historical_similarity_cases", ["reference_signal_id"])
    op.create_index("ix_historical_similarity_cases_case_date", "historical_similarity_cases", ["case_date"])
    op.create_index("ix_historical_similarity_cases_similarity_score", "historical_similarity_cases", ["similarity_score"])
    op.create_index("ix_historical_similarity_cases_created_at", "historical_similarity_cases", ["created_at"])
    op.create_index("ix_similarity_cases_ticker_created", "historical_similarity_cases", ["ticker", "created_at"])

    op.create_table(
        "confidence_adjustments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=True),
        sa.Column("sector", sa.String(length=120), nullable=True),
        sa.Column("signal_type", sa.String(length=80), nullable=True),
        sa.Column("base_confidence", sa.Float(), nullable=False),
        sa.Column("adjusted_confidence", sa.Float(), nullable=False),
        sa.Column("adjustment", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_confidence_adjustments_asset_id", "confidence_adjustments", ["asset_id"])
    op.create_index("ix_confidence_adjustments_ticker", "confidence_adjustments", ["ticker"])
    op.create_index("ix_confidence_adjustments_sector", "confidence_adjustments", ["sector"])
    op.create_index("ix_confidence_adjustments_signal_type", "confidence_adjustments", ["signal_type"])
    op.create_index("ix_confidence_adjustments_adjustment", "confidence_adjustments", ["adjustment"])
    op.create_index("ix_confidence_adjustments_created_at", "confidence_adjustments", ["created_at"])
    op.create_index("ix_confidence_adjustments_ticker_created", "confidence_adjustments", ["ticker", "created_at"])

    op.create_table(
        "source_reliability_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=160), nullable=False),
        sa.Column("article_count", sa.Integer(), nullable=False),
        sa.Column("linked_signal_count", sa.Integer(), nullable=False),
        sa.Column("correct_signal_rate", sa.Float(), nullable=True),
        sa.Column("false_positive_rate", sa.Float(), nullable=True),
        sa.Column("reliability_score", sa.Float(), nullable=False),
        sa.Column("evidence", json_type, nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", name="uq_source_reliability_source"),
    )
    op.create_index("ix_source_reliability_scores_source", "source_reliability_scores", ["source"])
    op.create_index("ix_source_reliability_scores_reliability_score", "source_reliability_scores", ["reliability_score"])
    op.create_index("ix_source_reliability_scores_updated_at", "source_reliability_scores", ["updated_at"])
    op.create_index("ix_source_reliability_scores_created_at", "source_reliability_scores", ["created_at"])
    op.create_index("ix_source_reliability_score", "source_reliability_scores", ["reliability_score"])

    op.create_table(
        "ticker_accuracy_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("evaluated_signals", sa.Integer(), nullable=False),
        sa.Column("correct_rate", sa.Float(), nullable=True),
        sa.Column("neutral_rate", sa.Float(), nullable=True),
        sa.Column("average_return", sa.Float(), nullable=True),
        sa.Column("average_drawdown", sa.Float(), nullable=True),
        sa.Column("accuracy_score", sa.Float(), nullable=False),
        sa.Column("profile_payload", json_type, nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", name="uq_ticker_accuracy_profile"),
    )
    op.create_index("ix_ticker_accuracy_profiles_asset_id", "ticker_accuracy_profiles", ["asset_id"])
    op.create_index("ix_ticker_accuracy_profiles_ticker", "ticker_accuracy_profiles", ["ticker"])
    op.create_index("ix_ticker_accuracy_profiles_accuracy_score", "ticker_accuracy_profiles", ["accuracy_score"])
    op.create_index("ix_ticker_accuracy_profiles_score", "ticker_accuracy_profiles", ["accuracy_score"])

    op.create_table(
        "sector_accuracy_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=False),
        sa.Column("evaluated_signals", sa.Integer(), nullable=False),
        sa.Column("correct_rate", sa.Float(), nullable=True),
        sa.Column("neutral_rate", sa.Float(), nullable=True),
        sa.Column("average_return", sa.Float(), nullable=True),
        sa.Column("average_drawdown", sa.Float(), nullable=True),
        sa.Column("accuracy_score", sa.Float(), nullable=False),
        sa.Column("profile_payload", json_type, nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sector", name="uq_sector_accuracy_profile"),
    )
    op.create_index("ix_sector_accuracy_profiles_sector", "sector_accuracy_profiles", ["sector"])
    op.create_index("ix_sector_accuracy_profiles_accuracy_score", "sector_accuracy_profiles", ["accuracy_score"])
    op.create_index("ix_sector_accuracy_profiles_score", "sector_accuracy_profiles", ["accuracy_score"])


def downgrade() -> None:
    op.drop_table("sector_accuracy_profiles")
    op.drop_table("ticker_accuracy_profiles")
    op.drop_table("source_reliability_scores")
    op.drop_table("confidence_adjustments")
    op.drop_table("historical_similarity_cases")
    op.drop_table("learning_events")
    op.drop_table("model_weight_versions")
    op.drop_table("signal_outcomes")
    op.drop_table("signal_evaluations")
