from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0016_trade_transparency_layer"
down_revision = "0015_reasoning_precision_engines"
branch_labels = None
depends_on = None


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def create_index(table: str, columns: list[str], suffix: str | None = None) -> None:
    name = f"ix_{table}_{suffix or '_'.join(columns)}"
    if len(name) > 63:
        name = f"ix_{table[:28]}_{(suffix or '_'.join(columns))[:24]}"
    op.create_index(name, table, columns)


def add_column(table: str, column: sa.Column) -> None:
    op.add_column(table, column)


def upgrade() -> None:
    add_column("trading_games", sa.Column("ledger_summary", json_type, nullable=True))
    add_column("trading_games", sa.Column("reality_check_summary", json_type, nullable=True))
    add_column("trading_games", sa.Column("transparency_updated_at", sa.DateTime(), nullable=True))
    create_index("trading_games", ["transparency_updated_at"])

    trade_columns = [
        sa.Column("asset_name", sa.String(length=220), nullable=True),
        sa.Column("asset_type", sa.String(length=40), nullable=True),
        sa.Column("sector", sa.String(length=120), nullable=True),
        sa.Column("industry", sa.String(length=160), nullable=True),
        sa.Column("thesis_id", sa.Integer(), nullable=True),
        sa.Column("sniper_score_at_entry", sa.Float(), nullable=True),
        sa.Column("opportunity_score_at_entry", sa.Float(), nullable=True),
        sa.Column("confidence_at_entry", sa.Float(), nullable=True),
        sa.Column("actionability_state_at_entry", sa.String(length=80), nullable=True),
        sa.Column("market_regime_at_entry", sa.String(length=120), nullable=True),
        sa.Column("sector_regime_at_entry", sa.String(length=120), nullable=True),
        sa.Column("benchmark_ticker", sa.String(length=32), nullable=True),
        sa.Column("entry_reason", sa.Text(), nullable=True),
        sa.Column("entry_trigger", sa.Text(), nullable=True),
        sa.Column("confirmation_condition", sa.Text(), nullable=True),
        sa.Column("notional_value", sa.Float(), nullable=True),
        sa.Column("stop_loss", sa.Float(), nullable=True),
        sa.Column("invalidation_level", sa.Float(), nullable=True),
        sa.Column("initial_target_1", sa.Float(), nullable=True),
        sa.Column("initial_target_2", sa.Float(), nullable=True),
        sa.Column("trailing_stop", sa.Text(), nullable=True),
        sa.Column("max_expected_loss", sa.Float(), nullable=True),
        sa.Column("exit_reason", sa.Text(), nullable=True),
        sa.Column("exit_trigger", sa.Text(), nullable=True),
        sa.Column("holding_days", sa.Integer(), nullable=True),
        sa.Column("gross_pnl_eur", sa.Float(), nullable=True),
        sa.Column("net_pnl_eur", sa.Float(), nullable=True),
        sa.Column("pnl_percent", sa.Float(), nullable=True),
        sa.Column("pnl_per_share", sa.Float(), nullable=True),
        sa.Column("max_favorable_excursion", sa.Float(), nullable=True),
        sa.Column("max_adverse_excursion", sa.Float(), nullable=True),
        sa.Column("target_1_hit", sa.Boolean(), nullable=True),
        sa.Column("target_2_hit", sa.Boolean(), nullable=True),
        sa.Column("invalidation_hit", sa.Boolean(), nullable=True),
        sa.Column("benchmark_return_same_period", sa.Float(), nullable=True),
        sa.Column("excess_return_vs_benchmark", sa.Float(), nullable=True),
        sa.Column("trade_quality_score", sa.Float(), nullable=True),
        sa.Column("data_quality_score", sa.Float(), nullable=True),
        sa.Column("outcome_label", sa.String(length=80), nullable=True),
        sa.Column("lesson_generated", sa.Text(), nullable=True),
    ]
    for column in trade_columns:
        add_column("trading_game_trades", column)

    for column in [
        "asset_type",
        "sector",
        "thesis_id",
        "actionability_state_at_entry",
        "market_regime_at_entry",
        "benchmark_ticker",
        "target_1_hit",
        "target_2_hit",
        "invalidation_hit",
        "trade_quality_score",
        "outcome_label",
    ]:
        create_index("trading_game_trades", [column])

    add_column("trading_game_equity_curve", sa.Column("event_type", sa.String(length=100), nullable=True))
    add_column("trading_game_equity_curve", sa.Column("related_trade_id", sa.Integer(), nullable=True))
    add_column("trading_game_equity_curve", sa.Column("annotation_payload", json_type, nullable=True))
    create_index("trading_game_equity_curve", ["event_type"])
    create_index("trading_game_equity_curve", ["related_trade_id"])

    op.create_table(
        "trade_engine_attributions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trade_id", sa.Integer(), nullable=False),
        sa.Column("engine_name", sa.String(length=120), nullable=False),
        sa.Column("vote", sa.String(length=80), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("contribution_score", sa.Float(), nullable=False),
        sa.Column("evidence_quality", sa.Float(), nullable=False),
        sa.Column("was_correct", sa.Boolean(), nullable=True),
        sa.Column("reliability_delta", sa.Float(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["trade_id"], ["trading_game_trades.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_id", "engine_name", name="uq_trade_engine_attribution_trade_engine"),
    )
    for column in ["trade_id", "engine_name", "vote", "confidence", "contribution_score", "was_correct", "created_at"]:
        create_index("trade_engine_attributions", [column])
    create_index("trade_engine_attributions", ["trade_id", "engine_name"], "trade_engine")

    op.create_table(
        "trade_quality_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trade_id", sa.Integer(), nullable=False),
        sa.Column("entry_quality", sa.Float(), nullable=False),
        sa.Column("exit_quality", sa.Float(), nullable=False),
        sa.Column("risk_reward_quality", sa.Float(), nullable=False),
        sa.Column("sizing_quality", sa.Float(), nullable=False),
        sa.Column("regime_alignment", sa.Float(), nullable=False),
        sa.Column("reproducibility_quality", sa.Float(), nullable=False),
        sa.Column("thesis_consistency", sa.Float(), nullable=False),
        sa.Column("benchmark_relative_quality", sa.Float(), nullable=False),
        sa.Column("rule_compliance", sa.Float(), nullable=False),
        sa.Column("luck_factor", sa.Float(), nullable=False),
        sa.Column("final_trade_quality_score", sa.Float(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["trade_id"], ["trading_game_trades.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_id", name="uq_trade_quality_scores_trade"),
    )
    for column in ["trade_id", "final_trade_quality_score", "created_at"]:
        create_index("trade_quality_scores", [column])
    create_index("trade_quality_scores", ["final_trade_quality_score", "created_at"], "final_created")

    op.create_table(
        "trade_learning_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trade_id", sa.Integer(), nullable=True),
        sa.Column("game_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("setup_type", sa.String(length=100), nullable=False),
        sa.Column("regime", sa.String(length=120), nullable=False),
        sa.Column("lesson_type", sa.String(length=120), nullable=False),
        sa.Column("observation", sa.Text(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("supporting_trades_json", json_type, nullable=False),
        sa.Column("contradicted_rules_json", json_type, nullable=False),
        sa.Column("proposed_rule_id", sa.Integer(), nullable=True),
        sa.Column("affected_module", sa.String(length=120), nullable=False),
        sa.Column("action_taken", sa.String(length=160), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["trading_games.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trade_id"], ["trading_game_trades.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ["trade_id", "game_id", "ticker", "setup_type", "regime", "lesson_type", "sample_size", "proposed_rule_id", "affected_module", "action_taken", "confidence", "created_at"]:
        create_index("trade_learning_evidence", [column])
    create_index("trade_learning_evidence", ["setup_type", "regime", "created_at"], "setup_regime")

    op.create_table(
        "trading_game_reality_checks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(), nullable=False),
        sa.Column("trades_count", sa.Integer(), nullable=False),
        sa.Column("unique_tickers", sa.Integer(), nullable=False),
        sa.Column("unique_sectors", sa.Integer(), nullable=False),
        sa.Column("unique_regimes", sa.Integer(), nullable=False),
        sa.Column("profit_concentration_top_1", sa.Float(), nullable=True),
        sa.Column("profit_concentration_top_3", sa.Float(), nullable=True),
        sa.Column("sample_quality_score", sa.Float(), nullable=False),
        sa.Column("realism_score", sa.Float(), nullable=False),
        sa.Column("statistical_confidence", sa.String(length=80), nullable=False),
        sa.Column("warnings_json", json_type, nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["trading_games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ["game_id", "evaluated_at", "trades_count", "sample_quality_score", "realism_score", "statistical_confidence"]:
        create_index("trading_game_reality_checks", [column])
    create_index("trading_game_reality_checks", ["game_id", "evaluated_at"], "game_eval")

    op.create_table(
        "equity_curve_annotations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("equity_curve_id", sa.Integer(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("label", sa.String(length=180), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("related_trade_id", sa.Integer(), nullable=True),
        sa.Column("related_thesis_id", sa.Integer(), nullable=True),
        sa.Column("pnl_impact", sa.Float(), nullable=True),
        sa.Column("capital_after_event", sa.Float(), nullable=True),
        sa.Column("payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["equity_curve_id"], ["trading_game_equity_curve.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["game_id"], ["trading_games.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["related_trade_id"], ["trading_game_trades.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ["game_id", "equity_curve_id", "timestamp", "event_type", "related_trade_id", "related_thesis_id", "created_at"]:
        create_index("equity_curve_annotations", [column])
    create_index("equity_curve_annotations", ["game_id", "timestamp"], "game_time")


def downgrade() -> None:
    op.drop_table("equity_curve_annotations")
    op.drop_table("trading_game_reality_checks")
    op.drop_table("trade_learning_evidence")
    op.drop_table("trade_quality_scores")
    op.drop_table("trade_engine_attributions")

    for column in ["event_type", "related_trade_id", "annotation_payload"]:
        op.drop_column("trading_game_equity_curve", column)

    for column in [
        "asset_name",
        "asset_type",
        "sector",
        "industry",
        "thesis_id",
        "sniper_score_at_entry",
        "opportunity_score_at_entry",
        "confidence_at_entry",
        "actionability_state_at_entry",
        "market_regime_at_entry",
        "sector_regime_at_entry",
        "benchmark_ticker",
        "entry_reason",
        "entry_trigger",
        "confirmation_condition",
        "notional_value",
        "stop_loss",
        "invalidation_level",
        "initial_target_1",
        "initial_target_2",
        "trailing_stop",
        "max_expected_loss",
        "exit_reason",
        "exit_trigger",
        "holding_days",
        "gross_pnl_eur",
        "net_pnl_eur",
        "pnl_percent",
        "pnl_per_share",
        "max_favorable_excursion",
        "max_adverse_excursion",
        "target_1_hit",
        "target_2_hit",
        "invalidation_hit",
        "benchmark_return_same_period",
        "excess_return_vs_benchmark",
        "trade_quality_score",
        "data_quality_score",
        "outcome_label",
        "lesson_generated",
    ]:
        op.drop_column("trading_game_trades", column)

    for column in ["ledger_summary", "reality_check_summary", "transparency_updated_at"]:
        op.drop_column("trading_games", column)
