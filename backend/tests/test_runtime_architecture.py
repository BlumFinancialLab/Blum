from datetime import datetime, timedelta
from pathlib import Path
import time

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import BackgroundJobState, BrainRuntimeEvent, DashboardSnapshot, LearningRun
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
from app.services.learning_loop import LearningLoopService
from app.services.realtime import startup_snapshot_warmup_budget
from app.services.worker_runtime import RuntimeWorkerCoordinator, WORKER_DEFINITIONS


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


def test_background_job_state_recovers_interrupted_running_jobs():
    with setup_db() as db:
        service = BackgroundJobStateService()
        service.start(db, "autonomous_research_engine", max_items=4)

        recovered = service.recover_interrupted(db, reason="test_restart")
        row = db.scalar(select(BackgroundJobState).where(BackgroundJobState.job_name == "autonomous_research_engine"))

        assert recovered["recovered"] == 1
        assert row.status == "interrupted"
        assert row.error_message == "test_restart"


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
        assert any(worker["name"] == "blum_professional_learning_cycle" for worker in state["worker_registry"])
        assert "learning_summary" in state["missing_snapshots"]
        assert health["status"] in {"degraded", "stale"}
        assert health["frontend_policy"] == "read_only_snapshot_observer"


def test_runtime_worker_coordinator_blocks_only_duplicate_worker():
    coordinator = RuntimeWorkerCoordinator()

    acquired_learning, learning_state = coordinator.begin("blum_professional_learning_cycle", max_items=10)
    acquired_duplicate, duplicate_state = coordinator.begin("blum_professional_learning_cycle", max_items=10)
    acquired_snapshot, snapshot_state = coordinator.begin("snapshot_producer", max_items=10)

    assert acquired_learning is True
    assert learning_state["queue_name"] == "professional_learning"
    assert acquired_duplicate is False
    assert duplicate_state["reason"] == "same_worker_already_running"
    assert acquired_snapshot is True
    assert snapshot_state["queue_name"] == "snapshots"
    assert coordinator.snapshot()["running_count"] == 2

    coordinator.complete("blum_professional_learning_cycle")
    coordinator.complete("snapshot_producer")

    assert coordinator.snapshot()["running_count"] == 0


def test_worker_registry_covers_core_runtime_modules():
    required = {
        "snapshot_producer",
        "runtime_snapshot_watchdog",
        "market_refresh",
        "blum_professional_learning_cycle",
        "blum_trading_game",
        "autonomous_research_engine",
    }

    assert required.issubset(set(WORKER_DEFINITIONS))


def test_get_side_effect_detection_guard_is_in_middleware_source():
    main_file = Path(__file__).resolve().parents[1] / "app" / "main.py"
    text = main_file.read_text()

    assert "GET_ENDPOINT_SIDE_EFFECT_DETECTED" in text
    assert "X-BLUM-GET-SIDE-EFFECT-RISK" in text
    assert "persist=true" in text


def test_dashboard_overview_snapshot_is_in_startup_warmup_budget():
    assert "learning_summary" in CRITICAL_SNAPSHOT_TYPES[:8]
    assert "dashboard_overview_summary" in CRITICAL_SNAPSHOT_TYPES[:8]


def test_startup_snapshot_warmup_budget_covers_all_critical_snapshots():
    assert startup_snapshot_warmup_budget() == len(CRITICAL_SNAPSHOT_TYPES)
    assert "capital_allocation_summary" in CRITICAL_SNAPSHOT_TYPES[: startup_snapshot_warmup_budget()]
    assert "alpha_recovery_summary" in CRITICAL_SNAPSHOT_TYPES[: startup_snapshot_warmup_budget()]
    assert "meta_cognition_summary" in CRITICAL_SNAPSHOT_TYPES[: startup_snapshot_warmup_budget()]
    assert "trading_game_ledger_snapshot" in CRITICAL_SNAPSHOT_TYPES[: startup_snapshot_warmup_budget()]
    assert "equity_curve_snapshot" in CRITICAL_SNAPSHOT_TYPES[: startup_snapshot_warmup_budget()]


def test_learning_daily_guard_uses_partial_batch_before_budget_wait(monkeypatch):
    with setup_db() as db:
        db.add(
            LearningRun(
                run_id="existing-today",
                trigger="test",
                status="ok",
                predictions_created=8,
            )
        )
        db.commit()
        monkeypatch.setattr("app.services.learning_loop.settings.learning_max_daily_runs", 10)

        guard = LearningLoopService().daily_guard(db, requested_batch=5)

        assert guard["allowed"] is True
        assert guard["effective_batch"] == 2
        assert guard["partial_batch"] is True
        assert guard["remaining_daily_budget"] == 2


def test_learning_daily_guard_reports_budget_wait_without_skip(monkeypatch):
    with setup_db() as db:
        db.add(
            LearningRun(
                run_id="full-budget",
                trigger="test",
                status="ok",
                predictions_created=10,
            )
        )
        db.commit()
        monkeypatch.setattr("app.services.learning_loop.settings.learning_max_daily_runs", 10)

        guard = LearningLoopService().daily_guard(db, requested_batch=5)

        assert guard["allowed"] is False
        assert guard["effective_batch"] == 0
        assert "daily learning budget exhausted" in guard["reason"]


def test_realtime_scheduler_has_professional_learning_lane_and_staggering():
    realtime_source = (Path(__file__).resolve().parents[1] / "app" / "services" / "realtime.py").read_text()
    worker_source = (Path(__file__).resolve().parents[1] / "app" / "services" / "worker_runtime.py").read_text()
    source = realtime_source + worker_source

    assert "blum_professional_learning_cycle" in source
    assert "run_professional_learning_cycle_job" in source
    assert "professional_continuous" in source
    assert "backup=False" in source
    assert "batch_size // 2" in source
    assert "sniper_simulation_limit=0" in source
    assert "next_run_time=datetime.utcnow() + timedelta" in source
    assert "same_worker_already_running" in source
    assert "running_jobs" in source
    assert "runtime_worker_coordinator.begin" in source


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
