from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0022_alpha_loss_recovery_engine"
down_revision = "0021_adaptive_capital_allocation"
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
        "benchmark_methodology_validations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("benchmark_comparison_id", sa.Integer(), nullable=True),
        sa.Column("benchmark_name", sa.String(length=120), nullable=False),
        sa.Column("mode", sa.String(length=80), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("methodology_valid", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("corrected_excess_return", sa.Float(), nullable=True),
        sa.Column("warnings_json", json_type, nullable=True),
        sa.Column("validation_checks_json", json_type, nullable=True),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["benchmark_comparison_id"], ["learning_benchmark_comparisons.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("benchmark_methodology_validations", ["benchmark_comparison_id"], "comparison")
    create_index("benchmark_methodology_validations", ["benchmark_name", "created_at"], "benchmark_created")
    create_index("benchmark_methodology_validations", ["methodology_valid", "confidence"], "valid_conf")
    create_index("benchmark_methodology_validations", ["mode"], "mode")
    create_index("benchmark_methodology_validations", ["period_start"], "period_start")
    create_index("benchmark_methodology_validations", ["period_end"], "period_end")
    create_index("benchmark_methodology_validations", ["created_at"], "created")

    op.create_table(
        "alpha_loss_attributions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("methodology_validation_id", sa.Integer(), nullable=True),
        sa.Column("benchmark_name", sa.String(length=120), nullable=False),
        sa.Column("mode", sa.String(length=80), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("total_alpha_loss", sa.Float(), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=True),
        sa.Column("setup_type", sa.String(length=120), nullable=True),
        sa.Column("sector", sa.String(length=120), nullable=True),
        sa.Column("engine_name", sa.String(length=120), nullable=True),
        sa.Column("capital_allocation_bucket", sa.String(length=120), nullable=True),
        sa.Column("contribution_value", sa.Float(), nullable=False),
        sa.Column("contribution_percent", sa.Float(), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["methodology_validation_id"], ["benchmark_methodology_validations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("alpha_loss_attributions", ["methodology_validation_id"], "methodology")
    create_index("alpha_loss_attributions", ["benchmark_name", "category", "created_at"], "benchmark_category")
    create_index("alpha_loss_attributions", ["contribution_value", "confidence"], "contribution")
    create_index("alpha_loss_attributions", ["ticker", "setup_type", "sector"], "scope")
    create_index("alpha_loss_attributions", ["mode"], "mode")
    create_index("alpha_loss_attributions", ["period_start"], "period_start")
    create_index("alpha_loss_attributions", ["period_end"], "period_end")
    create_index("alpha_loss_attributions", ["engine_name"], "engine")
    create_index("alpha_loss_attributions", ["capital_allocation_bucket"], "allocation_bucket")
    create_index("alpha_loss_attributions", ["sample_size"], "sample_size")
    create_index("alpha_loss_attributions", ["created_at"], "created")

    op.create_table(
        "missed_winners",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("decision_date", sa.Date(), nullable=True),
        sa.Column("benchmark_name", sa.String(length=120), nullable=False),
        sa.Column("future_return", sa.Float(), nullable=True),
        sa.Column("benchmark_relative_return", sa.Float(), nullable=True),
        sa.Column("blum_rank_at_decision", sa.Integer(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=False),
        sa.Column("confidence_at_decision", sa.Float(), nullable=True),
        sa.Column("blocked_rule", sa.String(length=180), nullable=True),
        sa.Column("missed_signals_json", json_type, nullable=True),
        sa.Column("suggested_learning_action", sa.Text(), nullable=False),
        sa.Column("source_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("source_trade_id", sa.Integer(), nullable=True),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_snapshot_id"], ["decision_universe_snapshots.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_trade_id"], ["trading_game_trades.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("missed_winners", ["ticker", "decision_date"], "ticker_date")
    create_index("missed_winners", ["benchmark_name", "created_at"], "benchmark_created")
    create_index("missed_winners", ["benchmark_relative_return", "future_return"], "return")
    create_index("missed_winners", ["blum_rank_at_decision"], "rank")
    create_index("missed_winners", ["blocked_rule"], "blocked_rule")
    create_index("missed_winners", ["source_snapshot_id"], "snapshot")
    create_index("missed_winners", ["source_trade_id"], "trade")
    create_index("missed_winners", ["created_at"], "created")

    op.create_table(
        "alpha_recovery_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("action_type", sa.String(length=120), nullable=False),
        sa.Column("detected_problem", sa.Text(), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("affected_module", sa.String(length=120), nullable=False),
        sa.Column("benchmark_name", sa.String(length=120), nullable=True),
        sa.Column("expected_impact", sa.Text(), nullable=False),
        sa.Column("before_metric", sa.Float(), nullable=True),
        sa.Column("after_metric", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("rollback_available", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.String(length=40), nullable=False),
        sa.Column("validation_status", sa.String(length=80), nullable=False),
        sa.Column("evidence_json", json_type, nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("alpha_recovery_actions", ["status", "priority"], "status_priority")
    create_index("alpha_recovery_actions", ["benchmark_name", "affected_module"], "benchmark_module")
    create_index("alpha_recovery_actions", ["created_at"], "created")
    create_index("alpha_recovery_actions", ["action_type"], "action_type")
    create_index("alpha_recovery_actions", ["affected_module"], "module")
    create_index("alpha_recovery_actions", ["rollback_available"], "rollback")
    create_index("alpha_recovery_actions", ["validation_status"], "validation")


def downgrade() -> None:
    op.drop_table("alpha_recovery_actions")
    op.drop_table("missed_winners")
    op.drop_table("alpha_loss_attributions")
    op.drop_table("benchmark_methodology_validations")
