from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
import json
import math
import os
from statistics import mean, pstdev
from typing import Any

from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from app.models import (
    Asset,
    BenchmarkRelativeOutcome,
    BlumDatasetExport,
    BlumKnowledgeRecord,
    BlumThesisOutcome,
    BlumTrainingExample,
    CompetingThesis,
    EngineVote,
    EnsembleWeightVersion,
    LearningEvent,
    ModelReliabilityByRegime,
    PriceHistory,
    ThesisCompetition,
    ThesisConvictionHistory,
    ThesisSurvivalMetric,
    TrainingExampleQualityScore,
)
from app.services.reasoning_core import engine_contributions, quality_score, run_reasoning_core_cycle


MATURE_OUTCOMES = ("correct", "wrong", "neutral")
DEFAULT_BENCHMARK = "SPY"
SECTOR_BENCHMARKS = {
    "Technology": "XLK",
    "Information Technology": "XLK",
    "Semiconductors": "SMH",
    "Healthcare": "XLV",
    "Health Care": "XLV",
    "Energy": "XLE",
    "Financials": "XLF",
    "Financial Services": "XLF",
    "Industrials": "XLI",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Utilities": "XLU",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    if value is None or math.isnan(float(value)):
        return low
    return max(low, min(high, float(value)))


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def pct_return(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start == 0:
        return None
    return (end - start) / start


def as_date(value: datetime | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


def listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if item not in (None, "", [], {})]
    if isinstance(value, tuple):
        return [item for item in value if item not in (None, "", [], {})]
    if isinstance(value, dict):
        return [value] if value else []
    return [value] if str(value).strip() else []


def json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    return value


def record_thesis_type(record: BlumKnowledgeRecord) -> str:
    reasoning = record.blum_reasoning or {}
    return (
        reasoning.get("classification")
        or reasoning.get("signal_type")
        or reasoning.get("thesis_type")
        or record.source_type
        or "research_thesis"
    )


def record_direction(record: BlumKnowledgeRecord) -> str:
    horizons = record.prediction_horizons or {}
    reasoning = record.blum_reasoning or {}
    direction = (
        horizons.get("expected_direction")
        or reasoning.get("expected_direction")
        or reasoning.get("direction")
        or ""
    )
    text = str(direction or record_thesis_type(record)).lower()
    if any(token in text for token in ("bear", "down", "avoid", "risk", "short", "weak")):
        return "bearish"
    if any(token in text for token in ("bull", "up", "strong", "breakout", "watch", "positive", "long")):
        return "bullish"
    return "neutral"


def record_horizon(record: BlumKnowledgeRecord) -> str:
    horizons = record.prediction_horizons or {}
    if isinstance(horizons, dict):
        for key in ("horizon", "time_horizon", "expected_horizon"):
            if horizons.get(key):
                return str(horizons[key])
    return "multi"


def setup_type(record: BlumKnowledgeRecord) -> str:
    reasoning = record.blum_reasoning or {}
    asset_context = record.asset_context or {}
    text = " ".join(
        str(item)
        for item in (
            reasoning.get("final_view"),
            reasoning.get("executive_thesis"),
            reasoning.get("technical_summary"),
            asset_context.get("setup_type"),
            record_thesis_type(record),
        )
        if item
    ).lower()
    if "breakout" in text:
        return "momentum_breakout"
    if "pullback" in text:
        return "pullback_to_trend"
    if "rotation" in text:
        return "sector_rotation_entry"
    if "reversal" in text:
        return "reversal_from_support"
    if "sentiment divergence" in text or "divergence" in text:
        return "sentiment_divergence"
    if "avoid" in text or "too risky" in text:
        return "avoid_no_edge"
    return "research_thesis"


def evidence_bundle(record: BlumKnowledgeRecord) -> tuple[list[Any], list[Any], list[Any]]:
    reasoning = record.blum_reasoning or {}
    critique = record.self_critique or {}
    supporting = listify(reasoning.get("supporting_evidence"))
    contradicting = listify(reasoning.get("contradicting_evidence"))
    risks = listify(reasoning.get("risks"))
    if critique:
        supporting.extend(listify((critique.get("analyst_view") or {}).get("key_points")))
        contradicting.extend(listify((critique.get("skeptic_view") or {}).get("key_points")))
        risks.extend(listify((critique.get("final_view") or {}).get("risks")))
    return supporting[:12], contradicting[:12], risks[:12]


def price_rows(db: Session, asset_id: int | None, start: date | None = None, end: date | None = None) -> list[PriceHistory]:
    if asset_id is None:
        return []
    query = select(PriceHistory).where(PriceHistory.asset_id == asset_id).order_by(PriceHistory.date)
    if start is not None:
        query = query.where(PriceHistory.date >= start)
    if end is not None:
        query = query.where(PriceHistory.date <= end)
    return list(db.scalars(query).all())


def price_on_or_after(db: Session, asset_id: int | None, target: date | None) -> PriceHistory | None:
    if asset_id is None or target is None:
        return None
    return db.scalar(
        select(PriceHistory)
        .where(and_(PriceHistory.asset_id == asset_id, PriceHistory.date >= target))
        .order_by(PriceHistory.date)
        .limit(1)
    )


def latest_price(db: Session, asset_id: int | None) -> PriceHistory | None:
    if asset_id is None:
        return None
    return db.scalar(
        select(PriceHistory)
        .where(PriceHistory.asset_id == asset_id)
        .order_by(desc(PriceHistory.date))
        .limit(1)
    )


def max_drawdown_from_rows(rows: list[PriceHistory]) -> float | None:
    if not rows:
        return None
    peak = rows[0].close
    worst = 0.0
    for row in rows:
        peak = max(peak, row.close)
        if peak:
            worst = min(worst, (row.close - peak) / peak)
    return worst


def max_upside_from_rows(rows: list[PriceHistory]) -> float | None:
    if not rows:
        return None
    start = rows[0].close
    if not start:
        return None
    return max((row.close - start) / start for row in rows)


def volatility_from_rows(rows: list[PriceHistory]) -> float | None:
    if len(rows) < 3:
        return None
    returns: list[float] = []
    previous = rows[0].close
    for row in rows[1:]:
        if previous:
            returns.append((row.close - previous) / previous)
        previous = row.close
    if not returns:
        return None
    return pstdev(returns) * math.sqrt(252)


def benchmark_ticker_for(record: BlumKnowledgeRecord) -> str:
    return SECTOR_BENCHMARKS.get(record.sector or "", DEFAULT_BENCHMARK)


def benchmark_asset(db: Session, record: BlumKnowledgeRecord) -> Asset | None:
    preferred = benchmark_ticker_for(record)
    asset = db.scalar(select(Asset).where(Asset.ticker == preferred).limit(1))
    if asset is None and preferred != DEFAULT_BENCHMARK:
        asset = db.scalar(select(Asset).where(Asset.ticker == DEFAULT_BENCHMARK).limit(1))
    return asset


def latest_benchmark_outcome(db: Session, object_type: str, object_id: int) -> BenchmarkRelativeOutcome | None:
    return db.scalar(
        select(BenchmarkRelativeOutcome)
        .where(and_(BenchmarkRelativeOutcome.object_type == object_type, BenchmarkRelativeOutcome.object_id == object_id))
        .order_by(desc(BenchmarkRelativeOutcome.updated_at))
        .limit(1)
    )


def record_payload(row: BlumKnowledgeRecord) -> dict:
    return {
        "id": row.id,
        "ticker": row.ticker,
        "sector": row.sector,
        "industry": row.industry,
        "thesis_type": record_thesis_type(row),
        "direction": record_direction(row),
        "horizon": record_horizon(row),
        "confidence": row.confidence,
        "conviction_score": row.conviction_score,
        "market_regime": row.market_regime,
        "volatility_regime": row.volatility_regime,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "executive_thesis": (row.blum_reasoning or {}).get("executive_thesis", ""),
    }


def benchmark_excess(asset_return: float | None, benchmark_return: float | None) -> float | None:
    if asset_return is None or benchmark_return is None:
        return None
    return asset_return - benchmark_return


def confidence_delta_from_evidence(strengthening_score: float, decay_score: float) -> float:
    raw_delta = (strengthening_score - decay_score) / 18.0
    raw_delta = max(-8.0, min(6.0, raw_delta))
    if raw_delta > 0 and strengthening_score < 55:
        return 0.0
    return raw_delta


def training_value_score(scores: dict[str, float]) -> float:
    weights = {
        "reasoning_quality_score": 0.20,
        "outcome_clarity_score": 0.15,
        "data_quality_score": 0.15,
        "contradiction_handling_score": 0.15,
        "confidence_calibration_score": 0.10,
        "regime_context_score": 0.10,
        "benchmark_relevance_score": 0.10,
        "reproducibility_score": 0.05,
    }
    return round(sum(clamp(scores.get(key, 0.0)) * weight for key, weight in weights.items()), 2)


def ensemble_disagreement_penalty(vote_weights: dict[str, float]) -> float:
    total = sum(max(0.0, value) for value in vote_weights.values())
    if total <= 0:
        return 0.0
    leading = max(vote_weights.values())
    return round(clamp((1 - leading / total) * 100), 2)


class BenchmarkRelativeEvaluator:
    def evaluate(
        self,
        db: Session,
        *,
        object_type: str = "blum_thesis",
        object_id: int | None = None,
        ticker: str | None = None,
        limit: int = 250,
        commit: bool = True,
    ) -> dict:
        if object_type != "blum_thesis":
            return {"status": "unsupported", "object_type": object_type, "message": "Only stored Blum theses are supported in this release."}
        query = select(BlumKnowledgeRecord).order_by(desc(BlumKnowledgeRecord.created_at)).limit(limit)
        if object_id is not None:
            query = query.where(BlumKnowledgeRecord.id == object_id)
        if ticker:
            query = query.where(BlumKnowledgeRecord.ticker == ticker.upper())
        records = list(db.scalars(query).all())
        updated = 0
        insufficient = 0
        for record in records:
            outcome = self.evaluate_record(db, record)
            updated += 1 if outcome.asset_return is not None and outcome.benchmark_return is not None else 0
            insufficient += 1 if outcome.asset_return is None or outcome.benchmark_return is None else 0
        if commit:
            db.commit()
        else:
            db.flush()
        return {
            "status": "ok",
            "records_seen": len(records),
            "benchmarks_updated": updated,
            "insufficient_data": insufficient,
            "rule": "Benchmark comparison uses only stored price rows between thesis creation and latest available matching date.",
        }

    def evaluate_record(self, db: Session, record: BlumKnowledgeRecord) -> BenchmarkRelativeOutcome:
        benchmark = benchmark_asset(db, record)
        start = as_date(record.created_at)
        asset_start = price_on_or_after(db, record.asset_id, start)
        asset_end = latest_price(db, record.asset_id)
        benchmark_start = price_on_or_after(db, benchmark.id if benchmark else None, start)
        benchmark_end = latest_price(db, benchmark.id if benchmark else None)
        end_candidates = [row.date for row in (asset_end, benchmark_end) if row is not None]
        end = min(end_candidates) if end_candidates else None
        if end is not None:
            asset_end = db.scalar(
                select(PriceHistory)
                .where(and_(PriceHistory.asset_id == record.asset_id, PriceHistory.date <= end))
                .order_by(desc(PriceHistory.date))
                .limit(1)
            )
            benchmark_asset_id = benchmark.id if benchmark else -1
            benchmark_end = db.scalar(
                select(PriceHistory)
                .where(and_(PriceHistory.asset_id == benchmark_asset_id, PriceHistory.date <= end))
                .order_by(desc(PriceHistory.date))
                .limit(1)
            )
        asset_return = pct_return(asset_start.close if asset_start else None, asset_end.close if asset_end else None)
        benchmark_return = pct_return(benchmark_start.close if benchmark_start else None, benchmark_end.close if benchmark_end else None)
        rows_asset = price_rows(db, record.asset_id, start, end)
        rows_benchmark = price_rows(db, benchmark.id if benchmark else None, start, end)
        excess = benchmark_excess(asset_return, benchmark_return)
        row = db.scalar(
            select(BenchmarkRelativeOutcome).where(
                and_(
                    BenchmarkRelativeOutcome.object_type == "blum_thesis",
                    BenchmarkRelativeOutcome.object_id == record.id,
                    BenchmarkRelativeOutcome.benchmark_ticker == (benchmark.ticker if benchmark else DEFAULT_BENCHMARK),
                )
            )
        )
        if row is None:
            row = BenchmarkRelativeOutcome(
                object_type="blum_thesis",
                object_id=record.id,
                ticker=record.ticker,
                benchmark_ticker=benchmark.ticker if benchmark else DEFAULT_BENCHMARK,
            )
            db.add(row)
        row.start_date = start
        row.end_date = end
        row.asset_return = asset_return
        row.benchmark_return = benchmark_return
        row.excess_return = excess
        row.max_drawdown_asset = max_drawdown_from_rows(rows_asset)
        row.max_drawdown_benchmark = max_drawdown_from_rows(rows_benchmark)
        row.volatility_asset = volatility_from_rows(rows_asset)
        row.volatility_benchmark = volatility_from_rows(rows_benchmark)
        row.hit_vs_benchmark = None if excess is None else excess > 0
        row.information_ratio_proxy = None
        if excess is not None and row.volatility_asset:
            row.information_ratio_proxy = excess / max(row.volatility_asset, 0.0001)
        row.opportunity_cost = None if excess is None else -excess
        row.evaluation_notes = {
            "data_status": "complete" if asset_return is not None and benchmark_return is not None else "insufficient_price_history",
            "asset_rows": len(rows_asset),
            "benchmark_rows": len(rows_benchmark),
            "benchmark_selection": "sector_proxy_or_spy",
        }
        row.updated_at = datetime.utcnow()
        return row

    def list(self, db: Session, ticker: str | None = None, limit: int = 80) -> dict:
        query = select(BenchmarkRelativeOutcome).order_by(desc(BenchmarkRelativeOutcome.updated_at)).limit(limit)
        if ticker:
            query = query.where(BenchmarkRelativeOutcome.ticker == ticker.upper())
        rows = list(db.scalars(query).all())
        return {
            "count": len(rows),
            "rows": [serialize_benchmark(row) for row in rows],
            "governance": "Benchmark-relative outcomes measure evidence versus passive alternatives; they are not investment recommendations.",
        }


class ConvictionDecayEngine:
    def evaluate(self, db: Session, thesis_id: int | None = None, limit: int = 250, commit: bool = True) -> dict:
        query = select(BlumKnowledgeRecord).order_by(desc(BlumKnowledgeRecord.created_at)).limit(limit)
        if thesis_id is not None:
            query = query.where(BlumKnowledgeRecord.id == thesis_id)
        records = list(db.scalars(query).all())
        created = 0
        for record in records:
            self.evaluate_record(db, record)
            created += 1
        if commit:
            db.commit()
        else:
            db.flush()
        return {"status": "ok", "records_seen": len(records), "conviction_rows_created": created}

    def evaluate_record(self, db: Session, record: BlumKnowledgeRecord) -> ThesisConvictionHistory:
        previous_row = db.scalar(
            select(ThesisConvictionHistory)
            .where(ThesisConvictionHistory.thesis_id == record.id)
            .order_by(desc(ThesisConvictionHistory.evaluated_at))
            .limit(1)
        )
        previous = safe_float(previous_row.new_confidence if previous_row else record.confidence, 50.0)
        supporting, contradicting, risks = evidence_bundle(record)
        age_days = max(0, (datetime.utcnow() - (record.created_at or datetime.utcnow())).days)
        benchmark = latest_benchmark_outcome(db, "blum_thesis", record.id)
        excess = benchmark.excess_return if benchmark else None
        direction = record_direction(record)
        price_confirmation = 50.0
        if excess is not None:
            if direction == "bearish":
                price_confirmation = 65.0 if excess < 0 else 35.0
            elif direction == "bullish":
                price_confirmation = 65.0 if excess > 0 else 35.0
            else:
                price_confirmation = 50.0 - min(15.0, abs(excess) * 100)
        asset_context = record.asset_context or {}
        sentiment = asset_context.get("sentiment_indicators") or {}
        narrative = (record.blum_reasoning or {}).get("narrative_analysis") or {}
        relative_volume = safe_float((asset_context.get("volume_profile") or {}).get("relative_volume"), 1.0)
        volume_confirmation = clamp(45 + (relative_volume - 1.0) * 18, 25, 80)
        sentiment_confirmation = clamp(50 + safe_float(sentiment.get("sentiment_score") or sentiment.get("average_sentiment"), 0) * 35, 20, 80)
        narrative_confirmation = clamp(45 + safe_float(narrative.get("intensity"), 0) * 0.35 + safe_float(narrative.get("velocity"), 0) * 0.25, 20, 80)
        regime_confirmation = 48.0
        regime = (record.market_regime or "").lower()
        if direction == "bullish" and any(token in regime for token in ("bull", "recovery", "risk_on", "expansion")):
            regime_confirmation = 62.0
        elif direction == "bullish" and any(token in regime for token in ("risk-off", "panic", "down")):
            regime_confirmation = 32.0
        elif direction == "bearish" and any(token in regime for token in ("risk-off", "panic", "down")):
            regime_confirmation = 62.0
        benchmark_confirmation = price_confirmation
        evidence_freshness = clamp(100 - age_days * 3.0)
        contradiction_pressure = clamp(len(contradicting) * 7 + len(risks) * 2 + max(0, age_days - 14) * 1.2)
        stale_pressure = max(0, 55 - evidence_freshness)
        decay_score = clamp(contradiction_pressure + stale_pressure + max(0, 50 - price_confirmation) + max(0, 48 - regime_confirmation))
        strengthening_score = clamp(
            (len(supporting) * 5)
            + (price_confirmation - 35) * 0.8
            + (volume_confirmation - 35) * 0.45
            + (sentiment_confirmation - 40) * 0.35
            + (narrative_confirmation - 40) * 0.30
            + (regime_confirmation - 35) * 0.50
        )
        delta = confidence_delta_from_evidence(strengthening_score, decay_score)
        new_confidence = clamp(previous + delta)
        lifecycle = (record.blum_reasoning or {}).get("thesis_lifecycle") or {}
        status = "stable"
        if lifecycle.get("status") == "INVALIDATED":
            status = "invalidated"
            new_confidence = min(new_confidence, 25.0)
        elif age_days >= 45 and lifecycle.get("status") not in ("COMPLETED", "INVALIDATED"):
            status = "stale"
            new_confidence = min(new_confidence, 55.0)
        elif new_confidence < 40 or contradiction_pressure > 60:
            status = "fragile"
        elif delta <= -2:
            status = "decaying"
        elif delta >= 2:
            status = "strengthening"
        explanation = self.explain(record, delta, status, price_confirmation, evidence_freshness, contradiction_pressure)
        row = ThesisConvictionHistory(
            thesis_id=record.id,
            previous_confidence=round(previous, 2),
            new_confidence=round(new_confidence, 2),
            confidence_delta=round(new_confidence - previous, 2),
            decay_score=round(decay_score, 2),
            strengthening_score=round(strengthening_score, 2),
            evidence_freshness_score=round(evidence_freshness, 2),
            contradiction_pressure=round(contradiction_pressure, 2),
            price_confirmation_score=round(price_confirmation, 2),
            volume_confirmation_score=round(volume_confirmation, 2),
            sentiment_confirmation_score=round(sentiment_confirmation, 2),
            narrative_confirmation_score=round(narrative_confirmation, 2),
            regime_confirmation_score=round(regime_confirmation, 2),
            benchmark_confirmation_score=round(benchmark_confirmation, 2),
            invalidation_distance=None,
            status=status,
            explanation=explanation,
        )
        db.add(row)
        record.confidence = round(new_confidence, 2)
        record.blum_reasoning = {
            **(record.blum_reasoning or {}),
            "conviction_decay": {
                "previous_confidence": round(previous, 2),
                "current_confidence": round(new_confidence, 2),
                "confidence_delta": round(new_confidence - previous, 2),
                "status": status,
                "explanation": explanation,
                "evaluated_at": datetime.utcnow().isoformat(),
            },
        }
        record.updated_at = datetime.utcnow()
        return row

    def explain(
        self,
        record: BlumKnowledgeRecord,
        delta: float,
        status: str,
        price_confirmation: float,
        freshness: float,
        contradiction_pressure: float,
    ) -> str:
        if status == "invalidated":
            return "Conviction is capped because the thesis lifecycle is invalidated by matured outcome evidence."
        if status == "stale":
            return "Conviction decayed because the thesis is aging without enough fresh confirming evidence."
        if delta > 0:
            return f"Conviction increased gradually because price or benchmark-relative behavior is confirming the {record_direction(record)} thesis."
        if delta < 0:
            return f"Conviction declined because confirmation is weak ({price_confirmation:.0f}/100), evidence freshness is {freshness:.0f}/100 and contradiction pressure is {contradiction_pressure:.0f}/100."
        return "Conviction is stable because confirming and contradicting evidence are balanced."

    def list(self, db: Session, thesis_id: int | None = None, limit: int = 80) -> dict:
        query = select(ThesisConvictionHistory).order_by(desc(ThesisConvictionHistory.evaluated_at)).limit(limit)
        if thesis_id is not None:
            query = query.where(ThesisConvictionHistory.thesis_id == thesis_id)
        rows = list(db.scalars(query).all())
        return {"count": len(rows), "rows": [serialize_conviction(row) for row in rows]}


class ThesisSurvivalEngine:
    def evaluate(self, db: Session, thesis_id: int | None = None, limit: int = 250, commit: bool = True) -> dict:
        query = select(BlumKnowledgeRecord).order_by(desc(BlumKnowledgeRecord.created_at)).limit(limit)
        if thesis_id is not None:
            query = query.where(BlumKnowledgeRecord.id == thesis_id)
        records = list(db.scalars(query).all())
        updated = 0
        for record in records:
            self.evaluate_record(db, record)
            updated += 1
        if commit:
            db.commit()
        else:
            db.flush()
        return {"status": "ok", "records_seen": len(records), "survival_metrics_updated": updated}

    def evaluate_record(self, db: Session, record: BlumKnowledgeRecord) -> ThesisSurvivalMetric:
        created = record.created_at or datetime.utcnow()
        age_days = max(0, (datetime.utcnow() - created).days)
        lifecycle = (record.blum_reasoning or {}).get("thesis_lifecycle") or {}
        latest_conviction = db.scalar(
            select(ThesisConvictionHistory)
            .where(ThesisConvictionHistory.thesis_id == record.id)
            .order_by(desc(ThesisConvictionHistory.evaluated_at))
            .limit(1)
        )
        current_confidence = safe_float(latest_conviction.new_confidence if latest_conviction else record.confidence, 50.0)
        status = lifecycle.get("status") or "ACTIVE"
        if status == "ACTIVE" and age_days > 90:
            status = "EXPIRED"
        benchmark = latest_benchmark_outcome(db, "blum_thesis", record.id)
        start = as_date(created)
        end = as_date(benchmark.end_date) if benchmark else as_date(datetime.utcnow())
        rows = price_rows(db, record.asset_id, start, end)
        invalidated_at = None
        completed_at = None
        expired_at = None
        if status == "INVALIDATED":
            invalidated_at = datetime.utcnow()
        elif status == "COMPLETED":
            completed_at = datetime.utcnow()
        elif status == "EXPIRED":
            expired_at = datetime.utcnow()
        final_return = benchmark.asset_return if benchmark else None
        excess_return = benchmark.excess_return if benchmark else None
        adverse = max_drawdown_from_rows(rows)
        favorable = max_upside_from_rows(rows)
        quality = self.survival_quality(status, current_confidence, age_days, final_return, excess_return, adverse)
        row = db.scalar(select(ThesisSurvivalMetric).where(ThesisSurvivalMetric.thesis_id == record.id))
        if row is None:
            row = ThesisSurvivalMetric(
                thesis_id=record.id,
                ticker=record.ticker,
                created_at=created,
                initial_confidence=safe_float(record.confidence, 50.0),
                max_confidence=safe_float(record.confidence, 50.0),
                min_confidence=safe_float(record.confidence, 50.0),
            )
            db.add(row)
        row.ticker = record.ticker
        row.sector = record.sector or ""
        row.thesis_type = record_thesis_type(record)
        row.direction = record_direction(record)
        row.horizon = record_horizon(record)
        row.evaluated_at = datetime.utcnow()
        row.thesis_age_days = age_days
        row.survival_status = status
        row.survival_days = age_days if status in ("ACTIVE", "STRENGTHENING", "WEAKENING") else min(age_days, row.survival_days or age_days)
        row.current_confidence = round(current_confidence, 2)
        row.confidence_decay = round(max(0, row.initial_confidence - current_confidence), 2)
        row.max_confidence = round(max(row.max_confidence or 0.0, current_confidence), 2)
        row.min_confidence = round(min(row.min_confidence or current_confidence, current_confidence), 2)
        row.invalidated_at = row.invalidated_at or invalidated_at
        row.completed_at = row.completed_at or completed_at
        row.expired_at = row.expired_at or expired_at
        row.final_return = final_return
        row.benchmark_return = benchmark.benchmark_return if benchmark else None
        row.excess_return = excess_return
        row.max_adverse_excursion = adverse
        row.max_favorable_excursion = favorable
        row.regime_primary = record.market_regime or "Unknown"
        row.regime_secondary = record.volatility_regime or "Unknown"
        row.sector_regime = f"{record.sector or 'Unknown'} / {record.market_regime or 'Unknown'}"
        row.failure_reason = self.failure_reason(status, final_return, excess_return, adverse)
        row.survival_quality_score = round(quality, 2)
        row.notes_json = {
            "lifecycle_reason": lifecycle.get("reason"),
            "benchmark_ticker": benchmark.benchmark_ticker if benchmark else None,
            "benchmark_data_status": (benchmark.evaluation_notes or {}).get("data_status") if benchmark else "missing",
            "rule": "Survival measures thesis durability, not trade advice.",
        }
        row.updated_at = datetime.utcnow()
        return row

    def survival_quality(
        self,
        status: str,
        confidence: float,
        age_days: int,
        final_return: float | None,
        excess_return: float | None,
        adverse: float | None,
    ) -> float:
        score = confidence
        score += min(12, age_days * 0.25)
        if status == "COMPLETED":
            score += 8
        if status == "INVALIDATED":
            score -= 18
        if status == "EXPIRED":
            score -= 8
        if excess_return is not None:
            score += max(-18, min(18, excess_return * 180))
        elif final_return is not None:
            score += max(-8, min(8, final_return * 80))
        if adverse is not None:
            score += max(-18, adverse * 160)
        return clamp(score)

    def failure_reason(self, status: str, final_return: float | None, excess_return: float | None, adverse: float | None) -> str:
        if status == "INVALIDATED":
            return "matured_outcomes_contradicted_thesis"
        if excess_return is not None and excess_return < -0.03:
            return "underperformed_relevant_benchmark"
        if adverse is not None and adverse < -0.10:
            return "drawdown_pressure"
        if status == "EXPIRED":
            return "thesis_expired_without_resolution"
        return ""

    def list(self, db: Session, thesis_id: int | None = None, ticker: str | None = None, limit: int = 80) -> dict:
        query = select(ThesisSurvivalMetric).order_by(desc(ThesisSurvivalMetric.evaluated_at)).limit(limit)
        if thesis_id is not None:
            query = query.where(ThesisSurvivalMetric.thesis_id == thesis_id)
        if ticker:
            query = query.where(ThesisSurvivalMetric.ticker == ticker.upper())
        rows = list(db.scalars(query).all())
        return {
            "count": len(rows),
            "average_survival_days": round(mean([row.survival_days for row in rows]), 2) if rows else 0.0,
            "status_distribution": dict(Counter(row.survival_status for row in rows)),
            "rows": [serialize_survival(row) for row in rows],
        }


class ReliabilityByRegimeEngine:
    def recalculate(self, db: Session, limit: int = 1000, commit: bool = True) -> dict:
        outcomes = list(
            db.scalars(
                select(BlumThesisOutcome)
                .where(BlumThesisOutcome.outcome.in_(MATURE_OUTCOMES))
                .order_by(desc(BlumThesisOutcome.updated_at))
                .limit(limit)
            ).all()
        )
        groups: dict[tuple[str, ...], dict[str, Any]] = defaultdict(
            lambda: {
                "correct": 0,
                "wrong": 0,
                "neutral": 0,
                "returns": [],
                "excess": [],
                "drawdowns": [],
                "confidence": [],
                "calibration_errors": [],
            }
        )
        for outcome in outcomes:
            record = outcome.knowledge_record
            if record is None:
                continue
            benchmark = latest_benchmark_outcome(db, "blum_thesis", record.id)
            for contribution in engine_contributions(record):
                key = (
                    contribution["engine_name"],
                    contribution.get("evidence_type", "unknown"),
                    setup_type(record),
                    record_thesis_type(record),
                    record.sector or "Unknown",
                    record.industry or "",
                    (record.asset.asset_type if record.asset else "stock"),
                    f"{outcome.horizon_days}D",
                    record.market_regime or "Unknown",
                    record.volatility_regime or "Unknown",
                    (record.market_context or {}).get("breadth_state") or "Unknown",
                )
                data = groups[key]
                data[outcome.outcome] += 1
                if outcome.realized_return is not None:
                    data["returns"].append(float(outcome.realized_return))
                if benchmark and benchmark.excess_return is not None:
                    data["excess"].append(float(benchmark.excess_return))
                if outcome.max_drawdown is not None:
                    data["drawdowns"].append(float(outcome.max_drawdown))
                data["confidence"].append(float(record.confidence or 0))
        updated = 0
        for key, data in groups.items():
            row = db.scalar(
                select(ModelReliabilityByRegime).where(
                    and_(
                        ModelReliabilityByRegime.engine_name == key[0],
                        ModelReliabilityByRegime.signal_type == key[1],
                        ModelReliabilityByRegime.setup_type == key[2],
                        ModelReliabilityByRegime.thesis_type == key[3],
                        ModelReliabilityByRegime.sector == key[4],
                        ModelReliabilityByRegime.industry == key[5],
                        ModelReliabilityByRegime.asset_class == key[6],
                        ModelReliabilityByRegime.horizon == key[7],
                        ModelReliabilityByRegime.market_regime == key[8],
                        ModelReliabilityByRegime.volatility_regime == key[9],
                        ModelReliabilityByRegime.breadth_regime == key[10],
                    )
                )
            )
            if row is None:
                row = ModelReliabilityByRegime(
                    engine_name=key[0],
                    signal_type=key[1],
                    setup_type=key[2],
                    thesis_type=key[3],
                    sector=key[4],
                    industry=key[5],
                    asset_class=key[6],
                    horizon=key[7],
                    market_regime=key[8],
                    volatility_regime=key[9],
                    breadth_regime=key[10],
                )
                db.add(row)
            self.apply_row(row, data)
            updated += 1
        if commit:
            db.commit()
        else:
            db.flush()
        return {"status": "ok", "outcomes_seen": len(outcomes), "rows_updated": updated}

    def apply_row(self, row: ModelReliabilityByRegime, data: dict[str, Any]) -> None:
        correct = int(data["correct"])
        wrong = int(data["wrong"])
        neutral = int(data["neutral"])
        sample = correct + wrong + neutral
        hit_rate = ((correct + neutral * 0.5) / sample) if sample else 0.0
        prior = 10
        reliability = ((hit_rate * sample) + (0.5 * prior)) / (sample + prior) * 100 if sample else 50.0
        avg_excess = mean(data["excess"]) if data["excess"] else None
        if avg_excess is not None:
            reliability += max(-10, min(10, avg_excess * 100))
        avg_confidence = mean(data["confidence"]) if data["confidence"] else 50.0
        row.sample_size = sample
        row.hit_rate = round(hit_rate, 4)
        row.average_return = round(mean(data["returns"]), 6) if data["returns"] else None
        row.excess_return_vs_benchmark = round(avg_excess, 6) if avg_excess is not None else None
        row.average_r_multiple = None
        row.max_drawdown = round(min(data["drawdowns"]), 6) if data["drawdowns"] else None
        row.false_positive_rate = round(wrong / sample, 4) if sample else 0.0
        row.false_negative_rate = round(wrong / sample, 4) if sample else 0.0
        row.calibration_error = round((hit_rate * 100) - avg_confidence, 2) if sample else None
        row.reliability_score = round(clamp(reliability), 2)
        row.confidence_penalty = round(max(0.0, 55.0 - row.reliability_score) / 100.0, 4)
        row.last_updated = datetime.utcnow()

    def list(self, db: Session, engine_name: str | None = None, limit: int = 80) -> dict:
        query = select(ModelReliabilityByRegime).order_by(desc(ModelReliabilityByRegime.reliability_score)).limit(limit)
        if engine_name:
            query = query.where(ModelReliabilityByRegime.engine_name == engine_name)
        rows = list(db.scalars(query).all())
        return {
            "count": len(rows),
            "rows": [serialize_reliability_by_regime(row) for row in rows],
            "guardrail": "Rows with small sample sizes should be treated as weak evidence, not durable reliability.",
        }


class ThesisCompetitionEngine:
    def run_for_ticker(self, db: Session, ticker: str, commit: bool = True) -> dict:
        ticker = ticker.upper()
        record = db.scalar(
            select(BlumKnowledgeRecord)
            .where(BlumKnowledgeRecord.ticker == ticker)
            .order_by(desc(BlumKnowledgeRecord.created_at))
            .limit(1)
        )
        if record is None:
            return {"status": "insufficient_data", "ticker": ticker, "message": "No Blum knowledge thesis exists for this ticker."}
        competition = ThesisCompetition(
            ticker=ticker,
            market_regime=record.market_regime or "Unknown",
            sector_regime=f"{record.sector or 'Unknown'} / {record.market_regime or 'Unknown'}",
            status="active",
        )
        db.add(competition)
        db.flush()
        candidates = self.build_candidates(db, record)
        thesis_rows: list[CompetingThesis] = []
        for candidate in candidates:
            row = CompetingThesis(competition_id=competition.id, **candidate)
            db.add(row)
            thesis_rows.append(row)
        db.flush()
        ranked = sorted(thesis_rows, key=lambda item: item.judge_score or 0, reverse=True)
        competition.winning_thesis_id = ranked[0].id if ranked else None
        competition.runner_up_thesis_id = ranked[1].id if len(ranked) > 1 else None
        spread = (ranked[0].judge_score - ranked[1].judge_score) if len(ranked) > 1 else 100
        competition.uncertainty_score = round(clamp(100 - spread), 2)
        competition.judge_summary = self.judge_summary(ranked)
        competition.next_evidence_to_watch = {
            "price_confirmation": "Benchmark-relative follow-through and invalidation distance.",
            "contradictions": "Sector weakness, stale news evidence, or regime deterioration.",
            "risk": "Confidence is reduced when bull, bear and neutral theses are tightly clustered.",
        }
        if commit:
            db.commit()
        else:
            db.flush()
        return {"status": "ok", "ticker": ticker, "competition": serialize_competition(competition, thesis_rows)}

    def build_candidates(self, db: Session, record: BlumKnowledgeRecord) -> list[dict]:
        supporting, contradicting, risks = evidence_bundle(record)
        benchmark = latest_benchmark_outcome(db, "blum_thesis", record.id)
        excess = safe_float(benchmark.excess_return if benchmark else 0.0, 0.0)
        base_conf = safe_float(record.confidence, 50.0)
        bull_score = clamp(base_conf + len(supporting) * 3 - len(contradicting) * 3 + excess * 120)
        bear_score = clamp(50 + len(contradicting) * 6 + len(risks) * 2 - len(supporting) * 2 - excess * 120)
        neutral_score = clamp(45 + abs(bull_score - bear_score) * -0.25 + len(risks) * 4 + (0 if benchmark else 12))
        horizon = record_horizon(record)
        return [
            {
                "thesis_side": "bull",
                "thesis_text": self.bull_text(record),
                "supporting_evidence_json": {"items": supporting, "benchmark_excess_return": excess if benchmark else None},
                "contradicting_evidence_json": {"items": contradicting},
                "confidence": round(base_conf, 2),
                "judge_score": round(bull_score, 2),
                "invalidation_conditions_json": {"items": listify((record.blum_reasoning or {}).get("invalidation_conditions"))},
                "expected_horizon": horizon,
            },
            {
                "thesis_side": "bear",
                "thesis_text": self.bear_text(record),
                "supporting_evidence_json": {"items": contradicting + risks},
                "contradicting_evidence_json": {"items": supporting},
                "confidence": round(clamp(bear_score), 2),
                "judge_score": round(bear_score, 2),
                "invalidation_conditions_json": {"items": ["Bear thesis weakens if price and sector strength confirm together."]},
                "expected_horizon": horizon,
            },
            {
                "thesis_side": "neutral",
                "thesis_text": self.neutral_text(record),
                "supporting_evidence_json": {"items": risks or ["Evidence balance is not decisive enough for a high-conviction view."]},
                "contradicting_evidence_json": {"items": supporting + contradicting},
                "confidence": round(clamp(neutral_score), 2),
                "judge_score": round(neutral_score, 2),
                "invalidation_conditions_json": {"items": ["Neutral thesis loses if one side receives independent price, volume and regime confirmation."]},
                "expected_horizon": horizon,
            },
        ]

    def bull_text(self, record: BlumKnowledgeRecord) -> str:
        thesis = (record.blum_reasoning or {}).get("executive_thesis") or f"{record.ticker} may keep improving if evidence confirms."
        return f"Bull thesis: {thesis}"

    def bear_text(self, record: BlumKnowledgeRecord) -> str:
        return f"Bear thesis: {record.ticker} may fail if contradictions, regime pressure or benchmark underperformance dominate the original thesis."

    def neutral_text(self, record: BlumKnowledgeRecord) -> str:
        return f"Neutral thesis: {record.ticker} remains a monitoring case until evidence resolves toward confirmation or invalidation."

    def judge_summary(self, ranked: list[CompetingThesis]) -> str:
        if not ranked:
            return "No competing thesis could be generated from stored evidence."
        leader = ranked[0]
        runner = ranked[1] if len(ranked) > 1 else None
        if runner and abs((leader.judge_score or 0) - (runner.judge_score or 0)) < 8:
            return f"{leader.thesis_side.title()} thesis leads only narrowly; uncertainty remains elevated."
        return f"{leader.thesis_side.title()} thesis currently leads the competition based on stored evidence and judge score."

    def evaluate(self, db: Session, limit: int = 120, commit: bool = True) -> dict:
        rows = list(db.scalars(select(CompetingThesis).order_by(desc(CompetingThesis.created_at)).limit(limit)).all())
        updated = 0
        for thesis in rows:
            competition = thesis.competition
            if competition is None:
                continue
            benchmark = db.scalar(
                select(BenchmarkRelativeOutcome)
                .where(and_(BenchmarkRelativeOutcome.ticker == competition.ticker, BenchmarkRelativeOutcome.object_type == "blum_thesis"))
                .order_by(desc(BenchmarkRelativeOutcome.updated_at))
                .limit(1)
            )
            if benchmark is None or benchmark.excess_return is None:
                continue
            thesis.benchmark_relative_outcome = serialize_benchmark(benchmark)
            if thesis.thesis_side == "bull":
                thesis.outcome_status = "supported" if benchmark.excess_return > 0 else "contradicted"
            elif thesis.thesis_side == "bear":
                thesis.outcome_status = "supported" if benchmark.excess_return < 0 else "contradicted"
            else:
                thesis.outcome_status = "supported" if abs(benchmark.excess_return) < 0.02 else "contradicted"
            thesis.evaluated_at = datetime.utcnow()
            updated += 1
        if commit:
            db.commit()
        else:
            db.flush()
        return {"status": "ok", "competing_theses_seen": len(rows), "evaluated": updated}

    def list(self, db: Session, ticker: str | None = None, limit: int = 60) -> dict:
        query = select(ThesisCompetition).order_by(desc(ThesisCompetition.created_at)).limit(limit)
        if ticker:
            query = query.where(ThesisCompetition.ticker == ticker.upper())
        competitions = list(db.scalars(query).all())
        rows = []
        for competition in competitions:
            theses = list(db.scalars(select(CompetingThesis).where(CompetingThesis.competition_id == competition.id)).all())
            rows.append(serialize_competition(competition, theses))
        return {"count": len(rows), "rows": rows}


class EnsembleEvolutionEngine:
    default_weights = {
        "thesis_engine": 0.16,
        "technical_engine": 0.14,
        "sentiment_engine": 0.12,
        "narrative_engine": 0.12,
        "fundamental_engine": 0.10,
        "regime_engine": 0.16,
        "self_critique_engine": 0.10,
        "historical_memory_engine": 0.10,
    }

    def vote_recent(self, db: Session, limit: int = 120, commit: bool = True) -> dict:
        records = list(db.scalars(select(BlumKnowledgeRecord).order_by(desc(BlumKnowledgeRecord.created_at)).limit(limit)).all())
        votes = 0
        for record in records:
            votes += self.vote_record(db, record)
        if commit:
            db.commit()
        else:
            db.flush()
        return {"status": "ok", "records_seen": len(records), "votes_recorded": votes}

    def vote_ticker(self, db: Session, ticker: str, commit: bool = True) -> dict:
        record = db.scalar(
            select(BlumKnowledgeRecord)
            .where(BlumKnowledgeRecord.ticker == ticker.upper())
            .order_by(desc(BlumKnowledgeRecord.created_at))
            .limit(1)
        )
        if record is None:
            return {"status": "insufficient_data", "ticker": ticker.upper()}
        votes = self.vote_record(db, record)
        consensus = self.consensus_for_record(db, record.id)
        if commit:
            db.commit()
        else:
            db.flush()
        return {"status": "ok", "ticker": ticker.upper(), "votes_recorded": votes, "consensus": consensus}

    def vote_record(self, db: Session, record: BlumKnowledgeRecord) -> int:
        weights = self.active_weights(db)
        created = 0
        for contribution in engine_contributions(record):
            engine_name = contribution["engine_name"]
            vote, confidence, evidence_quality = self.engine_vote(record, engine_name)
            row = db.scalar(
                select(EngineVote).where(
                    and_(
                        EngineVote.thesis_id == record.id,
                        EngineVote.engine_name == engine_name,
                        EngineVote.horizon == record_horizon(record),
                    )
                )
            )
            if row is None:
                row = EngineVote(
                    thesis_id=record.id,
                    ticker=record.ticker,
                    engine_name=engine_name,
                    horizon=record_horizon(record),
                )
                db.add(row)
                created += 1
            row.vote = vote
            row.confidence = round(confidence, 2)
            row.evidence_quality = round(evidence_quality, 2)
            row.regime = record.market_regime or "Unknown"
            row.sector = record.sector or "Unknown"
            row.created_at = datetime.utcnow()
            row.reliability_weight_at_time = round(weights.get(engine_name, 0.1), 4)
            outcome = db.scalar(
                select(BlumThesisOutcome)
                .where(and_(BlumThesisOutcome.knowledge_record_id == record.id, BlumThesisOutcome.outcome.in_(MATURE_OUTCOMES)))
                .order_by(desc(BlumThesisOutcome.updated_at))
                .limit(1)
            )
            row.outcome_evaluated = outcome is not None
            if outcome is not None:
                row.was_correct = self.vote_matches_outcome(row.vote, outcome.outcome)
                row.excess_return_contribution = safe_float(outcome.realized_return, 0.0) * row.reliability_weight_at_time
        return created

    def engine_vote(self, record: BlumKnowledgeRecord, engine_name: str) -> tuple[str, float, float]:
        direction = record_direction(record)
        quality = quality_score(record)
        confidence = safe_float(record.confidence, 50.0)
        if engine_name == "regime_engine":
            regime = (record.market_regime or "").lower()
            if direction == "bullish" and any(token in regime for token in ("risk-off", "panic", "down")):
                return "avoid", 62.0, quality
            if direction == "bullish" and any(token in regime for token in ("bull", "recovery", "risk_on")):
                return "bullish", 62.0, quality
        if engine_name == "self_critique_engine":
            _, contradictions, _ = evidence_bundle(record)
            return ("wait" if contradictions else direction, min(70.0, confidence), quality)
        if engine_name == "historical_memory_engine":
            historical = (record.blum_reasoning or {}).get("historical_similarity") or {}
            if not historical:
                return "insufficient_evidence", 35.0, quality
        if direction == "bearish":
            return "bearish", confidence, quality
        if direction == "bullish":
            return "bullish", confidence, quality
        return "neutral", min(55.0, confidence), quality

    def vote_matches_outcome(self, vote: str, outcome: str) -> bool | None:
        if vote in ("wait", "avoid", "insufficient_evidence") or outcome == "neutral":
            return None
        if vote == "bullish":
            return outcome == "correct"
        if vote == "bearish":
            return outcome == "wrong"
        return None

    def active_weights(self, db: Session) -> dict[str, float]:
        row = db.scalar(select(EnsembleWeightVersion).where(EnsembleWeightVersion.is_active.is_(True)).order_by(desc(EnsembleWeightVersion.created_at)).limit(1))
        if row and row.weights_json:
            return {**self.default_weights, **{str(k): float(v) for k, v in row.weights_json.items()}}
        return dict(self.default_weights)

    def consensus_for_record(self, db: Session, thesis_id: int) -> dict:
        rows = list(db.scalars(select(EngineVote).where(EngineVote.thesis_id == thesis_id)).all())
        weights = defaultdict(float)
        for row in rows:
            weights[row.vote] += safe_float(row.reliability_weight_at_time, 0.1) * safe_float(row.confidence, 50.0) / 100
        penalty = ensemble_disagreement_penalty(dict(weights))
        leading_vote = max(weights.items(), key=lambda item: item[1])[0] if weights else "insufficient_evidence"
        return {
            "thesis_id": thesis_id,
            "leading_vote": leading_vote,
            "vote_weights": dict(weights),
            "disagreement_score": penalty,
            "confidence_adjustment": round(-penalty / 4, 2),
            "rule": "High disagreement reduces confidence even when one engine is strongly positive.",
        }

    def recalculate(self, db: Session, min_sample: int = 30, commit: bool = True) -> dict:
        rows = list(db.scalars(select(ModelReliabilityByRegime).where(ModelReliabilityByRegime.sample_size >= min_sample)).all())
        if not rows:
            return {
                "status": "insufficient_sample",
                "min_sample": min_sample,
                "message": "No ensemble weights changed because regime-aware reliability evidence is still too small.",
            }
        grouped: dict[str, list[float]] = defaultdict(list)
        samples = 0
        for row in rows:
            grouped[row.engine_name].append(row.reliability_score)
            samples += row.sample_size
        weights = {}
        total = 0.0
        for engine, values in grouped.items():
            score = max(20.0, mean(values))
            weights[engine] = score
            total += score
        normalized = {engine: round(score / total, 4) for engine, score in weights.items()} if total else self.default_weights
        for row in db.scalars(select(EnsembleWeightVersion).where(EnsembleWeightVersion.is_active.is_(True))).all():
            row.is_active = False
        version = EnsembleWeightVersion(
            version_name=f"regime_weights_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            weights_json=normalized,
            reason="Updated from model_reliability_by_regime rows with sufficient sample size. This changes DB parameters only, not source code.",
            sample_size=samples,
            validation_score=round(mean([mean(values) for values in grouped.values()]), 2),
            calibration_score=50.0,
            is_active=True,
        )
        db.add(version)
        if commit:
            db.commit()
        else:
            db.flush()
        return {"status": "ok", "version_id": version.id, "weights": normalized, "sample_size": samples}

    def status(self, db: Session) -> dict:
        weights = self.active_weights(db)
        total_votes = int(db.scalar(select(func.count(EngineVote.id))) or 0)
        disagreements = self.disagreements(db, limit=20)
        return {"weights": weights, "total_votes": total_votes, "top_disagreements": disagreements["rows"][:5]}

    def disagreements(self, db: Session, limit: int = 80) -> dict:
        thesis_ids = [row[0] for row in db.execute(select(EngineVote.thesis_id).group_by(EngineVote.thesis_id).limit(limit * 3)).all()]
        rows = []
        for thesis_id in thesis_ids:
            consensus = self.consensus_for_record(db, thesis_id)
            if consensus["disagreement_score"] > 30:
                rows.append(consensus)
        rows = sorted(rows, key=lambda item: item["disagreement_score"], reverse=True)[:limit]
        return {"count": len(rows), "rows": rows}


class TrainingDatasetQualityService:
    def evaluate(self, db: Session, limit: int = 500, commit: bool = True) -> dict:
        examples = list(db.scalars(select(BlumTrainingExample).order_by(desc(BlumTrainingExample.created_at)).limit(limit)).all())
        updated = 0
        included = 0
        for example in examples:
            row = self.evaluate_example(db, example)
            updated += 1
            included += 1 if row.include_in_sft else 0
        if commit:
            db.commit()
        else:
            db.flush()
        return {"status": "ok", "examples_seen": len(examples), "quality_rows_updated": updated, "sft_included": included}

    def evaluate_example(self, db: Session, example: BlumTrainingExample) -> TrainingExampleQualityScore:
        record = example.knowledge_record
        quality = example.quality_scores or {}
        outcome = None
        benchmark = None
        if record is not None:
            outcome = db.scalar(
                select(BlumThesisOutcome)
                .where(and_(BlumThesisOutcome.knowledge_record_id == record.id, BlumThesisOutcome.outcome.in_(MATURE_OUTCOMES)))
                .order_by(desc(BlumThesisOutcome.updated_at))
                .limit(1)
            )
            benchmark = latest_benchmark_outcome(db, "blum_thesis", record.id)
        supporting, contradicting, risks = evidence_bundle(record) if record is not None else ([], [], [])
        scores = {
            "reasoning_quality_score": safe_float(quality.get("overall_score"), 50.0),
            "outcome_clarity_score": 80.0 if outcome and outcome.outcome in ("correct", "wrong") else 45.0 if outcome else 25.0,
            "data_quality_score": safe_float(quality.get("data_quality_score"), 55.0),
            "contradiction_handling_score": clamp(45 + len(contradicting) * 8 + len(risks) * 2, 35, 90),
            "confidence_calibration_score": clamp(100 - abs(safe_float(record.confidence if record else 50.0, 50.0) - (100 if outcome and outcome.outcome == "correct" else 50))),
            "regime_context_score": 75.0 if record and record.market_regime and record.market_regime != "Unknown" else 35.0,
            "benchmark_relevance_score": 80.0 if benchmark and benchmark.excess_return is not None else 30.0,
            "reproducibility_score": clamp(45 + len(supporting) * 5 + len(contradicting) * 4, 30, 90),
        }
        final_score = training_value_score(scores)
        row = db.scalar(select(TrainingExampleQualityScore).where(TrainingExampleQualityScore.training_example_id == example.id))
        if row is None:
            row = TrainingExampleQualityScore(training_example_id=example.id)
            db.add(row)
        row.thesis_id = example.knowledge_record_id
        for key, value in scores.items():
            setattr(row, key, round(value, 2))
        row.final_training_value_score = final_score
        row.include_in_sft = final_score >= 65
        row.include_in_preference_training = final_score >= 70 and bool(outcome)
        row.include_in_dpo = final_score >= 75 and bool(outcome) and bool(benchmark and benchmark.excess_return is not None)
        row.exclusion_reason = "" if row.include_in_sft else self.exclusion_reason(scores, outcome, benchmark)
        row.evaluated_at = datetime.utcnow()
        return row

    def exclusion_reason(self, scores: dict[str, float], outcome: BlumThesisOutcome | None, benchmark: BenchmarkRelativeOutcome | None) -> str:
        if scores["outcome_clarity_score"] < 50:
            return "Outcome is not mature or not clear enough for high-quality training."
        if scores["benchmark_relevance_score"] < 50:
            return "Benchmark-relative evidence is missing."
        if scores["contradiction_handling_score"] < 50:
            return "Contradiction handling is too shallow."
        return "Final training value score below threshold."

    def list(self, db: Session, limit: int = 80) -> dict:
        rows = list(db.scalars(select(TrainingExampleQualityScore).order_by(desc(TrainingExampleQualityScore.final_training_value_score)).limit(limit)).all())
        return {"count": len(rows), "rows": [serialize_training_quality(row) for row in rows]}

    def export_high_quality(self, db: Session, limit: int = 1000, min_score: float = 65.0, commit: bool = True) -> dict:
        rows = list(
            db.scalars(
                select(TrainingExampleQualityScore)
                .where(TrainingExampleQualityScore.final_training_value_score >= min_score)
                .order_by(desc(TrainingExampleQualityScore.final_training_value_score))
                .limit(limit)
            ).all()
        )
        export_dir = os.getenv("BLUM_TRAINING_EXPORT_DIR", "/tmp/blum_training_exports")
        os.makedirs(export_dir, exist_ok=True)
        export_name = f"blum_high_quality_reasoning_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jsonl"
        file_path = os.path.join(export_dir, export_name)
        count = 0
        with open(file_path, "w", encoding="utf-8") as handle:
            for row in rows:
                example = row.training_example
                if example is None:
                    continue
                payload = {
                    "schema_version": "blum-high-quality-reasoning-v0.2",
                    "quality": serialize_training_quality(row),
                    "input": example.input_payload,
                    "output": example.output_payload,
                    "messages": (example.messages or {}).get("items", []),
                    "preference": example.preference_payload,
                }
                handle.write(json.dumps(json_safe(payload), ensure_ascii=False) + "\n")
                count += 1
        export = BlumDatasetExport(
            export_name=export_name,
            format="jsonl",
            record_count=count,
            file_path=file_path,
            filters={"min_training_value_score": min_score, "limit": limit},
            status="created",
            payload_summary={
                "supported_exports": ["sft", "preference_pairs", "dpo_pairs", "reasoning_traces", "failed_thesis_examples"],
                "quality_gate": "Only scored examples above threshold are exported.",
            },
        )
        db.add(export)
        if commit:
            db.commit()
        else:
            db.flush()
        return {"status": "ok", "export_id": export.id, "record_count": count, "file_path": file_path}


class ReasoningCoreOrchestrator:
    def run(self, db: Session, limit: int = 250, commit: bool = True) -> dict:
        stages: list[dict] = []
        started = datetime.utcnow()
        for name, func in (
            ("legacy_reasoning_core", lambda: run_reasoning_core_cycle(db, limit=limit, commit=False)),
            ("benchmark_relative", lambda: BenchmarkRelativeEvaluator().evaluate(db, limit=limit, commit=False)),
            ("conviction_decay", lambda: ConvictionDecayEngine().evaluate(db, limit=limit, commit=False)),
            ("thesis_survival", lambda: ThesisSurvivalEngine().evaluate(db, limit=limit, commit=False)),
            ("reliability_by_regime", lambda: ReliabilityByRegimeEngine().recalculate(db, limit=max(limit * 4, 500), commit=False)),
            ("ensemble_votes", lambda: EnsembleEvolutionEngine().vote_recent(db, limit=min(limit, 160), commit=False)),
            ("thesis_competitions", lambda: self.run_competitions(db, limit=min(limit, 25))),
            ("training_dataset_quality", lambda: TrainingDatasetQualityService().evaluate(db, limit=max(limit, 200), commit=False)),
        ):
            try:
                payload = func()
                stages.append({"stage": name, "status": payload.get("status", "ok") if isinstance(payload, dict) else "ok", "payload": json_safe(payload)})
            except Exception as exc:  # pragma: no cover - defensive runtime guard
                stages.append({"stage": name, "status": "degraded", "error": f"{type(exc).__name__}: {exc}"})
        result = {
            "status": "ok" if all(stage["status"] != "degraded" for stage in stages) else "degraded",
            "started_at": started.isoformat(),
            "completed_at": datetime.utcnow().isoformat(),
            "limit": limit,
            "stages": stages,
            "safety": [
                "No source code was modified by the reasoning core.",
                "Weight changes, confidence changes and training gates are database records and can be reviewed.",
                "Missing data creates degraded or insufficient_data output rather than fabricated evidence.",
            ],
        }
        db.add(
            LearningEvent(
                event_type="reasoning_core_orchestrator",
                severity="Info" if result["status"] == "ok" else "Warning",
                title="Reasoning Core Orchestrator cycle completed",
                description="Ran thesis survival, conviction decay, regime-aware reliability, competition, ensemble, benchmark and training quality layers.",
                payload=result,
            )
        )
        if commit:
            db.commit()
        else:
            db.flush()
        return result

    def run_competitions(self, db: Session, limit: int = 25) -> dict:
        tickers = [
            row[0]
            for row in db.execute(
                select(BlumKnowledgeRecord.ticker)
                .group_by(BlumKnowledgeRecord.ticker)
                .order_by(func.max(BlumKnowledgeRecord.created_at).desc())
                .limit(limit)
            ).all()
        ]
        created = 0
        engine = ThesisCompetitionEngine()
        for ticker in tickers:
            result = engine.run_for_ticker(db, ticker, commit=False)
            created += 1 if result.get("status") == "ok" else 0
        return {"status": "ok", "tickers_seen": len(tickers), "competitions_created": created}

    def status(self, db: Session) -> dict:
        latest = self.latest(db)
        return {
            "status": "active",
            "latest_cycle": latest,
            "counts": {
                "thesis_survival_metrics": int(db.scalar(select(func.count(ThesisSurvivalMetric.id))) or 0),
                "conviction_history_rows": int(db.scalar(select(func.count(ThesisConvictionHistory.id))) or 0),
                "reliability_by_regime_rows": int(db.scalar(select(func.count(ModelReliabilityByRegime.id))) or 0),
                "thesis_competitions": int(db.scalar(select(func.count(ThesisCompetition.id))) or 0),
                "engine_votes": int(db.scalar(select(func.count(EngineVote.id))) or 0),
                "training_quality_rows": int(db.scalar(select(func.count(TrainingExampleQualityScore.id))) or 0),
                "benchmark_relative_outcomes": int(db.scalar(select(func.count(BenchmarkRelativeOutcome.id))) or 0),
            },
            "governance": "The precision core improves calibration and reasoning memory without claiming certainty or trading autonomously.",
        }

    def latest(self, db: Session) -> dict | None:
        event = db.scalar(
            select(LearningEvent)
            .where(LearningEvent.event_type == "reasoning_core_orchestrator")
            .order_by(desc(LearningEvent.created_at))
            .limit(1)
        )
        if event is None:
            return None
        return {"id": event.id, "created_at": event.created_at.isoformat(), "payload": event.payload}

    def diagnostics(self, db: Session) -> dict:
        return {
            "status": self.status(db),
            "ensemble": EnsembleEvolutionEngine().status(db),
            "survival": ThesisSurvivalEngine().list(db, limit=20),
            "conviction": ConvictionDecayEngine().list(db, limit=20),
            "benchmark": BenchmarkRelativeEvaluator().list(db, limit=20),
        }


def serialize_survival(row: ThesisSurvivalMetric) -> dict:
    return {
        "id": row.id,
        "thesis_id": row.thesis_id,
        "ticker": row.ticker,
        "sector": row.sector,
        "thesis_type": row.thesis_type,
        "direction": row.direction,
        "horizon": row.horizon,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "evaluated_at": row.evaluated_at.isoformat() if row.evaluated_at else None,
        "thesis_age_days": row.thesis_age_days,
        "survival_status": row.survival_status,
        "survival_days": row.survival_days,
        "initial_confidence": row.initial_confidence,
        "current_confidence": row.current_confidence,
        "confidence_decay": row.confidence_decay,
        "final_return": row.final_return,
        "benchmark_return": row.benchmark_return,
        "excess_return": row.excess_return,
        "max_adverse_excursion": row.max_adverse_excursion,
        "max_favorable_excursion": row.max_favorable_excursion,
        "regime_primary": row.regime_primary,
        "failure_reason": row.failure_reason,
        "survival_quality_score": row.survival_quality_score,
        "notes": row.notes_json,
    }


def serialize_conviction(row: ThesisConvictionHistory) -> dict:
    return {
        "id": row.id,
        "thesis_id": row.thesis_id,
        "evaluated_at": row.evaluated_at.isoformat() if row.evaluated_at else None,
        "previous_confidence": row.previous_confidence,
        "new_confidence": row.new_confidence,
        "confidence_delta": row.confidence_delta,
        "decay_score": row.decay_score,
        "strengthening_score": row.strengthening_score,
        "evidence_freshness_score": row.evidence_freshness_score,
        "contradiction_pressure": row.contradiction_pressure,
        "price_confirmation_score": row.price_confirmation_score,
        "benchmark_confirmation_score": row.benchmark_confirmation_score,
        "status": row.status,
        "explanation": row.explanation,
    }


def serialize_reliability_by_regime(row: ModelReliabilityByRegime) -> dict:
    return {
        "id": row.id,
        "engine_name": row.engine_name,
        "signal_type": row.signal_type,
        "setup_type": row.setup_type,
        "thesis_type": row.thesis_type,
        "sector": row.sector,
        "industry": row.industry,
        "asset_class": row.asset_class,
        "horizon": row.horizon,
        "market_regime": row.market_regime,
        "volatility_regime": row.volatility_regime,
        "breadth_regime": row.breadth_regime,
        "sample_size": row.sample_size,
        "hit_rate": row.hit_rate,
        "average_return": row.average_return,
        "excess_return_vs_benchmark": row.excess_return_vs_benchmark,
        "max_drawdown": row.max_drawdown,
        "false_positive_rate": row.false_positive_rate,
        "calibration_error": row.calibration_error,
        "reliability_score": row.reliability_score,
        "confidence_penalty": row.confidence_penalty,
        "last_updated": row.last_updated.isoformat() if row.last_updated else None,
    }


def serialize_competition(row: ThesisCompetition, theses: list[CompetingThesis]) -> dict:
    return {
        "id": row.id,
        "ticker": row.ticker,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "market_regime": row.market_regime,
        "sector_regime": row.sector_regime,
        "winning_thesis_id": row.winning_thesis_id,
        "runner_up_thesis_id": row.runner_up_thesis_id,
        "uncertainty_score": row.uncertainty_score,
        "judge_summary": row.judge_summary,
        "next_evidence_to_watch": row.next_evidence_to_watch,
        "status": row.status,
        "theses": [serialize_competing_thesis(item) for item in sorted(theses, key=lambda item: item.judge_score or 0, reverse=True)],
    }


def serialize_competing_thesis(row: CompetingThesis) -> dict:
    return {
        "id": row.id,
        "competition_id": row.competition_id,
        "thesis_side": row.thesis_side,
        "thesis_text": row.thesis_text,
        "supporting_evidence": row.supporting_evidence_json,
        "contradicting_evidence": row.contradicting_evidence_json,
        "confidence": row.confidence,
        "judge_score": row.judge_score,
        "invalidation_conditions": row.invalidation_conditions_json,
        "expected_horizon": row.expected_horizon,
        "outcome_status": row.outcome_status,
        "benchmark_relative_outcome": row.benchmark_relative_outcome,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "evaluated_at": row.evaluated_at.isoformat() if row.evaluated_at else None,
    }


def serialize_benchmark(row: BenchmarkRelativeOutcome) -> dict:
    return {
        "id": row.id,
        "object_type": row.object_type,
        "object_id": row.object_id,
        "ticker": row.ticker,
        "benchmark_ticker": row.benchmark_ticker,
        "start_date": row.start_date.isoformat() if row.start_date else None,
        "end_date": row.end_date.isoformat() if row.end_date else None,
        "asset_return": row.asset_return,
        "benchmark_return": row.benchmark_return,
        "excess_return": row.excess_return,
        "max_drawdown_asset": row.max_drawdown_asset,
        "max_drawdown_benchmark": row.max_drawdown_benchmark,
        "volatility_asset": row.volatility_asset,
        "volatility_benchmark": row.volatility_benchmark,
        "hit_vs_benchmark": row.hit_vs_benchmark,
        "information_ratio_proxy": row.information_ratio_proxy,
        "opportunity_cost": row.opportunity_cost,
        "evaluation_notes": row.evaluation_notes,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def serialize_training_quality(row: TrainingExampleQualityScore) -> dict:
    return {
        "id": row.id,
        "training_example_id": row.training_example_id,
        "thesis_id": row.thesis_id,
        "reasoning_quality_score": row.reasoning_quality_score,
        "outcome_clarity_score": row.outcome_clarity_score,
        "data_quality_score": row.data_quality_score,
        "contradiction_handling_score": row.contradiction_handling_score,
        "confidence_calibration_score": row.confidence_calibration_score,
        "regime_context_score": row.regime_context_score,
        "benchmark_relevance_score": row.benchmark_relevance_score,
        "reproducibility_score": row.reproducibility_score,
        "final_training_value_score": row.final_training_value_score,
        "include_in_sft": row.include_in_sft,
        "include_in_preference_training": row.include_in_preference_training,
        "include_in_dpo": row.include_in_dpo,
        "exclusion_reason": row.exclusion_reason,
        "evaluated_at": row.evaluated_at.isoformat() if row.evaluated_at else None,
    }
