from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from math import sqrt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ForexLearningEvidence, ForexStrategyReadiness
from app.services.forex_contracts import ForexReadiness, ForexStrategyEvidence
from app.core.config import get_settings


TERMINAL_OUTCOMES = {
    "WIN", "LOSS", "BREAKEVEN", "CORRECT_NO_TRADE", "MISSED_OPPORTUNITY",
    "EDGE_DESTROYED_BY_COSTS", "ORDER_NOT_FILLED", "NEWS_BLOCK_CORRECT",
    "NEWS_BLOCK_INCORRECT", "RISK_BLOCK_CORRECT", "RISK_BLOCK_INCORRECT", "DATA_BLOCKED",
}


@dataclass(frozen=True)
class ForexReadinessAssessment:
    strategy_id: str
    level: ForexReadiness
    sample_size: int
    net_expectancy_r: float | None
    blockers: tuple[str, ...]
    risk_adjusted_alpha: float | None = None
    max_drawdown_r: float | None = None
    confidence_interval: tuple[float, float] | None = None
    threshold_version: str = "forex-alpha-readiness-v1"


class BlumForexLearningEngine:
    minimum_alpha_forward_trades = 100

    def __init__(self) -> None:
        settings = get_settings()
        self.minimum_alpha_forward_trades = max(100, int(settings.forex_alpha_min_forward_trades))
        self.minimum_expectancy_r = max(0.0, float(settings.forex_alpha_min_expectancy_r))
        self.minimum_benchmark_excess = max(0.0, float(settings.forex_alpha_min_benchmark_excess))
        self.maximum_drawdown_r = max(1.0, float(settings.forex_alpha_max_drawdown_r))
        self.minimum_pairs = max(1, int(settings.forex_alpha_min_pairs))
        self.minimum_sessions = max(1, int(settings.forex_alpha_min_sessions))
        self.minimum_regimes = max(1, int(settings.forex_alpha_min_regimes))
        self.maximum_replay_forward_decay = max(0.0, float(settings.forex_alpha_max_replay_forward_decay))
        self.maximum_currency_concentration = min(1.0, max(0.0, float(settings.forex_alpha_max_currency_concentration)))
        self.threshold_version = settings.forex_alpha_threshold_version

    def record_outcome(self, db: Session, *, decision_id: int | None, outcome: str, payload: dict) -> ForexLearningEvidence | None:
        if outcome not in TERMINAL_OUTCOMES:
            return None
        payload = dict(payload)
        expected = _number(payload.get("expected_result"))
        realized = _number(payload.get("realized_result"))
        reward = self._reinforcement_reward(outcome, realized, _number(payload.get("benchmark_excess")))
        payload["reinforcement_reward_r"] = reward
        payload["policy_update_eligible"] = bool(
            reward is not None
            and outcome in {"WIN", "LOSS", "BREAKEVEN"}
            and float(payload.get("evidence_strength") or 0.0) >= 0.5
        )
        payload["reward_policy"] = "net_r_plus_bounded_benchmark_excess_v1"
        row = ForexLearningEvidence(
            decision_id=decision_id,
            position_id=payload.get("position_id"),
            strategy_id=str(payload.get("strategy_id") or "unknown"),
            pair=str(payload.get("pair") or "unknown"),
            session=payload.get("session"),
            regime=payload.get("regime"),
            setup_family=payload.get("setup_family"),
            direction=payload.get("direction"),
            outcome=outcome,
            expected_result=expected,
            realized_result=realized,
            difference=(realized - expected) if expected is not None and realized is not None else None,
            likely_cause=payload.get("likely_cause"),
            lesson=str(payload.get("lesson") or self._lesson(outcome)),
            evidence_strength=float(payload.get("evidence_strength") or 0.5),
            model_update_justified=bool(payload.get("model_update_justified", False)),
            evidence_type="PAPER_FORWARD_FOREX",
            payload_json=dict(payload),
        )
        db.add(row)
        db.flush()
        return row

    @staticmethod
    def _reinforcement_reward(outcome: str, realized_r: float | None, benchmark_excess: float | None) -> float | None:
        if outcome not in {"WIN", "LOSS", "BREAKEVEN"} or realized_r is None:
            return None
        benchmark_component = max(-0.25, min(0.25, float(benchmark_excess or 0.0) * 10.0))
        return max(-2.0, min(3.0, realized_r + benchmark_component))

    def assess_readiness(self, strategy: ForexStrategyEvidence, evidence: list[dict]) -> ForexReadinessAssessment:
        terminal = [row for row in evidence if row.get("outcome") in TERMINAL_OUTCOMES]
        closed = [row for row in terminal if row.get("outcome") in {"WIN", "LOSS", "BREAKEVEN"}]
        values = [float(row.get("net_r") or 0.0) for row in closed]
        expectancy = mean(values) if values else None
        benchmark_values = [float(row.get("benchmark_excess_r") or row.get("benchmark_excess") or 0.0) for row in closed]
        benchmark_alpha = mean(benchmark_values) if benchmark_values else None
        stdev = (sum((value - expectancy) ** 2 for value in values) / max(1, len(values) - 1)) ** 0.5 if values and expectancy is not None else 0.0
        stderr = stdev / sqrt(len(values)) if values else 0.0
        confidence_interval = (expectancy - 1.96 * stderr, expectancy + 1.96 * stderr) if expectancy is not None else None
        equity, peak, max_drawdown = 0.0, 0.0, 0.0
        for value in values:
            equity += value
            peak = max(peak, equity)
            max_drawdown = min(max_drawdown, equity - peak)
        blockers = []
        if len(closed) < self.minimum_alpha_forward_trades:
            blockers.append("MINIMUM_FORWARD_SAMPLE")
        if expectancy is None or expectancy <= self.minimum_expectancy_r:
            blockers.append("NON_POSITIVE_NET_EXPECTANCY")
        if benchmark_alpha is None or benchmark_alpha <= self.minimum_benchmark_excess:
            blockers.append("NON_POSITIVE_RISK_ADJUSTED_ALPHA")
        if confidence_interval is None or confidence_interval[0] <= 0:
            blockers.append("CONFIDENCE_INTERVAL_INCLUDES_NO_EDGE")
        if max_drawdown < -self.maximum_drawdown_r:
            blockers.append("MAX_DRAWDOWN")
        if len({row.get("pair") for row in closed}) < self.minimum_pairs:
            blockers.append("PAIR_COVERAGE")
        if len({row.get("session") for row in closed}) < self.minimum_sessions:
            blockers.append("SESSION_COVERAGE")
        if len({row.get("regime") for row in closed}) < self.minimum_regimes:
            blockers.append("REGIME_COVERAGE")
        if strategy.replay_forward_decay is None or strategy.replay_forward_decay > self.maximum_replay_forward_decay:
            blockers.append("REPLAY_FORWARD_DECAY")
        if strategy.currency_concentration is None or strategy.currency_concentration > self.maximum_currency_concentration:
            blockers.append("CURRENCY_CONCENTRATION")
        if strategy.active_blockers:
            blockers.append("ACTIVE_STRATEGY_BLOCKER")
        if len(closed) >= self.minimum_alpha_forward_trades and expectancy is not None and expectancy < -0.15:
            level = ForexReadiness.SUSPENDED
        elif len(closed) >= 30 and expectancy is not None and expectancy <= 0:
            level = ForexReadiness.DEGRADED
        elif not blockers:
            level = ForexReadiness.ALPHA_SIGNAL_ELIGIBLE
        else:
            level = strategy.readiness if strategy.readiness != ForexReadiness.ALPHA_SIGNAL_ELIGIBLE else ForexReadiness.DEGRADED
        return ForexReadinessAssessment(
            strategy.strategy_id,
            level,
            len(closed),
            expectancy,
            tuple(blockers),
            benchmark_alpha,
            max_drawdown,
            confidence_interval,
            self.threshold_version,
        )

    def refresh_readiness(self, db: Session, strategy: ForexStrategyEvidence) -> ForexStrategyReadiness:
        rows = db.scalars(
            select(ForexLearningEvidence)
            .where(ForexLearningEvidence.strategy_id == strategy.strategy_id, ForexLearningEvidence.evidence_type == "PAPER_FORWARD_FOREX")
            .order_by(ForexLearningEvidence.created_at, ForexLearningEvidence.id)
            .limit(5000)
        ).all()
        evidence = [
            {
                "outcome": row.outcome, "net_r": row.realized_result,
                "benchmark_excess": (row.payload_json or {}).get("benchmark_excess"),
                "pair": row.pair, "session": row.session, "regime": row.regime,
            }
            for row in rows
        ]
        assessment = self.assess_readiness(strategy, evidence)
        stored = db.scalar(select(ForexStrategyReadiness).where(ForexStrategyReadiness.strategy_id == strategy.strategy_id))
        if stored is None:
            stored = ForexStrategyReadiness(strategy_id=strategy.strategy_id)
            db.add(stored)
        stored.readiness_level = assessment.level.value
        stored.closed_forward_trades = assessment.sample_size
        stored.net_expectancy_r = assessment.net_expectancy_r
        stored.risk_adjusted_alpha = assessment.risk_adjusted_alpha
        stored.max_drawdown = assessment.max_drawdown_r
        stored.pair_count = len({row.pair for row in rows if row.outcome in {"WIN", "LOSS", "BREAKEVEN"}})
        stored.session_count = len({row.session for row in rows if row.session})
        stored.regime_count = len({row.regime for row in rows if row.regime})
        stored.confidence_interval_json = {"lower": assessment.confidence_interval[0], "upper": assessment.confidence_interval[1]} if assessment.confidence_interval else {}
        stored.replay_forward_decay = strategy.replay_forward_decay
        stored.blockers = list(assessment.blockers)
        stored.threshold_version = assessment.threshold_version
        db.flush()
        return stored

    @staticmethod
    def _lesson(outcome: str) -> str:
        return {
            "EDGE_DESTROYED_BY_COSTS": "Keep the setup blocked until expected movement exceeds spread, slippage and commission.",
            "CORRECT_NO_TRADE": "The abstention preserved paper capital under the observed conditions.",
            "MISSED_OPPORTUNITY": "Replay this rejection and test whether confirmation rules were too restrictive.",
            "WIN": "Retain the process as evidence; one outcome is not sufficient for promotion.",
            "LOSS": "Inspect regime, entry, cost and invalidation evidence before changing weights.",
        }.get(outcome, "Persist the terminal outcome as forward Forex evidence.")


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
