from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
import hashlib
import json
import os
from statistics import mean, stdev
from typing import Any

from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from app.ai.embeddings import EmbeddingModel
from app.core.config import get_settings
from app.models import (
    AIInsight,
    Asset,
    BlumDatasetExport,
    BlumKnowledgeGraphEdge,
    BlumKnowledgeGraphNode,
    BlumKnowledgeRecord,
    BlumModelTrainingJob,
    BlumNarrativeMemory,
    BlumReasoningMemory,
    BlumRegimeMemory,
    BlumSelfCritique,
    BlumThesisOutcome,
    BlumThesisQualityScore,
    BlumTrainingExample,
    ConfidenceCalibrationBucket,
    BenchmarkRelativeOutcome,
    EngineVote,
    ModelReliabilityByRegime,
    LearningEvent,
    MetaLearningEvent,
    ModelReliabilityMatrix,
    PriceHistory,
    SignalSnapshot,
    ThesisCompetition,
    ThesisConvictionHistory,
    ThesisLifecycleEvent,
    ThesisSurvivalMetric,
    TrainingExampleQualityScore,
)
from app.services.thesis_engine import build_asset_thesis
from app.services.persistence import backup_embedded_postgres_if_configured
from app.services.reasoning_precision import ReasoningCoreOrchestrator


HORIZONS = (1, 3, 7, 14, 30)
QUALITY_VERSION = "blum-reasoning-quality-v0.1"
TRAINING_SCHEMA_VERSION = "blum-financial-thesis-jsonl-v0.1"
DISCLAIMER = (
    "Blum Financial Model infrastructure stores and evaluates reasoning quality. "
    "It does not provide financial advice, does not execute trades and does not train a model automatically."
)


def model_status(db: Session) -> dict:
    return {
        "name": "Blum Financial Model",
        "purpose": "Proprietary financial reasoning dataset, memory and training infrastructure.",
        "generated_at": datetime.utcnow().isoformat(),
        "phase": "foundation",
        "counts": {
            "knowledge_records": count(db, BlumKnowledgeRecord.id),
            "thesis_outcomes": count(db, BlumThesisOutcome.id),
            "reasoning_memories": count(db, BlumReasoningMemory.id),
            "training_examples": count(db, BlumTrainingExample.id),
            "quality_scores": count(db, BlumThesisQualityScore.id),
            "self_critiques": count(db, BlumSelfCritique.id),
            "narrative_memories": count(db, BlumNarrativeMemory.id),
            "regime_memories": count(db, BlumRegimeMemory.id),
            "thesis_lifecycle_events": count(db, ThesisLifecycleEvent.id),
            "model_reliability_rows": count(db, ModelReliabilityMatrix.id),
            "confidence_calibration_buckets": count(db, ConfidenceCalibrationBucket.id),
            "meta_learning_events": count(db, MetaLearningEvent.id),
            "thesis_survival_metrics": count(db, ThesisSurvivalMetric.id),
            "thesis_conviction_history": count(db, ThesisConvictionHistory.id),
            "model_reliability_by_regime": count(db, ModelReliabilityByRegime.id),
            "thesis_competitions": count(db, ThesisCompetition.id),
            "engine_votes": count(db, EngineVote.id),
            "training_example_quality_scores": count(db, TrainingExampleQualityScore.id),
            "benchmark_relative_outcomes": count(db, BenchmarkRelativeOutcome.id),
            "graph_nodes": count(db, BlumKnowledgeGraphNode.id),
            "graph_edges": count(db, BlumKnowledgeGraphEdge.id),
            "dataset_exports": count(db, BlumDatasetExport.id),
            "training_jobs": count(db, BlumModelTrainingJob.id),
        },
        "training_readiness": training_readiness(db),
        "supported_model_families": ["Qwen", "Llama", "Mistral"],
        "supported_training_methods": ["LoRA", "full_fine_tuning", "DPO", "preference_learning"],
        "primary_asset": "Accumulated Blum reasoning, not raw market data.",
        "disclaimer": DISCLAIMER,
    }


def run_model_learning_cycle(db: Session, limit: int = 120) -> dict:
    signals = db.scalars(select(SignalSnapshot).order_by(desc(SignalSnapshot.created_at)).limit(limit)).all()
    skipped = 0
    before_count = count(db, BlumKnowledgeRecord.id)
    for signal in signals:
        asset = signal.asset or db.get(Asset, signal.asset_id)
        if asset is None:
            skipped += 1
            continue
        capture_signal_reasoning(db, signal, asset)
    db.flush()
    captured = max(0, count(db, BlumKnowledgeRecord.id) - before_count)
    outcome_result = evaluate_thesis_outcomes(db, limit=limit)
    dataset_result = build_training_dataset(db, limit=limit, min_quality=55.0)
    reasoning_core_result = ReasoningCoreOrchestrator().run(db, limit=limit, commit=False)
    event = LearningEvent(
        event_type="blum_model_autonomous_cycle",
        severity="Info",
        title="Blum Financial Model autonomous cycle completed",
        description="Captured latest reasoning, evaluated matured thesis outcomes, refreshed training examples and updated reasoning calibration.",
        payload={
            "signals_seen": len(signals),
            "knowledge_records_created": captured,
            "signals_skipped": skipped,
            "outcomes": outcome_result,
            "dataset": dataset_result,
            "reasoning_core": reasoning_core_result,
        },
    )
    db.add(event)
    db.commit()
    backup_result = backup_embedded_postgres_if_configured(reason="blum_model_autonomous_cycle")
    return {
        "status": "ok",
        "signals_seen": len(signals),
        "knowledge_records_created": captured,
        "signals_skipped": skipped,
        "outcomes": outcome_result,
        "dataset": dataset_result,
        "reasoning_core": reasoning_core_result,
        "learning_event_id": event.id,
        "persistence_backup": backup_result,
        "disclaimer": DISCLAIMER,
    }


def capture_latest_asset_reasoning(db: Session, asset: Asset, source_type: str = "manual_capture") -> dict:
    signal = db.scalar(
        select(SignalSnapshot)
        .where(SignalSnapshot.asset_id == asset.id)
        .order_by(desc(SignalSnapshot.created_at))
        .limit(1)
    )
    insight = db.scalar(
        select(AIInsight)
        .where(AIInsight.asset_id == asset.id)
        .order_by(desc(AIInsight.created_at))
        .limit(1)
    )
    record = capture_asset_reasoning(db, asset=asset, signal=signal, ai_insight=insight, source_type=source_type)
    db.commit()
    return serialize_record(record)


def capture_signal_reasoning(db: Session, signal: SignalSnapshot, asset: Asset) -> BlumKnowledgeRecord:
    return capture_asset_reasoning(db, asset=asset, signal=signal, source_type="signal_snapshot")


