from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analyst.release_contracts import DatasetSplit, ReleaseExample, ReleaseManifest
from app.analyst.release_redaction import sanitize_payload
from app.models import (
    BlumKnowledgeRecord,
    BlumThesisOutcome,
    BlumTrainingExample,
    TrainingExampleQualityScore,
)


BASE_MODEL = "Qwen/Qwen3-4B"
SCHEMA_VERSION = "blum-finance-reasoning-v1"
MATURE_OUTCOMES = {"correct", "wrong", "neutral"}


def build_release_dataset(
    db: Session,
    *,
    source_revision: str,
    output_dir: Path,
    min_score: float = 70.0,
    limit: int = 10_000,
) -> ReleaseManifest:
    rows = list(
        db.execute(
            select(TrainingExampleQualityScore, BlumTrainingExample, BlumKnowledgeRecord)
            .join(
                BlumTrainingExample,
                BlumTrainingExample.id == TrainingExampleQualityScore.training_example_id,
            )
            .join(
                BlumKnowledgeRecord,
                BlumKnowledgeRecord.id == BlumTrainingExample.knowledge_record_id,
            )
            .where(
                TrainingExampleQualityScore.include_in_sft.is_(True),
                TrainingExampleQualityScore.final_training_value_score >= min_score,
            )
            .order_by(BlumKnowledgeRecord.created_at, BlumKnowledgeRecord.id)
            .limit(limit)
        ).all()
    )
    if len(rows) < 3:
        raise ValueError("At least three publishable examples are required for temporal splits.")

    record_ids = [record.id for _, _, record in rows]
    outcomes = list(
        db.scalars(
            select(BlumThesisOutcome)
            .where(BlumThesisOutcome.knowledge_record_id.in_(record_ids))
            .order_by(BlumThesisOutcome.knowledge_record_id, BlumThesisOutcome.horizon_days.desc())
        ).all()
    )
    outcome_by_record: dict[int, BlumThesisOutcome] = {}
    for outcome in outcomes:
        outcome_by_record.setdefault(outcome.knowledge_record_id, outcome)

    candidates: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for quality, example, record in rows:
        candidate = _candidate_payload(
            quality=quality,
            example=example,
            record=record,
            outcome=outcome_by_record.get(record.id),
            source_revision=source_revision,
        )
        redaction = sanitize_payload(candidate)
        if not redaction.publishable:
            exclusions.append(
                {
                    "source_record_id": record.id,
                    "reason": "unlicensed_verbatim_source",
                    "blocked_fields": redaction.blocked_fields,
                }
            )
            continue
        canonical = _canonical_json(redaction.payload)
        content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if content_hash in seen_hashes:
            exclusions.append({"source_record_id": record.id, "reason": "duplicate_content"})
            continue
        seen_hashes.add(content_hash)
        redaction.payload["content_hash"] = content_hash
        redaction.payload["example_id"] = f"blum-{content_hash[:20]}"
        candidates.append(redaction.payload)

    if len(candidates) < 3:
        raise ValueError("Redaction left fewer than three publishable examples.")

    assigned = _assign_temporal_splits(candidates)
    output_dir.mkdir(parents=True, exist_ok=True)
    split_rows: dict[DatasetSplit, list[ReleaseExample]] = {
        split: [] for split in DatasetSplit
    }
    for payload in assigned:
        parsed = ReleaseExample.model_validate(payload)
        split_rows[parsed.split].append(parsed)

    for split, examples in split_rows.items():
        _write_jsonl(
            output_dir / f"{split.value}.jsonl",
            [example.model_dump(mode="json") for example in examples],
        )
    _write_jsonl(output_dir / "excluded.jsonl", exclusions)
    dataset_sha = _dataset_digest(output_dir)
    manifest = ReleaseManifest(
        schema_version="blum-finance-manifest-v1",
        source_revision=source_revision,
        base_model=BASE_MODEL,
        generated_at=datetime.now(UTC),
        split_counts={split: len(examples) for split, examples in split_rows.items()},
        split_date_ranges={
            split: {
                "start": examples[0].created_at,
                "end": examples[-1].created_at,
            }
            for split, examples in split_rows.items()
        },
        exclusion_counts=dict(Counter(item["reason"] for item in exclusions)),
        dataset_sha256=dataset_sha,
    )
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _candidate_payload(
    *,
    quality: TrainingExampleQualityScore,
    example: BlumTrainingExample,
    record: BlumKnowledgeRecord,
    outcome: BlumThesisOutcome | None,
    source_revision: str,
) -> dict[str, Any]:
    output = example.output_payload or {}
    reasoning = record.blum_reasoning or {}
    messages = (example.messages or {}).get("items", [])
    label = outcome.outcome if outcome is not None else "insufficient_evidence"
    status = "mature" if outcome is not None and label in MATURE_OUTCOMES else "inconclusive"
    benchmark_excess = None
    if outcome is not None:
        benchmark_excess = (outcome.outcome_payload or {}).get("benchmark_excess")
    return {
        "schema_version": SCHEMA_VERSION,
        "example_id": "pending",
        "source_record_id": record.id,
        "source_revision": source_revision,
        "created_at": record.created_at,
        "ticker": record.ticker,
        "thesis_lineage_id": record.reasoning_hash or f"knowledge-{record.id}",
        "split": DatasetSplit.TRAIN.value,
        "task_type": example.task_type,
        "messages": messages,
        "evidence": {
            "supporting": _strings(
                output.get("supporting_evidence")
                or reasoning.get("supporting_evidence")
            ),
            "contradicting": _strings(
                output.get("contradicting_evidence")
                or reasoning.get("contradicting_evidence")
            ),
            "risks": _strings(
                output.get("risk_assessment")
                or reasoning.get("risks")
            ),
            "provenance": [
                {
                    "source_type": record.source_type or "blum_knowledge_record",
                    "source_id": str(record.id),
                }
            ],
        },
        "outcome": {
            "status": status,
            "label": label,
            "benchmark_relative_return": benchmark_excess,
        },
        "quality": {
            "final_score": quality.final_training_value_score,
            "data_quality_score": quality.data_quality_score,
            "contradiction_handling_score": quality.contradiction_handling_score,
            "confidence_calibration_score": quality.confidence_calibration_score,
        },
    }


