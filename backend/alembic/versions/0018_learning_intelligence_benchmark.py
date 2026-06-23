from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0018_learning_intelligence_benchmark"
down_revision = "0017_trading_intelligence_lab"
branch_labels = None
depends_on = None


json_type = postgresql.JSONB(astext_type=sa.Text())


def create_index(table: str, columns: list[str], suffix: str | None = None) -> None:
    name = f"ix_{table}_{suffix or '_'.join(columns)}"
    if len(name) > 63:
        name = f"ix_{table[:30]}_{(suffix or '_'.join(columns))[:22]}"
    op.create_index(name, table, columns)


def upgrade() -> None:
    op.create_table(
        "blum_trading_power_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("mode", sa.String(length=80), nullable=False),
        sa.Column("scope", sa.String(length=120), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("classification", sa.String(length=120), nullable=False),
        sa.Column("benchmark_relative_score", sa.Float(), nullable=False),
        sa.Column("expectancy_score", sa.Float(), nullable=False),
        sa.Column("drawdown_control_score", sa.Float(), nullable=False),
        sa.Column("win_loss_quality_score", sa.Float(), nullable=False),
        sa.Column("missed_entry_penalty", sa.Float(), nullable=False),
        sa.Column("risk_management_score", sa.Float(), nullable=False),
        sa.Column("capital_cycle_score", sa.Float(), nullable=False),
        sa.Column("live_forward_validation_score", sa.Float(), nullable=False),
        sa.Column("regime_robustness_score", sa.Float(), nullable=False),
        sa.Column("setup_diversity_score", sa.Float(), nullable=False),
        sa.Column("statistical_confidence_score", sa.Float(), nullable=False),
        sa.Column("reproducibility_score", sa.Float(), nullable=False),
        sa.Column("decision_quality_score", sa.Float(), nullable=False),
        sa.Column("learning_velocity_score", sa.Float(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("warnings_json", json_type, nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("blum_trading_power_scores", ["mode", "calculated_at"], "mode_created")
    create_index("blum_trading_power_scores", ["scope", "score"], "scope_score")

    op.create_table(
        "learning_benchmark_comparisons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("mode", sa.String(length=80), nullable=False),
        sa.Column("benchmark_name", sa.String(length=120), nullable=False),
        sa.Column("benchmark_type", sa.String(length=80), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("blum_return", sa.Float(), nullable=True),
        sa.Column("benchmark_return", sa.Float(), nullable=True),
        sa.Column("excess_return", sa.Float(), nullable=True),
        sa.Column("blum_max_drawdown", sa.Float(), nullable=True),
        sa.Column("benchmark_max_drawdown", sa.Float(), nullable=True),
        sa.Column("blum_volatility", sa.Float(), nullable=True),
        sa.Column("benchmark_volatility", sa.Float(), nullable=True),
        sa.Column("sharpe_proxy", sa.Float(), nullable=True),
        sa.Column("sortino_proxy", sa.Float(), nullable=True),
        sa.Column("calmar_proxy", sa.Float(), nullable=True),
        sa.Column("information_ratio_proxy", sa.Float(), nullable=True),
        sa.Column("hit_rate_vs_benchmark", sa.Float(), nullable=True),
        sa.Column("risk_adjusted_advantage", sa.Float(), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("statistical_confidence", sa.String(length=80), nullable=False),
        sa.Column("result_label", sa.String(length=80), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("learning_benchmark_comparisons", ["mode", "benchmark_name", "calculated_at"], "mode_name_created")
    create_index("learning_benchmark_comparisons", ["result_label", "statistical_confidence"], "result_confidence")

    op.create_table(
        "learning_progress_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("window_type", sa.String(length=80), nullable=False),
        sa.Column("window_size", sa.Integer(), nullable=True),
        sa.Column("trades_count", sa.Integer(), nullable=False),
        sa.Column("win_rate", sa.Float(), nullable=True),
        sa.Column("missed_entry_rate", sa.Float(), nullable=True),
        sa.Column("loss_rate", sa.Float(), nullable=True),
        sa.Column("target_hit_rate", sa.Float(), nullable=True),
        sa.Column("stop_hit_rate", sa.Float(), nullable=True),
        sa.Column("expectancy_r", sa.Float(), nullable=True),
        sa.Column("benchmark_excess", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("trade_quality_avg", sa.Float(), nullable=True),
        sa.Column("confidence_calibration_error", sa.Float(), nullable=True),
        sa.Column("repeated_mistake_rate", sa.Float(), nullable=True),
        sa.Column("intelligence_growth_score", sa.Float(), nullable=False),
        sa.Column("trend_label", sa.String(length=80), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("learning_progress_snapshots", ["window_type", "window_size", "calculated_at"], "window_created")
    create_index("learning_progress_snapshots", ["trend_label", "intelligence_growth_score"], "trend_score")

    op.create_table(
        "learning_strength_weakness_map",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("dimension", sa.String(length=80), nullable=False),
        sa.Column("entity", sa.String(length=180), nullable=False),
        sa.Column("strength_score", sa.Float(), nullable=False),
        sa.Column("weakness_score", sa.Float(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("evidence", json_type, nullable=True),
        sa.Column("main_problem", sa.Text(), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("learning_strength_weakness_map", ["dimension", "entity"], "dimension_entity")
    create_index("learning_strength_weakness_map", ["priority", "weakness_score"], "priority_weakness")

    op.create_table(
        "self_improvement_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("source_metric", sa.String(length=120), nullable=False),
        sa.Column("source_dimension", sa.String(length=120), nullable=False),
        sa.Column("detected_problem", sa.Text(), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("affected_module", sa.String(length=120), nullable=False),
        sa.Column("priority", sa.String(length=40), nullable=False),
        sa.Column("expected_impact", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("before_metric", sa.Float(), nullable=True),
        sa.Column("after_metric", sa.Float(), nullable=True),
        sa.Column("improvement_observed", sa.Boolean(), nullable=True),
        sa.Column("notes_json", json_type, nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("self_improvement_actions", ["status", "priority"], "status_priority")
    create_index("self_improvement_actions", ["source_dimension", "affected_module"], "source_module")


def downgrade() -> None:
    op.drop_table("self_improvement_actions")
    op.drop_table("learning_strength_weakness_map")
    op.drop_table("learning_progress_snapshots")
    op.drop_table("learning_benchmark_comparisons")
    op.drop_table("blum_trading_power_scores")
