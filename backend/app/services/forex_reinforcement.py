from __future__ import annotations

from math import sqrt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ForexLearningEvidence, ForexPolicyState, ForexPolicyUpdate


class ForexReinforcementPolicyService:
    """Evidence-bound contextual bandit for completed Forex paper episodes."""

    policy_version = "forex-contextual-bandit-v1"
    minimum_policy_samples = 30
    maximum_confidence_adjustment = 0.08

    def replay_pending(self, db: Session, *, limit: int = 50) -> dict:
        bounded_limit = max(1, min(int(limit), 200))
        rows = db.scalars(
            select(ForexLearningEvidence)
            .outerjoin(ForexPolicyUpdate, ForexPolicyUpdate.evidence_id == ForexLearningEvidence.id)
            .where(
                ForexPolicyUpdate.id.is_(None),
                ForexLearningEvidence.outcome.in_(("WIN", "LOSS", "BREAKEVEN")),
                ForexLearningEvidence.realized_result.is_not(None),
                ForexLearningEvidence.evidence_strength >= 0.5,
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
        applied = db.scalar(select(ForexPolicyUpdate).where(ForexPolicyUpdate.evidence_id == evidence.id))
        if applied is not None:
            return {"status": "ALREADY_APPLIED", "policy_state_id": applied.policy_state_id}

        context = (
            evidence.strategy_id or "unknown",
            evidence.session or "UNKNOWN",
            evidence.regime or "UNKNOWN",
            evidence.setup_family or "UNKNOWN",
            evidence.direction or "ABSTAIN",
        )
        key = "|".join(context)
        state = db.scalar(select(ForexPolicyState).where(ForexPolicyState.policy_key == key))
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

        previous_q = float(state.q_value or 0.0)
        sample_after = int(state.sample_size or 0) + 1
        learning_rate = max(0.02, min(0.20, 1.0 / sqrt(sample_after)))
        bounded_reward = max(-2.0, min(3.0, reward))
        new_q = previous_q + learning_rate * (bounded_reward - previous_q)
        state.sample_size = sample_after
        state.q_value = new_q
        state.reward_sum = float(state.reward_sum or 0.0) + bounded_reward
        state.reward_sq_sum = float(state.reward_sq_sum or 0.0) + bounded_reward**2
        state.win_count = int(state.win_count or 0) + int(evidence.outcome == "WIN")
        state.loss_count = int(state.loss_count or 0) + int(evidence.outcome == "LOSS")
        state.last_evidence_id = evidence.id
        state.policy_version = self.policy_version
        state.evidence_grade, state.confidence_adjustment = self._policy_gate(state)
        db.add(
            ForexPolicyUpdate(
                policy_state_id=state.id,
                evidence_id=evidence.id,
                previous_q=previous_q,
                reward=bounded_reward,
                new_q=new_q,
                learning_rate=learning_rate,
                sample_size_after=sample_after,
                policy_version=self.policy_version,
            )
        )
        db.flush()
        return {
            "status": "UPDATED",
            "policy_state_id": state.id,
            "sample_size": state.sample_size,
            "q_value": state.q_value,
            "confidence_adjustment": state.confidence_adjustment,
            "evidence_grade": state.evidence_grade,
        }

    @staticmethod
    def _historical_reward(realized_r: float | None, benchmark_excess: float | None) -> float | None:
        if realized_r is None:
            return None
        benchmark_component = max(-0.25, min(0.25, float(benchmark_excess or 0.0) * 10.0))
        return max(-2.0, min(3.0, realized_r + benchmark_component))

    def _policy_gate(self, state: ForexPolicyState) -> tuple[str, float]:
        count = int(state.sample_size or 0)
        if count < self.minimum_policy_samples:
            return "LEARNING_ONLY", 0.0
        mean = float(state.reward_sum or 0.0) / count
        variance = max(0.0, float(state.reward_sq_sum or 0.0) / count - mean**2)
        margin = 1.96 * sqrt(variance / count)
        lower, upper = mean - margin, mean + margin
        if lower > 0:
            return "POLICY_ELIGIBLE", min(self.maximum_confidence_adjustment, 0.02 + min(mean, 1.0) * 0.06)
        if upper < 0:
            return "POLICY_ELIGIBLE", max(-self.maximum_confidence_adjustment, -0.02 + max(mean, -1.0) * 0.06)
        return "INCONCLUSIVE", 0.0


def _number(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
