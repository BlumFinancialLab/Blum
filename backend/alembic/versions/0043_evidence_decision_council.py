"""Add the evidence-bound multi-agent decision council.

Revision ID: 0043_agent_council
Revises: 0042_det_execution
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0043_agent_council"
down_revision = "0042_det_execution"
branch_labels = None
depends_on = None


JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "agent_council_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_uid", sa.String(128), nullable=False),
        sa.Column("knowledge_record_id", sa.Integer(), sa.ForeignKey("blum_knowledge_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("sector", sa.String(120), nullable=False, server_default="Unknown"),
        sa.Column("market_regime", sa.String(120), nullable=False, server_default="Unknown"),
        sa.Column("as_of", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="RUNNING"),
        sa.Column("current_stage", sa.String(60), nullable=False, server_default="analyst"),
        sa.Column("stage_cursor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("base_confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("final_confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("final_action", sa.String(32), nullable=False, server_default="WAIT"),
        sa.Column("disagreement_score", sa.Float(), nullable=False, server_default="100"),
        sa.Column("evidence_quality", sa.Float(), nullable=False, server_default="0"),
        sa.Column("memory_adjustment", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source_snapshot_json", JSON_TYPE, nullable=False),
        sa.Column("checkpoint_json", JSON_TYPE, nullable=False),
        sa.Column("final_decision_json", JSON_TYPE, nullable=False),
        sa.Column("warnings_json", JSON_TYPE, nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.UniqueConstraint("run_uid", name="uq_agent_council_run_uid"),
    )
    op.create_index("ix_agent_council_runs_status_created", "agent_council_runs", ["status", "created_at"])
    op.create_index("ix_agent_council_runs_ticker_asof", "agent_council_runs", ["ticker", "as_of"])
    op.create_index("ix_agent_council_runs_record_status", "agent_council_runs", ["knowledge_record_id", "status"])

    op.create_table(
        "agent_council_turns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("agent_council_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage", sa.String(60), nullable=False),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("turn_sequence", sa.Integer(), nullable=False),
        sa.Column("stance", sa.String(32), nullable=False, server_default="neutral"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reliability_weight", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("argument", sa.Text(), nullable=False, server_default=""),
        sa.Column("supporting_evidence_json", JSON_TYPE, nullable=False),
        sa.Column("contradicting_evidence_json", JSON_TYPE, nullable=False),
        sa.Column("evidence_refs_json", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("run_id", "stage", "agent_name", "round_number", name="uq_agent_council_turn"),
    )
    op.create_index("ix_agent_council_turns_run_sequence", "agent_council_turns", ["run_id", "turn_sequence"])
    op.create_index("ix_agent_council_turns_agent_created", "agent_council_turns", ["agent_name", "created_at"])

    op.create_table(
        "agent_council_reflections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("agent_council_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("outcome_id", sa.Integer(), sa.ForeignKey("blum_thesis_outcomes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("sector", sa.String(120), nullable=False, server_default="Unknown"),
        sa.Column("market_regime", sa.String(120), nullable=False, server_default="Unknown"),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("expected_action", sa.String(32), nullable=False),
        sa.Column("realized_return", sa.Float()),
        sa.Column("benchmark_return", sa.Float()),
        sa.Column("excess_return", sa.Float()),
        sa.Column("direction_correct", sa.Boolean()),
        sa.Column("actionability_was_helpful", sa.Boolean()),
        sa.Column("lesson", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence_json", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("run_id", "outcome_id", name="uq_agent_council_reflection_outcome"),
    )
    op.create_index("ix_agent_council_reflections_ticker_created", "agent_council_reflections", ["ticker", "created_at"])
    op.create_index("ix_agent_council_reflections_result", "agent_council_reflections", ["direction_correct", "excess_return"])


def downgrade() -> None:
    op.drop_index("ix_agent_council_reflections_result", table_name="agent_council_reflections")
    op.drop_index("ix_agent_council_reflections_ticker_created", table_name="agent_council_reflections")
    op.drop_table("agent_council_reflections")
    op.drop_index("ix_agent_council_turns_agent_created", table_name="agent_council_turns")
    op.drop_index("ix_agent_council_turns_run_sequence", table_name="agent_council_turns")
    op.drop_table("agent_council_turns")
    op.drop_index("ix_agent_council_runs_record_status", table_name="agent_council_runs")
    op.drop_index("ix_agent_council_runs_ticker_asof", table_name="agent_council_runs")
    op.drop_index("ix_agent_council_runs_status_created", table_name="agent_council_runs")
    op.drop_table("agent_council_runs")
