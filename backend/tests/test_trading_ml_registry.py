from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.services.trading_ml.registry import TradingMLModelRegistry, TradingMLPromotionService
from app.services.trading_ml.training import SklearnTradingModelTrainer
from test_trading_ml_training import examples


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def candidate(db, tmp_path, *, sample_count=48):
    result = SklearnTradingModelTrainer().fit(examples(sample_count))
    row = TradingMLModelRegistry(tmp_path).store_candidate(
        db,
        market_family="equity",
        result=result,
        evidence_lane_counts={"REPLAY_EVIDENCE": sample_count},
        asset_count=6,
        regime_count=2,
        setup_count=2,
    )
    return row


def test_low_sample_challenger_is_not_promoted(db, tmp_path):
    row = candidate(db, tmp_path)
    decision = TradingMLPromotionService(tmp_path).evaluate(db, row)
    assert decision.status == "INSUFFICIENT_EVIDENCE"
    assert "minimum_samples" in decision.failed_gates


def test_artifact_hash_mismatch_disables_model(db, tmp_path):
    row = candidate(db, tmp_path)
    row.status = "ACTIVE"
    row.sample_count = 300
    db.commit()
    Path(row.artifact_path).write_bytes(b"tampered")
    loaded = TradingMLModelRegistry(tmp_path).load_active(db, "equity")
    assert loaded.status == "DEGRADED"
    assert loaded.model is None
    db.refresh(row)
    assert row.status == "ACTIVE"


def test_registry_rejects_path_outside_trusted_root(db, tmp_path):
    row = candidate(db, tmp_path)
    row.status = "ACTIVE"
    row.artifact_path = str(tmp_path.parent / "outside.pkl")
    db.commit()
    loaded = TradingMLModelRegistry(tmp_path).load_active(db, "equity")
    assert loaded.status == "DEGRADED"
