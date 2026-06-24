from datetime import date, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    AlphaLossAttribution,
    AlphaRecoveryAction,
    Asset,
    CapitalPreservationAlpha,
    DashboardSnapshot,
    LearningFactorImportance,
    LearningFocusPriority,
    MissedWinner,
    PriceHistory,
    ReasoningNoiseFlag,
    TradingGame,
    TradingGameTrade,
)
from app.services.financial_chat import meta_cognition_lines
from app.services.learning_loop import HistoricalSamplerService
from app.services.meta_cognition import (
    CapitalPreservationAlphaEngine,
    LearningFocusOptimizer,
    LearningImportanceEngine,
    MetaCognitionEngine,
    ReasoningNoiseDetector,
)


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_game(db: Session) -> TradingGame:
    game = TradingGame(
        game_id="meta-cognition-test",
        status="active",
        starting_capital=100.0,
        current_capital=104.0,
        benchmark_ticker="QQQ",
        target_capital=10000.0,
        trade_count=5,
    )
    db.add(game)
    db.flush()
    rows = [
        dict(ticker="NVDA", setup="momentum_breakout", sector="Technology", r=2.1, excess=8.0, decision="active_setup", outcome="target_hit", missed=False),
        dict(ticker="AMD", setup="momentum_breakout", sector="Technology", r=-1.0, excess=-5.0, decision="active_setup", outcome="stopped_out", missed=False),
        dict(ticker="META", setup="trend_continuation", sector="Communication Services", r=1.2, excess=5.0, decision="active_setup", outcome="target_hit", missed=False),
        dict(ticker="QQQ", setup="momentum_breakout", sector="Technology", r=0.0, excess=9.0, decision="wait_for_trigger", outcome="missed_entry", missed=True),
        dict(ticker="XLF", setup="defensive_rotation", sector="Financials", r=0.0, excess=-4.0, decision="avoid", outcome="no_trade_correct", missed=False),
    ]
    for index, row in enumerate(rows):
        db.add(
            TradingGameTrade(
                game_id=game.id,
                mode="historical_simulation",
                ticker=row["ticker"],
                setup_type=row["setup"],
                sector=row["sector"],
                market_regime_at_entry="risk_on",
                benchmark_ticker="QQQ",
                decision_state=row["decision"],
                actionability_state_at_entry=row["decision"],
                entry_date=date(2024, 1, 2) + timedelta(days=index),
                exit_date=date(2024, 1, 20) + timedelta(days=index),
                entry_price=100.0,
                exit_price=108.0,
                position_size=1.0,
                notional_value=100.0,
                risk_amount=1.0,
                risk_percent=1.0,
                realized_r_multiple=row["r"],
                realized_pl=row["r"],
                net_pnl_eur=row["r"],
                pnl_percent=row["excess"],
                capital_before=100.0,
                capital_after=100.0 + row["r"],
                max_favorable_excursion=abs(row["excess"]),
                max_adverse_excursion=-1.0,
                stop_hit=row["r"] < 0,
                target_hit=row["r"] > 1,
                missed_entry=row["missed"],
                benchmark_return_same_period=1.0,
                excess_return_vs_benchmark=row["excess"],
                outcome_label=row["outcome"],
                confidence_at_entry=65.0,
                sniper_score_at_entry=70.0,
                opportunity_score_at_entry=72.0,
                payload={"narrative": "AI infrastructure", "sentiment": "improving"},
                created_at=datetime.utcnow() + timedelta(seconds=index),
            )
        )
    db.add(
        AlphaLossAttribution(
            benchmark_name="QQQ",
            total_alpha_loss=-12.0,
            category="missed_entry",
            ticker="QQQ",
            setup_type="momentum_breakout",
            sector="Technology",
            contribution_value=-9.0,
            sample_size=5,
            confidence=45.0,
            explanation="Missed entry caused benchmark-relative drag.",
        )
    )
    db.add(
        MissedWinner(
            ticker="QQQ",
            decision_date=date(2024, 1, 4),
            benchmark_name="QQQ",
            future_return=12.0,
            benchmark_relative_return=9.0,
            blum_rank_at_decision=8,
            rejection_reason="blocked_by_no_trade_filter",
            confidence_at_decision=55.0,
            blocked_rule="rsi_only_avoidance",
            missed_signals_json=["sector momentum", "relative strength"],
            suggested_learning_action="Replay missed winner in risk-on tech regime.",
        )
    )
    db.add(
        AlphaRecoveryAction(
            action_type="pullback_retest_experiment",
            detected_problem="Missed entry rate is too high.",
            recommended_action="Test pullback-retest entries against breakout-close entries.",
            affected_module="EntryExitEngine",
            benchmark_name="QQQ",
            before_metric=-9.0,
            after_metric=-4.0,
            status="testing",
            rollback_available=True,
            priority="high",
            validation_status="in_progress",
            evidence_json={"sample_size": 20},
        )
    )
    db.commit()
    return game


