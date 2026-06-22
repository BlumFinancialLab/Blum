from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0015_reasoning_precision_engines"
down_revision = "0014_reasoning_core_upgrade"
branch_labels = None
depends_on = None


json_type = postgresql.JSONB(astext_type=sa.Text())


def add_indexes(table: str, names: list[str]) -> None:
    for name in names:
        index_name = f"ix_{table}_{name}"
        if len(index_name) > 63:
            index_name = f"ix_{table[:28]}_{name[:24]}"
        op.create_index(index_name, table, [name])


def upgrade() -> None:
    op.create_table(
        "thesis_survival_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("thesis_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=False),
        sa.Column("thesis_type", sa.String(length=100), nullable=False),
        sa.Column("direction", sa.String(length=40), nullable=False),
        sa.Column("horizon", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(), nullable=False),
        sa.Column("thesis_age_days", sa.Float(), nullable=False),
        sa.Column("survival_status", sa.String(length=40), nullable=False),
        sa.Column("survival_days", sa.Float(), nullable=False),
        sa.Column("initial_confidence", sa.Float(), nullable=False),
        sa.Column("current_confidence", sa.Float(), nullable=False),
        sa.Column("confidence_decay", sa.Float(), nullable=False),
        sa.Column("max_confidence", sa.Float(), nullable=False),
        sa.Column("min_confidence", sa.Float(), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("expired_at", sa.DateTime(), nullable=True),
        sa.Column("final_return", sa.Float(), nullable=True),
        sa.Column("benchmark_return", sa.Float(), nullable=True),
        sa.Column("excess_return", sa.Float(), nullable=True),
        sa.Column("max_adverse_excursion", sa.Float(), nullable=True),
        sa.Column("max_favorable_excursion", sa.Float(), nullable=True),
        sa.Column("regime_primary", sa.String(length=120), nullable=False),
        sa.Column("regime_secondary", sa.String(length=120), nullable=False),
        sa.Column("sector_regime", sa.String(length=120), nullable=False),
        sa.Column("failure_reason", sa.String(length=180), nullable=False),
        sa.Column("survival_quality_score", sa.Float(), nullable=False),
        sa.Column("notes_json", json_type, nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["thesis_id"], ["blum_knowledge_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("thesis_id", name="uq_thesis_survival_metric_thesis"),
    )
    add_indexes(
        "thesis_survival_metrics",
        [
            "thesis_id",
            "ticker",
            "sector",
            "thesis_type",
            "direction",
            "horizon",
            "created_at",
            "evaluated_at",
            "thesis_age_days",
            "survival_status",
            "survival_days",
            "current_confidence",
            "invalidated_at",
            "completed_at",
            "expired_at",
            "excess_return",
            "regime_primary",
            "regime_secondary",
            "sector_regime",
            "failure_reason",
            "survival_quality_score",
            "updated_at",
        ],
    )
    op.create_index("ix_thesis_survival_ticker_status", "thesis_survival_metrics", ["ticker", "survival_status"])
    op.create_index("ix_thesis_survival_regime_quality", "thesis_survival_metrics", ["regime_primary", "survival_quality_score"])

    op.create_table(
        "thesis_conviction_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("thesis_id", sa.Integer(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(), nullable=False),
        sa.Column("previous_confidence", sa.Float(), nullable=False),
        sa.Column("new_confidence", sa.Float(), nullable=False),
        sa.Column("confidence_delta", sa.Float(), nullable=False),
        sa.Column("decay_score", sa.Float(), nullable=False),
        sa.Column("strengthening_score", sa.Float(), nullable=False),
        sa.Column("evidence_freshness_score", sa.Float(), nullable=False),
        sa.Column("contradiction_pressure", sa.Float(), nullable=False),
        sa.Column("price_confirmation_score", sa.Float(), nullable=False),
        sa.Column("volume_confirmation_score", sa.Float(), nullable=False),
        sa.Column("sentiment_confirmation_score", sa.Float(), nullable=False),
        sa.Column("narrative_confirmation_score", sa.Float(), nullable=False),
        sa.Column("regime_confirmation_score", sa.Float(), nullable=False),
        sa.Column("benchmark_confirmation_score", sa.Float(), nullable=False),
        sa.Column("invalidation_distance", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["thesis_id"], ["blum_knowledge_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    add_indexes("thesis_conviction_history", ["thesis_id", "evaluated_at", "new_confidence", "status"])
    op.create_index("ix_thesis_conviction_thesis_evaluated", "thesis_conviction_history", ["thesis_id", "evaluated_at"])

    op.create_table(
        "model_reliability_by_regime",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("engine_name", sa.String(length=100), nullable=False),
        sa.Column("signal_type", sa.String(length=100), nullable=False),
        sa.Column("setup_type", sa.String(length=100), nullable=False),
        sa.Column("thesis_type", sa.String(length=100), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=False),
        sa.Column("industry", sa.String(length=160), nullable=False),
        sa.Column("asset_class", sa.String(length=40), nullable=False),
        sa.Column("horizon", sa.String(length=40), nullable=False),
        sa.Column("market_regime", sa.String(length=120), nullable=False),
        sa.Column("volatility_regime", sa.String(length=80), nullable=False),
        sa.Column("breadth_regime", sa.String(length=80), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("hit_rate", sa.Float(), nullable=False),
        sa.Column("average_return", sa.Float(), nullable=True),
        sa.Column("excess_return_vs_benchmark", sa.Float(), nullable=True),
        sa.Column("average_r_multiple", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("false_positive_rate", sa.Float(), nullable=False),
        sa.Column("false_negative_rate", sa.Float(), nullable=False),
        sa.Column("calibration_error", sa.Float(), nullable=True),
        sa.Column("reliability_score", sa.Float(), nullable=False),
        sa.Column("confidence_penalty", sa.Float(), nullable=False),
        sa.Column("last_updated", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "engine_name",
            "signal_type",
            "setup_type",
            "thesis_type",
            "sector",
            "industry",
            "asset_class",
            "horizon",
            "market_regime",
            "volatility_regime",
            "breadth_regime",
            name="uq_model_reliability_by_regime_context",
        ),
    )
    add_indexes(
        "model_reliability_by_regime",
        ["engine_name", "signal_type", "setup_type", "thesis_type", "sector", "industry", "asset_class", "horizon", "market_regime", "volatility_regime", "breadth_regime", "sample_size", "reliability_score", "last_updated"],
    )
    op.create_index("ix_reliability_by_regime_engine_score", "model_reliability_by_regime", ["engine_name", "reliability_score"])
    op.create_index("ix_reliability_by_regime_context", "model_reliability_by_regime", ["market_regime", "sector", "horizon"])

    op.create_table(
        "thesis_competitions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("market_regime", sa.String(length=120), nullable=False),
        sa.Column("sector_regime", sa.String(length=120), nullable=False),
        sa.Column("winning_thesis_id", sa.Integer(), nullable=True),
        sa.Column("runner_up_thesis_id", sa.Integer(), nullable=True),
        sa.Column("uncertainty_score", sa.Float(), nullable=False),
        sa.Column("judge_summary", sa.Text(), nullable=False),
        sa.Column("next_evidence_to_watch", json_type, nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    add_indexes("thesis_competitions", ["ticker", "created_at", "winning_thesis_id", "runner_up_thesis_id", "uncertainty_score", "status"])
    op.create_index("ix_thesis_competitions_ticker_status", "thesis_competitions", ["ticker", "status"])

    op.create_table(
        "competing_theses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("thesis_side", sa.String(length=40), nullable=False),
        sa.Column("thesis_text", sa.Text(), nullable=False),
        sa.Column("supporting_evidence_json", json_type, nullable=False),
        sa.Column("contradicting_evidence_json", json_type, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("judge_score", sa.Float(), nullable=False),
        sa.Column("invalidation_conditions_json", json_type, nullable=False),
        sa.Column("expected_horizon", sa.String(length=80), nullable=False),
        sa.Column("outcome_status", sa.String(length=40), nullable=False),
        sa.Column("benchmark_relative_outcome", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["competition_id"], ["thesis_competitions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    add_indexes("competing_theses", ["competition_id", "thesis_side", "confidence", "judge_score", "expected_horizon", "outcome_status", "created_at", "evaluated_at"])
    op.create_index("ix_competing_theses_competition_side", "competing_theses", ["competition_id", "thesis_side"])
    op.create_index("ix_competing_theses_judge_score", "competing_theses", ["judge_score"])
    op.create_foreign_key("fk_thesis_competitions_winning_thesis", "thesis_competitions", "competing_theses", ["winning_thesis_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_thesis_competitions_runner_up_thesis", "thesis_competitions", "competing_theses", ["runner_up_thesis_id"], ["id"], ondelete="SET NULL")

    op.create_table(
        "engine_votes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("thesis_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("engine_name", sa.String(length=100), nullable=False),
        sa.Column("vote", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_quality", sa.Float(), nullable=False),
        sa.Column("horizon", sa.String(length=40), nullable=False),
        sa.Column("regime", sa.String(length=120), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("outcome_evaluated", sa.Boolean(), nullable=False),
        sa.Column("was_correct", sa.Boolean(), nullable=True),
        sa.Column("excess_return_contribution", sa.Float(), nullable=True),
        sa.Column("reliability_weight_at_time", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["thesis_id"], ["blum_knowledge_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("thesis_id", "engine_name", "horizon", name="uq_engine_vote_thesis_engine_horizon"),
    )
    add_indexes("engine_votes", ["thesis_id", "ticker", "engine_name", "vote", "confidence", "horizon", "regime", "sector", "created_at", "outcome_evaluated", "was_correct"])
    op.create_index("ix_engine_votes_ticker_engine", "engine_votes", ["ticker", "engine_name"])
    op.create_index("ix_engine_votes_outcome", "engine_votes", ["outcome_evaluated", "was_correct"])

    op.create_table(
        "ensemble_weight_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("version_name", sa.String(length=100), nullable=False),
        sa.Column("weights_json", json_type, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("validation_score", sa.Float(), nullable=False),
        sa.Column("calibration_score", sa.Float(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_name"),
    )
    add_indexes("ensemble_weight_versions", ["created_at", "version_name", "sample_size", "is_active"])
    op.create_index("ix_ensemble_weight_versions_active_created", "ensemble_weight_versions", ["is_active", "created_at"])

    op.create_table(
        "training_example_quality_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("training_example_id", sa.Integer(), nullable=False),
        sa.Column("thesis_id", sa.Integer(), nullable=True),
        sa.Column("reasoning_quality_score", sa.Float(), nullable=False),
        sa.Column("outcome_clarity_score", sa.Float(), nullable=False),
        sa.Column("data_quality_score", sa.Float(), nullable=False),
        sa.Column("contradiction_handling_score", sa.Float(), nullable=False),
        sa.Column("confidence_calibration_score", sa.Float(), nullable=False),
        sa.Column("regime_context_score", sa.Float(), nullable=False),
        sa.Column("benchmark_relevance_score", sa.Float(), nullable=False),
        sa.Column("reproducibility_score", sa.Float(), nullable=False),
        sa.Column("final_training_value_score", sa.Float(), nullable=False),
        sa.Column("include_in_sft", sa.Boolean(), nullable=False),
        sa.Column("include_in_preference_training", sa.Boolean(), nullable=False),
        sa.Column("include_in_dpo", sa.Boolean(), nullable=False),
        sa.Column("exclusion_reason", sa.Text(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["training_example_id"], ["blum_training_examples.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["thesis_id"], ["blum_knowledge_records.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("training_example_id", name="uq_training_example_quality_example"),
    )
    add_indexes("training_example_quality_scores", ["training_example_id", "thesis_id", "final_training_value_score", "include_in_sft", "include_in_preference_training", "include_in_dpo", "evaluated_at"])
    op.create_index("ix_training_quality_value", "training_example_quality_scores", ["final_training_value_score"])

    op.create_table(
        "benchmark_relative_outcomes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("object_type", sa.String(length=80), nullable=False),
        sa.Column("object_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("benchmark_ticker", sa.String(length=32), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("asset_return", sa.Float(), nullable=True),
        sa.Column("benchmark_return", sa.Float(), nullable=True),
        sa.Column("excess_return", sa.Float(), nullable=True),
        sa.Column("max_drawdown_asset", sa.Float(), nullable=True),
        sa.Column("max_drawdown_benchmark", sa.Float(), nullable=True),
        sa.Column("volatility_asset", sa.Float(), nullable=True),
        sa.Column("volatility_benchmark", sa.Float(), nullable=True),
        sa.Column("hit_vs_benchmark", sa.Boolean(), nullable=True),
        sa.Column("information_ratio_proxy", sa.Float(), nullable=True),
        sa.Column("opportunity_cost", sa.Float(), nullable=True),
        sa.Column("evaluation_notes", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_type", "object_id", "benchmark_ticker", name="uq_benchmark_relative_object_benchmark"),
    )
    add_indexes("benchmark_relative_outcomes", ["object_type", "object_id", "ticker", "benchmark_ticker", "start_date", "end_date", "excess_return", "hit_vs_benchmark", "created_at", "updated_at"])
    op.create_index("ix_benchmark_relative_ticker", "benchmark_relative_outcomes", ["ticker"])
    op.create_index("ix_benchmark_relative_hit", "benchmark_relative_outcomes", ["hit_vs_benchmark"])


def downgrade() -> None:
    op.drop_table("benchmark_relative_outcomes")
    op.drop_table("training_example_quality_scores")
    op.drop_table("ensemble_weight_versions")
    op.drop_table("engine_votes")
    op.drop_constraint("fk_thesis_competitions_runner_up_thesis", "thesis_competitions", type_="foreignkey")
    op.drop_constraint("fk_thesis_competitions_winning_thesis", "thesis_competitions", type_="foreignkey")
    op.drop_table("competing_theses")
    op.drop_table("thesis_competitions")
    op.drop_table("model_reliability_by_regime")
    op.drop_table("thesis_conviction_history")
    op.drop_table("thesis_survival_metrics")
