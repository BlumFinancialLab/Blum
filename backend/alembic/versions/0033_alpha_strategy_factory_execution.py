from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0033_alpha_factory_execution"
down_revision = "0032_copy_readiness_evidence"
branch_labels = None
depends_on = None


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "strategy_factory_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_uid", sa.String(140), nullable=False),
        sa.Column("hypothesis_family", sa.String(80), nullable=False),
        sa.Column("generation_seed", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("status", sa.String(60), nullable=False, server_default="RUNNING"),
        sa.Column("variants_examined", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("promoted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejection_counts_json", json_type, nullable=False),
        sa.Column("budgets_json", json_type, nullable=False),
        sa.Column("summary_json", json_type, nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("run_uid", name="uq_strategy_factory_runs_run_uid"),
    )
    op.create_index("ix_strategy_factory_runs_run_uid", "strategy_factory_runs", ["run_uid"])
    op.create_index("ix_strategy_factory_runs_hypothesis_family", "strategy_factory_runs", ["hypothesis_family"])
    op.create_index("ix_strategy_factory_runs_status", "strategy_factory_runs", ["status"])
    op.create_index("ix_strategy_factory_runs_started_at", "strategy_factory_runs", ["started_at"])
    op.create_index("ix_strategy_factory_runs_family_started", "strategy_factory_runs", ["hypothesis_family", "started_at"])
    op.create_index("ix_strategy_factory_runs_status_started", "strategy_factory_runs", ["status", "started_at"])

    op.create_table(
        "strategy_candidate_variants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("factory_run_id", sa.Integer(), sa.ForeignKey("strategy_factory_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("validation_id", sa.Integer(), sa.ForeignKey("replay_strategy_validations.id", ondelete="SET NULL")),
        sa.Column("fingerprint", sa.String(96), nullable=False),
        sa.Column("family", sa.String(80), nullable=False),
        sa.Column("setup_type", sa.String(100), nullable=False),
        sa.Column("market", sa.String(80), nullable=False, server_default="global"),
        sa.Column("asset_class", sa.String(60), nullable=False, server_default="stocks,etfs"),
        sa.Column("timeframe_stack", json_type, nullable=False),
        sa.Column("specification_json", json_type, nullable=False),
        sa.Column("complexity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("benchmark_ticker", sa.String(32), nullable=False, server_default="SPY"),
        sa.Column("lifecycle_state", sa.String(60), nullable=False, server_default="GENERATED"),
        sa.Column("final_verdict", sa.String(80)),
        sa.Column("is_champion", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("fingerprint", name="uq_strategy_candidate_variants_fingerprint"),
    )
    for column in ("factory_run_id", "validation_id", "fingerprint", "family", "setup_type", "market", "asset_class", "benchmark_ticker", "lifecycle_state", "final_verdict", "is_champion", "created_at", "updated_at"):
        op.create_index(f"ix_strategy_candidate_variants_{column}", "strategy_candidate_variants", [column])
    op.create_index("ix_strategy_candidate_variants_family_verdict", "strategy_candidate_variants", ["family", "final_verdict"])
    op.create_index("ix_strategy_candidate_variants_state_created", "strategy_candidate_variants", ["lifecycle_state", "created_at"])

    op.create_table(
        "strategy_validation_folds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("strategy_candidate_variants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fold_number", sa.Integer(), nullable=False),
        sa.Column("train_start", sa.DateTime(), nullable=False),
        sa.Column("train_end", sa.DateTime(), nullable=False),
        sa.Column("validation_start", sa.DateTime(), nullable=False),
        sa.Column("validation_end", sa.DateTime(), nullable=False),
        sa.Column("purge_bars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embargo_bars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("train_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("validation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metrics_json", json_type, nullable=False),
        sa.Column("coverage_json", json_type, nullable=False),
        sa.Column("warnings_json", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("candidate_id", "fold_number", name="uq_strategy_validation_folds_candidate_fold"),
    )
    op.create_index("ix_strategy_validation_folds_candidate_id", "strategy_validation_folds", ["candidate_id"])
    op.create_index("ix_strategy_validation_folds_validation_start", "strategy_validation_folds", ["validation_start"])
    op.create_index("ix_strategy_validation_folds_created_at", "strategy_validation_folds", ["created_at"])
    op.create_index("ix_strategy_validation_folds_candidate_validation", "strategy_validation_folds", ["candidate_id", "validation_start"])

    op.create_table(
        "strategy_promotion_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("strategy_candidate_variants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("validation_id", sa.Integer(), sa.ForeignKey("replay_strategy_validations.id", ondelete="SET NULL")),
        sa.Column("previous_candidate_id", sa.Integer(), sa.ForeignKey("strategy_candidate_variants.id", ondelete="SET NULL")),
        sa.Column("registry_key", sa.String(240), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence_json", json_type, nullable=False),
        sa.Column("reversible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("candidate_id", "validation_id", "previous_candidate_id", "registry_key", "event_type", "created_at"):
        op.create_index(f"ix_strategy_promotion_events_{column}", "strategy_promotion_events", [column])
    op.create_index("ix_strategy_promotion_events_registry_time", "strategy_promotion_events", ["registry_key", "created_at"])
    op.create_index("ix_strategy_promotion_events_candidate_type", "strategy_promotion_events", ["candidate_id", "event_type"])

    op.create_table(
        "paper_execution_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_uid", sa.String(140), nullable=False),
        sa.Column("duplicate_key", sa.String(220), nullable=False),
        sa.Column("paper_trade_id", sa.Integer(), sa.ForeignKey("live_forward_paper_trades.id", ondelete="SET NULL")),
        sa.Column("replay_trade_id", sa.Integer(), sa.ForeignKey("hyperbolic_replay_trades.id", ondelete="SET NULL")),
        sa.Column("validation_id", sa.Integer(), sa.ForeignKey("replay_strategy_validations.id", ondelete="SET NULL")),
        sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("strategy_candidate_variants.id", ondelete="SET NULL")),
        sa.Column("ticker", sa.String(48), nullable=False),
        sa.Column("side", sa.String(12), nullable=False),
        sa.Column("order_type", sa.String(24), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="SUBMITTED"),
        sa.Column("decision_timestamp", sa.DateTime(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime()),
        sa.Column("theoretical_price", sa.Float(), nullable=False),
        sa.Column("requested_quantity", sa.Float(), nullable=False),
        sa.Column("filled_quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("remaining_quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("average_fill_price", sa.Float()),
        sa.Column("limit_price", sa.Float()),
        sa.Column("stop_price", sa.Float()),
        sa.Column("target_price", sa.Float()),
        sa.Column("currency", sa.String(16), nullable=False, server_default="USD"),
        sa.Column("account_currency", sa.String(16), nullable=False, server_default="USD"),
        sa.Column("fx_rate", sa.Float()),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("order_payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("order_uid", name="uq_paper_execution_orders_uid"),
        sa.UniqueConstraint("duplicate_key", name="uq_paper_execution_orders_duplicate_key"),
    )
    for column in ("order_uid", "duplicate_key", "paper_trade_id", "replay_trade_id", "validation_id", "candidate_id", "ticker", "side", "order_type", "status", "decision_timestamp", "submitted_at", "expires_at", "created_at", "updated_at"):
        op.create_index(f"ix_paper_execution_orders_{column}", "paper_execution_orders", [column])
    op.create_index("ix_paper_execution_orders_status_submitted", "paper_execution_orders", ["status", "submitted_at"])
    op.create_index("ix_paper_execution_orders_ticker_decision", "paper_execution_orders", ["ticker", "decision_timestamp"])

    op.create_table(
        "paper_execution_fills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("paper_execution_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fill_uid", sa.String(180), nullable=False),
        sa.Column("market_timestamp", sa.DateTime(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("reference_price", sa.Float(), nullable=False),
        sa.Column("executed_price", sa.Float(), nullable=False),
        sa.Column("spread_bps", sa.Float(), nullable=False, server_default="0"),
        sa.Column("slippage_bps", sa.Float(), nullable=False, server_default="0"),
        sa.Column("commission_bps", sa.Float(), nullable=False, server_default="0"),
        sa.Column("spread_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("slippage_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("commission_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fx_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("borrow_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("gap_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("participation_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fill_payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("fill_uid", name="uq_paper_execution_fills_uid"),
    )
    op.create_index("ix_paper_execution_fills_order_id", "paper_execution_fills", ["order_id"])
    op.create_index("ix_paper_execution_fills_fill_uid", "paper_execution_fills", ["fill_uid"])
    op.create_index("ix_paper_execution_fills_market_timestamp", "paper_execution_fills", ["market_timestamp"])
    op.create_index("ix_paper_execution_fills_created_at", "paper_execution_fills", ["created_at"])
    op.create_index("ix_paper_execution_fills_order_market_time", "paper_execution_fills", ["order_id", "market_timestamp"])


def downgrade() -> None:
    op.drop_table("paper_execution_fills")
    op.drop_table("paper_execution_orders")
    op.drop_table("strategy_promotion_events")
    op.drop_table("strategy_validation_folds")
    op.drop_table("strategy_candidate_variants")
    op.drop_table("strategy_factory_runs")

