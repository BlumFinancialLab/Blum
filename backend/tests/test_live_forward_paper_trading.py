from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    Asset,
    LiveForwardPaperTrade,
    LiveForwardPaperTradeEvent,
    PaperForwardTrade,
    PaperForwardTradeEvent,
    ModelVersion,
    PriceHistory,
    TradeLearningEvidence,
)
from app.services.learning_loop import BASE_SIGNAL_WEIGHTS
from app.services.live_forward_paper_trading import LiveForwardPaperTradingService


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_asset(db: Session, ticker: str = "NVDA", close: float = 100.0) -> Asset:
    asset = Asset(
        ticker=ticker,
        name=ticker,
        category="Stock",
        sector="Technology",
        country="USA",
        asset_type="Stock",
        currency="USD",
        exchange="NASDAQ",
        is_active=True,
    )
    db.add(asset)
    db.flush()
    db.add(
        PriceHistory(
            asset_id=asset.id,
            date=date.today(),
            open=close - 1,
            high=close + 1,
            low=close - 2,
            close=close,
            volume=1_000_000,
            provider="test",
        )
    )
    db.commit()
    return asset


def add_price(db: Session, asset: Asset, day_offset: int, close: float) -> None:
    db.add(
        PriceHistory(
            asset_id=asset.id,
            date=date.today() + timedelta(days=day_offset),
            open=close - 1,
            high=close + 1,
            low=close - 2,
            close=close,
            volume=1_000_000,
            provider="test",
        )
    )
    db.commit()


def candidate(
    ticker: str = "NVDA",
    price: float | None = 100.0,
    *,
    entry_type: str = "MARKET",
    trigger_price: float | None = None,
    invalidation_level: float = 96.0,
    target_1: float = 105.0,
    target_2: float = 112.0,
) -> dict:
    plan = {
        "entry_type": entry_type,
        "entry_trigger": "close above 100 with volume confirmation",
        "confirmation_condition": "relative volume > 1.5x",
        "invalidation_level": invalidation_level,
        "target_1": target_1,
        "target_2": target_2,
    }
    if trigger_price is not None:
        plan["trigger_price"] = trigger_price
    return {
        "ticker": ticker,
        "asset": {"name": ticker, "asset_type": "Stock", "sector": "Technology"},
        "actionability": "active_setup",
        "sniper_score": 78.0,
        "confidence": 64.0,
        "setup": {"setup_type": "momentum_breakout"},
        "trade_plan": plan,
        "price_context": {"latest_price": price, "data_quality_score": 88.0},
        "market_regime": {"regime_primary": "risk_on"},
    }


def test_live_forward_duplicate_prevention_by_decision_key():
    with setup_db() as db:
        seed_asset(db)
        service = LiveForwardPaperTradingService()
        game = service.active_or_create_live_game(db)

        first = service.open_eligible_trades(db, game, [candidate()])
        second = service.open_eligible_trades(db, game, [candidate()])

        assert len(first["opened"]) == 1
        assert len(second["duplicates"]) == 1
        assert db.scalar(select(func.count(LiveForwardPaperTrade.id)).where(LiveForwardPaperTrade.ticker == "NVDA")) == 1


def test_live_forward_freezes_decision_without_future_prices():
    with setup_db() as db:
        seed_asset(db)
        db.add(ModelVersion(version="live-test-v1", weights={**BASE_SIGNAL_WEIGHTS, "sentiment": 0.5}, previous_weights=BASE_SIGNAL_WEIGHTS, is_active=True))
        db.commit()
        service = LiveForwardPaperTradingService()
        game = service.active_or_create_live_game(db)

        service.open_eligible_trades(db, game, [candidate()])
        trade = db.scalar(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.ticker == "NVDA"))

        assert trade is not None
        assert trade.model_version_used == "live-test-v1"
        assert trade.frozen_decision_payload["no_future_data_policy"].startswith("Frozen payload")
        assert "future_prices" not in trade.frozen_decision_payload
        assert trade.weights_used["sentiment"] > BASE_SIGNAL_WEIGHTS["sentiment"]


def test_live_forward_open_update_close_and_lesson_creation():
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        game = service.active_or_create_live_game(db)
        service.open_eligible_trades(db, game, [candidate()])
        trade = db.scalar(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.status == "OPEN"))
        assert trade is not None

        add_price(db, asset, 1, 106.0)
        updated = service.update_open_trades(db, game)
        lessons = service.publish_lessons(db, updated["closed"])
        db.commit()

        closed = db.get(LiveForwardPaperTrade, trade.id)
        assert closed.status == "CLOSED"
        assert closed.close_reason == "TARGET_1_HIT"
        assert closed.r_multiple is not None
        assert lessons
        assert db.scalar(select(TradeLearningEvidence).where(TradeLearningEvidence.trade_id == closed.ledger_trade_id)) is not None


