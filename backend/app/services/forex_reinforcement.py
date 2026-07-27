from __future__ import annotations

from math import sqrt

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import ForexLearningEvidence, ForexPolicyState, ForexPolicyUpdate


class ForexReinforcementPolicyService:
    """Evidence-bound contextual bandit for completed Forex paper episodes."""

    policy_version = "forex-hierarchical-contextual-bandit-v2"
    minimum_positive_samples = 30
    minimum_negative_samples = 12
    maximum_confidence_adjustment = 0.08
    policy_scopes = ("STRATEGY", "SETUP", "REGIME_SETUP", "FULL_CONTEXT")

    def replay_pending(self, db: Session, *, limit: int = 50) -> dict:
        bounded_limit = max(1, min(int(limit), 200))
        rows = db.scalars(
            select(ForexLearningEvidence)
            .where(
                ForexLearningEvidence.outcome.in_(("WIN", "LOSS", "BREAKEVEN")),
                ForexLearningEvidence.realized_result.is_not(None),
                ForexLearningEvidence.evidence_strength >= 0.5,
                ~exists().where(
                    ForexPolicyUpdate.evidence_id == ForexLearningEvidence.id,
                    ForexPolicyUpdate.policy_scope == "STRATEGY",
                ),
            )
            .order_by(ForexLearningEvidence.id)
            .limit(bounded_limit + 1)
        ).all()
        processed = 0
        for evidence in rows[:bounded_limit]:
            if self.observe(db, evidence).get("status") == "UPDATED":
                processed += 1
        return {
            "status": "UPDATED" if processed else "IDLE",
            "processed": processed,
            "remaining_hint": len(rows) > bounded_limit,
        }

    def observe(self, db: Session, evidence: ForexLearningEvidence) -> dict:
        payload = evidence.payload_json if isinstance(evidence.payload_json, dict) else {}
        reward = _number(payload.get("reinforcement_reward_r"))
        if reward is None and evidence.outcome in {"WIN", "LOSS", "BREAKEVEN"}:
            reward = self._historical_reward(
                _number(evidence.realized_result),
                _number(payload.get("benchmark_excess")),
            )
            if reward is not None:
                payload = {
                    **payload,
                    "reinforcement_reward_r": reward,
                    "policy_update_eligible": evidence.evidence_strength >= 0.5,
                    "reward_policy": "net_r_plus_bounded_benchmark_excess_v1",
                    "reward_backfilled": True,
                }
                evidence.payload_json = payload
        if (
            evidence.id is None
            or not payload.get("policy_update_eligible")
            or evidence.outcome not in {"WIN", "LOSS", "BREAKEVEN"}
            or reward is None
        ):
            return {"status": "SKIPPED", "reason": "TERMINAL_REWARD_REQUIRED"}
        bounded_reward = max(-2.0, min(3.0, reward))
        updates = []
        for scope, context in self._scoped_contexts(evidence):
            applied = db.scalar(
                select(ForexPolicyUpdate).where(
                    ForexPolicyUpdate.evidence_id == evidence.id,
                    ForexPolicyUpdate.policy_scope == scope,
                )
            )
            if applied is not None:
                continue
            state = self._state(db, scope=scope, context=context)
            previous_q = float(state.q_value or 0.0)
            sample_after = int(state.sample_size or 0) + 1
            learning_rate = max(0.02, min(0.20, 1.0 / sqrt(sample_after)))
            new_q = previous_q + learning_rate * (bounded_reward - previous_q)
            state.sample_size = sample_after
            state.q_value = new_q
            state.reward_sum = float(state.reward_sum or 0.0) + bounded_reward
            state.reward_sq_sum = float(state.reward_sq_sum or 0.0) + bounded_reward**2
            state.win_count = int(state.win_count or 0) + int(evidence.outcome == "WIN")
            state.loss_count = int(state.loss_count or 0) + int(evidence.outcome == "LOSS")
            cause = str(evidence.likely_cause or payload.get("likely_cause") or "UNSPECIFIED")
            cause_counts = dict(state.cause_counts_json or {})
            cause_counts[cause] = int(cause_counts.get(cause) or 0) + 1
            state.cause_counts_json = cause_counts
            state.last_evidence_id = evidence.id
            state.policy_version = self.policy_version
            state.evidence_grade, state.confidence_adjustment = self._policy_gate(state)
            update = ForexPolicyUpdate(
                policy_state_id=state.id,
                evidence_id=evidence.id,
                policy_scope=scope,
                previous_q=previous_q,
                reward=bounded_reward,
                new_q=new_q,
                learning_rate=learning_rate,
                sample_size_after=sample_after,
                policy_version=self.policy_version,
            )
            db.add(update)
            db.flush()
            updates.append(
                {
                    "policy_scope": scope,
                    "policy_state_id": state.id,
                    "sample_size": state.sample_size,
                    "q_value": state.q_value,
                    "confidence_adjustment": state.confidence_adjustment,
                    "evidence_grade": state.evidence_grade,
                }
            )
        if not updates:
            return {"status": "ALREADY_APPLIED", "policy_scopes": list(self.policy_scopes)}
        return {
            "status": "UPDATED",
            "policy_scopes": [row["policy_scope"] for row in updates],
            "updates": updates,
        }

    @staticmethod
    def _historical_reward(realized_r: float | None, benchmark_excess: float | None) -> float | None:
        if realized_r is None:
            return None
        benchmark_component = max(-0.25, min(0.25, float(benchmark_excess or 0.0) * 10.0))
        return max(-2.0, min(3.0, realized_r + benchmark_component))

    def _policy_gate(self, state: ForexPolicyState) -> tuple[str, float]:
        count = int(state.sample_size or 0)
        if count < self.minimum_negative_samples:
            return "LEARNING_ONLY", 0.0
        mean = float(state.reward_sum or 0.0) / count
        variance = max(0.0, float(state.reward_sq_sum or 0.0) / count - mean**2)
        margin = 1.96 * sqrt(variance / count)
        lower, upper = mean - margin, mean + margin
        if count >= self.minimum_positive_samples and lower > 0:
            return "POLICY_ELIGIBLE", min(self.maximum_confidence_adjustment, 0.02 + min(mean, 1.0) * 0.06)
        if upper < 0:
            return "POLICY_ELIGIBLE", max(-self.maximum_confidence_adjustment, -0.02 + max(mean, -1.0) * 0.06)
        return ("INCONCLUSIVE" if count >= self.minimum_positive_samples else "LEARNING_ONLY"), 0.0

    def _state(
        self,
        db: Session,
        *,
        scope: str,
        context: tuple[str, str, str, str, str],
    ) -> ForexPolicyState:
        key = "|".join((scope, *context))
        state = db.scalar(
            select(ForexPolicyState).where(ForexPolicyState.policy_key == key)
        )
        if state is None:
            state = ForexPolicyState(
                policy_key=key,
                strategy_id=context[0],
                session=context[1],
                regime=context[2],
                setup_family=context[3],
                direction=context[4],
                evidence_grade="LEARNING_ONLY",
                policy_version=self.policy_version,
            )
            db.add(state)
            db.flush()
        return state

    def _scoped_contexts(
        self,
        evidence: ForexLearningEvidence,
    ) -> tuple[tuple[str, tuple[str, str, str, str, str]], ...]:
        strategy = evidence.strategy_id or "unknown"
        session = evidence.session or "UNKNOWN"
        regime = evidence.regime or "UNKNOWN"
        setup = evidence.setup_family or "UNKNOWN"
        direction = evidence.direction or "ABSTAIN"
        return (
            ("STRATEGY", (strategy, "ALL", "ALL", "ALL", "ALL")),
            ("SETUP", (strategy, "ALL", "ALL", setup, direction)),
            ("REGIME_SETUP", (strategy, "ALL", regime, setup, direction)),
            ("FULL_CONTEXT", (strategy, session, regime, setup, direction)),
        )


def _number(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
