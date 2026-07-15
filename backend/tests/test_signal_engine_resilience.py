from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Asset, FundamentalSnapshot
from app.signals.engine import fundamental_features


def test_partial_fundamentals_do_not_break_signal_generation():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        asset = Asset(
            ticker="PARTIAL",
            name="Partial Fundamentals",
            category="Equity",
            sector="Technology",
            country="US",
            asset_type="stock",
        )
        db.add(asset)
        db.flush()
        db.add(
            FundamentalSnapshot(
                asset_id=asset.id,
                ticker=asset.ticker,
                period_end=date(2026, 3, 31),
                metrics={
                    "revenue": {"value": 1_000.0},
                    "assets": {"value": 2_000.0},
                    "operating_cash_flow": {"value": 120.0},
                },
                quality_score=45.0,
            )
        )
        db.commit()

        result = fundamental_features(db, asset)

        assert result["status"] == "ready"
        assert result["profit_margin"] is None
        assert result["liabilities_to_assets"] is None
        assert result["cash_conversion"] is None
        assert isinstance(result["fundamental_score"], float)
