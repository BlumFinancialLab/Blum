from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.engine.brain.trader_brain import TraderBrainService
from app.main import app
from app.models import DashboardSnapshot, StrategyEvidenceSnapshot, StrategyReadinessHistory
from app.services.copy_readiness_evidence import BlumCopyReadinessEngine
from app.services.live_forward_paper_trading import LiveForwardPaperTradingService


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_rows(db: Session, count: int = 12) -> None:
    for index in range(count):
        strategy_id = f"setup:strategy_{index}"
        db.add(
            StrategyEvidenceSnapshot(
                strategy_id=strategy_id,
                setup_type=f"strategy_{index}",
                evidence_class="PAPER_FORWARD_EVIDENCE",
                closed_trades=index + 1,
                forward_trades=index + 1,
                net_expectancy=0.1,
                evaluated_at=datetime(2026, 7, 14, 10, 0) + timedelta(minutes=index),
            )
        )
        db.add(
            StrategyReadinessHistory(
                strategy_id=strategy_id,
                copy_readiness_status="FORWARD_EVIDENCE_GROWING",
                maturity_score=float(index),
                strategy_forward_trades=index + 1,
                blockers_json=["strategy_forward_sample_below_threshold"],
                real_capital_eligibility="OBSERVE_ONLY",
                evaluated_at=datetime(2026, 7, 14, 10, 1) + timedelta(minutes=index),
            )
        )
    db.commit()


def test_copy_readiness_routes_are_registered():
    paths = {route.path for route in app.routes}

    assert "/api/copy-readiness/strategies" in paths
    assert "/api/copy-readiness/strategies/{strategy_id}" in paths
    assert "/api/copy-readiness/strategies/{strategy_id}/timeline" in paths
    assert "/api/copy-readiness/recalculate" in paths


def test_strategy_get_is_paginated_and_read_only():
    from app.api.routers.copy_readiness import strategies

    with setup_db() as db:
        seed_rows(db, count=30)
        before_cards = db.scalar(select(func.count()).select_from(StrategyEvidenceSnapshot))
        before_history = db.scalar(select(func.count()).select_from(StrategyReadinessHistory))

        response = strategies(limit=10, offset=0, db=db)

        assert len(response["rows"]) == 10
        assert response["has_more"] is True
        assert db.scalar(select(func.count()).select_from(StrategyEvidenceSnapshot)) == before_cards
        assert db.scalar(select(func.count()).select_from(StrategyReadinessHistory)) == before_history


def test_alpha_snapshot_exposes_compact_readiness_without_recalculation(monkeypatch):
    with setup_db() as db:
        seed_rows(db, count=1)
        monkeypatch.setattr(
            BlumCopyReadinessEngine,
            "recalculate",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("GET must not recalculate")),
        )

        payload = TraderBrainService().alpha(db)

        assert payload["copy_readiness"]["total_strategies"] == 1


def test_paper_snapshot_separates_ready_and_not_ready_candidates():
    with setup_db() as db:
        payload = LiveForwardPaperTradingService().snapshot_payload(db)

        assert "copy_readiness" in payload
        assert payload["copy_ready_open_candidates"] == []
        assert payload["not_copy_ready_open_candidates"] == []


def test_recalculate_command_is_bounded_and_refreshes_snapshots():
    from app.api.routers.copy_readiness import recalculate

    with setup_db() as db:
        payload = recalculate(max_items=10, max_strategies=5, db=db)

        assert payload["status"] == "completed"
        assert payload["projection"]["max_items"] == 10
        assert payload["readiness"]["max_strategies"] == 5
        snapshot_types = set(db.scalars(select(DashboardSnapshot.snapshot_type)).all())
        assert {
            "copy_readiness_summary",
            "paper_forward_snapshot",
            "trader_alpha_summary",
        }.issubset(snapshot_types)
