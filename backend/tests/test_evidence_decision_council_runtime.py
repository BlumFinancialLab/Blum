from datetime import datetime

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import AgentCouncilRun, BackgroundJobState, DashboardSnapshot
from app.services.central_brain_runtime import SnapshotProducerService
from app.services.decision_council import DecisionCouncilSnapshotService, DecisionCouncilWorker


def _db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_worker_is_bounded_and_records_cursor_on_empty_database():
    db = _db()

    result = DecisionCouncilWorker().run(db, max_items=3, max_seconds=1, now=datetime(2026, 8, 3))

    state = db.scalar(select(BackgroundJobState).where(BackgroundJobState.job_name == "evidence_decision_council"))
    assert result["status"] == "COMPLETED"
    assert result["budgets"] == {"max_items": 3, "max_seconds": 1}
    assert state.cursor_json == {"knowledge_record_id": 0}


def test_snapshot_get_is_read_only():
    db = _db()
    SnapshotProducerService().produce(db, "decision_council_summary")
    before_runs = db.scalar(select(func.count(AgentCouncilRun.id)))
    before_snapshots = db.scalar(select(func.count(DashboardSnapshot.id)))

    first = DecisionCouncilSnapshotService().latest(db)
    second = DecisionCouncilSnapshotService().latest(db)

    assert first["snapshot_status"] in {"ready", "stale"}
    assert second["runs"]["total"] == 0
    assert db.scalar(select(func.count(AgentCouncilRun.id))) == before_runs
    assert db.scalar(select(func.count(DashboardSnapshot.id))) == before_snapshots
