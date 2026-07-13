from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.routes import router
from app.core.config import Settings
from app.core.database import Base
from app.models import (
    Asset,
    IntradayPaperRun,
    LearningEvent,
    LiveForwardPaperGame,
    LiveForwardPaperTrade,
    LiveForwardPaperTradeEvent,
    ReplayMarketBar,
    ReplayStrategyValidation,
    StrategyMemory,
    TradeLearningEvidence,
)
from app.services.intraday_contracts import PAPER_FORWARD_INTRADAY
from app.services.intraday_market_data import StrictIntradayDataGateway
from app.services.intraday_opportunity import IntradayPortfolioState, BlumIntradayOpportunityEngine
from app.services.intraday_paper_engine import BlumIntradayPaperEngine, IntradayPaperLearningService, intraday_snapshot_summary
from app.services.live_forward_paper_trading import LiveForwardPaperTradingService
from app.services.promoted_strategy_registry import BlumPromotedStrategyRegistry
from app.services import realtime
from app.engine.brain.trader_brain import TraderBrainService


NOW = datetime(2026, 7, 13, 14, 30)


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_asset(db: Session, ticker: str = "NVDA", market: str = "United States") -> Asset:
    row = Asset(
        ticker=ticker,
        name=ticker,
        category="Stock",
        asset_type="Stock",
        sector="Technology",
        country=market,
        exchange="NASDAQ",
        currency="USD",
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def seed_validation(
    db: Session,
    *,
    setup_type: str = "intraday_breakout",
    sample_size: int = 500,
    verdict: str = "PROMOTED_TO_PAPER",
    markets: list[str] | None = None,
    metrics: dict | None = None,
    overfitting_score: float = 15.0,
) -> ReplayStrategyValidation:
    row = ReplayStrategyValidation(
        setup_type=setup_type,
        sample_size=sample_size,
        markets_json=markets or ["USA", "GERMANY"],
        windows_json=[{"id": "w1"}, {"id": "w2"}, {"id": "w3"}],
        metrics_json=metrics
        or {
            "benchmark_excess": 4.0,
            "expectancy_r": 0.25,
            "stability_score": 75.0,
            "walk_forward_score": 70.0,
            "max_drawdown": -8.0,
            "candidate_weights": {"momentum": 0.35},
            "timeframe_stack": ["1d", "15m", "5m", "1m"],
            "entry_rules": {"trigger": "one_minute_breakout"},
            "stop_rules": {"atr_multiple": 1.0},
            "target_rules": {"risk_multiple": 1.8},
        },
        overfitting_score=overfitting_score,
        verdict=verdict,
        explanation="fixture",
        created_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def seed_bars(
    db: Session,
    asset: Asset,
    timeframe: str,
    *,
    count: int,
    step: timedelta,
    end: datetime = NOW,
    price_step: float = 0.08,
    volume: float = 2_000_000,
) -> None:
    start = end - step * (count - 1)
    for index in range(count):
        close = 100.0 + index * price_step
        db.add(
            ReplayMarketBar(
                asset_id=asset.id,
                source_symbol=asset.ticker,
                normalized_symbol=asset.ticker,
                market=asset.country,
                timeframe=timeframe,
                bar_timestamp=start + step * index,
                open=close - 0.04,
                high=close + 0.12,
                low=close - 0.10,
                close=close,
                volume=volume,
                provider="fixture",
                acquired_at=NOW,
                data_quality_score=95.0,
                source_metadata={"source": "test"},
            )
        )
    db.commit()


def seed_complete_stack(db: Session, asset: Asset, *, one_minute_end: datetime = NOW) -> None:
    seed_bars(db, asset, "1d", count=80, step=timedelta(days=1), end=NOW)
    seed_bars(db, asset, "15m", count=80, step=timedelta(minutes=15), end=NOW)
    seed_bars(db, asset, "5m", count=80, step=timedelta(minutes=5), end=NOW)
    seed_bars(db, asset, "1m", count=80, step=timedelta(minutes=1), end=one_minute_end)


def test_registry_returns_only_latest_fully_promoted_strategy():
    with setup_db() as db:
        promoted = seed_validation(db)
        seed_validation(db, setup_type="pullback", sample_size=299)
        rows = BlumPromotedStrategyRegistry().list_eligible(db, market="USA", asset_class="Stock")

    assert [row.validation_id for row in rows] == [promoted.id]
    assert rows[0].evidence_type == "WALK_FORWARD_EVIDENCE"
    assert rows[0].timeframe_stack == ("1d", "15m", "5m", "1m")


def test_registry_rejects_unstable_negative_or_overfit_strategy():
    with setup_db() as db:
        seed_validation(db, setup_type="unstable", metrics={"benchmark_excess": 2.0, "expectancy_r": 0.2, "stability_score": 20.0})
        seed_validation(db, setup_type="negative", metrics={"benchmark_excess": -1.0, "expectancy_r": -0.1, "stability_score": 80.0})
        seed_validation(db, setup_type="overfit", overfitting_score=80.0)
        rows = BlumPromotedStrategyRegistry().list_eligible(db, market="USA", asset_class="Stock")

    assert rows == []


def test_data_gateway_requires_all_four_timeframes_without_fallback():
    with setup_db() as db:
        asset = seed_asset(db)
        seed_bars(db, asset, "1d", count=80, step=timedelta(days=1))
        seed_bars(db, asset, "15m", count=80, step=timedelta(minutes=15))
        seed_bars(db, asset, "5m", count=80, step=timedelta(minutes=5))
        result = StrictIntradayDataGateway(refresh_missing=False).load(db, asset=asset, now=NOW)

    assert result.status == "INTRADAY_DATA_BLOCKED"
    assert "MISSING_1M_DATA" in result.blockers
    assert result.bars["1m"] == ()


def test_data_gateway_rejects_stale_one_minute_data():
    with setup_db() as db:
        asset = seed_asset(db)
        seed_complete_stack(db, asset, one_minute_end=NOW - timedelta(minutes=20))
        result = StrictIntradayDataGateway(refresh_missing=False, max_one_minute_age=timedelta(minutes=3)).load(db, asset=asset, now=NOW)

    assert result.status == "INTRADAY_DATA_BLOCKED"
    assert "STALE_1M_DATA" in result.blockers


def test_opportunity_rejects_expected_move_that_costs_destroy():
    with setup_db() as db:
        asset = seed_asset(db)
        strategy_row = seed_validation(db)
        seed_complete_stack(db, asset)
        strategy = BlumPromotedStrategyRegistry().list_eligible(db, market="USA", asset_class="Stock")[0]
        bundle = StrictIntradayDataGateway(refresh_missing=False).load(db, asset=asset, now=NOW)
        decision = BlumIntradayOpportunityEngine(min_expected_move_bps=500.0).evaluate(
            strategy=strategy,
            data=bundle,
            portfolio=IntradayPortfolioState(capital=10_000.0),
            desk="NasdaqAgent",
            benchmark_ticker="QQQ",
        )

    assert strategy.validation_id == strategy_row.id
    assert decision.status == "INTRADAY_BLOCKED"
    assert decision.reason_code in {"EXPECTED_MOVE_TOO_SMALL", "COSTS_KILL_EDGE"}


def test_opportunity_rejects_duplicate_open_ticker():
    with setup_db() as db:
        asset = seed_asset(db)
        seed_validation(db)
        seed_complete_stack(db, asset)
        strategy = BlumPromotedStrategyRegistry().list_eligible(db, market="USA", asset_class="Stock")[0]
        bundle = StrictIntradayDataGateway(refresh_missing=False).load(db, asset=asset, now=NOW)
        decision = BlumIntradayOpportunityEngine().evaluate(
            strategy=strategy,
            data=bundle,
            portfolio=IntradayPortfolioState(capital=10_000.0, open_tickers=frozenset({"NVDA"})),
            desk="NasdaqAgent",
            benchmark_ticker="QQQ",
        )

    assert decision.status == "INTRADAY_BLOCKED"
    assert decision.reason_code == "TICKER_CONCENTRATION"


def test_intraday_trade_evidence_constant_is_forward_only():
    assert PAPER_FORWARD_INTRADAY == "PAPER_FORWARD_INTRADAY"
    assert PAPER_FORWARD_INTRADAY != "REPLAY_EVIDENCE"


def test_intraday_trade_persists_strategy_cost_and_lifecycle_metadata():
    with setup_db() as db:
        game = LiveForwardPaperGame(game_id="intraday-test", starting_capital=10_000, current_capital=10_000, cash=10_000)
        db.add(game)
        validation = seed_validation(db)
        validation_id = validation.id
        run = IntradayPaperRun(run_uid="intraday-run-test", trigger="test", status="RUNNING", started_at=NOW)
        db.add(run)
        db.flush()
        trade = LiveForwardPaperTrade(
            trade_uid="intraday-trade-test",
            game_id=game.id,
            ticker="NVDA",
            setup_type="intraday_breakout",
            status="OPEN",
            decision_timestamp=NOW,
            duplicate_key="intraday-test-key",
            trading_mode="INTRADAY_PAPER_FORWARD",
            evidence_type=PAPER_FORWARD_INTRADAY,
            promoted_validation_id=validation.id,
            intraday_run_id=run.id,
            market="USA",
            desk="NasdaqAgent",
            session_name="regular",
            timeframe_stack=["1d", "15m", "5m", "1m"],
            data_timestamps={"1m": NOW.isoformat()},
            execution_costs={"total_round_trip_bps": 5.0},
            net_expectancy_bps=18.0,
            sizing_reason="risk controlled",
            last_managed_bar_at=NOW,
        )
        db.add(trade)
        db.commit()
        stored = db.scalar(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.trade_uid == "intraday-trade-test"))

    assert stored is not None
    assert stored.evidence_type == PAPER_FORWARD_INTRADAY
    assert stored.timeframe_stack == ["1d", "15m", "5m", "1m"]
    assert stored.promoted_validation_id == validation_id


def test_run_opens_only_promoted_triggered_candidate_with_adverse_fill():
    with setup_db() as db:
        asset = seed_asset(db)
        seed_validation(db)
        seed_complete_stack(db, asset)
        observed_price = db.scalar(
            select(ReplayMarketBar.close)
            .where(ReplayMarketBar.asset_id == asset.id, ReplayMarketBar.timeframe == "1m")
            .order_by(ReplayMarketBar.bar_timestamp.desc())
            .limit(1)
        )
        engine = BlumIntradayPaperEngine(now_provider=lambda: NOW, refresh_missing=False)

        first = engine.run_once(db, trigger="test", assets=[asset])
        second = engine.run_once(db, trigger="test", assets=[asset])
        trade = db.scalar(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.evidence_type == PAPER_FORWARD_INTRADAY))
        events = db.scalars(
            select(LiveForwardPaperTradeEvent)
            .where(LiveForwardPaperTradeEvent.paper_trade_id == trade.id)
            .order_by(LiveForwardPaperTradeEvent.id)
        ).all()

    assert first["trades_opened"] == 1
    assert second["trades_opened"] == 0
    assert trade is not None
    assert trade.entry_price > observed_price
    assert trade.frozen_decision_payload["evidence_type"] == PAPER_FORWARD_INTRADAY
    assert [event.event_type for event in events[:2]] == ["INTRADAY_TRADE_CANDIDATE", "INTRADAY_TRADE_OPENED"]


