from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from math import sqrt
from statistics import mean, stdev
from typing import Any

import pandas as pd
from sqlalchemy import and_, delete, desc, func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Asset,
    ConfidenceAdjustment,
    HistoricalSimilarityCase,
    LearningEvent,
    ModelWeightVersion,
    NewsArticle,
    NewsAssetLink,
    PriceHistory,
    SectorAccuracyProfile,
    SignalEvaluation,
    SignalOutcome,
    SignalSnapshot,
    SourceReliabilityScore,
    TickerAccuracyProfile,
)
from app.scoring.weights import OPPORTUNITY_WEIGHTS, normalized_weights
from app.signals.engine import load_prices


settings = get_settings()
HORIZONS = (1, 3, 7, 14, 30)
MATURE_OUTCOMES = ("correct", "wrong", "neutral")
DISCLAIMER = (
    "Educational research case study only. Blum does not provide financial advice, "
    "does not execute trades and never claims certainty."
)


def brain_status(db: Session) -> dict:
    total_evaluations = int(db.scalar(select(func.count(SignalEvaluation.id))) or 0)
    mature_evaluations = int(
        db.scalar(select(func.count(SignalEvaluation.id)).where(SignalEvaluation.outcome.in_(MATURE_OUTCOMES))) or 0
    )
    pending = int(
        db.scalar(select(func.count(SignalEvaluation.id)).where(SignalEvaluation.outcome == "inconclusive")) or 0
    )
    historical_accuracy = success_rate(db)
    success_7d = success_rate(db, horizon_days=7)
    success_30d = success_rate(db, horizon_days=30)
    data_quality = db.scalar(select(func.avg(SignalEvaluation.data_quality_score))) or 0.0
    calibration = confidence_calibration(db)
    active_version = active_weight_version(db)
    best, weakest = signal_type_extremes(db)
    drift_warning = model_drift_warning(success_7d, success_30d, calibration, mature_evaluations)

    return {
        "name": "Blum Financial Brain",
        "generated_at": datetime.utcnow().isoformat(),
        "learning_state": "Learning Active" if settings.enable_learning_loop else "Learning Passive",
        "scheduler_enabled": settings.enable_learning_loop,
        "learning_interval_minutes": settings.learning_loop_minutes,
        "signals_evaluated": total_evaluations,
        "mature_evaluations": mature_evaluations,
        "pending_evaluations": pending,
        "historical_accuracy": historical_accuracy,
        "success_rate_7d": success_7d,
        "success_rate_30d": success_30d,
        "confidence_calibration": calibration,
        "best_performing_signal_types": best,
        "weakest_signal_types": weakest,
        "data_quality_score": round(float(data_quality), 1),
        "model_drift_warning": drift_warning,
        "active_weight_version": serialize_weight_version(active_version),
        "governance": [
            "No absolute certainty is shown.",
            "No direct buy or sell instructions are generated.",
            "Every adjustment is logged as a reversible database record.",
            "The learning loop updates parameters and confidence, not source code.",
            "Evidence is separated into observed data, inference and hypothesis.",
            "No automated trading is connected or allowed.",
        ],
        "disclaimer": DISCLAIMER,
    }


def brain_accuracy(db: Session) -> dict:
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "historical_accuracy": success_rate(db),
        "success_rate_7d": success_rate(db, horizon_days=7),
        "success_rate_30d": success_rate(db, horizon_days=30),
        "confidence_calibration": confidence_calibration(db),
        "by_signal_type": group_performance(db, SignalEvaluation.signal_type),
        "by_sector": group_performance(db, SignalEvaluation.sector),
        "ticker_profiles": [serialize_ticker_profile(row) for row in db.scalars(select(TickerAccuracyProfile).order_by(desc(TickerAccuracyProfile.updated_at)).limit(80)).all()],
        "sector_profiles": [serialize_sector_profile(row) for row in db.scalars(select(SectorAccuracyProfile).order_by(desc(SectorAccuracyProfile.updated_at)).limit(80)).all()],
        "source_reliability": [serialize_source_reliability(row) for row in db.scalars(select(SourceReliabilityScore).order_by(desc(SourceReliabilityScore.reliability_score)).limit(80)).all()],
        "disclaimer": DISCLAIMER,
    }


def brain_learning_events(db: Session, limit: int = 50) -> list[dict]:
    rows = db.scalars(select(LearningEvent).order_by(desc(LearningEvent.created_at)).limit(limit)).all()
    return [serialize_learning_event(row) for row in rows]


def brain_signal_evaluations(db: Session, ticker: str | None = None, limit: int = 120) -> list[dict]:
    query = select(SignalEvaluation).order_by(desc(SignalEvaluation.created_at), desc(SignalEvaluation.horizon_days))
    if ticker:
        query = query.where(SignalEvaluation.ticker == ticker.upper())
    rows = db.scalars(query.limit(limit)).all()
    return [serialize_evaluation(row) for row in rows]


def brain_asset_memory(db: Session, asset: Asset) -> dict:
    latest_signal = db.scalar(select(SignalSnapshot).where(SignalSnapshot.asset_id == asset.id).order_by(desc(SignalSnapshot.created_at)).limit(1))
    evaluations = db.scalars(
        select(SignalEvaluation).where(SignalEvaluation.asset_id == asset.id).order_by(desc(SignalEvaluation.signal_created_at), SignalEvaluation.horizon_days).limit(80)
    ).all()
    confidence = db.scalars(
        select(ConfidenceAdjustment).where(ConfidenceAdjustment.asset_id == asset.id).order_by(desc(ConfidenceAdjustment.created_at)).limit(30)
    ).all()
    similar_cases = db.scalars(
        select(HistoricalSimilarityCase).where(HistoricalSimilarityCase.asset_id == asset.id).order_by(desc(HistoricalSimilarityCase.created_at), desc(HistoricalSimilarityCase.similarity_score)).limit(20)
    ).all()
    profile = db.scalar(select(TickerAccuracyProfile).where(TickerAccuracyProfile.ticker == asset.ticker))
    sector_profile = db.scalar(select(SectorAccuracyProfile).where(SectorAccuracyProfile.sector == asset.sector))
    summary = summarize_memory(asset, profile, sector_profile, evaluations, confidence, similar_cases)
    return {
        "ticker": asset.ticker,
        "generated_at": datetime.utcnow().isoformat(),
        "learning_state": "Learning Active" if settings.enable_learning_loop else "Learning Passive",
        "latest_signal": {
            "classification": latest_signal.classification,
            "score": latest_signal.blum_score,
            "confidence": latest_signal.confidence_score,
            "created_at": iso(latest_signal.created_at),
        }
        if latest_signal
        else None,
        "blum_memory_summary": summary,
        "historical_similarity": aggregate_similarity(similar_cases),
        "similar_historical_setups": [serialize_similarity_case(row) for row in similar_cases[:8]],
        "confidence_evolution": [serialize_confidence_adjustment(row) for row in confidence],
        "signal_outcome_history": [serialize_evaluation(row) for row in evaluations[:30]],
        "why_confidence_changed": [row.reason for row in confidence[:6]],
        "what_blum_learned": learned_points(asset, profile, sector_profile, evaluations, similar_cases),
        "governance_note": "This memory changes confidence and ranking evidence only; it does not issue orders or modify source code.",
        "disclaimer": DISCLAIMER,
    }


