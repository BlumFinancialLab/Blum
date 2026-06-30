from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Asset, SniperScore, TradePlan, TradingGame, TradingGameTrade
from app.services.copy_trading_intelligence import CopyTradingIntelligenceService


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_copy_trading_dashboard_is_paper_only_and_uses_stored_trade_plan():
    with setup_db() as db:
        asset = Asset(
            ticker="NVDA",
            name="NVIDIA Corporation",
            category="Equity",
            sector="Technology",
            country="US",
            asset_type="Stock",
        )
        db.add(asset)
        db.flush()
        plan = TradePlan(
            asset_id=asset.id,
            ticker="NVDA",
            setup_type="momentum_breakout",
            actionability="actionable_if_confirmed",
            entry_zone={"low": 128.0, "high": 131.0},
            entry_trigger="daily close above resistance with relative volume > 1.5x",
            confirmation_condition="sector and benchmark confirmation still positive",
            invalidation_level=123.5,
            target_1=138.0,
            target_2=145.0,
            confidence=72.0,
            historical_setup_reliability=64.0,
        )
        game = TradingGame(game_id="copy-test", current_capital=120.0)
        db.add_all([plan, game])
        db.flush()
        db.add(
            TradingGameTrade(
                game_id=game.id,
                ticker="NVDA",
                setup_type="momentum_breakout",
                outcome_label="target_hit",
                realized_r_multiple=1.7,
                net_pnl_eur=2.4,
                excess_return_vs_benchmark=3.2,
                trade_quality_score=78.0,
                lesson_generated="breakout worked only after volume confirmation",
                created_at=datetime.utcnow(),
            )
        )
        db.commit()

        payload = CopyTradingIntelligenceService().dashboard(db, limit=10)

        assert payload["paper_only"] is True
        assert payload["no_broker_execution"] is True
        assert payload["rows"][0]["ticker"] == "NVDA"
        assert payload["rows"][0]["copy_readiness"] == "copy_ready_if_triggered"
        assert "volume confirmation" in payload["rows"][0]["learning_evidence"]["lesson"]


def test_copy_trading_downgrades_sniper_without_trade_plan():
    with setup_db() as db:
        db.add(
            SniperScore(
                ticker="AMD",
                setup_type="pullback_to_trend",
                actionability="wait_for_trigger",
                sniper_score=69.0,
                confidence=61.0,
                data_quality_score=74.0,
            )
        )
        db.commit()

        payload = CopyTradingIntelligenceService().candidates(db, limit=5)

        assert payload["rows"][0]["ticker"] == "AMD"
        assert payload["rows"][0]["copy_readiness"] == "watch_only_missing_risk_plan"
        assert "trade_plan" in payload["rows"][0]["missing_data"]