def test_live_forward_data_blocked_when_no_future_market_data():
    with setup_db() as db:
        seed_asset(db)
        service = LiveForwardPaperTradingService()
        game = service.active_or_create_live_game(db)
        service.open_eligible_trades(db, game, [candidate()])

        updated = service.update_open_trades(db, game)
        events = db.scalars(select(LiveForwardPaperTradeEvent).where(LiveForwardPaperTradeEvent.event_type == "DATA_BLOCKED")).all()

        assert updated["data_blocked"]
        assert events


def test_live_forward_missing_entry_price_creates_data_blocked_decision():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()
        game = service.active_or_create_live_game(db)

        result = service.open_eligible_trades(db, game, [candidate(price=None)])

        assert len(result["data_blocked"]) == 1
        trade = db.scalar(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.status == "DATA_BLOCKED"))
        assert trade is not None
        assert trade.frozen_decision_payload["price_context"]["latest_price"] is None


def test_paper_forward_candidate_foundation_freezes_decision_and_event():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()

        trade = service.create_candidate(db, candidate())
        db.commit()

        stored = db.get(PaperForwardTrade, trade.id)
        event = db.scalar(select(PaperForwardTradeEvent).where(PaperForwardTradeEvent.paper_trade_id == trade.id))
        assert stored is not None
        assert stored.status == "CANDIDATE"
        assert stored.ledger_trade_id is None
        assert stored.open_timestamp is None
        assert stored.decision_payload_frozen["ticker"] == "NVDA"
        assert stored.decision_payload_frozen["no_future_data_policy"].startswith("Frozen payload")
        assert stored.weights_used
        assert event is not None
        assert event.event_type == "DECISION_CREATED"
        assert event.trade_id == trade.id


def test_paper_forward_create_candidate_is_idempotent():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()

        first = service.create_candidate(db, candidate())
        second = service.create_candidate(db, candidate())
        db.commit()

        assert second.id == first.id
        assert db.scalar(select(func.count(PaperForwardTrade.id)).where(PaperForwardTrade.ticker == "NVDA")) == 1


def test_paper_forward_append_event_uses_event_log():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate())

        event = service.append_event(db, trade.id, "POSITION_UPDATED", "manual test event", payload={"check": True}, price_used=101.0)
        db.commit()

        assert event.id is not None
        assert event.trade_id == trade.id
        assert event.payload["check"] is True
        assert event.price_used == 101.0


def test_paper_forward_snapshot_get_is_read_only_without_snapshot():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()

        before = db.scalar(select(func.count(PaperForwardTrade.id)))
        payload = service.snapshot(db)
        after = db.scalar(select(func.count(PaperForwardTrade.id)))

        assert payload["status"] == "missing"
        assert before == after == 0


def test_paper_forward_get_style_methods_are_read_only_and_report_blockers():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()

        before = db.scalar(select(func.count(PaperForwardTrade.id)))
        status = service.status_readonly(db)
        trades = service.paper_trades(db, limit=5)
        detail = service.trade_detail(db, 999)
        events = service.events(db, 999)
        after = db.scalar(select(func.count(PaperForwardTrade.id)))

        assert before == after == 0
        assert status["readiness"] == "NO_SNAPSHOTS"
        assert status["current_blockers"] == ["no_live_forward_paper_game"]
        assert trades["rows"] == []
        assert detail["status"] == "not_found"
        assert events["events"] == []


def test_paper_forward_run_once_freezes_candidates_without_opening_positions():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()
        service.scan_candidates = lambda _db, limit=30: [candidate()]  # type: ignore[method-assign]

        report = service.run_once(db)
        trade = db.scalar(select(PaperForwardTrade).where(PaperForwardTrade.ticker == "NVDA"))
        events = db.scalars(select(PaperForwardTradeEvent).where(PaperForwardTradeEvent.paper_trade_id == trade.id)).all()

        assert report["status"] == "ok"
        assert report["mode"] == "foundation_candidate_freeze"
        assert trade.status == "CANDIDATE"
        assert trade.ledger_trade_id is None
        assert any(event.event_type == "DECISION_CREATED" for event in events)


