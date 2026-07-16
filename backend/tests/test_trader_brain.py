from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    BlumTradingPowerScore,
    HistoricalPrediction,
    LearningBenchmarkComparison,
    LearningFocusPriority,
    LearningRun,
    LiveForwardPaperGame,
    LiveForwardPaperTrade,
    PredictionOutcome,
    SelfImprovementAction,
    StrategyReadinessHistory,
    TradeLearningEvidence,
    TradingGame,
    TradingGameTrade,
    TradingIntelligenceMetric,
)
from app.services.trader_brain import TRADER_BRAIN_FEATURE_SET, TRADER_BRAIN_VERSION, TraderBrainService


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_brain_snapshot_is_startup_safe_and_does_not_call_heavy_readiness_services(monkeypatch):
    import app.engine.brain.trader_brain as trader_brain_module

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("heavy service should not run during Brain startup snapshot")

    monkeypatch.setattr(trader_brain_module.LearningSummaryService, "summary", fail_if_called)
    monkeypatch.setattr(trader_brain_module.TradingGameReadinessService, "readiness", fail_if_called)
    monkeypatch.setattr(trader_brain_module.AlphaReadinessEngine, "readiness", fail_if_called)

    with setup_db() as db:
        db.add(LearningRun(run_id="fast-brain", status="completed", trigger="test", started_at=datetime.utcnow()))
        db.commit()

        payload = TraderBrainService().brain(db)

    assert payload["version"] == TRADER_BRAIN_VERSION
    assert payload["status"] in {"ready", "insufficient_evidence"}
    assert payload["policy"].startswith("Trader Brain is read-only")


def test_trader_brain_is_read_only_truth_first_summary():
    with setup_db() as db:
        game = TradingGame(game_id="brain-test", current_capital=140.0, starting_capital=100.0, target_capital=10000.0, trade_count=1)
        db.add(game)
        db.add(TradingIntelligenceMetric(trades_count=25, win_rate=0.52, expectancy_r=0.31, trade_quality_score=62.0, risk_reward_quality_score=58.0))
        db.add(LearningBenchmarkComparison(benchmark_name="SPY", result_label="underperforming", excess_return=-2.4, sample_size=25, statistical_confidence="low evidence"))
        db.commit()

        payload = TraderBrainService().brain(db)

    assert payload["version"] == TRADER_BRAIN_VERSION
    assert payload["feature_set"] == TRADER_BRAIN_FEATURE_SET
    assert "brain_score" in payload
    assert payload["policy"].startswith("Trader Brain is read-only")
    assert any("BLUM vs SPY" in line for line in payload["truth"])


