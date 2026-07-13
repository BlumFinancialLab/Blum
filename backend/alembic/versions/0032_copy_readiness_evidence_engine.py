from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0032_copy_readiness_evidence"
down_revision = "0031_intraday_paper"
branch_labels = None
depends_on = None


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "strategy_evidence_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("strategy_id", sa.String(160), nullable=False),
        sa.Column("setup_type", sa.String(100), nullable=False),
        sa.Column("evidence_class", sa.String(60), nullable=False),
        sa.Column("total_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("closed_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("forward_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("win_rate", sa.Float()),
        sa.Column("gross_expectancy", sa.Float()),
        sa.Column("net_expectancy", sa.Float()),
        sa.Column("average_r", sa.Float()),
        sa.Column("profit_factor", sa.Float()),
        sa.Column("sharpe_proxy", sa.Float()),
        sa.Column("sortino_proxy", sa.Float()),
        sa.Column("max_drawdown", sa.Float()),
        sa.Column("benchmark_return", sa.Float()),
        sa.Column("benchmark_excess", sa.Float()),
        sa.Column("total_costs", sa.Float()),
        sa.Column("average_slippage", sa.Float()),
        sa.Column("metrics_json", json_type),
        sa.Column("markets_json", json_type),
        sa.Column("timeframes_json", json_type),
        sa.Column("source_rows_json", json_type),
        sa.Column("warnings_json", json_type),
        sa.Column("concentration_json", json_type),
        sa.Column("regimes_json", json_type),
        sa.Column("confidence_interval_json", json_type),
        sa.Column("evaluated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("strategy_id", "setup_type", "evidence_class", "evaluated_at", "created_at"):
        op.create_index(f"ix_strategy_evidence_snapshots_{column}", "strategy_evidence_snapshots", [column])
    op.create_index(
        "ix_strategy_evidence_snapshots_latest",
        "strategy_evidence_snapshots",
        ["strategy_id", "evidence_class", "evaluated_at"],
    )

    op.create_table(
        "strategy_readiness_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("strategy_id", sa.String(160), nullable=False),
        sa.Column("previous_copy_readiness_status", sa.String(80)),
        sa.Column("copy_readiness_status", sa.String(80), nullable=False),
        sa.Column("maturity_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("global_forward_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("strategy_forward_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("observation_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed_gates_json", json_type),
        sa.Column("failed_gates_json", json_type),
        sa.Column("blockers_json", json_type),
        sa.Column("reasons_json", json_type),
        sa.Column("decay_status", sa.String(80)),
        sa.Column("real_capital_eligibility", sa.String(100)),
        sa.Column("threshold_version", sa.String(80), nullable=False, server_default="copy-readiness-v1"),
        sa.Column("evaluated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in (
        "strategy_id",
        "copy_readiness_status",
        "decay_status",
        "real_capital_eligibility",
        "threshold_version",
        "evaluated_at",
        "created_at",
    ):
        op.create_index(f"ix_strategy_readiness_history_{column}", "strategy_readiness_history", [column])
    op.create_index(
        "ix_strategy_readiness_history_latest",
        "strategy_readiness_history",
        ["strategy_id", "evaluated_at"],
    )

    op.create_table(
        "evidence_timeline_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_key", sa.String(220), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("strategy_id", sa.String(160)),
        sa.Column("trade_id", sa.Integer()),
        sa.Column("payload_json", json_type),
        sa.Column("event_timestamp", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("event_key", name="uq_evidence_timeline_events_event_key"),
    )
    for column in ("event_key", "event_type", "strategy_id", "trade_id", "event_timestamp", "created_at"):
        op.create_index(f"ix_evidence_timeline_events_{column}", "evidence_timeline_events", [column])
    op.create_index(
        "ix_evidence_timeline_events_strategy_time",
        "evidence_timeline_events",
        ["strategy_id", "event_timestamp"],
    )


def downgrade() -> None:
    op.drop_table("evidence_timeline_events")
    op.drop_table("strategy_readiness_history")
    op.drop_table("strategy_evidence_snapshots")
