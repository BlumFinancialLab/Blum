from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ingestion.news_ingestor import NewsIngestor
from app.models import NewsArticle, PriceHistory, SignalSnapshot
from app.services.accuracy import run_accuracy_audit
from app.services.etf import update_etf_trends
from app.services.fundamentals import update_fundamentals
from app.services.ipo import update_ipo_radar
from app.services.macro import update_macro_snapshots
from app.services.market_data import MarketDataService
from app.signals.engine import SignalEngine


class PipelineService:
    """Runs the real-data intelligence pipeline and returns audit diagnostics."""

    def run(self, db: Session, tickers: list[str] | None = None, limit: int = 36, period: str = "max") -> dict:
        market = MarketDataService().update_prices(db, tickers=tickers, period=period, limit=limit)
        news = NewsIngestor().update_news(db, lookback_hours=72, limit_per_feed=35)
        signals = SignalEngine().run(db, tickers=tickers, limit=limit)
        etf = update_etf_trends(db)
        ipo = update_ipo_radar(db, limit_per_form=35)
        macro = update_macro_snapshots(db)
        fundamentals = update_fundamentals(db, tickers=tickers, limit=min(limit, 24))
        accuracy = run_accuracy_audit(db, limit=limit)
        readiness = pipeline_readiness(db)
        return {
            "market_update": market,
            "news_update": news,
            "signal_run": signals,
            "etf_update": etf,
            "ipo_update": ipo,
            "macro_update": macro,
            "fundamentals_update": fundamentals,
            "accuracy_audit": accuracy,
            "readiness": readiness,
            "status": "ready" if readiness["signal_count"] > 0 else "incomplete",
            "message": pipeline_message(readiness, market),
        }


def pipeline_readiness(db: Session) -> dict:
    provider_rows = db.execute(
        select(PriceHistory.provider, func.count(PriceHistory.id))
        .group_by(PriceHistory.provider)
        .order_by(func.count(PriceHistory.id).desc())
    ).all()
    return {
        "price_row_count": int(db.scalar(select(func.count(PriceHistory.id))) or 0),
        "news_article_count": int(db.scalar(select(func.count(NewsArticle.id))) or 0),
        "signal_count": int(db.scalar(select(func.count(SignalSnapshot.id))) or 0),
        "price_providers": [{"provider": provider, "rows": int(count)} for provider, count in provider_rows],
    }


def pipeline_message(readiness: dict, market: dict) -> str:
    if readiness["signal_count"] > 0:
        return "The intelligence pipeline produced signal snapshots from real public data."
    if readiness["price_row_count"] == 0:
        missing = market.get("missing_assets", [])
        return (
            "No signals were created because no real OHLCV rows were stored. "
            f"Every configured public price provider failed or returned no data for {len(missing)} assets."
        )
    if readiness["news_article_count"] == 0:
        return "Prices are available, but no public news articles were stored yet. Signals can still run, but narrative evidence is missing."
    return "Data exists, but the signal engine did not create snapshots. Check indicator history length and provider diagnostics."