def test_lifecycle_uses_only_later_one_minute_bar_and_closes_stop():
    with setup_db() as db:
        asset = seed_asset(db)
        seed_validation(db)
        seed_complete_stack(db, asset)
        clock = {"now": NOW}
        engine = BlumIntradayPaperEngine(now_provider=lambda: clock["now"], refresh_missing=False)
        opened = engine.run_once(db, trigger="test", assets=[asset])
        trade = db.scalar(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.evidence_type == PAPER_FORWARD_INTRADAY))
        frozen_payload = dict(trade.frozen_decision_payload)
        stop = float(trade.stop_loss)

        clock["now"] = NOW + timedelta(minutes=1)
        db.add(
            ReplayMarketBar(
                asset_id=asset.id,
                source_symbol=asset.ticker,
                normalized_symbol=asset.ticker,
                market=asset.country,
                timeframe="1m",
                bar_timestamp=clock["now"],
                open=stop + 0.2,
                high=stop + 0.3,
                low=stop - 0.2,
                close=stop - 0.1,
                volume=3_000_000,
                provider="fixture",
                acquired_at=clock["now"],
                data_quality_score=95.0,
                source_metadata={"source": "test"},
            )
        )
        db.commit()
        closed = engine.run_once(db, trigger="test", assets=[asset])
        db.refresh(trade)

    assert opened["trades_opened"] == 1
    assert closed["trades_closed"] == 1
    assert trade.status == "CLOSED"
    assert trade.close_reason == "STOP_HIT"
    assert trade.last_managed_bar_at == NOW + timedelta(minutes=1)
    assert trade.closed_at == NOW + timedelta(minutes=1)
    assert trade.frozen_decision_payload == frozen_payload
    assert trade.net_pnl_eur < 0


