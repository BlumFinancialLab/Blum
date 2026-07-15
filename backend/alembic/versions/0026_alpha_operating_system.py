from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0026_alpha_operating_system"
down_revision = "0025_tg_runtime_snap"
branch_labels = None
depends_on = None


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def create_index(table: str, columns: list[str], suffix: str | None = None) -> None:
    name = f"ix_{table}_{suffix or '_'.join(columns)}"
    if len(name) > 63:
        name = f"ix_{table[:30]}_{(suffix or '_'.join(columns))[:22]}"
    op.create_index(name, table, columns)


def upgrade() -> None:
    op.create_table(
        "trading_game_readiness_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=80), nullable=False, server_default="WAITING_FOR_SOURCE_DATA"),
        sa.Column("evidence_grade", sa.String(length=80), nullable=False, server_default="insufficient"),
        sa.Column("blocker", sa.Text(), nullable=False, server_default=""),
        sa.Column("next_required_action", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload_json", json_type, nullable=True),
        sa.Column("warnings_json", json_type, nullable=True),
        sa.Column("methodology_version", sa.String(length=80), nullable=False, server_default="trading-game-readiness-v1"),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("is_stale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["game_id"], ["trading_games.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("trading_game_readiness_snapshots", ["generated_at"], "generated")
    create_index("trading_game_readiness_snapshots", ["status", "evidence_grade"], "status_grade")
    create_index("trading_game_readiness_snapshots", ["game_id", "generated_at"], "game_generated")

    op.create_table(
        "alpha_readiness_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False, server_default="INSUFFICIENT_EVIDENCE"),
        sa.Column("alpha_readiness_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence_grade", sa.String(length=80), nullable=False, server_default="insufficient"),
        sa.Column("classification", sa.String(length=120), nullable=False, server_default="not_ready"),
        sa.Column("payload_json", json_type, nullable=True),
        sa.Column("warnings_json", json_type, nullable=True),
        sa.Column("methodology_version", sa.String(length=80), nullable=False, server_default="alpha-readiness-v1"),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("is_stale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("alpha_readiness_snapshots", ["generated_at"], "generated")
    create_index("alpha_readiness_snapshots", ["alpha_readiness_score", "evidence_grade"], "score")

    op.create_table(
        "alpha_gate_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("gate_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False, server_default="blocked"),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("payload_json", json_type, nullable=True),
        sa.Column("warnings_json", json_type, nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("alpha_gate_snapshots", ["generated_at"], "generated")
    create_index("alpha_gate_snapshots", ["gate_name", "status"], "status")

    op.create_table(
        "edge_map_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=120), nullable=False, server_default="global"),
        sa.Column("evidence_grade", sa.String(length=80), nullable=False, server_default="insufficient"),
        sa.Column("payload_json", json_type, nullable=True),
        sa.Column("warnings_json", json_type, nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("edge_map_snapshots", ["generated_at"], "generated")
    create_index("edge_map_snapshots", ["scope", "evidence_grade"], "scope")

    op.create_table(
        "paper_copy_strategies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("strategy_id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False, server_default="BLUM Paper Copy Strategy"),
        sa.Column("status", sa.String(length=80), nullable=False, server_default="paper_only"),
        sa.Column("strategy_type", sa.String(length=120), nullable=False, server_default="conditional_copy_watchlist"),
        sa.Column("copyability_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("risk_budget_percent", sa.Float(), nullable=False, server_default="1"),
        sa.Column("max_open_positions", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("rules_json", json_type, nullable=True),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.Column("warnings_json", json_type, nullable=True),
        sa.Column("paper_only", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("no_broker_execution", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("strategy_id"),
    )
    create_index("paper_copy_strategies", ["strategy_id"], "strategy_id")
    create_index("paper_copy_strategies", ["status", "created_at"], "status_created")
    create_index("paper_copy_strategies", ["copyability_score"], "score")

    op.create_table(
        "paper_copy_portfolios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.String(length=100), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=80), nullable=False, server_default="paper_active"),
        sa.Column("starting_capital", sa.Float(), nullable=False, server_default="100"),
        sa.Column("current_capital", sa.Float(), nullable=False, server_default="100"),
        sa.Column("cash", sa.Float(), nullable=False, server_default="100"),
        sa.Column("exposure", sa.Float(), nullable=False, server_default="0"),
        sa.Column("realized_pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unrealized_pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("benchmark_ticker", sa.String(length=32), nullable=False, server_default="SPY"),
        sa.Column("risk_state", sa.String(length=80), nullable=False, server_default="conservative"),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.Column("warnings_json", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["strategy_id"], ["paper_copy_strategies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("portfolio_id"),
    )
    create_index("paper_copy_portfolios", ["portfolio_id"], "portfolio_id")
    create_index("paper_copy_portfolios", ["status", "updated_at"], "status_updated")
    create_index("paper_copy_portfolios", ["strategy_id"], "strategy")

    op.create_table(
        "paper_copy_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=True),
        sa.Column("strategy_id", sa.Integer(), nullable=True),
        sa.Column("source_trade_plan_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=40), nullable=False, server_default="paper_buy"),
        sa.Column("status", sa.String(length=80), nullable=False, server_default="planned"),
        sa.Column("order_type", sa.String(length=80), nullable=False, server_default="conditional_paper"),
        sa.Column("trigger_condition", sa.Text(), nullable=False, server_default=""),
        sa.Column("paper_price", sa.Float(), nullable=True),
        sa.Column("paper_quantity", sa.Float(), nullable=True),
        sa.Column("risk_amount", sa.Float(), nullable=True),
        sa.Column("invalidation_level", sa.Float(), nullable=True),
        sa.Column("target_1", sa.Float(), nullable=True),
        sa.Column("target_2", sa.Float(), nullable=True),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["portfolio_id"], ["paper_copy_portfolios.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["strategy_id"], ["paper_copy_strategies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_trade_plan_id"], ["trade_plans.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("paper_copy_orders", ["portfolio_id", "created_at"], "portfolio_created")
    create_index("paper_copy_orders", ["ticker", "status"], "ticker_status")
    create_index("paper_copy_orders", ["strategy_id"], "strategy")
    create_index("paper_copy_orders", ["source_trade_plan_id"], "source_plan")

    op.create_table(
        "paper_copy_positions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=True),
        sa.Column("strategy_id", sa.Integer(), nullable=True),
        sa.Column("source_order_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False, server_default="open"),
        sa.Column("quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("entry_price", sa.Float(), nullable=True),
        sa.Column("current_price", sa.Float(), nullable=True),
        sa.Column("market_value", sa.Float(), nullable=True),
        sa.Column("unrealized_pnl", sa.Float(), nullable=True),
        sa.Column("realized_pnl", sa.Float(), nullable=True),
        sa.Column("invalidation_level", sa.Float(), nullable=True),
        sa.Column("target_1", sa.Float(), nullable=True),
        sa.Column("target_2", sa.Float(), nullable=True),
        sa.Column("opened_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.ForeignKeyConstraint(["portfolio_id"], ["paper_copy_portfolios.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["strategy_id"], ["paper_copy_strategies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_order_id"], ["paper_copy_orders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("paper_copy_positions", ["portfolio_id", "status"], "portfolio_status")
    create_index("paper_copy_positions", ["ticker", "opened_at"], "ticker_opened")
    create_index("paper_copy_positions", ["strategy_id"], "strategy")
    create_index("paper_copy_positions", ["source_order_id"], "source_order")

    op.create_table(
        "paper_copy_portfolio_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=True),
        sa.Column("strategy_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("capital", sa.Float(), nullable=True),
        sa.Column("exposure", sa.Float(), nullable=True),
        sa.Column("open_positions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pending_orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("copyability_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence_grade", sa.String(length=80), nullable=False, server_default="insufficient"),
        sa.Column("payload_json", json_type, nullable=True),
        sa.Column("warnings_json", json_type, nullable=True),
        sa.ForeignKeyConstraint(["portfolio_id"], ["paper_copy_portfolios.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["strategy_id"], ["paper_copy_strategies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("paper_copy_portfolio_snapshots", ["portfolio_id", "created_at"], "portfolio_created")
    create_index("paper_copy_portfolio_snapshots", ["copyability_score", "evidence_grade"], "score")
    create_index("paper_copy_portfolio_snapshots", ["strategy_id"], "strategy")


def downgrade() -> None:
    op.drop_table("paper_copy_portfolio_snapshots")
    op.drop_table("paper_copy_positions")
    op.drop_table("paper_copy_orders")
    op.drop_table("paper_copy_portfolios")
    op.drop_table("paper_copy_strategies")
    op.drop_table("edge_map_snapshots")
    op.drop_table("alpha_gate_snapshots")
    op.drop_table("alpha_readiness_snapshots")
    op.drop_table("trading_game_readiness_snapshots")
