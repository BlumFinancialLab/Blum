from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0034_realistic_execution_market"
down_revision = "0033_alpha_factory_execution"
branch_labels = None
depends_on = None


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "intraday_no_trade_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_uid", sa.String(220), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("intraday_paper_runs.id", ondelete="SET NULL")),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticker", sa.String(48), nullable=False),
        sa.Column("setup_type", sa.String(100), nullable=False),
        sa.Column("market", sa.String(60), nullable=False),
        sa.Column("desk", sa.String(100)),
        sa.Column("benchmark_ticker", sa.String(32)),
        sa.Column("reason_code", sa.String(100), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="PENDING"),
        sa.Column("decision_timestamp", sa.DateTime(), nullable=False),
        sa.Column("evaluation_due_at", sa.DateTime(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime()),
        sa.Column("theoretical_price", sa.Float(), nullable=False),
        sa.Column("expected_move_bps", sa.Float(), nullable=False, server_default="0"),
        sa.Column("expected_cost_bps", sa.Float(), nullable=False, server_default="0"),
        sa.Column("future_return", sa.Float()),
        sa.Column("benchmark_return", sa.Float()),
        sa.Column("capital_preserved", sa.Float(), nullable=False, server_default="0"),
        sa.Column("opportunity_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("outcome_label", sa.String(100)),
        sa.Column("decision_payload", json_type, nullable=False),
        sa.Column("evaluation_payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("decision_uid", name="uq_intraday_no_trade_decision_uid"),
    )
    for column in (
        "decision_uid",
        "run_id",
        "asset_id",
        "ticker",
        "setup_type",
        "market",
        "desk",
        "benchmark_ticker",
        "reason_code",
        "status",
        "decision_timestamp",
        "evaluation_due_at",
        "evaluated_at",
        "outcome_label",
        "created_at",
    ):
        op.create_index(f"ix_intraday_no_trade_decisions_{column}", "intraday_no_trade_decisions", [column])
    op.create_index("ix_intraday_no_trade_status_due", "intraday_no_trade_decisions", ["status", "evaluation_due_at"])
    op.create_index("ix_intraday_no_trade_ticker_time", "intraday_no_trade_decisions", ["ticker", "decision_timestamp"])


def downgrade() -> None:
    op.drop_table("intraday_no_trade_decisions")
