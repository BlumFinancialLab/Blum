from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import Asset, ETFTrend, NewsArticle, PriceHistory, SentimentAnalysis, SignalSnapshot
from app.services.market_data import market_snapshot_for_asset
from app.services.pipeline import pipeline_readiness
from app.services.realtime import realtime_status


def dashboard_overview(db: Session) -> dict:
    signals = db.scalars(select(SignalSnapshot).order_by(desc(SignalSnapshot.created_at), desc(SignalSnapshot.blum_score)).limit(80)).all()
    latest_by_ticker = {}
    for signal in signals:
        latest_by_ticker.setdefault(signal.ticker, signal)
    top = sorted(latest_by_ticker.values(), key=lambda item: item.blum_score, reverse=True)[:12]
    classifications = {}
    for signal in latest_by_ticker.values():
        classifications[signal.classification] = classifications.get(signal.classification, 0) + 1
    sentiment_avg = db.scalar(select(func.avg(SentimentAnalysis.score))) or 0
    article_count = db.scalar(select(func.count(NewsArticle.id))) or 0
    asset_count = db.scalar(select(func.count(Asset.id))) or 0
    etf_trends = db.execute(
        select(ETFTrend, Asset)
        .join(Asset, Asset.id == ETFTrend.asset_id)
        .order_by(desc(ETFTrend.created_at), desc(ETFTrend.confirmation_score))
        .limit(10)
    ).all()
    return {
        "market_pulse": {
            "asset_count": asset_count,
            "article_count": article_count,
            "average_sentiment": round(float(sentiment_avg), 4),
            "signal_count": len(latest_by_ticker),
            "classification_mix": classifications,
            "price_row_count": int(db.scalar(select(func.count(PriceHistory.id))) or 0),
        },
        "readiness": pipeline_readiness(db),
        "realtime": realtime_status(),
        "todays_strongest_signals": [signal_payload(item, db) for item in top],
        "narrative_breakouts": [signal_payload(item, db) for item in top if item.classification == "Narrative Breakout"],
        "technical_breakouts": [signal_payload(item, db) for item in top if item.classification == "Technical Breakout"],
        "sentiment_divergence": [signal_payload(item, db) for item in top if item.classification == "Sentiment Divergence"],
        "watchlist_candidates": [signal_payload(item, db) for item in top if item.classification in {"Strong Watch", "Watch"}],
        "etf_rotation_leaders": [etf_payload(item, asset, db) for item, asset in etf_trends],
    }


def signal_payload(signal: SignalSnapshot, db: Session | None = None) -> dict:
    payload = {
        "ticker": signal.ticker,
        "classification": signal.classification,
        "blum_score": signal.blum_score,
        "risk_level": signal.risk_level,
        "time_horizon": signal.time_horizon,
        "score_version": signal.score_version,
        "confidence_score": signal.confidence_score,
        "lifecycle_state": signal.lifecycle_state,
        "score_breakdown": signal.score_breakdown,
        "explanation": signal.explanation,
        "watch_points": signal.watch_points,
        "created_at": signal.created_at,
    }
    if db is not None and signal.asset is not None:
        payload["asset"] = {
            "ticker": signal.asset.ticker,
            "name": signal.asset.name,
            "category": signal.asset.category,
            "sector": signal.asset.sector,
            "industry": signal.asset.industry,
            "country": signal.asset.country,
            "asset_type": signal.asset.asset_type,
            "currency": signal.asset.currency,
            "exchange": signal.asset.exchange,
            "description": signal.asset.description,
        }
        payload["market_snapshot"] = market_snapshot_for_asset(db, signal.asset)
    return payload


def etf_payload(item: ETFTrend, asset: Asset, db: Session) -> dict:
    return {
        "ticker": item.ticker,
        "category": item.category,
        "asset": {
            "ticker": asset.ticker,
            "name": asset.name,
            "category": asset.category,
            "sector": asset.sector,
            "industry": asset.industry,
            "country": asset.country,
            "asset_type": asset.asset_type,
            "currency": asset.currency,
            "exchange": asset.exchange,
            "description": asset.description,
        },
        "market_snapshot": market_snapshot_for_asset(db, asset),
        "momentum_score": item.momentum_score,
        "thematic_score": item.thematic_score,
        "confirmation_score": item.confirmation_score,
    }
