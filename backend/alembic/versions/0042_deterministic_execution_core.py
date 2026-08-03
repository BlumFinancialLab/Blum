"""Add deterministic execution shadow evidence.

Revision ID: 0042_det_execution
Revises: 0041_pf_direction
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0042_det_execution"
down_revision = "0041_pf_direction"
branch_labels = None
depends_on = None


JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "deterministic_execution_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_uid", sa.String(120), nullable=False),
        sa.Column("environment", sa.String(40), nullable=False),
        sa.Column("kernel_name", sa.String(80), nullable=False, server_default="nautilus_trader"),
        sa.Column("kernel_version", sa.String(40)),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("source_object_type", sa.String(80)),
        sa.Column("source_object_id", sa.String(120)),
        sa.Column("reproducibility_fingerprint", sa.String(128), nullable=False),
        sa.Column("order_event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("position_event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("costs_json", JSON_TYPE, nullable=False),
        sa.Column("diagnostics_json", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.UniqueConstraint("run_uid"),
        sa.UniqueConstraint("reproducibility_fingerprint", name="uq_deterministic_execution_fingerprint"),
    )
    op.create_index("ix_deterministic_execution_runs_status_created", "deterministic_execution_runs", ["status", "created_at"])
    op.create_index("ix_deterministic_execution_runs_source", "deterministic_execution_runs", ["source_object_type", "source_object_id"])
    op.create_table(
        "deterministic_execution_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("deterministic_execution_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_uid", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("entity_id", sa.String(160), nullable=False),
        sa.Column("decision_id", sa.String(160)),
        sa.Column("event_timestamp", sa.DateTime(), nullable=False),
        sa.Column("payload_json", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("event_uid", name="uq_deterministic_execution_event_uid"),
    )
    op.create_index("ix_deterministic_execution_events_run_timestamp", "deterministic_execution_events", ["run_id", "event_timestamp"])
    op.create_table(
        "execution_parity_comparisons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("deterministic_execution_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_object_type", sa.String(80)),
        sa.Column("source_object_id", sa.String(120)),
        sa.Column("asset_class", sa.String(40)),
        sa.Column("regime", sa.String(80)),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("state_agreement", sa.Boolean()),
        sa.Column("quantity_difference", sa.Float()),
        sa.Column("fill_price_difference", sa.Float()),
        sa.Column("cost_difference", sa.Float()),
        sa.Column("pnl_difference", sa.Float()),
        sa.Column("reasons_json", JSON_TYPE, nullable=False),
        sa.Column("evidence_json", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_execution_parity_status_created", "execution_parity_comparisons", ["status", "created_at"])
    op.create_index("ix_execution_parity_source", "execution_parity_comparisons", ["source_object_type", "source_object_id"])
    op.create_table(
        "execution_kernel_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("state_key", sa.String(80), nullable=False, unique=True),
        sa.Column("mode", sa.String(40), nullable=False, server_default="SHADOW"),
        sa.Column("previous_mode", sa.String(40)),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matched_samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state_agreement_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("asset_classes_json", JSON_TYPE, nullable=False),
        sa.Column("regimes_json", JSON_TYPE, nullable=False),
        sa.Column("promoted_at", sa.DateTime()),
        sa.Column("quarantined_at", sa.DateTime()),
        sa.Column("rollback_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("warnings_json", JSON_TYPE, nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_execution_kernel_state_mode_updated", "execution_kernel_state", ["mode", "updated_at"])


def downgrade() -> None:
    op.drop_index("ix_execution_kernel_state_mode_updated", table_name="execution_kernel_state")
    op.drop_table("execution_kernel_state")
    op.drop_index("ix_execution_parity_source", table_name="execution_parity_comparisons")
    op.drop_index("ix_execution_parity_status_created", table_name="execution_parity_comparisons")
    op.drop_table("execution_parity_comparisons")
    op.drop_index("ix_deterministic_execution_events_run_timestamp", table_name="deterministic_execution_events")
    op.drop_table("deterministic_execution_events")
    op.drop_index("ix_deterministic_execution_runs_source", table_name="deterministic_execution_runs")
    op.drop_index("ix_deterministic_execution_runs_status_created", table_name="deterministic_execution_runs")
    op.drop_table("deterministic_execution_runs")
