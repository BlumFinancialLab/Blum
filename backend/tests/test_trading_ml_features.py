from datetime import datetime, timedelta

import pytest

from app.models import ForexDecision, ForexLearningEvidence, HistoricalPrediction, HyperbolicReplayTrade, PredictionOutcome
from app.services.trading_ml import FeatureSchema, FutureFeatureDataError, TradingMLFeatureBuilder


DECISION_AT = datetime(2026, 1, 2, 10, 0)


def equity_prediction() -> HistoricalPrediction:
    return HistoricalPrediction(
        id=101,
        ticker="NVDA",
        asset_type="Equity",
        sector="Technology",
        market="USA",
        market_regime="risk_on",
        volatility_regime="normal",
        analysis_date=DECISION_AT.date(),
        initial_price=140.0,
        expected_direction="bullish",
        confidence=72.0,
        data_quality_score=91.0,
        prediction_payload={
            "prediction": {"aggregate_score": 0.7, "aggregate_confidence": 72.0},
            "timeframes": {"1d": {"expected_r": 1.5, "expected_net_r": 1.2}},
        },
        point_in_time_context={
            "market_timestamp": DECISION_AT.isoformat(),
            "data_quality_score": 91.0,
            "market_context": {"market_regime": "risk_on", "volatility_regime": "normal"},
            "future_prices": [{"timestamp": "2026-01-03T10:00:00", "close": 145.0}],
        },
        created_at=DECISION_AT,
    )


def equity_outcome(*, realized_return: float) -> PredictionOutcome:
    return PredictionOutcome(
        id=201,
        prediction_id=101,
        ticker="NVDA",
        timeframe="1d",
        horizon_days=1,
        evaluation_date=(DECISION_AT + timedelta(days=1)).date(),
        realized_return=realized_return,
        metrics_payload={"benchmark_excess": 0.8},
    )


def forex_decision_with_frame_timestamp(*, market_timestamp: datetime, decision_timestamp: datetime) -> ForexDecision:
    return ForexDecision(
        id=301,
        decision_uid="fx-decision-301",
        pair="EURUSD=X",
        strategy_id="fx-breakout-v1",
        status="APPROVED",
        direction="LONG",
        decision_timestamp=decision_timestamp,
        evidence_type="PAPER_FORWARD_FOREX",
        proposal_json={
            "setup_family": "momentum_breakout",
            "expected_r": 1.4,
            "confidence": 74.0,
        },
        input_snapshot={
            "market": {
                "timestamp": market_timestamp.isoformat(),
                "trend_score": 0.4,
                "spread": 0.0001,
            },
            "frames": [{"as_of": market_timestamp.isoformat(), "momentum_score": 0.6}],
        },
    )


def forex_evidence() -> ForexLearningEvidence:
    return ForexLearningEvidence(
        id=401,
        decision_id=301,
        strategy_id="fx-breakout-v1",
        pair="EURUSD=X",
        session="LONDON",
        regime="trend",
        setup_family="momentum_breakout",
        direction="LONG",
        outcome="WIN",
        expected_result=1.4,
        realized_result=0.8,
        evidence_strength=0.9,
        evidence_type="PAPER_FORWARD_FOREX",
        payload_json={"benchmark_excess": 0.2, "evaluated_at": "2026-01-02T11:00:00"},
        created_at=DECISION_AT + timedelta(hours=1),
    )


def test_equity_feature_builder_uses_only_frozen_prediction_context():
    example = TradingMLFeatureBuilder().from_equity(
        prediction=equity_prediction(),
        outcome=equity_outcome(realized_return=4.0),
    )

    assert example.market_family == "equity"
    assert example.label_positive_r == 1
    assert example.decision_timestamp <= example.outcome_timestamp
    assert "future_prices" not in example.features


def test_equity_feature_builder_does_not_read_nested_future_prices():
    prediction = equity_prediction()
    prediction.point_in_time_context["future_prices"] = [{"trend_score": 99.0}]

    example = TradingMLFeatureBuilder().from_equity(prediction, equity_outcome(realized_return=4.0))

    assert example.features["trend_score"] is None


def test_feature_schema_is_stable_and_normalizes_missing_numeric_values():
    prediction = equity_prediction()
    prediction.prediction_payload = {}
    example = TradingMLFeatureBuilder().from_equity(prediction, equity_outcome(realized_return=-1.0))

    assert FeatureSchema.current().version == "trading-ml-features-v1"
    assert example.features["trend_score"] is None
    assert example.features["market_family"] == "equity"
    assert FeatureSchema.current().hash == FeatureSchema.current().hash


def test_forex_feature_builder_rejects_future_snapshot_data():
    decision = forex_decision_with_frame_timestamp(
        market_timestamp=datetime(2026, 1, 2, 10, 1),
        decision_timestamp=DECISION_AT,
    )

    with pytest.raises(FutureFeatureDataError):
        TradingMLFeatureBuilder().from_forex(decision, forex_evidence())


def test_forex_feature_builder_preserves_only_point_in_time_snapshot_data():
    decision = forex_decision_with_frame_timestamp(
        market_timestamp=datetime(2026, 1, 2, 10, 0),
        decision_timestamp=DECISION_AT,
    )

    example = TradingMLFeatureBuilder().from_forex(decision, forex_evidence())

    assert example.source_object_type == "forex_decision"
    assert example.source_object_id == "301"
    assert example.realized_net_r == 0.8
    assert example.sample_weight == 1.0
    assert example.features["session"] == "LONDON"


def test_replay_feature_builder_uses_evidence_weight_and_closed_outcome():
    trade = HyperbolicReplayTrade(
        id=501,
        ticker="EURUSD=X",
        market="FOREX",
        setup_type="momentum_breakout",
        strategy_fingerprint="fx-breakout-v1",
        timeframe="1m",
        state="REPLAY_EVALUATED",
        evidence_type="REPLAY_EVIDENCE",
        decision_timestamp=DECISION_AT,
        exit_timestamp=DECISION_AT + timedelta(minutes=5),
        r_multiple=1.2,
        benchmark_excess=0.2,
        data_quality_score=95.0,
        decision_payload={"regime": "trend", "session": "LONDON", "direction": "LONG"},
        execution_payload={"total_cost": 0.1},
    )

    example = TradingMLFeatureBuilder().from_replay(trade)

    assert example.market_family == "forex"
    assert example.realized_net_r == 1.2
    assert example.sample_weight == 0.25
    assert example.label_positive_r == 1