def test_closed_intraday_trade_updates_forward_memory_once_but_open_trade_does_not():
    with setup_db() as db:
        game = LiveForwardPaperGame(game_id="learning", starting_capital=100, current_capital=100, cash=100)
        db.add(game)
        db.flush()
        trade = LiveForwardPaperTrade(
            trade_uid="learning-trade",
            game_id=game.id,
            ticker="NVDA",
            setup_type="intraday_breakout",
            status="OPEN",
            decision_timestamp=NOW,
            duplicate_key="learning-trade-key",
            trading_mode="INTRADAY_PAPER_FORWARD",
            evidence_type=PAPER_FORWARD_INTRADAY,
            market="USA",
            desk="NasdaqAgent",
            session_name="regular",
            timeframe_stack=["1d", "15m", "5m", "1m"],
            entry_price=100.0,
            stop_loss=99.0,
            position_size=1.0,
            frozen_decision_payload={"regime": "trend_up"},
        )
        db.add(trade)
        db.flush()
        learning = IntradayPaperLearningService()
        assert learning.apply_closed_trade(db, trade)["status"] == "not_closed"

        trade.status = "CLOSED"
        trade.closed_at = NOW + timedelta(minutes=20)
        trade.exit_price = 102.0
        trade.net_pnl_eur = 1.9
        trade.r_multiple = 1.9
        trade.excess_return_vs_benchmark = 1.5
        trade.close_reason = "TARGET_HIT"
        first = learning.apply_closed_trade(db, trade)
        second = learning.apply_closed_trade(db, trade)
        evidence_count = len(db.scalars(select(TradeLearningEvidence)).all())
        memory_count = len(db.scalars(select(StrategyMemory)).all())
        event_count = len(db.scalars(select(LearningEvent).where(LearningEvent.event_type == "intraday_paper_trade_closed")).all())

    assert first["status"] == "applied"
    assert second["status"] == "duplicate"
    assert evidence_count == 1
    assert memory_count == 1
    assert event_count == 1


