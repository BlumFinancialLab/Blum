"""Add the autonomous paper-only Forex trader core.

Revision ID: 0036_autonomous_forex_alpha_trader
Revises: 0035_decision_execution_parity
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0036_autonomous_forex_alpha_trader"
down_revision = "0035_decision_execution_parity"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.create_table(
        "forex_trader_cycles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cycle_uid", sa.String(120), nullable=False),
        sa.Column("cycle_key", sa.String(180), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("session", sa.String(60)),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("duration_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("pairs_scanned", JSON_TYPE, nullable=False),
        sa.Column("agent_outputs", JSON_TYPE, nullable=False),
        sa.Column("candidates_json", JSON_TYPE, nullable=False),
        sa.Column("approved_candidates", JSON_TYPE, nullable=False),
        sa.Column("rejected_candidates", JSON_TYPE, nullable=False),
        sa.Column("orders_json", JSON_TYPE, nullable=False),
        sa.Column("fills_json", JSON_TYPE, nullable=False),
        sa.Column("position_updates", JSON_TYPE, nullable=False),
        sa.Column("closed_trades", JSON_TYPE, nullable=False),
        sa.Column("blockers", JSON_TYPE, nullable=False),
        sa.Column("learning_events", JSON_TYPE, nullable=False),
        sa.Column("next_action", sa.Text()),
        sa.Column("code_commit", sa.String(80)),
        sa.Column("strategy_version", sa.String(80), nullable=False),
        sa.Column("cost_model_version", sa.String(80), nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("data_coverage_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("cycle_uid", name="uq_forex_trader_cycles_uid"),
        sa.UniqueConstraint("cycle_key", name="uq_forex_trader_cycles_key"),
    )
    op.create_index("ix_forex_cycles_status_started", "forex_trader_cycles", ["status", "started_at"])
    op.create_index("ix_forex_trader_cycles_configuration_hash", "forex_trader_cycles", ["configuration_hash"])
    op.create_index("ix_forex_trader_cycles_data_coverage_hash", "forex_trader_cycles", ["data_coverage_hash"])

    op.create_table(
        "forex_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_uid", sa.String(180), nullable=False),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("forex_trader_cycles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pair", sa.String(32), nullable=False),
        sa.Column("strategy_id", sa.String(120), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("decision_timestamp", sa.DateTime(), nullable=False),
        sa.Column("blockers", JSON_TYPE, nullable=False),
        sa.Column("proposal_json", JSON_TYPE, nullable=False),
        sa.Column("risk_json", JSON_TYPE, nullable=False),
        sa.Column("execution_json", JSON_TYPE, nullable=False),
        sa.Column("input_snapshot", JSON_TYPE, nullable=False),
        sa.Column("evidence_type", sa.String(60), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("decision_uid", name="uq_forex_decisions_uid"),
    )
    op.create_index("ix_forex_decisions_pair_time", "forex_decisions", ["pair", "decision_timestamp"])
    op.create_index("ix_forex_decisions_status_time", "forex_decisions", ["status", "decision_timestamp"])
    op.create_index("ix_forex_decisions_cycle_id", "forex_decisions", ["cycle_id"])
    op.create_index("ix_forex_decisions_strategy_id", "forex_decisions", ["strategy_id"])
    op.create_index("ix_forex_decisions_evidence_type", "forex_decisions", ["evidence_type"])

    op.create_table(
        "forex_positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("position_uid", sa.String(180), nullable=False),
        sa.Column("decision_id", sa.Integer(), sa.ForeignKey("forex_decisions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("pair", sa.String(32), nullable=False),
        sa.Column("strategy_id", sa.String(120), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("quantity_lots", sa.Float(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("stop_price", sa.Float(), nullable=False),
        sa.Column("target_price", sa.Float(), nullable=False),
        sa.Column("current_price", sa.Float(), nullable=False),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime()),
        sa.Column("exit_price", sa.Float()),
        sa.Column("exit_reason", sa.String(80)),
        sa.Column("gross_pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("net_pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("realized_r", sa.Float()),
        sa.Column("spread_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("slippage_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("commission", sa.Float(), nullable=False, server_default="0"),
        sa.Column("swap_accrued", sa.Float(), nullable=False, server_default="0"),
        sa.Column("margin_used", sa.Float(), nullable=False, server_default="0"),
        sa.Column("mfe", sa.Float(), nullable=False, server_default="0"),
        sa.Column("mae", sa.Float(), nullable=False, server_default="0"),
        sa.Column("last_managed_at", sa.DateTime()),
        sa.Column("contract_json", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("position_uid", name="uq_forex_positions_uid"),
    )
    op.create_index("ix_forex_positions_status_pair", "forex_positions", ["status", "pair"])
    op.create_index("ix_forex_positions_decision_id", "forex_positions", ["decision_id"])
    op.create_index("ix_forex_positions_strategy_id", "forex_positions", ["strategy_id"])
    op.create_index("ix_forex_positions_opened_at", "forex_positions", ["opened_at"])
    op.create_index("ix_forex_positions_closed_at", "forex_positions", ["closed_at"])

    op.create_table(
        "forex_learning_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.Integer(), sa.ForeignKey("forex_decisions.id", ondelete="SET NULL")),
        sa.Column("position_id", sa.Integer(), sa.ForeignKey("forex_positions.id", ondelete="SET NULL")),
        sa.Column("strategy_id", sa.String(120), nullable=False),
        sa.Column("pair", sa.String(32), nullable=False),
        sa.Column("session", sa.String(60)),
        sa.Column("regime", sa.String(60)),
        sa.Column("setup_family", sa.String(80)),
        sa.Column("direction", sa.String(16)),
        sa.Column("outcome", sa.String(80), nullable=False),
        sa.Column("expected_result", sa.Float()),
        sa.Column("realized_result", sa.Float()),
        sa.Column("difference", sa.Float()),
        sa.Column("likely_cause", sa.Text()),
        sa.Column("lesson", sa.Text(), nullable=False),
        sa.Column("evidence_strength", sa.Float(), nullable=False),
        sa.Column("model_update_justified", sa.Boolean(), nullable=False),
        sa.Column("evidence_type", sa.String(60), nullable=False),
        sa.Column("payload_json", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_forex_learning_strategy_time", "forex_learning_evidence", ["strategy_id", "created_at"])
    op.create_index("ix_forex_learning_evidence_decision_id", "forex_learning_evidence", ["decision_id"])
    op.create_index("ix_forex_learning_evidence_position_id", "forex_learning_evidence", ["position_id"])
    op.create_index("ix_forex_learning_evidence_outcome", "forex_learning_evidence", ["outcome"])
    op.create_index("ix_forex_learning_evidence_evidence_type", "forex_learning_evidence", ["evidence_type"])

    op.create_table(
        "forex_strategy_readiness",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("strategy_id", sa.String(120), nullable=False),
        sa.Column("readiness_level", sa.String(60), nullable=False),
        sa.Column("closed_forward_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("net_expectancy_r", sa.Float()),
        sa.Column("risk_adjusted_alpha", sa.Float()),
        sa.Column("max_drawdown", sa.Float()),
        sa.Column("pair_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("session_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("regime_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence_interval_json", JSON_TYPE, nullable=False),
        sa.Column("replay_forward_decay", sa.Float()),
        sa.Column("blockers", JSON_TYPE, nullable=False),
        sa.Column("threshold_version", sa.String(80), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("strategy_id", name="uq_forex_strategy_readiness_strategy_id"),
    )
    op.create_index("ix_forex_readiness_level_updated", "forex_strategy_readiness", ["readiness_level", "updated_at"])

    op.create_table(
        "forex_trader_runtime_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("runtime_key", sa.String(80), nullable=False),
        sa.Column("desired_state", sa.String(40), nullable=False),
        sa.Column("scheduler_status", sa.String(40), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime()),
        sa.Column("current_cycle_key", sa.String(180)),
        sa.Column("lock_expires_at", sa.DateTime()),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column("next_run_after", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("runtime_key", name="uq_forex_trader_runtime_state_runtime_key"),
    )
    op.create_index("ix_forex_runtime_scheduler_status", "forex_trader_runtime_state", ["scheduler_status"])
    op.create_index("ix_forex_runtime_heartbeat", "forex_trader_runtime_state", ["heartbeat_at"])
    op.create_index("ix_forex_runtime_lock", "forex_trader_runtime_state", ["lock_expires_at"])


def downgrade() -> None:
    op.drop_table("forex_trader_runtime_state")
    op.drop_table("forex_strategy_readiness")
    op.drop_table("forex_learning_evidence")
    op.drop_table("forex_positions")
    op.drop_table("forex_decisions")
    op.drop_table("forex_trader_cycles")
