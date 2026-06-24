from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0023_meta_cognition_engine"
down_revision = "0022_alpha_loss_recovery_engine"
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
        "learning_factor_importance",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.Column("factor_name", sa.String(length=120), nullable=False),
        sa.Column("factor_family", sa.String(length=120), nullable=False),
        sa.Column("horizon", sa.String(length=80), nullable=True),
        sa.Column("regime", sa.String(length=120), nullable=True),
        sa.Column("sector", sa.String(length=120), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("alpha_contribution", sa.Float(), nullable=False),
        sa.Column("alpha_loss_contribution", sa.Float(), nullable=False),
        sa.Column("missed_winner_contribution", sa.Float(), nullable=False),
        sa.Column("capital_preservation_contribution", sa.Float(), nullable=False),
        sa.Column("noise_score", sa.Float(), nullable=False),
        sa.Column("overvaluation_score", sa.Float(), nullable=False),
        sa.Column("undervaluation_score", sa.Float(), nullable=False),
        sa.Column("reliability_score", sa.Float(), nullable=False),
        sa.Column("evidence_quality", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("recommended_weight_action", sa.String(length=80), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("warnings_json", json_type, nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("learning_factor_importance", ["factor_name", "calculated_at"], "factor_created")
    create_index("learning_factor_importance", ["factor_family", "horizon", "regime", "sector"], "scope")
    create_index("learning_factor_importance", ["reliability_score", "confidence"], "reliability")
    create_index("learning_factor_importance", ["sample_size"], "sample")
    create_index("learning_factor_importance", ["noise_score"], "noise")
    create_index("learning_factor_importance", ["recommended_weight_action"], "action")
    create_index("learning_factor_importance", ["calculated_at"], "created")

    op.create_table(
        "meta_cognition_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("source_event_type", sa.String(length=120), nullable=False),
        sa.Column("source_event_id", sa.Integer(), nullable=True),
        sa.Column("evaluated_module", sa.String(length=120), nullable=False),
        sa.Column("evaluated_action", sa.Text(), nullable=False),
        sa.Column("before_metric", sa.Float(), nullable=True),
        sa.Column("after_metric", sa.Float(), nullable=True),
        sa.Column("delta", sa.Float(), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("benchmark_context", json_type, nullable=True),
        sa.Column("live_or_historical", sa.String(length=80), nullable=False),
        sa.Column("improvement_observed", sa.Boolean(), nullable=True),
        sa.Column("degradation_observed", sa.Boolean(), nullable=True),
        sa.Column("overfitting_risk", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("conclusion", sa.Text(), nullable=False),
        sa.Column("recommended_next_step", sa.Text(), nullable=False),
        sa.Column("notes_json", json_type, nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("meta_cognition_events", ["evaluated_module", "created_at"], "module_created")
    create_index("meta_cognition_events", ["improvement_observed", "degradation_observed", "confidence"], "outcome")
    create_index("meta_cognition_events", ["source_event_type"], "source_type")
    create_index("meta_cognition_events", ["source_event_id"], "source_id")
    create_index("meta_cognition_events", ["delta"], "delta")
    create_index("meta_cognition_events", ["sample_size"], "sample")
    create_index("meta_cognition_events", ["live_or_historical"], "mode")
    create_index("meta_cognition_events", ["overfitting_risk"], "overfit")
    create_index("meta_cognition_events", ["created_at"], "created")

    op.create_table(
        "capital_preservation_alpha",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("no_trade_decision_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("decision_date", sa.Date(), nullable=True),
        sa.Column("setup_type", sa.String(length=120), nullable=True),
        sa.Column("no_trade_reason", sa.Text(), nullable=False),
        sa.Column("horizon", sa.String(length=80), nullable=True),
        sa.Column("future_return", sa.Float(), nullable=True),
        sa.Column("benchmark_return", sa.Float(), nullable=True),
        sa.Column("avoided_loss", sa.Float(), nullable=False),
        sa.Column("missed_gain", sa.Float(), nullable=False),
        sa.Column("capital_preserved", sa.Float(), nullable=False),
        sa.Column("opportunity_cost", sa.Float(), nullable=False),
        sa.Column("was_correct", sa.Boolean(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["no_trade_decision_id"], ["trading_game_trades.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("capital_preservation_alpha", ["no_trade_decision_id"], "decision")
    create_index("capital_preservation_alpha", ["ticker", "decision_date"], "ticker_date")
    create_index("capital_preservation_alpha", ["was_correct", "quality_score"], "quality")
    create_index("capital_preservation_alpha", ["setup_type"], "setup")
    create_index("capital_preservation_alpha", ["horizon"], "horizon")
    create_index("capital_preservation_alpha", ["created_at"], "created")

    op.create_table(
        "learning_focus_priorities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("priority_type", sa.String(length=120), nullable=False),
        sa.Column("target", sa.String(length=180), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("expected_learning_value", sa.Float(), nullable=False),
        sa.Column("urgency", sa.String(length=40), nullable=False),
        sa.Column("sample_gap", sa.Integer(), nullable=False),
        sa.Column("linked_alpha_loss_id", sa.Integer(), nullable=True),
        sa.Column("linked_factor_importance_id", sa.Integer(), nullable=True),
        sa.Column("linked_recovery_action_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("notes_json", json_type, nullable=True),
        sa.ForeignKeyConstraint(["linked_alpha_loss_id"], ["alpha_loss_attributions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["linked_factor_importance_id"], ["learning_factor_importance.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["linked_recovery_action_id"], ["alpha_recovery_actions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("learning_focus_priorities", ["status", "urgency"], "status_urgency")
    create_index("learning_focus_priorities", ["priority_type", "target"], "type_target")
    create_index("learning_focus_priorities", ["expected_learning_value"], "value")
    create_index("learning_focus_priorities", ["sample_gap"], "sample_gap")
    create_index("learning_focus_priorities", ["linked_alpha_loss_id"], "alpha_loss")
    create_index("learning_focus_priorities", ["linked_factor_importance_id"], "factor")
    create_index("learning_focus_priorities", ["linked_recovery_action_id"], "recovery")
    create_index("learning_focus_priorities", ["created_at"], "created")

    op.create_table(
        "reasoning_noise_flags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("factor_name", sa.String(length=120), nullable=False),
        sa.Column("module_name", sa.String(length=120), nullable=False),
        sa.Column("noise_type", sa.String(length=120), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("evidence", json_type, nullable=True),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    create_index("reasoning_noise_flags", ["factor_name", "created_at"], "factor_created")
    create_index("reasoning_noise_flags", ["status", "severity"], "status_severity")
    create_index("reasoning_noise_flags", ["module_name"], "module")
    create_index("reasoning_noise_flags", ["noise_type"], "noise_type")
    create_index("reasoning_noise_flags", ["sample_size"], "sample")
    create_index("reasoning_noise_flags", ["created_at"], "created")


def downgrade() -> None:
    op.drop_table("reasoning_noise_flags")
    op.drop_table("learning_focus_priorities")
    op.drop_table("capital_preservation_alpha")
    op.drop_table("meta_cognition_events")
    op.drop_table("learning_factor_importance")
