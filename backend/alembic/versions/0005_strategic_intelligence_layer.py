from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_strategic_intelligence_layer"
down_revision = "0004_accuracy_confidence_layer"
branch_labels = None
depends_on = None


json_type = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("watchlist_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("thesis", sa.Text(), nullable=False),
        sa.Column("alert_rules", json_type, nullable=False),
        sa.Column("last_score", sa.Float(), nullable=True),
        sa.Column("metadata_payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", "watchlist_name", name="uq_watchlist_ticker_name"),
    )
    op.create_index("ix_watchlist_items_asset_id", "watchlist_items", ["asset_id"])
    op.create_index("ix_watchlist_items_ticker", "watchlist_items", ["ticker"])
    op.create_index("ix_watchlist_items_watchlist_name", "watchlist_items", ["watchlist_name"])
    op.create_index("ix_watchlist_items_status", "watchlist_items", ["status"])
    op.create_index("ix_watchlist_items_created_at", "watchlist_items", ["created_at"])
    op.create_index("ix_watchlist_items_name_created", "watchlist_items", ["watchlist_name", "created_at"])

    op.create_table(
        "intelligence_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=True),
        sa.Column("report_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=260), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("structured_output", json_type, nullable=False),
        sa.Column("data_mode", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_intelligence_reports_asset_id", "intelligence_reports", ["asset_id"])
    op.create_index("ix_intelligence_reports_ticker", "intelligence_reports", ["ticker"])
    op.create_index("ix_intelligence_reports_report_type", "intelligence_reports", ["report_type"])
    op.create_index("ix_intelligence_reports_data_mode", "intelligence_reports", ["data_mode"])
    op.create_index("ix_intelligence_reports_created_at", "intelligence_reports", ["created_at"])
    op.create_index("ix_intelligence_reports_ticker_created", "intelligence_reports", ["ticker", "created_at"])

    op.create_table(
        "portfolio_scenarios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scenario_name", sa.String(length=160), nullable=False),
        sa.Column("risk_profile", sa.String(length=80), nullable=False),
        sa.Column("allocation", json_type, nullable=False),
        sa.Column("rationale", json_type, nullable=False),
        sa.Column("disclaimer", sa.Text(), nullable=False),
        sa.Column("data_mode", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_portfolio_scenarios_scenario_name", "portfolio_scenarios", ["scenario_name"])
    op.create_index("ix_portfolio_scenarios_risk_profile", "portfolio_scenarios", ["risk_profile"])
    op.create_index("ix_portfolio_scenarios_data_mode", "portfolio_scenarios", ["data_mode"])
    op.create_index("ix_portfolio_scenarios_created", "portfolio_scenarios", ["created_at"])


def downgrade() -> None:
    op.drop_table("portfolio_scenarios")
    op.drop_table("intelligence_reports")
    op.drop_table("watchlist_items")
