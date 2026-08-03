from datetime import datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import BackgroundJobState
from app.services.deterministic_execution.catalog import CatalogProjectionResult
from app.services.deterministic_execution.worker import DeterministicExecutionWorker


class UnavailableProjector:
    def project(self, db, *, cursor, limit, runtime_now):
        return CatalogProjectionResult("UNAVAILABLE", cursor or {"replay_market_bar_id": 0}, reason="wheel missing")


def test_worker_survives_unavailable_kernel_and_persists_cursor():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = Session(engine)
    result = DeterministicExecutionWorker(projector=UnavailableProjector()).run(
        db,
        max_items=2,
        max_seconds=1,
        now=datetime(2026, 8, 3),
    )

    state = db.scalar(select(BackgroundJobState).where(BackgroundJobState.job_name == "deterministic_execution_core"))
    assert result["status"] == "degraded"
    assert state.status == "completed"
    assert state.cursor_json == {"replay_market_bar_id": 0, "paper_trade_id": 0}


def test_worker_budget_is_bounded():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = Session(engine)
    result = DeterministicExecutionWorker(projector=UnavailableProjector()).run(db, max_items=1, max_seconds=1)
    assert result["budgets"] == {"max_items": 1, "max_seconds": 1}
