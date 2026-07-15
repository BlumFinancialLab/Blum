from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0012_market_sniper_engine"
down_revision = "0011_blum_learning_loop"
branch_labels = None
depends_on = None


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "market_regime_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("regime_primary", sa.String(length=80), nullable=False),
        sa.Column("regime_secondary", sa.String(length=80), nullable=False),
        sa.Column("volatility_state", sa.String(length=80), nullable=False),
        sa.Column("breadth_state", sa.String(length=80), nullable=False),
        sa.Column("risk_appetite_score", sa.Float(), nullable=False),
        sa.Column("sector_rotation_score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("data_sources", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_market_regime_snapshots_date", "market_regime_snapshots", ["date"])
    op.create_index("ix_market_regime_snapshots_regime_primary", "market_regime_snapshots", ["regime_primary"])
    op.create_index("ix_market_regime_snapshots_regime_secondary", "market_regime_snapshots", ["regime_secondary"])
    op.create_index("ix_market_regime_snapshots_volatility_state", "market_regime_snapshots", ["volatility_state"])
    op.create_index("ix_market_regime_snapshots_breadth_state", "market_regime_snapshots", ["breadth_state"])
    op.create_index("ix_market_regime_snapshots_risk_appetite_score", "market_regime_snapshots", ["risk_appetite_score"])
    op.create_index("ix_market_regime_snapshots_sector_rotation_score", "market_regime_snapshots", ["sector_rotation_score"])
    op.create_index("ix_market_regime_snapshots_confidence", "market_regime_snapshots", ["confidence"])
    op.create_index("ix_market_regime_snapshots_created_at", "market_regime_snapshots", ["created_at"])
    op.create_index("ix_market_regime_snapshots_date_created", "market_regime_snapshots", ["date", "created_at"])

    op.create_table(
        "setup_library",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("setup_type", sa.String(length=100), nullable=False),
        sa.Column("setup_quality_score", sa.Float(), nullable=False),
        sa.Column("setup_maturity", sa.String(length=80), nullable=False),
        sa.Column("required_confirmation", sa.Text(), nullable=False),
        sa.Column("invalidation_logic", sa.Text(), nullable=False),
        sa.Column("best_timeframe", sa.String(length=80), nullable=False),
        sa.Column("historical_reliability", sa.Float(), nullable=False),
        sa.Column("regime_sensitivity", json_type, nullable=False),
        sa.Column("common_failure_modes", json_type, nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("setup_type", name="uq_setup_library_setup_type"),
    )
    op.create_index("ix_setup_library_setup_type", "setup_library", ["setup_type"])
    op.create_index("ix_setup_library_setup_quality_score", "setup_library", ["setup_quality_score"])
    op.create_index("ix_setup_library_setup_maturity", "setup_library", ["setup_maturity"])
    op.create_index("ix_setup_library_best_timeframe", "setup_library", ["best_timeframe"])
    op.create_index("ix_setup_library_historical_reliability", "setup_library", ["historical_reliability"])
    op.create_index("ix_setup_library_updated_at", "setup_library", ["updated_at"])
    op.create_index("ix_setup_library_created_at", "setup_library", ["created_at"])
    op.create_index("ix_setup_library_quality_reliability", "setup_library", ["setup_quality_score", "historical_reliability"])

    op.create_table(
        "sniper_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("setup_type", sa.String(length=100), nullable=False),
        sa.Column("sniper_score", sa.Float(), nullable=False),
        sa.Column("actionability", sa.String(length=80), nullable=False),
        sa.Column("components", json_type, nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("data_quality_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sniper_scores_asset_id", "sniper_scores", ["asset_id"])
    op.create_index("ix_sniper_scores_ticker", "sniper_scores", ["ticker"])
    op.create_index("ix_sniper_scores_setup_type", "sniper_scores", ["setup_type"])
    op.create_index("ix_sniper_scores_sniper_score", "sniper_scores", ["sniper_score"])
    op.create_index("ix_sniper_scores_actionability", "sniper_scores", ["actionability"])
    op.create_index("ix_sniper_scores_confidence", "sniper_scores", ["confidence"])
    op.create_index("ix_sniper_scores_data_quality_score", "sniper_scores", ["data_quality_score"])
    op.create_index("ix_sniper_scores_created_at", "sniper_scores", ["created_at"])
    op.create_index("ix_sniper_scores_ticker_created", "sniper_scores", ["ticker", "created_at"])

    op.create_table(
        "trade_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("sniper_score_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("setup_type", sa.String(length=100), nullable=False),
        sa.Column("actionability", sa.String(length=80), nullable=False),
        sa.Column("timeframe", sa.String(length=80), nullable=False),
        sa.Column("entry_zone", json_type, nullable=False),
        sa.Column("entry_trigger", sa.Text(), nullable=False),
        sa.Column("confirmation_condition", sa.Text(), nullable=False),
        sa.Column("invalidation_level", sa.Float(), nullable=True),
        sa.Column("stop_logic", sa.Text(), nullable=False),
        sa.Column("target_1", sa.Float(), nullable=True),
        sa.Column("target_2", sa.Float(), nullable=True),
        sa.Column("trailing_exit_logic", sa.Text(), nullable=False),
        sa.Column("partial_exit_logic", sa.Text(), nullable=False),
        sa.Column("no_trade_conditions", json_type, nullable=False),
        sa.Column("expected_holding_period", sa.String(length=80), nullable=False),
        sa.Column("risk_reward_estimate", json_type, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("historical_setup_reliability", sa.Float(), nullable=False),
        sa.Column("disclaimer", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sniper_score_id"], ["sniper_scores.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name in ["asset_id", "sniper_score_id", "ticker", "setup_type", "actionability", "timeframe", "confidence", "created_at"]:
        op.create_index(f"ix_trade_plans_{name}", "trade_plans", [name])
    op.create_index("ix_trade_plans_ticker_created", "trade_plans", ["ticker", "created_at"])

    op.create_table(
        "trade_plan_outcomes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trade_plan_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("setup_type", sa.String(length=100), nullable=False),
        sa.Column("timeframe", sa.String(length=40), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=True),
        sa.Column("exit_date", sa.Date(), nullable=True),
        sa.Column("entry_price", sa.Float(), nullable=True),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("realized_r_multiple", sa.Float(), nullable=True),
        sa.Column("max_adverse_excursion", sa.Float(), nullable=True),
        sa.Column("max_favorable_excursion", sa.Float(), nullable=True),
        sa.Column("outcome_label", sa.String(length=80), nullable=False),
        sa.Column("payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["trade_plan_id"], ["trade_plans.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name in ["trade_plan_id", "ticker", "setup_type", "timeframe", "entry_date", "exit_date", "realized_r_multiple", "outcome_label", "created_at"]:
        op.create_index(f"ix_trade_plan_outcomes_{name}", "trade_plan_outcomes", [name])
    op.create_index("ix_trade_plan_outcomes_ticker_timeframe", "trade_plan_outcomes", ["ticker", "timeframe"])

    op.create_table(
        "execution_simulations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trade_plan_id", sa.Integer(), nullable=True),
        sa.Column("prediction_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("setup_type", sa.String(length=100), nullable=False),
        sa.Column("simulation_mode", sa.String(length=80), nullable=False),
        sa.Column("entry_model", sa.String(length=80), nullable=False),
        sa.Column("exit_model", sa.String(length=80), nullable=False),
        sa.Column("realized_r_multiple", sa.Float(), nullable=True),
        sa.Column("max_adverse_excursion", sa.Float(), nullable=True),
        sa.Column("max_favorable_excursion", sa.Float(), nullable=True),
        sa.Column("time_in_trade", sa.Integer(), nullable=True),
        sa.Column("stop_hit", sa.Boolean(), nullable=False),
        sa.Column("target_hit", sa.Boolean(), nullable=False),
        sa.Column("trailing_exit_hit", sa.Boolean(), nullable=False),
        sa.Column("missed_entry", sa.Boolean(), nullable=False),
        sa.Column("false_breakout", sa.Boolean(), nullable=False),
        sa.Column("failed_confirmation", sa.Boolean(), nullable=False),
        sa.Column("opportunity_cost", sa.Float(), nullable=True),
        sa.Column("simulation_payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["prediction_id"], ["historical_predictions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["trade_plan_id"], ["trade_plans.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name in ["trade_plan_id", "prediction_id", "ticker", "setup_type", "simulation_mode", "entry_model", "exit_model", "realized_r_multiple", "stop_hit", "target_hit", "trailing_exit_hit", "missed_entry", "false_breakout", "failed_confirmation", "created_at"]:
        op.create_index(f"ix_execution_simulations_{name}", "execution_simulations", [name])
    op.create_index("ix_execution_simulations_ticker_created", "execution_simulations", ["ticker", "created_at"])

    op.create_table(
        "r_multiple_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("setup_type", sa.String(length=100), nullable=False),
        sa.Column("timeframe", sa.String(length=40), nullable=False),
        sa.Column("market_regime", sa.String(length=80), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("hit_rate", sa.Float(), nullable=True),
        sa.Column("average_r", sa.Float(), nullable=True),
        sa.Column("median_r", sa.Float(), nullable=True),
        sa.Column("max_drawdown_r", sa.Float(), nullable=True),
        sa.Column("profit_factor", sa.Float(), nullable=True),
        sa.Column("payoff_ratio", sa.Float(), nullable=True),
        sa.Column("expectancy_r", sa.Float(), nullable=True),
        sa.Column("evidence", json_type, nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("setup_type", "timeframe", "market_regime", "sector", name="uq_r_metric_setup_timeframe_regime_sector"),
    )
    for name in ["setup_type", "timeframe", "market_regime", "sector", "sample_count", "expectancy_r", "updated_at", "created_at"]:
        op.create_index(f"ix_r_multiple_metrics_{name}", "r_multiple_metrics", [name])
    op.create_index("ix_r_multiple_metrics_expectancy", "r_multiple_metrics", ["expectancy_r"])

    op.create_table(
        "signal_reliability_matrix",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("signal_name", sa.String(length=120), nullable=False),
        sa.Column("setup_type", sa.String(length=100), nullable=False),
        sa.Column("timeframe", sa.String(length=40), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=False),
        sa.Column("market_regime", sa.String(length=80), nullable=False),
        sa.Column("volatility_state", sa.String(length=80), nullable=False),
        sa.Column("asset_class", sa.String(length=40), nullable=False),
        sa.Column("liquidity_bucket", sa.String(length=80), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("correct_count", sa.Integer(), nullable=False),
        sa.Column("false_positive_count", sa.Integer(), nullable=False),
        sa.Column("average_r", sa.Float(), nullable=True),
        sa.Column("expectancy_r", sa.Float(), nullable=True),
        sa.Column("reliability_score", sa.Float(), nullable=False),
        sa.Column("evidence", json_type, nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("signal_name", "setup_type", "timeframe", "sector", "market_regime", "volatility_state", "asset_class", "liquidity_bucket", name="uq_signal_reliability_context"),
    )
    for name in ["signal_name", "setup_type", "timeframe", "sector", "market_regime", "volatility_state", "asset_class", "liquidity_bucket", "sample_count", "expectancy_r", "reliability_score", "updated_at", "created_at"]:
        op.create_index(f"ix_signal_reliability_matrix_{name}", "signal_reliability_matrix", [name])
    op.create_index("ix_signal_reliability_matrix_score", "signal_reliability_matrix", ["reliability_score"])

    op.create_table(
        "no_trade_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("trade_plan_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("setup_type", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("conditions", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["trade_plan_id"], ["trade_plans.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name in ["asset_id", "trade_plan_id", "ticker", "setup_type", "severity", "created_at"]:
        op.create_index(f"ix_no_trade_decisions_{name}", "no_trade_decisions", [name])
    op.create_index("ix_no_trade_decisions_ticker_created", "no_trade_decisions", ["ticker", "created_at"])

    op.create_table(
        "exit_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("trade_plan_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("exit_type", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["trade_plan_id"], ["trade_plans.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name in ["asset_id", "trade_plan_id", "ticker", "exit_type", "action", "confidence", "created_at"]:
        op.create_index(f"ix_exit_signals_{name}", "exit_signals", [name])
    op.create_index("ix_exit_signals_ticker_created", "exit_signals", ["ticker", "created_at"])

    op.create_table(
        "portfolio_risk_context",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("context_name", sa.String(length=120), nullable=False),
        sa.Column("sector_concentration", json_type, nullable=False),
        sa.Column("factor_concentration", json_type, nullable=False),
        sa.Column("correlation", json_type, nullable=False),
        sa.Column("beta", json_type, nullable=False),
        sa.Column("volatility_contribution", json_type, nullable=False),
        sa.Column("overlapping_etf_exposure", json_type, nullable=False),
        sa.Column("max_simultaneous_setups", sa.Integer(), nullable=False),
        sa.Column("risk_per_theme", json_type, nullable=False),
        sa.Column("risk_per_regime", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_portfolio_risk_context_context_name", "portfolio_risk_context", ["context_name"])
    op.create_index("ix_portfolio_risk_context_created_at", "portfolio_risk_context", ["created_at"])
    op.create_index("ix_portfolio_risk_context_created", "portfolio_risk_context", ["created_at"])


def downgrade() -> None:
    for table in [
        "portfolio_risk_context",
        "exit_signals",
        "no_trade_decisions",
        "signal_reliability_matrix",
        "r_multiple_metrics",
        "execution_simulations",
        "trade_plan_outcomes",
        "trade_plans",
        "sniper_scores",
        "setup_library",
        "market_regime_snapshots",
    ]:
        op.drop_table(table)
