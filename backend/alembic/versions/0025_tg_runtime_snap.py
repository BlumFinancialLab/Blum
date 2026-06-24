from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0025_tg_runtime_snap"
down_revision = "0024_runtime_architecture"
branch_labels = None
depends_on = None


json_type = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "trading_game_ledger_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("limit", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("total_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_json", json_type, nullable=True),
        sa.Column("summary_json", json_type, nullable=True),
        sa.Column("trace_json", json_type, nullable=True),
        sa.Column("payload_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_stale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["game_id"], ["trading_games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trading_game_ledger_snapshots_game_id", "trading_game_ledger_snapshots", ["game_id"])
    op.create_index("ix_trading_game_ledger_snapshots_created_at", "trading_game_ledger_snapshots", ["created_at"])
    op.create_index("ix_trading_game_ledger_snapshots_expires_at", "trading_game_ledger_snapshots", ["expires_at"])
    op.create_index("ix_trading_game_ledger_snapshots_is_stale", "trading_game_ledger_snapshots", ["is_stale"])
    op.create_index("ix_trading_game_ledger_snapshots_total_trades", "trading_game_ledger_snapshots", ["total_trades"])
    op.create_index("ix_trading_game_ledger_snapshots_game_created", "trading_game_ledger_snapshots", ["game_id", "created_at"])
    op.create_index("ix_trading_game_ledger_snapshots_expires", "trading_game_ledger_snapshots", ["expires_at"])

    op.create_table(
        "equity_curve_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("limit", sa.Integer(), nullable=False, server_default="500"),
        sa.Column("point_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("annotation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_json", json_type, nullable=True),
        sa.Column("summary_json", json_type, nullable=True),
        sa.Column("trace_json", json_type, nullable=True),
        sa.Column("payload_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_stale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["game_id"], ["trading_games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_equity_curve_snapshots_game_id", "equity_curve_snapshots", ["game_id"])
    op.create_index("ix_equity_curve_snapshots_created_at", "equity_curve_snapshots", ["created_at"])
    op.create_index("ix_equity_curve_snapshots_expires_at", "equity_curve_snapshots", ["expires_at"])
    op.create_index("ix_equity_curve_snapshots_is_stale", "equity_curve_snapshots", ["is_stale"])
    op.create_index("ix_equity_curve_snapshots_game_created", "equity_curve_snapshots", ["game_id", "created_at"])
    op.create_index("ix_equity_curve_snapshots_expires", "equity_curve_snapshots", ["expires_at"])


def downgrade() -> None:
    op.drop_table("equity_curve_snapshots")
    op.drop_table("trading_game_ledger_snapshots")
