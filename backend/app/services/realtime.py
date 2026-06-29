from __future__ import annotations

from datetime import datetime, timedelta
import threading
import time
import traceback

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.ingestion.news_ingestor import NewsIngestor
from app.services.accuracy import run_accuracy_audit
from app.services.autonomous_engine import AutonomousResearchEngine
from app.services.blum_financial_model import run_model_learning_cycle
from app.services.central_brain_runtime import BackgroundJobStateService, SnapshotProducerService, SnapshotWatchdogService
from app.services.data_continuity import repair_data_gaps
from app.services.etf import update_etf_trends
from app.services.fundamentals import update_fundamentals
from app.services.financial_brain_learning import run_learning_cycle
from app.services.ipo import update_ipo_radar
from app.services.learning_loop import LearningLoopService
from app.services.macro import update_macro_snapshots
from app.services.market_data import MarketDataService
from app.services.performance import performance_recorder
from app.services.pipeline import PipelineService
from app.services.trading_game import TradingGameSimulator
from app.signals.engine import SignalEngine


settings = get_settings()
_scheduler: BackgroundScheduler | None = None
_state_lock = threading.RLock()
_state = {
    "started": False,
    "running": False,
    "last_started_at": None,
    "last_completed_at": None,
    "last_job": None,
    "last_status": "idle",
    "last_error": "",
    "last_result": {},
    "current_stage": None,
    "stage_started_at": None,
    "stage_completed_at": None,
    "completed_stages": [],
    "stage_results": {},
}


def start_realtime_services() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone="UTC")
    if settings.enable_live_startup and settings.startup_run_full_autonomous:
        threading.Thread(target=run_startup_pipeline, daemon=True).start()
    elif settings.enable_live_startup:
        threading.Thread(target=run_startup_snapshot_warmup, daemon=True).start()
    _add_interval_job(run_runtime_snapshot_watchdog, minutes=5, job_id="runtime_snapshot_watchdog", delay_seconds=45, jitter_seconds=10)
    _add_interval_job(run_snapshot_refresh_job, minutes=10, job_id="snapshot_producer", delay_seconds=105, jitter_seconds=20)
    if settings.enable_autonomous_engine:
        _add_interval_job(run_autonomous_engine_job, minutes=settings.autonomous_cycle_minutes, job_id="autonomous_research_engine", delay_seconds=180, jitter_seconds=45)
    _add_interval_job(run_news_refresh, minutes=settings.news_refresh_minutes, job_id="news_refresh", delay_seconds=240, jitter_seconds=30)
    _add_interval_job(run_market_refresh, minutes=settings.market_refresh_minutes, job_id="market_refresh", delay_seconds=360, jitter_seconds=45)
    _add_interval_job(run_data_gap_repair, minutes=settings.data_gap_repair_minutes, job_id="data_gap_repair", delay_seconds=480, jitter_seconds=45)
    _add_interval_job(run_accuracy_audit_job, minutes=settings.accuracy_audit_minutes, job_id="accuracy_audit", delay_seconds=600, jitter_seconds=45)
    _add_interval_job(run_macro_refresh, minutes=settings.macro_refresh_minutes, job_id="macro_refresh", delay_seconds=720, jitter_seconds=45)
    _add_interval_job(run_fundamentals_refresh, minutes=settings.fundamentals_refresh_minutes, job_id="fundamentals_refresh", delay_seconds=840, jitter_seconds=45)
    _add_interval_job(run_ipo_refresh, minutes=settings.ipo_refresh_minutes, job_id="ipo_refresh", delay_seconds=960, jitter_seconds=45)
    if settings.enable_learning_loop:
        if settings.professional_learning_enabled:
            _add_interval_job(
                run_professional_learning_cycle_job,
                minutes=settings.professional_learning_minutes,
                job_id="blum_professional_learning_cycle",
                delay_seconds=150,
                jitter_seconds=30,
            )
        else:
            _add_interval_job(run_learning_cycle_job, minutes=settings.learning_loop_minutes, job_id="financial_brain_learning", delay_seconds=1020, jitter_seconds=45)
            _add_interval_job(run_blum_model_cycle_job, minutes=settings.blum_model_cycle_minutes, job_id="blum_financial_model_cycle", delay_seconds=1080, jitter_seconds=45)
            _add_interval_job(run_blum_learning_loop_job, minutes=settings.learning_loop_minutes, job_id="blum_point_in_time_learning_loop", delay_seconds=1140, jitter_seconds=45)
            if settings.trading_game_enabled:
                _add_interval_job(run_trading_game_job, minutes=settings.learning_loop_minutes, job_id="blum_trading_game", delay_seconds=1200, jitter_seconds=45)
    _scheduler.start()
    with _state_lock:
        _state["started"] = True


