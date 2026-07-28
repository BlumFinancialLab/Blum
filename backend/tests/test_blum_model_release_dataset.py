from __future__ import annotations

from datetime import datetime, timedelta
import json

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.analyst.release_dataset import build_release_dataset
from app.analyst.release_redaction import sanitize_payload
from app.analyst.release_contracts import ReleaseExample, ReleaseManifest
from app.core.database import Base
from app.models import (
    BlumKnowledgeRecord,
    BlumThesisOutcome,
    BlumTrainingExample,
    TrainingExampleQualityScore,
)


REVISION = "a" * 40


def valid_example() -> dict:
    return {
        "schema_version": "blum-finance-reasoning-v1",
        "example_id": "example-1",
        "source_record_id": 1,
        "source_revision": REVISION,
        "created_at": datetime(2026, 1, 1),
        "ticker": "NVDA",
        "thesis_lineage_id": "thesis-1",
        "split": "train",
        "task_type": "financial_thesis_generation",
        "messages": [
            {"role": "system", "content": "Use only supplied evidence."},
            {"role": "user", "content": "Evaluate the setup."},
            {"role": "assistant", "content": "Evidence is insufficient."},
        ],
        "evidence": {
            "supporting": ["Relative strength improved."],
            "contradicting": ["Volume confirmation is missing."],
            "risks": ["Regime could deteriorate."],
            "provenance": [{"source_type": "signal_snapshot", "source_id": "1"}],
        },
        "outcome": {
            "status": "inconclusive",
            "label": "insufficient_evidence",
            "benchmark_relative_return": None,
        },
        "quality": {
            "final_score": 74.0,
            "data_quality_score": 80.0,
            "contradiction_handling_score": 72.0,
            "confidence_calibration_score": 68.0,
        },
        "content_hash": "b" * 64,
    }


def valid_manifest() -> dict:
    return {
        "schema_version": "blum-finance-manifest-v1",
        "source_revision": REVISION,
        "base_model": "Qwen/Qwen3-4B",
        "generated_at": datetime(2026, 1, 2),
        "split_counts": {"train": 80, "validation": 10, "test": 10},
        "split_date_ranges": {
            "train": {"start": "2025-01-01T00:00:00", "end": "2025-10-31T00:00:00"},
            "validation": {"start": "2025-11-01T00:00:00", "end": "2025-11-30T00:00:00"},
            "test": {"start": "2025-12-01T00:00:00", "end": "2025-12-31T00:00:00"},
        },
        "exclusion_counts": {"low_quality": 5},
        "dataset_sha256": "c" * 64,
    }


def test_release_example_requires_provenance_and_evidence() -> None:
    payload = valid_example()
    payload["evidence"]["provenance"] = []

    with pytest.raises(ValidationError):
        ReleaseExample.model_validate(payload)


def test_release_example_accepts_complete_evidence() -> None:
    example = ReleaseExample.model_validate(valid_example())

    assert example.source_revision == REVISION
    assert example.evidence.contradicting == ["Volume confirmation is missing."]


def test_release_manifest_records_immutable_source_revision() -> None:
    manifest = ReleaseManifest.model_validate(valid_manifest())

    assert len(manifest.source_revision) == 40
    assert manifest.base_model == "Qwen/Qwen3-4B"


def test_release_manifest_rejects_non_commit_revision() -> None:
    payload = valid_manifest()
    payload["source_revision"] = "main"

    with pytest.raises(ValidationError):
        ReleaseManifest.model_validate(payload)


def test_redaction_removes_tokens_email_and_broker_identifiers() -> None:
    result = sanitize_payload(
        {
            "text": "Mail trader@example.com with bearer hf_abcdefghijklmnopqrstuvwxyz.",
            "api_key": "hf_secret",
            "broker_account_id": "ABC-123",
        }
    )
    serialized = json.dumps(result.payload)

    assert "trader@example.com" not in serialized
    assert "hf_secret" not in serialized
    assert "ABC-123" not in serialized
    assert result.blocked_fields == ["api_key", "broker_account_id"]
    assert result.pii_matches == ["email", "hugging_face_token"]


def test_unlicensed_verbatim_source_blocks_publication() -> None:
    result = sanitize_payload(
        {
            "raw_article": "A complete third-party article body.",
            "summary": "Revenue growth accelerated.",
        }
    )

    assert result.publishable is False
    assert result.payload == {"summary": "Revenue growth accelerated."}


def test_release_dataset_uses_temporal_splits_without_lineage_leakage(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    start = datetime(2025, 1, 1)
    with Session(engine) as db:
        for index in range(12):
            record = BlumKnowledgeRecord(
                ticker=f"T{index:02d}",
                sector="Technology",
                source_type="signal_snapshot",
                reasoning_hash=f"reason-{index}",
                market_regime="risk_on",
                blum_reasoning={
                    "supporting_evidence": ["Relative strength improved."],
                    "contradicting_evidence": ["Volume is not confirmed."],
                    "risks": ["Volatility could expand."],
                },
                created_at=start + timedelta(days=index),
            )
            db.add(record)
            db.flush()
            example = BlumTrainingExample(
                knowledge_record_id=record.id,
                task_type="financial_thesis_generation",
                messages={
                    "items": [
                        {"role": "system", "content": "Use supplied evidence only."},
                        {"role": "user", "content": f"Evaluate T{index:02d}."},
                        {"role": "assistant", "content": '{"status":"watch"}'},
                    ]
                },
                input_payload={"ticker": f"T{index:02d}"},
                output_payload={
                    "supporting_evidence": ["Relative strength improved."],
                    "contradicting_evidence": ["Volume is not confirmed."],
                    "risk_assessment": ["Volatility could expand."],
                },
                export_ready=True,
                created_at=start + timedelta(days=index),
            )
            db.add(example)
            db.flush()
            db.add(
                TrainingExampleQualityScore(
                    training_example_id=example.id,
                    thesis_id=record.id,
                    final_training_value_score=80,
                    data_quality_score=82,
                    contradiction_handling_score=79,
                    confidence_calibration_score=76,
                    include_in_sft=True,
                )
            )
            db.add(
                BlumThesisOutcome(
                    knowledge_record_id=record.id,
                    ticker=f"T{index:02d}",
                    horizon_days=7,
                    outcome="correct",
                    success=True,
                    realized_return=0.03,
                    outcome_payload={"benchmark_excess": 0.01},
                )
            )
        db.commit()

        manifest = build_release_dataset(
            db,
            source_revision=REVISION,
            output_dir=tmp_path,
            min_score=70,
        )

    rows = []
    for split in ("train", "validation", "test"):
        with (tmp_path / f"{split}.jsonl").open(encoding="utf-8") as handle:
            rows.extend(json.loads(line) for line in handle if line.strip())
    lineage_splits: dict[str, set[str]] = {}
    for row in rows:
        lineage_splits.setdefault(row["thesis_lineage_id"], set()).add(row["split"])

    assert all(len(splits) == 1 for splits in lineage_splits.values())
    assert manifest.split_counts["train"] == 9
    assert manifest.split_counts["validation"] == 1
    assert manifest.split_counts["test"] == 2
    assert rows[0]["created_at"] < rows[-1]["created_at"]
    assistant_payload = json.loads(rows[0]["messages"][-1]["content"])
    assert {
        "status",
        "thesis",
        "bull_case",
        "bear_case",
        "risks",
        "invalidation_conditions",
        "confidence",
        "what_would_change_the_view",
    }.issubset(assistant_payload)
