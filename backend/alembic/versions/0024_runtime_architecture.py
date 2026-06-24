from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0024_runtime_architecture"
down_revision = "0023_meta_cognition_engine"
branch_labels = None
depends_on = None


json_type = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column("dashboard_snapshots", sa.Column("missing_sections_json", json_type, nullable=True))

    op.create_table(
        "brain_runtime_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("source_module", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("payload_json", json_type, nullable=True),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brain_runtime_events_created_at", "brain_runtime_events", ["created_at"])
    op.create_index("ix_brain_runtime_events_event_type", "brain_runtime_events", ["event_type"])
    op.create_index("ix_brain_runtime_events_source_module", "brain_runtime_events", ["source_module"])
    op.create_index("ix_brain_runtime_events_status", "brain_runtime_events", ["status"])
    op.create_index("ix_brain_runtime_events_module_created", "brain_runtime_events", ["source_module", "created_at"])
    op.create_index("ix_brain_runtime_events_type_created", "brain_runtime_events", ["event_type", "created_at"])
    op.create_index("ix_brain_runtime_events_status_created", "brain_runtime_events", ["status", "created_at"])

    op.create_table(
        "background_job_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_name", sa.String(length=160), nullable=False),
        sa.Column("stage_name", sa.String(length=160), nullable=False, server_default="default"),
        sa.Column("status", sa.String(length=80), nullable=False, server_default="idle"),
        sa.Column("cursor_json", json_type, nullable=True),
        sa.Column("items_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("last_started_at", sa.DateTime(), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(), nullable=True),
        sa.Column("next_run_after", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_background_job_state_job_name", "background_job_state", ["job_name"])
    op.create_index("ix_background_job_state_stage_name", "background_job_state", ["stage_name"])
    op.create_index("ix_background_job_state_status", "background_job_state", ["status"])
    op.create_index("ix_background_job_state_last_started_at", "background_job_state", ["last_started_at"])
    op.create_index("ix_background_job_state_last_completed_at", "background_job_state", ["last_completed_at"])
    op.create_index("ix_background_job_state_next_run_after", "background_job_state", ["next_run_after"])
    op.create_index("ix_background_job_state_enabled", "background_job_state", ["enabled", "status"])
    op.create_index("ix_background_job_state_job_stage", "background_job_state", ["job_name", "stage_name"])
    op.create_index("ix_background_job_state_status_next", "background_job_state", ["status", "next_run_after"])


def downgrade() -> None:
    op.drop_table("background_job_state")
    op.drop_table("brain_runtime_events")
    op.drop_column("dashboard_snapshots", "missing_sections_json")