def brain_confidence_history(db: Session, asset: Asset) -> dict:
    rows = db.scalars(select(ConfidenceAdjustment).where(ConfidenceAdjustment.asset_id == asset.id).order_by(desc(ConfidenceAdjustment.created_at)).limit(120)).all()
    return {
        "ticker": asset.ticker,
        "rows": [serialize_confidence_adjustment(row) for row in rows],
        "latest": serialize_confidence_adjustment(rows[0]) if rows else None,
        "disclaimer": DISCLAIMER,
    }


def evaluate_signals_for_learning(db: Session, limit: int = 240) -> dict:
    signals = db.scalars(select(SignalSnapshot).order_by(desc(SignalSnapshot.created_at)).limit(limit)).all()
    created = 0
    updated = 0
    inconclusive = 0
    mature = 0
    for signal in signals:
        asset = signal.asset or db.scalar(select(Asset).where(Asset.id == signal.asset_id))
        if not asset:
            continue
        prices = load_prices(db, asset.id)
        for horizon in HORIZONS:
            evaluation = db.scalar(
                select(SignalEvaluation).where(
                    and_(SignalEvaluation.signal_id == signal.id, SignalEvaluation.horizon_days == horizon)
                )
            )
            is_new = evaluation is None
            if evaluation is None:
                evaluation = SignalEvaluation(signal_id=signal.id, asset_id=asset.id, ticker=signal.ticker, signal_type=signal.classification, horizon_days=horizon, signal_created_at=signal.created_at)
                db.add(evaluation)
            result = evaluate_signal_horizon(signal, asset, prices, horizon)
            apply_evaluation(evaluation, signal, asset, result)
            if result["outcome"] == "inconclusive":
                inconclusive += 1
            else:
                mature += 1
            created += 1 if is_new else 0
            updated += 0 if is_new else 1
        update_signal_outcome(db, signal, asset)

    profile_result = refresh_accuracy_profiles(db)
    source_result = refresh_source_reliability(db)
    confidence_result = refresh_confidence_adjustments(db, limit=min(limit, 120))
    similarity_result = refresh_similarity_cases(db, limit=min(limit, 120))
    event = LearningEvent(
        event_type="signal_evaluation_cycle",
        severity="Info",
        title="Signal evaluation cycle completed",
        description=(
            f"Evaluated {len(signals)} signal snapshots across {len(HORIZONS)} horizons. "
            "Inconclusive rows remain pending until future OHLCV observations mature."
        ),
        payload={
            "signals_seen": len(signals),
            "evaluations_created": created,
            "evaluations_updated": updated,
            "mature_evaluations": mature,
            "inconclusive_evaluations": inconclusive,
            "profiles": profile_result,
            "sources": source_result,
            "confidence_adjustments": confidence_result,
            "similarity_cases": similarity_result,
        },
    )
    db.add(event)
    db.commit()
    return {
        "status": "ok",
        "signals_seen": len(signals),
        "evaluations_created": created,
        "evaluations_updated": updated,
        "mature_evaluations": mature,
        "inconclusive_evaluations": inconclusive,
        "profiles": profile_result,
        "sources": source_result,
        "confidence_adjustments": confidence_result,
        "similarity_cases": similarity_result,
        "learning_event_id": event.id,
        "disclaimer": DISCLAIMER,
    }


def recalculate_model_weights(db: Session) -> dict:
    mature_count = int(db.scalar(select(func.count(SignalEvaluation.id)).where(SignalEvaluation.outcome.in_(MATURE_OUTCOMES))) or 0)
    previous = active_model_weights(db)
    if mature_count < 8:
        event = LearningEvent(
            event_type="weight_recalibration_skipped",
            severity="Warning",
            title="Insufficient mature signals for weight recalibration",
            description="Blum did not change factor weights because the historical evaluation sample is not yet statistically useful.",
            payload={"mature_evaluations": mature_count, "minimum_required": 8, "weights": previous},
        )
        db.add(event)
        db.commit()
        return {
            "status": "insufficient_sample",
            "mature_evaluations": mature_count,
            "minimum_required": 8,
            "weights_unchanged": previous,
            "learning_event_id": event.id,
            "governance": "No weights changed. Blum waits for real matured outcomes before recalibration.",
        }

    by_type = {row["key"]: row for row in group_performance(db, SignalEvaluation.signal_type)}
    proposed = dict(previous)
    proposed = adjust_group(proposed, by_type.get("Technical Breakout"), ["momentum", "trend", "volume"])
    proposed = adjust_group(proposed, by_type.get("Narrative Breakout"), ["sentiment", "news", "sector"])
    proposed = adjust_group(proposed, by_type.get("Sentiment Divergence"), ["sentiment", "risk"])
    proposed = adjust_group(proposed, by_type.get("High Risk / High Momentum"), ["risk", "volume"], inverse=True)
    proposed = normalized_weights({key: max(0.03, min(0.26, value)) for key, value in proposed.items()})
    if weights_close(previous, proposed):
        event = LearningEvent(
            event_type="weight_recalibration_noop",
            severity="Info",
            title="Weights already calibrated",
            description="Observed mature outcomes did not justify a material weight change.",
            payload={"mature_evaluations": mature_count, "weights": previous, "by_signal_type": by_type},
        )
        db.add(event)
        db.commit()
        return {"status": "no_material_change", "mature_evaluations": mature_count, "weights": previous, "learning_event_id": event.id}

    db.execute(update(ModelWeightVersion).where(ModelWeightVersion.is_active.is_(True)).values(is_active=False))
    version = f"brain-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    weight_version = ModelWeightVersion(
        version=version,
        weights=proposed,
        previous_weights=previous,
        calibration_metrics={
            "mature_evaluations": mature_count,
            "historical_accuracy": success_rate(db),
            "success_rate_7d": success_rate(db, horizon_days=7),
            "success_rate_30d": success_rate(db, horizon_days=30),
            "by_signal_type": by_type,
        },
        change_reason="Database-only adaptive recalibration from matured signal outcomes. Source code was not modified.",
        is_active=True,
    )
    event = LearningEvent(
        event_type="weight_recalibration",
        severity="Info",
        title="Adaptive factor weights recalibrated",
        description="Blum created a new reversible model_weight_versions row from historical outcome evidence.",
        payload={"version": version, "previous_weights": previous, "new_weights": proposed, "mature_evaluations": mature_count},
    )
    db.add(weight_version)
    db.add(event)
    db.commit()
    return {
        "status": "updated",
        "version": version,
        "previous_weights": previous,
        "new_weights": proposed,
        "mature_evaluations": mature_count,
        "learning_event_id": event.id,
        "governance": "Weights changed only in the database and can be reversed by activating a previous version.",
    }


def run_learning_cycle(db: Session, limit: int = 240) -> dict:
    evaluation = evaluate_signals_for_learning(db, limit=limit)
    weights = recalculate_model_weights(db)
    event = LearningEvent(
        event_type="autonomous_learning_cycle",
        severity="Info",
        title="Autonomous learning cycle completed",
        description="Blum evaluated matured signals, refreshed memory profiles, recalculated confidence and audited weight calibration.",
        payload={"evaluation": evaluation, "weights": weights},
    )
    db.add(event)
    db.commit()
    return {"status": "ok", "evaluation": evaluation, "weights": weights, "learning_event_id": event.id, "disclaimer": DISCLAIMER}