def seed_asset_history(db: Session, ticker: str = "QQQ") -> Asset:
    asset = Asset(
        ticker=ticker,
        name=f"{ticker} Test Asset",
        category="ETF",
        sector="Technology",
        country="USA",
        asset_type="ETF",
        currency="USD",
        exchange="NASDAQ",
        is_active=True,
    )
    db.add(asset)
    db.flush()
    start = date(2019, 1, 1)
    for offset in range(1900):
        close = 100.0 + offset * 0.04
        db.add(
            PriceHistory(
                asset_id=asset.id,
                date=start + timedelta(days=offset),
                open=close - 0.2,
                high=close + 0.5,
                low=close - 0.5,
                close=close,
                volume=1_000_000 + offset,
                provider="test",
            )
        )
    db.commit()
    return asset


def test_factor_importance_is_evidence_bound_and_handles_insufficient_samples():
    with setup_db() as db:
        seed_game(db)

        payload = LearningImportanceEngine().recalculate(db, persist=True)
        rows = {row["factor_name"]: row for row in payload["rows"]}

        assert payload["status"] == "ready"
        assert rows["momentum"]["sample_size"] > 0
        assert rows["momentum"]["recommended_weight_action"] == "freeze_until_more_samples"
        assert "insufficient_sample_size" in rows["momentum"]["warnings"]
        assert db.scalar(select(LearningFactorImportance).where(LearningFactorImportance.factor_name == "momentum")) is not None


def test_capital_preservation_alpha_separates_avoided_loss_from_missed_gain():
    with setup_db() as db:
        seed_game(db)

        payload = CapitalPreservationAlphaEngine().evaluate(db, persist=True)
        rows = {row["ticker"]: row for row in payload["rows"]}

        assert rows["XLF"]["was_correct"] is True
        assert rows["XLF"]["capital_preserved"] > 0
        assert rows["QQQ"]["was_correct"] is False
        assert rows["QQQ"]["missed_gain"] > 0
        assert db.scalar(select(CapitalPreservationAlpha).where(CapitalPreservationAlpha.ticker == "XLF")) is not None


def test_learning_focus_and_noise_generation_create_auditable_records():
    with setup_db() as db:
        seed_game(db)
        CapitalPreservationAlphaEngine().evaluate(db, persist=True)
        LearningImportanceEngine().recalculate(db, persist=True)

        focus = LearningFocusOptimizer().generate(db, persist=True)
        noise = ReasoningNoiseDetector().detect(db, persist=True)

        assert focus["rows"]
        assert noise["rows"]
        assert db.scalar(select(LearningFocusPriority)) is not None
        assert db.scalar(select(ReasoningNoiseFlag)) is not None


def test_meta_cognition_recalculate_writes_snapshot_and_chat_uses_stored_evidence():
    with setup_db() as db:
        seed_game(db)

        summary = MetaCognitionEngine().recalculate_all(db)
        chat_lines = meta_cognition_lines(MetaCognitionEngine().summary(db), "it")

        assert summary["status"] == "ready"
        assert db.scalar(select(DashboardSnapshot).where(DashboardSnapshot.snapshot_type == "meta_cognition_summary")) is not None
        assert any("Fattore" in line or "Prossimo focus" in line for line in chat_lines)


def test_learning_loop_focus_priority_sampler_consumes_priorities_without_disabling_sampling():
    with setup_db() as db:
        seed_asset_history(db, "QQQ")
        db.add(
            LearningFocusPriority(
                priority_type="factor_importance_focus",
                target="QQQ",
                reason="Study missed tech winner.",
                expected_learning_value=90.0,
                urgency="high",
                sample_gap=20,
                status="active",
            )
        )
        db.commit()

        sample = HistoricalSamplerService().focus_priority_sample(db)

        assert sample is not None
        assert sample["asset"].ticker == "QQQ"
        assert sample["sampling_reason"] == "learning_focus_priority"
