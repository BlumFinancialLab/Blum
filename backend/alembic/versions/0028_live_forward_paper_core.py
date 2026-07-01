from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0028_paper_forward_core"
down_revision = "0027_feedback_loop"
branch_labels = None
depends_on = None


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table_name: str) -> set[str]:
    if table_name not in _tables():
        return set()
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _constraints(table_name: str) -> set[str]:
    if table_name not in _tables():
        return set()
    inspector = sa.inspect(op.get_bind())
    return {constraint["name"] for constraint in inspector.get_unique_constraints(table_name)}


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if index_name not in _indexes(table_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    tables = _tables()
    if "live_forward_paper_trades" not in tables:
        op.create_table(
            "live_forward_paper_trades",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("trade_uid", sa.String(length=100), nullable=False),
            sa.Column("game_id", sa.Integer(), nullable=False),
            sa.Column("ledger_trade_id", sa.Integer(), nullable=True),
            sa.Column("feedback_loop_audit_id", sa.Integer(), nullable=True),
            sa.Column("ticker", sa.String(length=32), nullable=False),
            sa.Column("asset_name", sa.String(length=220), nullable=True),
            sa.Column("asset_type", sa.String(length=40), nullable=True),
            sa.Column("sector", sa.String(length=120), nullable=True),
            sa.Column("industry", sa.String(length=160), nullable=True),
            sa.Column("setup_type", sa.String(length=100), nullable=False),
            sa.Column("status", sa.String(length=60), nullable=False, server_default="CANDIDATE"),
            sa.Column("close_reason", sa.String(length=80), nullable=True),
            sa.Column("decision_timestamp", sa.DateTime(), nullable=False),
            sa.Column("decision_date", sa.Date(), nullable=True),
            sa.Column("model_version_used", sa.String(length=100), nullable=False, server_default="base-static"),
            sa.Column("weights_used", json_type, nullable=True),
            sa.Column("confidence_adjustment", sa.Float(), nullable=False, server_default="0"),
            sa.Column("learning_memory_used", json_type, nullable=True),
            sa.Column("strategy_memory_used", json_type, nullable=True),
            sa.Column("research_priority_used", json_type, nullable=True),
            sa.Column("frozen_decision_payload", json_type, nullable=True),
            sa.Column("actionability_state", sa.String(length=80), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("sniper_score", sa.Float(), nullable=True),
            sa.Column("benchmark_ticker", sa.String(length=32), nullable=True),
            sa.Column("entry_trigger", sa.Text(), nullable=True),
            sa.Column("confirmation_condition", sa.Text(), nullable=True),
            sa.Column("entry_price", sa.Float(), nullable=True),
            sa.Column("entry_date", sa.Date(), nullable=True),
            sa.Column("opened_at", sa.DateTime(), nullable=True),
            sa.Column("stop_loss", sa.Float(), nullable=True),
            sa.Column("invalidation_level", sa.Float(), nullable=True),
            sa.Column("target_1", sa.Float(), nullable=True),
            sa.Column("target_2", sa.Float(), nullable=True),
            sa.Column("position_size", sa.Float(), nullable=False, server_default="0"),
            sa.Column("notional_value", sa.Float(), nullable=True),
            sa.Column("risk_amount", sa.Float(), nullable=False, server_default="0"),
            sa.Column("risk_percent", sa.Float(), nullable=False, server_default="0"),
            sa.Column("expected_risk", sa.Float(), nullable=True),
            sa.Column("expected_reward", sa.Float(), nullable=True),
            sa.Column("expected_r_multiple", sa.Float(), nullable=True),
            sa.Column("current_price", sa.Float(), nullable=True),
            sa.Column("unrealized_pnl", sa.Float(), nullable=False, server_default="0"),
            sa.Column("exit_price", sa.Float(), nullable=True),
            sa.Column("exit_date", sa.Date(), nullable=True),
            sa.Column("closed_at", sa.DateTime(), nullable=True),
            sa.Column("gross_pnl_eur", sa.Float(), nullable=True),
            sa.Column("net_pnl_eur", sa.Float(), nullable=True),
            sa.Column("pnl_percent", sa.Float(), nullable=True),
            sa.Column("pnl_per_share", sa.Float(), nullable=True),
            sa.Column("r_multiple", sa.Float(), nullable=True),
            sa.Column("max_favorable_excursion", sa.Float(), nullable=False, server_default="0"),
            sa.Column("max_adverse_excursion", sa.Float(), nullable=False, server_default="0"),
            sa.Column("target_1_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("target_2_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("stop_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("invalidation_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("benchmark_return_same_period", sa.Float(), nullable=True),
            sa.Column("excess_return_vs_benchmark", sa.Float(), nullable=True),
            sa.Column("outcome_label", sa.String(length=80), nullable=True),
            sa.Column("lesson_learned", sa.Text(), nullable=True),
            sa.Column("duplicate_key", sa.String(length=220), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["feedback_loop_audit_id"], ["feedback_loop_audits.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["game_id"], ["live_forward_paper_games.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["ledger_trade_id"], ["trading_game_trades.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("duplicate_key", name="uq_live_forward_paper_trade_duplicate_key"),
        )

    if "live_forward_paper_trade_events" not in _tables():
        op.create_table(
            "live_forward_paper_trade_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("paper_trade_id", sa.Integer(), nullable=False),
            sa.Column("event_timestamp", sa.DateTime(), nullable=False),
            sa.Column("event_type", sa.String(length=100), nullable=False),
            sa.Column("price_used", sa.Float(), nullable=True),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("payload", json_type, nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["paper_trade_id"], ["live_forward_paper_trades.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    for name, columns in {
        "ix_live_forward_paper_trades_trade_uid": ["trade_uid"],
        "ix_live_forward_paper_trades_game_id": ["game_id"],
        "ix_live_forward_paper_trades_ledger_trade_id": ["ledger_trade_id"],
        "ix_live_forward_paper_trades_feedback_loop_audit_id": ["feedback_loop_audit_id"],
        "ix_live_forward_paper_trades_ticker": ["ticker"],
        "ix_live_forward_paper_trades_status": ["status"],
        "ix_live_forward_paper_trades_decision_date": ["decision_date"],
        "ix_live_forward_paper_trades_model_version_used": ["model_version_used"],
        "ix_live_forward_paper_trades_sniper_score": ["sniper_score"],
        "ix_live_forward_paper_trades_duplicate_key": ["duplicate_key"],
        "ix_live_forward_trades_status_created": ["status", "created_at"],
        "ix_live_forward_trades_ticker_decision": ["ticker", "decision_date"],
        "ix_live_forward_trades_game_status": ["game_id", "status", "created_at"],
    }.items():
        _create_index_if_missing(name, "live_forward_paper_trades", columns)

    for name, columns in {
        "ix_live_forward_paper_trade_events_paper_trade_id": ["paper_trade_id"],
        "ix_live_forward_paper_trade_events_event_type": ["event_type"],
        "ix_live_forward_events_trade_time": ["paper_trade_id", "event_timestamp"],
        "ix_live_forward_events_type_time": ["event_type", "event_timestamp"],
    }.items():
        _create_index_if_missing(name, "live_forward_paper_trade_events", columns)


def downgrade() -> None:
    if "live_forward_paper_trade_events" in _tables():
        op.drop_table("live_forward_paper_trade_events")
    if "live_forward_paper_trades" in _tables():
        op.drop_table("live_forward_paper_trades")