def active_model_weights(db: Session | None = None) -> dict[str, float]:
    if db is None:
        return normalized_weights(OPPORTUNITY_WEIGHTS)
    active = active_weight_version(db)
    if active and active.weights:
        return normalized_weights({key: float(active.weights.get(key, value)) for key, value in OPPORTUNITY_WEIGHTS.items()})
    return normalized_weights(OPPORTUNITY_WEIGHTS)


def evaluate_signal_horizon(signal: SignalSnapshot, asset: Asset, prices: pd.DataFrame, horizon_days: int) -> dict:
    signal_date = as_date(signal.created_at)
    target_date = signal_date + timedelta(days=horizon_days)
    expected_direction = expected_direction_for(signal)
    initial_thesis = thesis_snapshot(signal)
    news_evidence = {
        "news_count_7d": value_from_dict(signal.narrative_summary, "news_count_7d"),
        "news_count_30d": value_from_dict(signal.narrative_summary, "news_count_30d"),
        "narrative_intensity": value_from_dict(signal.narrative_summary, "narrative_intensity"),
        "semantic_trend_score": value_from_dict(signal.narrative_summary, "semantic_trend_score"),
    }
    base_payload = {
        "horizon_days": horizon_days,
        "target_date": target_date.isoformat(),
        "observed_data": {"price_source": "stored_price_history", "price_rows": int(len(prices))},
        "inference": {"expected_direction": expected_direction, "signal_type": signal.classification},
        "hypothesis": initial_thesis.get("executive_thesis")
        or "A positive watch signal should show price resilience or follow-through after the chosen horizon.",
        "initial_thesis": initial_thesis,
    }
    if prices.empty:
        reason = "No stored OHLCV rows were available for evaluation."
        return {
            **base_payload,
            "news_evidence": news_evidence,
            "price_at_signal": None,
            "price_after_horizon": None,
            "max_drawdown": None,
            "max_upside": None,
            "realized_return": None,
            "volatility_after_signal": None,
            "outcome": "inconclusive",
            "explanation_quality_score": explanation_quality(signal),
            "data_quality_score": data_quality(signal, asset, prices, news_evidence),
            "reason": reason,
            "thesis_learning": thesis_learning(signal, "inconclusive", None, expected_direction, horizon_days, initial_thesis, reason),
        }

    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    entry = latest_row_on_or_before(frame, signal_date)
    target = earliest_row_on_or_after(frame, target_date)
    if entry is None or target is None or date.today() < target_date:
        reason = "The requested horizon has not matured or the future price row is not stored yet."
        return {
            **base_payload,
            "news_evidence": news_evidence,
            "price_at_signal": float(entry["close"]) if entry is not None else None,
            "price_after_horizon": float(target["close"]) if target is not None else None,
            "max_drawdown": None,
            "max_upside": None,
            "realized_return": None,
            "volatility_after_signal": None,
            "outcome": "inconclusive",
            "explanation_quality_score": explanation_quality(signal),
            "data_quality_score": data_quality(signal, asset, prices, news_evidence),
            "reason": reason,
            "thesis_learning": thesis_learning(signal, "inconclusive", None, expected_direction, horizon_days, initial_thesis, reason),
        }

    entry_price = float(entry["close"])
    target_price = float(target["close"])
    window = frame[(frame["date"] >= entry["date"]) & (frame["date"] <= target["date"])].copy()
    realized = pct(entry_price, target_price)
    drawdown = pct(entry_price, float(window["low"].astype(float).min())) if not window.empty else None
    upside = pct(entry_price, float(window["high"].astype(float).max())) if not window.empty else None
    volatility = realized_volatility(window)
    outcome = classify_outcome(realized, expected_direction)
    reason = outcome_reason(outcome, realized, expected_direction, horizon_days)
    return {
        **base_payload,
        "news_evidence": news_evidence,
        "price_at_signal": round(entry_price, 4),
        "price_after_horizon": round(target_price, 4),
        "max_drawdown": drawdown,
        "max_upside": upside,
        "realized_return": realized,
        "volatility_after_signal": volatility,
        "outcome": outcome,
        "explanation_quality_score": explanation_quality(signal),
        "data_quality_score": data_quality(signal, asset, prices, news_evidence),
        "reason": reason,
        "thesis_learning": thesis_learning(signal, outcome, realized, expected_direction, horizon_days, initial_thesis, reason),
    }


def apply_evaluation(evaluation: SignalEvaluation, signal: SignalSnapshot, asset: Asset, result: dict) -> None:
    evaluation.asset_id = asset.id
    evaluation.ticker = signal.ticker
    evaluation.sector = asset.sector or "Unknown"
    evaluation.signal_type = signal.classification
    evaluation.expected_direction = result["inference"]["expected_direction"]
    evaluation.time_horizon = signal.time_horizon
    evaluation.signal_created_at = signal.created_at
    evaluation.initial_confidence = float(signal.confidence_score or 0.0)
    evaluation.initial_sentiment = float(value_from_dict(signal.narrative_summary, "sentiment_7d"))
    evaluation.initial_momentum = float(value_from_dict(signal.score_breakdown, "momentum_score"))
    evaluation.news_evidence = result.get("news_evidence", {})
    evaluation.price_at_signal = result.get("price_at_signal")
    evaluation.price_after_horizon = result.get("price_after_horizon")
    evaluation.max_drawdown = result.get("max_drawdown")
    evaluation.max_upside = result.get("max_upside")
    evaluation.realized_return = result.get("realized_return")
    evaluation.volatility_after_signal = result.get("volatility_after_signal")
    evaluation.outcome = result.get("outcome", "inconclusive")
    evaluation.explanation_quality_score = float(result.get("explanation_quality_score") or 0.0)
    evaluation.data_quality_score = float(result.get("data_quality_score") or 0.0)
    evaluation.evaluation_payload = {
        "observed_data": result.get("observed_data", {}),
        "inference": result.get("inference", {}),
        "hypothesis": result.get("hypothesis", ""),
        "initial_thesis": result.get("initial_thesis", {}),
        "thesis_learning": result.get("thesis_learning", {}),
        "reason": result.get("reason", ""),
        "target_date": result.get("target_date"),
    }
    evaluation.updated_at = datetime.utcnow()


def update_signal_outcome(db: Session, signal: SignalSnapshot, asset: Asset) -> None:
    evaluations = db.scalars(select(SignalEvaluation).where(SignalEvaluation.signal_id == signal.id)).all()
    mature = [row for row in evaluations if row.outcome in MATURE_OUTCOMES and row.realized_return is not None]
    returns = [float(row.realized_return) for row in mature]
    final = "inconclusive"
    if mature:
        correct = sum(1 for row in mature if row.outcome == "correct")
        wrong = sum(1 for row in mature if row.outcome == "wrong")
        neutral = sum(1 for row in mature if row.outcome == "neutral")
        if correct > wrong and correct >= neutral:
            final = "correct"
        elif wrong > correct and wrong >= neutral:
            final = "wrong"
        else:
            final = "neutral"
    outcome = db.scalar(select(SignalOutcome).where(SignalOutcome.signal_id == signal.id))
    if outcome is None:
        outcome = SignalOutcome(signal_id=signal.id, asset_id=asset.id, ticker=signal.ticker, signal_type=signal.classification, signal_created_at=signal.created_at)
        db.add(outcome)
    outcome.asset_id = asset.id
    outcome.ticker = signal.ticker
    outcome.sector = asset.sector or "Unknown"
    outcome.signal_type = signal.classification
    outcome.signal_created_at = signal.created_at
    outcome.initial_score = float(signal.blum_score or 0.0)
    outcome.initial_confidence = float(signal.confidence_score or 0.0)
    outcome.final_outcome = final
    outcome.best_horizon_days = max(mature, key=lambda row: row.realized_return).horizon_days if mature else None
    outcome.worst_horizon_days = min(mature, key=lambda row: row.realized_return).horizon_days if mature else None
    outcome.average_realized_return = round(mean(returns), 3) if returns else None
    outcome.outcome_payload = {
        "evaluations": [serialize_evaluation(row) for row in evaluations],
        "initial_thesis": thesis_snapshot(signal),
        "reasoning_learning": aggregate_thesis_learning(evaluations),
        "initial_features": {
            "score": signal.blum_score,
            "confidence": signal.confidence_score,
            "momentum": value_from_dict(signal.score_breakdown, "momentum_score"),
            "sentiment": value_from_dict(signal.narrative_summary, "sentiment_7d"),
            "risk_level": signal.risk_level,
            "news_count_7d": value_from_dict(signal.narrative_summary, "news_count_7d"),
        },
    }
    outcome.updated_at = datetime.utcnow()


