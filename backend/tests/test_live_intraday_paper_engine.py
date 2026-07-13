from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Asset, IntradayPaperRun, LiveForwardPaperGame, LiveForwardPaperTrade, ReplayMarketBar, ReplayStrategyValidation
from app.services.intraday_contracts import PAPER_FORWARD_INTRADAY
from app.services.intraday_market_data import StrictIntradayDataGateway
from app.services.intraday_opportunity import IntradayPortfolioState, BlumIntradayOpportunityEngine
from app.services.promoted_strategy_registry import BlumPromotedStrategyRegistry


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
