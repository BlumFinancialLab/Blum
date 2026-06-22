from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean
from typing import Any

from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from app.models import (
    BlumKnowledgeRecord,
    BlumThesisOutcome,
    ConfidenceCalibrationBucket,
    LearningEvent,
    MetaLearningEvent,
    ModelReliabilityMatrix,
    ThesisLifecycleEvent,
)


THESIS_STATUSES = ("ACTIVE", "STRENGTHENING", "WEAKENING", "INVALIDATED", "COMPLETED")
MATURE_OUTCOMES = ("correct", "wrong", "neutral")
ENGINE_NAMES = (
    "thesis_engine",
    "technical_engine",
    "sentiment_engine",
    "narrative_engine",
    "fundamental_engine",
    "regime_engine",
    "self_critique_engine",
    "historical_memory_engine",
)


def run_reasoning_core_cycle(db: Session, limit: int = 250, commit: bool = True) -> dict:
    """Upgrade stored Blum theses into measured, self-correcting reasoning memory."""

    records = db.scalars(select(BlumKnowledgeRecord).order_by(desc(BlumKnowledgeRecord.created_at)).limit(limit)).all()
    lifecycle = update_thesis_lifecycle(db, records)
    reliability = update_model_reliability_matrix(db, limit=max(limit * 5, 500))
    calibration = update_confidence_calibration(db, limit=max(limit * 5, 500))
    meta = generate_meta_learning_events(db)
    result = {
        "status": "ok",
        "records_seen": len(records),
        "thesis_lifecycle": lifecycle,
        "model_reliability": reliability,
        "confidence_calibration": calibration,
        "meta_learning": meta,
        "governance": [
            "The reasoning core adjusts measured confidence and weight recommendations, not source code.",
            "A thesis is preserved with its evidence, contradictions, context, lifecycle and outcome.",
            "Calibration measures whether stated confidence matched historical thesis outcomes.",
        ],
    }
    db.add(
        LearningEvent(
            event_type="blum_reasoning_core_cycle",
            severity="Info",
            title="Blum Reasoning Core cycle completed",
            description="Updated thesis lifecycle, model reliability, confidence calibration and meta-learning events.",
            payload=result,
        )
    )
    if commit:
        db.commit()
    else:
        db.flush()
    return result


def update_thesis_lifecycle(db: Session, records: list[BlumKnowledgeRecord]) -> dict:
    changed = 0
    unchanged = 0
    status_counts: dict[str, int] = {status: 0 for status in THESIS_STATUSES}
    for record in records:
        outcomes = db.scalars(
            select(BlumThesisOutcome)
            .where(BlumThesisOutcome.knowledge_record_id == record.id)
            .order_by(BlumThesisOutcome.horizon_days)
        ).all()
        previous_payload = (record.blum_reasoning or {}).get("thesis_lifecycle") or {}
        previous_status = previous_payload.get("status") or "NEW"
        lifecycle = classify_lifecycle(record, outcomes)
        status_counts[lifecycle["status"]] = status_counts.get(lifecycle["status"], 0) + 1
        if previous_status != lifecycle["status"] or not previous_payload:
            db.add(
                ThesisLifecycleEvent(
                    knowledge_record_id=record.id,
                    ticker=record.ticker,
                    previous_status=previous_status,
                    new_status=lifecycle["status"],
                    status_reason=lifecycle["reason"],
                    confidence=float(record.confidence or 0.0),
                    conviction_score=float(record.conviction_score or 0.0),
                    outcome_summary=lifecycle["outcome_summary"],
                    evidence_delta=lifecycle["evidence_delta"],
                )
            )
            changed += 1
        else:
            unchanged += 1
        record.blum_reasoning = {
            **(record.blum_reasoning or {}),
            "thesis_lifecycle": lifecycle,
        }
        record.updated_at = datetime.utcnow()
    return {"updated_records": changed, "unchanged_records": unchanged, "status_counts": status_counts}


