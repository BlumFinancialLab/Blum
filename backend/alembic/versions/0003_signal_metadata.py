from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_signal_metadata"
down_revision = "0002_market_brain_ipo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("signal_snapshots") as batch:
        batch.add_column(sa.Column("score_version", sa.String(length=40), nullable=False, server_default="blum-score-v0.4"))
        batch.add_column(sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("lifecycle_state", sa.String(length=40), nullable=False, server_default="new"))
        batch.create_index("ix_signal_snapshots_score_version", ["score_version"])
        batch.create_index("ix_signal_snapshots_confidence_score", ["confidence_score"])
        batch.create_index("ix_signal_snapshots_lifecycle_state", ["lifecycle_state"])
        batch.alter_column("score_version", server_default=None)
        batch.alter_column("confidence_score", server_default=None)
        batch.alter_column("lifecycle_state", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("signal_snapshots") as batch:
        batch.drop_index("ix_signal_snapshots_lifecycle_state")
        batch.drop_index("ix_signal_snapshots_confidence_score")
        batch.drop_index("ix_signal_snapshots_score_version")
        batch.drop_column("lifecycle_state")
        batch.drop_column("confidence_score")
        batch.drop_column("score_version")
