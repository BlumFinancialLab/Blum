"""Add the evidence-bound Forex knowledge academy.

Revision ID: 0037_forex_evidence_academy
Revises: 0036_forex_alpha_trader
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0037_forex_evidence_academy"
down_revision = "0036_forex_alpha_trader"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.create_table(
        "forex_knowledge_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_key", sa.String(120), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("source_type", sa.String(80), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("license", sa.String(120), nullable=False),
        sa.Column("usage_policy", JSON_TYPE, nullable=False),
        sa.Column("schema_json", JSON_TYPE, nullable=False),
        sa.Column("validation_status", sa.String(40), nullable=False),
        sa.Column("validation_notes", JSON_TYPE, nullable=False),
        sa.Column("last_validated_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("source_key", name="uq_forex_knowledge_sources_key"),
    )
    op.create_index("ix_forex_knowledge_source_status", "forex_knowledge_sources", ["validation_status", "updated_at"])
    op.create_index("ix_forex_knowledge_sources_provider", "forex_knowledge_sources", ["provider"])
    op.create_index("ix_forex_knowledge_sources_source_type", "forex_knowledge_sources", ["source_type"])

    op.create_table(
        "forex_curriculum_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assignment_key", sa.String(180), nullable=False),
        sa.Column("priority_type", sa.String(60), nullable=False),
        sa.Column("pair", sa.String(32), nullable=False),
        sa.Column("session", sa.String(60), nullable=False),
        sa.Column("regime", sa.String(60), nullable=False),
        sa.Column("setup_family", sa.String(80), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("expected_information_gain", sa.Float(), nullable=False),
        sa.Column("priority_score", sa.Float(), nullable=False),
        sa.Column("sample_gap", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("replay_spec_json", JSON_TYPE, nullable=False),
        sa.Column("samples_generated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_sampled_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("assignment_key", name="uq_forex_curriculum_assignment_key"),
    )
    op.create_index("ix_forex_curriculum_status_priority", "forex_curriculum_assignments", ["status", "priority_score"])
    op.create_index("ix_forex_curriculum_context", "forex_curriculum_assignments", ["pair", "session", "regime", "setup_family"])

    op.create_table(
        "forex_contextual_memory",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("memory_key", sa.String(240), nullable=False),
        sa.Column("strategy_id", sa.String(120), nullable=False),
        sa.Column("pair_family", sa.String(40), nullable=False),
        sa.Column("session", sa.String(60), nullable=False),
        sa.Column("regime", sa.String(60), nullable=False),
        sa.Column("setup_family", sa.String(80), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("win_rate", sa.Float()),
        sa.Column("net_expectancy_r", sa.Float()),
        sa.Column("benchmark_excess", sa.Float()),
        sa.Column("cost_failure_rate", sa.Float()),
        sa.Column("confidence_interval_json", JSON_TYPE, nullable=False),
        sa.Column("evidence_grade", sa.String(40), nullable=False),
        sa.Column("confidence_adjustment", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source_evidence_ids", JSON_TYPE, nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("compiled_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("memory_key", name="uq_forex_contextual_memory_key"),
    )
    op.create_index("ix_forex_memory_context", "forex_contextual_memory", ["strategy_id", "session", "regime", "setup_family"])
    op.create_index("ix_forex_memory_grade_updated", "forex_contextual_memory", ["evidence_grade", "updated_at"])

    op.create_table(
        "forex_knowledge_ingestion_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_key", sa.String(120), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("cursor_json", JSON_TYPE, nullable=False),
        sa.Column("rows_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_accepted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("validation_json", JSON_TYPE, nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
    )
    op.create_index("ix_forex_ingestion_source_status", "forex_knowledge_ingestion_runs", ["source_key", "status", "started_at"])


def downgrade() -> None:
    op.drop_table("forex_knowledge_ingestion_runs")
    op.drop_table("forex_contextual_memory")
    op.drop_table("forex_curriculum_assignments")
    op.drop_table("forex_knowledge_sources")
