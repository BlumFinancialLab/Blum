from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.analyst.hf_training import SnapshotPolicy, build_snapshot
from app.analyst.hf_training_runtime import BlumHFTrainingService, LocalSnapshotPublisher


def candidate(*, outcome: dict | None = None) -> dict:
    return {
        "example_id": 7,
        "knowledge_record_id": 11,
        "lineage_key": "lineage-11",
        "created_at": "2026-08-01T10:00:00Z",
        "quality": 91,
        "task_type": "financial_thesis_generation",
        "messages": [
            {"role": "system", "content": "Use only supplied evidence."},
            {"role": "user", "content": '{"ticker":"NVDA","as_of":"2026-08-01T10:00:00Z"}'},
            {"role": "assistant", "content": '{"status":"watch","confidence":61}'},
        ],
        "input": {"ticker": "NVDA", "as_of": "2026-08-01T10:00:00Z"},
        "output": {"status": "watch", "confidence": 61},
        "preference": {},
        "outcomes": [outcome] if outcome else [],
        "flags": {},
        "provenance": {"source_verified": True, "license_ok": True},
    }


def matured_outcome() -> dict:
    return {
        "horizon_days": 20,
        "realized_return": -3.2,
        "max_drawdown": -5.1,
        "max_upside": 1.0,
        "outcome": "incorrect",
        "success": False,
        "updated_at": "2026-08-21T10:00:00Z",
    }


def test_matured_snapshot_adds_post_outcome_turn_after_original_thesis() -> None:
    snapshot = build_snapshot([candidate(outcome=matured_outcome())], SnapshotPolicy())
    row = next(iter(next(rows for rows in snapshot.records.values() if rows)))

    assert row["messages"][:3] == candidate(outcome=matured_outcome())["messages"]
    assert row["messages"][3]["role"] == "user"
    observed = json.loads(row["messages"][3]["content"])
    reflection = json.loads(row["messages"][4]["content"])
    assert observed["context_type"] == "validated_post_outcome_evidence"
    assert observed["outcomes"][0]["realized_return"] == -3.2
    assert reflection["outcome_assessment"] == "contradicted"
    assert reflection["confidence_direction"] == "decrease"
    assert "single matured thesis" in reflection["sample_warning"].lower()


def test_immature_snapshot_never_invents_outcome_learning_turn() -> None:
    snapshot = build_snapshot(
        [candidate()],
        SnapshotPolicy(require_matured_outcome=False),
    )
    row = next(iter(next(rows for rows in snapshot.records.values() if rows)))

    assert row["messages"] == candidate()["messages"]
    assert row["learning_context"] is None


def test_local_snapshot_publisher_is_atomic_and_idempotent(tmp_path) -> None:
    snapshot = build_snapshot([candidate(outcome=matured_outcome())], SnapshotPolicy())
    publisher = LocalSnapshotPublisher(tmp_path)

    first = publisher.publish(snapshot)
    second = publisher.publish(snapshot)

    assert first["status"] == "published"
    assert second["status"] == "already_published"
    assert Path(first["archive_path"]).is_file()
    assert json.loads(Path(first["manifest_path"]).read_text())["snapshot_hash"] == snapshot.snapshot_hash


def test_local_snapshot_publisher_serializes_concurrent_identical_writes(tmp_path) -> None:
    snapshot = build_snapshot([candidate(outcome=matured_outcome())], SnapshotPolicy())
    publisher = LocalSnapshotPublisher(tmp_path)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: publisher.publish(snapshot), range(4)))

    assert {result["status"] for result in results} <= {"published", "already_published"}
    assert sum(result["status"] == "published" for result in results) == 1
    assert all(Path(result["archive_path"]).is_file() for result in results)


def test_supervisor_persists_continual_snapshot_without_hub_token(tmp_path) -> None:
    service = BlumHFTrainingService(token="")
    service.settings.hf_dataset_snapshot_enabled = True
    service.settings.hf_dataset_snapshot_dir = str(tmp_path)
    service.settings.hf_training_enabled = False
    service.collect_candidates = lambda db: [candidate(outcome=matured_outcome())]  # type: ignore[method-assign]
    service._configured_champion_revision = lambda db: "champion-sha"  # type: ignore[method-assign]

    result = service.supervise(None)  # type: ignore[arg-type]

    assert result["status"] == "snapshot_ready"
    assert result["local_snapshot"]["accepted_rows"] == 1
    assert result["training"]["status"] == "disabled"
    assert result["training"]["token_configured"] is False
