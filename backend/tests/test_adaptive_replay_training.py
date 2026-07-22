from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.main import app
from app.engine.facade import BlumEngineFacade
from app.models import BackgroundJobState, StrategyFactoryRun
from app.services.adaptive_replay_training import (
    BlumAdaptiveTrainingController,
    ReplayResourceSample,
    ReplayTrainingConfig,
    ReplayTrainingSnapshotService,
    refresh_strategy_factory_state,
)
from app.services.executable_strategy import canonical_strategy_spec
from app.services.forex_evidence_academy import ForexCurriculumPlanner


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


class StaticResourceMonitor:
    def __init__(self, cpu: float, memory: float, api_p95_ms: float, active_jobs: int = 0):
        self.sample = ReplayResourceSample(cpu_percent=cpu, memory_percent=memory, api_p95_ms=api_p95_ms, active_jobs=active_jobs)

    def read(self, db=None) -> ReplayResourceSample:
        return self.sample


class RecordingEngine:
    def __init__(self):
        self.calls = []

    def run_cycle(self, db, request):
        self.calls.append(request)
        return {
            "status": "COMPLETED",
            "run_id": "replay-test",
            "assets_selected": ["NVDA"],
            "markets_selected": ["USA"],
            "timeframes_used": ["1d"],
            "trades_generated": 12,
            "trades_validated": 12,
            "experiments_run": 0,
            "strategies_promoted": 0,
            "strategies_rejected": 0,
            "runtime_seconds": 0.1,
            "resource_limits_applied": {"max_seconds": request.max_seconds, "max_assets": request.max_assets},
            "blockers": [],
            "lookahead_violations": 0,
            "next_cursor": {"asset_id": 99},
            "next_action": "continue",
        }


class StaticPromotionFrontier:
    def research_plan(self, db, *, limit, seed, selection_history=None):
        spec = canonical_strategy_spec("intraday_breakout").to_payload()
        return {
            "specs": [spec],
            "reasons": [{"strategy_fingerprint": spec["strategy_fingerprint"], "reason": "promotion_frontier", "sample_size": 12}],
            "selection_mix": {"promotion_frontier": 1, "failure_replay": 0, "coverage_gap": 0, "broad_exploration": 0},
            "stalled_rotations": 0,
        }

    def snapshot(self, db, limit=20):
        return {"status": "READY", "candidates": []}

    def priority_specs(self, db, *, market_filter, limit):
        spec = canonical_strategy_spec("intraday_breakout")
        return (
            {
                **spec.to_payload(),
                "market_filter": market_filter,
                "minimum_relative_volume": 0.0,
                "minimum_stop_percent": 0.0005,
            },
        )


def config() -> ReplayTrainingConfig:
    return ReplayTrainingConfig(
        target_trades_per_day=5000,
        max_seconds_per_cycle=120,
        max_assets_per_cycle=20,
        max_trades_per_cycle=500,
        max_experiments_per_cycle=5,
        min_promotion_samples=300,
    )


def test_controller_throttles_under_high_load():
    engine = RecordingEngine()
    controller = BlumAdaptiveTrainingController(
        engine=engine,
        resource_monitor=StaticResourceMonitor(cpu=88, memory=84, api_p95_ms=2300),
        config=config(),
    )
    with setup_db() as db:
        result = controller.run_once(db, trigger="test")

    assert result["adaptive_training_state"] == "THROTTLED"
    assert engine.calls[0].max_assets < config().max_assets_per_cycle
    assert engine.calls[0].max_seconds <= config().max_seconds_per_cycle


def test_controller_pauses_when_runtime_is_degraded():
    engine = RecordingEngine()
    controller = BlumAdaptiveTrainingController(
        engine=engine,
        resource_monitor=StaticResourceMonitor(cpu=98, memory=94, api_p95_ms=6000),
        config=config(),
    )
    with setup_db() as db:
        result = controller.run_once(db, trigger="test")

    assert result["adaptive_training_state"] == "PAUSED_FOR_RUNTIME"
    assert engine.calls == []
    assert result["reason_if_target_missed"]