def capture_ai_insight_reasoning(db: Session, asset: Asset, insight_model: AIInsight, signal: SignalSnapshot | None = None) -> BlumKnowledgeRecord:
    return capture_asset_reasoning(db, asset=asset, signal=signal, ai_insight=insight_model, source_type=insight_model.insight_type or "ai_insight")


def capture_asset_reasoning(
    db: Session,
    *,
    asset: Asset,
    signal: SignalSnapshot | None = None,
    ai_insight: AIInsight | None = None,
    source_type: str = "asset_analysis",
) -> BlumKnowledgeRecord:
    thesis = extract_thesis(asset, signal, ai_insight)
    market_context = build_market_context(signal, thesis)
    asset_context = build_asset_context(asset, signal)
    reasoning = build_reasoning_packet(thesis, signal, ai_insight)
    horizons = build_prediction_horizons(reasoning, signal)
    quality = evaluate_thesis_quality(reasoning, market_context, asset_context)
    critique = build_self_critique(reasoning, market_context, quality)
    training_sample = build_training_sample(market_context, asset_context, reasoning, critique)
    reasoning_hash = hash_reasoning(asset, signal, ai_insight, source_type, reasoning)

    existing = db.scalar(select(BlumKnowledgeRecord).where(BlumKnowledgeRecord.reasoning_hash == reasoning_hash))
    if existing is not None:
        return existing

    record = BlumKnowledgeRecord(
        asset_id=asset.id,
        signal_id=signal.id if signal is not None else None,
        ai_insight_id=ai_insight.id if ai_insight is not None else None,
        ticker=asset.ticker,
        sector=asset.sector or "Unknown",
        industry=asset.industry or "",
        source_type=source_type,
        reasoning_hash=reasoning_hash,
        market_regime=market_context["market_regime"],
        volatility_regime=market_context["volatility_regime"],
        risk_sentiment=market_context["risk_sentiment"],
        confidence=float(reasoning.get("confidence", 0.0) or 0.0),
        conviction_score=float(reasoning.get("conviction_score", 0.0) or 0.0),
        market_context=safe_json(market_context),
        asset_context=safe_json(asset_context),
        blum_reasoning=safe_json(reasoning),
        prediction_horizons=safe_json(horizons),
        quality_scores=safe_json(quality),
        self_critique=safe_json(critique),
        training_sample=safe_json(training_sample),
    )
    db.add(record)
    db.flush()
    persist_quality(db, record, quality)
    persist_self_critique(db, record, critique)
    persist_reasoning_memory(db, record, training_sample)
    persist_training_example(db, record, training_sample, quality)
    persist_narrative_memory(db, record)
    persist_regime_memory(db, record)
    persist_knowledge_graph(db, record)
    db.add(
        LearningEvent(
            event_type="blum_financial_model_capture",
            severity="Info",
            title=f"Captured proprietary reasoning for {asset.ticker}",
            description="Blum stored an evidence-bound financial thesis as proprietary reasoning memory and training data.",
            payload={"knowledge_record_id": record.id, "ticker": asset.ticker, "source_type": source_type, "quality": quality},
        )
    )
    return record


def evaluate_thesis_outcomes(db: Session, limit: int = 250) -> dict:
    records = db.scalars(select(BlumKnowledgeRecord).order_by(desc(BlumKnowledgeRecord.created_at)).limit(limit)).all()
    created = 0
    updated = 0
    matured = 0
    pending = 0
    for record in records:
        for horizon in HORIZONS:
            outcome = db.scalar(
                select(BlumThesisOutcome).where(
                    and_(BlumThesisOutcome.knowledge_record_id == record.id, BlumThesisOutcome.horizon_days == horizon)
                )
            )
            is_new = outcome is None
            if outcome is None:
                outcome = BlumThesisOutcome(
                    knowledge_record_id=record.id,
                    asset_id=record.asset_id,
                    ticker=record.ticker,
                    horizon_days=horizon,
                )
                db.add(outcome)
            result = evaluate_record_horizon(db, record, horizon)
            apply_outcome(outcome, record, result)
            if result["outcome"] == "inconclusive":
                pending += 1
            else:
                matured += 1
            created += 1 if is_new else 0
            updated += 0 if is_new else 1
    refresh_memory_outcomes(db, records)
    db.add(
        LearningEvent(
            event_type="blum_financial_model_outcome_evaluation",
            severity="Info",
            title="Blum Financial Model outcome evaluation completed",
            description="Evaluated stored financial theses across 1D, 3D, 7D, 14D and 30D horizons.",
            payload={"records_seen": len(records), "created": created, "updated": updated, "matured": matured, "pending": pending},
        )
    )
    db.commit()
    return {"status": "ok", "records_seen": len(records), "created": created, "updated": updated, "matured": matured, "pending": pending, "disclaimer": DISCLAIMER}


def semantic_reasoning_search(db: Session, query: str, limit: int = 12) -> list[dict]:
    memories = db.scalars(select(BlumReasoningMemory).order_by(desc(BlumReasoningMemory.created_at)).limit(800)).all()
    vectors = [memory.embedding.get("values", []) for memory in memories]
    scores = embedding_model().similarity(query, vectors)
    ranked = sorted(zip(memories, scores), key=lambda item: item[1], reverse=True)[:limit]
    return [
        {
            "score": round(float(score), 4),
            "memory": serialize_memory(memory),
        }
        for memory, score in ranked
    ]


def build_training_dataset(db: Session, limit: int = 500, min_quality: float = 55.0) -> dict:
    records = db.scalars(select(BlumKnowledgeRecord).order_by(desc(BlumKnowledgeRecord.created_at)).limit(limit)).all()
    created = 0
    updated = 0
    ready = 0
    for record in records:
        quality = float((record.quality_scores or {}).get("overall_score", 0.0) or 0.0)
        sample = record.training_sample or build_training_sample(record.market_context, record.asset_context, record.blum_reasoning, record.self_critique)
        example = db.scalar(
            select(BlumTrainingExample).where(
                and_(BlumTrainingExample.knowledge_record_id == record.id, BlumTrainingExample.task_type == "financial_thesis_generation")
            )
        )
        is_ready = quality >= min_quality
        if example is None:
            example = BlumTrainingExample(knowledge_record_id=record.id, task_type="financial_thesis_generation")
            db.add(example)
            created += 1
        else:
            updated += 1
        apply_training_example(example, sample, record.quality_scores or {}, is_ready)
        ready += 1 if is_ready else 0
    db.commit()
    return {"status": "ok", "records_seen": len(records), "examples_created": created, "examples_updated": updated, "export_ready": ready, "min_quality": min_quality}