def test_intraday_snapshot_is_read_only_and_reports_no_activity_truthfully():
    with setup_db() as db:
        before = len(db.scalars(select(IntradayPaperRun)).all())
        snapshot = intraday_snapshot_summary(db, now=NOW)
        after = len(db.scalars(select(IntradayPaperRun)).all())

    assert before == after == 0
    assert snapshot["status"] == "NO_INTRADAY_RUNS"
    assert snapshot["trades_opened_today"] == 0


def test_intraday_run_reports_data_blocked_when_no_eligible_market_data_exists():
    with setup_db() as db:
        result = BlumIntradayPaperEngine(
            now_provider=lambda: NOW,
            refresh_missing=False,
        ).run_once(db, trigger="test", assets=[])
        persisted = db.scalar(select(IntradayPaperRun).where(IntradayPaperRun.run_uid == result["run_id"]))

    assert result["status"] == "DATA_BLOCKED"
    assert persisted is not None
    assert persisted.status == "DATA_BLOCKED"
    assert result["blockers"][0]["reason"] == "NO_DESK_ASSETS_WITH_INTRADAY_DATA"


def test_intraday_command_is_post_only_and_settings_are_bounded():
    methods = {
        method
        for route in router.routes
        if getattr(route, "path", None) == "/api/paper-forward/run-intraday"
        for method in (route.methods or set())
    }
    settings = Settings(DATABASE_URL="sqlite:///:memory:")

    assert methods == {"POST"}
    assert settings.intraday_paper_enabled is True
    assert 1 <= settings.intraday_paper_minutes <= 60
    assert settings.intraday_max_runtime_seconds <= 120


