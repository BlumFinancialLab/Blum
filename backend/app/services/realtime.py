from __future__ import annotations

from datetime import datetime
import threading
import traceback

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.ingestion.news_ingestor import NewsIngestor
from app.services.accuracy import run_accuracy_audit
from app.services.autonomous_engine import AutonomousResearchEngine
from app.services.blum_financial_model import run_model_learning_cycle
from app.services.data_continuity import repair_data_gaps
from app.services.etf import update_etf_trends
from app.services.fundamentals import update_fundamentals
from app.services.financial_brain_learning import run_learning_cycle
from app.services.ipo import update_ipo_radar
from app.services.macro import update_macro_snapshots
from app.services.market_data import MarketDataService
from app.services.pipeline import PipelineService
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
}


def start_realtime_services() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone="UTC")
    if settings.enable_live_startup:
        threading.Thread(target=run_startup_pipeline, daemon=True).start()
    if settings.enable_autonomous_engine:
        _scheduler.add_job(run_autonomous_engine_job, "interval", minutes=settings.autonomous_cycle_minutes, id="autonomous_research_engine", replace_existing=True, max_instances=1)
        _scheduler.start()
        with _state_lock:
            _state["started"] = True
        return
    _scheduler.add_job(run_news_refresh, "interval", minutes=settings.news_refresh_minutes, id="news_refresh", replace_existing=True, max_instances=1)
    _scheduler.add_job(run_market_refresh, "interval", minutes=settings.market_refresh_minutes, id="market_refresh", replace_existing=True, max_instances=1)
    _scheduler.add_job(run_data_gap_repair, "interval", minutes=settings.data_gap_repair_minutes, id="data_gap_repair", replace_existing=True, max_instances=1)
    _scheduler.add_job(run_accuracy_audit_job, "interval", minutes=settings.accuracy_audit_minutes, id="accuracy_audit", replace_existing=True, max_instances=1)
    _scheduler.add_job(run_macro_refresh, "interval", minutes=settings.macro_refresh_minutes, id="macro_refresh", replace_existing=True, max_instances=1)
    _scheduler.add_job(run_fundamentals_refresh, "interval", minutes=settings.fundamentals_refresh_minutes, id="fundamentals_refresh", replace_existing=True, max_instances=1)
    _scheduler.add_job(run_ipo_refresh, "interval", minutes=settings.ipo_refresh_minutes, id="ipo_refresh", replace_existing=True, max_instances=1)
    if settings.enable_learning_loop:
        _scheduler.add_job(run_learning_cycle_job, "interval", minutes=settings.learning_loop_minutes, id="financial_brain_learning", replace_existing=True, max_instances=1)
        _scheduler.add_job(run_blum_model_cycle_job, "interval", minutes=settings.blum_model_cycle_minutes, id="blum_financial_model_cycle", replace_existing=True, max_instances=1)
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
        return dict(_state)


def run_startup_pipeline() -> None:
    if settings.enable_autonomous_engine:
        _run_job("autonomous_startup", lambda db: AutonomousResearchEngine().run_cycle(db, trigger="startup"))
        return

    def work(db):
        pipeline = PipelineService().run(db, limit=settings.startup_pipeline_limit, period=settings.historical_price_period)
        learning = run_learning_cycle(db, limit=settings.max_update_assets * 6) if settings.enable_learning_loop else {}
        model_learning = run_model_learning_cycle(db, limit=settings.blum_model_cycle_limit) if settings.enable_learning_loop else {}
        return {"pipeline": pipeline, "financial_brain_learning": learning, "blum_financial_model": model_learning}

    _run_job("startup_pipeline", work)


def run_news_refresh() -> None:
    _run_job("news_refresh", lambda db: NewsIngestor().update_news(db, lookback_hours=72, limit_per_feed=35))


def run_market_refresh() -> None:
    def work(db):
        market = MarketDataService().update_prices(db, period=settings.refresh_price_period, limit=settings.max_update_assets)
        signals = SignalEngine().run(db, limit=settings.max_update_assets)
        etf = update_etf_trends(db)
        learning = run_learning_cycle(db, limit=settings.max_update_assets * 6) if settings.enable_learning_loop else {}
        model_learning = run_model_learning_cycle(db, limit=settings.blum_model_cycle_limit) if settings.enable_learning_loop else {}
        return {"market_update": market, "signal_run": signals, "etf_update": etf, "financial_brain_learning": learning, "blum_financial_model": model_learning}

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


def run_autonomous_engine_job() -> None:
    _run_job("autonomous_research_engine", lambda db: AutonomousResearchEngine().run_cycle(db, trigger="scheduled"))


def _run_job(job_name: str, work):
    with _state_lock:
        if _state["running"]:
            return
        _state["running"] = True
        _state["last_started_at"] = datetime.utcnow().isoformat()
        _state["last_job"] = job_name
        _state["last_status"] = "running"
        _state["last_error"] = ""
    try:
        with SessionLocal() as db:
            result = work(db)
        with _state_lock:
            _state["last_completed_at"] = datetime.utcnow().isoformat()
            _state["last_status"] = "ok"
            _state["last_result"] = result or {}
    except Exception as exc:
        with _state_lock:
            _state["last_completed_at"] = datetime.utcnow().isoformat()
            _state["last_status"] = "error"
            _state["last_error"] = f"{type(exc).__name__}: {str(exc)}"
            _state["last_result"] = {"traceback": traceback.format_exc(limit=4)}
    finally:
        with _state_lock:
            _state["running"] = False