def export_training_jsonl(db: Session, limit: int = 1000, min_quality: float = 60.0, export_name: str | None = None) -> dict:
    build_training_dataset(db, limit=limit, min_quality=min_quality)
    examples = db.scalars(
        select(BlumTrainingExample)
        .where(BlumTrainingExample.export_ready.is_(True))
        .order_by(desc(BlumTrainingExample.created_at))
        .limit(limit)
    ).all()
    export_dir = get_settings().training_export_dir
    os.makedirs(export_dir, exist_ok=True)
    name = export_name or f"blum_financial_thesis_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jsonl"
    file_path = os.path.join(export_dir, name)
    with open(file_path, "w", encoding="utf-8") as handle:
        for example in examples:
            row = {
                "schema_version": TRAINING_SCHEMA_VERSION,
                "task_type": example.task_type,
                "base_model_family": example.base_model_family,
                "input": example.input_payload,
                "output": example.output_payload,
                "messages": example.messages.get("items", []),
                "quality_scores": example.quality_scores,
                "preference": example.preference_payload,
            }
            handle.write(json.dumps(safe_json(row), ensure_ascii=False) + "\n")
            example.exported_at = datetime.utcnow()
    export = BlumDatasetExport(
        export_name=name,
        format="jsonl",
        record_count=len(examples),
        file_path=file_path,
        filters={"limit": limit, "min_quality": min_quality, "export_ready": True},
        status="created",
        payload_summary={
            "schema_version": TRAINING_SCHEMA_VERSION,
            "supported_training": ["sft", "lora", "dpo", "preference_learning"],
            "target_repository": get_settings().blum_model_repository,
        },
    )
    db.add(export)
    db.commit()
    return {
        "status": "ok",
        "export_id": export.id,
        "export_name": name,
        "format": "jsonl",
        "record_count": len(examples),
        "file_path": file_path,
        "target_repository": get_settings().blum_model_repository,
    }


def training_manifest() -> dict:
    settings = get_settings()
    return {
        "project": "Blum Analyst",
        "target_repository": settings.blum_model_repository,
        "objective": "Train future models to reason better about markets, not to predict stock prices.",
        "supported_base_models": {
            "qwen": ["Qwen/Qwen2.5-0.5B-Instruct", "Qwen/Qwen2.5-1.5B-Instruct", "Qwen/Qwen2.5-7B-Instruct"],
            "llama": ["meta-llama/Llama-3.2-1B-Instruct", "meta-llama/Llama-3.1-8B-Instruct"],
            "mistral": ["mistralai/Mistral-7B-Instruct-v0.3"],
        },
        "supported_methods": {
            "lora": {"purpose": "Low-cost supervised adaptation on Blum thesis examples.", "status": "infrastructure_ready"},
            "full_fine_tuning": {"purpose": "Future larger-scale training after dataset quality and size are sufficient.", "status": "planned"},
            "dpo": {"purpose": "Preference learning from analyst/skeptic/final-view comparisons.", "status": "infrastructure_ready"},
            "preference_learning": {"purpose": "Rank stronger thesis reasoning over shallow or overconfident alternatives.", "status": "infrastructure_ready"},
        },
        "dataset_schema": TRAINING_SCHEMA_VERSION,
        "quality_gate": {
            "minimum_default_quality": 60,
            "required_dimensions": [
                "reasoning_depth",
                "consistency",
                "contradiction_handling",
                "confidence_calibration",
                "historical_alignment",
                "narrative_quality",
                "explainability_quality",
            ],
        },
        "governance": [
            "No training is launched automatically from the Space.",
            "No trading action is produced.",
            "Low-quality or insufficient-evidence theses remain excluded from export unless explicitly requested.",
            "The proprietary asset is Blum reasoning memory, not raw market data.",
        ],
    }


def list_knowledge_records(db: Session, ticker: str | None = None, limit: int = 100) -> list[dict]:
    query = select(BlumKnowledgeRecord).order_by(desc(BlumKnowledgeRecord.created_at))
    if ticker:
        query = query.where(BlumKnowledgeRecord.ticker == ticker.upper())
    return [serialize_record(row) for row in db.scalars(query.limit(limit)).all()]


def get_knowledge_record(db: Session, record_id: int) -> dict | None:
    record = db.get(BlumKnowledgeRecord, record_id)
    if record is None:
        return None
    outcomes = db.scalars(select(BlumThesisOutcome).where(BlumThesisOutcome.knowledge_record_id == record.id).order_by(BlumThesisOutcome.horizon_days)).all()
    return {**serialize_record(record), "outcomes": [serialize_outcome(row) for row in outcomes]}


def quality_overview(db: Session, limit: int = 80) -> dict:
    rows = db.scalars(select(BlumThesisQualityScore).order_by(desc(BlumThesisQualityScore.created_at)).limit(limit)).all()
    values = [float(row.overall_score) for row in rows]
    return {
        "average_quality": round(mean(values), 2) if values else None,
        "sample_size": len(rows),
        "rows": [serialize_quality(row) for row in rows],
        "dimensions": ["reasoning_depth", "consistency", "contradiction_handling", "confidence_calibration", "historical_alignment", "narrative_quality", "explainability_quality"],
    }


def self_critique_for_record(db: Session, record_id: int) -> dict | None:
    critique = db.scalar(select(BlumSelfCritique).where(BlumSelfCritique.knowledge_record_id == record_id))
    return serialize_self_critique(critique) if critique else None


def narrative_memory(db: Session, limit: int = 80) -> list[dict]:
    rows = db.scalars(select(BlumNarrativeMemory).order_by(desc(BlumNarrativeMemory.updated_at)).limit(limit)).all()
    return [serialize_narrative(row) for row in rows]


def regime_memory(db: Session, limit: int = 80) -> list[dict]:
    rows = db.scalars(select(BlumRegimeMemory).order_by(desc(BlumRegimeMemory.updated_at)).limit(limit)).all()
    return [serialize_regime(row) for row in rows]


def graph_snapshot(db: Session, limit: int = 160) -> dict:
    nodes = db.scalars(select(BlumKnowledgeGraphNode).order_by(desc(BlumKnowledgeGraphNode.updated_at)).limit(limit)).all()
    node_ids = [node.id for node in nodes]
    edges = []
    if node_ids:
        edges = db.scalars(
            select(BlumKnowledgeGraphEdge)
            .where(BlumKnowledgeGraphEdge.source_node_id.in_(node_ids))
            .order_by(desc(BlumKnowledgeGraphEdge.updated_at))
            .limit(limit * 2)
        ).all()
    return {"nodes": [serialize_node(row) for row in nodes], "edges": [serialize_edge(row) for row in edges]}


