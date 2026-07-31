from __future__ import annotations

from app.analyst.hf_training import SnapshotPolicy, build_snapshot


def example(
    identifier: int,
    lineage: str,
    *,
    quality: float = 85.0,
    matured: bool = True,
    flags: dict | None = None,
) -> dict:
    return {
        "example_id": identifier,
        "knowledge_record_id": identifier,
        "lineage_key": lineage,
        "created_at": f"2026-07-{(identifier % 28) + 1:02d}T10:00:00Z",
        "quality": quality,
        "task_type": "financial_thesis_generation",
        "messages": [
            {"role": "user", "content": f"Evidence packet {identifier}"},
            {"role": "assistant", "content": "Produce the BLUM thesis contract."},
        ],
        "input": {"as_of": "2026-07-01", "ticker": f"T{identifier}"},
        "output": {"thesis": f"Thesis {identifier}", "confidence": 0.6},
        "preference": {},
        "outcomes": ([{"horizon_days": 20, "realized_return": 2.0, "outcome": "correct"}] if matured else []),
        "flags": flags or {},
    }


def test_snapshot_rejects_unmatured_low_quality_and_contaminated_rows() -> None:
    rows = [
        example(1, "lineage-a"),
        example(2, "lineage-b", matured=False),
        example(3, "lineage-c", quality=55),
        example(4, "lineage-d", flags={"quarantined": True}),
        example(5, "lineage-e", flags={"source_verified": False}),
    ]
    snapshot = build_snapshot(rows, SnapshotPolicy(minimum_quality=70.0, require_matured_outcome=True))
    assert snapshot.manifest["accepted_rows"] == 1
    assert snapshot.manifest["rejected_rows"] == 4
    assert snapshot.manifest["rejection_reasons"] == {
        "critical_safety_or_provenance_flag": 2,
        "immature_outcome": 1,
        "quality_below_threshold": 1,
    }


def test_snapshot_is_deterministic_and_never_splits_one_lineage() -> None:
    rows = [example(index, f"lineage-{index // 2}") for index in range(1, 80)]
    first = build_snapshot(rows, SnapshotPolicy(minimum_quality=70.0, require_matured_outcome=True))
    second = build_snapshot(list(reversed(rows)), SnapshotPolicy(minimum_quality=70.0, require_matured_outcome=True))

    assert first.snapshot_hash == second.snapshot_hash
    assert first.files == second.files

    lineage_splits: dict[str, set[str]] = {}
    for split, records in first.records.items():
        for record in records:
            lineage_splits.setdefault(record["lineage_key"], set()).add(split)
    assert all(len(splits) == 1 for splits in lineage_splits.values())
    assert set(first.records) == {"train", "validation", "test"}


def test_duplicate_lineage_content_is_deduplicated() -> None:
    rows = [example(1, "same"), example(2, "same"), example(3, "unique")]
    snapshot = build_snapshot(rows, SnapshotPolicy(minimum_quality=70.0, require_matured_outcome=True))
    assert snapshot.manifest["accepted_rows"] == 2
    assert snapshot.manifest["rejection_reasons"]["duplicate_lineage"] == 1
