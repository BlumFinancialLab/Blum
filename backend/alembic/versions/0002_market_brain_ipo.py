from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_market_brain_ipo"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ipo_companies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cik", sa.String(length=20)),
        sa.Column("name", sa.String(length=260), nullable=False),
        sa.Column("ticker", sa.String(length=32)),
        sa.Column("exchange", sa.String(length=80)),
        sa.Column("country", sa.String(length=80), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=False),
        sa.Column("industry", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("company_metadata", sa.JSON(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("cik", "name", name="uq_ipo_company_cik_name"),
    )
    op.create_index("ix_ipo_companies_cik", "ipo_companies", ["cik"])
    op.create_index("ix_ipo_companies_country", "ipo_companies", ["country"])
    op.create_index("ix_ipo_companies_exchange", "ipo_companies", ["exchange"])
    op.create_index("ix_ipo_companies_last_seen", "ipo_companies", ["last_seen_at"])
    op.create_index("ix_ipo_companies_name", "ipo_companies", ["name"])
    op.create_index("ix_ipo_companies_sector", "ipo_companies", ["sector"])
    op.create_index("ix_ipo_companies_status", "ipo_companies", ["status"])
    op.create_index("ix_ipo_companies_ticker", "ipo_companies", ["ticker"])

    op.create_table(
        "ipo_filings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("ipo_companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cik", sa.String(length=20)),
        sa.Column("company_name", sa.String(length=260), nullable=False),
        sa.Column("form_type", sa.String(length=40), nullable=False),
        sa.Column("filing_date", sa.DateTime()),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("accession_number", sa.String(length=80), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("accession_number", name="uq_ipo_filing_accession"),
    )
    op.create_index("ix_ipo_filings_accession_number", "ipo_filings", ["accession_number"])
    op.create_index("ix_ipo_filings_cik", "ipo_filings", ["cik"])
    op.create_index("ix_ipo_filings_company_form_date", "ipo_filings", ["company_id", "form_type", "filing_date"])
    op.create_index("ix_ipo_filings_company_id", "ipo_filings", ["company_id"])
    op.create_index("ix_ipo_filings_company_name", "ipo_filings", ["company_name"])
    op.create_index("ix_ipo_filings_created_at", "ipo_filings", ["created_at"])
    op.create_index("ix_ipo_filings_filing_date", "ipo_filings", ["filing_date"])
    op.create_index("ix_ipo_filings_form_type", "ipo_filings", ["form_type"])
    op.create_index("ix_ipo_filings_source", "ipo_filings", ["source"])

    op.create_table(
        "ipo_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("ipo_companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filing_id", sa.Integer(), sa.ForeignKey("ipo_filings.id", ondelete="SET NULL")),
        sa.Column("readiness_score", sa.Float(), nullable=False),
        sa.Column("listing_probability_score", sa.Float(), nullable=False),
        sa.Column("narrative_heat_score", sa.Float(), nullable=False),
        sa.Column("valuation_risk_score", sa.Float(), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("opportunity_score", sa.Float(), nullable=False),
        sa.Column("classification", sa.String(length=80), nullable=False),
        sa.Column("time_horizon", sa.String(length=80), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ipo_scores_classification", "ipo_scores", ["classification"])
    op.create_index("ix_ipo_scores_company_created", "ipo_scores", ["company_id", "created_at"])
    op.create_index("ix_ipo_scores_company_id", "ipo_scores", ["company_id"])
    op.create_index("ix_ipo_scores_created_at", "ipo_scores", ["created_at"])
    op.create_index("ix_ipo_scores_filing_id", "ipo_scores", ["filing_id"])
    op.create_index("ix_ipo_scores_opportunity_score", "ipo_scores", ["opportunity_score"])
    op.create_index("ix_ipo_scores_readiness_score", "ipo_scores", ["readiness_score"])

    op.create_table(
        "market_brain_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(length=80), nullable=False),
        sa.Column("brain_score", sa.Float(), nullable=False),
        sa.Column("regime", sa.String(length=120), nullable=False),
        sa.Column("horizon", sa.String(length=80), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("structured_output", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_market_brain_snapshots_brain_score", "market_brain_snapshots", ["brain_score"])
    op.create_index("ix_market_brain_snapshots_created_at", "market_brain_snapshots", ["created_at"])
    op.create_index("ix_market_brain_snapshots_regime", "market_brain_snapshots", ["regime"])
    op.create_index("ix_market_brain_snapshots_run_id", "market_brain_snapshots", ["run_id"], unique=True)


def downgrade() -> None:
    op.drop_table("market_brain_snapshots")
    op.drop_table("ipo_scores")
    op.drop_table("ipo_filings")
    op.drop_table("ipo_companies")
