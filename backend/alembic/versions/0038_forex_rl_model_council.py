"""Add Forex reinforcement policy and financial model council.

Revision ID: 0038_forex_rl_model_council
Revises: 0037_forex_evidence_academy
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0038_forex_rl_model_council"
down_revision = "0037_forex_evidence_academy"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.create_table(
        "forex_policy_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("policy_key", sa.String(240), nullable=False),
        sa.Column("strategy_id", sa.String(120), nullable=False),
        sa.Column("session", sa.String(60), nullable=False),
        sa.Column("regime", sa.String(60), nullable=False),
        sa.Column("setup_family", sa.String(80), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("q_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reward_sum", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reward_sq_sum", sa.Float(), nullable=False, server_default="0"),
        sa.Column("win_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("loss_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evidence_grade", sa.String(40), nullable=False),
        sa.Column("confidence_adjustment", sa.Float(), nullable=False, server_default="0"),
        sa.Column("last_evidence_id", sa.Integer(), sa.ForeignKey("forex_learning_evidence.id", ondelete="SET NULL")),
        sa.Column("policy_version", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("policy_key", name="uq_forex_policy_state_key"),
    )
    op.create_index("ix_forex_policy_states_policy_key", "forex_policy_states", ["policy_key"])
    op.create_index("ix_forex_policy_states_strategy_id", "forex_policy_states", ["strategy_id"])
    op.create_index("ix_forex_policy_states_evidence_grade", "forex_policy_states", ["evidence_grade"])
    op.create_index("ix_forex_policy_states_last_evidence_id", "forex_policy_states", ["last_evidence_id"])
    op.create_index("ix_forex_policy_states_updated_at", "forex_policy_states", ["updated_at"])
    op.create_index("ix_forex_policy_context", "forex_policy_states", ["strategy_id", "session", "regime", "setup_family", "direction"])

    op.create_table(
        "forex_policy_updates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("policy_state_id", sa.Integer(), sa.ForeignKey("forex_policy_states.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_id", sa.Integer(), sa.ForeignKey("forex_learning_evidence.id", ondelete="CASCADE"), nullable=False),
        sa.Column("previous_q", sa.Float(), nullable=False),
        sa.Column("reward", sa.Float(), nullable=False),
        sa.Column("new_q", sa.Float(), nullable=False),
        sa.Column("learning_rate", sa.Float(), nullable=False),
        sa.Column("sample_size_after", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("evidence_id", name="uq_forex_policy_update_evidence"),
    )
    op.create_index("ix_forex_policy_updates_policy_state_id", "forex_policy_updates", ["policy_state_id"])
    op.create_index("ix_forex_policy_updates_evidence_id", "forex_policy_updates", ["evidence_id"])
    op.create_index("ix_forex_policy_updates_created_at", "forex_policy_updates", ["created_at"])

    op.create_table(
        "financial_model_advisors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("advisor_key", sa.String(80), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("provider_type", sa.String(60), nullable=False),
        sa.Column("model_id", sa.String(240)),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("role", sa.String(120), nullable=False),
        sa.Column("execution_mode", sa.String(60), nullable=False),
        sa.Column("runtime_status", sa.String(60), nullable=False),
        sa.Column("license", sa.String(80), nullable=False),
        sa.Column("resource_profile", JSON_TYPE, nullable=False),
        sa.Column("capabilities", JSON_TYPE, nullable=False),
        sa.Column("direct_trading_authority", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("advisor_key", name="uq_financial_model_advisor_key"),
    )
    op.create_index("ix_financial_model_advisors_advisor_key", "financial_model_advisors", ["advisor_key"])
    op.create_index("ix_financial_model_advisors_provider_type", "financial_model_advisors", ["provider_type"])
    op.create_index("ix_financial_model_advisors_role", "financial_model_advisors", ["role"])
    op.create_index("ix_financial_model_advisors_execution_mode", "financial_model_advisors", ["execution_mode"])
    op.create_index("ix_financial_model_advisors_runtime_status", "financial_model_advisors", ["runtime_status"])
    op.create_index("ix_financial_model_advisors_enabled", "financial_model_advisors", ["enabled"])
    op.create_index("ix_financial_model_advisors_updated_at", "financial_model_advisors", ["updated_at"])

    op.create_table(
        "financial_model_votes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("advisor_key", sa.String(80), nullable=False),
        sa.Column("object_type", sa.String(80), nullable=False),
        sa.Column("object_id", sa.String(120), nullable=False),
        sa.Column("ticker", sa.String(32)),
        sa.Column("task", sa.String(80), nullable=False),
        sa.Column("vote", sa.String(40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence_quality", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("output_json", JSON_TYPE, nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("runtime_status", sa.String(60), nullable=False),
        sa.Column("direct_action_allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("outcome_evaluated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reward_contribution", sa.Float()),
        sa.Column("was_helpful", sa.Boolean()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime()),
        sa.UniqueConstraint("advisor_key", "object_type", "object_id", "task", "evidence_hash", name="uq_financial_model_vote_evidence"),
    )
    op.create_index("ix_financial_model_votes_advisor_key", "financial_model_votes", ["advisor_key"])
    op.create_index("ix_financial_model_votes_object_type", "financial_model_votes", ["object_type"])
    op.create_index("ix_financial_model_votes_object_id", "financial_model_votes", ["object_id"])
    op.create_index("ix_financial_model_votes_ticker", "financial_model_votes", ["ticker"])
    op.create_index("ix_financial_model_votes_task", "financial_model_votes", ["task"])
    op.create_index("ix_financial_model_votes_vote", "financial_model_votes", ["vote"])
    op.create_index("ix_financial_model_votes_evidence_hash", "financial_model_votes", ["evidence_hash"])
    op.create_index("ix_financial_model_votes_runtime_status", "financial_model_votes", ["runtime_status"])
    op.create_index("ix_financial_model_votes_outcome_evaluated", "financial_model_votes", ["outcome_evaluated"])
    op.create_index("ix_financial_model_votes_was_helpful", "financial_model_votes", ["was_helpful"])
    op.create_index("ix_financial_model_votes_created_at", "financial_model_votes", ["created_at"])
    op.create_index("ix_financial_model_vote_object", "financial_model_votes", ["object_type", "object_id", "created_at"])


def downgrade() -> None:
    op.drop_table("financial_model_votes")
    op.drop_table("financial_model_advisors")
    op.drop_table("forex_policy_updates")
    op.drop_table("forex_policy_states")
