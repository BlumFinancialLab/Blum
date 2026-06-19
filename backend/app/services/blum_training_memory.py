from __future__ import annotations

from statistics import mean

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import (
    Asset,
    BlumReasoningMemory,
    ConfidenceAdjustment,
    HistoricalSimilarityCase,
    SectorAccuracyProfile,
    SignalEvaluation,
    TickerAccuracyProfile,
)


class BlumTrainingMemoryService:
    """Read-only memory layer used by the chat assistant to ground reasoning in Blum outcomes."""

    def asset_memory(self, db: Session, asset: Asset, limit: int = 8) -> dict:
        evaluations = db.scalars(
            select(SignalEvaluation)
            .where(SignalEvaluation.asset_id == asset.id)
            .order_by(desc(SignalEvaluation.updated_at))
            .limit(limit)
        ).all()
        ticker_profile = db.scalar(select(TickerAccuracyProfile).where(TickerAccuracyProfile.ticker == asset.ticker).limit(1))
        sector_profile = db.scalar(select(SectorAccuracyProfile).where(SectorAccuracyProfile.sector == asset.sector).limit(1))
        similarity = db.scalars(
            select(HistoricalSimilarityCase)
            .where(HistoricalSimilarityCase.asset_id == asset.id)
            .order_by(desc(HistoricalSimilarityCase.similarity_score), desc(HistoricalSimilarityCase.created_at))
            .limit(limit)
        ).all()
        adjustments = db.scalars(
            select(ConfidenceAdjustment)
            .where(ConfidenceAdjustment.asset_id == asset.id)
            .order_by(desc(ConfidenceAdjustment.created_at))
            .limit(5)
        ).all()
        mature = [row for row in evaluations if row.outcome != "inconclusive"]
        return {
            "status": "ready" if evaluations or ticker_profile or sector_profile else "limited_memory",
            "ticker": asset.ticker,
            "evaluated_signals": len(evaluations),
            "mature_evaluations": len(mature),
            "historical_success_rate": success_rate(mature),
            "average_realized_return": average([row.realized_return for row in mature]),
            "average_drawdown": average([row.max_drawdown for row in mature]),
            "ticker_accuracy_profile": serialize_profile(ticker_profile),
            "sector_accuracy_profile": serialize_profile(sector_profile),
            "similar_cases": [serialize_similarity(row) for row in similarity],
            "confidence_adjustments": [serialize_adjustment(row) for row in adjustments],
            "learning_summary": learning_summary(asset, mature, ticker_profile, sector_profile),
            "policy": "Memory is based on stored Blum signal outcomes and reasoning records. Missing samples lower confidence.",
        }

    def semantic_memory(self, db: Session, query: str, limit: int = 6) -> list[dict]:
        rows = db.scalars(select(BlumReasoningMemory).order_by(desc(BlumReasoningMemory.created_at)).limit(600)).all()
        query_terms = {token for token in query.lower().split() if len(token) > 3}
        ranked = []
        for row in rows:
            sector = row.metadata_payload.get("sector") or row.metadata_payload.get("asset_context", {}).get("sector") or ""
            text = f"{row.ticker} {sector} {row.memory_text}".lower()
            overlap = sum(1 for token in query_terms if token in text)
            if overlap:
                ranked.append((row, overlap))
        ranked.sort(key=lambda item: (item[1], item[0].created_at), reverse=True)
        return [
            {
                "ticker": row.ticker,
                "sector": row.metadata_payload.get("sector") or row.metadata_payload.get("asset_context", {}).get("sector"),
                "similarity_proxy": score,
                "memory_text": row.memory_text[:700],
                "outcome_summary": row.metadata_payload.get("outcome_summary") or {"outcome_label": row.outcome_label},
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row, score in ranked[:limit]
        ]


def serialize_profile(profile) -> dict | None:
    if profile is None:
        return None
    return {
        "evaluated_signals": profile.evaluated_signals,
        "correct_rate": profile.correct_rate,
        "neutral_rate": profile.neutral_rate,
        "average_return": profile.average_return,
        "average_drawdown": profile.average_drawdown,
        "accuracy_score": profile.accuracy_score,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def serialize_similarity(row: HistoricalSimilarityCase) -> dict:
    return {
        "case_date": row.case_date.isoformat() if row.case_date else None,
        "similarity_score": row.similarity_score,
        "features": row.features,
        "outcome_summary": row.outcome_summary,
    }


def serialize_adjustment(row: ConfidenceAdjustment) -> dict:
    return {
        "base_confidence": row.base_confidence,
        "adjusted_confidence": row.adjusted_confidence,
        "adjustment": row.adjustment,
        "reason": row.reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def success_rate(rows: list[SignalEvaluation]) -> float | None:
    if not rows:
        return None
    correct = sum(1 for row in rows if row.outcome == "correct")
    return round(correct / len(rows) * 100, 1)


def average(values: list[float | None]) -> float | None:
    cleaned = [float(value) for value in values if value is not None]
    return round(mean(cleaned), 4) if cleaned else None


def learning_summary(asset: Asset, rows: list[SignalEvaluation], ticker_profile, sector_profile) -> str:
    if not rows and not ticker_profile and not sector_profile:
        return f"Blum has limited evaluated memory for {asset.ticker}; confidence should remain conservative until more outcomes mature."
    rate = success_rate(rows)
    if rate is not None:
        return f"Blum has evaluated {len(rows)} mature {asset.ticker} signal horizons with a {rate}% correct-rate proxy."
    if ticker_profile:
        return f"Ticker memory score is {ticker_profile.accuracy_score:.1f}/100 from stored signal outcomes."
    return f"Sector memory is available for {asset.sector}, but ticker-specific evidence remains limited."