def stop_realtime_services() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def realtime_status() -> dict:
    with _state_lock:
        payload = dict(_state)
    payload["scheduled_jobs"] = scheduled_jobs()
    return payload


def _add_interval_job(func, *, minutes: int, job_id: str, delay_seconds: int, jitter_seconds: int = 0) -> None:
    if _scheduler is None:
        return
    _scheduler.add_job(
        func,
        "interval",
        minutes=max(1, int(minutes)),
        id=job_id,
        replace_existing=True,
        max_instances=1,
        next_run_time=datetime.utcnow() + timedelta(seconds=max(0, delay_seconds)),
        jitter=max(0, jitter_seconds),
    )


def scheduled_jobs() -> list[dict]:
    if _scheduler is None:
        return []
    jobs = []
    for job in _scheduler.get_jobs():
        jobs.append(
            {
                "id": job.id,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            }
        )
    return sorted(jobs, key=lambda item: item["id"])


def run_startup_pipeline() -> None:
    if settings.enable_autonomous_engine:
        _run_job(
            "autonomous_startup",
            lambda db: AutonomousResearchEngine(progress_callback=_update_stage_progress).run_cycle(db, trigger="startup"),
        )
        return

    def work(db):
        pipeline = PipelineService().run(db, limit=settings.startup_pipeline_limit, period=settings.historical_price_period)
        learning = run_learning_cycle(db, limit=settings.max_update_assets * 6) if settings.enable_learning_loop else {}
        model_learning = run_model_learning_cycle(db, limit=settings.blum_model_cycle_limit) if settings.enable_learning_loop else {}
        point_in_time_learning = LearningLoopService().run_batch(db, batch_size=min(settings.learning_batch_size, 25), trigger="startup") if settings.enable_learning_loop else {}
        trading_game = TradingGameSimulator().run(db, batch_size=min(settings.trading_game_batch_size, 40)) if settings.trading_game_enabled else {}
        return {"pipeline": pipeline, "financial_brain_learning": learning, "blum_financial_model": model_learning, "blum_learning_loop": point_in_time_learning, "trading_game": trading_game}

    _run_job("startup_pipeline", work)


def run_startup_snapshot_warmup() -> None:
    def work(db):
        health = SnapshotWatchdogService().health(db, queue_rebuild=True)
        snapshots = SnapshotProducerService().produce_many(db, max_items=startup_snapshot_warmup_budget())
        return {"snapshot_health": health, "snapshots": snapshots, "policy": "startup_light_mode"}

    _run_job("startup_snapshot_warmup", work)


def startup_snapshot_warmup_budget() -> int:
    """Warm every critical snapshot after API startup without page-triggered work."""

    from app.services.central_brain_runtime import CRITICAL_SNAPSHOT_TYPES

    configured_limit = max(1, settings.blum_autonomous_max_items_per_job)
    return min(configured_limit, len(CRITICAL_SNAPSHOT_TYPES))


def run_runtime_snapshot_watchdog() -> None:
    _run_job("runtime_snapshot_watchdog", lambda db: SnapshotWatchdogService().health(db, queue_rebuild=True))


def run_snapshot_refresh_job() -> None:
    _run_job("snapshot_producer", lambda db: SnapshotProducerService().produce_many(db, max_items=settings.blum_autonomous_max_items_per_job))


def run_news_refresh() -> None:
    _run_job("news_refresh", lambda db: NewsIngestor().update_news(db, lookback_hours=72, limit_per_feed=35))


