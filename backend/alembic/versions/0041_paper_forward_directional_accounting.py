"""Add authoritative paper-forward directional accounting.

Revision ID: 0041_pf_direction
Revises: 0040_trading_ml_champion
"""

from alembic import op
import sqlalchemy as sa


revision = "0041_pf_direction"
down_revision = "0040_trading_ml_champion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "live_forward_paper_trades",
        sa.Column("side", sa.String(length=8), nullable=True),
    )
    op.add_column(
        "live_forward_paper_trades",
        sa.Column(
            "accounting_status",
            sa.String(length=64),
            nullable=False,
            server_default="PENDING_SIDE_VERIFICATION",
        ),
    )
    op.add_column(
        "live_forward_paper_trades",
        sa.Column("accounting_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "live_forward_paper_trades",
        sa.Column("accounting_recomputed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_live_forward_paper_trades_side",
        "live_forward_paper_trades",
        ["side"],
    )
    op.create_index(
        "ix_live_forward_paper_trades_accounting_status",
        "live_forward_paper_trades",
        ["accounting_status"],
    )
    op.create_index(
        "ix_live_forward_paper_trades_accounting_version",
        "live_forward_paper_trades",
        ["accounting_version"],
    )
    op.create_index(
        "ix_live_forward_paper_trades_accounting_recomputed_at",
        "live_forward_paper_trades",
        ["accounting_recomputed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_live_forward_paper_trades_accounting_recomputed_at",
        table_name="live_forward_paper_trades",
    )
    op.drop_index(
        "ix_live_forward_paper_trades_accounting_version",
        table_name="live_forward_paper_trades",
    )
    op.drop_index(
        "ix_live_forward_paper_trades_accounting_status",
        table_name="live_forward_paper_trades",
    )
    op.drop_index(
        "ix_live_forward_paper_trades_side",
        table_name="live_forward_paper_trades",
    )
    op.drop_column("live_forward_paper_trades", "accounting_recomputed_at")
    op.drop_column("live_forward_paper_trades", "accounting_version")
    op.drop_column("live_forward_paper_trades", "accounting_status")
    op.drop_column("live_forward_paper_trades", "side")