def classify_lifecycle(record: BlumKnowledgeRecord, outcomes: list[BlumThesisOutcome]) -> dict:
    mature = [row for row in outcomes if row.outcome in MATURE_OUTCOMES]
    correct = sum(1 for row in mature if row.outcome == "correct")
    wrong = sum(1 for row in mature if row.outcome == "wrong")
    neutral = sum(1 for row in mature if row.outcome == "neutral")
    realized = [float(row.realized_return) for row in mature if row.realized_return is not None]
    drawdowns = [float(row.max_drawdown) for row in mature if row.max_drawdown is not None]
    strongest_horizon = max((row.horizon_days for row in mature), default=0)
    if not mature:
        status = "ACTIVE"
        reason = "No matured outcome has enough stored price evidence yet; thesis remains active but unproven."
    elif wrong >= 2 and wrong > correct:
        status = "INVALIDATED"
        reason = "Multiple matured horizons contradicted the thesis; the original reasoning should be reviewed."
    elif wrong > correct:
        status = "WEAKENING"
        reason = "Contradicting outcomes exceed confirming outcomes, but invalidation is not yet conclusive."
    elif correct > wrong and strongest_horizon >= 30:
        status = "COMPLETED"
        reason = "The thesis reached a long enough evaluation horizon with more confirming than contradicting outcomes."
    elif correct > wrong:
        status = "STRENGTHENING"
        reason = "Early matured outcomes support the thesis; confidence can improve only with continued evidence."
    else:
        status = "ACTIVE"
        reason = "Matured outcomes are mixed or neutral; thesis stays active with conservative confidence."
    outcome_summary = {
        "matured_horizons": len(mature),
        "correct": correct,
        "wrong": wrong,
        "neutral": neutral,
        "inconclusive": sum(1 for row in outcomes if row.outcome == "inconclusive"),
        "average_realized_return": round(mean(realized), 4) if realized else None,
        "worst_drawdown": round(min(drawdowns), 4) if drawdowns else None,
        "strongest_horizon_days": strongest_horizon,
    }
    evidence_delta = {
        "confidence_at_creation": round(float(record.confidence or 0.0), 2),
        "conviction_at_creation": round(float(record.conviction_score or 0.0), 2),
        "success_balance": correct - wrong,
        "calibration_note": calibration_note(record, mature),
    }
    return {
        "status": status,
        "allowed_statuses": list(THESIS_STATUSES),
        "reason": reason,
        "outcome_summary": outcome_summary,
        "evidence_delta": evidence_delta,
        "updated_at": datetime.utcnow().isoformat(),
        "governance": "Lifecycle status measures thesis evidence over time; it is not a trade instruction.",
    }


def update_model_reliability_matrix(db: Session, limit: int = 1000) -> dict:
    outcomes = db.scalars(
        select(BlumThesisOutcome)
        .where(BlumThesisOutcome.outcome.in_(MATURE_OUTCOMES))
        .order_by(desc(BlumThesisOutcome.updated_at))
        .limit(limit)
    ).all()
    groups: dict[tuple[str, str, str, str], dict[str, Any]] = defaultdict(lambda: {
        "correct": 0,
        "wrong": 0,
        "neutral": 0,
        "inconclusive": 0,
        "confidence": [],
        "quality": [],
        "tickers": set(),
        "evidence_types": set(),
    })
    for outcome in outcomes:
        record = outcome.knowledge_record
        if record is None:
            continue
        timeframe = f"{outcome.horizon_days}D"
        for contribution in engine_contributions(record):
            key = (contribution["engine_name"], record.sector or "Unknown", record.market_regime or "Unknown", timeframe)
            group = groups[key]
            group[outcome.outcome] += 1
            group["confidence"].append(float(record.confidence or 0.0))
            group["quality"].append(quality_score(record))
            group["tickers"].add(record.ticker)
            group["evidence_types"].add(contribution["evidence_type"])
    rows_updated = 0
    for key, data in groups.items():
        engine_name, sector, regime, timeframe = key
        row = db.scalar(
            select(ModelReliabilityMatrix).where(
                and_(
                    ModelReliabilityMatrix.engine_name == engine_name,
                    ModelReliabilityMatrix.sector == sector,
                    ModelReliabilityMatrix.market_regime == regime,
                    ModelReliabilityMatrix.timeframe == timeframe,
                )
            )
        )
        if row is None:
            row = ModelReliabilityMatrix(engine_name=engine_name, sector=sector, market_regime=regime, timeframe=timeframe)
            db.add(row)
        apply_reliability_row(row, data)
        rows_updated += 1
    return {"outcomes_seen": len(outcomes), "rows_updated": rows_updated, "engines": list(ENGINE_NAMES)}


