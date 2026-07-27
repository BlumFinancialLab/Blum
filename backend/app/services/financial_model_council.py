from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.sentiment import FinancialSentimentModel
from app.models import FinancialModelAdvisor, FinancialModelVote


ADVISOR_SPECS = (
    {
        "advisor_key": "finbert",
        "display_name": "FinBERT",
        "provider_type": "transformers_model",
        "model_id": "ProsusAI/finbert",
        "source_url": "https://huggingface.co/ProsusAI/finbert",
        "role": "financial_sentiment",
        "execution_mode": "local_cpu",
        "runtime_status": "CONFIGURED_LOCAL",
        "license": "review_required",
        "resource_profile": {"cpu_compatible": True, "critical_path": False},
        "capabilities": ["sentiment", "text_classification"],
    },
    {
        "advisor_key": "fingpt",
        "display_name": "FinGPT",
        "provider_type": "framework_and_adapter",
        "model_id": "FinGPT/fingpt-sentiment_llama2-13b_lora",
        "source_url": "https://github.com/AI4Finance-Foundation/FinGPT",
        "role": "financial_language_adapter",
        "execution_mode": "remote_optional",
        "runtime_status": "ADAPTER_READY_REMOTE_DISABLED",
        "license": "mit",
        "resource_profile": {"gpu_recommended": True, "critical_path": False},
        "capabilities": ["sentiment", "instruction_tuning", "financial_qa"],
    },
    {
        "advisor_key": "finrobot",
        "display_name": "FinRobot",
        "provider_type": "agent_framework",
        "model_id": None,
        "source_url": "https://github.com/AI4Finance-Foundation/FinRobot",
        "role": "multi_agent_review",
        "execution_mode": "local_orchestration",
        "runtime_status": "INTEGRATED",
        "license": "apache-2.0",
        "resource_profile": {"cpu_compatible": True, "critical_path": False},
        "capabilities": ["agent_coordination", "risk_review", "evidence_synthesis"],
    },
    {
        "advisor_key": "finllama",
        "display_name": "FinLlama",
        "provider_type": "generative_model",
        "model_id": "bavest/fin-llama-33b-merged",
        "source_url": "https://huggingface.co/bavest/fin-llama-33b-merged",
        "role": "financial_reasoning",
        "execution_mode": "remote_optional",
        "runtime_status": "ADAPTER_READY_GPU_REQUIRED",
        "license": "gpl",
        "resource_profile": {"parameters": "33B", "gpu_required": True, "critical_path": False},
        "capabilities": ["financial_qa", "report_analysis", "reasoning"],
    },
    {
        "advisor_key": "investlm",
        "display_name": "InvestLM",
        "provider_type": "research_model",
        "model_id": None,
        "source_url": "https://github.com/AbaciNLP/InvestLM",
        "role": "investment_reasoning",
        "execution_mode": "remote_optional",
        "runtime_status": "LICENSE_AND_ENDPOINT_REQUIRED",
        "license": "review_required",
        "resource_profile": {"gpu_required": True, "critical_path": False},
        "capabilities": ["investment_qa", "report_analysis", "portfolio_reasoning"],
    },
)


