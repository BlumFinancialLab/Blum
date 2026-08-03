from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import time
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import (
    AgentCouncilReflection,
    AgentCouncilRun,
    AgentCouncilTurn,
    BackgroundJobState,
    BlumKnowledgeRecord,
    BlumThesisOutcome,
    EngineVote,
    ModelReliabilityMatrix,
)
from app.services.central_brain_runtime import BackgroundJobStateService, BrainEventBus
from app.services.dashboard_snapshots import DashboardSnapshotService


_DIRECTION = {"bullish": 1.0, "buy": 1.0, "bearish": -1.0, "sell": -1.0}


def _bounded(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return round(max(low, min(high, float(value))), 4)


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


class EvidenceBoundDecisionCouncil:
    """Turns stored BLUM evidence into an auditable multi-agent decision.

    The council is deliberately deterministic. It never fetches market data or
    calls an LLM: every turn cites evidence frozen before the council clock.
    """

    stages = ("analyst", "research_debate", "risk_debate", "portfolio_verdict")

    def __init__(self, *, min_evidence_sources: int = 2, min_memory_samples: int = 5) -> None:
        self.min_evidence_sources = max(2, min_evidence_sources)
        self.min_memory_samples = max(1, min_memory_samples)

    def run_for_record(self, db: Session, record_id: int, *, as_of: datetime | None = None) -> dict:
        decision_clock = as_of or datetime.utcnow()
        record = db.get(BlumKnowledgeRecord, record_id)
        if record is None:
            return {"status": "REJECTED", "reason": "knowledge_record_not_found", "record_id": record_id}
        if record.created_at and record.created_at > decision_clock:
            return {"status": "REJECTED", "reason": "knowledge_created_after_decision_clock", "record_id": record_id}

        raw_votes = list(
            db.scalars(
                select(EngineVote)
                .where(EngineVote.thesis_id == record.id, EngineVote.created_at <= decision_clock)
                .order_by(EngineVote.engine_name, desc(EngineVote.created_at), desc(EngineVote.id))
            )
        )
        latest_by_engine: dict[str, EngineVote] = {}
        for vote in raw_votes:
            latest_by_engine.setdefault(vote.engine_name, vote)
        votes = sorted(latest_by_engine.values(), key=lambda row: row.id)
        evidence_fingerprint = ":".join(f"{vote.id}:{vote.vote}:{vote.confidence}" for vote in votes)
        run_uid = hashlib.sha256(
            f"decision-council-v2:{record.id}:{record.reasoning_hash}:{evidence_fingerprint}".encode("utf-8")
        ).hexdigest()
        run = db.scalar(select(AgentCouncilRun).where(AgentCouncilRun.run_uid == run_uid).limit(1))
        if run is not None and run.status == "COMPLETED":
            return self._serialize(run)

        if run is None:
            run = AgentCouncilRun(
                run_uid=run_uid,
                knowledge_record_id=record.id,
                ticker=record.ticker,
                sector=record.sector or "Unknown",
                market_regime=record.market_regime or "Unknown",
                as_of=decision_clock,
                source_snapshot_json=self._source_snapshot(record, decision_clock),
            )
            db.add(run)
            db.flush()

        try:
            analyses = self._weighted_votes(db, record, votes, decision_clock)
            source_snapshot = dict(run.source_snapshot_json or {})
            source_snapshot["engine_votes"] = [
                {
                    "vote_id": item["vote_id"],
                    "engine": item["engine_name"],
                    "stance": item["stance"],
                    "confidence": item["confidence"],
                    "evidence_quality": item["evidence_quality"],
                    "reliability": item["reliability"],
                }
                for item in analyses
            ]
            run.source_snapshot_json = source_snapshot
            self._persist_analyst_turns(db, run, analyses)
            self._checkpoint(run, "research_debate", 1, {"analysts": len(analyses)})
            db.commit()

            score = self._directional_score(analyses)
            disagreement = self._disagreement(analyses)
            evidence_quality = self._evidence_quality(analyses)
            self._persist_research_debate(db, run, record, analyses, score)
            self._checkpoint(run, "risk_debate", 2, {"directional_score": score})
            db.commit()

            trade_plan = _as_dict(_as_dict(record.blum_reasoning).get("trade_plan"))
            risk = self._persist_risk_debate(db, run, trade_plan, score, disagreement, evidence_quality)
            self._checkpoint(run, "portfolio_verdict", 3, risk)
            db.commit()

            memory = self._memory(db, record, decision_clock)
            warnings: list[str] = []
            if len(analyses) < self.min_evidence_sources:
                warnings.append("insufficient_independent_evidence")
            if risk["invalidation_level"] is None:
                warnings.append("missing_invalidation")
            if risk["risk_reward"] is None:
                warnings.append("missing_risk_reward")
            if evidence_quality < 40:
                warnings.append("weak_evidence_quality")
            if disagreement >= 60:
                warnings.append("high_engine_disagreement")

            action = "BUY" if score >= 0.20 else "SELL" if score <= -0.20 else "WAIT"
            if warnings or risk["risk_reward"] is None or risk["risk_reward"] < 1.2:
                action = "WAIT"
            base_confidence = self._base_confidence(analyses, score, disagreement)
            final_confidence = _bounded(base_confidence + memory["adjustment"], 0.0, 95.0)
            if action == "WAIT":
                final_confidence = min(final_confidence, 59.0)

            verdict = {
                "action": action,
                "confidence": final_confidence,
                "directional_score": round(score, 6),
                "invalidation_level": risk["invalidation_level"],
                "stop_loss": risk["stop_loss"],
                "risk_reward": risk["risk_reward"],
                "source_record_id": record.id,
                "source_reasoning_hash": record.reasoning_hash,
                "as_of": decision_clock.isoformat(),
                "evidence_sources": [item["engine_name"] for item in analyses],
                "memory_used": memory,
                "warnings": warnings,
                "reason": self._verdict_reason(action, score, warnings),
            }
            self._add_turn(
                db,
                run,
                stage="portfolio_verdict",
                agent_name="portfolio_manager",
                sequence=100,
                stance=action.lower(),
                confidence=final_confidence,
                reliability=1.0,
                argument=verdict["reason"],
                supporting=[{"engine": item["engine_name"], "stance": item["stance"]} for item in analyses],
                contradicting=[{"warning": warning} for warning in warnings],
                refs=[{"type": "blum_knowledge_record", "id": record.id}],
            )

            run.status = "COMPLETED"
            run.current_stage = "completed"
            run.stage_cursor = 4
            run.base_confidence = base_confidence
            run.final_confidence = final_confidence
            run.final_action = action
            run.disagreement_score = disagreement
            run.evidence_quality = evidence_quality
            run.memory_adjustment = memory["adjustment"]
            run.final_decision_json = verdict
            run.warnings_json = warnings
            run.error_message = ""
            run.completed_at = datetime.utcnow()

            reasoning = dict(_as_dict(record.blum_reasoning))
            reasoning["decision_council"] = {
                "run_id": run.id,
                "action": action,
                "confidence": final_confidence,
                "disagreement_score": disagreement,
                "evidence_quality": evidence_quality,
                "memory_adjustment": memory["adjustment"],
                "as_of": decision_clock.isoformat(),
            }
            record.blum_reasoning = reasoning
            db.commit()
            return self._serialize(run)
        except Exception as exc:
            db.rollback()
            failed = db.scalar(select(AgentCouncilRun).where(AgentCouncilRun.run_uid == run_uid).limit(1))
            if failed is not None:
                failed.status = "FAILED"
                failed.error_message = f"{type(exc).__name__}: {exc}"[:4000]
                failed.updated_at = datetime.utcnow()
                db.commit()
            raise

    def reflect_mature_outcomes(self, db: Session, *, limit: int = 50) -> dict:
        rows = db.execute(
            select(AgentCouncilRun, BlumThesisOutcome)
            .join(BlumThesisOutcome, BlumThesisOutcome.knowledge_record_id == AgentCouncilRun.knowledge_record_id)
            .outerjoin(
                AgentCouncilReflection,
                (AgentCouncilReflection.run_id == AgentCouncilRun.id)
                & (AgentCouncilReflection.outcome_id == BlumThesisOutcome.id),
            )
            .where(AgentCouncilRun.status == "COMPLETED", AgentCouncilReflection.id.is_(None))
            .order_by(BlumThesisOutcome.id)
            .limit(max(1, limit))
        ).all()
        created = 0
        for run, outcome in rows:
            realized = float(outcome.realized_return) if outcome.realized_return is not None else None
            benchmark_value = _as_dict(outcome.outcome_payload).get("benchmark_return")
            benchmark = float(benchmark_value) if benchmark_value is not None else None
            excess = realized - benchmark if realized is not None and benchmark is not None else None
            direction_correct = self._direction_correct(run.final_action, realized)
            helpful = direction_correct
            lesson = self._reflection_lesson(run.final_action, direction_correct, excess)
            db.add(
                AgentCouncilReflection(
                    run_id=run.id,
                    outcome_id=outcome.id,
                    ticker=run.ticker,
                    sector=run.sector,
                    market_regime=run.market_regime,
                    horizon_days=outcome.horizon_days,
                    expected_action=run.final_action,
                    realized_return=realized,
                    benchmark_return=benchmark,
                    excess_return=excess,
                    direction_correct=direction_correct,
                    actionability_was_helpful=helpful,
                    lesson=lesson,
                    evidence_json={
                        "outcome": outcome.outcome,
                        "success": outcome.success,
                        "source_record_id": run.knowledge_record_id,
                        "decision_confidence": run.final_confidence,
                    },
                )
            )
            created += 1
        db.commit()
        return {"created": created, "considered": len(rows)}

    def _source_snapshot(self, record: BlumKnowledgeRecord, as_of: datetime) -> dict:
        return {
            "record_id": record.id,
            "ticker": record.ticker,
            "reasoning_hash": record.reasoning_hash,
            "record_created_at": record.created_at.isoformat() if record.created_at else None,
            "decision_clock": as_of.isoformat(),
            "market_context": _as_dict(record.market_context),
            "asset_context": _as_dict(record.asset_context),
            "policy": "stored_point_in_time_evidence_only",
        }

    def _weighted_votes(self, db: Session, record: BlumKnowledgeRecord, votes: list[EngineVote], as_of: datetime) -> list[dict]:
        engine_names = {vote.engine_name for vote in votes}
        reliability_rows = []
        if engine_names:
            reliability_rows = list(
                db.scalars(
                    select(ModelReliabilityMatrix).where(
                        ModelReliabilityMatrix.engine_name.in_(engine_names),
                        ModelReliabilityMatrix.updated_at <= as_of,
                        ModelReliabilityMatrix.market_regime.in_([record.market_regime, "All", "all"]),
                        ModelReliabilityMatrix.sector.in_([record.sector, "All", "all"]),
                    )
                )
            )
        reliability_by_engine: dict[str, ModelReliabilityMatrix] = {}
        for row in reliability_rows:
            current = reliability_by_engine.get(row.engine_name)
            row_specificity = int(row.market_regime == record.market_regime) + int(row.sector == record.sector)
            current_specificity = (
                int(current.market_regime == record.market_regime) + int(current.sector == record.sector)
                if current is not None
                else -1
            )
            if current is None or (row_specificity, row.updated_at, row.id) > (current_specificity, current.updated_at, current.id):
                reliability_by_engine[row.engine_name] = row
        output = []
        for vote in votes:
            reliability_row = reliability_by_engine.get(vote.engine_name)
            stored = float(vote.reliability_weight_at_time or 0.5)
            if reliability_row is not None and int(reliability_row.sample_size or 0) >= 20:
                stored = float(reliability_row.reliability_score or 50.0) / 100.0
            output.append(
                {
                    "vote_id": vote.id,
                    "engine_name": vote.engine_name,
                    "stance": str(vote.vote or "neutral").lower(),
                    "direction": _DIRECTION.get(str(vote.vote or "").lower(), 0.0),
                    "confidence": _bounded(vote.confidence or 0.0),
                    "evidence_quality": _bounded(vote.evidence_quality or 0.0),
                    "reliability": _bounded(stored, 0.05, 1.0),
                }
            )
        return output

    def _persist_analyst_turns(self, db: Session, run: AgentCouncilRun, analyses: list[dict]) -> None:
        for sequence, item in enumerate(analyses, start=1):
            self._add_turn(
                db,
                run,
                stage="analyst",
                agent_name=item["engine_name"],
                sequence=sequence,
                stance=item["stance"],
                confidence=item["confidence"],
                reliability=item["reliability"],
                argument=f"{item['engine_name']} voted {item['stance']} from stored evidence.",
                supporting=[{"vote_id": item["vote_id"], "evidence_quality": item["evidence_quality"]}],
                refs=[{"type": "engine_vote", "id": item["vote_id"]}],
            )

    def _persist_research_debate(self, db: Session, run: AgentCouncilRun, record: BlumKnowledgeRecord, analyses: list[dict], score: float) -> None:
        positive = [item for item in analyses if item["direction"] > 0]
        negative = [item for item in analyses if item["direction"] < 0]
        critique = _as_dict(record.self_critique)
        skeptic = _as_dict(critique.get("skeptic_view"))
        self._add_turn(db, run, stage="research_debate", agent_name="bull_researcher", sequence=30, stance="bullish", confidence=self._side_confidence(positive), reliability=0.7, argument="Bull case is supported only by aligned stored engine votes.", supporting=positive, refs=self._vote_refs(positive))
        self._add_turn(db, run, stage="research_debate", agent_name="bear_researcher", sequence=31, stance="bearish", confidence=self._side_confidence(negative), reliability=0.7, argument="Bear case includes contrary votes and the stored skeptic critique.", supporting=negative, contradicting=_as_list(skeptic.get("key_points")), refs=self._vote_refs(negative))
        self._add_turn(db, run, stage="research_debate", agent_name="research_manager", sequence=32, stance="bullish" if score > 0.2 else "bearish" if score < -0.2 else "neutral", confidence=_bounded(abs(score) * 100), reliability=0.8, argument="Research manager resolves the debate from reliability-weighted directional evidence.", supporting=analyses, refs=self._vote_refs(analyses))

    def _persist_risk_debate(self, db: Session, run: AgentCouncilRun, trade_plan: dict, score: float, disagreement: float, evidence_quality: float) -> dict:
        risk_reward = self._number(trade_plan.get("risk_reward"))
        invalidation = trade_plan.get("invalidation_level")
        stop_loss = trade_plan.get("stop_loss")
        self._add_turn(db, run, stage="risk_debate", agent_name="aggressive_risk", sequence=60, stance="accept" if abs(score) >= 0.2 and (risk_reward or 0) >= 1.2 else "wait", confidence=_bounded(abs(score) * 100), reliability=0.5, argument="Aggressive risk accepts only directional evidence with adequate reward-to-risk.")
        conservative_accepts = invalidation is not None and risk_reward is not None and risk_reward >= 1.5 and evidence_quality >= 50 and disagreement < 50
        self._add_turn(db, run, stage="risk_debate", agent_name="conservative_risk", sequence=61, stance="accept" if conservative_accepts else "avoid", confidence=_bounded(100 - disagreement), reliability=0.9, argument="Conservative risk requires clear invalidation, quality evidence and controlled disagreement.")
        self._add_turn(db, run, stage="risk_debate", agent_name="neutral_risk", sequence=62, stance="accept" if invalidation is not None and (risk_reward or 0) >= 1.2 else "wait", confidence=_bounded(evidence_quality), reliability=0.8, argument="Neutral risk enforces BLUM invalidation and reward-to-risk guardrails.")
        return {"risk_reward": risk_reward, "invalidation_level": invalidation, "stop_loss": stop_loss}

    def _memory(self, db: Session, record: BlumKnowledgeRecord, as_of: datetime) -> dict:
        rows = list(
            db.scalars(
                select(AgentCouncilReflection)
                .where(AgentCouncilReflection.ticker == record.ticker, AgentCouncilReflection.created_at <= as_of)
                .order_by(desc(AgentCouncilReflection.created_at))
                .limit(100)
            )
        )
        if len(rows) < self.min_memory_samples:
            return {"sample_size": len(rows), "adjustment": 0.0, "status": "insufficient_sample"}
        correctness = [1.0 if row.direction_correct else 0.0 for row in rows if row.direction_correct is not None]
        excess = [float(row.excess_return) for row in rows if row.excess_return is not None]
        hit_rate = sum(correctness) / len(correctness) if correctness else 0.5
        average_excess = sum(excess) / len(excess) if excess else 0.0
        adjustment = _bounded((hit_rate - 0.5) * 6.0 + max(-5.0, min(5.0, average_excess)) * 0.4, -5.0, 5.0)
        return {"sample_size": len(rows), "hit_rate": round(hit_rate, 4), "average_excess_return": round(average_excess, 4), "adjustment": adjustment, "status": "applied"}

    def _add_turn(self, db: Session, run: AgentCouncilRun, *, stage: str, agent_name: str, sequence: int, stance: str, confidence: float, reliability: float, argument: str, supporting: list | None = None, contradicting: list | None = None, refs: list | None = None) -> None:
        exists = db.scalar(select(AgentCouncilTurn.id).where(AgentCouncilTurn.run_id == run.id, AgentCouncilTurn.stage == stage, AgentCouncilTurn.agent_name == agent_name, AgentCouncilTurn.round_number == 1).limit(1))
        if exists is not None:
            return
        db.add(AgentCouncilTurn(run_id=run.id, stage=stage, agent_name=agent_name, round_number=1, turn_sequence=sequence, stance=stance, confidence=_bounded(confidence), reliability_weight=_bounded(reliability, 0.0, 1.0), argument=argument, supporting_evidence_json=supporting or [], contradicting_evidence_json=contradicting or [], evidence_refs_json=refs or []))
        db.flush()

    def _checkpoint(self, run: AgentCouncilRun, stage: str, cursor: int, payload: dict) -> None:
        run.current_stage = stage
        run.stage_cursor = cursor
        run.checkpoint_json = {"last_completed_stage": self.stages[max(0, cursor - 1)], "next_stage": stage, **payload}
        run.updated_at = datetime.utcnow()

    @staticmethod
    def _directional_score(items: list[dict]) -> float:
        denominator = sum(item["reliability"] * max(0.1, item["confidence"] / 100.0) for item in items)
        if denominator <= 0:
            return 0.0
        numerator = sum(item["direction"] * item["reliability"] * max(0.1, item["confidence"] / 100.0) for item in items)
        return max(-1.0, min(1.0, numerator / denominator))

    @staticmethod
    def _disagreement(items: list[dict]) -> float:
        denominator = sum(item["reliability"] for item in items)
        if denominator <= 0:
            return 100.0
        signed = sum(item["direction"] * item["reliability"] for item in items)
        return _bounded((1.0 - abs(signed) / denominator) * 100.0)

    @staticmethod
    def _evidence_quality(items: list[dict]) -> float:
        denominator = sum(item["reliability"] for item in items)
        return _bounded(sum(item["evidence_quality"] * item["reliability"] for item in items) / denominator) if denominator else 0.0

    @staticmethod
    def _base_confidence(items: list[dict], score: float, disagreement: float) -> float:
        if not items:
            return 0.0
        mean_confidence = sum(item["confidence"] * item["reliability"] for item in items) / sum(item["reliability"] for item in items)
        return _bounded(mean_confidence * abs(score) * (1.0 - disagreement / 100.0))

    @staticmethod
    def _side_confidence(items: list[dict]) -> float:
        return _bounded(sum(item["confidence"] for item in items) / len(items)) if items else 0.0

    @staticmethod
    def _vote_refs(items: list[dict]) -> list[dict]:
        return [{"type": "engine_vote", "id": item["vote_id"]} for item in items]

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _direction_correct(action: str, realized: float | None) -> bool | None:
        if realized is None:
            return None
        if action == "BUY":
            return realized > 0
        if action == "SELL":
            return realized < 0
        return realized <= 0

    @staticmethod
    def _reflection_lesson(action: str, correct: bool | None, excess: float | None) -> str:
        if correct is None:
            return "Outcome is incomplete; no directional lesson can be claimed."
        relative = "beat its benchmark" if excess is not None and excess > 0 else "did not beat its benchmark"
        return f"The {action} verdict was {'directionally correct' if correct else 'directionally wrong'} and {relative}."

    @staticmethod
    def _verdict_reason(action: str, score: float, warnings: list[str]) -> str:
        if action == "WAIT":
            return "Wait: the council could not satisfy every evidence and risk gate. " + (", ".join(warnings) or "Directional edge is unclear.")
        return f"{action}: reliability-weighted evidence produced a directional score of {score:.3f} with all mandatory risk gates present."

    @staticmethod
    def _serialize(run: AgentCouncilRun) -> dict:
        memory = _as_dict(run.final_decision_json).get("memory_used", {})
        return {
            "status": run.status,
            "run_id": run.id,
            "run_uid": run.run_uid,
            "record_id": run.knowledge_record_id,
            "ticker": run.ticker,
            "final_action": run.final_action,
            "final_confidence": run.final_confidence,
            "disagreement_score": run.disagreement_score,
            "evidence_quality": run.evidence_quality,
            "memory_adjustment": run.memory_adjustment,
            "memory_used": memory,
            "warnings": list(run.warnings_json or []),
            "decision": dict(run.final_decision_json or {}),
        }


class DecisionCouncilWorker:
    job_name = "evidence_decision_council"

    def __init__(self, council: EvidenceBoundDecisionCouncil | None = None) -> None:
        self.council = council or EvidenceBoundDecisionCouncil()

    def run(self, db: Session, *, max_items: int = 25, max_seconds: int = 120, now: datetime | None = None, manage_state: bool = True) -> dict:
        started = time.perf_counter()
        clock = now or datetime.utcnow()
        budget_items = max(1, max_items)
        budget_seconds = max(1, max_seconds)
        state = db.scalar(select(BackgroundJobState).where(BackgroundJobState.job_name == self.job_name).limit(1))
        cursor = int(_as_dict(state.cursor_json).get("knowledge_record_id") or 0) if state else 0
        if manage_state:
            BackgroundJobStateService().start(db, self.job_name, max_items=budget_items, cursor={"knowledge_record_id": cursor})
        processed = 0
        last_id = cursor
        errors: list[dict] = []
        try:
            rows = list(db.scalars(select(BlumKnowledgeRecord).where(BlumKnowledgeRecord.id > cursor, BlumKnowledgeRecord.created_at <= clock).order_by(BlumKnowledgeRecord.id).limit(budget_items)))
            for record in rows:
                if time.perf_counter() - started >= budget_seconds:
                    break
                try:
                    self.council.run_for_record(db, record.id, as_of=clock)
                    processed += 1
                    last_id = record.id
                except Exception as exc:
                    db.rollback()
                    errors.append({"record_id": record.id, "error": f"{type(exc).__name__}: {exc}"})
                    last_id = record.id
            reflections = self.council.reflect_mature_outcomes(db, limit=budget_items)
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            if manage_state:
                BackgroundJobStateService().complete(db, self.job_name, duration_ms=duration_ms, items_processed=processed, cursor={"knowledge_record_id": last_id}, next_run_after=clock + timedelta(minutes=10), payload={"processed": processed, "errors": len(errors), "reflections": reflections["created"]})
            else:
                BackgroundJobStateService().heartbeat(db, self.job_name, items_processed=processed, cursor={"knowledge_record_id": last_id})
            BrainEventBus().publish(db, "decision_council_completed", self.job_name, duration_ms=duration_ms, payload={"processed": processed, "errors": errors, "reflections": reflections})
            return {"status": "COMPLETED", "processed": processed, "errors": errors, "reflections": reflections, "cursor": {"knowledge_record_id": last_id}, "budgets": {"max_items": budget_items, "max_seconds": budget_seconds}, "duration_ms": duration_ms}
        except Exception as exc:
            db.rollback()
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            if manage_state:
                BackgroundJobStateService().fail(db, self.job_name, duration_ms=duration_ms, error_message=f"{type(exc).__name__}: {exc}")
            raise


class DecisionCouncilSnapshotService:
    snapshot_type = "decision_council_summary"

    def build(self, db: Session) -> dict:
        total = int(db.scalar(select(func.count(AgentCouncilRun.id))) or 0)
        completed = int(db.scalar(select(func.count(AgentCouncilRun.id)).where(AgentCouncilRun.status == "COMPLETED")) or 0)
        failed = int(db.scalar(select(func.count(AgentCouncilRun.id)).where(AgentCouncilRun.status == "FAILED")) or 0)
        actions = {str(action): int(count) for action, count in db.execute(select(AgentCouncilRun.final_action, func.count(AgentCouncilRun.id)).where(AgentCouncilRun.status == "COMPLETED").group_by(AgentCouncilRun.final_action)).all()}
        latest = db.scalar(select(AgentCouncilRun).order_by(desc(AgentCouncilRun.created_at)).limit(1))
        reflections = int(db.scalar(select(func.count(AgentCouncilReflection.id))) or 0)
        helpful = int(db.scalar(select(func.count(AgentCouncilReflection.id)).where(AgentCouncilReflection.actionability_was_helpful.is_(True))) or 0)
        mean_disagreement = db.scalar(select(func.avg(AgentCouncilRun.disagreement_score)).where(AgentCouncilRun.status == "COMPLETED"))
        return {
            "status": "ready",
            "runs": {"total": total, "completed": completed, "failed": failed, "actions": actions},
            "latest": EvidenceBoundDecisionCouncil._serialize(latest) if latest else None,
            "reflections": {"sample_size": reflections, "helpful_rate": round(helpful / reflections, 4) if reflections else None},
            "average_disagreement": round(float(mean_disagreement), 4) if mean_disagreement is not None else None,
            "evidence_warning": "Insufficient outcome reflections for a reliability conclusion." if reflections < 30 else None,
            "policy": "Deterministic evidence council; no market fetch or model inference during snapshot generation.",
        }

    def latest(self, db: Session) -> dict:
        payload = DashboardSnapshotService().latest(db, self.snapshot_type)
        result = dict(payload.get("payload") or {})
        result["snapshot_status"] = payload.get("status")
        result["snapshot_created_at"] = payload.get("created_at")
        return result

    def run_detail(self, db: Session, run_id: int) -> dict:
        run = db.get(AgentCouncilRun, run_id)
        if run is None:
            return {"status": "NOT_FOUND", "run_id": run_id}
        turns = list(
            db.scalars(
                select(AgentCouncilTurn)
                .where(AgentCouncilTurn.run_id == run_id)
                .order_by(AgentCouncilTurn.turn_sequence, AgentCouncilTurn.id)
                .limit(100)
            )
        )
        reflection_rows = list(
            db.scalars(
                select(AgentCouncilReflection)
                .where(AgentCouncilReflection.run_id == run_id)
                .order_by(AgentCouncilReflection.created_at)
                .limit(50)
            )
        )
        return {
            **EvidenceBoundDecisionCouncil._serialize(run),
            "source_snapshot": dict(run.source_snapshot_json or {}),
            "checkpoint": dict(run.checkpoint_json or {}),
            "turns": [
                {
                    "stage": row.stage,
                    "agent": row.agent_name,
                    "round": row.round_number,
                    "stance": row.stance,
                    "confidence": row.confidence,
                    "reliability_weight": row.reliability_weight,
                    "argument": row.argument,
                    "supporting_evidence": list(row.supporting_evidence_json or []),
                    "contradicting_evidence": list(row.contradicting_evidence_json or []),
                    "evidence_refs": list(row.evidence_refs_json or []),
                }
                for row in turns
            ],
            "reflections": [
                {
                    "horizon_days": row.horizon_days,
                    "realized_return": row.realized_return,
                    "benchmark_return": row.benchmark_return,
                    "excess_return": row.excess_return,
                    "direction_correct": row.direction_correct,
                    "actionability_was_helpful": row.actionability_was_helpful,
                    "lesson": row.lesson,
                }
                for row in reflection_rows
            ],
        }