def update_confidence_calibration(db: Session, limit: int = 1000) -> dict:
    outcomes = db.scalars(
        select(BlumThesisOutcome)
        .where(BlumThesisOutcome.outcome.in_(MATURE_OUTCOMES))
        .order_by(desc(BlumThesisOutcome.updated_at))
        .limit(limit)
    ).all()
    buckets: dict[str, dict[str, Any]] = defaultdict(lambda: {"scores": [], "confidence": [], "tickers": set(), "outcomes": defaultdict(int)})
    for outcome in outcomes:
        record = outcome.knowledge_record
        if record is None:
            continue
        confidence = clamp(float(record.confidence or 0.0))
        label, min_conf, max_conf = confidence_bucket(confidence)
        buckets[label]["scores"].append(outcome_success_value(outcome.outcome))
        buckets[label]["confidence"].append(confidence)
        buckets[label]["tickers"].add(record.ticker)
        buckets[label]["outcomes"][outcome.outcome] += 1
        buckets[label]["range"] = (min_conf, max_conf)
    rows_updated = 0
    for label, data in buckets.items():
        min_conf, max_conf = data["range"]
        row = db.scalar(select(ConfidenceCalibrationBucket).where(ConfidenceCalibrationBucket.bucket_label == label))
        if row is None:
            row = ConfidenceCalibrationBucket(bucket_label=label, min_confidence=min_conf, max_confidence=max_conf)
            db.add(row)
        success_rate = mean(data["scores"]) * 100 if data["scores"] else 0.0
        avg_confidence = mean(data["confidence"]) if data["confidence"] else 0.0
        error = success_rate - avg_confidence
        row.min_confidence = min_conf
        row.max_confidence = max_conf
        row.sample_count = len(data["scores"])
        row.average_confidence = round(avg_confidence, 2)
        row.empirical_success_rate = round(success_rate, 2)
        row.calibration_error = round(error, 2)
        row.suggested_adjustment = round(error * 0.35, 2)
        row.evidence = {
            "outcomes": dict(data["outcomes"]),
            "sample_tickers": sorted(data["tickers"])[:20],
            "interpretation": "Positive error means confidence has been understated; negative error means overconfidence risk.",
        }
        row.updated_at = datetime.utcnow()
        rows_updated += 1
    return {"outcomes_seen": len(outcomes), "buckets_updated": rows_updated}


def generate_meta_learning_events(db: Session) -> dict:
    created = 0
    reliability_rows = db.scalars(select(ModelReliabilityMatrix).where(ModelReliabilityMatrix.sample_count >= 5)).all()
    for row in reliability_rows:
        if row.reliability_score < 45:
            created += add_meta_event_once(
                db,
                event_type="engine_underperformance",
                engine_name=row.engine_name,
                root_cause=f"low_reliability:{row.engine_name}:{row.market_regime}:{row.timeframe}",
                severity="Warning",
                lesson=f"{row.engine_name} has weak reliability in {row.market_regime}/{row.timeframe}; future theses should reduce its weight unless independent evidence confirms it.",
                proposed_change={"weight_adjustment": row.weight_adjustment, "context": {"sector": row.sector, "market_regime": row.market_regime, "timeframe": row.timeframe}},
                trigger_payload=serialize_reliability(row),
            )
        elif row.reliability_score >= 68:
            created += add_meta_event_once(
                db,
                event_type="engine_strength",
                engine_name=row.engine_name,
                root_cause=f"high_reliability:{row.engine_name}:{row.market_regime}:{row.timeframe}",
                severity="Info",
                lesson=f"{row.engine_name} has shown useful reliability in {row.market_regime}/{row.timeframe}; it can receive modestly higher weight when data quality is comparable.",
                proposed_change={"weight_adjustment": row.weight_adjustment, "context": {"sector": row.sector, "market_regime": row.market_regime, "timeframe": row.timeframe}},
                trigger_payload=serialize_reliability(row),
            )
    calibration_rows = db.scalars(select(ConfidenceCalibrationBucket).where(ConfidenceCalibrationBucket.sample_count >= 5)).all()
    for row in calibration_rows:
        if row.calibration_error <= -12:
            created += add_meta_event_once(
                db,
                event_type="confidence_overstatement",
                engine_name="confidence_calibration",
                root_cause=f"overconfidence:{row.bucket_label}",
                severity="Warning",
                lesson=f"Confidence bucket {row.bucket_label} is overstated by {abs(row.calibration_error):.1f} points; future thesis confidence should be compressed in this range.",
                proposed_change={"confidence_adjustment_points": row.suggested_adjustment, "bucket": row.bucket_label},
                trigger_payload=serialize_calibration(row),
            )
        elif row.calibration_error >= 12:
            created += add_meta_event_once(
                db,
                event_type="confidence_understatement",
                engine_name="confidence_calibration",
                root_cause=f"underconfidence:{row.bucket_label}",
                severity="Info",
                lesson=f"Confidence bucket {row.bucket_label} has been conservative by {row.calibration_error:.1f} points; BLUM can slightly trust similar evidence when sample quality is stable.",
                proposed_change={"confidence_adjustment_points": row.suggested_adjustment, "bucket": row.bucket_label},
                trigger_payload=serialize_calibration(row),
            )
    latest_failures = db.scalars(
        select(ThesisLifecycleEvent)
        .where(ThesisLifecycleEvent.new_status.in_(("WEAKENING", "INVALIDATED")))
        .order_by(desc(ThesisLifecycleEvent.created_at))
        .limit(60)
    ).all()
    for event in latest_failures:
        root = lifecycle_root_cause(event)
        created += add_meta_event_once(
            db,
            event_type="thesis_failure_pattern",
            engine_name="thesis_engine",
            ticker=event.ticker,
            root_cause=root,
            severity="Warning" if event.new_status == "INVALIDATED" else "Info",
            lesson=f"{event.ticker} thesis moved to {event.new_status}: {event.status_reason}",
            proposed_change={"review": "Inspect whether technical, sentiment, regime or risk evidence was overweighted.", "thesis_status": event.new_status},
            trigger_payload={
                "knowledge_record_id": event.knowledge_record_id,
                "outcome_summary": event.outcome_summary,
                "evidence_delta": event.evidence_delta,
            },
        )
    return {"events_created": created, "dedupe_window_hours": 24}