def test_brain_snapshot_exposes_measurable_learning_trading_and_copy_readiness_proof():
    with setup_db() as db:
        db.add_all(
            [
                LearningRun(
                    run_id="brain-proof-1",
                    status="completed",
                    trigger="scheduled",
                    predictions_created=8,
                    outcomes_evaluated=5,
                    memory_updates=2,
                    started_at=datetime(2026, 7, 1, 8, 0, 0),
                ),
                LearningRun(
                    run_id="brain-proof-2",
                    status="completed",
                    trigger="scheduled",
                    predictions_created=12,
                    outcomes_evaluated=9,
                    memory_updates=4,
                    started_at=datetime(2026, 7, 2, 8, 0, 0),
                ),
                BlumTradingPowerScore(
                    calculated_at=datetime(2026, 7, 1, 9, 0, 0),
                    score=42.0,
                    decision_quality_score=45.0,
                    learning_velocity_score=38.0,
                ),
                BlumTradingPowerScore(
                    calculated_at=datetime(2026, 7, 2, 9, 0, 0),
                    score=48.0,
                    decision_quality_score=53.0,
                    learning_velocity_score=57.0,
                ),
            ]
        )
        game = LiveForwardPaperGame(
            game_id="brain-proof-game",
            starting_capital=100.0,
            current_capital=105.0,
        )
        db.add(game)
        db.flush()
        db.add_all(
            [
                LiveForwardPaperTrade(
                    trade_uid="brain-proof-win",
                    duplicate_key="brain-proof-win",
                    game_id=game.id,
                    ticker="NVDA",
                    setup_type="momentum_breakout",
                    status="CLOSED",
                    decision_timestamp=datetime(2026, 7, 1, 10, 0, 0),
                    closed_at=datetime(2026, 7, 1, 16, 0, 0),
                    entry_price=100.0,
                    position_size=1.0,
                    notional_value=100.0,
                    net_pnl_eur=8.0,
                    r_multiple=2.0,
                    benchmark_return_same_period=2.0,
                    excess_return_vs_benchmark=6.0,
                    outcome_label="target_hit",
                ),
                LiveForwardPaperTrade(
                    trade_uid="brain-proof-loss",
                    duplicate_key="brain-proof-loss",
                    game_id=game.id,
                    ticker="AMD",
                    setup_type="pullback_to_trend",
                    status="CLOSED",
                    decision_timestamp=datetime(2026, 7, 2, 10, 0, 0),
                    closed_at=datetime(2026, 7, 2, 16, 0, 0),
                    entry_price=100.0,
                    position_size=1.0,
                    notional_value=100.0,
                    net_pnl_eur=-3.0,
                    r_multiple=-0.75,
                    benchmark_return_same_period=1.0,
                    excess_return_vs_benchmark=-4.0,
                    outcome_label="stopped_out",
                ),
            ]
        )
        db.add(
            StrategyReadinessHistory(
                strategy_id="setup:momentum_breakout",
                copy_readiness_status="FORWARD_EVIDENCE_LOW",
                maturity_score=18.0,
                global_forward_trades=2,
                strategy_forward_trades=2,
                observation_days=10,
                blockers_json=["strategy_forward_trades", "observation_days"],
                real_capital_eligibility="NOT_ELIGIBLE",
                evaluated_at=datetime(2026, 7, 2, 18, 0, 0),
            )
        )
        db.commit()

        payload = TraderBrainService().brain(db)

    learning = payload["learning_proof"]
    assert learning["productive_cycles"] == 2
    assert learning["predictions_created"] == 20
    assert learning["outcomes_evaluated"] == 14
    assert learning["memory_updates"] == 6
    assert learning["outcome_conversion_rate"] == 0.7
    assert [point["predictions"] for point in learning["series"]] == [8, 12]

    trading = payload["trading_proof"]
    assert trading["evidence_class"] == "PAPER_FORWARD_EVIDENCE"
    assert trading["closed_trades"] == 2
    assert trading["wins"] == 1
    assert trading["losses"] == 1
    assert trading["realized_pnl_eur"] == 5.0
    assert trading["expectancy_r"] == 0.625
    assert trading["equity_series"][-1]["blum_equity"] == 105.0
    assert trading["equity_series"][-1]["benchmark_equity"] == 103.0
    assert trading["sample_warning"]

    readiness = payload["copy_readiness"]
    assert readiness["copy_readiness_status"] == "FORWARD_EVIDENCE_LOW"
    assert readiness["real_capital_eligibility"] == "NOT_ELIGIBLE"
    assert readiness["strategy_forward_progress"] == pytest.approx(2 / 30, abs=0.0001)
    assert readiness["observation_progress"] == pytest.approx(10 / 90, abs=0.0001)
    assert readiness["blockers"] == ["observation_days", "strategy_forward_trades"]


