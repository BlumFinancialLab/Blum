from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.services.trading_ml.inference import TradingMLInferenceService
from app.services.trading_ml.registry import TradingMLModelRegistry
from app.services.trading_ml.training import SklearnTradingModelTrainer
from test_trading_ml_training import examples


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def active(db, tmp_path):
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
    return result, row


def test_active_model_adjusts_confidence_within_five_points(db, tmp_path):
    result, row = active(db, tmp_path)
    advice = TradingMLInferenceService(TradingMLModelRegistry(tmp_path)).advise(
        db,
        market_family="equity",
        features=dict(examples()[1].features),
        asset_key="A1",
        setup_type="momentum",
        regime="risk_on",
    )
    assert advice.status == "ACTIVE"
    assert abs(advice.confidence_adjustment) <= 5.0
    assert advice.model_uid == row.model_uid


def test_ml_cannot_bypass_deterministic_avoid(db, tmp_path):
    active(db, tmp_path)
    advice = TradingMLInferenceService(TradingMLModelRegistry(tmp_path)).advise(
        db,
        market_family="equity",
        features=dict(examples()[1].features),
        deterministic_blockers=("DETERMINISTIC_NEUTRAL",),
    )
    assert advice.confidence_adjustment == 0.0
    assert "EXISTING_BLOCKER_PRESERVED" in advice.guardrails


def test_write_workflow_persists_one_prediction_per_decision_model(db, tmp_path):
    _, row = active(db, tmp_path)
    service = TradingMLInferenceService(TradingMLModelRegistry(tmp_path))
    for _ in range(2):
        service.advise(
            db,
            market_family="equity",
            features=dict(examples()[1].features),
            source_object_type="historical_prediction",
            source_object_id="42",
            persist=True,
        )
    db.commit()
    from app.models import TradingMLPrediction
    assert db.query(TradingMLPrediction).count() == 1
    assert db.query(TradingMLPrediction).one().model_version_id == row.id
