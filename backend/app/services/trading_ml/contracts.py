"""Immutable contracts shared by trading ML training and inference."""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Literal


@dataclass(frozen=True)
class TradingMLExample:
    source_object_type: str
    source_object_id: str
    market_family: Literal["equity", "forex"]
    evidence_lane: str
    decision_timestamp: datetime
    outcome_timestamp: datetime
    asset_key: str
    setup_type: str
    regime: str
    features: dict[str, float | str | None]
    realized_net_r: float
    label_positive_r: int
    benchmark_excess: float | None
    sample_weight: float


@dataclass(frozen=True)
class TradingMLAdvice:
    status: str
    model_uid: str | None
    probability_positive_r: float | None
    predicted_net_r: float | None
    uncertainty: float | None
    confidence_adjustment: float
    veto_recommended: bool
    explanation: tuple[str, ...]
    guardrails: tuple[str, ...]


@dataclass(frozen=True)
class FeatureSchema:
    version: str
    feature_names: tuple[str, ...]

    @property
    def hash(self) -> str:
        payload = json.dumps(
            {"feature_names": self.feature_names, "version": self.version},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def current(cls) -> "FeatureSchema":
        return cls(version="trading-ml-features-v1", feature_names=FEATURE_NAMES)


NUMERIC_FEATURES = (
    "aggregate_score",
    "confidence",
    "trend_score",
    "momentum_score",
    "volume_score",
    "volatility_score",
    "support_resistance_score",
    "sentiment_score",
    "narrative_score",
    "fundamental_score",
    "regime_score",
    "expected_gross_r",
    "expected_net_r",
    "expected_cost",
    "stop_distance",
    "target_distance",
    "data_quality_score",
    "liquidity_score",
    "spread",
    "slippage",
    "volatility",
    "recent_return",
    "multi_timeframe_trend",
    "contextual_bandit_adjustment",
    "contextual_bandit_sample_size",
)

CATEGORICAL_FEATURES = (
    "market_family",
    "setup_type",
    "regime",
    "session",
    "direction",
    "timeframe",
    "sector_or_currency_family",
)

FEATURE_NAMES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
