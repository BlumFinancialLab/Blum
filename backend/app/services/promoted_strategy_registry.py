from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ReplayStrategyValidation, StrategyCandidateVariant
from app.services.intraday_contracts import (
    PAPER_FORWARD_INTRADAY_EXPERIMENTAL,
    PromotedIntradayStrategy,
    REQUIRED_INTRADAY_TIMEFRAMES,
)
from app.services.executable_strategy import canonical_strategy_spec


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
        experimental = [projection for row in self._experimental_rows(db) if (projection := self._project_experimental(row)) is not None]
        return {
            "promoted_rows": len(promoted),
            "eligible_intraday_strategies": len(eligible),
            "strategy_ids": [row.strategy_id for row in eligible],
            "minimum_samples": settings.replay_min_promotion_samples,
            "status": "READY" if eligible else "NO_PROMOTED_STRATEGIES",
            "experimental_eligible": len(experimental),
            "experimental_status": "READY" if experimental else "NO_EXPERIMENTAL_CHALLENGERS",
        }

    def list_experimental(self, db: Session, *, market: str, asset_class: str) -> list[PromotedIntradayStrategy]:
        """Return evidence-generating challengers without promoting them.

        These strategies remain excluded from certified alpha and copy-readiness.
        They may only create reduced-risk paper-forward observations.
        """

        latest_by_setup: dict[str, PromotedIntradayStrategy] = {}
        for row in self._experimental_rows(db):
            projection = self._project_experimental(row)
            if (
                projection
                and row.setup_type not in latest_by_setup
                and self._supports(projection, market=market, asset_class=asset_class)
            ):
                latest_by_setup[row.setup_type] = projection
        output = list(latest_by_setup.values())
        return sorted(output, key=lambda item: (item.walk_forward_score, item.validated_trade_count), reverse=True)

    def bootstrap_exploration(
        self,
        *,
        market: str,
        asset_class: str,
    ) -> PromotedIntradayStrategy:
        """Build a non-certified, reduced-risk contract for evidence collection.

        This contract is used only when the registry has no promoted or
        evidence-backed challenger. The normal signal, data, cost, liquidity,
        session, sizing, and execution gates still apply.
        """

        normalized_market = normalize_market(market)
        normalized_class = str(asset_class or "Stock").strip() or "Stock"
        spec = canonical_strategy_spec("intraday_breakout")
        risk_multiplier = min(
            0.10,
            max(
                0.05,
                float(settings.intraday_experimental_risk_multiplier),
            ),
        )
        slug = "-".join(
            part
            for part in (
                normalized_market.lower().replace("_", "-"),
                normalized_class.lower().replace("_", "-"),
            )
            if part
        )
        metrics = {
            "certification_version": "bootstrap_exploration_v1",
            "validation_verdict": "UNVALIDATED_EXPLORATION",
            "evidence_lane": "bootstrap_exploration_paper",
            "paper_risk_multiplier": risk_multiplier,
            "certified_for_copy_readiness": False,
            "net_expectancy_r": 0.0,
            "benchmark_excess": None,
            "sample_size": 0,
            "guardrail": (
                "Paper evidence only; strict point-in-time, cost, liquidity, "
                "risk, and execution gates remain mandatory."
            ),
        }
        return PromotedIntradayStrategy(
            validation_id=None,
            strategy_id=f"bootstrap-intraday-breakout-{slug}-v1",
            setup_type="intraday_breakout",
            supported_markets=(normalized_market,),
            supported_asset_classes=(normalized_class,),
            timeframe_stack=tuple(spec.required_timeframes),
            entry_rules={"entry_rule": spec.entry_rule},
            stop_rules={"stop_atr_multiple": spec.stop_atr_multiple},
            target_rules={"target_r_multiple": spec.target_r_multiple},
            minimum_confidence=50.0,
            minimum_edge_score=50.0,
            validated_trade_count=0,
            walk_forward_score=50.0,
            expected_costs={},
            max_allowed_drawdown=0.0,
            promotion_timestamp=datetime.utcnow(),
            model_version="bootstrap-exploration-v1",
            evidence_type=PAPER_FORWARD_INTRADAY_EXPERIMENTAL,
            executable_strategy=spec.to_payload(),
            metrics=metrics,
        )

    @staticmethod
    def _experimental_rows(db: Session) -> list[ReplayStrategyValidation]:
        return list(
            db.scalars(
                select(ReplayStrategyValidation)
                .join(StrategyCandidateVariant, StrategyCandidateVariant.validation_id == ReplayStrategyValidation.id)
                .where(ReplayStrategyValidation.verdict == "NEEDS_MORE_EVIDENCE")
                .where(StrategyCandidateVariant.is_champion.is_(False))
                .order_by(desc(ReplayStrategyValidation.created_at), desc(ReplayStrategyValidation.id))
                .limit(100)
            ).all()
        )

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
        markets = tuple(str(value).upper() for value in (row.markets_json or []))
        expected_stack = ("1h", "15m", "5m", "1m") if "1h" in timeframe_stack else REQUIRED_INTRADAY_TIMEFRAMES
        if sample_size < settings.replay_min_promotion_samples:
            return None
        overfitting_score = 100.0 if row.overfitting_score is None else float(row.overfitting_score)
        if overfitting_score >= 70.0:
            return None
        if stability < 50.0 or expectancy <= 0.0 or benchmark_excess <= 0.0:
            return None
        if timeframe_stack != expected_stack:
            return None
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
            executable_strategy=self._executable_strategy(row.setup_type, metrics),
            metrics=metrics,
        )

    def _project_experimental(self, row: ReplayStrategyValidation) -> PromotedIntradayStrategy | None:
        metrics = row.metrics_json if isinstance(row.metrics_json, dict) else {}
        sample_size = int(row.sample_size or 0)
        expectancy = number(metrics.get("net_expectancy_r"), number(metrics.get("expectancy_r"), 0.0))
        benchmark_excess = number(metrics.get("benchmark_excess"), 0.0)
        stability = number(
            metrics.get("experimental_stability_score"),
            number(metrics.get("stability_score"), 0.0),
        )
        data_quality = number(metrics.get("data_quality_score"), 0.0)
        cost_coverage = number(metrics.get("cost_coverage"), 0.0)
        timeframe_stack = tuple(metrics.get("timeframe_stack") or REQUIRED_INTRADAY_TIMEFRAMES)
        markets = tuple(str(value).upper() for value in (row.markets_json or []))
        expected_stack = ("1h", "15m", "5m", "1m") if "1h" in timeframe_stack else REQUIRED_INTRADAY_TIMEFRAMES
        if metrics.get("certification_version") != "alpha_strategy_factory_v1":
            return None
        if sample_size < max(30, int(settings.intraday_experimental_min_samples)):
            return None
        if expectancy <= 0.0 or benchmark_excess <= 0.0 or stability < 50.0:
            return None
        overfitting_score = 100.0 if row.overfitting_score is None else float(row.overfitting_score)
        if data_quality < 70.0 or cost_coverage < 1.0 or overfitting_score >= 70.0:
            return None
        if timeframe_stack != expected_stack:
            return None
        risk_multiplier = max(0.05, min(0.5, float(settings.intraday_experimental_risk_multiplier)))
        asset_classes = tuple(str(value) for value in (metrics.get("supported_asset_classes") or ["Stock", "ETF"]))
        experimental_metrics = {
            **metrics,
            "evidence_lane": "experimental_paper",
            "paper_risk_multiplier": risk_multiplier,
            "certified_for_copy_readiness": False,
            "validation_verdict": row.verdict,
        }
        return PromotedIntradayStrategy(
            validation_id=row.id,
            strategy_id=f"experimental-replay-validation-{row.id}",
            setup_type=row.setup_type,
            supported_markets=markets,
            supported_asset_classes=asset_classes,
            timeframe_stack=timeframe_stack,
            entry_rules=dict(metrics.get("entry_rules") or {}),
            stop_rules=dict(metrics.get("stop_rules") or {}),
            target_rules=dict(metrics.get("target_rules") or {}),
            minimum_confidence=min(50.0, number(metrics.get("minimum_confidence"), 50.0)),
            minimum_edge_score=min(50.0, number(metrics.get("minimum_edge_score"), 50.0)),
            validated_trade_count=sample_size,
            walk_forward_score=max(50.0, min(stability, 80.0)),
            expected_costs=dict(metrics.get("expected_costs") or {}),
            max_allowed_drawdown=abs(number(metrics.get("max_drawdown"), 0.0)),
            promotion_timestamp=row.created_at,
            model_version=str(metrics.get("model_version") or "experimental-replay-v1"),
            evidence_type=PAPER_FORWARD_INTRADAY_EXPERIMENTAL,
            executable_strategy=self._executable_strategy(row.setup_type, metrics),
            metrics=experimental_metrics,
        )

    @staticmethod
    def _executable_strategy(setup_type: str, metrics: dict) -> dict:
        payload = metrics.get("executable_strategy")
        if isinstance(payload, dict) and payload:
            return dict(payload)
        return canonical_strategy_spec(setup_type).to_payload()

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
