from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Asset, ETFTrend, SignalSnapshot
from app.services.market_data import market_snapshot_for_asset


def update_etf_trends(db: Session) -> dict:
    etfs = db.scalars(select(Asset).where(Asset.asset_type == "ETF", Asset.is_active.is_(True))).all()
    created = 0
    for etf in etfs:
        signal = db.scalar(select(SignalSnapshot).where(SignalSnapshot.asset_id == etf.id).order_by(desc(SignalSnapshot.created_at)).limit(1))
        if not signal:
            continue
        breakdown = signal.score_breakdown or {}
        trend = ETFTrend(
            asset_id=etf.id,
            ticker=etf.ticker,
            category=etf.category,
            momentum_score=breakdown.get("momentum_score", 0),
            thematic_score=breakdown.get("semantic_trend_score", 0),
            confirmation_score=(breakdown.get("momentum_score", 0) * 0.45 + breakdown.get("trend_score", 0) * 0.35 + breakdown.get("sentiment_score", 0) * 0.20),
            details={
                "sector": etf.sector,
                "classification": signal.classification,
                "risk_level": signal.risk_level,
                "score_breakdown": breakdown,
            },
        )
        db.add(trend)
        created += 1
    db.commit()
    return {"etf_trends_created": created}


def list_etf_trends(db: Session, limit: int = 30) -> list[dict]:
    rows = db.execute(
        select(ETFTrend, Asset)
        .join(Asset, Asset.id == ETFTrend.asset_id)
        .order_by(desc(ETFTrend.created_at), desc(ETFTrend.confirmation_score))
        .limit(limit)
    ).all()
    return [
        {
            "ticker": trend.ticker,
            "category": trend.category,
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
            "momentum_score": round(trend.momentum_score, 1),
            "thematic_score": round(trend.thematic_score, 1),
            "confirmation_score": round(trend.confirmation_score, 1),
            "details": trend.details,
            "created_at": trend.created_at,
        }
        for trend, asset in rows
    ]