def create_training_job_plan(
    db: Session,
    *,
    job_name: str,
    model_family: str,
    base_model: str,
    method: str,
    dataset_export_id: int | None = None,
    training_config: dict | None = None,
) -> dict:
    job = BlumModelTrainingJob(
        job_name=job_name,
        model_family=model_family,
        base_model=base_model,
        method=method,
        dataset_export_id=dataset_export_id,
        status="planned",
        training_config=training_config or default_training_config(model_family, base_model, method),
        metrics={},
    )
    db.add(job)
    db.commit()
    return {
        "status": "planned",
        "job_id": job.id,
        "job_name": job.job_name,
        "governance": "This creates a training plan only. It does not start fine-tuning inside the Space.",
    }


def extract_thesis(asset: Asset, signal: SignalSnapshot | None, ai_insight: AIInsight | None) -> dict:
    if ai_insight and isinstance(ai_insight.structured_output, dict) and ai_insight.structured_output.get("thesis"):
        return ai_insight.structured_output["thesis"]
    if signal and isinstance(signal.narrative_summary, dict) and signal.narrative_summary.get("thesis"):
        return signal.narrative_summary["thesis"]
    signal_payload = signal_to_dict(signal, asset) if signal else {
        "classification": "Insufficient Evidence",
        "blum_score": 0,
        "risk_level": "Not Rated",
        "time_horizon": "Not Rated",
        "score_breakdown": {},
        "confidence_score": 0,
        "asset": asset_to_dict(asset),
    }
    return build_asset_thesis(
        asset=asset,
        signal=signal_payload,
        technical=(signal.technical_summary if signal else {}) or {},
        narrative=(signal.narrative_summary if signal else {}) or {},
        related_news=[],
        market_context={},
        historical_similarity={},
        accuracy={},
    )


def build_market_context(signal: SignalSnapshot | None, thesis: dict) -> dict:
    context = thesis.get("market_context", {}) or {}
    technical = (signal.technical_summary or {}) if signal else {}
    ts = technical.get("time_series", {}) if isinstance(technical.get("time_series"), dict) else {}
    regime = context.get("regime") or "Sideways"
    volatility_regime = ts.get("regime") or volatility_label(technical)
    return {
        "timestamp": iso(signal.created_at if signal else datetime.utcnow()),
        "market_regime": regime,
        "volatility_regime": volatility_regime,
        "sector_performance": {"relative_strength": value_from(signal.score_breakdown if signal else {}, "sector_score")},
        "macro_environment": context.get("macro_environment", {}),
        "market_breadth": context.get("market_breadth", {}),
        "risk_sentiment": risk_sentiment(signal, regime),
        "signal_regime_adjustment": context.get("signal_regime_adjustment"),
    }


def build_asset_context(asset: Asset, signal: SignalSnapshot | None) -> dict:
    technical = (signal.technical_summary or {}) if signal else {}
    narrative = (signal.narrative_summary or {}) if signal else {}
    breakdown = (signal.score_breakdown or {}) if signal else {}
    return {
        "ticker": asset.ticker,
        "name": asset.name,
        "sector": asset.sector,
        "industry": asset.industry,
        "country": asset.country,
        "asset_type": asset.asset_type,
        "market_cap": None,
        "price_action": {
            "perf_1d": technical.get("perf_1d"),
            "perf_5d": technical.get("perf_5d"),
            "perf_1m": technical.get("perf_1m"),
            "perf_3m": technical.get("perf_3m"),
            "drawdown": technical.get("recent_drawdown"),
        },
        "volume_profile": {
            "relative_volume": technical.get("relative_volume"),
            "volume_spike": technical.get("volume_spike"),
            "volume_score": breakdown.get("volume_score"),
        },
        "technical_indicators": technical,
        "sentiment_indicators": {
            "sentiment_7d": narrative.get("sentiment_7d"),
            "sentiment_30d": narrative.get("sentiment_30d"),
            "sentiment_score": breakdown.get("sentiment_score"),
        },
        "news_indicators": {
            "news_count_7d": narrative.get("news_count_7d"),
            "news_count_30d": narrative.get("news_count_30d"),
            "narrative_intensity": narrative.get("narrative_intensity"),
            "semantic_trend_score": narrative.get("semantic_trend_score"),
        },
    }


def build_reasoning_packet(thesis: dict, signal: SignalSnapshot | None, ai_insight: AIInsight | None) -> dict:
    return {
        "executive_thesis": thesis.get("executive_thesis") or thesis.get("final_blum_view") or "",
        "why_now": thesis.get("what_is_happening") or thesis.get("why_it_may_be_happening") or "",
        "supporting_evidence": thesis.get("supporting_evidence", []),
        "contradicting_evidence": thesis.get("contradicting_evidence", []),
        "risks": thesis.get("risks", []),
        "invalidation_conditions": thesis.get("invalidation_conditions", []),
        "confirmation_conditions": thesis.get("confirmation_conditions", []),
        "narrative_analysis": thesis.get("narrative_analysis", {}),
        "causal_reasoning": thesis.get("causal_reasoning", {}),
        "historical_similarity": thesis.get("historical_similarity", {}),
        "what_the_market_may_be_missing": thesis.get("what_the_market_may_be_missing", []),
        "confidence": float(getattr(signal, "confidence_score", 0.0) or 0.0),
        "conviction_score": float(thesis.get("conviction_score") or (thesis.get("conviction") or {}).get("score") or 0.0),
        "classification": getattr(signal, "classification", thesis.get("classification", "Research Thesis")) if signal else "Research Thesis",
        "final_view": thesis.get("final_blum_view") or "",
        "source_model": getattr(ai_insight, "model_name", None),
        "intellectual_honesty": thesis.get("intellectual_honesty", []),
    }


def build_prediction_horizons(reasoning: dict, signal: SignalSnapshot | None) -> dict:
    expected_direction = "downside_risk_review" if getattr(signal, "classification", "") == "Avoid / Too Risky" else "up_or_resilient"
    return {
        "objective": "Evaluate whether the thesis reasoning was supported by subsequent market behavior; not a price forecast.",
        "expected_direction": expected_direction,
        "horizons": [{"days": horizon, "status": "pending"} for horizon in HORIZONS],
    }