def test_training_ground_exposes_hypothesis_validation_and_lessons():
    with setup_db() as db:
        db.add(LearningRun(run_id="run-test", status="completed", trigger="test", batch_size=10, predictions_created=8, outcomes_evaluated=6, mistakes_found=2, memory_updates=3, started_at=datetime.utcnow()))
        db.add(LearningFocusPriority(priority_type="alpha_loss_replay", target="missed winners", reason="missed momentum leaders", expected_learning_value=82.0, urgency="high", status="active"))
        db.add(TradeLearningEvidence(ticker="NVDA", setup_type="momentum_breakout", lesson_type="setup_confirmed", observation="volume confirmed breakout", sample_size=64, confidence=71.0))
        db.commit()

        payload = TraderBrainService().training_ground(db)

    assert payload["current_experiment"]["name"] == "alpha_loss_replay"
    assert "missed winners" in payload["current_hypothesis"]
    assert payload["current_validation"]["outcomes_evaluated"] == 6
    assert payload["knowledge_gained"][0]["ticker"] == "NVDA"


def test_training_ground_does_not_look_empty_when_latest_run_is_budget_wait():
    with setup_db() as db:
        db.add(
            LearningRun(
                run_id="productive-run",
                status="completed",
                trigger="professional_learning",
                batch_size=10,
                predictions_created=8,
                outcomes_evaluated=6,
                mistakes_found=2,
                memory_updates=3,
                started_at=datetime(2026, 6, 30, 9, 0, 0),
            )
        )
        db.add(
            LearningRun(
                run_id="budget-wait",
                status="budget_wait",
                trigger="professional_learning",
                batch_size=0,
                predictions_created=0,
                outcomes_evaluated=0,
                mistakes_found=0,
                memory_updates=0,
                started_at=datetime(2026, 6, 30, 10, 0, 0),
            )
        )
        for index in range(3):
            db.add(
                TradeLearningEvidence(
                    ticker="IBM",
                    setup_type="avoid_no_edge",
                    regime="Recovery",
                    lesson_type="entry_timing_bad",
                    observation="avoid no edge was missed; evaluate trigger strictness.",
                    sample_size=80,
                    confidence=94.11,
                    created_at=datetime(2026, 6, 30, 10, 5, index),
                )
            )
        db.commit()

        payload = TraderBrainService().training_ground(db)

    validation = payload["current_validation"]
    assert validation["status"] == "completed"
    assert validation["latest_scheduler_status"] == "budget_wait"
    assert validation["display_status"] == "waiting_budget_using_latest_evidence"
    assert validation["predictions_generated"] == 8
    assert validation["outcomes_evaluated"] == 6
    assert validation["evidence_total"]["predictions_generated"] == 8
    assert validation["evidence_total"]["outcomes_evaluated"] == 6
    assert validation["latest_productive_run"]["predictions_generated"] == 8
    assert "stored evidence exists" in validation["summary"]
    assert validation["budget_guard"]["status"] == "budget_wait"
    assert payload["budget_guard"]["status"] == "budget_wait"
    assert all(row["predictions_generated"] > 0 for row in payload["learning_timeline"])
    assert len(payload["patterns_rejected"]) == 1


def test_paper_trading_is_paper_only_and_uses_completed_trade_evidence():
    with setup_db() as db:
        game = TradingGame(game_id="paper-test")
        db.add(game)
        db.flush()
        db.add(
            TradingGameTrade(
                game_id=game.id,
                ticker="AMD",
                setup_type="pullback_to_trend",
                entry_date=date(2026, 1, 1),
                exit_date=date(2026, 1, 8),
                entry_price=100.0,
                exit_price=108.0,
                position_size=1.0,
                invalidation_level=96.0,
                realized_r_multiple=2.0,
                net_pnl_eur=8.0,
                outcome_label="target_hit",
                lesson_generated="Pullback confirmation worked.",
                created_at=datetime.utcnow(),
            )
        )
        db.commit()

        payload = TraderBrainService().paper_trading(db)

    assert payload["mode"] == "paper_only"
    assert payload["no_broker_execution"] is True
    assert payload["snapshot_type"] == "PaperTradingSnapshot"
    assert payload["readiness_state"] == "READY"
    assert payload["completed_decisions"][0]["ticker"] == "AMD"
    assert payload["closed_decisions"][0]["entry"] == 100.0
    assert payload["closed_decisions"][0]["exit"] == 108.0
    assert payload["closed_decisions"][0]["position_size"] == 1.0
    assert payload["closed_decisions"][0]["r_multiple"] == 2.0
    assert payload["closed_decisions"][0]["trade_replay"]["risk_plan"]["stop"] == 96.0
    assert payload["completed_decisions"][0]["lesson_learned"] == "Pullback confirmation worked."


