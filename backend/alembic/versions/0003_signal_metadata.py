from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_signal_metadata"
down_revision = "0002_market_brain_ipo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("signal_snapshots", sa.Column("score_version", sa.String(length=40), nullable=False, server_default="blum-score-v0.4"))
    op.add_column("signal_snapshots", sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"))
    op.add_column("signal_snapshots", sa.Column("lifecycle_state", sa.String(length=40), nullable=False, server_default="new"))
    op.create_index("ix_signal_snapshots_score_version", "signal_snapshots", ["score_version"])
    op.create_index("ix_signal_snapshots_confidence_score", "signal_snapshots", ["confidence_score"])
    op.create_index("ix_signal_snapshots_lifecycle_state", "signal_snapshots", ["lifecycle_state"])
    op.alter_column("signal_snapshots", "score_version", server_default=None)
    op.alter_column("signal_snapshots", "confidence_score", server_default=None)
    op.alter_column("signal_snapshots", "lifecycle_state", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_signal_snapshots_lifecycle_state", table_name="signal_snapshots")
    op.drop_index("ix_signal_snapshots_confidence_score", table_name="signal_snapshots")
    op.drop_index("ix_signal_snapshots_score_version", table_name="signal_snapshots")
    op.drop_column("signal_snapshots", "lifecycle_state")
    op.drop_column("signal_snapshots", "confidence_score")
    op.drop_column("signal_snapshots", "score_version")
