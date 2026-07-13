from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0030_hyperbolic_replay"
down_revision = "0029_learning_accel"
branch_labels = None
depends_on = None


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "replay_market_bars",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_symbol", sa.String(48), nullable=False),
        sa.Column("normalized_symbol", sa.String(48), nullable=False),
        sa.Column("market", sa.String(40), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("bar_timestamp", sa.DateTime(), nullable=False),
        sa.Column("open", sa.Float()),
        sa.Column("high", sa.Float()),
        sa.Column("low", sa.Float()),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float()),
        sa.Column("provider", sa.String(48), nullable=False),
        sa.Column("acquired_at", sa.DateTime(), nullable=False),
        sa.Column("data_quality_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source_metadata", json_type),
        sa.UniqueConstraint("asset_id", "timeframe", "bar_timestamp", name="uq_replay_bar_timestamp"),
    )
    op.create_index("ix_replay_bars_asset_timeframe_timestamp", "replay_market_bars", ["asset_id", "timeframe", "bar_timestamp"])
    for column in ("asset_id", "source_symbol", "normalized_symbol", "market", "timeframe", "bar_timestamp", "provider", "acquired_at", "data_quality_score"):
        op.create_index(f"ix_replay_market_bars_{column}", "replay_market_bars", [column])

    op.create_table(
        "replay_data_coverages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_symbol", sa.String(48), nullable=False),
        sa.Column("normalized_symbol", sa.String(48), nullable=False),
        sa.Column("market", sa.String(40), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("provider", sa.String(48), nullable=False),
        sa.Column("requested_start", sa.DateTime()),
        sa.Column("requested_end", sa.DateTime()),
        sa.Column("available_start", sa.DateTime()),
        sa.Column("available_end", sa.DateTime()),
        sa.Column("rows_available", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("coverage_percent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("data_quality_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(40), nullable=False, server_default="INITIALIZING"),
        sa.Column("missing_intervals", json_type),
        sa.Column("blockers", json_type),
        sa.Column("source_metadata", json_type),
        sa.Column("acquired_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("asset_id", "timeframe", "provider", name="uq_replay_coverage_asset_timeframe_provider"),
    )
    op.create_index("ix_replay_coverage_status_updated", "replay_data_coverages", ["status", "updated_at"])
    for column in ("asset_id", "source_symbol", "normalized_symbol", "market", "timeframe", "provider", "available_start", "available_end", "data_quality_score", "status", "updated_at"):
        op.create_index(f"ix_replay_data_coverages_{column}", "replay_data_coverages", [column])

    op.create_table(
        "hyperbolic_replay_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(120), nullable=False, unique=True),
        sa.Column("trigger", sa.String(40), nullable=False, server_default="scheduled"),
        sa.Column("status", sa.String(40), nullable=False, server_default="RUNNING"),
        sa.Column("evidence_type", sa.String(40), nullable=False, server_default="REPLAY_EVIDENCE"),
        sa.Column("adaptive_state", sa.String(40), nullable=False, server_default="RUNNING"),
        sa.Column("assets_selected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trades_generated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trades_validated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("experiments_run", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("duration_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("markets_json", json_type),
        sa.Column("timeframes_json", json_type),
        sa.Column("cursor_json", json_type),
        sa.Column("resource_limits_json", json_type),
        sa.Column("blockers_json", json_type),
        sa.Column("summary_json", json_type),
    )
    op.create_index("ix_hyperbolic_replay_runs_run_id", "hyperbolic_replay_runs", ["run_id"])
    op.create_index("ix_hyperbolic_replay_runs_status_started", "hyperbolic_replay_runs", ["status", "started_at"])
    for column in ("trigger", "status", "evidence_type", "adaptive_state", "started_at", "completed_at"):
        op.create_index(f"ix_hyperbolic_replay_runs_{column}", "hyperbolic_replay_runs", [column])

    op.create_table(
        "hyperbolic_replay_trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("hyperbolic_replay_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticker", sa.String(48), nullable=False),
        sa.Column("market", sa.String(40), nullable=False),
        sa.Column("setup_type", sa.String(80), nullable=False),
        sa.Column("timeframe", sa.String(16), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("evidence_type", sa.String(40), nullable=False, server_default="REPLAY_EVIDENCE"),
        sa.Column("decision_timestamp", sa.DateTime(), nullable=False),
        sa.Column("entry_timestamp", sa.DateTime()),
        sa.Column("exit_timestamp", sa.DateTime()),
        sa.Column("entry_price", sa.Float()),
        sa.Column("exit_price", sa.Float()),
        sa.Column("stop_price", sa.Float()),
        sa.Column("target_price", sa.Float()),
        sa.Column("position_size", sa.Float(), nullable=False, server_default="0"),
        sa.Column("gross_pnl", sa.Float()),
        sa.Column("net_pnl", sa.Float()),
        sa.Column("r_multiple", sa.Float()),
        sa.Column("benchmark_excess", sa.Float()),
        sa.Column("data_quality_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("decision_payload", json_type),
        sa.Column("execution_payload", json_type),
        sa.Column("outcome_payload", json_type),
        sa.Column("rejection_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("asset_id", "setup_type", "timeframe", "decision_timestamp", name="uq_replay_trade_decision"),
    )
    op.create_index("ix_hyperbolic_replay_trades_run_state", "hyperbolic_replay_trades", ["run_id", "state"])
    op.create_index("ix_hyperbolic_replay_trades_ticker_decision", "hyperbolic_replay_trades", ["ticker", "decision_timestamp"])
    for column in ("run_id", "asset_id", "ticker", "market", "setup_type", "timeframe", "state", "evidence_type", "decision_timestamp", "entry_timestamp", "exit_timestamp", "r_multiple", "benchmark_excess", "created_at"):
        op.create_index(f"ix_hyperbolic_replay_trades_{column}", "hyperbolic_replay_trades", [column])

    op.create_table(
        "replay_strategy_validations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("experiment_id", sa.Integer(), sa.ForeignKey("blum_learning_experiments.id", ondelete="SET NULL")),
        sa.Column("setup_type", sa.String(80), nullable=False),
        sa.Column("evidence_type", sa.String(40), nullable=False, server_default="WALK_FORWARD_EVIDENCE"),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("markets_json", json_type),
        sa.Column("windows_json", json_type),
        sa.Column("metrics_json", json_type),
        sa.Column("overfitting_score", sa.Float(), nullable=False, server_default="100"),
        sa.Column("verdict", sa.String(60), nullable=False, server_default="NEEDS_MORE_EVIDENCE"),
        sa.Column("explanation", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_replay_strategy_validations_experiment_id", "replay_strategy_validations", ["experiment_id"])
    op.create_index("ix_replay_strategy_validations_setup_verdict", "replay_strategy_validations", ["setup_type", "verdict"])
    op.create_index("ix_replay_strategy_validations_created", "replay_strategy_validations", ["created_at"])
    for column in ("setup_type", "evidence_type", "sample_size", "verdict"):
        op.create_index(f"ix_replay_strategy_validations_{column}", "replay_strategy_validations", [column])


def downgrade() -> None:
    op.drop_table("replay_strategy_validations")
    op.drop_table("hyperbolic_replay_trades")
    op.drop_table("hyperbolic_replay_runs")
    op.drop_table("replay_data_coverages")
    op.drop_table("replay_market_bars")
