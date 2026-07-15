from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0009_auto_dataset_intel"
down_revision = "0008_blum_financial_model"
branch_labels = None
depends_on = None


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "external_dataset_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.String(length=220), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=260), nullable=False),
        sa.Column("primary_domain", sa.String(length=80), nullable=False),
        sa.Column("data_domains", json_type, nullable=False),
        sa.Column("license", sa.String(length=80), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("ingestion_mode", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("dataset_url", sa.Text(), nullable=False),
        sa.Column("viewer_status", json_type, nullable=False),
        sa.Column("parquet_files", json_type, nullable=False),
        sa.Column("size_summary", json_type, nullable=False),
        sa.Column("usage_policy", json_type, nullable=False),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", name="uq_external_dataset_source_dataset_id"),
    )
    for column in ["dataset_id", "provider", "primary_domain", "license", "priority", "ingestion_mode", "status", "last_checked_at", "created_at", "updated_at"]:
        op.create_index(f"ix_external_dataset_sources_{column}", "external_dataset_sources", [column])
    op.create_index("ix_external_dataset_sources_status_priority", "external_dataset_sources", ["status", "priority"])
    op.create_index("ix_external_dataset_sources_domain_updated", "external_dataset_sources", ["primary_domain", "updated_at"])

    op.create_table(
        "autonomous_engine_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=100), nullable=False),
        sa.Column("trigger", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("stage_results", json_type, nullable=False),
        sa.Column("readiness_score", sa.Float(), nullable=False),
        sa.Column("data_coverage_score", sa.Float(), nullable=False),
        sa.Column("reasoning_memory_created", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("error_payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_autonomous_engine_run_id"),
    )
    for column in ["run_id", "trigger", "status", "started_at", "completed_at", "readiness_score", "data_coverage_score", "created_at"]:
        op.create_index(f"ix_autonomous_engine_runs_{column}", "autonomous_engine_runs", [column])
    op.create_index("ix_autonomous_engine_runs_status_started", "autonomous_engine_runs", ["status", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_autonomous_engine_runs_status_started", table_name="autonomous_engine_runs")
    for column in ["created_at", "data_coverage_score", "readiness_score", "completed_at", "started_at", "status", "trigger", "run_id"]:
        op.drop_index(f"ix_autonomous_engine_runs_{column}", table_name="autonomous_engine_runs")
    op.drop_table("autonomous_engine_runs")

    op.drop_index("ix_external_dataset_sources_domain_updated", table_name="external_dataset_sources")
    op.drop_index("ix_external_dataset_sources_status_priority", table_name="external_dataset_sources")
    for column in ["updated_at", "created_at", "last_checked_at", "status", "ingestion_mode", "priority", "license", "primary_domain", "provider", "dataset_id"]:
        op.drop_index(f"ix_external_dataset_sources_{column}", table_name="external_dataset_sources")
    op.drop_table("external_dataset_sources")
