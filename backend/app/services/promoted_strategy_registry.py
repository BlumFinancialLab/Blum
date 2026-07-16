from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ReplayStrategyValidation, StrategyCandidateVariant
from app.services.intraday_contracts import PromotedIntradayStrategy, REQUIRED_INTRADAY_TIMEFRAMES


settings = get_settings()


class BlumPromotedStrategyRegistry:
    """Read-only projection of replay validations eligible for paper-forward use."""

    def list_eligible(self, db: Session, *, market: str, asset_class: str) -> list[PromotedIntradayStrategy]:
        rows = db.scalars(
            select(ReplayStrategyValidation)
            .join(StrategyCandidateVariant, StrategyCandidateVariant.validation_id == ReplayStrategyValidation.id)
            .where(ReplayStrategyValidation.verdict == "PROMOTED_TO_PAPER")
            .where(StrategyCandidateVariant.is_champion.is_(True))
            .order_by(desc(ReplayStrategyValidation.created_at), desc(ReplayStrategyValidation.id))
        ).all()
        latest_by_setup: dict[str, ReplayStrategyValidation] = {}
        for row in rows:
            latest_by_setup.setdefault(row.setup_type, row)
        output: list[PromotedIntradayStrategy] = []
        for row in latest_by_setup.values():
            projection = self._project(row)
            if projection and self._supports(projection, market=market, asset_class=asset_class):
                output.append(projection)
        return sorted(output, key=lambda item: (item.walk_forward_score, item.validated_trade_count), reverse=True)

    def status(self, db: Session) -> dict:
        promoted = db.scalars(
            select(ReplayStrategyValidation)
            .join(StrategyCandidateVariant, StrategyCandidateVariant.validation_id == ReplayStrategyValidation.id)
            .where(ReplayStrategyValidation.verdict == "PROMOTED_TO_PAPER")
            .where(StrategyCandidateVariant.is_champion.is_(True))
            .order_by(desc(ReplayStrategyValidation.created_at))
        ).all()
        eligible = [projection for row in promoted if (projection := self._project(row)) is not None]
        return {
            "promoted_rows": len(promoted),
            "eligible_intraday_strategies": len(eligible),
            "strategy_ids": [row.strategy_id for row in eligible],
            "minimum_samples": settings.replay_min_promotion_samples,
            "status": "READY" if eligible else "NO_PROMOTED_STRATEGIES",
        }

    def _project(self, row: ReplayStrategyValidation) -> PromotedIntradayStrategy | None:
        metrics = row.metrics_json if isinstance(row.metrics_json, dict) else {}
        if metrics.get("certification_version") != "alpha_strategy_factory_v1":
            return None
        if not bool(metrics.get("multiple_testing_significant")):
            return None
        sample_size = int(row.sample_size or 0)
        stability = number(metrics.get("stability_score"), 0.0)
        expectancy = number(
            metrics.get("expectancy_r"),
            number(metrics.get("net_expectancy_r"), 0.0),
        )
        benchmark_excess = number(metrics.get("benchmark_excess"), 0.0)
        deflated_sharpe = number(metrics.get("deflated_sharpe_probability"), 0.0) * 100.0
        derived_walk_forward_score = min(stability, deflated_sharpe) if deflated_sharpe > 0 else stability
        timeframe_stack = tuple(metrics.get("timeframe_stack") or REQUIRED_INTRADAY_TIMEFRAMES)
        if sample_size < settings.replay_min_promotion_samples:
            return None
        if float(row.overfitting_score or 100.0) >= 70.0:
            return None
        if stability < 50.0 or expectancy <= 0.0 or benchmark_excess <= 0.0:
            return None
        if timeframe_stack != REQUIRED_INTRADAY_TIMEFRAMES:
            return None
        markets = tuple(str(value).upper() for value in (row.markets_json or []))
        asset_classes = tuple(str(value) for value in (metrics.get("supported_asset_classes") or ["Stock", "ETF"]))
        return PromotedIntradayStrategy(
            validation_id=row.id,
            strategy_id=f"replay-validation-{row.id}",
            setup_type=row.setup_type,
            supported_markets=markets,
            supported_asset_classes=asset_classes,
            timeframe_stack=timeframe_stack,
            entry_rules=dict(metrics.get("entry_rules") or {}),
            stop_rules=dict(metrics.get("stop_rules") or {}),
            target_rules=dict(metrics.get("target_rules") or {}),
            minimum_confidence=number(metrics.get("minimum_confidence"), 60.0),
            minimum_edge_score=number(metrics.get("minimum_edge_score"), settings.blum_quant_edge_min_score),
            validated_trade_count=sample_size,
            walk_forward_score=number(metrics.get("walk_forward_score"), derived_walk_forward_score),
            expected_costs=dict(metrics.get("expected_costs") or {}),
            max_allowed_drawdown=abs(number(metrics.get("max_drawdown"), 0.0)),
            promotion_timestamp=row.created_at,
            model_version=str(metrics.get("model_version") or "replay-validation-v1"),
            evidence_type=row.evidence_type,
            metrics=metrics,
        )

    @staticmethod
    def _supports(strategy: PromotedIntradayStrategy, *, market: str, asset_class: str) -> bool:
        requested_market = normalize_market(market)
        supported = {normalize_market(value) for value in strategy.supported_markets}
        requested_class = str(asset_class or "").strip().lower()
        classes = {str(value).strip().lower() for value in strategy.supported_asset_classes}
        return requested_market in supported and requested_class in classes


def normalize_market(value: str) -> str:
    key = str(value or "").strip().upper()
    aliases = {
        "US": "USA",
        "UNITED STATES": "USA",
        "NASDAQ": "USA",
        "NYSE": "USA",
        "ITALY": "ITALY",
        "GERMANY": "GERMANY",
        "FRANCE": "FRANCE",
    }
    return aliases.get(key, key)


def number(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