def evaluate_thesis_quality(reasoning: dict, market_context: dict, asset_context: dict) -> dict:
    supporting = listify(reasoning.get("supporting_evidence"))
    contradicting = listify(reasoning.get("contradicting_evidence"))
    risks = listify(reasoning.get("risks"))
    invalidation = listify(reasoning.get("invalidation_conditions"))
    missing = listify(reasoning.get("what_the_market_may_be_missing"))
    narrative = reasoning.get("narrative_analysis") or {}
    historical = reasoning.get("historical_similarity") or {}
    reasoning_depth = clamp(len(supporting) * 12 + len(contradicting) * 14 + len(risks) * 10 + len(invalidation) * 10 + len(missing) * 8)
    consistency = clamp(70 + (10 if reasoning.get("final_view") else -15) - max(0, len(contradicting) - 3) * 5)
    contradiction_handling = clamp(45 + len(contradicting) * 14 + (15 if invalidation else 0))
    confidence = float(reasoning.get("confidence") or 0.0)
    conviction = float(reasoning.get("conviction_score") or 0.0)
    confidence_calibration = clamp(100 - abs(confidence - conviction) * 0.6) if confidence or conviction else 50
    historical_alignment = 72 if historical.get("similar_cases_found") else 48
    narrative_quality = clamp(35 + (20 if narrative.get("lifecycle") else 0) + value_from(narrative, "intensity") * 0.25 + min(20, len(narrative.get("most_exposed_assets", [])) * 4))
    explainability_quality = clamp(30 + len(supporting) * 10 + len(contradicting) * 9 + len(risks) * 8 + (15 if reasoning.get("causal_reasoning") else 0))
    overall = mean_safe([reasoning_depth, consistency, contradiction_handling, confidence_calibration, historical_alignment, narrative_quality, explainability_quality])
    return {
        "evaluator_version": QUALITY_VERSION,
        "reasoning_depth": round(reasoning_depth, 1),
        "consistency": round(consistency, 1),
        "contradiction_handling": round(contradiction_handling, 1),
        "confidence_calibration": round(confidence_calibration, 1),
        "historical_alignment": round(historical_alignment, 1),
        "narrative_quality": round(narrative_quality, 1),
        "explainability_quality": round(explainability_quality, 1),
        "overall_score": round(overall, 1),
        "quality_gate": "export_ready" if overall >= 60 else "needs_review",
        "reducer_notes": quality_reducers(reasoning, market_context, asset_context),
    }


def build_self_critique(reasoning: dict, market_context: dict, quality: dict) -> dict:
    return {
        "analyst_view": {
            "main_thesis": reasoning.get("executive_thesis", ""),
            "why_it_matters": reasoning.get("why_now", ""),
            "best_evidence": listify(reasoning.get("supporting_evidence"))[:4],
        },
        "skeptic_view": {
            "why_thesis_may_fail": listify(reasoning.get("contradicting_evidence"))[:5] or ["No explicit contradiction is stored; this itself should be treated cautiously."],
            "risk_factors": listify(reasoning.get("risks"))[:5],
            "missing_information": listify(reasoning.get("intellectual_honesty"))[:5],
        },
        "historical_view": {
            "similarity": reasoning.get("historical_similarity", {}),
            "interpretation": "Historical similarity is used as context for reasoning quality, not as a forecast.",
        },
        "final_view": {
            "balanced_conclusion": reasoning.get("final_view") or reasoning.get("executive_thesis", ""),
            "market_regime": market_context.get("market_regime"),
            "quality_score": quality.get("overall_score"),
            "confidence_note": "Confidence and conviction are thesis-quality measures, not certainty.",
        },
    }


def build_training_sample(market_context: dict, asset_context: dict, reasoning: dict, critique: dict) -> dict:
    input_payload = {
        "market_context": market_context,
        "asset_context": asset_context,
        "news": asset_context.get("news_indicators", {}),
        "technicals": asset_context.get("technical_indicators", {}),
        "sentiment": asset_context.get("sentiment_indicators", {}),
        "sector_data": {"sector": asset_context.get("sector"), "industry": asset_context.get("industry")},
        "historical_memory": reasoning.get("historical_similarity", {}),
    }
    output_payload = {
        "executive_thesis": reasoning.get("executive_thesis", ""),
        "bull_case": listify(reasoning.get("supporting_evidence")),
        "bear_case": listify(reasoning.get("contradicting_evidence")),
        "supporting_evidence": listify(reasoning.get("supporting_evidence")),
        "contradicting_evidence": listify(reasoning.get("contradicting_evidence")),
        "risk_assessment": listify(reasoning.get("risks")),
        "what_the_market_may_be_missing": listify(reasoning.get("what_the_market_may_be_missing")),
        "invalidation_conditions": listify(reasoning.get("invalidation_conditions")),
        "final_view": reasoning.get("final_view", ""),
        "self_critique": critique,
    }
    user_payload = {
        "instruction": "Generate an evidence-bound financial thesis. Do not give buy or sell advice.",
        "input": input_payload,
    }
    return {
        "schema_version": TRAINING_SCHEMA_VERSION,
        "input": input_payload,
        "output": output_payload,
        "messages": {
            "items": [
                {"role": "system", "content": "You are Blum Analyst, a financial reasoning model. You explain, critique and contextualize. You do not give financial advice."},
                {"role": "user", "content": json.dumps(safe_json(user_payload), ensure_ascii=False)},
                {"role": "assistant", "content": json.dumps(safe_json(output_payload), ensure_ascii=False)},
            ]
        },
        "preference": {
            "chosen": output_payload,
            "rejected": {
                "reason": "Overconfident shallow answer excluded from Blum training targets.",
                "content": "Momentum is high and sentiment is positive, so this is interesting.",
            },
        },
    }


def persist_quality(db: Session, record: BlumKnowledgeRecord, quality: dict) -> None:
    row = BlumThesisQualityScore(
        knowledge_record_id=record.id,
        reasoning_depth=quality["reasoning_depth"],
        consistency=quality["consistency"],
        contradiction_handling=quality["contradiction_handling"],
        confidence_calibration=quality["confidence_calibration"],
        historical_alignment=quality["historical_alignment"],
        narrative_quality=quality["narrative_quality"],
        explainability_quality=quality["explainability_quality"],
        overall_score=quality["overall_score"],
        evaluator_version=quality["evaluator_version"],
        quality_payload=quality,
    )
    db.add(row)


def persist_self_critique(db: Session, record: BlumKnowledgeRecord, critique: dict) -> None:
    db.add(
        BlumSelfCritique(
            knowledge_record_id=record.id,
            analyst_view=critique["analyst_view"],
            skeptic_view=critique["skeptic_view"],
            historical_view=critique["historical_view"],
            final_view=critique["final_view"],
            critique_payload=critique,
        )
    )


def persist_reasoning_memory(db: Session, record: BlumKnowledgeRecord, sample: dict) -> None:
    text = memory_text(record)
    embedder = embedding_model()
    db.add(
        BlumReasoningMemory(
            knowledge_record_id=record.id,
            asset_id=record.asset_id,
            ticker=record.ticker,
            memory_type="asset_thesis",
            embedding_model=embedder.model_name,
            embedding={"values": embedder.embed_text(text)},
            memory_text=text,
            metadata_payload={
                "market_regime": record.market_regime,
                "conviction_score": record.conviction_score,
                "quality_score": record.quality_scores.get("overall_score"),
                "training_schema": sample.get("schema_version"),
            },
            outcome_label="pending",
            quality_score=float(record.quality_scores.get("overall_score", 0.0)),
        )
    )