def refresh_accuracy_profiles(db: Session) -> dict:
    ticker_rows = db.execute(
        select(SignalEvaluation.ticker, SignalEvaluation.asset_id).where(SignalEvaluation.outcome.in_(MATURE_OUTCOMES)).group_by(SignalEvaluation.ticker, SignalEvaluation.asset_id)
    ).all()
    ticker_count = 0
    for ticker, asset_id in ticker_rows:
        evaluations = db.scalars(select(SignalEvaluation).where(SignalEvaluation.ticker == ticker, SignalEvaluation.outcome.in_(MATURE_OUTCOMES))).all()
        profile = db.scalar(select(TickerAccuracyProfile).where(TickerAccuracyProfile.ticker == ticker))
        stats = profile_stats(evaluations)
        if profile is None:
            profile = TickerAccuracyProfile(ticker=ticker, asset_id=asset_id)
            db.add(profile)
        profile.asset_id = asset_id
        apply_profile(profile, stats)
        ticker_count += 1

    sectors = [row[0] for row in db.execute(select(SignalEvaluation.sector).where(SignalEvaluation.outcome.in_(MATURE_OUTCOMES)).group_by(SignalEvaluation.sector)).all()]
    sector_count = 0
    for sector in sectors:
        evaluations = db.scalars(select(SignalEvaluation).where(SignalEvaluation.sector == sector, SignalEvaluation.outcome.in_(MATURE_OUTCOMES))).all()
        profile = db.scalar(select(SectorAccuracyProfile).where(SectorAccuracyProfile.sector == sector))
        stats = profile_stats(evaluations)
        if profile is None:
            profile = SectorAccuracyProfile(sector=sector or "Unknown")
            db.add(profile)
        profile.sector = sector or "Unknown"
        apply_profile(profile, stats)
        sector_count += 1
    return {"ticker_profiles_updated": ticker_count, "sector_profiles_updated": sector_count}


def refresh_source_reliability(db: Session) -> dict:
    sources = [row[0] for row in db.execute(select(NewsArticle.source).group_by(NewsArticle.source)).all()]
    updated = 0
    for source in sources:
        article_count = int(db.scalar(select(func.count(NewsArticle.id)).where(NewsArticle.source == source)) or 0)
        rows = db.execute(
            select(SignalOutcome.final_outcome)
            .join(NewsAssetLink, NewsAssetLink.asset_id == SignalOutcome.asset_id)
            .join(NewsArticle, NewsArticle.id == NewsAssetLink.article_id)
            .where(NewsArticle.source == source)
        ).all()
        outcomes = [row[0] for row in rows if row[0] in MATURE_OUTCOMES]
        correct = outcomes.count("correct")
        wrong = outcomes.count("wrong")
        usable = correct + wrong
        correct_rate = correct / usable if usable else None
        false_positive_rate = wrong / usable if usable else None
        score = 50.0 if correct_rate is None else clamp(40 + correct_rate * 55 - (false_positive_rate or 0) * 15)
        record = db.scalar(select(SourceReliabilityScore).where(SourceReliabilityScore.source == source))
        if record is None:
            record = SourceReliabilityScore(source=source)
            db.add(record)
        record.article_count = article_count
        record.linked_signal_count = len(rows)
        record.correct_signal_rate = round(correct_rate, 4) if correct_rate is not None else None
        record.false_positive_rate = round(false_positive_rate, 4) if false_positive_rate is not None else None
        record.reliability_score = round(score, 1)
        record.evidence = {"mature_linked_outcomes": len(outcomes), "correct": correct, "wrong": wrong}
        record.updated_at = datetime.utcnow()
        updated += 1
    return {"sources_updated": updated}


def refresh_confidence_adjustments(db: Session, limit: int = 120) -> dict:
    signals = db.scalars(select(SignalSnapshot).order_by(desc(SignalSnapshot.created_at)).limit(limit)).all()
    created = 0
    for signal in signals:
        asset = signal.asset or db.scalar(select(Asset).where(Asset.id == signal.asset_id))
        if not asset:
            continue
        base = float(signal.confidence_score or 0.0)
        ticker_profile = db.scalar(select(TickerAccuracyProfile).where(TickerAccuracyProfile.ticker == asset.ticker))
        sector_profile = db.scalar(select(SectorAccuracyProfile).where(SectorAccuracyProfile.sector == asset.sector))
        source_score = linked_source_score(db, asset)
        coherence = evidence_coherence(signal)
        risk_penalty = volatility_penalty(signal)
        profile_adjustment = profile_delta(ticker_profile) + profile_delta(sector_profile)
        source_adjustment = (source_score - 50) * 0.08 if source_score is not None else 0.0
        adjustment = clamp(profile_adjustment + source_adjustment + coherence + risk_penalty, -18, 18)
        adjusted = clamp(base + adjustment)
        reason = confidence_reason(signal, asset, adjustment, ticker_profile, sector_profile, source_score, coherence, risk_penalty)
        db.add(
            ConfidenceAdjustment(
                asset_id=asset.id,
                ticker=asset.ticker,
                sector=asset.sector,
                signal_type=signal.classification,
                base_confidence=round(base, 1),
                adjusted_confidence=round(adjusted, 1),
                adjustment=round(adjustment, 1),
                reason=reason,
                evidence={
                    "observed_data": {
                        "ticker_accuracy_score": getattr(ticker_profile, "accuracy_score", None),
                        "sector_accuracy_score": getattr(sector_profile, "accuracy_score", None),
                        "source_reliability_score": source_score,
                    },
                    "inference": {
                        "coherence_adjustment": round(coherence, 2),
                        "risk_penalty": round(risk_penalty, 2),
                    },
                    "hypothesis": "Confidence should rise when similar evidence historically followed through and fall when it did not.",
                },
            )
        )
        created += 1
    return {"confidence_adjustments_created": created}


