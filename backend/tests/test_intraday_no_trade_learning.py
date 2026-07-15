from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Asset, IntradayNoTradeDecision, IntradayPaperRun, ReplayMarketBar, StrategyMemory, TradeLearningEvidence
from app.services.intraday_contracts import INTRADAY_BLOCKED, IntradayDecision
from app.services.intraday_no_trade_learning import IntradayNoTradeLearningService
from app.services.intraday_paper_engine import intraday_snapshot_summary


NOW = datetime(2026, 7, 15, 14, 30)


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_asset(db: Session, ticker: str = "NVDA") -> Asset:
    asset = Asset(
        ticker=ticker,
        name=ticker,
        category="Stock",
        asset_type="Stock",
        sector="Technology",
        country="United States",
        exchange="NASDAQ",
        currency="USD",
    )
    db.add(asset)
    db.flush()
    return asset


def decision(*, reason: str = "COSTS_KILL_EDGE") -> IntradayDecision:
    return IntradayDecision(
        status=INTRADAY_BLOCKED,
        reason_code=reason,
        explanation="Rejected by a strict execution gate.",
        ticker="NVDA",
        market="USA",
        desk="NasdaqAgent",
        benchmark_ticker="QQQ",
        strategy_id="intraday:breakout",
        validation_id=10,
        setup_type="intraday_breakout",
        decision_timestamp=NOW,
        entry_price=100.0,
        expected_move_bps=30.0,
        net_expectancy_bps=-5.0,
        regime="trend_up",
        session="regular",
        costs={"total_round_trip_bps": 35.0},
    )


def future_bar(db: Session, asset: Asset, *, close: float, minutes: int = 31) -> None:
    db.add(
        ReplayMarketBar(
            asset_id=asset.id,
            source_symbol=asset.ticker,
            normalized_symbol=asset.ticker,
            market="USA",
            timeframe="1m",
            bar_timestamp=NOW + timedelta(minutes=minutes),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1_000_000,
            provider="fixture",
            acquired_at=NOW + timedelta(minutes=minutes),
            data_quality_score=95.0,
            source_metadata={},
        )
    )


def test_no_trade_decision_is_frozen_and_idempotent() -> None:
    with setup_db() as db:
        asset = seed_asset(db)
        run = IntradayPaperRun(run_uid="run-1", trigger="test", status="RUNNING", started_at=NOW)
        db.add(run)
        db.flush()
        service = IntradayNoTradeLearningService(evaluation_minutes=30)

        first = service.record(db, run=run, asset=asset, decision=decision())
        duplicate = service.record(db, run=run, asset=asset, decision=decision())

    assert first.id == duplicate.id
    assert first.status == "PENDING"
    assert first.theoretical_price == 100.0
    assert first.decision_payload["reason_code"] == "COSTS_KILL_EDGE"


def test_future_outperformance_marks_missed_opportunity_and_updates_memory() -> None:
    with setup_db() as db:
        asset = seed_asset(db)
        run = IntradayPaperRun(run_uid="run-2", trigger="test", status="RUNNING", started_at=NOW)
        db.add(run)
        db.flush()
        service = IntradayNoTradeLearningService(evaluation_minutes=30)
        row = service.record(db, run=run, asset=asset, decision=decision(reason="WAITING_FOR_TRIGGER"))
        future_bar(db, asset, close=101.0)
        db.flush()

        result = service.evaluate_due(db, now=NOW + timedelta(minutes=31))
        db.refresh(row)
        evidence = db.scalar(select(TradeLearningEvidence).where(TradeLearningEvidence.action_taken == f"intraday_no_trade:{row.id}"))
        memory = db.scalar(select(StrategyMemory).where(StrategyMemory.memory_key == "intraday_no_trade:WAITING_FOR_TRIGGER:USA:trend_up"))

    assert result["evaluated"] == 1
    assert row.outcome_label == "MISSED_OPPORTUNITY"
    assert row.opportunity_cost > 0
    assert evidence.lesson_type == "no_trade_filter_missed_opportunity"
    assert memory.negative_count == 1


def test_decline_after_rejection_marks_correct_no_trade() -> None:
    with setup_db() as db:
        asset = seed_asset(db)
        run = IntradayPaperRun(run_uid="run-3", trigger="test", status="RUNNING", started_at=NOW)
        db.add(run)
        db.flush()
        service = IntradayNoTradeLearningService(evaluation_minutes=30)
        row = service.record(db, run=run, asset=asset, decision=decision(reason="LIQUIDITY_TOO_LOW"))
        future_bar(db, asset, close=98.0)
        db.flush()

        service.evaluate_due(db, now=NOW + timedelta(minutes=31))
        db.refresh(row)

    assert row.outcome_label == "CORRECT_NO_TRADE"
    assert row.capital_preserved > 0


def test_no_future_bar_keeps_decision_pending() -> None:
    with setup_db() as db:
        asset = seed_asset(db)
        run = IntradayPaperRun(run_uid="run-4", trigger="test", status="RUNNING", started_at=NOW)
        db.add(run)
        db.flush()
        service = IntradayNoTradeLearningService(evaluation_minutes=30)
        row = service.record(db, run=run, asset=asset, decision=decision())

        result = service.evaluate_due(db, now=NOW + timedelta(minutes=31))
        db.refresh(row)

    assert result["evaluated"] == 0
    assert row.status == "PENDING"


def test_intraday_snapshot_exposes_no_trade_learning_counts() -> None:
    with setup_db() as db:
        asset = seed_asset(db)
        run = IntradayPaperRun(run_uid="run-5", trigger="test", status="RUNNING", started_at=NOW)
        db.add(run)
        db.flush()
        service = IntradayNoTradeLearningService(evaluation_minutes=30)
        service.record(db, run=run, asset=asset, decision=decision(reason="LIQUIDITY_TOO_LOW"))
        future_bar(db, asset, close=98.0)
        service.evaluate_due(db, now=NOW + timedelta(minutes=31))
        db.flush()

        snapshot = intraday_snapshot_summary(db, now=NOW + timedelta(minutes=31))

    assert snapshot["no_trade_evidence"]["CORRECT_NO_TRADE"] == 1
    assert snapshot["no_trade_pending"] == 0
