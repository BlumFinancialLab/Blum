from __future__ import annotations

from sqlalchemy.orm import Session

from app.engine.contracts import (
    ENGINE_VERSION,
    PROJECT_FEATURE_SET,
    EngineStatusContract,
    engine_module_catalog,
    event_contract,
)
from app.services.trader_brain import TraderBrainService


class BlumEngineFacade:
    """Headless intelligence boundary for BLUM.

    This facade is the first stable seam between the financial operating system
    and the application runtime. It delegates to legacy services while enforcing
    a contract that has no presentation responsibility.
    """

    def status(self, db: Session) -> dict:
        trader = TraderBrainService()
        brain = trader.brain(db)
        training = trader.training_ground(db)
        paper = trader.paper_trading(db, limit=12)
        alpha = trader.alpha(db)
        contract = EngineStatusContract(
            version=ENGINE_VERSION,
            feature_set=PROJECT_FEATURE_SET,
            source_of_truth=True,
            headless_capable=True,
            intelligence_modules=engine_module_catalog(),
            event_contract=event_contract(),
            current_brain_status=self._brain_status(brain),
            current_learning_status=self._learning_status(training),
            current_alpha_status=self._alpha_status(alpha),
            current_paper_trading_status=self._paper_status(paper),
            policy=(
                "BLUM Engine owns intelligence, decisions, learning, evidence and knowledge. "
                "It can run without any product surface and never depends on presentation code."
            ),
        )
        return contract.to_dict()

    def contract(self) -> dict:
        return {
            "version": ENGINE_VERSION,
            "feature_set": PROJECT_FEATURE_SET,
            "source_of_truth": True,
            "headless_capable": True,
            "modules": [module.to_dict() for module in engine_module_catalog()],
            "events": event_contract(),
            "decision_object": {
                "ticker": "string",
                "decision_type": "paper_trade | thesis | no_trade | portfolio_action",
                "actionability": "avoid | watch | wait_for_trigger | active_setup | manage | reduce | exit",
                "thesis_id": "optional string",
                "confidence": "optional 0-100",
                "decision_quality": "optional 0-100",
                "expected_alpha": "optional benchmark-relative estimate",
                "entry_zone": "optional structured zone",
                "invalidation": "required for trade-like decisions",
                "targets": "optional structured target zones",
                "bull_thesis": "evidence-backed bull case",
                "bear_thesis": "evidence-backed contradiction case",
                "risks": "list of explicit risks",
                "evidence_refs": "stable references to stored Engine evidence",
            },
            "policy": "The Engine emits evidence-bound objects only; it does not execute real trades and does not own product delivery.",
        }

    @staticmethod
    def _brain_status(payload: dict) -> dict:
        return {
            "status": payload.get("status"),
            "brain_score": payload.get("brain_score"),
            "decision_quality": payload.get("decision_quality"),
            "alpha_readiness": payload.get("alpha_readiness"),
            "evidence_quality": payload.get("evidence_quality"),
            "latest_lesson": payload.get("latest_lesson"),
            "current_weakness": payload.get("current_weakness"),
            "current_strength": payload.get("current_strength"),
        }

    @staticmethod
    def _learning_status(payload: dict) -> dict:
        validation = payload.get("current_validation") or {}
        return {
            "status": payload.get("status"),
            "current_experiment": payload.get("current_experiment"),
            "current_hypothesis": payload.get("current_hypothesis"),
            "outcomes_evaluated": validation.get("outcomes_evaluated"),
            "mistakes_analyzed": validation.get("mistakes_analyzed"),
            "memory_updates": validation.get("memory_updates"),
        }

    @staticmethod
    def _paper_status(payload: dict) -> dict:
        return {
            "status": payload.get("status"),
            "mode": payload.get("mode"),
            "no_broker_execution": payload.get("no_broker_execution"),
            "decision_count": len(payload.get("decisions") or []),
            "completed_decision_count": len(payload.get("completed_decisions") or []),
        }

    @staticmethod
    def _alpha_status(payload: dict) -> dict:
        return {
            "status": payload.get("status"),
            "alpha": payload.get("alpha"),
            "sample_size": payload.get("sample_size"),
            "evidence_grade": payload.get("evidence_grade"),
            "truth": payload.get("truth"),
        }