def refresh_similarity_cases(db: Session, limit: int = 120) -> dict:
    signals = db.scalars(select(SignalSnapshot).order_by(desc(SignalSnapshot.created_at)).limit(limit)).all()
    created = 0
    for signal in signals:
        asset = signal.asset or db.scalar(select(Asset).where(Asset.id == signal.asset_id))
        if not asset:
            continue
        current_features = signal_feature_vector(signal)
        candidates = db.scalars(
            select(SignalOutcome)
            .where(SignalOutcome.signal_id != signal.id, SignalOutcome.final_outcome.in_(MATURE_OUTCOMES))
            .order_by(desc(SignalOutcome.signal_created_at))
            .limit(400)
        ).all()
        ranked = []
        for outcome in candidates:
            features = outcome.outcome_payload.get("initial_features", {}) if outcome.outcome_payload else {}
            similarity = setup_similarity(current_features, features, asset.sector, outcome.sector, signal.classification, outcome.signal_type)
            if similarity >= 45:
                ranked.append((similarity, outcome))
        ranked.sort(key=lambda item: item[0], reverse=True)
        db.execute(delete(HistoricalSimilarityCase).where(HistoricalSimilarityCase.reference_signal_id == signal.id))
        for similarity, outcome in ranked[:8]:
            db.add(
                HistoricalSimilarityCase(
                    asset_id=asset.id,
                    ticker=asset.ticker,
                    reference_signal_id=signal.id,
                    case_date=as_date(outcome.signal_created_at),
                    similarity_score=round(similarity, 1),
                    features={"current": current_features, "historical": outcome.outcome_payload.get("initial_features", {}) if outcome.outcome_payload else {}},
                    outcome_summary={
                        "historical_ticker": outcome.ticker,
                        "historical_signal_type": outcome.signal_type,
                        "final_outcome": outcome.final_outcome,
                        "average_realized_return": outcome.average_realized_return,
                        "best_horizon_days": outcome.best_horizon_days,
                        "worst_horizon_days": outcome.worst_horizon_days,
                    },
                )
            )
            created += 1
    return {"similarity_cases_created": created}


def success_rate(db: Session, horizon_days: int | None = None) -> float | None:
    query = select(SignalEvaluation.outcome).where(SignalEvaluation.outcome.in_(MATURE_OUTCOMES))
    if horizon_days is not None:
        query = query.where(SignalEvaluation.horizon_days == horizon_days)
    outcomes = [row[0] for row in db.execute(query).all()]
    correct = outcomes.count("correct")
    wrong = outcomes.count("wrong")
    denominator = correct + wrong
    if denominator == 0:
        return None
    return round(correct / denominator, 4)


def confidence_calibration(db: Session) -> dict:
    rows = db.execute(
        select(SignalEvaluation.initial_confidence, SignalEvaluation.outcome).where(SignalEvaluation.outcome.in_(MATURE_OUTCOMES))
    ).all()
    scored = [(float(conf), outcome) for conf, outcome in rows if conf is not None and outcome in {"correct", "wrong"}]
    if len(scored) < 5:
        return {"status": "insufficient_sample", "score": None, "sample_size": len(scored)}
    avg_confidence = mean(conf for conf, _ in scored) / 100
    realized = sum(1 for _, outcome in scored if outcome == "correct") / len(scored)
    calibration_error = abs(avg_confidence - realized)
    score = clamp((1 - calibration_error) * 100)
    return {
        "status": "calibrated" if score >= 70 else "needs_attention",
        "score": round(score, 1),
        "sample_size": len(scored),
        "avg_initial_confidence": round(avg_confidence, 4),
        "realized_correct_rate": round(realized, 4),
    }


def signal_type_extremes(db: Session) -> tuple[list[dict], list[dict]]:
    rows = group_performance(db, SignalEvaluation.signal_type)
    usable = [row for row in rows if row["mature_count"] >= 2 and row["success_rate"] is not None]
    best = sorted(usable, key=lambda row: row["success_rate"], reverse=True)[:5]
    weakest = sorted(usable, key=lambda row: row["success_rate"])[:5]
    return best, weakest


def group_performance(db: Session, column) -> list[dict]:
    values = [row[0] for row in db.execute(select(column).where(SignalEvaluation.outcome.in_(MATURE_OUTCOMES)).group_by(column)).all()]
    output = []
    for value in values:
        evaluations = db.scalars(select(SignalEvaluation).where(column == value, SignalEvaluation.outcome.in_(MATURE_OUTCOMES))).all()
        stats = profile_stats(evaluations)
        output.append(
            {
                "key": value or "Unknown",
                "mature_count": stats["evaluated_signals"],
                "success_rate": stats["correct_rate"],
                "neutral_rate": stats["neutral_rate"],
                "average_return": stats["average_return"],
                "average_drawdown": stats["average_drawdown"],
                "accuracy_score": stats["accuracy_score"],
            }
        )
    return sorted(output, key=lambda row: (row["accuracy_score"], row["mature_count"]), reverse=True)


def profile_stats(evaluations: list[SignalEvaluation]) -> dict:
    if not evaluations:
        return {"evaluated_signals": 0, "correct_rate": None, "neutral_rate": None, "average_return": None, "average_drawdown": None, "accuracy_score": 50.0}
    correct = sum(1 for row in evaluations if row.outcome == "correct")
    wrong = sum(1 for row in evaluations if row.outcome == "wrong")
    neutral = sum(1 for row in evaluations if row.outcome == "neutral")
    usable = correct + wrong
    returns = [float(row.realized_return) for row in evaluations if row.realized_return is not None]
    drawdowns = [float(row.max_drawdown) for row in evaluations if row.max_drawdown is not None]
    correct_rate = correct / usable if usable else None
    neutral_rate = neutral / len(evaluations)
    avg_return = mean(returns) if returns else None
    avg_drawdown = mean(drawdowns) if drawdowns else None
    accuracy = 50.0
    if correct_rate is not None:
        accuracy = 35 + correct_rate * 55 + min(10, max(-10, (avg_return or 0) * 0.8)) + neutral_rate * 5
    return {
        "evaluated_signals": len(evaluations),
        "correct_rate": round(correct_rate, 4) if correct_rate is not None else None,
        "neutral_rate": round(neutral_rate, 4),
        "average_return": round(avg_return, 3) if avg_return is not None else None,
        "average_drawdown": round(avg_drawdown, 3) if avg_drawdown is not None else None,
        "accuracy_score": round(clamp(accuracy), 1),
        "correct": correct,
        "wrong": wrong,
        "neutral": neutral,
    }


def apply_profile(profile: TickerAccuracyProfile | SectorAccuracyProfile, stats: dict) -> None:
    profile.evaluated_signals = int(stats["evaluated_signals"])
    profile.correct_rate = stats["correct_rate"]
    profile.neutral_rate = stats["neutral_rate"]
    profile.average_return = stats["average_return"]
    profile.average_drawdown = stats["average_drawdown"]
    profile.accuracy_score = stats["accuracy_score"]
    profile.profile_payload = {"outcome_counts": {"correct": stats.get("correct", 0), "wrong": stats.get("wrong", 0), "neutral": stats.get("neutral", 0)}}
    profile.updated_at = datetime.utcnow()


def model_drift_warning(success_7d: float | None, success_30d: float | None, calibration: dict, mature_count: int) -> dict:
    if mature_count < 8:
        return {"status": "insufficient_sample", "severity": "Info", "message": "Not enough matured outcomes to detect model drift."}
    calibration_score = calibration.get("score")
    if calibration_score is not None and calibration_score < 55:
        return {"status": "calibration_drift", "severity": "Warning", "message": "Initial confidence is materially misaligned with realized outcomes."}
    if success_7d is not None and success_30d is not None and success_7d + 0.15 < success_30d:
        return {"status": "short_term_decay", "severity": "Warning", "message": "7D follow-through is weakening versus 30D outcomes."}
    return {"status": "stable", "severity": "Info", "message": "No material model drift detected from the current matured sample."}