def reasoning_core_status(db: Session) -> dict:
    return {
        "status": "active",
        "objective": "Turn Blum analyses into persistent theses with critique, lifecycle, calibration and meta-learning.",
        "counts": {
            "knowledge_records": scalar_count(db, BlumKnowledgeRecord.id),
            "thesis_lifecycle_events": scalar_count(db, ThesisLifecycleEvent.id),
            "model_reliability_rows": scalar_count(db, ModelReliabilityMatrix.id),
            "confidence_buckets": scalar_count(db, ConfidenceCalibrationBucket.id),
            "meta_learning_events": scalar_count(db, MetaLearningEvent.id),
        },
        "latest_lifecycle": thesis_lifecycle_records(db, limit=8),
        "weakest_engines": model_reliability_overview(db, limit=5, order="asc")["rows"],
        "calibration": confidence_calibration_overview(db)["summary"],
        "governance": "BLUM learns reasoning quality and calibration; it does not guarantee market outcomes or execute trades.",
    }


def thesis_lifecycle_records(
    db: Session,
    ticker: str | None = None,
    status: str | None = None,
    limit: int = 80,
) -> list[dict]:
    query = select(BlumKnowledgeRecord).order_by(desc(BlumKnowledgeRecord.updated_at)).limit(limit)
    if ticker:
        query = query.where(BlumKnowledgeRecord.ticker == ticker.upper())
    records = db.scalars(query).all()
    rows = []
    for record in records:
        lifecycle = (record.blum_reasoning or {}).get("thesis_lifecycle") or {}
        if status and lifecycle.get("status") != status.upper():
            continue
        rows.append(
            {
                "knowledge_record_id": record.id,
                "ticker": record.ticker,
                "sector": record.sector,
                "market_regime": record.market_regime,
                "confidence": record.confidence,
                "conviction_score": record.conviction_score,
                "lifecycle": lifecycle,
                "executive_thesis": (record.blum_reasoning or {}).get("executive_thesis"),
                "created_at": iso(record.created_at),
                "updated_at": iso(record.updated_at),
            }
        )
    return rows[:limit]


def model_reliability_overview(
    db: Session,
    engine_name: str | None = None,
    limit: int = 80,
    order: str = "desc",
) -> dict:
    ordering = ModelReliabilityMatrix.reliability_score.asc() if order == "asc" else desc(ModelReliabilityMatrix.reliability_score)
    query = select(ModelReliabilityMatrix).order_by(ordering, desc(ModelReliabilityMatrix.updated_at)).limit(limit)
    if engine_name:
        query = query.where(ModelReliabilityMatrix.engine_name == engine_name)
    rows = db.scalars(query).all()
    return {
        "rows": [serialize_reliability(row) for row in rows],
        "interpretation": "Reliability is contextual by engine, sector, regime and horizon. It is a weight signal, not a forecast guarantee.",
    }


