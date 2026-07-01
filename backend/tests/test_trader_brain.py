from datetime import date, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    LearningBenchmarkComparison,
    LearningFocusPriority,
    LearningRun,
    SelfImprovementAction,
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
    assert validation["status"] == "budget_wait"
    assert validation["display_status"] == "waiting_budget_using_latest_evidence"
    assert validation["evidence_total"]["predictions_generated"] == 8
    assert validation["evidence_total"]["outcomes_evaluated"] == 6
    assert validation["latest_productive_run"]["predictions_generated"] == 8
    assert "stored evidence exists" in validation["summary"]
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


def test_alpha_page_reports_insufficient_evidence_instead_of_claiming_alpha():
    with setup_db() as db:
        payload = TraderBrainService().alpha(db)

    assert payload["status"] == "INSUFFICIENT_EVIDENCE"
    assert payload["historical"]["status"] == "insufficient_evidence"
    assert payload["policy"].startswith("Alpha page reports benchmark-relative evidence")


def test_product_surface_is_reduced_to_four_primary_pages():
    root = Path(__file__).resolve().parents[2] / "frontend" / "components" / "AppShell.tsx"
    text = root.read_text()

    assert 'label: "Brain"' in text
    assert 'label: "Training"' in text
    assert 'label: "Paper Trading"' in text
    assert 'label: "Alpha"' in text
    assert 'label: "Radar"' not in text
    assert 'label: "Signals"' not in text
    assert 'label: "Performance"' not in text


def test_legacy_pages_are_lightweight_aliases():
    frontend = Path(__file__).resolve().parents[2] / "frontend" / "app"

    assert (frontend / "learning" / "page.tsx").read_text().strip() == 'export { default } from "../training-ground/page";'
    assert (frontend / "copy-trading" / "page.tsx").read_text().strip() == 'export { default } from "../paper-trading/page";'
    assert (frontend / "dashboard" / "page.tsx").read_text().strip() == 'export { default } from "../page";'


def test_paper_trading_page_uses_single_snapshot_and_readiness_states():
    page = Path(__file__).resolve().parents[2] / "frontend" / "app" / "paper-trading" / "page.tsx"
    text = page.read_text()

    assert "api.traderPaperTrading(40)" in text
    assert "PaperTradingSnapshot" in text
    assert "NO_DECISIONS" in text
    assert "NO_ELIGIBLE_SETUPS" in text
    assert "NO_SNAPSHOTS" in text
    assert "WORKER_FAILED" in text
    assert "DATA_BLOCKED" in text
    assert "INSUFFICIENT_EVIDENCE" in text
    assert "No completed trades" not in text
    assert "Trade Replay is intentionally lazy-rendered" in text
