from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes import router, trading_ml_status
from app.core.database import Base
from app.services.dashboard_snapshots import DashboardSnapshotService
from app.services.trading_ml.worker import TradingMLLearningWorker


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_status_get_never_runs_training(monkeypatch, db):
    monkeypatch.setattr(
        TradingMLLearningWorker,
        "run_once",
        lambda *args, **kwargs: pytest.fail("GET triggered training"),
    )
    payload = trading_ml_status(db)
    assert payload["status"] == "INITIALIZING"
    assert payload["training_triggered"] is False


def test_status_get_reads_snapshot_only(monkeypatch, db):
    DashboardSnapshotService().write(db, "trading_ml_status", {"status": "SHADOW", "markets": {}})
    monkeypatch.setattr(
        TradingMLLearningWorker,
        "run_once",
        lambda *args, **kwargs: pytest.fail("GET triggered training"),
    )
    payload = trading_ml_status(db)
    assert payload["status"] == "SHADOW"
    assert payload["training_triggered"] is False


def test_trading_ml_routes_include_explicit_get_and_post():
    routes = {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}
    assert ("/api/trading-ml/status", ("GET",)) in routes
    assert ("/api/trading-ml/run", ("POST",)) in routes