def persist_training_example(db: Session, record: BlumKnowledgeRecord, sample: dict, quality: dict) -> None:
    example = BlumTrainingExample(
        knowledge_record_id=record.id,
        task_type="financial_thesis_generation",
        dataset_split=dataset_split(record.id),
        base_model_family="qwen_llama_mistral",
    )
    apply_training_example(example, sample, quality, quality.get("overall_score", 0) >= 60)
    db.add(example)


def persist_narrative_memory(db: Session, record: BlumKnowledgeRecord) -> None:
    narrative = (record.blum_reasoning or {}).get("narrative_analysis") or {}
    labels = narrative.get("most_exposed_assets") or [record.ticker]
    name = narrative.get("theme") or narrative.get("label") or infer_narrative_name(record)
    db.add(
        BlumNarrativeMemory(
            narrative=name,
            lifecycle_stage=narrative.get("lifecycle", "Emerging"),
            intensity=float(narrative.get("intensity") or 0.0),
            velocity=float(narrative.get("growth_velocity") or 0.0),
            saturation=float(narrative.get("saturation") or 0.0),
            crowding=float(narrative.get("crowding") or 0.0),
            linked_assets={"tickers": labels},
            sectors={"items": [record.sector]},
            outcome_summary={"status": "pending", "knowledge_record_id": record.id},
        )
    )


def persist_regime_memory(db: Session, record: BlumKnowledgeRecord) -> None:
    db.add(
        BlumRegimeMemory(
            market_regime=record.market_regime,
            volatility_regime=record.volatility_regime,
            liquidity_regime="Unknown",
            macro_context=record.market_context.get("macro_environment", {}),
            reasoning_patterns={
                "classification": record.blum_reasoning.get("classification"),
                "conviction_score": record.conviction_score,
                "contradictions": record.blum_reasoning.get("contradicting_evidence", []),
            },
            outcome_summary={"status": "pending", "knowledge_record_id": record.id},
            sample_count=1,
        )
    )


def persist_knowledge_graph(db: Session, record: BlumKnowledgeRecord) -> None:
    asset = upsert_node(db, "company_or_etf", record.ticker, {"ticker": record.ticker, "sector": record.sector, "industry": record.industry})
    sector = upsert_node(db, "sector", record.sector or "Unknown", {"sector": record.sector})
    regime = upsert_node(db, "market_regime", record.market_regime, {"volatility_regime": record.volatility_regime})
    add_edge(db, asset, sector, "belongs_to_sector", 1.0, {"knowledge_record_id": record.id})
    add_edge(db, asset, regime, "analyzed_under_regime", 1.0, {"knowledge_record_id": record.id})
    narrative = record.blum_reasoning.get("narrative_analysis", {}) if record.blum_reasoning else {}
    narrative_name = narrative.get("theme") or narrative.get("label") or infer_narrative_name(record)
    narrative_node = upsert_node(db, "narrative", narrative_name, narrative)
    add_edge(db, asset, narrative_node, "exposed_to_narrative", max(0.1, float(narrative.get("intensity") or 50) / 100), {"knowledge_record_id": record.id})
    add_edge(db, narrative_node, sector, "affects_sector", 0.6, {"knowledge_record_id": record.id})


def evaluate_record_horizon(db: Session, record: BlumKnowledgeRecord, horizon_days: int) -> dict:
    created_day = as_date(record.created_at)
    target_day = created_day + timedelta(days=horizon_days)
    entry = price_on_or_before(db, record.asset_id, created_day)
    target = price_on_or_after(db, record.asset_id, target_day)
    expected = (record.prediction_horizons or {}).get("expected_direction", "up_or_resilient")
    base = {
        "expected_direction": expected,
        "target_date": target_day.isoformat(),
        "observed_data": {"price_source": "stored_price_history", "knowledge_record_id": record.id},
    }
    if entry is None or target is None or date.today() < target_day:
        return {
            **base,
            "price_at_thesis": entry.close if entry is not None else None,
            "price_after_horizon": target.close if target is not None else None,
            "realized_return": None,
            "max_drawdown": None,
            "max_upside": None,
            "realized_volatility": None,
            "outcome": "inconclusive",
            "success": None,
            "reason": "Horizon has not matured or stored OHLCV rows are unavailable.",
        }
    window = price_window(db, record.asset_id, entry.date, target.date)
    realized = pct(float(entry.close), float(target.close))
    drawdown = pct(float(entry.close), min(float(row.low or row.close) for row in window)) if window else None
    upside = pct(float(entry.close), max(float(row.high or row.close) for row in window)) if window else None
    volatility = realized_volatility(window)
    outcome = classify_outcome(realized, expected)
    return {
        **base,
        "price_at_thesis": round(float(entry.close), 4),
        "price_after_horizon": round(float(target.close), 4),
        "realized_return": realized,
        "max_drawdown": drawdown,
        "max_upside": upside,
        "realized_volatility": volatility,
        "outcome": outcome,
        "success": outcome == "correct",
        "reason": f"{horizon_days}D realized return of {realized:.2f}% produced outcome {outcome}.",
    }


def apply_outcome(outcome: BlumThesisOutcome, record: BlumKnowledgeRecord, result: dict) -> None:
    outcome.asset_id = record.asset_id
    outcome.ticker = record.ticker
    outcome.expected_direction = result["expected_direction"]
    outcome.price_at_thesis = result.get("price_at_thesis")
    outcome.price_after_horizon = result.get("price_after_horizon")
    outcome.realized_return = result.get("realized_return")
    outcome.max_drawdown = result.get("max_drawdown")
    outcome.max_upside = result.get("max_upside")
    outcome.realized_volatility = result.get("realized_volatility")
    outcome.outcome = result.get("outcome", "inconclusive")
    outcome.success = result.get("success")
    outcome.outcome_payload = result
    outcome.updated_at = datetime.utcnow()


def refresh_memory_outcomes(db: Session, records: list[BlumKnowledgeRecord]) -> None:
    for record in records:
        outcomes = db.scalars(select(BlumThesisOutcome).where(BlumThesisOutcome.knowledge_record_id == record.id)).all()
        mature = [row for row in outcomes if row.outcome in {"correct", "wrong", "neutral"}]
        label = "pending"
        if mature:
            correct = sum(1 for row in mature if row.outcome == "correct")
            wrong = sum(1 for row in mature if row.outcome == "wrong")
            label = "supported" if correct > wrong else "contradicted" if wrong > correct else "mixed"
        memories = db.scalars(select(BlumReasoningMemory).where(BlumReasoningMemory.knowledge_record_id == record.id)).all()
        for memory in memories:
            memory.outcome_label = label
            memory.metadata_payload = {**(memory.metadata_payload or {}), "outcomes": [serialize_outcome(row) for row in outcomes]}