def test_paper_forward_run_once_duplicate_does_not_overwrite_frozen_payload():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()
        service.scan_candidates = lambda _db, limit=30: [candidate()]  # type: ignore[method-assign]

        first_report = service.run_once(db)
        trade = db.scalar(select(PaperForwardTrade).where(PaperForwardTrade.ticker == "NVDA"))
        frozen_before = dict(trade.decision_payload_frozen)

        service.scan_candidates = lambda _db, limit=30: [candidate(price=100.0) | {"confidence": 12.0}]  # type: ignore[method-assign]
        second_report = service.run_once(db)
        refreshed = db.get(PaperForwardTrade, trade.id)

        assert first_report["created"]
        assert second_report["duplicates"]
        assert db.scalar(select(func.count(PaperForwardTrade.id)).where(PaperForwardTrade.ticker == "NVDA")) == 1
        assert refreshed.id == trade.id
        assert refreshed.decision_payload_frozen == frozen_before
        assert refreshed.decision_payload_frozen["confidence"] == 64.0


def test_paper_forward_lifecycle_opens_candidate_when_trigger_is_met():
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate(entry_type="ABOVE_TRIGGER", trigger_price=102.0, target_1=130.0, target_2=150.0))
        frozen_before = dict(trade.frozen_decision_payload)
        add_price(db, asset, 1, 103.0)

        report = service.run_lifecycle(db)
        opened = db.get(PaperForwardTrade, trade.id)
        events = db.scalars(select(PaperForwardTradeEvent).where(PaperForwardTradeEvent.paper_trade_id == trade.id)).all()

        assert report["status"] == "ok"
        assert opened.status == "OPEN"
        assert opened.open_price == 103.0
        assert opened.ledger_trade_id is not None
        assert opened.decision_payload_frozen == frozen_before
        assert any(event.event_type == "ENTRY_TRIGGERED" for event in events)
        assert any(event.event_type == "POSITION_OPENED" for event in events)


def test_paper_forward_lifecycle_keeps_candidate_when_trigger_not_met():
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate(entry_type="ABOVE_TRIGGER", trigger_price=104.0, target_1=130.0, target_2=150.0))
        add_price(db, asset, 1, 101.0)

        report = service.run_lifecycle(db)
        stored = db.get(PaperForwardTrade, trade.id)
        opened_events = db.scalars(
            select(PaperForwardTradeEvent).where(PaperForwardTradeEvent.paper_trade_id == trade.id, PaperForwardTradeEvent.event_type == "POSITION_OPENED")
        ).all()

        assert report["phases"]["open_eligible_trades"]["waiting"]
        assert stored.status == "CANDIDATE"
        assert opened_events == []


def test_paper_forward_lifecycle_data_blocked_when_market_data_missing():
    with setup_db() as db:
        seed_asset(db)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate())

        report = service.run_lifecycle(db)
        stored = db.get(PaperForwardTrade, trade.id)
        events = db.scalars(select(PaperForwardTradeEvent).where(PaperForwardTradeEvent.paper_trade_id == trade.id)).all()

        assert stored.status == "CANDIDATE"
        assert report["phases"]["open_eligible_trades"]["data_blocked"]
        assert any(event.event_type == "DATA_BLOCKED" for event in events)


def test_paper_forward_lifecycle_updates_open_trade_unrealized_pnl():
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate(target_1=130.0, target_2=150.0))
        add_price(db, asset, 1, 100.0)
        service.run_lifecycle(db)
        add_price(db, asset, 2, 103.0)

        report = service.run_lifecycle(db)
        refreshed = db.get(PaperForwardTrade, trade.id)
        events = db.scalars(select(PaperForwardTradeEvent).where(PaperForwardTradeEvent.paper_trade_id == trade.id)).all()

        assert refreshed.status == "OPEN"
        assert refreshed.current_price == 103.0
        assert refreshed.unrealized_pnl > 0
        assert report["phases"]["update_open_trades"]["updated"]
        assert any(event.event_type == "POSITION_UPDATED" for event in events)


def test_paper_forward_lifecycle_stop_hit_closes_trade_and_calculates_pnl():
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate(invalidation_level=96.0, target_1=130.0, target_2=150.0))
        add_price(db, asset, 1, 100.0)
        service.run_lifecycle(db)
        add_price(db, asset, 2, 94.0)

        service.run_lifecycle(db)
        closed = db.get(PaperForwardTrade, trade.id)
        events = db.scalars(select(PaperForwardTradeEvent).where(PaperForwardTradeEvent.paper_trade_id == trade.id)).all()

        assert closed.status == "CLOSED"
        assert closed.close_reason == "STOP_HIT"
        assert closed.outcome == "LOSS"
        assert closed.pnl_per_share == -6.0
        assert closed.pnl_percent < 0
        assert closed.r_multiple < 0
        assert any(event.event_type == "STOP_HIT" for event in events)
        assert any(event.event_type == "POSITION_CLOSED" for event in events)


