from datetime import date, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    Asset,
    FeedbackLoopAudit,
    HistoricalPrediction,
    LearningFocusPriority,
    LearningRun,
    ModelVersion,
    PriceHistory,
    SignalPerformance,
    StrategyMemory,
)
from app.services.learning_loop import (
    BASE_SIGNAL_WEIGHTS,
    LearningLoopService,
    ModelScoreService,
    PredictionEngine,
)


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def prediction_context() -> dict:
    return {
        "asset": {"ticker": "NVDA", "sector": "Technology"},
        "analysis_date": "2024-06-01",
        "initial_price": 100.0,
        "technical": {
            "status": "ready",
            "trend_direction": "uptrend",
            "moving_averages": {"alignment": "bullish_stack"},
            "technical_indicators": {"rsi": 62.0, "macd_hist": 1.0},
            "volume": {"relative_volume": 1.2},
            "volatility": {"regime": "medium"},
            "levels": {"nearest_support": 94.0, "nearest_resistance": 118.0, "invalidation_level": 94.0},
            "risk_reward_estimate": {"status": "estimated"},
            "technical_summary": "Uptrend with constructive momentum.",
        },
        "fundamentals": {"status": "ready", "quality_score": 56.0},
        "news": {"article_count_total_as_of": 10, "article_count_14d": 8, "average_quality_14d": 2.0, "themes_14d": [{"theme": "AI"}]},
        "macro": {"status": "ready"},
        "market_context": {"market_regime": "Bull Expansion", "volatility_regime": "Low"},
        "data_quality_score": 76.0,
        "point_in_time_policy": {"future": "hidden"},
    }


def seed_asset_history(db: Session) -> Asset:
    asset = Asset(
        ticker="NVDA",
        name="NVIDIA",
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
    start = date(2020, 1, 1)
    for offset in range(1250):
        close = 100.0 + offset * 0.05
        db.add(
            PriceHistory(
                asset_id=asset.id,
                date=start + timedelta(days=offset),
                open=close - 0.5,
                high=close + 1.0,
                low=close - 1.0,
                close=close,
                volume=1_000_000 + offset * 100,
                provider="test",
            )
        )
    db.commit()
    return asset


def test_active_model_version_weights_change_future_prediction_output():
    with setup_db() as db:
        base = PredictionEngine().predict(prediction_context())
        learned_weights = dict(BASE_SIGNAL_WEIGHTS)
        learned_weights["sentiment"] = 0.72
        learned_weights["trend_structure"] = 0.04
        db.add(
            ModelVersion(
                version="learned-sentiment-heavy",
                model_name="BLUM Learning Loop",
                weights=learned_weights,
                previous_weights=BASE_SIGNAL_WEIGHTS,
                is_active=True,
            )
        )
        db.commit()

        learned = PredictionEngine().predict(prediction_context(), db=db)

    assert learned["model_version_used"] == "learned-sentiment-heavy"
    assert learned["weights_used"]["sentiment"] > base["weights_used"]["sentiment"]
    assert learned["prediction"]["aggregate_score"] != base["prediction"]["aggregate_score"]


def test_signal_performance_and_strategy_memory_change_confidence():
    with setup_db() as db:
        context = prediction_context()
        base = PredictionEngine().predict(context, db=db)
        db.add(
            SignalPerformance(
                signal_name="trend_structure",
                timeframe="mid",
                market_regime="Bull Expansion",
                sample_count=20,
                correct_count=16,
                false_positive_count=1,
                false_negative_count=0,
                reliability_score=78.0,
                weight_adjustment=0.05,
            )
        )
        db.add(
            StrategyMemory(
                memory_key="volume_confirmation:relative-volume",
                category="volume_confirmation",
                lesson="Momentum setups improve when volume confirms.",
                conditions={"relative_volume_gt": 1.0},
                reliability_score=72.0,
                sample_count=8,
                positive_count=6,
                negative_count=2,
            )
        )
        db.commit()

        learned = PredictionEngine().predict(context, db=db)

    assert learned["feedback_loop"]["learning_memory_used"]["signal_performance"]
    assert learned["feedback_loop"]["strategy_memory_used"]["rows"]
    assert learned["feedback_loop"]["confidence_adjustment"] > 0
    assert learned["prediction"]["aggregate_confidence"] > base["prediction"]["aggregate_confidence"]


def test_run_single_sample_persists_weights_memory_research_priority_and_audit():
    with setup_db() as db:
        asset = seed_asset_history(db)
        focus = LearningFocusPriority(
            priority_type="missed_entry_replay",
            target="NVDA",
            reason="Replay high-quality missed entries.",
            expected_learning_value=88.0,
            urgency="high",
            status="active",
        )
        run = LearningRun(run_id="feedback-run", status="running", trigger="test")
        db.add_all([focus, run])
        db.add(
            ModelVersion(
                version="learned-active",
                model_name="BLUM Learning Loop",
                weights={**BASE_SIGNAL_WEIGHTS, "momentum": 0.5},
                previous_weights=BASE_SIGNAL_WEIGHTS,
                is_active=True,
            )
        )
        db.commit()

        report = LearningLoopService().run_single_sample(
            db,
            run,
            {
                "asset": asset,
                "analysis_date": date(2022, 5, 1),
                "sampling_reason": "learning_focus_priority",
                "learning_focus_priority_id": focus.id,
                "priority_type": focus.priority_type,
            },
        )
        prediction = db.scalar(select(HistoricalPrediction).where(HistoricalPrediction.ticker == "NVDA"))
        audit = db.scalar(select(FeedbackLoopAudit).where(FeedbackLoopAudit.prediction_id == prediction.id))

    assert prediction.model_version_used == "learned-active"
    assert prediction.weights_used["momentum"] > BASE_SIGNAL_WEIGHTS["momentum"]
    assert prediction.learning_memory_used["policy"].startswith("SignalPerformance")
    assert prediction.strategy_memory_used["policy"].startswith("StrategyMemory")
    assert prediction.research_priority_used["priority_type"] == "missed_entry_replay"
    assert report["feedback_loop_audit"]["model_version_used"] == "learned-active"
    assert audit is not None
    assert audit.future_decision_json["ticker"] == "NVDA"


def test_model_version_is_not_created_with_insufficient_evidence():
    with setup_db() as db:
        db.add(
            SignalPerformance(
                signal_name="momentum",
                timeframe="short",
                market_regime="Bull Expansion",
                sample_count=1,
                correct_count=1,
                false_positive_count=0,
                false_negative_count=0,
                reliability_score=85.0,
                weight_adjustment=0.1,
            )
        )
        db.commit()

        result = ModelScoreService().recalculate(db)

    assert result["status"] == "insufficient_evidence"
    assert result["thresholds"]["min_outcomes"] >= 30
    assert db.scalar(select(ModelVersion)) is None