def test_paper_trading_empty_state_is_explicit_and_snapshot_first():
    with setup_db() as db:
        payload = TraderBrainService().paper_trading(db)

    assert payload["snapshot_type"] == "PaperTradingSnapshot"
    assert payload["readiness_state"] in {
        "NO_DECISIONS",
        "NO_ELIGIBLE_SETUPS",
        "NO_SNAPSHOTS",
        "WORKER_FAILED",
        "DATA_BLOCKED",
        "INSUFFICIENT_EVIDENCE",
    }
    assert payload["readiness_explanation"]
    assert payload["open_decisions"] == []
    assert payload["closed_decisions"] == []
    assert payload["journal_summary"]["open_count"] == 0


def test_alpha_page_reports_insufficient_evidence_instead_of_claiming_alpha(monkeypatch):
    monkeypatch.setattr("app.engine.brain.trader_brain.settings.paper_forward_lifecycle_enabled", False)
    with setup_db() as db:
        payload = TraderBrainService().alpha(db)

    assert payload["status"] == "NO_DATA"
    assert payload["evidence_grade"] == "NO_DATA"
    assert "evidence_split" in payload
    assert payload["historical"]["status"] == "NO_DATA"
    assert payload["paper_forward_lifecycle_mode"] == "CANDIDATE_FREEZE_ONLY"
    assert payload["paper_forward"]["evidence_reason"] == "Paper-forward lifecycle is currently disabled. BLUM is freezing decisions but not opening or closing trades."
    assert any(item["code"] == "paper_forward_lifecycle_disabled" for item in payload["current_blockers"])
    assert payload["policy"].startswith("Alpha page reports benchmark-relative paper-forward evidence")
    assert payload["verdict"] == "No paper-forward evidence yet."
    assert payload["current_blockers"]


def test_alpha_snapshot_shows_historical_evidence_when_paper_forward_has_no_closed_trades():
    with setup_db() as db:
        game = TradingGame(game_id="hist-alpha", current_capital=126.0, starting_capital=100.0)
        db.add(game)
        db.flush()
        db.add(
            TradingGameTrade(
                game_id=game.id,
                mode="historical_simulation",
                ticker="MSFT",
                setup_type="trend_continuation",
                exit_date=date(2026, 1, 20),
                net_pnl_eur=6.0,
                pnl_percent=6.0,
                realized_r_multiple=1.5,
                benchmark_return_same_period=2.0,
                excess_return_vs_benchmark=4.0,
                outcome_label="target_hit",
            )
        )
        db.commit()

        payload = TraderBrainService().alpha(db)

    split = payload["evidence_split"]
    assert payload["paper_forward"]["status"] == "NO_DATA"
    assert split["historical_replay"]["status"] == "ready"
    assert split["historical_replay"]["sample_size"] == 1
    assert split["historical_replay"]["benchmark_excess"] == 4.0
    assert payload["evidence_grade"] == "INSUFFICIENT_EVIDENCE"
    assert payload["verdict"] == "No paper-forward evidence yet. Historical evidence is available separately."
    assert payload["historical_alpha"] == 4.0
    assert payload["primary_evidence"]["source"] == "historical_replay"
    assert payload["total_evidence_sample_size"] == 1