def active_weight_version(db: Session) -> ModelWeightVersion | None:
    return db.scalar(select(ModelWeightVersion).where(ModelWeightVersion.is_active.is_(True)).order_by(desc(ModelWeightVersion.created_at)).limit(1))


def adjust_group(weights: dict[str, float], performance: dict | None, keys: list[str], inverse: bool = False) -> dict[str, float]:
    if not performance or performance.get("success_rate") is None or performance.get("mature_count", 0) < 3:
        return weights
    success = float(performance["success_rate"])
    delta = max(-0.025, min(0.025, (success - 0.52) * 0.04))
    if inverse:
        delta = -delta
    for key in keys:
        if key in weights:
            weights[key] = float(weights[key]) + delta
    return weights


def weights_close(previous: dict, proposed: dict) -> bool:
    return all(abs(float(previous.get(key, 0)) - float(proposed.get(key, 0))) < 0.003 for key in OPPORTUNITY_WEIGHTS)


def linked_source_score(db: Session, asset: Asset) -> float | None:
    rows = db.execute(
        select(SourceReliabilityScore.reliability_score)
        .join(NewsArticle, NewsArticle.source == SourceReliabilityScore.source)
        .join(NewsAssetLink, NewsAssetLink.article_id == NewsArticle.id)
        .where(NewsAssetLink.asset_id == asset.id)
        .limit(20)
    ).all()
    values = [float(row[0]) for row in rows if row[0] is not None]
    return round(mean(values), 1) if values else None


def evidence_coherence(signal: SignalSnapshot) -> float:
    sentiment = float(value_from_dict(signal.narrative_summary, "sentiment_7d"))
    momentum = float(value_from_dict(signal.score_breakdown, "momentum_score"))
    if sentiment > 0.15 and momentum >= 62:
        return 5.0
    if sentiment < -0.15 and momentum >= 65:
        return -6.0
    if sentiment > 0.2 and momentum < 45:
        return -4.0
    return 0.0


def volatility_penalty(signal: SignalSnapshot) -> float:
    technical = signal.technical_summary or {}
    vol = float(value_from_dict(technical, "historical_volatility"))
    drawdown = abs(float(value_from_dict(technical, "recent_drawdown")))
    penalty = 0.0
    if vol > 55:
        penalty -= 4.0
    if drawdown > 18:
        penalty -= 3.0
    if signal.risk_level == "High":
        penalty -= 3.0
    return penalty


def profile_delta(profile: TickerAccuracyProfile | SectorAccuracyProfile | None) -> float:
    if not profile or profile.evaluated_signals < 3:
        return 0.0
    return (float(profile.accuracy_score) - 50.0) * 0.08


def confidence_reason(signal: SignalSnapshot, asset: Asset, adjustment: float, ticker_profile, sector_profile, source_score: float | None, coherence: float, risk_penalty: float) -> str:
    direction = "increases" if adjustment > 1 else "reduces" if adjustment < -1 else "keeps"
    parts = [
        f"Blum {direction} confidence for {asset.ticker} because historical ticker and sector memory, source reliability, evidence coherence and volatility risk were recalculated.",
    ]
    if ticker_profile and ticker_profile.evaluated_signals:
        parts.append(f"Ticker memory: {ticker_profile.evaluated_signals} matured evaluations with accuracy score {ticker_profile.accuracy_score:.1f}.")
    if sector_profile and sector_profile.evaluated_signals:
        parts.append(f"Sector memory: {sector_profile.evaluated_signals} matured evaluations with accuracy score {sector_profile.accuracy_score:.1f}.")
    if source_score is not None:
        parts.append(f"Linked source reliability average is {source_score:.1f}.")
    if coherence:
        parts.append(f"Price-news coherence impact: {coherence:+.1f}.")
    if risk_penalty:
        parts.append(f"Volatility/risk penalty: {risk_penalty:+.1f}.")
    return " ".join(parts)


def setup_similarity(current: dict, historical: dict, current_sector: str, historical_sector: str, current_type: str, historical_type: str) -> float:
    score = 0.0
    score += 24 if current_type == historical_type else 8
    score += 18 if current_sector == historical_sector else 4
    for key, max_distance, weight in [
        ("score", 35, 18),
        ("confidence", 40, 14),
        ("momentum", 45, 16),
        ("sentiment", 1.2, 10),
        ("news_count_7d", 8, 8),
    ]:
        distance = abs(float(current.get(key, 0) or 0) - float(historical.get(key, 0) or 0))
        score += max(0, weight * (1 - min(distance, max_distance) / max_distance))
    return clamp(score)


def signal_feature_vector(signal: SignalSnapshot) -> dict:
    return {
        "score": float(signal.blum_score or 0.0),
        "confidence": float(signal.confidence_score or 0.0),
        "momentum": float(value_from_dict(signal.score_breakdown, "momentum_score")),
        "sentiment": float(value_from_dict(signal.narrative_summary, "sentiment_7d")),
        "news_count_7d": float(value_from_dict(signal.narrative_summary, "news_count_7d")),
        "risk_level": signal.risk_level,
    }


def aggregate_similarity(cases: list[HistoricalSimilarityCase]) -> dict:
    if not cases:
        return {
            "similar_cases_found": 0,
            "average_return": None,
            "success_rate": None,
            "average_drawdown": None,
            "confidence_adjustment": 0,
            "explanation": "No matured historical signal cases are similar enough yet. Blum will update this memory after signals mature.",
        }
    returns = [case.outcome_summary.get("average_realized_return") for case in cases if case.outcome_summary.get("average_realized_return") is not None]
    outcomes = [case.outcome_summary.get("final_outcome") for case in cases]
    success = outcomes.count("correct") / max(1, outcomes.count("correct") + outcomes.count("wrong"))
    adjustment = (success - 0.5) * 18 if outcomes.count("correct") + outcomes.count("wrong") else 0
    return {
        "similar_cases_found": len(cases),
        "average_return": round(mean([float(value) for value in returns]), 3) if returns else None,
        "success_rate": round(success, 4) if outcomes.count("correct") + outcomes.count("wrong") else None,
        "average_drawdown": None,
        "confidence_adjustment": round(adjustment, 1),
        "explanation": (
            f"Blum found {len(cases)} similar matured signal memories. "
            f"Historical follow-through adjusts confidence by {adjustment:+.1f} points."
        ),
    }


def summarize_memory(asset: Asset, profile, sector_profile, evaluations: list[SignalEvaluation], confidence: list[ConfidenceAdjustment], cases: list[HistoricalSimilarityCase]) -> str:
    if not evaluations:
        return f"Blum has not yet stored matured signal evaluations for {asset.ticker}. The memory layer is active and waiting for horizon outcomes."
    mature = [row for row in evaluations if row.outcome in MATURE_OUTCOMES]
    if not mature:
        return f"Blum has {len(evaluations)} pending horizon evaluations for {asset.ticker}; outcome memory will mature as new real OHLCV rows arrive."
    latest_adj = confidence[0].adjustment if confidence else 0
    return (
        f"Blum has evaluated {len(mature)} matured horizons for {asset.ticker}. "
        f"Ticker accuracy score is {getattr(profile, 'accuracy_score', 50):.1f}; sector memory is {getattr(sector_profile, 'accuracy_score', 50):.1f}. "
        f"Latest confidence adjustment is {latest_adj:+.1f}, based on historical outcome memory and evidence coherence."
    )