def test_paper_forward_lifecycle_target_hit_closes_with_lesson_and_audit_events():
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate(target_1=104.0, target_2=150.0))
        add_price(db, asset, 1, 100.0)
        service.run_lifecycle(db)
        add_price(db, asset, 2, 106.0)

        service.run_lifecycle(db)
        closed = db.get(PaperForwardTrade, trade.id)
        events = db.scalars(select(PaperForwardTradeEvent).where(PaperForwardTradeEvent.paper_trade_id == trade.id)).all()
        lesson = db.scalar(select(TradeLearningEvidence).where(TradeLearningEvidence.trade_id == closed.ledger_trade_id))

        assert closed.status == "CLOSED"
        assert closed.close_reason == "TARGET_1_HIT"
        assert closed.outcome == "WIN"
        assert closed.net_pnl_eur > 0
        assert lesson is not None
        assert lesson.supporting_trades_json["paper_forward_trade_id"] == closed.id
        assert any(event.event_type == "TARGET_HIT" for event in events)
        assert any(event.event_type == "OUTCOME_EVALUATED" for event in events)
        assert any(event.event_type == "LESSON_CREATED" for event in events)


def test_paper_forward_lifecycle_expiry_closes_trade():
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate(target_1=130.0, target_2=150.0))
        add_price(db, asset, 1, 100.0)
        service.run_lifecycle(db)
        opened = db.get(PaperForwardTrade, trade.id)
        opened.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
        add_price(db, asset, 2, 101.0)

        service.run_lifecycle(db)
        closed = db.get(PaperForwardTrade, trade.id)

        assert closed.status == "EXPIRED"
        assert closed.close_reason == "TIME_EXIT"
        assert closed.close_price == 101.0


def test_paper_forward_lifecycle_invalidation_closes_trade():
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate(invalidation_level=96.0, target_1=130.0, target_2=150.0))
        add_price(db, asset, 1, 100.0)
        service.run_lifecycle(db)
        opened = db.get(PaperForwardTrade, trade.id)
        opened.stop_loss = None
        db.commit()
        add_price(db, asset, 2, 95.0)

        service.run_lifecycle(db)
        closed = db.get(PaperForwardTrade, trade.id)

        assert closed.status == "INVALIDATED"
        assert closed.close_reason == "INVALIDATION_HIT"
        assert closed.invalidation_hit is True


def test_paper_forward_lifecycle_is_idempotent_after_open_and_close():
    with setup_db() as db:
        asset = seed_asset(db)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate(target_1=104.0, target_2=150.0))
        add_price(db, asset, 1, 100.0)
        service.run_lifecycle(db)
        add_price(db, asset, 2, 106.0)
        service.run_lifecycle(db)
        event_count = db.scalar(select(func.count(PaperForwardTradeEvent.id)).where(PaperForwardTradeEvent.paper_trade_id == trade.id))
        lesson_count = db.scalar(select(func.count(TradeLearningEvidence.id)))

        service.run_lifecycle(db)
        event_count_after = db.scalar(select(func.count(PaperForwardTradeEvent.id)).where(PaperForwardTradeEvent.paper_trade_id == trade.id))
        lesson_count_after = db.scalar(select(func.count(TradeLearningEvidence.id)))

        assert event_count_after == event_count
        assert lesson_count_after == lesson_count


def test_paper_forward_lifecycle_calculates_benchmark_excess_when_available():
    with setup_db() as db:
        asset = seed_asset(db)
        spy = seed_asset(db, ticker="SPY", close=100.0)
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(db, candidate(target_1=104.0, target_2=150.0))
        add_price(db, asset, 1, 100.0)
        add_price(db, spy, 1, 101.0)
        service.run_lifecycle(db)
        add_price(db, asset, 2, 106.0)
        add_price(db, spy, 2, 102.0)

        service.run_lifecycle(db)
        closed = db.get(PaperForwardTrade, trade.id)

        assert closed.benchmark_return is not None
        assert closed.benchmark_excess is not None
        assert closed.benchmark_excess > 0


def test_paper_forward_scheduler_uses_foundation_run_once_not_lifecycle_run_cycle():
    source = (Path(__file__).resolve().parents[1] / "app" / "services" / "realtime.py").read_text()
    start = source.index("def run_live_forward_paper_trading_job")
    block = source[start : source.index("\n\ndef ", start + 1)]

    assert ".run_once(db)" in block
    assert "paper_forward_lifecycle_enabled" in block
    assert ".run_cycle(db)" not in block
