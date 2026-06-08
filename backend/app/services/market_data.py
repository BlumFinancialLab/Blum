from __future__ import annotations

from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Asset, PriceHistory
from app.providers.yfinance_provider import StooqProvider, YahooChartProvider, YFinanceProvider, to_price_rows


class MarketDataService:
    def __init__(self):
        self.settings = get_settings()
        self.providers = [YFinanceProvider(), YahooChartProvider(), StooqProvider()]

    def update_prices(self, db: Session, tickers: list[str] | None = None, period: str = "max", limit: int | None = None) -> dict:
        limit = limit or self.settings.max_update_assets
        query = select(Asset).where(Asset.is_active.is_(True)).order_by(Asset.asset_type, Asset.ticker)
        if tickers:
            query = query.where(Asset.ticker.in_([ticker.upper() for ticker in tickers]))
        assets = db.scalars(query.limit(limit)).all()
        inserted = 0
        updated_assets = 0
        provider_report: list[dict] = []
        remaining = {asset.ticker: asset for asset in assets}
        for provider in self.providers:
            if not remaining:
                break
            requested = list(remaining)
            try:
                frames = provider.download_history(requested, period=period)
            except Exception as exc:
                provider_report.append(
                    {
                        "provider": provider.name,
                        "requested": len(requested),
                        "resolved": 0,
                        "status": "error",
                        "error": str(exc)[:220],
                    }
                )
                continue
            resolved = 0
            for ticker, frame in frames.items():
                asset = remaining.get(ticker)
                if asset is None or frame is None or frame.empty:
                    continue
                rows = to_price_rows(asset.id, frame, provider.name)
                if not rows:
                    continue
                min_date = min(row["date"] for row in rows)
                db.execute(delete(PriceHistory).where(PriceHistory.asset_id == asset.id, PriceHistory.date >= min_date))
                db.add_all([PriceHistory(**row) for row in rows])
                inserted += len(rows)
                updated_assets += 1
                resolved += 1
                remaining.pop(ticker, None)
            provider_report.append(
                {
                    "provider": provider.name,
                    "requested": len(requested),
                    "resolved": resolved,
                    "status": "ok" if resolved else "no_data",
                }
            )
        db.commit()
        missing_assets = list(remaining)
        return {
            "providers": [provider.name for provider in self.providers],
            "data_mode": "real_public_data_only",
            "updated_assets": updated_assets,
            "price_rows": inserted,
            "period": period,
            "missing_assets": missing_assets,
            "provider_report": provider_report,
            "warning": (
                "Some assets have no stored prices because every configured public provider failed or returned no data. No synthetic prices were generated."
                if missing_assets
                else ""
            ),
        }


def latest_price_payload(db: Session, ticker: str) -> dict | None:
    asset = db.scalar(select(Asset).where(Asset.ticker == ticker.upper()))
    if not asset:
        return None
    return market_snapshot_for_asset(db, asset)


def market_snapshot_for_asset(db: Session, asset: Asset) -> dict:
    rows = db.scalars(
        select(PriceHistory)
        .where(PriceHistory.asset_id == asset.id)
        .order_by(desc(PriceHistory.date))
        .limit(24)
    ).all()
    if not rows:
        return {
            "ticker": asset.ticker,
            "currency": asset.currency,
            "data_status": "missing_price_history",
            "price": None,
            "date": None,
            "volume": None,
            "provider": None,
            "perf_1d": None,
            "perf_5d": None,
            "perf_1m": None,
        }
    latest = rows[0]
    return {
        "ticker": asset.ticker,
        "currency": asset.currency,
        "data_status": "ready",
        "price": round(float(latest.close), 4),
        "date": str(latest.date),
        "volume": latest.volume,
        "provider": latest.provider,
        "perf_1d": pct_change(rows, 1),
        "perf_5d": pct_change(rows, 5),
        "perf_1m": pct_change(rows, 21),
    }


def pct_change(rows: list[PriceHistory], offset: int) -> float | None:
    if len(rows) <= offset:
        return None
    current = float(rows[0].close)
    previous = float(rows[offset].close)
    if previous == 0:
        return None
    return round((current / previous - 1) * 100, 4)