def run_market_refresh() -> None:
    def work(db):
        market = MarketDataService().update_prices(db, period=settings.refresh_price_period, limit=settings.max_update_assets)
        signals = SignalEngine().run(db, limit=settings.max_update_assets)
        etf = update_etf_trends(db)
        learning = run_learning_cycle(db, limit=settings.max_update_assets * 6) if settings.enable_learning_loop else {}
        model_learning = run_model_learning_cycle(db, limit=settings.blum_model_cycle_limit) if settings.enable_learning_loop else {}
        point_in_time_learning = LearningLoopService().run_batch(db, batch_size=min(settings.learning_batch_size, 25), trigger="market_refresh") if settings.enable_learning_loop else {}
        trading_game = TradingGameSimulator().run(db, batch_size=min(settings.trading_game_batch_size, 40)) if settings.trading_game_enabled else {}
        return {"market_update": market, "signal_run": signals, "etf_update": etf, "financial_brain_learning": learning, "blum_financial_model": model_learning, "blum_learning_loop": point_in_time_learning, "trading_game": trading_game}

    _run_job("market_refresh", work)


def run_data_gap_repair() -> None:
    _run_job("data_gap_repair", lambda db: repair_data_gaps(db, limit=settings.max_update_assets))


def run_accuracy_audit_job() -> None:
    _run_job("accuracy_audit", lambda db: run_accuracy_audit(db, limit=settings.max_update_assets))


def run_macro_refresh() -> None:
    _run_job("macro_refresh", lambda db: update_macro_snapshots(db))


def run_fundamentals_refresh() -> None:
    _run_job("fundamentals_refresh", lambda db: update_fundamentals(db, limit=min(settings.max_update_assets, 24)))


def run_ipo_refresh() -> None:
    def work(db):
        return update_ipo_radar(db, limit_per_form=45)

    _run_job("ipo_refresh", work)


def run_learning_cycle_job() -> None:
    _run_job("financial_brain_learning", lambda db: run_learning_cycle(db, limit=settings.max_update_assets * 6))


def run_blum_model_cycle_job() -> None:
    _run_job("blum_financial_model_cycle", lambda db: run_model_learning_cycle(db, limit=settings.blum_model_cycle_limit))


def run_blum_learning_loop_job() -> None:
    _run_job("blum_point_in_time_learning_loop", lambda db: LearningLoopService().run_batch(db, batch_size=settings.learning_batch_size, trigger="scheduled"))


def run_trading_game_job() -> None:
    _run_job("blum_trading_game", lambda db: TradingGameSimulator().run(db, batch_size=settings.trading_game_batch_size))


