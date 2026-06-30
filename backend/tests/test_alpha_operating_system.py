from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    LearningBenchmarkComparison,
    SniperScore,
    TradePlan,
    TradingGame,
    TradingGameTrade,
)
from app.services.alpha_operating_system import (
    AlphaGateService,
    AlphaReadinessEngine,
    BrainCommandSummaryService,
    EdgeMapService,
    PaperCopyTradingService,
    TradingGameReadinessService,
)
from app.services.trading_game_runtime import TradingGameRuntimeSnapshotService


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_trading_game_readiness_explains_missing_source_data():
    with setup_db() as db:
        payload = TradingGameReadinessService().readiness(db)

    assert payload["status"] == "WAITING_FOR_SOURCE_DATA"
    assert "No TradingGame row" in payload["blocker"]
    assert payload["evidence_grade"] == "insufficient"


def test_trading_game_readiness_ready_when_snapshots_and_eligible_trades_exist():
    with setup_db() as db:
        game = TradingGame(game_id="readiness-test", current_capital=105.0, target_capital=10000.0)
        db.add(game)
        db.flush()
        for index in range(3):
            db.add(
                TradingGameTrade(
                    game_id=game.id,
                    ticker=f"T{index}",
                    setup_type="momentum_breakout",
                    entry_date=date(2025, 1, 2 + index),
                    exit_date=date(2025, 1, 5 + index),
                    entry_price=100.0,
                    position_size=0.2,
                    invalidation_level=96.0,
                    realized_r_multiple=1.0,
                    net_pnl_eur=1.0,
                    outcome_label="target_hit",
                    created_at=datetime.utcnow(),
                )
            )
        db.commit()
        TradingGameRuntimeSnapshotService().produce_ledger_snapshot(db, game_id=game.id, limit=10)
        TradingGameRuntimeSnapshotService().produce_equity_snapshot(db, game_id=game.id, limit=10)

        payload = TradingGameReadinessService().readiness(db)

    assert payload["status"] == "READY"
    assert payload["eligible_trade_count"] == 3
    assert payload["ledger_snapshot_status"] == "ready"
    assert payload["equity_snapshot_status"] == "ready"


def test_alpha_readiness_is_capped_without_live_and_benchmark_depth():
    with setup_db() as db:
        game = TradingGame(game_id="alpha-test", current_capital=150.0)
        db.add(game)
        db.flush()
        for index in range(12):
            db.add(
                TradingGameTrade(
                    game_id=game.id,
                    ticker=f"A{index}",
                    setup_type="pullback_to_trend",
                    realized_r_multiple=2.0,
                    excess_return_vs_benchmark=4.0,
                    outcome_label="target_hit",
                    created_at=datetime.utcnow(),
                )
            )
        db.commit()

        payload = AlphaReadinessEngine().readiness(db)

    assert payload["status"] == "INSUFFICIENT_EVIDENCE"
    assert payload["alpha_readiness_score"] <= 60
    assert "benchmark_comparison_missing" in payload["warnings"]


def test_alpha_gates_require_benchmark_and_live_samples():
    with setup_db() as db:
        payload = AlphaGateService().gates(db)

    blocked = [row for row in payload["rows"] if not row["passed"]]
    assert blocked
    assert payload["all_required_gates_passed"] is False


def test_edge_map_uses_stored_trade_outcomes_without_recalculation():
    with setup_db() as db:
        game = TradingGame(game_id="edge-test")
        db.add(game)
        db.flush()
        db.add_all(
            [
                TradingGameTrade(game_id=game.id, ticker="NVDA", setup_type="momentum_breakout", sector="Technology", realized_r_multiple=2.0, excess_return_vs_benchmark=5.0, outcome_label="target_hit"),
                TradingGameTrade(game_id=game.id, ticker="AAPL", setup_type="momentum_breakout", sector="Technology", realized_r_multiple=-1.0, excess_return_vs_benchmark=-2.0, outcome_label="stopped_out"),
            ]
        )
        db.commit()

        payload = EdgeMapService().edge_map(db)

    assert payload["status"] == "ready"
    assert payload["best_setups"][0]["entity"] == "momentum_breakout"
    assert payload["sample_size"] == 2


def test_paper_copy_summary_is_paper_only_and_reuses_trade_plan_evidence():
    with setup_db() as db:
        db.add(
            TradePlan(
                ticker="NVDA",
                setup_type="momentum_breakout",
                actionability="actionable_if_confirmed",
                entry_trigger="close above resistance with relative volume > 1.5x",
                invalidation_level=120.0,
                target_1=140.0,
                confidence=72.0,
                historical_setup_reliability=60.0,
            )
        )
        db.commit()

        payload = PaperCopyTradingService().summary(db, limit=5)

    assert payload["paper_only"] is True
    assert payload["no_broker_execution"] is True
    assert payload["readiness"]["status"] == "READY_FOR_PAPER_MONITORING"
    assert payload["rows"][0]["ticker"] == "NVDA"


def test_brain_command_summary_is_compact_and_truth_first():
    with setup_db() as db:
        db.add(LearningBenchmarkComparison(benchmark_name="SPY", result_label="underperforming", excess_return=-4.2, sample_size=12, statistical_confidence="low evidence"))
        db.add(SniperScore(ticker="AMD", setup_type="pullback_to_trend", actionability="wait_for_trigger", sniper_score=68.0, confidence=60.0))
        db.commit()

        payload = BrainCommandSummaryService().summary(db)

    assert payload["feature_set"] == "project-split"
    assert "capability_matrix" in payload
    assert payload["policy"].startswith("Command reads compact evidence")