def test_historical_alpha_recomputes_comparable_return_instead_of_trusting_inconsistent_excess():
    with setup_db() as db:
        game = TradingGame(game_id="hist-comparable-alpha", current_capital=100.1, starting_capital=100.0)
        db.add(game)
        db.flush()
        db.add(
            TradingGameTrade(
                game_id=game.id,
                mode="historical_simulation",
                ticker="NVDA",
                setup_type="momentum_breakout",
                entry_date=date(2026, 1, 2),
                exit_date=date(2026, 1, 20),
                entry_price=100.0,
                exit_price=110.0,
                net_pnl_eur=0.1,
                pnl_percent=0.1,
                realized_r_multiple=1.5,
                benchmark_return_same_period=2.0,
                excess_return_vs_benchmark=50.0,
                outcome_label="target_hit",
            )
        )
        db.commit()

        payload = TraderBrainService().alpha(db)

    historical = payload["evidence_split"]["historical_replay"]
    assert historical["blum_return"] == 10.0
    assert historical["benchmark_return"] == 2.0
    assert historical["benchmark_excess"] == 8.0
    assert historical["results"][0]["capital_return"] == 0.1


def test_alpha_snapshot_separates_walk_forward_validation_from_historical_benchmark_rows():
    with setup_db() as db:
        run = LearningRun(run_id="wf-run", status="completed", evaluation_mode="walk_forward_validation")
        db.add(run)
        db.flush()
        prediction = HistoricalPrediction(
            learning_run_id=run.id,
            ticker="NVDA",
            analysis_date=date(2026, 1, 2),
            expected_direction="bullish",
            confidence=0.64,
            prediction_payload={"learning_mode_metadata": {"mode": "walk_forward_validation", "walk_forward_validation": True}},
        )
        db.add(prediction)
        db.flush()
        db.add(
            PredictionOutcome(
                prediction_id=prediction.id,
                ticker="NVDA",
                timeframe="mid",
                horizon_days=30,
                realized_return=9.0,
                direction_correct=True,
                outcome_label="direction_correct",
            )
        )
        db.add(
            LearningBenchmarkComparison(
                mode="historical_simulation",
                benchmark_name="SPY",
                blum_return=20.0,
                benchmark_return=10.0,
                excess_return=10.0,
                sample_size=60,
                result_label="outperforming",
                calculated_at=datetime(2026, 1, 1, 10, 0, 0),
            )
        )
        db.add(
            LearningBenchmarkComparison(
                mode="walk_forward_validation",
                benchmark_name="SPY",
                blum_return=8.0,
                benchmark_return=3.0,
                excess_return=5.0,
                sample_size=40,
                result_label="outperforming",
                calculated_at=datetime(2026, 1, 2, 10, 0, 0),
            )
        )
        db.commit()

        payload = TraderBrainService().alpha(db)

    split = payload["evidence_split"]
    assert split["walk_forward_validation"]["status"] == "ready"
    assert split["walk_forward_validation"]["sample_size"] == 1
    assert split["walk_forward_validation"]["benchmark_excess"] == 5.0
    assert split["historical_replay"]["benchmark_excess"] == 10.0
    assert payload["walk_forward_alpha"] == 5.0
    assert payload["verdict"] == "Walk-forward evidence exists, paper-forward still insufficient."


def test_alpha_snapshot_uses_closed_paper_forward_evidence_without_blending_historical():
    with setup_db() as db:
        game = LiveForwardPaperGame(game_id="alpha-paper-forward", starting_capital=100.0, current_capital=108.0)
        db.add(game)
        db.flush()
        db.add(
            LiveForwardPaperTrade(
                trade_uid="pf-alpha-1",
                duplicate_key="pf-alpha-1",
                game_id=game.id,
                ticker="NVDA",
                setup_type="momentum_breakout",
                status="CLOSED",
                close_reason="TARGET_1_HIT",
                decision_timestamp=datetime.utcnow(),
                decision_date=date(2026, 1, 2),
                entry_price=100.0,
                exit_price=108.0,
                position_size=1.0,
                stop_loss=96.0,
                target_1=108.0,
                net_pnl_eur=8.0,
                pnl_percent=8.0,
                r_multiple=2.0,
                benchmark_return_same_period=2.0,
                excess_return_vs_benchmark=6.0,
                outcome_label="target_hit",
                lesson_learned="Momentum breakout worked only with volume confirmation.",
            )
        )
        db.add(LearningBenchmarkComparison(mode="historical_simulation", benchmark_name="SPY", blum_return=30.0, benchmark_return=10.0, excess_return=20.0, sample_size=100, result_label="outperforming"))
        db.commit()

        payload = TraderBrainService().alpha(db)

    assert payload["sample_size"] == 1
    assert payload["alpha"] == 6.0
    assert payload["paper_forward_alpha"] == 6.0
    assert payload["historical_alpha"] == 20.0
    assert payload["evidence_grade"] == "INSUFFICIENT_EVIDENCE"
    assert payload["latest_alpha_lessons"][0]["ticker"] == "NVDA"


