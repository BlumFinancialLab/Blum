from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0017_trading_intelligence_lab"
down_revision = "0016_trade_transparency_layer"
branch_labels = None
depends_on = None


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def create_index(table: str, columns: list[str], suffix: str | None = None) -> None:
    name = f"ix_{table}_{suffix or '_'.join(columns)}"
    if len(name) > 63:
        name = f"ix_{table[:28]}_{(suffix or '_'.join(columns))[:24]}"
    op.create_index(name, table, columns)


def upgrade() -> None:
    op.add_column("trading_games", sa.Column("target_capital", sa.Float(), nullable=True))
    op.add_column("trading_games", sa.Column("active_cycle_id", sa.Integer(), nullable=True))
    op.add_column("trading_games", sa.Column("target_cycles_completed", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("trading_games", sa.Column("bankrupt_cycles", sa.Integer(), nullable=False, server_default="0"))
    create_index("trading_games", ["active_cycle_id"])

    op.add_column("trading_game_trades", sa.Column("mode", sa.String(length=80), nullable=False, server_default="historical_simulation"))
    op.add_column("trading_game_trades", sa.Column("capital_cycle_id", sa.Integer(), nullable=True))
    create_index("trading_game_trades", ["mode"])
    create_index("trading_game_trades", ["capital_cycle_id"])

    op.create_table(
        "trading_capital_cycles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("cycle_number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("start_capital", sa.Float(), nullable=False),
        sa.Column("target_capital", sa.Float(), nullable=False),
        sa.Column("final_capital", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=60), nullable=False),
        sa.Column("reached_target", sa.Boolean(), nullable=False),
        sa.Column("went_to_zero", sa.Boolean(), nullable=False),
        sa.Column("return_percent", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("trades_count", sa.Integer(), nullable=False),
        sa.Column("wins", sa.Integer(), nullable=False),
        sa.Column("losses", sa.Integer(), nullable=False),
        sa.Column("missed_entries", sa.Integer(), nullable=False),
        sa.Column("target_hits", sa.Integer(), nullable=False),
        sa.Column("stop_hits", sa.Integer(), nullable=False),
        sa.Column("no_trade_correct", sa.Integer(), nullable=False),
        sa.Column("no_trade_missed_opportunity", sa.Integer(), nullable=False),
        sa.Column("profit_factor", sa.Float(), nullable=True),
        sa.Column("expectancy_r", sa.Float(), nullable=True),
        sa.Column("benchmark_return", sa.Float(), nullable=True),
        sa.Column("excess_return_vs_benchmark", sa.Float(), nullable=True),
        sa.Column("best_trade_id", sa.Integer(), nullable=True),
        sa.Column("worst_trade_id", sa.Integer(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("success_reason", sa.Text(), nullable=True),
        sa.Column("lessons_json", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["trading_games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ["game_id", "cycle_number", "started_at", "ended_at", "target_capital", "status", "reached_target", "went_to_zero", "trades_count", "best_trade_id", "worst_trade_id", "created_at", "updated_at"]:
        create_index("trading_capital_cycles", [column])
    create_index("trading_capital_cycles", ["game_id", "cycle_number"], "game_cycle")

    op.create_table(
        "trading_intelligence_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("scope", sa.String(length=80), nullable=False),
        sa.Column("scope_id", sa.String(length=120), nullable=True),
        sa.Column("window_type", sa.String(length=80), nullable=False),
        sa.Column("window_size", sa.Integer(), nullable=True),
        sa.Column("trades_count", sa.Integer(), nullable=False),
        sa.Column("win_rate", sa.Float(), nullable=True),
        sa.Column("loss_rate", sa.Float(), nullable=True),
        sa.Column("missed_entry_rate", sa.Float(), nullable=True),
        sa.Column("target_hit_rate", sa.Float(), nullable=True),
        sa.Column("stop_hit_rate", sa.Float(), nullable=True),
        sa.Column("no_trade_correct_rate", sa.Float(), nullable=True),
        sa.Column("no_trade_missed_opportunity_rate", sa.Float(), nullable=True),
        sa.Column("expectancy_r", sa.Float(), nullable=True),
        sa.Column("profit_factor", sa.Float(), nullable=True),
        sa.Column("average_r", sa.Float(), nullable=True),
        sa.Column("median_r", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("benchmark_excess", sa.Float(), nullable=True),
        sa.Column("entry_timing_score", sa.Float(), nullable=True),
        sa.Column("exit_timing_score", sa.Float(), nullable=True),
        sa.Column("sizing_quality_score", sa.Float(), nullable=True),
        sa.Column("risk_reward_quality_score", sa.Float(), nullable=True),
        sa.Column("reproducibility_score", sa.Float(), nullable=True),
        sa.Column("trade_quality_score", sa.Float(), nullable=True),
        sa.Column("intelligence_growth_score", sa.Float(), nullable=True),
        sa.Column("notes_json", json_type, nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ["calculated_at", "scope", "scope_id", "window_type", "window_size", "trades_count", "intelligence_growth_score"]:
        create_index("trading_intelligence_metrics", [column])
    create_index("trading_intelligence_metrics", ["scope", "scope_id", "window_type", "window_size"], "scope_window")

    op.create_table(
        "live_forward_paper_games",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=60), nullable=False),
        sa.Column("starting_capital", sa.Float(), nullable=False),
        sa.Column("current_capital", sa.Float(), nullable=False),
        sa.Column("target_capital", sa.Float(), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("exposure", sa.Float(), nullable=False),
        sa.Column("realized_pl", sa.Float(), nullable=False),
        sa.Column("benchmark_ticker", sa.String(length=32), nullable=False),
        sa.Column("open_positions", sa.Integer(), nullable=False),
        sa.Column("cycle_number", sa.Integer(), nullable=False),
        sa.Column("configuration", json_type, nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_id", name="uq_live_forward_paper_games_game_id"),
    )
    for column in ["game_id", "status", "current_capital", "benchmark_ticker", "open_positions", "cycle_number", "started_at", "updated_at"]:
        create_index("live_forward_paper_games", [column])
    create_index("live_forward_paper_games", ["status", "started_at"], "status_started")

    op.create_table(
        "live_forward_paper_positions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("trade_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("setup_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=60), nullable=False),
        sa.Column("decision_timestamp", sa.DateTime(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=True),
        sa.Column("current_price", sa.Float(), nullable=True),
        sa.Column("position_size", sa.Float(), nullable=False),
        sa.Column("risk_amount", sa.Float(), nullable=False),
        sa.Column("stop_loss", sa.Float(), nullable=True),
        sa.Column("target_1", sa.Float(), nullable=True),
        sa.Column("target_2", sa.Float(), nullable=True),
        sa.Column("thesis_snapshot", json_type, nullable=True),
        sa.Column("data_snapshot", json_type, nullable=True),
        sa.Column("no_future_data_policy", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["live_forward_paper_games.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trade_id"], ["trading_game_trades.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ["game_id", "trade_id", "ticker", "setup_type", "status", "decision_timestamp", "created_at", "updated_at"]:
        create_index("live_forward_paper_positions", [column])
    create_index("live_forward_paper_positions", ["game_id", "status", "created_at"], "game_status")

    op.create_table(
        "historical_live_comparisons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("historical_sample_size", sa.Integer(), nullable=False),
        sa.Column("live_sample_size", sa.Integer(), nullable=False),
        sa.Column("historical_win_rate", sa.Float(), nullable=True),
        sa.Column("live_win_rate", sa.Float(), nullable=True),
        sa.Column("historical_expectancy", sa.Float(), nullable=True),
        sa.Column("live_expectancy", sa.Float(), nullable=True),
        sa.Column("historical_target_hit_rate", sa.Float(), nullable=True),
        sa.Column("live_target_hit_rate", sa.Float(), nullable=True),
        sa.Column("historical_missed_entry_rate", sa.Float(), nullable=True),
        sa.Column("live_missed_entry_rate", sa.Float(), nullable=True),
        sa.Column("historical_max_drawdown", sa.Float(), nullable=True),
        sa.Column("live_max_drawdown", sa.Float(), nullable=True),
        sa.Column("historical_benchmark_excess", sa.Float(), nullable=True),
        sa.Column("live_benchmark_excess", sa.Float(), nullable=True),
        sa.Column("historical_profit_factor", sa.Float(), nullable=True),
        sa.Column("live_profit_factor", sa.Float(), nullable=True),
        sa.Column("sample_warning", sa.Text(), nullable=True),
        sa.Column("comparison_payload", json_type, nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("historical_live_comparisons", ["created_at"])


def downgrade() -> None:
    op.drop_table("historical_live_comparisons")
    op.drop_table("live_forward_paper_positions")
    op.drop_table("live_forward_paper_games")
    op.drop_table("trading_intelligence_metrics")
    op.drop_table("trading_capital_cycles")
    op.drop_index("ix_trading_game_trades_capital_cycle_id", table_name="trading_game_trades")
    op.drop_index("ix_trading_game_trades_mode", table_name="trading_game_trades")
    op.drop_index("ix_trading_games_active_cycle_id", table_name="trading_games")
    op.drop_column("trading_game_trades", "capital_cycle_id")
    op.drop_column("trading_game_trades", "mode")
    op.drop_column("trading_games", "bankrupt_cycles")
    op.drop_column("trading_games", "target_cycles_completed")
    op.drop_column("trading_games", "active_cycle_id")
    op.drop_column("trading_games", "target_capital")
