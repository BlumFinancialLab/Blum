from datetime import datetime, timedelta
from pathlib import Path
import time

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import BackgroundJobState, BrainRuntimeEvent, DashboardSnapshot
from app.services.central_brain_runtime import (
    BackgroundJobStateService,
    BrainEventBus,
    CRITICAL_SNAPSHOT_TYPES,
    CentralBrainRuntime,
    LearningHealthService,
    SnapshotProducerService,
    SnapshotWatchdogService,
)
from app.services.dashboard_snapshots import DashboardSnapshotService


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_brain_event_bus_persists_module_events():
    with setup_db() as db:
        event = BrainEventBus().publish(
            db,
            "module_completed",
            "learning_loop",
            duration_ms=42.5,
            payload={"items": 3},
        )

        row = db.scalar(select(BrainRuntimeEvent).where(BrainRuntimeEvent.source_module == "learning_loop"))

        assert event["source_module"] == "learning_loop"
        assert row is not None
        assert row.payload_json["items"] == 3


def test_background_job_state_records_start_complete_and_budget_stop():
    with setup_db() as db:
        service = BackgroundJobStateService()
        started = service.start(db, "snapshot_producer", max_items=4, cursor={"offset": 0})
        completed = service.complete(db, "snapshot_producer", duration_ms=35.0, items_processed=4, cursor={"offset": 4})

        row = db.get(BackgroundJobState, started.id)

        assert row is not None
        assert completed.status == "completed"
        assert row.cursor_json["offset"] == 4
        assert service.should_stop(time.perf_counter() - 200, 1, max_items=100, max_seconds=1) is True
        assert service.should_stop(time.perf_counter(), 5, max_items=5, max_seconds=100) is True


def test_snapshot_producer_writes_missing_sections_and_watchdog_detects_stale():
    with setup_db() as db:
        produced = SnapshotProducerService().produce(db, "benchmark_summary")
        assert produced["snapshot_type"] == "benchmark_summary"
        assert "learning_benchmark_comparisons" in produced["missing_sections"]

        row = db.scalar(select(DashboardSnapshot).where(DashboardSnapshot.snapshot_type == "benchmark_summary"))
        row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()

        health = SnapshotWatchdogService().health(db)
        assert "benchmark_summary" in health["stale_snapshots"]
        assert "learning_summary" in health["missing_snapshots"]


def test_dashboard_snapshot_service_keeps_missing_sections_round_trip():
    with setup_db() as db:
        payload = DashboardSnapshotService().write(
            db,
            "learning_summary",
            {"status": "partial"},
            missing_sections=["trading_game"],
            ttl_seconds=60,
        )
        latest = DashboardSnapshotService().latest(db, "learning_summary")

        assert payload["missing_sections"] == ["trading_game"]
        assert latest["missing_sections"] == ["trading_game"]


def test_dashboard_snapshot_service_serializes_datetime_payloads():
    now = datetime(2026, 1, 2, 3, 4, 5)
    with setup_db() as db:
        DashboardSnapshotService().write(
            db,
            "dashboard_overview_summary",
            {"generated_at": now, "rows": [{"created_at": now}]},
            source_modules={"checked_at": now},
            warnings=[{"created_at": now}],
            ttl_seconds=60,
        )
        latest = DashboardSnapshotService().latest(db, "dashboard_overview_summary")

        assert latest["payload"]["generated_at"] == "2026-01-02T03:04:05"
        assert latest["payload"]["rows"][0]["created_at"] == "2026-01-02T03:04:05"
        assert latest["source_modules"]["checked_at"] == "2026-01-02T03:04:05"
        assert latest["warnings"][0]["created_at"] == "2026-01-02T03:04:05"


def test_runtime_state_and_learning_health_work_with_empty_database():
    with setup_db() as db:
        state = CentralBrainRuntime().state(db)
        health = LearningHealthService().health(db)

        assert state["system_readiness"]["api_ready"] is True
        assert "learning_summary" in state["missing_snapshots"]
        assert health["status"] in {"degraded", "stale"}
        assert health["frontend_policy"] == "read_only_snapshot_observer"


def test_get_side_effect_detection_guard_is_in_middleware_source():
    main_file = Path(__file__).resolve().parents[1] / "app" / "main.py"
    text = main_file.read_text()

    assert "GET_ENDPOINT_SIDE_EFFECT_DETECTED" in text
    assert "X-BLUM-GET-SIDE-EFFECT-RISK" in text
    assert "persist=true" in text


def test_dashboard_overview_snapshot_is_in_startup_warmup_budget():
    assert "learning_summary" in CRITICAL_SNAPSHOT_TYPES[:8]
    assert "dashboard_overview_summary" in CRITICAL_SNAPSHOT_TYPES[:8]


def test_snapshot_producer_batch_continues_after_failed_snapshot(monkeypatch):
    with setup_db() as db:
        original_payload = SnapshotProducerService._payload

        def fail_one(self, session, snapshot_type, missing_sections, warnings):
            if snapshot_type == "dashboard_overview_summary":
                raise RuntimeError("forced snapshot failure")
            return original_payload(self, session, snapshot_type, missing_sections, warnings)

        monkeypatch.setattr(SnapshotProducerService, "_payload", fail_one)
        result = SnapshotProducerService().produce_many(
            db,
            snapshot_types=["dashboard_overview_summary", "benchmark_summary"],
            max_items=2,
        )
        latest = DashboardSnapshotService().latest(db, "benchmark_summary")

        assert result["produced"] == 1
        assert result["failed"][0]["snapshot_type"] == "dashboard_overview_summary"
        assert latest["snapshot_type"] == "benchmark_summary"