def confidence_calibration_overview(db: Session) -> dict:
    rows = db.scalars(select(ConfidenceCalibrationBucket).order_by(ConfidenceCalibrationBucket.min_confidence)).all()
    weighted_errors = [abs(row.calibration_error) * row.sample_count for row in rows]
    samples = sum(row.sample_count for row in rows)
    return {
        "summary": {
            "bucket_count": len(rows),
            "sample_count": samples,
            "mean_absolute_calibration_error": round(sum(weighted_errors) / samples, 2) if samples else None,
            "status": "measured" if samples >= 20 else "collecting_samples",
        },
        "buckets": [serialize_calibration(row) for row in rows],
    }


def meta_learning_event_list(db: Session, limit: int = 80, status: str | None = None) -> list[dict]:
    query = select(MetaLearningEvent).order_by(desc(MetaLearningEvent.created_at)).limit(limit)
    if status:
        query = query.where(MetaLearningEvent.status == status)
    return [serialize_meta_event(row) for row in db.scalars(query).all()]


def engine_contributions(record: BlumKnowledgeRecord) -> list[dict]:
    reasoning = record.blum_reasoning or {}
    asset = record.asset_context or {}
    technical = asset.get("technical_indicators") or {}
    price_action = asset.get("price_action") or {}
    sentiment = asset.get("sentiment_indicators") or {}
    news = asset.get("news_indicators") or {}
    narrative = reasoning.get("narrative_analysis") or {}
    historical = reasoning.get("historical_similarity") or {}
    contributions = [{"engine_name": "thesis_engine", "evidence_type": "complete_thesis"}]
    if meaningful_dict(technical) or meaningful_dict(price_action):
        contributions.append({"engine_name": "technical_engine", "evidence_type": "price_volume_indicators"})
    if meaningful_dict(sentiment) or meaningful_dict(news):
        contributions.append({"engine_name": "sentiment_engine", "evidence_type": "news_sentiment"})
    if meaningful_dict(narrative):
        contributions.append({"engine_name": "narrative_engine", "evidence_type": "narrative_lifecycle"})
    if meaningful_dict(narrative.get("fundamentals") or asset.get("fundamentals") or {}):
        contributions.append({"engine_name": "fundamental_engine", "evidence_type": "fundamental_context"})
    if record.market_regime and record.market_regime != "Unknown":
        contributions.append({"engine_name": "regime_engine", "evidence_type": "market_regime_context"})
    if meaningful_dict(record.self_critique or {}):
        contributions.append({"engine_name": "self_critique_engine", "evidence_type": "analyst_skeptic_judge"})
    if meaningful_dict(historical):
        contributions.append({"engine_name": "historical_memory_engine", "evidence_type": "similar_cases"})
    return contributions


def apply_reliability_row(row: ModelReliabilityMatrix, data: dict[str, Any]) -> None:
    correct = int(data["correct"])
    wrong = int(data["wrong"])
    neutral = int(data["neutral"])
    inconclusive = int(data["inconclusive"])
    sample_count = correct + wrong + neutral + inconclusive
    mature = max(1, correct + wrong + neutral)
    empirical = (correct + neutral * 0.5) / mature
    prior_samples = 8
    reliability = ((empirical * mature) + (0.50 * prior_samples)) / (mature + prior_samples) * 100
    avg_quality = mean(data["quality"]) if data["quality"] else 50.0
    avg_confidence = mean(data["confidence"]) if data["confidence"] else 50.0
    reliability = clamp(reliability + (avg_quality - 50) * 0.08 - inconclusive * 0.7)
    row.sample_count = sample_count
    row.correct_count = correct
    row.wrong_count = wrong
    row.neutral_count = neutral
    row.inconclusive_count = inconclusive
    row.reliability_score = round(reliability, 2)
    row.weight_adjustment = round(max(-0.08, min(0.08, (reliability - 50) / 500)), 4)
    row.calibration_error = round(reliability - avg_confidence, 2)
    row.evidence = {
        "average_confidence": round(avg_confidence, 2),
        "average_quality_score": round(avg_quality, 2),
        "sample_tickers": sorted(data["tickers"])[:20],
        "evidence_types": sorted(data["evidence_types"]),
        "rule": "Bayesian reliability with neutral outcomes scored at 0.5 and quality-adjusted conservatively.",
    }
    row.updated_at = datetime.utcnow()