class FinancialModelCouncil:
    """Resource-aware model adapters; advisors never receive trading authority."""

    def ensure_registered(self, db: Session) -> dict:
        expected = {spec["advisor_key"] for spec in ADVISOR_SPECS}
        existing = set(db.scalars(select(FinancialModelAdvisor.advisor_key)).all())
        if expected.issubset(existing):
            return {"status": "READY", "registered": len(expected), "changed": False}
        result = self.register(db)
        return {**result, "changed": True}

    def status(self, db: Session) -> dict:
        advisors = db.scalars(
            select(FinancialModelAdvisor).order_by(FinancialModelAdvisor.advisor_key)
        ).all()
        vote_counts = dict(
            db.execute(
                select(FinancialModelVote.advisor_key, func.count(FinancialModelVote.id))
                .group_by(FinancialModelVote.advisor_key)
            ).all()
        )
        return {
            "direct_trading_authority": False,
            "advisors": {
                row.advisor_key: {
                    "display_name": row.display_name,
                    "role": row.role,
                    "model_id": row.model_id,
                    "execution_mode": row.execution_mode,
                    "runtime_status": row.runtime_status,
                    "license": row.license,
                    "resource_profile": row.resource_profile,
                    "capabilities": row.capabilities,
                    "votes_recorded": int(vote_counts.get(row.advisor_key, 0)),
                }
                for row in advisors
            },
        }

    def register(self, db: Session) -> dict:
        for spec in ADVISOR_SPECS:
            row = db.scalar(select(FinancialModelAdvisor).where(FinancialModelAdvisor.advisor_key == spec["advisor_key"]))
            values = {**spec, "direct_trading_authority": False, "enabled": True}
            if row is None:
                db.add(FinancialModelAdvisor(**values))
            else:
                for field, value in values.items():
                    setattr(row, field, value)
        db.commit()
        return {"status": "READY", "registered": len(ADVISOR_SPECS)}

    def analyze_sentiment(self, db: Session, *, object_type: str, object_id: str, ticker: str | None, text: str) -> dict:
        started = time.perf_counter()
        result = FinancialSentimentModel().analyze(text)
        label = str(result.get("label") or "neutral")
        vote = {"positive": "support", "negative": "oppose"}.get(label, "abstain")
        return self._store_vote(
            db,
            advisor_key="finbert",
            object_type=object_type,
            object_id=object_id,
            ticker=ticker,
            task="financial_sentiment",
            vote=vote,
            confidence=float(result.get("confidence") or 0.0),
            evidence={"text": text[:1800], "result": result},
            output=result,
            latency_ms=(time.perf_counter() - started) * 1000,
            runtime_status=str(result.get("model_name") or "fallback"),
        )

    def review_forex_decision(self, db: Session, *, decision_id: int, ticker: str, evidence: dict) -> dict:
        blockers = list(evidence.get("blockers") or [])
        aligned = evidence.get("context_direction") == evidence.get("price_direction")
        supported = bool(evidence.get("approved") and aligned and float(evidence.get("expected_net_pips") or 0.0) > 0 and not blockers)
        vote = "support" if supported else "oppose" if blockers else "abstain"
        confidence = max(0.0, min(1.0, float(evidence.get("confidence") or 0.0)))
        output = {
            "vote": vote,
            "reason": (
                "Independent agents align and expected movement remains positive after modeled costs."
                if supported
                else f"Decision remains blocked by: {', '.join(blockers)}."
                if blockers
                else "Agent evidence is not aligned."
            ),
            "direct_action_allowed": False,
        }
        return self._store_vote(
            db,
            advisor_key="finrobot",
            object_type="forex_decision",
            object_id=str(decision_id),
            ticker=ticker,
            task="multi_agent_risk_review",
            vote=vote,
            confidence=confidence,
            evidence=evidence,
            output=output,
            latency_ms=0.0,
            runtime_status="local_orchestration",
        )

    def evaluate_outcome(self, db: Session, *, decision_id: int, reward_r: float) -> dict:
        rows = db.scalars(
            select(FinancialModelVote).where(
                FinancialModelVote.object_type == "forex_decision",
                FinancialModelVote.object_id == str(decision_id),
                FinancialModelVote.outcome_evaluated.is_(False),
            )
        ).all()
        for row in rows:
            row.outcome_evaluated = True
            row.reward_contribution = float(reward_r)
            row.was_helpful = (
                (row.vote == "support" and reward_r > 0)
                or (row.vote == "oppose" and reward_r < 0)
                or (row.vote == "abstain" and reward_r == 0)
            )
            row.evaluated_at = datetime.utcnow()
        db.flush()
        return {"votes_evaluated": len(rows)}

    def _store_vote(
        self,
        db: Session,
        *,
        advisor_key: str,
        object_type: str,
        object_id: str,
        ticker: str | None,
        task: str,
        vote: str,
        confidence: float,
        evidence: dict,
        output: dict,
        latency_ms: float,
        runtime_status: str,
    ) -> dict:
        evidence_hash = sha256(json.dumps(evidence, sort_keys=True, default=str).encode()).hexdigest()
        existing = db.scalar(
            select(FinancialModelVote).where(
                FinancialModelVote.advisor_key == advisor_key,
                FinancialModelVote.object_type == object_type,
                FinancialModelVote.object_id == object_id,
                FinancialModelVote.task == task,
                FinancialModelVote.evidence_hash == evidence_hash,
            )
        )
        if existing is not None:
            return {"status": "ALREADY_RECORDED", "vote_id": existing.id, "vote": existing.vote}
        row = FinancialModelVote(
            advisor_key=advisor_key,
            object_type=object_type,
            object_id=object_id,
            ticker=ticker,
            task=task,
            vote=vote,
            confidence=confidence,
            evidence_quality=min(1.0, confidence),
            evidence_hash=evidence_hash,
            output_json=output,
            latency_ms=latency_ms,
            runtime_status=runtime_status,
            direct_action_allowed=False,
        )
        db.add(row)
        db.flush()
        return {"status": "RECORDED", "vote_id": row.id, "vote": vote, "direct_action_allowed": False}
