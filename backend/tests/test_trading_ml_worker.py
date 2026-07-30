from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time

import polars as pl
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    BackgroundJobState,
    BrainRuntimeEvent,
    DashboardSnapshot,
    TradingMLModelVersion,
    TradingMLTrainingRun,
)
from app.services.trading_ml.contracts import InsufficientTrainingEvidenceError
from app.services.trading_ml.dataset import DatasetSlice
from app.services.trading_ml.feature_store import ProjectionResult, _row_from_example
from app.services.trading_ml.registry import TradingMLModelRegistry
from app.services.trading_ml.training import SklearnTradingModelTrainer
from app.services.trading_ml.worker import TradingMLLearningWorker
from test_trading_ml_training import examples


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class FakeProjector:
    def __init__(self, source_count=16):
        self.source_count = source_count
        self.offsets = {"equity": 0, "forex": 0}
        self.rows = {"equity": [], "forex": []}

    def project(self, db, *, market_family, limit):
        offset = self.offsets[market_family]
        source = examples(self.source_count)[offset : offset + limit]
        mapped = [
            replace(
                row,
                source_object_id=f"{market_family}-{offset + index + 1}",
                market_family=market_family,
                features={**dict(row.features), "market_family": market_family},
                asset_key=(f"FX{index % 6}" if market_family == "forex" else row.asset_key),
            )
            for index, row in enumerate(source)
        ]
        self.rows[market_family].extend(mapped)
        self.offsets[market_family] += len(mapped)
        return ProjectionResult(
            rows_written=len(mapped),
            partitions_written=1 if mapped else 0,
            dataset_hash=f"dataset-{market_family}-{self.offsets[market_family]}",
            source_cursor={
                "source_table": "fake",
                "last_source_id": self.offsets[market_family],
                "source_offsets": {"fake": self.offsets[market_family]},
            },
            rows_considered=len(mapped),
            rows_rejected=0,
            is_exhausted=self.offsets[market_family] >= self.source_count,
        )

    def scan(self, *, market_family):
        return pl.DataFrame([_row_from_example(row) for row in self.rows[market_family]]).lazy()

    def manifest(self):
        return {
            "source_cursors": {
                family: {
                    "source_table": "fake",
                    "last_source_id": offset,
                    "source_offsets": {"fake": offset},
                }
                for family, offset in self.offsets.items()
            }
        }


def worker(tmp_path):
    instance = TradingMLLearningWorker(artifact_root=tmp_path, max_rows=8, max_runtime_seconds=30)
    instance.projector = FakeProjector()
    return instance


def test_worker_resumes_cursor_after_budget(db, tmp_path):
    instance = worker(tmp_path)
    first = instance.run_once(db, "test")
    first_cursor = dict(db.query(BackgroundJobState).filter_by(job_name=instance.job_name).one().cursor_json)
    second = instance.run_once(db, "test")
    second_cursor = db.query(BackgroundJobState).filter_by(job_name=instance.job_name).one().cursor_json
    assert first["markets"]["equity"]["status"] == "SHADOW"
    assert second_cursor["equity"]["last_source_id"] >= first_cursor["equity"]["last_source_id"]
    assert db.query(DashboardSnapshot).filter_by(snapshot_type="trading_ml_status").count() == 2
    assert db.query(BrainRuntimeEvent).filter_by(source_module=instance.job_name).count() == 2


def test_worker_isolates_market_family_failure(db, tmp_path, monkeypatch):
    instance = worker(tmp_path)
    original = instance._run_market

    def isolated(session, market_family, trigger, started):
        if market_family == "equity":
            raise RuntimeError("equity lane failed")
        return original(session, market_family, trigger, started)

    monkeypatch.setattr(instance, "_run_market", isolated)
    result = instance.run_once(db, "test")
    assert result["markets"]["equity"]["status"] == "FAILED"
    assert result["markets"]["forex"]["status"] == "SHADOW"


def test_worker_records_insufficient_chronology_as_evidence_gap(db, tmp_path, monkeypatch):
    instance = TradingMLLearningWorker(artifact_root=tmp_path, max_rows=320, max_runtime_seconds=30)
    instance.projector = FakeProjector(source_count=320)

    def insufficient(*args, **kwargs):
        raise InsufficientTrainingEvidenceError(
            "Insufficient chronological history after applying purge and embargo for fold 1"
        )

    monkeypatch.setattr("app.services.trading_ml.worker.BoundedOptunaChallengerSearch.search", insufficient)

    result = instance.run_once(db, "test")

    assert result["status"] == "COMPLETED"
    assert result["markets"]["equity"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["markets"]["forex"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert {
        row.status for row in db.query(TradingMLTrainingRun).all()
    } == {"INSUFFICIENT_EVIDENCE"}


def test_worker_governs_invalid_active_artifact_outside_read_path(db, tmp_path):
    result = SklearnTradingModelTrainer().fit(examples())
    row = TradingMLModelRegistry(tmp_path).store_candidate(
        db,
        market_family="equity",
        result=result,
        asset_count=6,
        regime_count=2,
        setup_count=2,
    )
    row.status = "ACTIVE"
    row.sample_count = 300
    db.commit()
    Path(row.artifact_path).write_bytes(b"tampered")

    instance = worker(tmp_path)
    instance.run_once(db, "test")

    db.refresh(row)
    assert row.status == "DEGRADED"


def test_end_to_end_challenger_audit_chain(db, tmp_path):
    instance = worker(tmp_path)
    result = instance.run_once(db, "certification")
    assert result["markets"]["equity"]["status"] == "SHADOW"
    model = db.query(TradingMLModelVersion).first()
    assert model.dataset_hash
    assert model.artifact_sha256
    assert model.status == "SHADOW"


class FakeFinRLXEngine:
    enabled = True

    def __init__(self):
        self.training_requests = []

    def status(self):
        return {"status": "NO_VALIDATED_ARTIFACT", "paper_only": True}

    def run_training(self, *, market_family, request):
        self.training_requests.append((market_family, request))
        return {
            "status": "VALIDATED_SHADOW",
            "paper_only": True,
            "manifest": {"algorithm": "PPO", "market_family": market_family},
        }


def test_worker_runs_optional_finrlx_research_inside_existing_budget(db, tmp_path):
    instance = worker(tmp_path)
    finrlx = FakeFinRLXEngine()
    instance.finrlx = finrlx

    result = instance.run_once(db, "test")

    assert result["finrlx"]["status"] == "VALIDATED_SHADOW"
    assert finrlx.training_requests[0][0] == "forex"
    assert finrlx.training_requests[0][1]["max_rows"] == 8
    stored = db.query(DashboardSnapshot).filter_by(snapshot_type="trading_ml_status").first()
    assert stored.payload_json["finrlx"]["paper_only"] is True


def test_worker_initializes_finrlx_before_core_lanes_exhaust_budget(
    db,
    tmp_path,
    monkeypatch,
):
    instance = worker(tmp_path)
    instance.max_runtime_seconds = 2
    finrlx = FakeFinRLXEngine()
    instance.finrlx = finrlx

    def consume_budget(session, market_family, trigger, started):
        time.sleep(2.05)
        return {"status": "SHADOW", "rows_considered": 0}

    monkeypatch.setattr(instance, "_run_market", consume_budget)

    result = instance.run_once(db, "test")

    assert result["finrlx"]["status"] == "VALIDATED_SHADOW"
    assert len(finrlx.training_requests) == 1