def _assign_temporal_splits(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: (row["created_at"], row["source_record_id"]))
    group_order: list[str] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in ordered:
        lineage = str(row["thesis_lineage_id"])
        if lineage not in grouped:
            group_order.append(lineage)
            grouped[lineage] = []
        grouped[lineage].append(row)
    if len(group_order) < 3:
        raise ValueError("At least three thesis lineages are required for temporal splits.")

    train_end = max(1, int(len(group_order) * 0.8))
    validation_end = max(train_end + 1, int(len(group_order) * 0.9))
    validation_end = min(validation_end, len(group_order) - 1)
    split_by_lineage: dict[str, DatasetSplit] = {}
    for index, lineage in enumerate(group_order):
        if index < train_end:
            split_by_lineage[lineage] = DatasetSplit.TRAIN
        elif index < validation_end:
            split_by_lineage[lineage] = DatasetSplit.VALIDATION
        else:
            split_by_lineage[lineage] = DatasetSplit.TEST

    assigned: list[dict[str, Any]] = []
    for row in ordered:
        row["split"] = split_by_lineage[str(row["thesis_lineage_id"])].value
        assigned.append(row)
    return assigned


def _dataset_digest(output_dir: Path) -> str:
    digest = hashlib.sha256()
    for name in ("train.jsonl", "validation.jsonl", "test.jsonl", "excluded.jsonl"):
        digest.update(name.encode("utf-8"))
        digest.update((output_dir / name).read_bytes())
    return digest.hexdigest()


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(_canonical_json(row) + "\n")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]
