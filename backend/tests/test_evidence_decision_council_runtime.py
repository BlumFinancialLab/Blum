from datetime import datetime

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import AgentCouncilRun, BackgroundJobState, BlumKnowledgeRecord, DashboardSnapshot, EngineVote
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


def test_worker_prioritizes_recent_records_with_independent_votes():
    db = _db()
    for index in range(3):
        record = BlumKnowledgeRecord(
            ticker=f"T{index}",
            sector="Technology",
            source_type="test",
            reasoning_hash=f"runtime-{index}",
            market_regime="risk_on",
            confidence=70,
            blum_reasoning={"trade_plan": {"risk_reward": 2.0, "invalidation_level": 90.0}},
            created_at=datetime(2026, 8, index + 1),
            updated_at=datetime(2026, 8, index + 1),
        )
        db.add(record)
        db.flush()
        for engine_name in ("technical_engine", "regime_engine"):
            db.add(EngineVote(thesis_id=record.id, ticker=record.ticker, engine_name=engine_name, vote="bullish", confidence=70, evidence_quality=80, horizon="swing", regime="risk_on", sector="Technology", created_at=datetime(2026, 8, index + 1)))
    db.commit()

    result = DecisionCouncilWorker().run(db, max_items=1, max_seconds=2, now=datetime(2026, 8, 4))

    latest = db.scalar(select(AgentCouncilRun).order_by(AgentCouncilRun.id.desc()).limit(1))
    assert result["processed"] == 1
    assert latest.ticker == "T2"