def apply_training_example(example: BlumTrainingExample, sample: dict, quality: dict, export_ready: bool) -> None:
    example.dataset_split = example.dataset_split or "train"
    example.base_model_family = "qwen_llama_mistral"
    example.input_payload = sample["input"]
    example.output_payload = sample["output"]
    example.messages = sample["messages"]
    example.quality_scores = quality
    example.preference_payload = sample["preference"]
    example.export_ready = bool(export_ready)
    example.updated_at = datetime.utcnow()


def default_training_config(model_family: str, base_model: str, method: str) -> dict:
    return {
        "model_family": model_family,
        "base_model": base_model,
        "method": method,
        "dataset_schema": TRAINING_SCHEMA_VERSION,
        "target_modules": "all-linear for LoRA adapters",
        "learning_rate": 2e-5 if method == "full_fine_tuning" else 1e-4,
        "max_seq_length": 4096,
        "packing": True,
        "train_on": ["executive thesis", "bull case", "bear case", "risk assessment", "self critique", "final view"],
        "not_launched_in_space": True,
    }


@lru_cache(maxsize=1)
def embedding_model() -> EmbeddingModel:
    return EmbeddingModel()


def serialize_record(record: BlumKnowledgeRecord) -> dict:
    return {
        "id": record.id,
        "ticker": record.ticker,
        "sector": record.sector,
        "industry": record.industry,
        "source_type": record.source_type,
        "market_regime": record.market_regime,
        "volatility_regime": record.volatility_regime,
        "risk_sentiment": record.risk_sentiment,
        "confidence": record.confidence,
        "conviction_score": record.conviction_score,
        "market_context": record.market_context,
        "asset_context": record.asset_context,
        "blum_reasoning": record.blum_reasoning,
        "prediction_horizons": record.prediction_horizons,
        "quality_scores": record.quality_scores,
        "self_critique": record.self_critique,
        "training_sample": record.training_sample,
        "created_at": iso(record.created_at),
    }


def serialize_outcome(row: BlumThesisOutcome) -> dict:
    return {
        "id": row.id,
        "knowledge_record_id": row.knowledge_record_id,
        "ticker": row.ticker,
        "horizon_days": row.horizon_days,
        "expected_direction": row.expected_direction,
        "price_at_thesis": row.price_at_thesis,
        "price_after_horizon": row.price_after_horizon,
        "realized_return": row.realized_return,
        "max_drawdown": row.max_drawdown,
        "max_upside": row.max_upside,
        "realized_volatility": row.realized_volatility,
        "outcome": row.outcome,
        "success": row.success,
        "outcome_payload": row.outcome_payload,
        "updated_at": iso(row.updated_at),
    }


def serialize_memory(row: BlumReasoningMemory) -> dict:
    return {
        "id": row.id,
        "knowledge_record_id": row.knowledge_record_id,
        "ticker": row.ticker,
        "memory_type": row.memory_type,
        "memory_text": row.memory_text,
        "metadata_payload": row.metadata_payload,
        "outcome_label": row.outcome_label,
        "quality_score": row.quality_score,
        "created_at": iso(row.created_at),
    }


def serialize_quality(row: BlumThesisQualityScore) -> dict:
    return {
        "id": row.id,
        "knowledge_record_id": row.knowledge_record_id,
        "reasoning_depth": row.reasoning_depth,
        "consistency": row.consistency,
        "contradiction_handling": row.contradiction_handling,
        "confidence_calibration": row.confidence_calibration,
        "historical_alignment": row.historical_alignment,
        "narrative_quality": row.narrative_quality,
        "explainability_quality": row.explainability_quality,
        "overall_score": row.overall_score,
        "quality_payload": row.quality_payload,
        "created_at": iso(row.created_at),
    }


def serialize_self_critique(row: BlumSelfCritique) -> dict:
    return {
        "id": row.id,
        "knowledge_record_id": row.knowledge_record_id,
        "analyst_view": row.analyst_view,
        "skeptic_view": row.skeptic_view,
        "historical_view": row.historical_view,
        "final_view": row.final_view,
        "critique_payload": row.critique_payload,
        "created_at": iso(row.created_at),
    }


def serialize_narrative(row: BlumNarrativeMemory) -> dict:
    return {
        "id": row.id,
        "narrative": row.narrative,
        "lifecycle_stage": row.lifecycle_stage,
        "intensity": row.intensity,
        "velocity": row.velocity,
        "saturation": row.saturation,
        "crowding": row.crowding,
        "linked_assets": row.linked_assets,
        "sectors": row.sectors,
        "outcome_summary": row.outcome_summary,
        "updated_at": iso(row.updated_at),
    }


def serialize_regime(row: BlumRegimeMemory) -> dict:
    return {
        "id": row.id,
        "market_regime": row.market_regime,
        "volatility_regime": row.volatility_regime,
        "liquidity_regime": row.liquidity_regime,
        "macro_context": row.macro_context,
        "reasoning_patterns": row.reasoning_patterns,
        "outcome_summary": row.outcome_summary,
        "sample_count": row.sample_count,
        "updated_at": iso(row.updated_at),
    }


def serialize_node(row: BlumKnowledgeGraphNode) -> dict:
    return {"id": row.id, "node_type": row.node_type, "label": row.label, "canonical_key": row.canonical_key, "properties": row.properties}


def serialize_edge(row: BlumKnowledgeGraphEdge) -> dict:
    return {"id": row.id, "source_node_id": row.source_node_id, "target_node_id": row.target_node_id, "relation_type": row.relation_type, "weight": row.weight, "evidence": row.evidence}


def training_readiness(db: Session) -> dict:
    ready = int(db.scalar(select(func.count(BlumTrainingExample.id)).where(BlumTrainingExample.export_ready.is_(True))) or 0)
    total = count(db, BlumTrainingExample.id)
    return {
        "export_ready_examples": ready,
        "total_examples": total,
        "status": "ready_for_small_lora_experiment" if ready >= 50 else "collecting_reasoning_memory",
        "minimum_recommended_examples": 50,
    }


def upsert_node(db: Session, node_type: str, label: str, properties: dict) -> BlumKnowledgeGraphNode:
    canonical = f"{node_type}:{str(label).strip().lower()}"
    node = db.scalar(select(BlumKnowledgeGraphNode).where(BlumKnowledgeGraphNode.canonical_key == canonical))
    if node is None:
        node = BlumKnowledgeGraphNode(node_type=node_type, label=str(label), canonical_key=canonical, properties=properties, embedding={})
        db.add(node)
        db.flush()
    else:
        node.properties = {**(node.properties or {}), **properties}
        node.updated_at = datetime.utcnow()
    return node