def learned_points(asset: Asset, profile, sector_profile, evaluations: list[SignalEvaluation], cases: list[HistoricalSimilarityCase]) -> list[str]:
    points = []
    if profile and profile.evaluated_signals:
        points.append(f"{asset.ticker} has {profile.evaluated_signals} matured evaluations with a {profile.accuracy_score:.1f} memory score.")
    if sector_profile and sector_profile.evaluated_signals:
        points.append(f"{asset.sector} setups have {sector_profile.evaluated_signals} matured evaluations and a {sector_profile.accuracy_score:.1f} sector memory score.")
    if cases:
        aggregate = aggregate_similarity(cases)
        points.append(f"Similar historical setups suggest a {aggregate.get('confidence_adjustment', 0):+.1f} confidence adjustment.")
    if not points:
        points.append("Blum needs more matured real-market outcomes before drawing asset-specific learning conclusions.")
    points.append("Any learning output is a research confidence adjustment, not financial advice.")
    return points


def expected_direction_for(signal: SignalSnapshot) -> str:
    if signal.classification == "Avoid / Too Risky":
        return "downside_risk_review"
    return "up_or_resilient"


def classify_outcome(realized_return: float, expected_direction: str) -> str:
    if expected_direction == "downside_risk_review":
        if realized_return <= -0.75:
            return "correct"
        if realized_return >= 2.0:
            return "wrong"
        return "neutral"
    if realized_return >= 0.75:
        return "correct"
    if realized_return <= -2.0:
        return "wrong"
    return "neutral"


def outcome_reason(outcome: str, realized_return: float, expected_direction: str, horizon: int) -> str:
    if outcome == "correct":
        return f"The {horizon}D realized return of {realized_return:.2f}% aligned with the expected {expected_direction} thesis."
    if outcome == "wrong":
        return f"The {horizon}D realized return of {realized_return:.2f}% contradicted the expected {expected_direction} thesis."
    return f"The {horizon}D realized return of {realized_return:.2f}% was not decisive enough to classify the signal as correct or wrong."


def thesis_snapshot(signal: SignalSnapshot) -> dict:
    thesis = ((signal.narrative_summary or {}).get("thesis") or {}) if isinstance(signal.narrative_summary, dict) else {}
    return {
        "executive_thesis": thesis.get("executive_thesis") or signal.explanation,
        "supporting_evidence": thesis.get("supporting_evidence", []),
        "contradicting_evidence": thesis.get("contradicting_evidence", []),
        "confirmation_conditions": thesis.get("confirmation_conditions", []),
        "invalidation_conditions": thesis.get("invalidation_conditions", []),
        "conviction_score": thesis.get("conviction_score", value_from_dict(signal.narrative_summary, "conviction_score")),
        "conviction_reducers": thesis.get("conviction_reducers", []),
        "causal_reasoning": thesis.get("causal_reasoning", {}),
        "narrative_analysis": thesis.get("narrative_analysis", {}),
        "market_context": thesis.get("market_context", {}),
        "what_the_market_may_be_missing": thesis.get("what_the_market_may_be_missing", []),
        "final_blum_view": thesis.get("final_blum_view", ""),
    }


def thesis_learning(
    signal: SignalSnapshot,
    outcome: str,
    realized_return: float | None,
    expected_direction: str,
    horizon_days: int,
    initial_thesis: dict,
    reason: str,
) -> dict:
    contradiction_count = len(initial_thesis.get("contradicting_evidence") or [])
    support_count = len(initial_thesis.get("supporting_evidence") or [])
    conviction = float(initial_thesis.get("conviction_score") or 0.0)
    momentum = value_from_dict(signal.score_breakdown, "momentum_score")
    sentiment = value_from_dict(signal.narrative_summary, "sentiment_7d")
    news_count = value_from_dict(signal.narrative_summary, "news_count_7d")
    risk_level = signal.risk_level or "Unknown"
    hypothesis_result = {
        "correct": "initial thesis supported by realized price behavior",
        "wrong": "initial thesis contradicted by realized price behavior",
        "neutral": "initial thesis not decisively supported or contradicted",
        "inconclusive": "initial thesis cannot be evaluated yet",
    }.get(outcome, "initial thesis unresolved")

    underestimated = []
    overestimated = []
    reasoning_errors = []
    if outcome == "wrong":
        if contradiction_count:
            underestimated.append("Contradicting evidence should receive more weight in similar future setups.")
        if risk_level == "High":
            underestimated.append("High risk classification may have been underweighted versus upside evidence.")
        if sentiment < 0 and momentum >= 60:
            underestimated.append("Negative sentiment was weaker than momentum in the initial thesis but may have mattered more.")
        if momentum >= 68:
            overestimated.append("Momentum strength may have been over-extrapolated.")
        if news_count < 2:
            overestimated.append("The system may have inferred too much from thin news evidence.")
        if conviction >= 65:
            reasoning_errors.append("High conviction was not justified by the realized horizon outcome.")
    elif outcome == "correct":
        if support_count:
            underestimated.append("Supporting evidence appears useful and should remain visible in similar cases.")
        if conviction < 50:
            reasoning_errors.append("Conviction may have been too cautious relative to follow-through.")
    elif outcome == "neutral":
        overestimated.append("The initial thesis may have expected clearer follow-through than the market delivered.")
        if news_count >= 3 and abs(sentiment) > 0.12:
            reasoning_errors.append("Narrative evidence did not translate into decisive price behavior over this horizon.")
    else:
        reasoning_errors.append("No conclusion until the horizon matures and stored OHLCV rows are available.")

    return {
        "horizon_days": horizon_days,
        "expected_direction": expected_direction,
        "realized_return": realized_return,
        "hypothesis_result": hypothesis_result,
        "thesis_was_supported": outcome == "correct",
        "thesis_was_contradicted": outcome == "wrong",
        "evidence_underestimated": underestimated or ["No specific underestimated evidence can be isolated from this evaluation."],
        "factors_potentially_overestimated": overestimated or ["No specific overestimated factor can be isolated from this evaluation."],
        "possible_reasoning_errors": reasoning_errors or ["No repeating reasoning error detected from this horizon alone."],
        "future_adjustment_hint": future_adjustment_hint(outcome, conviction, contradiction_count, momentum, sentiment, news_count, risk_level),
        "reason": reason,
    }


def future_adjustment_hint(
    outcome: str,
    conviction: float,
    contradiction_count: int,
    momentum: float,
    sentiment: float,
    news_count: float,
    risk_level: str,
) -> str:
    if outcome == "wrong" and contradiction_count:
        return "Lower future conviction when contradictions are present unless independent confirmations are stronger."
    if outcome == "wrong" and momentum >= 68 and news_count < 2:
        return "Do not let price momentum alone dominate a thesis when narrative evidence is thin."
    if outcome == "wrong" and risk_level == "High":
        return "Increase the risk penalty for high-volatility setups with weak confirmation."
    if outcome == "correct" and conviction < 50:
        return "Similar aligned setups may deserve a higher baseline conviction once evidence quality is sufficient."
    if outcome == "neutral" and abs(sentiment) > 0.12:
        return "Narrative strength should be treated as context, not as confirmation without price follow-through."
    if outcome == "inconclusive":
        return "Wait for real matured price rows before changing weights or confidence."
    return "No automatic weight change should be inferred from one horizon; aggregate with similar matured cases."


