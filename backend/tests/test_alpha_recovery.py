from datetime import date, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    AlphaLossAttribution,
    AlphaRecoveryAction,
    BenchmarkMethodologyValidation,
    CapitalAllocationSnapshot,
    DecisionUniverseSnapshot,
    LearningBenchmarkComparison,
    MissedWinner,
    TradingGame,
    TradingGameTrade,
)
from app.services.alpha_recovery import (
    AlphaLossAttributionEngine,
    AlphaRecoveryActionEngine,
    AlphaRecoveryDashboardService,
    BenchmarkMethodologyValidator,
    MissedWinnersEngine,
)


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_benchmark(db: Session, *, sample_size: int = 40, excess: float = -12.5) -> LearningBenchmarkComparison:
    row = LearningBenchmarkComparison(
        benchmark_name="QQQ",
        benchmark_type="market",
        mode="historical_simulation",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 6, 30),
        blum_return=4.0,
        benchmark_return=4.0 - excess,
        excess_return=excess,
        sample_size=sample_size,
        statistical_confidence="medium evidence" if sample_size >= 30 else "very low evidence",
        result_label="underperforming" if excess < 0 else "outperforming",
        explanation="Stored benchmark comparison for test.",
    )
    db.add(row)
    db.commit()
    return row


def seed_game_with_trades(db: Session) -> TradingGame:
    game = TradingGame(
        game_id="alpha-loss-test",
        status="active",
        starting_capital=100.0,
        current_capital=98.0,
        benchmark_ticker="QQQ",
        target_capital=10000.0,
        trade_count=4,
    )
    db.add(game)
    db.flush()
    rows = [
        dict(ticker="NVDA", setup_type="momentum_breakout", sector="Technology", missed_entry=True, excess=8.0, r=0.0, risk=0.0, pnl=0.0, mfe=2.0, stop=False, outcome="missed_entry"),
        dict(ticker="AMD", setup_type="momentum_breakout", sector="Technology", missed_entry=False, excess=-5.0, r=-1.0, risk=1.2, pnl=-1.2, mfe=0.2, stop=True, outcome="stopped_out"),
        dict(ticker="MSFT", setup_type="trend_continuation", sector="Technology", missed_entry=False, excess=6.0, r=0.3, risk=0.4, pnl=0.12, mfe=2.2, stop=False, outcome="partial_profit"),
        dict(ticker="META", setup_type="trend_continuation", sector="Communication Services", missed_entry=False, excess=4.0, r=1.5, risk=0.5, pnl=0.75, mfe=2.1, stop=False, outcome="target_hit"),
    ]
    for index, row in enumerate(rows):
        db.add(
            TradingGameTrade(
                game_id=game.id,
                mode="historical_simulation",
                ticker=row["ticker"],
                setup_type=row["setup_type"],
                sector=row["sector"],
                benchmark_ticker="QQQ",
                decision_state="active_setup" if not row["missed_entry"] else "wait_for_trigger",
                actionability_state_at_entry="active_setup",
                entry_date=date(2024, 1, 2) + timedelta(days=index),
                exit_date=date(2024, 1, 20) + timedelta(days=index),
                entry_price=100.0,
                exit_price=101.0,
                position_size=1.0,
                risk_amount=row["risk"],
                risk_percent=row["risk"],
                realized_r_multiple=row["r"],
                realized_pl=row["pnl"],
                net_pnl_eur=row["pnl"],
                capital_before=100.0,
                capital_after=100.0 + row["pnl"],
                max_favorable_excursion=row["mfe"],
                max_adverse_excursion=-0.5,
                stop_hit=row["stop"],
                target_hit=row["r"] >= 1.5,
                missed_entry=row["missed_entry"],
                benchmark_return_same_period=1.0,
                excess_return_vs_benchmark=row["excess"],
                outcome_label=row["outcome"],
                created_at=datetime.utcnow() + timedelta(seconds=index),
            )
        )
    db.add(
        CapitalAllocationSnapshot(
            game_id=game.id,
            total_capital=98.0,
            cash_reserve_percent=45.0,
            deployable_percent=55.0,
            allocation_quality_score=48.0,
            explanation="High cash reserve during underperformance.",
        )
    )
    db.commit()
    return game


