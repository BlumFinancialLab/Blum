from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0011_blum_learning_loop"
down_revision = "0010_financial_chat_memory"
branch_labels = None
depends_on = None


json_type = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "learning_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=100), nullable=False),
        sa.Column("trigger", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("evaluation_mode", sa.String(length=80), nullable=False),
        sa.Column("asset_universe", sa.String(length=120), nullable=False),
        sa.Column("batch_size", sa.Integer(), nullable=False),
        sa.Column("predictions_created", sa.Integer(), nullable=False),
        sa.Column("outcomes_evaluated", sa.Integer(), nullable=False),
        sa.Column("mistakes_found", sa.Integer(), nullable=False),
        sa.Column("memory_updates", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("summary", json_type, nullable=False),
        sa.Column("anti_overfitting_report", json_type, nullable=False),
        sa.Column("error_payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_learning_run_id"),
    )
    op.create_index("ix_learning_runs_run_id", "learning_runs", ["run_id"])
    op.create_index("ix_learning_runs_status", "learning_runs", ["status"])
    op.create_index("ix_learning_runs_trigger", "learning_runs", ["trigger"])
    op.create_index("ix_learning_runs_evaluation_mode", "learning_runs", ["evaluation_mode"])
    op.create_index("ix_learning_runs_asset_universe", "learning_runs", ["asset_universe"])
    op.create_index("ix_learning_runs_started_at", "learning_runs", ["started_at"])
    op.create_index("ix_learning_runs_created_at", "learning_runs", ["created_at"])
    op.create_index("ix_learning_runs_status_started", "learning_runs", ["status", "started_at"])

    op.create_table(
        "historical_predictions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("learning_run_id", sa.Integer(), nullable=True),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("asset_type", sa.String(length=40), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=False),
        sa.Column("market", sa.String(length=80), nullable=False),
        sa.Column("market_regime", sa.String(length=120), nullable=False),
        sa.Column("volatility_regime", sa.String(length=80), nullable=False),
        sa.Column("analysis_date", sa.Date(), nullable=False),
        sa.Column("initial_price", sa.Float(), nullable=True),
        sa.Column("prediction_payload", json_type, nullable=False),
        sa.Column("point_in_time_context", json_type, nullable=False),
        sa.Column("expected_direction", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("model_version", sa.String(length=80), nullable=False),
        sa.Column("data_quality_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["learning_run_id"], ["learning_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_historical_predictions_learning_run_id", "historical_predictions", ["learning_run_id"])
    op.create_index("ix_historical_predictions_asset_id", "historical_predictions", ["asset_id"])
    op.create_index("ix_historical_predictions_ticker", "historical_predictions", ["ticker"])
    op.create_index("ix_historical_predictions_asset_type", "historical_predictions", ["asset_type"])
    op.create_index("ix_historical_predictions_sector", "historical_predictions", ["sector"])
    op.create_index("ix_historical_predictions_market", "historical_predictions", ["market"])
    op.create_index("ix_historical_predictions_market_regime", "historical_predictions", ["market_regime"])
    op.create_index("ix_historical_predictions_volatility_regime", "historical_predictions", ["volatility_regime"])
    op.create_index("ix_historical_predictions_analysis_date", "historical_predictions", ["analysis_date"])
    op.create_index("ix_historical_predictions_expected_direction", "historical_predictions", ["expected_direction"])
    op.create_index("ix_historical_predictions_confidence", "historical_predictions", ["confidence"])
    op.create_index("ix_historical_predictions_model_version", "historical_predictions", ["model_version"])
    op.create_index("ix_historical_predictions_data_quality_score", "historical_predictions", ["data_quality_score"])
    op.create_index("ix_historical_predictions_created_at", "historical_predictions", ["created_at"])
    op.create_index("ix_historical_predictions_ticker_date", "historical_predictions", ["ticker", "analysis_date"])
    op.create_index("ix_historical_predictions_run_created", "historical_predictions", ["learning_run_id", "created_at"])

    op.create_table(
        "prediction_outcomes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("prediction_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=40), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("evaluation_date", sa.Date(), nullable=True),
        sa.Column("price_at_evaluation", sa.Float(), nullable=True),
        sa.Column("realized_return", sa.Float(), nullable=True),
        sa.Column("max_favorable_excursion", sa.Float(), nullable=True),
        sa.Column("max_adverse_excursion", sa.Float(), nullable=True),
        sa.Column("drawdown", sa.Float(), nullable=True),
        sa.Column("time_to_target", sa.Integer(), nullable=True),
        sa.Column("time_to_invalidation", sa.Integer(), nullable=True),
        sa.Column("target_hit", sa.Boolean(), nullable=False),
        sa.Column("invalidation_hit", sa.Boolean(), nullable=False),
        sa.Column("direction_correct", sa.Boolean(), nullable=True),
        sa.Column("false_positive", sa.Boolean(), nullable=False),
        sa.Column("false_negative", sa.Boolean(), nullable=False),
        sa.Column("missed_opportunity", sa.Boolean(), nullable=False),
        sa.Column("outcome_label", sa.String(length=40), nullable=False),
        sa.Column("confidence_calibration_error", sa.Float(), nullable=True),
        sa.Column("metrics_payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["prediction_id"], ["historical_predictions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prediction_id", "timeframe", name="uq_prediction_outcome_prediction_timeframe"),
    )
    op.create_index("ix_prediction_outcomes_prediction_id", "prediction_outcomes", ["prediction_id"])
    op.create_index("ix_prediction_outcomes_ticker", "prediction_outcomes", ["ticker"])
    op.create_index("ix_prediction_outcomes_timeframe", "prediction_outcomes", ["timeframe"])
    op.create_index("ix_prediction_outcomes_horizon_days", "prediction_outcomes", ["horizon_days"])
    op.create_index("ix_prediction_outcomes_evaluation_date", "prediction_outcomes", ["evaluation_date"])
    op.create_index("ix_prediction_outcomes_realized_return", "prediction_outcomes", ["realized_return"])
    op.create_index("ix_prediction_outcomes_target_hit", "prediction_outcomes", ["target_hit"])
    op.create_index("ix_prediction_outcomes_invalidation_hit", "prediction_outcomes", ["invalidation_hit"])
    op.create_index("ix_prediction_outcomes_direction_correct", "prediction_outcomes", ["direction_correct"])
    op.create_index("ix_prediction_outcomes_false_positive", "prediction_outcomes", ["false_positive"])
    op.create_index("ix_prediction_outcomes_false_negative", "prediction_outcomes", ["false_negative"])
    op.create_index("ix_prediction_outcomes_missed_opportunity", "prediction_outcomes", ["missed_opportunity"])
    op.create_index("ix_prediction_outcomes_outcome_label", "prediction_outcomes", ["outcome_label"])
    op.create_index("ix_prediction_outcomes_created_at", "prediction_outcomes", ["created_at"])
    op.create_index("ix_prediction_outcomes_ticker_timeframe", "prediction_outcomes", ["ticker", "timeframe"])

    op.create_table(
        "mistake_analysis",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("prediction_id", sa.Integer(), nullable=True),
        sa.Column("outcome_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=40), nullable=False),
        sa.Column("error_type", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("predicted", json_type, nullable=False),
        sa.Column("actual", json_type, nullable=False),
        sa.Column("misleading_signal", sa.Text(), nullable=False),
        sa.Column("signal_to_weight_more", sa.Text(), nullable=False),
        sa.Column("rule_adjustment", sa.Text(), nullable=False),
        sa.Column("future_impact", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["outcome_id"], ["prediction_outcomes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prediction_id"], ["historical_predictions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mistake_analysis_prediction_id", "mistake_analysis", ["prediction_id"])
    op.create_index("ix_mistake_analysis_outcome_id", "mistake_analysis", ["outcome_id"])
    op.create_index("ix_mistake_analysis_ticker", "mistake_analysis", ["ticker"])
    op.create_index("ix_mistake_analysis_timeframe", "mistake_analysis", ["timeframe"])
    op.create_index("ix_mistake_analysis_error_type", "mistake_analysis", ["error_type"])
    op.create_index("ix_mistake_analysis_severity", "mistake_analysis", ["severity"])
    op.create_index("ix_mistake_analysis_created_at", "mistake_analysis", ["created_at"])
    op.create_index("ix_mistake_analysis_error_created", "mistake_analysis", ["error_type", "created_at"])

    op.create_table(
        "signal_performance",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("signal_name", sa.String(length=120), nullable=False),
        sa.Column("timeframe", sa.String(length=40), nullable=False),
        sa.Column("market_regime", sa.String(length=120), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("correct_count", sa.Integer(), nullable=False),
        sa.Column("false_positive_count", sa.Integer(), nullable=False),
        sa.Column("false_negative_count", sa.Integer(), nullable=False),
        sa.Column("average_return", sa.Float(), nullable=True),
        sa.Column("average_drawdown", sa.Float(), nullable=True),
        sa.Column("profit_factor", sa.Float(), nullable=True),
        sa.Column("reliability_score", sa.Float(), nullable=False),
        sa.Column("weight_adjustment", sa.Float(), nullable=False),
        sa.Column("evidence", json_type, nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("signal_name", "timeframe", "market_regime", name="uq_signal_performance_signal_timeframe_regime"),
    )
    op.create_index("ix_signal_performance_signal_name", "signal_performance", ["signal_name"])
    op.create_index("ix_signal_performance_timeframe", "signal_performance", ["timeframe"])
    op.create_index("ix_signal_performance_market_regime", "signal_performance", ["market_regime"])
    op.create_index("ix_signal_performance_sample_count", "signal_performance", ["sample_count"])
    op.create_index("ix_signal_performance_reliability_score", "signal_performance", ["reliability_score"])
    op.create_index("ix_signal_performance_updated_at", "signal_performance", ["updated_at"])
    op.create_index("ix_signal_performance_created_at", "signal_performance", ["created_at"])
    op.create_index("ix_signal_performance_reliability", "signal_performance", ["reliability_score"])

    op.create_table(
        "strategy_memory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("memory_key", sa.String(length=180), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("lesson", sa.Text(), nullable=False),
        sa.Column("conditions", json_type, nullable=False),
        sa.Column("reliability_score", sa.Float(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("positive_count", sa.Integer(), nullable=False),
        sa.Column("negative_count", sa.Integer(), nullable=False),
        sa.Column("evidence", json_type, nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("memory_key", name="uq_strategy_memory_key"),
    )
    op.create_index("ix_strategy_memory_memory_key", "strategy_memory", ["memory_key"])
    op.create_index("ix_strategy_memory_category", "strategy_memory", ["category"])
    op.create_index("ix_strategy_memory_reliability_score", "strategy_memory", ["reliability_score"])
    op.create_index("ix_strategy_memory_last_seen_at", "strategy_memory", ["last_seen_at"])
    op.create_index("ix_strategy_memory_created_at", "strategy_memory", ["created_at"])
    op.create_index("ix_strategy_memory_updated_at", "strategy_memory", ["updated_at"])
    op.create_index("ix_strategy_memory_category_reliability", "strategy_memory", ["category", "reliability_score"])

    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=160), nullable=False),
        sa.Column("weights", json_type, nullable=False),
        sa.Column("previous_weights", json_type, nullable=False),
        sa.Column("training_window", json_type, nullable=False),
        sa.Column("validation_metrics", json_type, nullable=False),
        sa.Column("anti_overfitting_report", json_type, nullable=False),
        sa.Column("change_log", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version"),
    )
    op.create_index("ix_model_versions_version", "model_versions", ["version"])
    op.create_index("ix_model_versions_model_name", "model_versions", ["model_name"])
    op.create_index("ix_model_versions_is_active", "model_versions", ["is_active"])
    op.create_index("ix_model_versions_created_at", "model_versions", ["created_at"])
    op.create_index("ix_model_versions_active_created", "model_versions", ["is_active", "created_at"])

    op.create_table(
        "learning_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("metric_name", sa.String(length=120), nullable=False),
        sa.Column("timeframe", sa.String(length=40), nullable=False),
        sa.Column("market_regime", sa.String(length=120), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_learning_metrics_metric_name", "learning_metrics", ["metric_name"])
    op.create_index("ix_learning_metrics_timeframe", "learning_metrics", ["timeframe"])
    op.create_index("ix_learning_metrics_market_regime", "learning_metrics", ["market_regime"])
    op.create_index("ix_learning_metrics_created_at", "learning_metrics", ["created_at"])
    op.create_index("ix_learning_metrics_name_timeframe_created", "learning_metrics", ["metric_name", "timeframe", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_learning_metrics_name_timeframe_created", table_name="learning_metrics")
    op.drop_index("ix_learning_metrics_created_at", table_name="learning_metrics")
    op.drop_index("ix_learning_metrics_market_regime", table_name="learning_metrics")
    op.drop_index("ix_learning_metrics_timeframe", table_name="learning_metrics")
    op.drop_index("ix_learning_metrics_metric_name", table_name="learning_metrics")
    op.drop_table("learning_metrics")

    op.drop_index("ix_model_versions_active_created", table_name="model_versions")
    op.drop_index("ix_model_versions_created_at", table_name="model_versions")
    op.drop_index("ix_model_versions_is_active", table_name="model_versions")
    op.drop_index("ix_model_versions_model_name", table_name="model_versions")
    op.drop_index("ix_model_versions_version", table_name="model_versions")
    op.drop_table("model_versions")

    op.drop_index("ix_strategy_memory_category_reliability", table_name="strategy_memory")
    op.drop_index("ix_strategy_memory_updated_at", table_name="strategy_memory")
    op.drop_index("ix_strategy_memory_created_at", table_name="strategy_memory")
    op.drop_index("ix_strategy_memory_last_seen_at", table_name="strategy_memory")
    op.drop_index("ix_strategy_memory_reliability_score", table_name="strategy_memory")
    op.drop_index("ix_strategy_memory_category", table_name="strategy_memory")
    op.drop_index("ix_strategy_memory_memory_key", table_name="strategy_memory")
    op.drop_table("strategy_memory")

    op.drop_index("ix_signal_performance_reliability", table_name="signal_performance")
    op.drop_index("ix_signal_performance_created_at", table_name="signal_performance")
    op.drop_index("ix_signal_performance_updated_at", table_name="signal_performance")
    op.drop_index("ix_signal_performance_reliability_score", table_name="signal_performance")
    op.drop_index("ix_signal_performance_sample_count", table_name="signal_performance")
    op.drop_index("ix_signal_performance_market_regime", table_name="signal_performance")
    op.drop_index("ix_signal_performance_timeframe", table_name="signal_performance")
    op.drop_index("ix_signal_performance_signal_name", table_name="signal_performance")
    op.drop_table("signal_performance")

    op.drop_index("ix_mistake_analysis_error_created", table_name="mistake_analysis")
    op.drop_index("ix_mistake_analysis_created_at", table_name="mistake_analysis")
    op.drop_index("ix_mistake_analysis_severity", table_name="mistake_analysis")
    op.drop_index("ix_mistake_analysis_error_type", table_name="mistake_analysis")
    op.drop_index("ix_mistake_analysis_timeframe", table_name="mistake_analysis")
    op.drop_index("ix_mistake_analysis_ticker", table_name="mistake_analysis")
    op.drop_index("ix_mistake_analysis_outcome_id", table_name="mistake_analysis")
    op.drop_index("ix_mistake_analysis_prediction_id", table_name="mistake_analysis")
    op.drop_table("mistake_analysis")

    op.drop_index("ix_prediction_outcomes_ticker_timeframe", table_name="prediction_outcomes")
    op.drop_index("ix_prediction_outcomes_created_at", table_name="prediction_outcomes")
    op.drop_index("ix_prediction_outcomes_outcome_label", table_name="prediction_outcomes")
    op.drop_index("ix_prediction_outcomes_missed_opportunity", table_name="prediction_outcomes")
    op.drop_index("ix_prediction_outcomes_false_negative", table_name="prediction_outcomes")
    op.drop_index("ix_prediction_outcomes_false_positive", table_name="prediction_outcomes")
    op.drop_index("ix_prediction_outcomes_direction_correct", table_name="prediction_outcomes")
    op.drop_index("ix_prediction_outcomes_invalidation_hit", table_name="prediction_outcomes")
    op.drop_index("ix_prediction_outcomes_target_hit", table_name="prediction_outcomes")
    op.drop_index("ix_prediction_outcomes_realized_return", table_name="prediction_outcomes")
    op.drop_index("ix_prediction_outcomes_evaluation_date", table_name="prediction_outcomes")
    op.drop_index("ix_prediction_outcomes_horizon_days", table_name="prediction_outcomes")
    op.drop_index("ix_prediction_outcomes_timeframe", table_name="prediction_outcomes")
    op.drop_index("ix_prediction_outcomes_ticker", table_name="prediction_outcomes")
    op.drop_index("ix_prediction_outcomes_prediction_id", table_name="prediction_outcomes")
    op.drop_table("prediction_outcomes")

    op.drop_index("ix_historical_predictions_run_created", table_name="historical_predictions")
    op.drop_index("ix_historical_predictions_ticker_date", table_name="historical_predictions")
    op.drop_index("ix_historical_predictions_created_at", table_name="historical_predictions")
    op.drop_index("ix_historical_predictions_data_quality_score", table_name="historical_predictions")
    op.drop_index("ix_historical_predictions_model_version", table_name="historical_predictions")
    op.drop_index("ix_historical_predictions_confidence", table_name="historical_predictions")
    op.drop_index("ix_historical_predictions_expected_direction", table_name="historical_predictions")
    op.drop_index("ix_historical_predictions_analysis_date", table_name="historical_predictions")
    op.drop_index("ix_historical_predictions_volatility_regime", table_name="historical_predictions")
    op.drop_index("ix_historical_predictions_market_regime", table_name="historical_predictions")
    op.drop_index("ix_historical_predictions_market", table_name="historical_predictions")
    op.drop_index("ix_historical_predictions_sector", table_name="historical_predictions")
    op.drop_index("ix_historical_predictions_asset_type", table_name="historical_predictions")
    op.drop_index("ix_historical_predictions_ticker", table_name="historical_predictions")
    op.drop_index("ix_historical_predictions_asset_id", table_name="historical_predictions")
    op.drop_index("ix_historical_predictions_learning_run_id", table_name="historical_predictions")
    op.drop_table("historical_predictions")

    op.drop_index("ix_learning_runs_status_started", table_name="learning_runs")
    op.drop_index("ix_learning_runs_created_at", table_name="learning_runs")
    op.drop_index("ix_learning_runs_started_at", table_name="learning_runs")
    op.drop_index("ix_learning_runs_asset_universe", table_name="learning_runs")
    op.drop_index("ix_learning_runs_evaluation_mode", table_name="learning_runs")
    op.drop_index("ix_learning_runs_trigger", table_name="learning_runs")
    op.drop_index("ix_learning_runs_status", table_name="learning_runs")
    op.drop_index("ix_learning_runs_run_id", table_name="learning_runs")
    op.drop_table("learning_runs")