def test_product_surface_is_reduced_to_four_primary_pages():
    root = Path(__file__).resolve().parents[2] / "frontend" / "components" / "AppShell.tsx"
    text = root.read_text()

    assert 'label: "Brain"' in text
    assert 'label: "Training Ground"' in text
    assert 'label: "Paper Trading"' in text
    assert 'label: "Alpha"' in text
    assert 'label: "Radar"' not in text
    assert 'label: "Signals"' not in text
    assert 'label: "Performance"' not in text


def test_brain_page_renders_learning_profit_and_copy_readiness_from_one_snapshot():
    frontend = Path(__file__).resolve().parents[2] / "frontend"
    page_text = (frontend / "app" / "brain" / "page.tsx").read_text()
    styles_text = (frontend / "app" / "globals.css").read_text()
    charts_path = frontend / "components" / "BrainEvidenceCharts.tsx"

    assert page_text.count("api.traderBrain()") == 1
    assert "BrainEvidenceCharts" in page_text
    assert 'className="terminal-command-grid brain-command-grid"' in page_text
    assert ".brain-command-grid" in styles_text
    assert "repeat(6, minmax(0, 1fr))" in styles_text
    assert "safeNumber(data?.brain_score) + 1" not in page_text
    assert charts_path.exists()

    charts_text = charts_path.read_text()
    assert "Brain Improvement" in charts_text
    assert "P/L vs Benchmark" in charts_text
    assert "Learning Throughput" in charts_text
    assert "Copy Trading Gate" in charts_text
    assert "Insufficient evidence" in charts_text
    assert "COPY_READY_PAPER_ONLY" in charts_text


def test_legacy_pages_are_lightweight_aliases():
    frontend = Path(__file__).resolve().parents[2] / "frontend" / "app"

    assert (frontend / "learning" / "page.tsx").read_text().strip() == 'export { default } from "../training-ground/page";'
    assert (frontend / "copy-trading" / "page.tsx").read_text().strip() == 'export { default } from "../paper-trading/page";'
    assert (frontend / "dashboard" / "page.tsx").read_text().strip() == 'export { default } from "../page";'


def test_paper_trading_page_uses_single_snapshot_and_readiness_states():
    page = Path(__file__).resolve().parents[2] / "frontend" / "app" / "paper-trading" / "page.tsx"
    text = page.read_text()

    assert "api.paperForwardSnapshot()" in text
    assert "api.paperForwardTrades(50)" in text
    assert "api.paperForwardTradeDetail(tradeId)" in text
    assert "api.paperForwardEvents(tradeId)" in text
    assert "Live-Forward Paper Trading" in text
    assert "NO_DECISIONS" in text
    assert "NO_ELIGIBLE_SETUPS" in text
    assert "NO_SNAPSHOTS" in text
    assert "WORKER_DISABLED" in text
    assert "DATA_BLOCKED" in text
    assert "INSUFFICIENT_EVIDENCE" in text
    assert "No completed trades" not in text
    assert "No raw JSON" not in text
    assert "Developer payload" in text