def test_scheduler_runs_intraday_worker_independently(monkeypatch):
    observed = {}

    class StubEngine:
        def run_once(self, db, *, trigger):
            observed["db"] = db
            observed["trigger"] = trigger
            return {"status": "COMPLETED"}

    sentinel_db = object()
    monkeypatch.setattr(realtime, "BlumIntradayPaperEngine", StubEngine)
    monkeypatch.setattr(realtime, "_run_job", lambda name, work: observed.update(name=name, result=work(sentinel_db)))

    realtime.run_intraday_paper_trading_job()

    assert observed == {"name": "intraday_paper_trading", "db": sentinel_db, "trigger": "scheduled", "result": {"status": "COMPLETED"}}


def test_paper_snapshot_embeds_read_only_intraday_summary():
    with setup_db() as db:
        payload = LiveForwardPaperTradingService().snapshot_payload(db)

    assert payload["intraday"]["status"] == "NO_INTRADAY_RUNS"
    assert payload["intraday"]["evidence_type"] == PAPER_FORWARD_INTRADAY


def test_alpha_keeps_closed_intraday_evidence_separate_from_generic_paper_forward():
    with setup_db() as db:
        game = LiveForwardPaperGame(game_id="alpha-intraday", starting_capital=100, current_capital=102, cash=102, realized_pl=2)
        db.add(game)
        db.flush()
        db.add(
            LiveForwardPaperTrade(
                trade_uid="alpha-intraday-trade",
                game_id=game.id,
                ticker="NVDA",
                setup_type="intraday_breakout",
                status="CLOSED",
                decision_timestamp=NOW,
                decision_date=NOW.date(),
                opened_at=NOW,
                closed_at=NOW + timedelta(minutes=30),
                entry_price=100,
                exit_price=102,
                position_size=1,
                net_pnl_eur=1.9,
                gross_pnl_eur=2.0,
                pnl_percent=1.9,
                r_multiple=1.9,
                benchmark_return_same_period=0.5,
                excess_return_vs_benchmark=1.4,
                outcome_label="win",
                duplicate_key="alpha-intraday-key",
                trading_mode="INTRADAY_PAPER_FORWARD",
                evidence_type=PAPER_FORWARD_INTRADAY,
                timeframe_stack=["1d", "15m", "5m", "1m"],
                costs_paid=0.1,
                holding_minutes=30,
            )
        )
        db.commit()
        snapshot = TraderBrainService().alpha(db)

    intraday = snapshot["evidence_split"]["intraday_paper_forward"]
    assert intraday["sample_size"] == 1
    assert intraday["costs_paid"] == 0.1
    assert intraday["average_holding_minutes"] == 30
    assert snapshot["evidence_split"]["paper_forward"]["sample_size"] == 0