def add_edge(db: Session, source: BlumKnowledgeGraphNode, target: BlumKnowledgeGraphNode, relation_type: str, weight: float, evidence: dict) -> None:
    edge = db.scalar(
        select(BlumKnowledgeGraphEdge).where(
            and_(
                BlumKnowledgeGraphEdge.source_node_id == source.id,
                BlumKnowledgeGraphEdge.target_node_id == target.id,
                BlumKnowledgeGraphEdge.relation_type == relation_type,
            )
        )
    )
    if edge is None:
        db.add(BlumKnowledgeGraphEdge(source_node_id=source.id, target_node_id=target.id, relation_type=relation_type, weight=weight, evidence=evidence))
    else:
        edge.weight = max(float(edge.weight or 0), weight)
        edge.evidence = {**(edge.evidence or {}), **evidence}
        edge.updated_at = datetime.utcnow()


def signal_to_dict(signal: SignalSnapshot, asset: Asset) -> dict:
    return {
        "classification": signal.classification,
        "blum_score": signal.blum_score,
        "risk_level": signal.risk_level,
        "time_horizon": signal.time_horizon,
        "score_breakdown": signal.score_breakdown,
        "confidence_score": signal.confidence_score,
        "asset": asset_to_dict(asset),
    }


def asset_to_dict(asset: Asset) -> dict:
    return {"ticker": asset.ticker, "name": asset.name, "sector": asset.sector, "industry": asset.industry, "asset_type": asset.asset_type, "country": asset.country}


def memory_text(record: BlumKnowledgeRecord) -> str:
    reasoning = record.blum_reasoning or {}
    parts = [
        f"Ticker: {record.ticker}",
        f"Regime: {record.market_regime}",
        f"Executive thesis: {reasoning.get('executive_thesis', '')}",
        f"Supporting evidence: {' | '.join(listify(reasoning.get('supporting_evidence')))}",
        f"Contradicting evidence: {' | '.join(listify(reasoning.get('contradicting_evidence')))}",
        f"Risks: {' | '.join(listify(reasoning.get('risks')))}",
        f"Final view: {reasoning.get('final_view', '')}",
    ]
    return "\n".join(parts)


def hash_reasoning(asset: Asset, signal: SignalSnapshot | None, ai_insight: AIInsight | None, source_type: str, reasoning: dict) -> str:
    payload = {
        "ticker": asset.ticker,
        "signal_id": getattr(signal, "id", None),
        "ai_insight_id": getattr(ai_insight, "id", None),
        "source_type": source_type,
        "executive_thesis": reasoning.get("executive_thesis", ""),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def price_on_or_before(db: Session, asset_id: int | None, target: date):
    if asset_id is None:
        return None
    return db.scalar(select(PriceHistory).where(PriceHistory.asset_id == asset_id, PriceHistory.date <= target).order_by(desc(PriceHistory.date)).limit(1))


def price_on_or_after(db: Session, asset_id: int | None, target: date):
    if asset_id is None:
        return None
    return db.scalar(select(PriceHistory).where(PriceHistory.asset_id == asset_id, PriceHistory.date >= target).order_by(PriceHistory.date).limit(1))


def price_window(db: Session, asset_id: int | None, start: date, end: date) -> list[PriceHistory]:
    if asset_id is None:
        return []
    return db.scalars(select(PriceHistory).where(PriceHistory.asset_id == asset_id, PriceHistory.date >= start, PriceHistory.date <= end).order_by(PriceHistory.date)).all()


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


def realized_volatility(rows: list[PriceHistory]) -> float | None:
    closes = [float(row.close) for row in rows if row.close is not None]
    if len(closes) < 3:
        return None
    returns = [((closes[index] / closes[index - 1]) - 1) * 100 for index in range(1, len(closes)) if closes[index - 1]]
    if len(returns) < 2:
        return None
    return round(stdev(returns), 4)


def quality_reducers(reasoning: dict, market_context: dict, asset_context: dict) -> list[str]:
    reducers = []
    if not listify(reasoning.get("contradicting_evidence")):
        reducers.append("No explicit contradiction was stored; skepticism may be too weak.")
    if not reasoning.get("causal_reasoning"):
        reducers.append("Causal reasoning packet is missing.")
    if not reasoning.get("historical_similarity"):
        reducers.append("Historical comparison is missing or thin.")
    if not asset_context.get("news_indicators", {}).get("news_count_7d"):
        reducers.append("Recent news evidence is thin.")
    return reducers or ["No major quality reducer was detected."]


def infer_narrative_name(record: BlumKnowledgeRecord) -> str:
    sector = record.sector or "Market Structure"
    if "semiconductor" in sector.lower() or record.ticker in {"NVDA", "AMD", "AVGO", "SMH"}:
        return "Semiconductors"
    if "energy" in sector.lower():
        return "Energy"
    if "health" in sector.lower():
        return "Healthcare Innovation"
    if "defense" in sector.lower():
        return "Defense"
    return sector


def volatility_label(technical: dict) -> str:
    vol = value_from(technical, "historical_volatility")
    if vol >= 55:
        return "High Volatility"
    if vol <= 18 and vol > 0:
        return "Low Volatility"
    return "Normal Volatility"


def risk_sentiment(signal: SignalSnapshot | None, regime: str) -> str:
    if signal and signal.risk_level == "High":
        return "High Risk"
    if regime in {"Risk-Off", "Panic"}:
        return "Defensive"
    if regime in {"Bull Expansion", "Recovery"}:
        return "Constructive"
    return "Balanced"


def dataset_split(record_id: int | None) -> str:
    if record_id is None:
        return "train"
    if record_id % 10 == 0:
        return "test"
    if record_id % 10 == 1:
        return "validation"
    return "train"


def count(db: Session, column) -> int:
    return int(db.scalar(select(func.count(column))) or 0)


def pct(start: float, end: float) -> float:
    if not start:
        return 0.0
    return round(((end / start) - 1) * 100, 4)


def value_from(payload: dict | None, key: str, default: float = 0.0) -> float:
    try:
        return float((payload or {}).get(key, default) or default)
    except Exception:
        return default


def mean_safe(values: list[float]) -> float:
    valid = [float(value) for value in values if value is not None]
    return mean(valid) if valid else 0.0


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def listify(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [stringify(item) for item in value if stringify(item)]
    return [stringify(value)] if stringify(value) else []


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        return value.get("explanation") or value.get("reason") or value.get("summary") or json.dumps(safe_json(value), ensure_ascii=False)
    return str(value)


def safe_json(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): safe_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_json(item) for item in value]
    if isinstance(value, tuple):
        return [safe_json(item) for item in value]
    return value


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
