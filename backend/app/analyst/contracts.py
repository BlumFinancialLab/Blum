from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.engine.contracts import BLUM_ANALYST_REPOSITORY, ENGINE_VERSION, PROJECT_FEATURE_SET


@dataclass(frozen=True)
class AnalystDatasetContract:
    repository: str
    version: str
    feature_set: str
    source_layer: str
    purpose: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    supported_training_modes: list[str] = field(default_factory=list)
    automatic_training_enabled: bool = False
    automatic_dataset_snapshots_enabled: bool = True
    community_memory_policy: str = "opt_in_pull_request_quarantine"
    source_of_truth: bool = False
    policy: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyst_dataset_contract(repository: str = BLUM_ANALYST_REPOSITORY) -> AnalystDatasetContract:
    return AnalystDatasetContract(
        repository=repository,
        version=ENGINE_VERSION,
        feature_set=PROJECT_FEATURE_SET,
        source_layer="blum_engine",
        purpose="Learn BLUM reasoning patterns from curated Engine evidence without owning market data.",
        input_schema={
            "market_context": "point-in-time market, regime, benchmark and portfolio context",
            "asset_context": "ticker, fundamentals, technicals, sentiment, narrative and risk evidence",
            "decision_context": "Engine decision, actionability, thesis, contradiction and no-trade evidence",
            "outcome_context": "paper outcome, benchmark-relative result, mistake analysis and learning event",
        },
        output_schema={
            "executive_thesis": "balanced thesis",
            "bull_case": "supporting argument",
            "bear_case": "contradicting argument",
            "risk_assessment": "explicit risk and invalidation logic",
            "confidence_rationale": "calibrated confidence explanation",
            "final_view": "informational conclusion validated by Engine",
        },
        supported_training_modes=["sft_jsonl", "preference_pairs", "dpo_pairs", "reasoning_traces"],
        automatic_training_enabled=False,
        automatic_dataset_snapshots_enabled=True,
        community_memory_policy="opt_in_pull_request_quarantine",
        source_of_truth=False,
        policy="BLUM Analyst is a reasoning assistant. BLUM Engine validates all outputs before use.",
    )
