"""Add executable strategy identity to replay trades.

Revision ID: 0035_decision_execution_parity
Revises: 0034_realistic_execution_market
"""

from alembic import op
import sqlalchemy as sa


revision = "0035_decision_execution_parity"
down_revision = "0034_realistic_execution_market"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "hyperbolic_replay_trades" not in sa.inspect(bind).get_table_names():
        # Some supported legacy installations were stamped after the replay
        # migration without creating its optional tables. Keep this migration
        # additive; a future replay bootstrap can create the current model.
        return
    op.add_column(
        "hyperbolic_replay_trades",
        sa.Column("strategy_fingerprint", sa.String(length=96), nullable=True),
    )
    trades = sa.table(
        "hyperbolic_replay_trades",
        sa.column("setup_type", sa.String(length=80)),
        sa.column("strategy_fingerprint", sa.String(length=96)),
    )
    op.execute(
        trades.update().where(trades.c.strategy_fingerprint.is_(None)).values(
            strategy_fingerprint=sa.literal("legacy:") + trades.c.setup_type
        )
    )
    with op.batch_alter_table("hyperbolic_replay_trades") as batch:
        batch.alter_column("strategy_fingerprint", existing_type=sa.String(length=96), nullable=False)
        batch.drop_constraint("uq_replay_trade_decision", type_="unique")
        batch.create_unique_constraint(
            "uq_replay_trade_strategy_decision",
            ["asset_id", "strategy_fingerprint", "timeframe", "decision_timestamp"],
        )
        batch.create_index(
            "ix_hyperbolic_replay_trades_strategy_fingerprint",
            ["strategy_fingerprint"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "hyperbolic_replay_trades" not in sa.inspect(bind).get_table_names():
        return
    with op.batch_alter_table("hyperbolic_replay_trades") as batch:
        batch.drop_index("ix_hyperbolic_replay_trades_strategy_fingerprint")
        batch.drop_constraint("uq_replay_trade_strategy_decision", type_="unique")
        batch.create_unique_constraint(
            "uq_replay_trade_decision",
            ["asset_id", "setup_type", "timeframe", "decision_timestamp"],
        )
        batch.drop_column("strategy_fingerprint")
