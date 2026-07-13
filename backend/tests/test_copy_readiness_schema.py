from __future__ import annotations

from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import EvidenceTimelineEvent, StrategyEvidenceSnapshot, StrategyReadinessHistory


def test_evidence_tables_support_sqlite_json():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        row = StrategyEvidenceSnapshot(
            strategy_id="setup:momentum_breakout",
            setup_type="momentum_breakout",
            evidence_class="REPLAY_EVIDENCE",
            metrics_json={"sample_size": 50},
            markets_json=["US"],
            timeframes_json=["1d"],
            warnings_json=[],
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        assert row.metrics_json["sample_size"] == 50
        assert row.markets_json == ["US"]
        assert row.timeframes_json == ["1d"]
        assert row.warnings_json == []


def test_timeline_event_key_is_unique():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(EvidenceTimelineEvent(event_key="trade:42:closed", event_type="TRADE_CLOSED"))
        db.commit()

        db.add(EvidenceTimelineEvent(event_key="trade:42:closed", event_type="TRADE_CLOSED"))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("duplicate evidence timeline event key was accepted")


def test_evidence_schema_has_latest_read_indexes():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    evidence_indexes = {index["name"] for index in inspector.get_indexes("strategy_evidence_snapshots")}
    readiness_indexes = {index["name"] for index in inspector.get_indexes("strategy_readiness_history")}
    timeline_indexes = {index["name"] for index in inspector.get_indexes("evidence_timeline_events")}

    assert "ix_strategy_evidence_snapshots_latest" in evidence_indexes
    assert "ix_strategy_readiness_history_latest" in readiness_indexes
    assert "ix_evidence_timeline_events_strategy_time" in timeline_indexes


def test_readiness_history_persists_gate_decision_json():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        row = StrategyReadinessHistory(
            strategy_id="setup:momentum_breakout",
            copy_readiness_status="FORWARD_EVIDENCE_LOW",
            passed_gates_json=["replay_evidence"],
            failed_gates_json=["strategy_forward_trades"],
            reasons_json=["More closed forward trades are required."],
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        assert row.failed_gates_json == ["strategy_forward_trades"]
