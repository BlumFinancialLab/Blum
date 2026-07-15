from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0019_decision_quality"
down_revision = "0018_learning_intel_benchmark"
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
        "decision_universe_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("market_regime", sa.String(length=120), nullable=True),
        sa.Column("volatility_regime", sa.String(length=120), nullable=True),
        sa.Column("selected_asset", sa.String(length=32), nullable=False),
        sa.Column("selected_rank", sa.Integer(), nullable=True),
        sa.Column("selected_score", sa.Float(), nullable=True),
        sa.Column("total_candidates", sa.Integer(), nullable=False),
        sa.Column("candidates_json", json_type, nullable=True),
        sa.Column("benchmark_snapshot", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("decision_universe_snapshots", ["selected_asset", "timestamp"], "selected_created")
    create_index("decision_universe_snapshots", ["market_regime", "timestamp"], "regime_created")

    op.create_table(
        "opportunity_recall_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=True),
        sa.Column("setup", sa.String(length=120), nullable=True),
        sa.Column("regime", sa.String(length=120), nullable=True),
        sa.Column("timeframe", sa.String(length=80), nullable=True),
        sa.Column("captured_outperformers", sa.Integer(), nullable=False),
        sa.Column("total_outperformers", sa.Integer(), nullable=False),
        sa.Column("opportunity_recall", sa.Float(), nullable=True),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("opportunity_recall_metrics", ["sector", "setup", "regime", "timeframe"], "scope")

    op.create_table(
        "opportunity_precision_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=True),
        sa.Column("setup", sa.String(length=120), nullable=True),
        sa.Column("regime", sa.String(length=120), nullable=True),
        sa.Column("timeframe", sa.String(length=80), nullable=True),
        sa.Column("successful_opportunities", sa.Integer(), nullable=False),
        sa.Column("selected_opportunities", sa.Integer(), nullable=False),
        sa.Column("opportunity_precision", sa.Float(), nullable=True),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("opportunity_precision_metrics", ["sector", "setup", "regime", "timeframe"], "scope")

    op.create_table(
        "alpha_capture_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=True),
        sa.Column("sector", sa.String(length=120), nullable=True),
        sa.Column("regime", sa.String(length=120), nullable=True),
        sa.Column("timeframe", sa.String(length=80), nullable=True),
        sa.Column("available_alpha", sa.Float(), nullable=True),
        sa.Column("captured_alpha", sa.Float(), nullable=True),
        sa.Column("alpha_capture_rate", sa.Float(), nullable=True),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("alpha_capture_metrics", ["ticker", "sector", "regime", "timeframe"], "scope")

    op.create_table(
        "ranking_accuracy_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=True),
        sa.Column("setup", sa.String(length=120), nullable=True),
        sa.Column("regime", sa.String(length=120), nullable=True),
        sa.Column("timeframe", sa.String(length=80), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("top1_accuracy", sa.Float(), nullable=True),
        sa.Column("top3_accuracy", sa.Float(), nullable=True),
        sa.Column("top5_accuracy", sa.Float(), nullable=True),
        sa.Column("ranking_correlation", sa.Float(), nullable=True),
        sa.Column("ranking_decay", sa.Float(), nullable=True),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("ranking_accuracy_metrics", ["sector", "setup", "regime", "timeframe"], "scope")

    op.create_table(
        "decision_superiority_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("mode", sa.String(length=80), nullable=False),
        sa.Column("scope", sa.String(length=120), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("classification", sa.String(length=120), nullable=False),
        sa.Column("opportunity_recall", sa.Float(), nullable=True),
        sa.Column("opportunity_precision", sa.Float(), nullable=True),
        sa.Column("alpha_capture", sa.Float(), nullable=True),
        sa.Column("ranking_accuracy", sa.Float(), nullable=True),
        sa.Column("benchmark_excess", sa.Float(), nullable=True),
        sa.Column("live_validation", sa.Float(), nullable=True),
        sa.Column("regime_consistency", sa.Float(), nullable=True),
        sa.Column("reproducibility", sa.Float(), nullable=True),
        sa.Column("drawdown_control", sa.Float(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("warnings_json", json_type, nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("decision_superiority_scores", ["mode", "calculated_at"], "mode_created")
    create_index("decision_superiority_scores", ["score", "classification"], "score_class")

    op.create_table(
        "business_quality_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("growth_quality", sa.Float(), nullable=True),
        sa.Column("profitability_quality", sa.Float(), nullable=True),
        sa.Column("cash_flow_quality", sa.Float(), nullable=True),
        sa.Column("balance_sheet_quality", sa.Float(), nullable=True),
        sa.Column("capital_allocation_quality", sa.Float(), nullable=True),
        sa.Column("moat_quality", sa.Float(), nullable=True),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("business_quality_profiles", ["ticker", "calculated_at"], "ticker_created")

    op.create_table(
        "management_quality_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("insider_alignment", sa.Float(), nullable=True),
        sa.Column("execution_consistency", sa.Float(), nullable=True),
        sa.Column("earnings_delivery", sa.Float(), nullable=True),
        sa.Column("management_quality", sa.Float(), nullable=True),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("management_quality_profiles", ["ticker", "calculated_at"], "ticker_created")

    op.create_table(
        "fundamental_alpha_patterns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("pattern_name", sa.String(length=160), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=True),
        sa.Column("timeframe", sa.String(length=80), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("average_forward_return", sa.Float(), nullable=True),
        sa.Column("hit_rate", sa.Float(), nullable=True),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("fundamental_alpha_patterns", ["pattern_name", "sector", "timeframe"], "scope")

    op.create_table(
        "business_quality_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=True),
        sa.Column("business_quality_score", sa.Float(), nullable=False),
        sa.Column("growth_quality", sa.Float(), nullable=True),
        sa.Column("profitability_quality", sa.Float(), nullable=True),
        sa.Column("cash_flow_quality", sa.Float(), nullable=True),
        sa.Column("balance_sheet_quality", sa.Float(), nullable=True),
        sa.Column("capital_allocation_quality", sa.Float(), nullable=True),
        sa.Column("moat_quality", sa.Float(), nullable=True),
        sa.Column("management_quality", sa.Float(), nullable=True),
        sa.Column("data_quality_score", sa.Float(), nullable=False),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("business_quality_scores", ["ticker", "calculated_at"], "ticker_created")
    create_index("business_quality_scores", ["business_quality_score"], "score")

    op.create_table(
        "portfolio_contributions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=True),
        sa.Column("return_contribution", sa.Float(), nullable=True),
        sa.Column("risk_contribution", sa.Float(), nullable=True),
        sa.Column("drawdown_contribution", sa.Float(), nullable=True),
        sa.Column("alpha_contribution", sa.Float(), nullable=True),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.ForeignKeyConstraint(["game_id"], ["trading_games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("portfolio_contributions", ["game_id", "ticker", "calculated_at"], "scope")

    op.create_table(
        "portfolio_correlations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("scope", sa.String(length=120), nullable=False),
        sa.Column("asset_a", sa.String(length=32), nullable=False),
        sa.Column("asset_b", sa.String(length=32), nullable=False),
        sa.Column("correlation", sa.Float(), nullable=True),
        sa.Column("correlation_type", sa.String(length=80), nullable=False),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", "asset_a", "asset_b", name="uq_portfolio_correlation_pair"),
    )
    create_index("portfolio_correlations", ["scope", "correlation"], "scope_corr")

    op.create_table(
        "portfolio_alpha_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("portfolio_alpha_score", sa.Float(), nullable=False),
        sa.Column("marginal_return_score", sa.Float(), nullable=True),
        sa.Column("marginal_risk_score", sa.Float(), nullable=True),
        sa.Column("diversification_score", sa.Float(), nullable=True),
        sa.Column("benchmark_excess_score", sa.Float(), nullable=True),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.ForeignKeyConstraint(["game_id"], ["trading_games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("portfolio_alpha_scores", ["ticker", "calculated_at"], "ticker_created")

    op.create_table(
        "position_sizing_outcomes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("sizing_logic", sa.String(length=120), nullable=False),
        sa.Column("timeframe", sa.String(length=80), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("average_r", sa.Float(), nullable=True),
        sa.Column("drawdown_impact", sa.Float(), nullable=True),
        sa.Column("capital_efficiency", sa.Float(), nullable=True),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("position_sizing_outcomes", ["sizing_logic", "timeframe"], "logic_timeframe")

    op.create_table(
        "portfolio_quality_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=True),
        sa.Column("portfolio_quality_score", sa.Float(), nullable=False),
        sa.Column("diversification", sa.Float(), nullable=True),
        sa.Column("concentration_risk", sa.Float(), nullable=True),
        sa.Column("drawdown_control", sa.Float(), nullable=True),
        sa.Column("alpha_generation", sa.Float(), nullable=True),
        sa.Column("benchmark_excess", sa.Float(), nullable=True),
        sa.Column("capital_efficiency", sa.Float(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("warnings_json", json_type, nullable=True),
        sa.ForeignKeyConstraint(["game_id"], ["trading_games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("portfolio_quality_scores", ["game_id", "calculated_at"], "game_created")
    create_index("portfolio_quality_scores", ["portfolio_quality_score"], "score")


def downgrade() -> None:
    for table in [
        "portfolio_quality_scores",
        "position_sizing_outcomes",
        "portfolio_alpha_scores",
        "portfolio_correlations",
        "portfolio_contributions",
        "business_quality_scores",
        "fundamental_alpha_patterns",
        "management_quality_profiles",
        "business_quality_profiles",
        "decision_superiority_scores",
        "ranking_accuracy_metrics",
        "alpha_capture_metrics",
        "opportunity_precision_metrics",
        "opportunity_recall_metrics",
        "decision_universe_snapshots",
    ]:
        op.drop_table(table)