def test_controller_resumes_from_persisted_cursor_and_checkpoints_next_slice():
    engine = RecordingEngine()
    controller = BlumAdaptiveTrainingController(
        engine=engine,
        resource_monitor=StaticResourceMonitor(cpu=20, memory=30, api_p95_ms=120),
        config=config(),
    )
    with setup_db() as db:
        db.add(
            BackgroundJobState(
                job_name="hyperbolic_replay_training",
                stage_name="replay_slice",
                status="completed",
                cursor_json={"asset_id": 42},
                enabled=True,
            )
        )
        db.commit()
        controller.run_once(db, trigger="test")
        state = db.query(BackgroundJobState).filter_by(
            job_name="hyperbolic_replay_training",
            stage_name="replay_slice",
        ).one()

    assert engine.calls[0].after_asset_id == 42
    assert engine.calls[0].priority_markets == ("FOREX",)
    assert state.cursor_json["asset_id"] == 99
    assert state.cursor_json["research_selection_history"] == {}
    assert state.status == "completed"


def test_controller_restores_independent_priority_market_cursors():
    engine = RecordingEngine()
    controller = BlumAdaptiveTrainingController(
        engine=engine,
        resource_monitor=StaticResourceMonitor(cpu=20, memory=30, api_p95_ms=120),
        config=config(),
    )
    with setup_db() as db:
        db.add(
            BackgroundJobState(
                job_name="hyperbolic_replay_training",
                stage_name="replay_slice",
                status="completed",
                cursor_json={"asset_id": 42, "market_cursors": {"FOREX": 84}},
                enabled=True,
            )
        )
        db.commit()
        controller.run_once(db, trigger="test")

    assert engine.calls[0].market_cursors == {"FOREX": 84}


def test_controller_passes_promotion_frontier_specs_to_bounded_replay():
    engine = RecordingEngine()
    controller = BlumAdaptiveTrainingController(
        engine=engine,
        resource_monitor=StaticResourceMonitor(cpu=20, memory=30, api_p95_ms=120),
        config=config(),
        promotion_frontier=StaticPromotionFrontier(),
    )
    with setup_db() as db:
        controller.run_once(db, trigger="test")

    assert engine.calls[0].strategy_specs
    assert engine.calls[0].strategy_specs[0]["strategy_fingerprint"]
    assert any(spec["market_filter"] == "forex_only" for spec in engine.calls[0].strategy_specs)


def test_controller_consumes_active_forex_curriculum_without_replacing_broad_research():
    engine = RecordingEngine()
    controller = BlumAdaptiveTrainingController(
        engine=engine,
        resource_monitor=StaticResourceMonitor(cpu=20, memory=30, api_p95_ms=120),
        config=config(),
        promotion_frontier=StaticPromotionFrontier(),
    )
    with setup_db() as db:
        assignments = ForexCurriculumPlanner().generate(db, limit=3)
        assignment_id = assignments[0].id
        controller.run_once(db, trigger="test")

    specs = list(engine.calls[0].strategy_specs)
    assert any(spec.get("forex_curriculum_assignment_id") == assignment_id for spec in specs)
    assert any(spec.get("market_filter") != "forex_only" for spec in specs)


def test_controller_checkpoints_research_progress_history_with_asset_cursor():
    engine = RecordingEngine()
    controller = BlumAdaptiveTrainingController(
        engine=engine,
        resource_monitor=StaticResourceMonitor(cpu=20, memory=30, api_p95_ms=120),
        config=config(),
        promotion_frontier=StaticPromotionFrontier(),
    )
    with setup_db() as db:
        controller.run_once(db, trigger="test")
        state = db.query(BackgroundJobState).filter_by(
            job_name="hyperbolic_replay_training", stage_name="replay_slice"
        ).one()

    assert state.cursor_json["asset_id"] == 99
    history = state.cursor_json["research_selection_history"]
    assert len(history) == 2
    assert {row["last_sample_size"] for row in history.values()} == {0, 12}
    assert all(row["consecutive_no_progress"] == 0 for row in history.values())