def run_professional_learning_cycle_job() -> None:
    def work(db):
        batch_size = max(1, min(settings.professional_learning_batch_size, settings.learning_batch_size, settings.blum_autonomous_max_items_per_job))
        trading_batch = max(3, min(settings.trading_game_batch_size, max(3, batch_size // 2)))
        learning = run_learning_cycle(db, limit=max(20, min(settings.max_update_assets * 2, batch_size * 4)))
        model_learning = run_model_learning_cycle(db, limit=max(20, min(settings.blum_model_cycle_limit, batch_size * 4)), backup=False)
        point_in_time_learning = LearningLoopService().run_batch(db, batch_size=batch_size, trigger="professional_continuous")
        trading_game = TradingGameSimulator().run(db, batch_size=trading_batch) if settings.trading_game_enabled else {"status": "disabled"}
        snapshots = SnapshotProducerService().produce_many(db, max_items=settings.blum_autonomous_max_items_per_job)
        return {
            "mode": "professional_continuous_learning",
            "batch_size": batch_size,
            "financial_brain_learning": learning,
            "blum_financial_model": model_learning,
            "blum_learning_loop": point_in_time_learning,
            "trading_game": trading_game,
            "snapshots": snapshots,
            "policy": "Bounded server-side learning cycle. Frontend pages observe snapshots only and never trigger this work on render.",
        }

    _run_job("blum_professional_learning_cycle", work)


def run_autonomous_engine_job() -> None:
    _run_job(
        "autonomous_research_engine",
        lambda db: AutonomousResearchEngine(progress_callback=_update_stage_progress).run_cycle(db, trigger="scheduled"),
    )


def _update_stage_progress(progress: dict) -> None:
    with _state_lock:
        _state["current_stage"] = progress.get("stage")
        _state["stage_started_at"] = progress.get("stage_started_at")
        _state["stage_completed_at"] = progress.get("stage_completed_at")
        _state["completed_stages"] = progress.get("completed_stages", [])
        _state["stage_results"] = _compact_payload(progress.get("stage_results", {}))


def _run_job(job_name: str, work):
    with _state_lock:
        if _state["running"]:
            performance_recorder.record_background_task(
                job_name,
                0.0,
                {"status": "deferred", "reason": "another_background_job_running", "blocking_job": _state.get("last_job")},
                datetime.utcnow(),
            )
            return
        _state["running"] = True
        _state["last_started_at"] = datetime.utcnow().isoformat()
        _state["last_job"] = job_name
        _state["last_status"] = "running"
        _state["last_error"] = ""
        _state["current_stage"] = None
        _state["stage_started_at"] = None
        _state["stage_completed_at"] = None
        _state["completed_stages"] = []
        _state["stage_results"] = {}
    perf_started_at = datetime.utcnow()
    perf_started = time.perf_counter()
    perf_status = "ok"
    perf_error = ""
    max_items = settings.blum_autonomous_max_items_per_job
    with SessionLocal() as db:
        BackgroundJobStateService().start(db, job_name, max_items=max_items)
    try:
        with SessionLocal() as db:
            result = work(db)
            duration_ms = (time.perf_counter() - perf_started) * 1000
            BackgroundJobStateService().complete(
                db,
                job_name,
                duration_ms=duration_ms,
                payload=_compact_payload(result or {}),
            )
        with _state_lock:
            _state["last_completed_at"] = datetime.utcnow().isoformat()
            _state["last_status"] = "ok"
            _state["last_result"] = _compact_payload(result or {})
    except Exception as exc:
        perf_status = "error"
        perf_error = f"{type(exc).__name__}: {str(exc)}"
        with SessionLocal() as db:
            BackgroundJobStateService().fail(db, job_name, duration_ms=(time.perf_counter() - perf_started) * 1000, error_message=perf_error)
        with _state_lock:
            _state["last_completed_at"] = datetime.utcnow().isoformat()
            _state["last_status"] = "error"
            _state["last_error"] = perf_error
            _state["last_result"] = {"traceback": traceback.format_exc(limit=4)}
    finally:
        performance_recorder.record_background_task(
            job_name,
            (time.perf_counter() - perf_started) * 1000,
            {"status": perf_status, "error": perf_error},
            perf_started_at,
        )
        with _state_lock:
            _state["running"] = False


def _compact_payload(value, depth: int = 0):
    if depth > 5:
        return "<truncated>"
    if isinstance(value, dict):
        compact = {}
        for key, item in value.items():
            if key in {"sources", "source_diagnostics", "diagnostics"} and isinstance(item, list):
                compact[key] = {
                    "count": len(item),
                    "sample": [_compact_payload(row, depth + 1) for row in item[:8]],
                }
                continue
            if key in {"viewer_status", "parquet_files", "size_summary"} and isinstance(item, dict):
                compact[key] = _compact_dataset_metadata(item)
                continue
            compact[key] = _compact_payload(item, depth + 1)
        return compact
    if isinstance(value, list):
        if len(value) > 12:
            return {"count": len(value), "sample": [_compact_payload(item, depth + 1) for item in value[:12]]}
        return [_compact_payload(item, depth + 1) for item in value]
    if isinstance(value, str) and len(value) > 600:
        return f"{value[:600]}..."
    return value


def _compact_dataset_metadata(value: dict) -> dict:
    output = {}
    if "status" in value:
        output["status"] = value.get("status")
    if "file_count" in value:
        output["file_count"] = value.get("file_count")
    if "sample_files" in value and isinstance(value["sample_files"], list):
        output["sample_files"] = [
            {
                "dataset": item.get("dataset"),
                "config": item.get("config"),
                "split": item.get("split"),
                "filename": item.get("filename"),
                "size": item.get("size"),
            }
            for item in value["sample_files"][:3]
            if isinstance(item, dict)
        ]
    if "size" in value and isinstance(value["size"], dict):
        dataset = value["size"].get("dataset", {})
        if isinstance(dataset, dict):
            output["dataset_size"] = {
                "num_rows": dataset.get("num_rows"),
                "num_bytes_parquet_files": dataset.get("num_bytes_parquet_files"),
            }
    if not output:
        output = _compact_payload({k: v for k, v in value.items() if k != "detail"}, depth=1)
    return output
