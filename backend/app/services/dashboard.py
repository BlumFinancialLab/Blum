from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import Asset, ETFTrend, NewsArticle, SentimentAnalysis, SignalSnapshot


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
    etf_trends = db.scalars(select(ETFTrend).order_by(desc(ETFTrend.created_at), desc(ETFTrend.confirmation_score)).limit(10)).all()
    return {
        "market_pulse": {
            "asset_count": asset_count,
            "article_count": article_count,
            "average_sentiment": round(float(sentiment_avg), 4),
            "signal_count": len(latest_by_ticker),
            "classification_mix": classifications,
        },
        "todays_strongest_signals": [signal_payload(item) for item in top],
        "narrative_breakouts": [signal_payload(item) for item in top if item.classification == "Narrative Breakout"],
        "technical_breakouts": [signal_payload(item) for item in top if item.classification == "Technical Breakout"],
        "sentiment_divergence": [signal_payload(item) for item in top if item.classification == "Sentiment Divergence"],
        "watchlist_candidates": [signal_payload(item) for item in top if item.classification in {"Strong Watch", "Watch"}],
        "etf_rotation_leaders": [
            {
                "ticker": item.ticker,
                "category": item.category,
                "momentum_score": item.momentum_score,
                "thematic_score": item.thematic_score,
                "confirmation_score": item.confirmation_score,
            }
            for item in etf_trends
        ],
    }


def signal_payload(signal: SignalSnapshot) -> dict:
    return {
        "ticker": signal.ticker,
        "classification": signal.classification,
        "blum_score": signal.blum_score,
        "risk_level": signal.risk_level,
        "time_horizon": signal.time_horizon,
        "score_breakdown": signal.score_breakdown,
        "explanation": signal.explanation,
        "watch_points": signal.watch_points,
        "created_at": signal.created_at,
    }

