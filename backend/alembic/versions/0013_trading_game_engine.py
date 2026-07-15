from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0013_trading_game_engine"
down_revision = "0012_market_sniper_engine"
branch_labels = None
depends_on = None


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "trading_games",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("mode", sa.String(length=80), nullable=False),
        sa.Column("starting_capital", sa.Float(), nullable=False),
        sa.Column("current_capital", sa.Float(), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("exposure", sa.Float(), nullable=False),
        sa.Column("realized_pl", sa.Float(), nullable=False),
        sa.Column("unrealized_pl", sa.Float(), nullable=False),
        sa.Column("peak_capital", sa.Float(), nullable=False),
        sa.Column("max_drawdown", sa.Float(), nullable=False),
        sa.Column("benchmark_ticker", sa.String(length=32), nullable=False),
        sa.Column("benchmark_start_price", sa.Float(), nullable=True),
        sa.Column("benchmark_end_price", sa.Float(), nullable=True),
        sa.Column("benchmark_return", sa.Float(), nullable=True),
        sa.Column("alpha", sa.Float(), nullable=True),
        sa.Column("beta", sa.Float(), nullable=True),
        sa.Column("trade_count", sa.Integer(), nullable=False),
        sa.Column("win_rate", sa.Float(), nullable=True),
        sa.Column("expectancy_r", sa.Float(), nullable=True),
        sa.Column("profit_factor", sa.Float(), nullable=True),
        sa.Column("average_r", sa.Float(), nullable=True),
        sa.Column("sharpe", sa.Float(), nullable=True),
        sa.Column("sortino", sa.Float(), nullable=True),
        sa.Column("risk_per_trade", sa.Float(), nullable=False),
        sa.Column("risk_of_ruin", sa.Float(), nullable=True),
        sa.Column("max_consecutive_losses", sa.Integer(), nullable=False),
        sa.Column("time_to_double_days", sa.Integer(), nullable=True),
        sa.Column("time_to_ruin_days", sa.Integer(), nullable=True),
        sa.Column("configuration", json_type, nullable=False),
        sa.Column("failure_report", json_type, nullable=False),
        sa.Column("success_report", json_type, nullable=False),
        sa.Column("lessons", json_type, nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_id", name="uq_trading_games_game_id"),
    )
    for name in ["game_id", "status", "mode", "current_capital", "benchmark_ticker", "started_at", "ended_at", "updated_at"]:
        op.create_index(f"ix_trading_games_{name}", "trading_games", [name])
    op.create_index("ix_trading_games_status_started", "trading_games", ["status", "started_at"])

    op.create_table(
        "trading_game_trades",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("execution_simulation_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("setup_type", sa.String(length=100), nullable=False),
        sa.Column("timeframe", sa.String(length=40), nullable=False),
        sa.Column("decision_state", sa.String(length=80), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=True),
        sa.Column("exit_date", sa.Date(), nullable=True),
        sa.Column("entry_price", sa.Float(), nullable=True),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("position_size", sa.Float(), nullable=False),
        sa.Column("risk_amount", sa.Float(), nullable=False),
        sa.Column("risk_percent", sa.Float(), nullable=False),
        sa.Column("realized_r_multiple", sa.Float(), nullable=True),
        sa.Column("realized_pl", sa.Float(), nullable=False),
        sa.Column("capital_before", sa.Float(), nullable=False),
        sa.Column("capital_after", sa.Float(), nullable=False),
        sa.Column("stop_hit", sa.Boolean(), nullable=False),
        sa.Column("target_hit", sa.Boolean(), nullable=False),
        sa.Column("missed_entry", sa.Boolean(), nullable=False),
        sa.Column("false_breakout", sa.Boolean(), nullable=False),
        sa.Column("slippage_bps", sa.Float(), nullable=False),
        sa.Column("spread_bps", sa.Float(), nullable=False),
        sa.Column("reproducibility_score", sa.Float(), nullable=False),
        sa.Column("benchmark_return", sa.Float(), nullable=True),
        sa.Column("payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["execution_simulation_id"], ["execution_simulations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["game_id"], ["trading_games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name in ["game_id", "execution_simulation_id", "ticker", "setup_type", "timeframe", "decision_state", "entry_date", "exit_date", "realized_r_multiple", "stop_hit", "target_hit", "missed_entry", "false_breakout", "reproducibility_score", "created_at"]:
        op.create_index(f"ix_trading_game_trades_{name}", "trading_game_trades", [name])
    op.create_index("ix_trading_game_trades_game_created", "trading_game_trades", ["game_id", "created_at"])

    op.create_table(
        "trading_game_equity_curve",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("equity_date", sa.Date(), nullable=True),
        sa.Column("equity", sa.Float(), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("exposure", sa.Float(), nullable=False),
        sa.Column("drawdown", sa.Float(), nullable=False),
        sa.Column("benchmark_equity", sa.Float(), nullable=True),
        sa.Column("benchmark_return", sa.Float(), nullable=True),
        sa.Column("payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["trading_games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name in ["game_id", "equity_date", "equity", "created_at"]:
        op.create_index(f"ix_trading_game_equity_curve_{name}", "trading_game_equity_curve", [name])
    op.create_index("ix_trading_game_equity_game_date", "trading_game_equity_curve", ["game_id", "equity_date"])

    op.create_table(
        "trading_game_failures",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("report", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["trading_games.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name in ["game_id", "category", "severity", "created_at"]:
        op.create_index(f"ix_trading_game_failures_{name}", "trading_game_failures", [name])
    op.create_index("ix_trading_game_failures_game_created", "trading_game_failures", ["game_id", "created_at"])

    op.create_table(
        "capital_management_lessons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("lesson", sa.Text(), nullable=False),
        sa.Column("reliability_score", sa.Float(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("evidence", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for name in ["category", "reliability_score", "sample_count", "created_at", "updated_at"]:
        op.create_index(f"ix_capital_management_lessons_{name}", "capital_management_lessons", [name])
    op.create_index("ix_capital_management_lessons_category_updated", "capital_management_lessons", ["category", "updated_at"])


def downgrade() -> None:
    op.drop_table("capital_management_lessons")
    op.drop_table("trading_game_failures")
    op.drop_table("trading_game_equity_curve")
    op.drop_table("trading_game_trades")
    op.drop_table("trading_games")
