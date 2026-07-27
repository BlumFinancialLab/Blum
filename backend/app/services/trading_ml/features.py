"""Point-in-time feature extraction for immutable stored trading evidence."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time
from typing import Any

from app.models import ForexDecision, ForexLearningEvidence, HistoricalPrediction, HyperbolicReplayTrade, PredictionOutcome

from .contracts import CATEGORICAL_FEATURES, NUMERIC_FEATURES, TradingMLExample


EVIDENCE_WEIGHTS = {
    "REPLAY_EVIDENCE": 0.25,
    "WALK_FORWARD_EVIDENCE": 0.75,
    "PAPER_FORWARD": 1.0,
    "PAPER_FORWARD_FOREX": 1.0,
    "LIVE_FORWARD": 1.0,
}


class FutureFeatureDataError(ValueError):
    """Raised when an input snapshot contains data newer than the decision."""


class UnlabeledFeatureDataError(ValueError):
    """Raised when a source does not contain a realized supervised target."""


class TradingMLFeatureBuilder:
    """Builds point-in-time labeled examples without reading mutable state."""

    def from_equity(self, prediction: HistoricalPrediction, outcome: PredictionOutcome) -> TradingMLExample:
        realized = _number(_first((outcome.metrics_payload or {},), "realized_net_r"))
        if realized is None:
            realized = _number(outcome.realized_return)
        if realized is None:
            raise UnlabeledFeatureDataError("equity outcome has no realized return")

        context = _without_future_data(_mapping(prediction.point_in_time_context))
        payload = _mapping(prediction.prediction_payload)
        decision_timestamp = _decision_timestamp(prediction.created_at, prediction.analysis_date)
        outcome_timestamp = _outcome_timestamp(outcome.evaluation_date, outcome.created_at)
        market_context = _mapping(context.get("market_context"))
        features = _features(
            sources=(payload, context, market_context),
            categorical={
                "market_family": "equity",
                "setup_type": _string(_first((payload, context), "setup_type", "setup_family"), "unknown"),
                "regime": _string(_first((market_context, context), "market_regime", "regime"), prediction.market_regime or "unknown"),
                "session": _string(_first((context,), "session"), "unknown"),
                "direction": _string(prediction.expected_direction, "neutral"),
                "timeframe": _string(_first((payload, context), "timeframe"), "unknown"),
                "sector_or_currency_family": _string(prediction.sector, "unknown"),
            },
            defaults={
                "confidence": prediction.confidence,
                "data_quality_score": prediction.data_quality_score,
                "volatility_score": _first((market_context,), "volatility_score") or prediction.volatility_regime,
            },
        )
        return TradingMLExample(
            source_object_type="historical_prediction",
            source_object_id=str(prediction.id),
            market_family="equity",
            evidence_lane="PAPER_FORWARD",
            decision_timestamp=decision_timestamp,
            outcome_timestamp=outcome_timestamp,
            asset_key=prediction.ticker,
            setup_type=str(features["setup_type"]),
            regime=str(features["regime"]),
            features=features,
            realized_net_r=realized,
            label_positive_r=int(realized > 0),
            benchmark_excess=_number(_first((outcome.metrics_payload or {},), "benchmark_excess")),
            sample_weight=_weight("PAPER_FORWARD"),
        )

    def from_forex(self, decision: ForexDecision, evidence: ForexLearningEvidence) -> TradingMLExample:
        snapshot = _mapping(decision.input_snapshot)
        _reject_future_timestamps(snapshot, decision.decision_timestamp)
        realized = _number(evidence.realized_result)
        if realized is None:
            raise UnlabeledFeatureDataError("Forex evidence has no realized result")

        proposal = _mapping(decision.proposal_json)
        risk = _mapping(decision.risk_json)
        payload = _mapping(evidence.payload_json)
        features = _features(
            sources=(proposal, risk, snapshot, payload),
            categorical={
                "market_family": "forex",
                "setup_type": _string(evidence.setup_family or proposal.get("setup_family"), "unknown"),
                "regime": _string(evidence.regime or _first((snapshot, payload), "regime"), "unknown"),
                "session": _string(evidence.session or snapshot.get("session"), "unknown"),
                "direction": _string(evidence.direction or decision.direction, "neutral"),
                "timeframe": _string(_first((proposal, snapshot), "timeframe"), "unknown"),
                "sector_or_currency_family": _currency_family(decision.pair),
            },
            defaults={"confidence": proposal.get("confidence")},
        )
        return TradingMLExample(
            source_object_type="forex_decision",
            source_object_id=str(decision.id),
            market_family="forex",
            evidence_lane=evidence.evidence_type,
            decision_timestamp=decision.decision_timestamp,
            outcome_timestamp=_outcome_timestamp(payload.get("evaluated_at"), evidence.created_at),
            asset_key=decision.pair,
            setup_type=str(features["setup_type"]),
            regime=str(features["regime"]),
            features=features,
            realized_net_r=realized,
            label_positive_r=int(realized > 0),
            benchmark_excess=_number(payload.get("benchmark_excess")),
            sample_weight=_weight(evidence.evidence_type),
        )

    def from_replay(self, trade: HyperbolicReplayTrade) -> TradingMLExample:
        realized = _number(trade.r_multiple)
        if realized is None or trade.exit_timestamp is None:
            raise UnlabeledFeatureDataError("replay trade has no closed realized R")

        decision = _mapping(trade.decision_payload)
        execution = _mapping(trade.execution_payload)
        outcome = _mapping(trade.outcome_payload)
        market_family = "forex" if trade.market.upper() == "FOREX" else "equity"
        features = _features(
            sources=(decision, execution, outcome),
            categorical={
                "market_family": market_family,
                "setup_type": _string(trade.setup_type, "unknown"),
                "regime": _string(_first((decision, outcome), "regime"), "unknown"),
                "session": _string(_first((decision,), "session"), "unknown"),
                "direction": _string(_first((decision,), "direction"), "neutral"),
                "timeframe": _string(trade.timeframe, "unknown"),
                "sector_or_currency_family": _currency_family(trade.ticker) if market_family == "forex" else _string(trade.market, "unknown"),
            },
            defaults={"data_quality_score": trade.data_quality_score},
        )
        return TradingMLExample(
            source_object_type="hyperbolic_replay_trade",
            source_object_id=str(trade.id),
            market_family=market_family,
            evidence_lane=trade.evidence_type,
            decision_timestamp=trade.decision_timestamp,
            outcome_timestamp=trade.exit_timestamp,
            asset_key=trade.ticker,
            setup_type=str(features["setup_type"]),
            regime=str(features["regime"]),
            features=features,
            realized_net_r=realized,
            label_positive_r=int(realized > 0),
            benchmark_excess=_number(trade.benchmark_excess),
            sample_weight=_weight(trade.evidence_type),
        )


def _features(*, sources: tuple[Mapping[str, Any], ...], categorical: dict[str, str], defaults: Mapping[str, Any]) -> dict[str, float | str | None]:
    features: dict[str, float | str | None] = {name: None for name in NUMERIC_FEATURES}
    aliases = {
        "aggregate_score": ("aggregate_score", "score"),
        "confidence": ("aggregate_confidence", "confidence"),
        "trend_score": ("trend_score",),
        "momentum_score": ("momentum_score",),
        "volume_score": ("volume_score",),
        "volatility_score": ("volatility_score",),
        "support_resistance_score": ("support_resistance_score",),
        "sentiment_score": ("sentiment_score",),
        "narrative_score": ("narrative_score",),
        "fundamental_score": ("fundamental_score",),
        "regime_score": ("regime_score",),
        "expected_gross_r": ("expected_gross_r", "expected_r"),
        "expected_net_r": ("expected_net_r",),
        "expected_cost": ("expected_cost", "total_cost"),
        "stop_distance": ("stop_distance",),
        "target_distance": ("target_distance",),
        "data_quality_score": ("data_quality_score", "quality_score"),
        "liquidity_score": ("liquidity_score",),
        "spread": ("spread",),
        "slippage": ("slippage", "slippage_cost"),
        "volatility": ("volatility",),
        "recent_return": ("recent_return",),
        "multi_timeframe_trend": ("multi_timeframe_trend",),
        "contextual_bandit_adjustment": ("contextual_bandit_adjustment", "confidence_adjustment"),
        "contextual_bandit_sample_size": ("contextual_bandit_sample_size", "sample_size"),
    }
    for name, keys in aliases.items():
        value = _first(sources, *keys)
        if value is None:
            value = defaults.get(name)
        features[name] = _number(value)
    features.update({name: categorical.get(name, "unknown") for name in CATEGORICAL_FEATURES})
    return features


def _first(sources: tuple[Mapping[str, Any], ...], *keys: str) -> Any:
    for source in sources:
        for key in keys:
            value = _nested_value(source, key)
            if value is not None:
                return value
    return None


def _nested_value(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        if value.get(key) is not None:
            return value[key]
        for nested in value.values():
            found = _nested_value(nested, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _nested_value(nested, key)
            if found is not None:
                return found
    return None


def _reject_future_timestamps(snapshot: Mapping[str, Any], decision_timestamp: datetime) -> None:
    for path, key, value in _walk(snapshot):
        if not _is_market_timestamp_key(key):
            continue
        timestamp = _parse_timestamp(value)
        if timestamp is not None and _later_than(timestamp, decision_timestamp):
            raise FutureFeatureDataError(f"future snapshot data at {path}")


def _walk(value: Any, path: str = "input_snapshot"):
    if isinstance(value, Mapping):
        for key, nested in value.items():
            nested_path = f"{path}.{key}"
            yield nested_path, str(key), nested
            yield from _walk(nested, nested_path)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _walk(nested, f"{path}[{index}]")


def _is_market_timestamp_key(key: str) -> bool:
    normalized = key.lower()
    return normalized in {"as_of", "acquired_at", "captured_at", "market_time"} or "timestamp" in normalized


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _later_than(left: datetime, right: datetime) -> bool:
    if (left.tzinfo is None) != (right.tzinfo is None):
        left = left.replace(tzinfo=None)
        right = right.replace(tzinfo=None)
    return left > right


def _decision_timestamp(created_at: datetime | None, analysis_date: date | datetime | None) -> datetime:
    if created_at is not None:
        return created_at
    if isinstance(analysis_date, datetime):
        return analysis_date
    if isinstance(analysis_date, date):
        return datetime.combine(analysis_date, time.min)
    raise UnlabeledFeatureDataError("prediction has no decision timestamp")


def _outcome_timestamp(value: date | datetime | str | None, fallback: datetime | None) -> datetime:
    parsed = _parse_timestamp(value)
    if parsed is not None:
        return parsed
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if fallback is not None:
        return fallback
    raise UnlabeledFeatureDataError("outcome has no evaluation timestamp")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _without_future_data(value: Mapping[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, nested in value.items():
        if key == "future_prices":
            continue
        if isinstance(nested, Mapping):
            sanitized[key] = _without_future_data(nested)
        elif isinstance(nested, list):
            sanitized[key] = [
                _without_future_data(item) if isinstance(item, Mapping) else item
                for item in nested
            ]
        else:
            sanitized[key] = nested
    return sanitized


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string(value: Any, default: str) -> str:
    return str(value) if value not in (None, "") else default


def _weight(evidence_lane: str) -> float:
    return EVIDENCE_WEIGHTS.get(evidence_lane, 1.0)


def _currency_family(pair: str) -> str:
    return pair.replace("=X", "")[:6] or "unknown"
