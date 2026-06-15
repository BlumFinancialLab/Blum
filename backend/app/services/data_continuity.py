from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Asset, PriceHistory
from app.services.etf import update_etf_trends
from app.services.market_data import MarketDataService
from app.signals.engine import SignalEngine


settings = get_settings()


def data_coverage_report(db: Session) -> dict:
    rows = db.execute(
        select(
            Asset,
            func.count(PriceHistory.id),
            func.min(PriceHistory.date),
            func.max(PriceHistory.date),
        )
        .outerjoin(PriceHistory, PriceHistory.asset_id == Asset.id)
        .where(Asset.is_active.is_(True))
        .group_by(Asset.id)
        .order_by(Asset.asset_type, Asset.ticker)
    ).all()
    today = date.today()
    assets = []
    for asset, count, first_date, last_date in rows:
        count = int(count or 0)
        status = coverage_status(count, last_date, today)
        assets.append(
            {
                "ticker": asset.ticker,
                "name": asset.name,
                "asset_type": asset.asset_type,
                "sector": asset.sector,
                "country": asset.country,
                "rows": count,
                "first_date": first_date.isoformat() if first_date else None,
                "last_date": last_date.isoformat() if last_date else None,
                "age_days": (today - last_date).days if last_date else None,
                "status": status,
            }
        )
    stale = [item for item in assets if item["status"] == "stale"]
    missing = [item for item in assets if item["status"] == "missing"]
    short = [item for item in assets if item["status"] == "short_history"]
    ready = [item for item in assets if item["status"] == "ready"]
    return {
        "data_policy": "Real public OHLCV only. Gaps are repaired from providers; missing data is never filled synthetically.",
        "learning_mode": "historical_cache_plus_continuous_incremental_refresh",
        "minimum_history_rows": settings.minimum_history_rows,
        "stale_price_max_age_days": settings.stale_price_max_age_days,
        "asset_count": len(assets),
        "ready_assets": len(ready),
        "stale_assets": len(stale),
        "missing_assets": len(missing),
        "short_history_assets": len(short),
        "coverage_ratio": round(len(ready) / max(1, len(assets)), 4),
        "repair_candidates": [item["ticker"] for item in [*missing, *short, *stale]],
        "assets": assets,
    }


def repair_data_gaps(db: Session, limit: int | None = None) -> dict:
    report = data_coverage_report(db)
    candidates = report["repair_candidates"][: limit or settings.max_update_assets]
    if not candidates:
        return {
            "status": "ready",
            "message": "Historical market memory is current enough for the configured universe.",
            "coverage": report,
            "market_update": {},
            "signal_run": {},
            "etf_update": {},
        }
    missing_or_short = {
        item["ticker"]
        for item in report["assets"]
        if item["status"] in {"missing", "short_history"}
    }
    period = settings.historical_price_period if any(ticker in missing_or_short for ticker in candidates) else settings.refresh_price_period
    market = MarketDataService().update_prices(db, tickers=candidates, period=period, limit=len(candidates))
    signals = SignalEngine().run(db, tickers=candidates, limit=len(candidates))
    etf = update_etf_trends(db)
    next_report = data_coverage_report(db)
    return {
        "status": "repaired" if market.get("updated_assets", 0) else "attempted",
        "period": period,
        "repair_candidates": candidates,
        "market_update": market,
        "signal_run": signals,
        "etf_update": etf,
        "coverage_before": report,
        "coverage": next_report,
    }


def coverage_status(row_count: int, last_date: date | None, today: date) -> str:
    if row_count == 0 or last_date is None:
        return "missing"
    if row_count < settings.minimum_history_rows:
        return "short_history"
    if (today - last_date).days > settings.stale_price_max_age_days:
        return "stale"
    return "ready"