def aggregate_thesis_learning(evaluations: list[SignalEvaluation]) -> dict:
    payloads = [row.evaluation_payload or {} for row in evaluations]
    learnings = [payload.get("thesis_learning", {}) for payload in payloads if payload.get("thesis_learning")]
    if not learnings:
        return {
            "status": "pending",
            "summary": "No thesis-learning payloads are available yet for this signal.",
            "repeating_reasoning_errors": [],
        }
    supported = sum(1 for item in learnings if item.get("thesis_was_supported"))
    contradicted = sum(1 for item in learnings if item.get("thesis_was_contradicted"))
    unresolved = len(learnings) - supported - contradicted
    errors: dict[str, int] = defaultdict(int)
    for item in learnings:
        for error in item.get("possible_reasoning_errors", []):
            errors[error] += 1
    repeated = sorted(errors.items(), key=lambda item: item[1], reverse=True)[:5]
    if contradicted > supported:
        summary = "The initial thesis is currently more contradicted than supported across matured horizons."
    elif supported > contradicted:
        summary = "The initial thesis is currently supported by more matured horizons than it is contradicted by."
    else:
        summary = "The initial thesis remains mixed or unresolved across matured horizons."
    return {
        "status": "evaluated" if supported or contradicted else "pending",
        "summary": summary,
        "supported_horizons": supported,
        "contradicted_horizons": contradicted,
        "unresolved_horizons": unresolved,
        "repeating_reasoning_errors": [{"error": error, "count": count} for error, count in repeated],
    }


def explanation_quality(signal: SignalSnapshot) -> float:
    length_score = min(45, len(signal.explanation or "") / 8)
    watch_score = min(25, len((signal.watch_points or {}).get("items", [])) * 7)
    breakdown_score = min(30, len(signal.score_breakdown or {}) * 4)
    return round(clamp(length_score + watch_score + breakdown_score), 1)


def data_quality(signal: SignalSnapshot, asset: Asset, prices: pd.DataFrame, news_evidence: dict) -> float:
    history_score = min(35, len(prices) / 12)
    signal_score = min(25, float(signal.confidence_score or 0) * 0.25)
    news_score = min(25, float(news_evidence.get("news_count_30d") or 0) * 3)
    metadata_score = 15 if asset.sector and asset.country and asset.asset_type else 8
    return round(clamp(history_score + signal_score + news_score + metadata_score), 1)


def latest_row_on_or_before(frame: pd.DataFrame, target: date) -> pd.Series | None:
    subset = frame[frame["date"] <= target]
    if subset.empty:
        return None
    return subset.iloc[-1]


def earliest_row_on_or_after(frame: pd.DataFrame, target: date) -> pd.Series | None:
    subset = frame[frame["date"] >= target]
    if subset.empty:
        return None
    return subset.iloc[0]


def realized_volatility(window: pd.DataFrame) -> float | None:
    if window.empty or len(window) < 3:
        return None
    closes = [float(value) for value in window["close"].tolist() if value is not None]
    returns = [((closes[index] / closes[index - 1]) - 1) * 100 for index in range(1, len(closes)) if closes[index - 1]]
    if len(returns) < 2:
        return None
    return round(stdev(returns) * sqrt(252), 3)


def pct(start: float, end: float) -> float:
    if not start:
        return 0.0
    return round(((end / start) - 1) * 100, 3)


def value_from_dict(payload: dict | None, key: str, default: float = 0.0) -> float:
    try:
        return float((payload or {}).get(key, default) or default)
    except (TypeError, ValueError):
        return default


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def as_date(value: datetime | date | None) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.utcnow().date()


def iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def serialize_weight_version(row: ModelWeightVersion | None) -> dict | None:
    if row is None:
        return {"version": "static-code-default", "weights": active_model_weights(None), "created_at": None, "change_reason": "No database recalibration has been activated yet."}
    return {
        "version": row.version,
        "weights": row.weights,
        "previous_weights": row.previous_weights,
        "calibration_metrics": row.calibration_metrics,
        "change_reason": row.change_reason,
        "created_at": iso(row.created_at),
    }


def serialize_evaluation(row: SignalEvaluation) -> dict:
    return {
        "id": row.id,
        "signal_id": row.signal_id,
        "ticker": row.ticker,
        "sector": row.sector,
        "signal_type": row.signal_type,
        "expected_direction": row.expected_direction,
        "time_horizon": row.time_horizon,
        "horizon_days": row.horizon_days,
        "signal_created_at": iso(row.signal_created_at),
        "initial_confidence": row.initial_confidence,
        "initial_sentiment": row.initial_sentiment,
        "initial_momentum": row.initial_momentum,
        "news_evidence": row.news_evidence,
        "price_at_signal": row.price_at_signal,
        "price_after_horizon": row.price_after_horizon,
        "max_drawdown": row.max_drawdown,
        "max_upside": row.max_upside,
        "realized_return": row.realized_return,
        "volatility_after_signal": row.volatility_after_signal,
        "outcome": row.outcome,
        "explanation_quality_score": row.explanation_quality_score,
        "data_quality_score": row.data_quality_score,
        "evaluation_payload": row.evaluation_payload,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def serialize_learning_event(row: LearningEvent) -> dict:
    return {
        "id": row.id,
        "event_type": row.event_type,
        "severity": row.severity,
        "title": row.title,
        "description": row.description,
        "payload": row.payload,
        "created_at": iso(row.created_at),
    }


def serialize_confidence_adjustment(row: ConfidenceAdjustment) -> dict:
    return {
        "id": row.id,
        "ticker": row.ticker,
        "sector": row.sector,
        "signal_type": row.signal_type,
        "base_confidence": row.base_confidence,
        "adjusted_confidence": row.adjusted_confidence,
        "adjustment": row.adjustment,
        "reason": row.reason,
        "evidence": row.evidence,
        "created_at": iso(row.created_at),
    }


def serialize_similarity_case(row: HistoricalSimilarityCase) -> dict:
    return {
        "id": row.id,
        "ticker": row.ticker,
        "reference_signal_id": row.reference_signal_id,
        "case_date": iso(row.case_date),
        "similarity_score": row.similarity_score,
        "features": row.features,
        "outcome_summary": row.outcome_summary,
        "created_at": iso(row.created_at),
    }


def serialize_ticker_profile(row: TickerAccuracyProfile) -> dict:
    return {
        "ticker": row.ticker,
        "evaluated_signals": row.evaluated_signals,
        "correct_rate": row.correct_rate,
        "neutral_rate": row.neutral_rate,
        "average_return": row.average_return,
        "average_drawdown": row.average_drawdown,
        "accuracy_score": row.accuracy_score,
        "profile_payload": row.profile_payload,
        "updated_at": iso(row.updated_at),
    }


def serialize_sector_profile(row: SectorAccuracyProfile) -> dict:
    return {
        "sector": row.sector,
        "evaluated_signals": row.evaluated_signals,
        "correct_rate": row.correct_rate,
        "neutral_rate": row.neutral_rate,
        "average_return": row.average_return,
        "average_drawdown": row.average_drawdown,
        "accuracy_score": row.accuracy_score,
        "profile_payload": row.profile_payload,
        "updated_at": iso(row.updated_at),
    }


def serialize_source_reliability(row: SourceReliabilityScore) -> dict:
    return {
        "source": row.source,
        "article_count": row.article_count,
        "linked_signal_count": row.linked_signal_count,
        "correct_signal_rate": row.correct_signal_rate,
        "false_positive_rate": row.false_positive_rate,
        "reliability_score": row.reliability_score,
        "evidence": row.evidence,
        "updated_at": iso(row.updated_at),
    }
