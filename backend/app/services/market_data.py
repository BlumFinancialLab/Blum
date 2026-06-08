from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Asset, PriceHistory
from app.providers.yfinance_provider import YFinanceProvider, to_price_rows


class MarketDataService:
    def __init__(self):
        self.settings = get_settings()
        self.provider = YFinanceProvider()

    def update_prices(self, db: Session, tickers: list[str] | None = None, period: str = "2y", limit: int | None = None) -> dict:
        limit = limit or self.settings.max_update_assets
        query = select(Asset).where(Asset.is_active.is_(True)).order_by(Asset.asset_type, Asset.ticker)
        if tickers:
            query = query.where(Asset.ticker.in_([ticker.upper() for ticker in tickers]))
        assets = db.scalars(query.limit(limit)).all()
        frames = self.provider.download_history([asset.ticker for asset in assets], period=period)
        inserted = 0
        updated_assets = 0
        for asset in assets:
            frame = frames.get(asset.ticker)
            if frame is None or frame.empty:
                continue
            rows = to_price_rows(asset.id, frame, self.provider.name)
            if not rows:
                continue
            min_date = min(row["date"] for row in rows)
            db.execute(delete(PriceHistory).where(PriceHistory.asset_id == asset.id, PriceHistory.date >= min_date))
            db.add_all([PriceHistory(**row) for row in rows])
            inserted += len(rows)
            updated_assets += 1
        db.commit()
        return {"provider": self.provider.name, "updated_assets": updated_assets, "price_rows": inserted, "period": period}


def latest_price_payload(db: Session, ticker: str) -> dict | None:
    asset = db.scalar(select(Asset).where(Asset.ticker == ticker.upper()))
    if not asset:
        return None
    price = db.scalar(select(PriceHistory).where(PriceHistory.asset_id == asset.id).order_by(PriceHistory.date.desc()).limit(1))
    if not price:
        return None
    return {"ticker": asset.ticker, "date": str(price.date), "close": price.close, "volume": price.volume}

