from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.analyst.release_contracts import ReleaseExample, ReleaseManifest


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
