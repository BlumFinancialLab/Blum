from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import DashboardSnapshot, DeterministicExecutionRun
from app.services.central_brain_runtime import SnapshotProducerService
from app.services.deterministic_execution.snapshot import DeterministicExecutionSnapshotService


def _db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_empty_snapshot_is_truthful_and_producible():
    db = _db()
    payload = DeterministicExecutionSnapshotService().build(db)
    assert payload["status"] in {"INITIALIZING", "UNAVAILABLE"}
    assert payload["runs"]["total"] == 0

    snapshot = SnapshotProducerService().produce(db, "deterministic_execution_summary")
    assert snapshot["payload"]["mode"] == "SHADOW"


def test_snapshot_read_is_read_only():
    db = _db()
    SnapshotProducerService().produce(db, "deterministic_execution_summary")
    before_runs = db.scalar(select(func.count(DeterministicExecutionRun.id)))
    before_snapshots = db.scalar(select(func.count(DashboardSnapshot.id)))

    first = DeterministicExecutionSnapshotService().latest(db)
    second = DeterministicExecutionSnapshotService().latest(db)

    assert first["snapshot_status"] in {"ready", "stale"}
    assert second["runs"]["total"] == 0
    assert db.scalar(select(func.count(DeterministicExecutionRun.id))) == before_runs
    assert db.scalar(select(func.count(DashboardSnapshot.id))) == before_snapshots