def test_runtime_pause_preserves_existing_replay_cursor():
    controller = BlumAdaptiveTrainingController(
        engine=RecordingEngine(),
        resource_monitor=StaticResourceMonitor(cpu=99, memory=95, api_p95_ms=7000),
        config=config(),
    )
    with setup_db() as db:
        db.add(
            BackgroundJobState(
                job_name="hyperbolic_replay_training",
                stage_name="replay_slice",
                status="completed",
                cursor_json={"asset_id": 17},
                enabled=True,
            )
        )
        db.commit()
        controller.run_once(db, trigger="test")
        state = db.query(BackgroundJobState).filter_by(
            job_name="hyperbolic_replay_training",
            stage_name="replay_slice",
        ).one()

    assert state.cursor_json == {"asset_id": 17}


def test_controller_waits_when_background_job_budget_is_exhausted():
    engine = RecordingEngine()
    controller = BlumAdaptiveTrainingController(
        engine=engine,
        resource_monitor=StaticResourceMonitor(cpu=30, memory=40, api_p95_ms=300, active_jobs=4),
        config=config(),
    )
    with setup_db() as db:
        result = controller.run_once(db, trigger="test")

    assert result["adaptive_training_state"] == "BUDGET_WAIT"
    assert engine.calls == []


def test_replay_training_snapshot_is_read_only_and_stale_safe():
    with setup_db() as db:
        missing = ReplayTrainingSnapshotService().snapshot(db)
        ReplayTrainingSnapshotService().write(
            db,
            {
                "replay_engine_status": "COMPLETED",
                "validated_trades_today": 125,
                "target_trades_per_day": 5000,
            },
        )
        stored = ReplayTrainingSnapshotService().snapshot(db)

    assert missing["replay_engine_status"] == "INITIALIZING"
    assert stored["validated_trades_today"] == 125
    assert stored["target_trades_per_day"] == 5000


def test_factory_worker_refreshes_factory_state_without_waiting_for_next_replay():
    with setup_db() as db:
        ReplayTrainingSnapshotService().write(
            db,
            {
                "strategy_factory": {
                    "status": "READY",
                    "latest_run_at": "2026-07-15T12:00:00",
                    "examined_variants": 1,
                    "promoted_to_paper": 0,
                }
            },
        )
        db.add(
            StrategyFactoryRun(
                run_uid="factory-latest",
                hypothesis_family="intraday_scalping",
                generation_seed=7,
                status="COMPLETED",
                started_at=datetime(2026, 7, 16, 6, 47),
                completed_at=datetime(2026, 7, 16, 6, 47, 1),
            )
        )
        db.commit()

        refreshed = refresh_strategy_factory_state(db)

    assert refreshed["strategy_factory"]["latest_run_at"] == "2026-07-16T06:47:01"


def test_facade_manual_replay_calls_controller_only_on_command(monkeypatch):
    calls = []

    def fake_run(self, db, trigger="manual"):
        calls.append(trigger)
        return {"status": "COMPLETED", "trades_validated": 4}

    monkeypatch.setattr(BlumAdaptiveTrainingController, "run_once", fake_run)
    with setup_db() as db:
        result = BlumEngineFacade().run_training_replay(db)

    assert result["trades_validated"] == 4
    assert calls == ["manual"]


def test_training_snapshot_never_executes_replay_controller(monkeypatch):
    def forbidden_run(*args, **kwargs):
        raise AssertionError("A read-only training snapshot must not execute replay training.")

    monkeypatch.setattr(BlumAdaptiveTrainingController, "run_once", forbidden_run)
    with setup_db() as db:
        snapshot = BlumEngineFacade().training_snapshot(db)

    assert snapshot["policy"].startswith("Training Ground observes")
    assert snapshot["hyperbolic_replay"]["replay_engine_status"] == "INITIALIZING"


def test_replay_defaults_keep_bounded_professional_training_guards():
    settings = ReplayTrainingConfig.from_settings()

    assert settings.target_trades_per_day == 5000
    assert settings.max_seconds_per_cycle <= 120
    assert settings.min_promotion_samples >= 300
    assert settings.max_experiments_per_cycle <= 8


def test_manual_replay_endpoint_is_post_only():
    route = next(route for route in app.routes if route.path == "/api/training/run-replay")

    assert route.methods == {"POST"}