def test_benchmark_methodology_validator_blocks_invalid_sample_and_corrects_excess():
    with setup_db() as db:
        invalid = seed_benchmark(db, sample_size=3, excess=-8.0)
        payload = BenchmarkMethodologyValidator().validate_row(invalid)
        assert payload["methodology_valid"] is False
        assert "insufficient_sample_size" in payload["warnings"]
        assert payload["corrected_excess_return"] == -8.0


def test_alpha_loss_attribution_persists_measurable_causes():
    with setup_db() as db:
        seed_benchmark(db)
        seed_game_with_trades(db)
        methodology = BenchmarkMethodologyValidator().validate_latest(db, persist=True)
        assert methodology["rows"][0]["methodology_valid"] is True

        attribution = AlphaLossAttributionEngine().calculate(db, persist=True)
        categories = {row["category"] for row in attribution["rows"]}

        assert attribution["status"] == "ready"
        assert "missed_entry" in categories
        assert "wrong_asset_selection" in categories
        assert "premature_exit" in categories
        assert "weak_capital_allocation" in categories
        assert db.scalar(select(AlphaLossAttribution).where(AlphaLossAttribution.category == "missed_entry")) is not None


def test_missed_winners_detection_uses_trade_and_decision_snapshot_evidence():
    with setup_db() as db:
        seed_game_with_trades(db)
        db.add(
            DecisionUniverseSnapshot(
                timestamp=datetime(2024, 2, 1),
                market_regime="risk_on",
                volatility_regime="low_volatility",
                selected_asset="AAPL",
                selected_rank=1,
                selected_score=74.0,
                total_candidates=2,
                candidates_json={
                    "candidates": [
                        {"ticker": "NVDA", "rank": 4, "benchmark_relative_return": 18.0, "decision_state": "rejected", "confidence": 58},
                    ]
                },
                benchmark_snapshot={"benchmark": "QQQ", "benchmark_return": 3.0},
            )
        )
        db.commit()

        payload = MissedWinnersEngine().detect(db, persist=True)
        tickers = {row["ticker"] for row in payload["rows"]}

        assert "NVDA" in tickers
        assert db.scalar(select(MissedWinner).where(MissedWinner.ticker == "NVDA")) is not None


def test_alpha_recovery_actions_and_dashboard_snapshot_are_evidence_bound():
    with setup_db() as db:
        seed_benchmark(db)
        seed_game_with_trades(db)

        result = AlphaRecoveryDashboardService().recalculate(db)
        assert result["status"] == "ready"
        assert result["missed_winners_count"] >= 1

        action = db.scalar(select(AlphaRecoveryAction).order_by(AlphaRecoveryAction.id).limit(1))
        validation = db.scalar(select(BenchmarkMethodologyValidation).order_by(BenchmarkMethodologyValidation.id).limit(1))
        dashboard = AlphaRecoveryDashboardService().dashboard(db)

        assert action is not None
        assert action.rollback_available is True
        assert validation is not None
        assert dashboard["snapshot"]["status"] == "ready"
        assert dashboard["truth_layer"]["lines"]


def test_alpha_replay_priorities_expose_missed_winners_without_fabricating():
    with setup_db() as db:
        seed_game_with_trades(db)
        MissedWinnersEngine().detect(db, persist=True)

        priorities = AlphaRecoveryActionEngine().replay_priorities(db)

        assert priorities["mode"] == "alpha_loss_replay"
        assert priorities["priorities"]["missed_winners"]
        assert "not financial advice" not in priorities["sampling_instruction"].lower()
