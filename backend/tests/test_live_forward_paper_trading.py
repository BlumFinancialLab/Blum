from datetime import date, timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    Asset,
    LiveForwardPaperTrade,
    LiveForwardPaperTradeEvent,
    ModelVersion,
    PriceHistory,
    TradeLearningEvidence,
)
from app.services.learning_loop import BASE_SIGNAL_WEIGHTS
from app.services.trading_intelligence_lab import LiveForwardPaperTradingService


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


def candidate(ticker: str = "NVDA", price: float | None = 100.0) -> dict:
    return {
        "ticker": ticker,
        "asset": {"name": ticker, "asset_type": "Stock", "sector": "Technology"},
        "actionability": "active_setup",
        "sniper_score": 78.0,
        "confidence": 64.0,
        "setup": {"setup_type": "momentum_breakout"},
        "trade_plan": {
            "entry_trigger": "close above 100 with volume confirmation",
            "confirmation_condition": "relative volume > 1.5x",
            "invalidation_level": 96.0,
            "target_1": 105.0,
            "target_2": 112.0,
        },
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
