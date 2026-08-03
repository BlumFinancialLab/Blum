from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import Base
from app.models import EvidenceTimelineEvent, StrategyEvidenceSnapshot, StrategyReadinessHistory


BACKEND_ROOT = Path(__file__).resolve().parents[1]
COPY_READINESS_TABLES = (
    "strategy_evidence_snapshots",
    "strategy_readiness_history",
    "evidence_timeline_events",
)


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _upgrade_copy_readiness_from_predecessor(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'copy-readiness.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()

    config = _alembic_config(database_url)
    command.stamp(config, "0031_intraday_paper")
    command.upgrade(config, "0032_copy_readiness_evidence")
    return config, database_url


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


def test_unknown_numeric_values_remain_null_and_measured_zero_is_preserved():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    evidence_columns = StrategyEvidenceSnapshot.__table__.c
    readiness_columns = StrategyReadinessHistory.__table__.c
    for column in (
        evidence_columns.total_trades,
        evidence_columns.closed_trades,
        evidence_columns.forward_trades,
        readiness_columns.maturity_score,
        readiness_columns.global_forward_trades,
        readiness_columns.strategy_forward_trades,
        readiness_columns.observation_days,
    ):
        assert column.nullable
        assert column.default is None
        assert column.server_default is None

    with Session(engine) as db:
        unknown_evidence = StrategyEvidenceSnapshot(
            strategy_id="setup:unknown",
            setup_type="unknown",
            evidence_class="REPLAY_EVIDENCE",
        )
        measured_zero_evidence = StrategyEvidenceSnapshot(
            strategy_id="setup:zero",
            setup_type="zero",
            evidence_class="FORWARD_EVIDENCE",
            total_trades=0,
            closed_trades=0,
            forward_trades=0,
        )
        unknown_readiness = StrategyReadinessHistory(
            strategy_id="setup:unknown",
            copy_readiness_status="UNKNOWN",
        )
        measured_zero_readiness = StrategyReadinessHistory(
            strategy_id="setup:zero",
            copy_readiness_status="FORWARD_EVIDENCE_LOW",
            maturity_score=0.0,
            global_forward_trades=0,
            strategy_forward_trades=0,
            observation_days=0,
        )
        db.add_all(
            (unknown_evidence, measured_zero_evidence, unknown_readiness, measured_zero_readiness)
        )
        db.commit()
        db.refresh(unknown_evidence)
        db.refresh(measured_zero_evidence)
        db.refresh(unknown_readiness)
        db.refresh(measured_zero_readiness)

        assert unknown_evidence.total_trades is None
        assert unknown_evidence.closed_trades is None
        assert unknown_evidence.forward_trades is None
        assert measured_zero_evidence.total_trades == 0
        assert measured_zero_evidence.closed_trades == 0
        assert measured_zero_evidence.forward_trades == 0
        assert unknown_readiness.maturity_score is None
        assert unknown_readiness.global_forward_trades is None
        assert unknown_readiness.strategy_forward_trades is None
        assert unknown_readiness.observation_days is None
        assert measured_zero_readiness.maturity_score == 0.0
        assert measured_zero_readiness.global_forward_trades == 0
        assert measured_zero_readiness.strategy_forward_trades == 0
        assert measured_zero_readiness.observation_days == 0


def test_confidence_interval_json_remains_nullable_without_a_default():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    column = StrategyEvidenceSnapshot.__table__.c.confidence_interval_json
    assert column.nullable
    assert column.default is None
    assert column.server_default is None

    with Session(engine) as db:
        row = StrategyEvidenceSnapshot(
            strategy_id="setup:summary_only",
            setup_type="summary_only",
            evidence_class="WALK_FORWARD_EVIDENCE",
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        assert row.confidence_interval_json is None


def test_copy_readiness_migration_is_append_only_and_round_trips_on_sqlite(tmp_path, monkeypatch):
    config, database_url = _upgrade_copy_readiness_from_predecessor(tmp_path, monkeypatch)
    engine = create_engine(database_url, future=True)

    with engine.begin() as connection:
        inspector = inspect(connection)
        assert set(COPY_READINESS_TABLES).issubset(inspector.get_table_names())
        assert {
            column["name"]: column for column in inspector.get_columns("strategy_evidence_snapshots")
        }["total_trades"]["nullable"]
        assert {
            column["name"]: column for column in inspector.get_columns("strategy_readiness_history")
        }["maturity_score"]["nullable"]
        assert {
            column["name"]: column for column in inspector.get_columns("strategy_evidence_snapshots")
        }["confidence_interval_json"]["nullable"]
        assert connection.execute(
            sa.text(
                "INSERT INTO strategy_evidence_snapshots "
                "(strategy_id, setup_type, evidence_class, evaluated_at, created_at) "
                "VALUES ('setup:one', 'one', 'REPLAY_EVIDENCE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        ).rowcount == 1
        assert connection.execute(
            sa.text(
                "INSERT INTO strategy_readiness_history "
                "(strategy_id, copy_readiness_status, evaluated_at, created_at) "
                "VALUES ('setup:one', 'UNKNOWN', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        ).rowcount == 1
        assert connection.execute(
            sa.text(
                "INSERT INTO evidence_timeline_events "
                "(event_key, event_type, event_timestamp, created_at) "
                "VALUES ('event:one', 'EVALUATED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        ).rowcount == 1

        for table_name in COPY_READINESS_TABLES:
            with pytest.raises(IntegrityError, match="append-only"):
                connection.execute(sa.text(f"UPDATE {table_name} SET id = id"))
            with pytest.raises(IntegrityError, match="append-only"):
                connection.execute(sa.text(f"DELETE FROM {table_name}"))

    engine.dispose()
    command.downgrade(config, "0031_intraday_paper")

    engine = create_engine(database_url, future=True)
    with engine.connect() as connection:
        inspector = inspect(connection)
        assert not set(COPY_READINESS_TABLES).intersection(inspector.get_table_names())
        trigger_names = {
            row[0]
            for row in connection.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
            )
        }
        assert not any(name.startswith("prevent_copy_readiness_") for name in trigger_names)
    engine.dispose()

    command.upgrade(config, "0032_copy_readiness_evidence")
    engine = create_engine(database_url, future=True)
    with engine.connect() as connection:
        inspector = inspect(connection)
        assert set(COPY_READINESS_TABLES).issubset(inspector.get_table_names())
        trigger_names = {
            row[0]
            for row in connection.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
            )
        }
        for table_name in COPY_READINESS_TABLES:
            assert f"prevent_copy_readiness_{table_name}_update" in trigger_names
            assert f"prevent_copy_readiness_{table_name}_delete" in trigger_names
    engine.dispose()
    get_settings.cache_clear()
