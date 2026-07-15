from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0021_adaptive_capital_allocation"
down_revision = "0020_dashboard_snapshots"
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
        "capital_allocation_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=True),
        sa.Column("mode", sa.String(length=80), nullable=False),
        sa.Column("total_capital", sa.Float(), nullable=True),
        sa.Column("cash_reserve_percent", sa.Float(), nullable=False),
        sa.Column("deployable_percent", sa.Float(), nullable=False),
        sa.Column("allocation_quality_score", sa.Float(), nullable=False),
        sa.Column("expected_risk_adjusted_alpha", sa.Float(), nullable=True),
        sa.Column("benchmark_context", json_type, nullable=True),
        sa.Column("allocation_json", json_type, nullable=True),
        sa.Column("warnings_json", json_type, nullable=True),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["trading_games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("capital_allocation_snapshots", ["game_id", "calculated_at"], "game_created")
    create_index("capital_allocation_snapshots", ["allocation_quality_score"], "quality")

    op.create_table(
        "opportunity_capital_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=True),
        sa.Column("setup_type", sa.String(length=120), nullable=True),
        sa.Column("capital_score", sa.Float(), nullable=False),
        sa.Column("recommended_weight", sa.Float(), nullable=False),
        sa.Column("max_weight", sa.Float(), nullable=False),
        sa.Column("cash_penalty", sa.Float(), nullable=False),
        sa.Column("risk_adjusted_alpha", sa.Float(), nullable=True),
        sa.Column("portfolio_fit", sa.Float(), nullable=True),
        sa.Column("sizing_confidence", sa.Float(), nullable=True),
        sa.Column("decision_state", sa.String(length=80), nullable=False),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.ForeignKeyConstraint(["game_id"], ["trading_games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("opportunity_capital_scores", ["ticker", "calculated_at"], "ticker_created")
    create_index("opportunity_capital_scores", ["capital_score"], "score")
    create_index("opportunity_capital_scores", ["sector"], "sector")
    create_index("opportunity_capital_scores", ["setup_type"], "setup")
    create_index("opportunity_capital_scores", ["decision_state"], "decision")

    op.create_table(
        "cash_allocation_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=True),
        sa.Column("cash_reserve_percent", sa.Float(), nullable=False),
        sa.Column("deployable_percent", sa.Float(), nullable=False),
        sa.Column("decision_state", sa.String(length=80), nullable=False),
        sa.Column("market_regime", sa.String(length=120), nullable=True),
        sa.Column("drawdown_state", sa.String(length=120), nullable=True),
        sa.Column("reasons_json", json_type, nullable=True),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.ForeignKeyConstraint(["game_id"], ["trading_games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("cash_allocation_decisions", ["game_id", "calculated_at"], "game_created")
    create_index("cash_allocation_decisions", ["cash_reserve_percent"], "cash")
    create_index("cash_allocation_decisions", ["decision_state"], "decision")
    create_index("cash_allocation_decisions", ["market_regime"], "regime")
    create_index("cash_allocation_decisions", ["drawdown_state"], "drawdown")

    op.create_table(
        "allocation_efficiency_audits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("allocation_efficiency_score", sa.Float(), nullable=False),
        sa.Column("allocation_regret_eur", sa.Float(), nullable=True),
        sa.Column("cash_drag_estimate", sa.Float(), nullable=True),
        sa.Column("benchmark_opportunity_cost", sa.Float(), nullable=True),
        sa.Column("overallocated_losers_json", json_type, nullable=True),
        sa.Column("underallocated_winners_json", json_type, nullable=True),
        sa.Column("recommendations_json", json_type, nullable=True),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.ForeignKeyConstraint(["game_id"], ["trading_games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("allocation_efficiency_audits", ["game_id", "calculated_at"], "game_created")
    create_index("allocation_efficiency_audits", ["allocation_efficiency_score"], "score")

    op.create_table(
        "sizing_logic_allocations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=True),
        sa.Column("sizing_logic", sa.String(length=120), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("average_r", sa.Float(), nullable=True),
        sa.Column("benchmark_excess", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("hit_rate", sa.Float(), nullable=True),
        sa.Column("risk_adjusted_alpha", sa.Float(), nullable=True),
        sa.Column("recommended_risk_percent", sa.Float(), nullable=True),
        sa.Column("recommendation", sa.String(length=120), nullable=False),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.ForeignKeyConstraint(["game_id"], ["trading_games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("sizing_logic_allocations", ["sizing_logic", "calculated_at"], "logic_created")
    create_index("sizing_logic_allocations", ["risk_adjusted_alpha"], "score")
    create_index("sizing_logic_allocations", ["recommendation"], "recommendation")

    op.create_table(
        "capital_interaction_risks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=True),
        sa.Column("interaction_type", sa.String(length=120), nullable=False),
        sa.Column("entity_a", sa.String(length=120), nullable=False),
        sa.Column("entity_b", sa.String(length=120), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("correlation", sa.Float(), nullable=True),
        sa.Column("combined_weight", sa.Float(), nullable=True),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.ForeignKeyConstraint(["game_id"], ["trading_games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("capital_interaction_risks", ["game_id", "calculated_at"], "game_created")
    create_index("capital_interaction_risks", ["entity_a", "entity_b"], "entities")
    create_index("capital_interaction_risks", ["interaction_type"], "type")
    create_index("capital_interaction_risks", ["risk_score"], "risk_score")


def downgrade() -> None:
    op.drop_table("capital_interaction_risks")
    op.drop_table("sizing_logic_allocations")
    op.drop_table("allocation_efficiency_audits")
    op.drop_table("cash_allocation_decisions")
    op.drop_table("opportunity_capital_scores")
    op.drop_table("capital_allocation_snapshots")
