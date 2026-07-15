from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Asset, PriceHistory
from app.services.market_data import MarketDataService


class DuplicateDateProvider:
    name = "duplicate_test"

    def download_history(self, tickers, period):
        index = [datetime(2026, 1, 2), datetime(2026, 1, 2)]
        frame = pd.DataFrame(
            {
                "Open": [100.0, 101.0],
                "High": [102.0, 103.0],
                "Low": [99.0, 100.0],
                "Close": [101.0, 102.0],
                "Volume": [1000.0, 1200.0],
            },
            index=index,
        )
        return {ticker: frame.copy() for ticker in tickers}


def test_market_refresh_deduplicates_provider_dates_and_is_idempotent():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            Asset(
                ticker="TEST",
                name="Test Asset",
                category="Equity",
                sector="Technology",
                industry="Software",
                country="US",
                asset_type="stock",
                exchange="NASDAQ",
            )
        )
        db.commit()
        service = MarketDataService()
        service.providers = [DuplicateDateProvider()]

        first = service.update_prices(db, tickers=["TEST"], period="1y", limit=1)
        second = service.update_prices(db, tickers=["TEST"], period="1y", limit=1)

        rows = db.scalars(select(PriceHistory)).all()
        assert first["price_rows"] == 1
        assert second["price_rows"] == 1
        assert db.scalar(select(func.count(PriceHistory.id))) == 1
        assert len(rows) == 1
        assert rows[0].close == 102.0


def test_market_refresh_bounds_secondary_provider_validation():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        for index in range(3):
            db.add(
                Asset(
                    ticker=f"V{index}",
                    name=f"Validation {index}",
                    category="Equity",
                    sector="Technology",
                    country="US",
                    asset_type="stock",
                )
            )
        db.commit()
        service = MarketDataService()
        service.providers = [DuplicateDateProvider()]
        validated = []
        service._record_provider_checks = lambda db, assets: validated.extend(asset.ticker for asset in assets) or {"validated_assets": len(assets), "diagnostics": []}

        result = service.update_prices(
            db,
            tickers=["V0", "V1", "V2"],
            period="1y",
            limit=3,
            provider_validation_limit=1,
        )

        assert result["updated_assets"] == 3
        assert result["provider_validation"]["validated_assets"] == 1
        assert len(validated) == 1
