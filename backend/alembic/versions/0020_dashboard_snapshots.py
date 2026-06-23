from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0020_dashboard_snapshots"
down_revision = "0019_decision_quality"
branch_labels = None
depends_on = None


json_type = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "dashboard_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_type", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("payload_json", json_type, nullable=True),
        sa.Column("source_modules_json", json_type, nullable=True),
        sa.Column("is_stale", sa.Boolean(), nullable=False),
        sa.Column("computation_duration_ms", sa.Float(), nullable=True),
        sa.Column("warnings_json", json_type, nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dashboard_snapshots_snapshot_type", "dashboard_snapshots", ["snapshot_type"])
    op.create_index("ix_dashboard_snapshots_created_at", "dashboard_snapshots", ["created_at"])
    op.create_index("ix_dashboard_snapshots_is_stale", "dashboard_snapshots", ["is_stale"])
    op.create_index("ix_dashboard_snapshots_type_created", "dashboard_snapshots", ["snapshot_type", "created_at"])
    op.create_index("ix_dashboard_snapshots_type_expires", "dashboard_snapshots", ["snapshot_type", "expires_at"])


def downgrade() -> None:
    op.drop_table("dashboard_snapshots")