def add_meta_event_once(
    db: Session,
    *,
    event_type: str,
    engine_name: str | None,
    root_cause: str,
    lesson: str,
    proposed_change: dict,
    trigger_payload: dict,
    severity: str = "Info",
    ticker: str | None = None,
) -> int:
    cutoff = datetime.utcnow() - timedelta(hours=24)
    existing = db.scalar(
        select(MetaLearningEvent).where(
            and_(
                MetaLearningEvent.event_type == event_type,
                MetaLearningEvent.engine_name == engine_name,
                MetaLearningEvent.root_cause == root_cause,
                MetaLearningEvent.ticker == ticker,
                MetaLearningEvent.created_at >= cutoff,
            )
        )
    )
    if existing is not None:
        return 0
    db.add(
        MetaLearningEvent(
            event_type=event_type,
            engine_name=engine_name,
            ticker=ticker,
            severity=severity,
            lesson=lesson,
            root_cause=root_cause,
            proposed_change=proposed_change,
            trigger_payload=trigger_payload,
            status="open",
        )
    )
    return 1


def calibration_note(record: BlumKnowledgeRecord, mature: list[BlumThesisOutcome]) -> str:
    if not mature:
        return "Pending: no matured horizon has been measured."
    success_rate = mean(outcome_success_value(row.outcome) for row in mature) * 100
    confidence = float(record.confidence or 0.0)
    gap = success_rate - confidence
    if gap <= -15:
        return "Initial confidence appears too high versus observed outcomes."
    if gap >= 15:
        return "Initial confidence appears conservative versus observed outcomes."
    return "Initial confidence is broadly aligned with observed thesis outcomes."


def lifecycle_root_cause(event: ThesisLifecycleEvent) -> str:
    summary = event.outcome_summary or {}
    delta = event.evidence_delta or {}
    if summary.get("wrong", 0) >= 2:
        return "repeated_wrong_horizons"
    if (summary.get("worst_drawdown") or 0) <= -8:
        return "drawdown_exceeded_thesis_tolerance"
    if "too high" in str(delta.get("calibration_note", "")).lower():
        return "overconfidence"
    return "mixed_evidence_decay"


def confidence_bucket(confidence: float) -> tuple[str, float, float]:
    lower = int(confidence // 10) * 10
    upper = 100 if lower >= 90 else lower + 10
    if confidence >= 100:
        lower = 90
        upper = 100
    return f"{lower}-{upper}", float(lower), float(upper)


def outcome_success_value(outcome: str) -> float:
    if outcome == "correct":
        return 1.0
    if outcome == "neutral":
        return 0.5
    return 0.0


def quality_score(record: BlumKnowledgeRecord) -> float:
    return float((record.quality_scores or {}).get("overall_score", 50.0) or 50.0)


def meaningful_dict(value: Any) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    return any(item not in (None, "", [], {}, 0, 0.0) for item in value.values())


def serialize_reliability(row: ModelReliabilityMatrix) -> dict:
    return {
        "id": row.id,
        "engine_name": row.engine_name,
        "sector": row.sector,
        "market_regime": row.market_regime,
        "timeframe": row.timeframe,
        "sample_count": row.sample_count,
        "correct_count": row.correct_count,
        "wrong_count": row.wrong_count,
        "neutral_count": row.neutral_count,
        "inconclusive_count": row.inconclusive_count,
        "reliability_score": row.reliability_score,
        "weight_adjustment": row.weight_adjustment,
        "calibration_error": row.calibration_error,
        "evidence": row.evidence,
        "updated_at": iso(row.updated_at),
    }


def serialize_calibration(row: ConfidenceCalibrationBucket) -> dict:
    return {
        "id": row.id,
        "bucket_label": row.bucket_label,
        "min_confidence": row.min_confidence,
        "max_confidence": row.max_confidence,
        "sample_count": row.sample_count,
        "average_confidence": row.average_confidence,
        "empirical_success_rate": row.empirical_success_rate,
        "calibration_error": row.calibration_error,
        "suggested_adjustment": row.suggested_adjustment,
        "evidence": row.evidence,
        "updated_at": iso(row.updated_at),
    }


def serialize_meta_event(row: MetaLearningEvent) -> dict:
    return {
        "id": row.id,
        "event_type": row.event_type,
        "engine_name": row.engine_name,
        "ticker": row.ticker,
        "severity": row.severity,
        "lesson": row.lesson,
        "root_cause": row.root_cause,
        "proposed_change": row.proposed_change,
        "trigger_payload": row.trigger_payload,
        "status": row.status,
        "created_at": iso(row.created_at),
    }


def scalar_count(db: Session, column) -> int:
    return int(db.scalar(select(func.count(column))) or 0)


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
