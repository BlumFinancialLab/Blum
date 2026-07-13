from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0031_intraday_paper"
down_revision = "0030_hyperbolic_replay"
branch_labels = None
depends_on = None


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "intraday_paper_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_uid", sa.String(120), nullable=False, unique=True),
        sa.Column("trigger", sa.String(40), nullable=False, server_default="scheduled"),
        sa.Column("status", sa.String(40), nullable=False, server_default="RUNNING"),
        sa.Column("markets_checked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assets_checked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidates_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidates_approved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trades_opened", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trades_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trades_closed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_due_to_costs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_due_to_risk", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_due_to_concentration", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("duration_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("data_blockers", json_type),
        sa.Column("summary_json", json_type),
    )
    op.create_index("ix_intraday_paper_runs_run_uid", "intraday_paper_runs", ["run_uid"])
    op.create_index("ix_intraday_paper_runs_status", "intraday_paper_runs", ["status"])
    op.create_index("ix_intraday_paper_runs_trigger", "intraday_paper_runs", ["trigger"])
    op.create_index("ix_intraday_paper_runs_started_at", "intraday_paper_runs", ["started_at"])
    op.create_index("ix_intraday_paper_runs_completed_at", "intraday_paper_runs", ["completed_at"])
    op.create_index("ix_intraday_paper_runs_status_started", "intraday_paper_runs", ["status", "started_at"])
    op.create_index("ix_intraday_paper_runs_trigger_started", "intraday_paper_runs", ["trigger", "started_at"])

    columns = [
        sa.Column("trading_mode", sa.String(60)),
        sa.Column("evidence_type", sa.String(60)),
        sa.Column(
            "promoted_validation_id",
            sa.Integer(),
            sa.ForeignKey(
                "replay_strategy_validations.id",
                name="fk_live_forward_intraday_validation",
                ondelete="SET NULL",
            ),
        ),
        sa.Column(
            "intraday_run_id",
            sa.Integer(),
            sa.ForeignKey(
                "intraday_paper_runs.id",
                name="fk_live_forward_intraday_run",
                ondelete="SET NULL",
            ),
        ),
        sa.Column("market", sa.String(60)),
        sa.Column("desk", sa.String(100)),
        sa.Column("session_name", sa.String(60)),
        sa.Column("timeframe_stack", json_type),
        sa.Column("data_timestamps", json_type),
        sa.Column("execution_costs", json_type),
        sa.Column("spread_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("slippage_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("commission_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("costs_paid", sa.Float(), nullable=False, server_default="0"),
        sa.Column("net_expectancy_bps", sa.Float()),
        sa.Column("sizing_reason", sa.Text()),
        sa.Column("trailing_stop", sa.Float()),
        sa.Column("last_managed_bar_at", sa.DateTime()),
        sa.Column("holding_minutes", sa.Float()),
        sa.Column("intraday_metadata", json_type),
    ]
    with op.batch_alter_table("live_forward_paper_trades") as batch:
        for column in columns:
            batch.add_column(column)

    for column in (
        "trading_mode",
        "evidence_type",
        "promoted_validation_id",
        "intraday_run_id",
        "market",
        "desk",
        "session_name",
        "last_managed_bar_at",
    ):
        op.create_index(f"ix_live_forward_paper_trades_{column}", "live_forward_paper_trades", [column])


def downgrade() -> None:
    for column in (
        "last_managed_bar_at",
        "session_name",
        "desk",
        "market",
        "intraday_run_id",
        "promoted_validation_id",
        "evidence_type",
        "trading_mode",
    ):
        op.drop_index(f"ix_live_forward_paper_trades_{column}", table_name="live_forward_paper_trades")
    with op.batch_alter_table("live_forward_paper_trades") as batch:
        for column in (
            "intraday_metadata",
            "holding_minutes",
            "last_managed_bar_at",
            "trailing_stop",
            "sizing_reason",
            "net_expectancy_bps",
            "costs_paid",
            "commission_cost",
            "slippage_cost",
            "spread_cost",
            "execution_costs",
            "data_timestamps",
            "timeframe_stack",
            "session_name",
            "desk",
            "market",
            "intraday_run_id",
            "promoted_validation_id",
            "evidence_type",
            "trading_mode",
        ):
            batch.drop_column(column)
    op.drop_table("intraday_paper_runs")
