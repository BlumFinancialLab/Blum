from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    EvidenceTimelineEvent,
    LiveForwardPaperGame,
    LiveForwardPaperTrade,
    StrategyEvidenceSnapshot,
    StrategyReadinessHistory,
)
from app.services.copy_readiness_evidence import copy_readiness_projections
from app.services.live_forward_paper_trading import LiveForwardPaperTradingService
from app.services.trading_intelligence_lab import serialize_paper_forward_trade


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_trade(db: Session, *, setup_type: str = "momentum_breakout") -> LiveForwardPaperTrade:
    game = LiveForwardPaperGame(
        game_id="readiness-game",
        status="active",
        starting_capital=100.0,
        current_capital=100.0,
        cash=100.0,
        exposure=0.0,
        open_positions=0,
        benchmark_ticker="SPY",
    )
    db.add(game)
    db.flush()
    trade = LiveForwardPaperTrade(
        trade_uid="readiness-trade",
        game_id=game.id,
        ticker="NVDA",
        setup_type=setup_type,
        status="CANDIDATE",
        decision_timestamp=datetime(2026, 7, 14, 10, 0),
        decision_date=date(2026, 7, 14),
        duplicate_key="readiness-trade-key",
        actionability_state="active_setup",
        frozen_decision_payload={
            "immutable": True,
            "market_regime": {"regime_primary": "risk_on"},
            "trade_plan": {"invalidation_level": 95.0},
        },
    )
    db.add(trade)
    db.flush()
    return trade


def seed_readiness(
    db: Session,
    *,
    status: str = "FORWARD_EVIDENCE_GROWING",
    eligibility: str = "OBSERVE_ONLY",
) -> None:
    db.add(
        StrategyEvidenceSnapshot(
            strategy_id="setup:momentum_breakout",
            setup_type="momentum_breakout",
            evidence_class="PAPER_FORWARD_EVIDENCE",
            total_trades=12,
            closed_trades=12,
            forward_trades=12,
            net_expectancy=0.18,
            benchmark_excess=None,
            total_costs=None,
            concentration_json={"tickers": {"top_share": 0.5}},
            confidence_interval_json={"lower": 0.31, "upper": 0.72},
            warnings_json=["benchmark_unavailable"],
            evaluated_at=datetime(2026, 7, 14, 9, 0),
        )
    )
    db.add(
        StrategyReadinessHistory(
            strategy_id="setup:momentum_breakout",
            copy_readiness_status=status,
            maturity_score=42.0,
            global_forward_trades=12,
            strategy_forward_trades=12,
            observation_days=20,
            blockers_json=["benchmark_excess_unavailable"],
            reasons_json=["Forward evidence remains below promotion gates."],
            real_capital_eligibility=eligibility,
            threshold_version="test-v1",
            evaluated_at=datetime(2026, 7, 14, 9, 5),
        )
    )
    db.flush()


def test_candidate_with_immature_strategy_is_not_copy_ready():
    with setup_db() as db:
        trade = seed_trade(db)
        seed_readiness(db)

        readiness = copy_readiness_projections(db, [trade])[trade.id]
        payload = serialize_paper_forward_trade(trade, compact=True, readiness=readiness)

        assert payload["copy_readiness_status"] == "NOT_COPY_READY"
        assert payload["strategy_readiness_status"] == "FORWARD_EVIDENCE_GROWING"
        assert payload["paper_trading_actionability"] == "active_setup"
        assert payload["benchmark_context"]["benchmark_excess"] is None
        assert payload["estimated_costs"] is None
        assert payload["evidence_warning"]


def test_ready_strategy_exposes_research_only_capital_classification():
    with setup_db() as db:
        trade = seed_trade(db)
        seed_readiness(
            db,
            status="COPY_READY_HIGH_CONFIDENCE",
            eligibility="ELIGIBLE_FOR_LIMITED_EXTERNAL_VALIDATION",
        )

        readiness = copy_readiness_projections(db, [trade])[trade.id]
        payload = serialize_paper_forward_trade(trade, compact=True, readiness=readiness)

        assert payload["copy_readiness_status"] == "COPY_READY_HIGH_CONFIDENCE"
        assert payload["real_capital_eligibility"] == "ELIGIBLE_FOR_LIMITED_EXTERNAL_VALIDATION"
        assert "research classification" in payload["reason_to_copy"].lower()


def test_trade_list_batch_enriches_rows_without_recalculating_readiness():
    with setup_db() as db:
        trade = seed_trade(db)
        seed_readiness(db)

        payload = LiveForwardPaperTradingService().paper_trades(db, limit=25)

        assert payload["rows"][0]["trade_id"] == trade.id
        assert payload["rows"][0]["copy_readiness_status"] == "NOT_COPY_READY"
        assert db.scalar(select(func.count()).select_from(StrategyReadinessHistory)) == 1


def test_lifecycle_event_is_mirrored_once_and_frozen_payload_is_unchanged():
    with setup_db() as db:
        trade = seed_trade(db)
        before = deepcopy(trade.frozen_decision_payload)
        service = LiveForwardPaperTradingService()

        service.append_event_once(
            db,
            trade,
            "POSITION_UPDATED",
            "Marked to new paper price.",
            payload={"current_r_multiple": 0.4},
            price_used=101.0,
        )
        service.append_event_once(
            db,
            trade,
            "POSITION_UPDATED",
            "Duplicate mark.",
            payload={"current_r_multiple": 0.4},
            price_used=101.0,
        )
        db.flush()

        assert trade.frozen_decision_payload == before
        assert db.scalar(select(func.count()).select_from(EvidenceTimelineEvent)) == 1
        event = db.scalar(select(EvidenceTimelineEvent))
        assert event is not None
        assert event.event_type == "trade_updated"
        assert event.strategy_id == "setup:momentum_breakout"
