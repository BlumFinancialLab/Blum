from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from model_release.blum_finance.inference import BlumFinancePipeline
from model_release.blum_finance.contributions import build_contribution_bundle
from model_release.blum_finance.memory import (
    BlumFinanceMemoryStore,
    InvalidMemoryRecord,
)
from model_release.blum_finance.schemas import FinancialReasoningRequest


def request(*, as_of: str = "2026-08-03T12:00:00Z") -> dict:
    return {
        "ticker": "EURUSD",
        "as_of": as_of,
        "horizon": "intraday",
        "market_context": {"regime": "risk_off"},
        "evidence": [
            {"type": "technical", "value": "price above MA20"},
            {"type": "regime", "value": "USD strength is elevated"},
        ],
    }


def memory_record(*, observed_at: str = "2026-08-02T15:00:00Z") -> dict:
    return {
        "model_revision": "a" * 40,
        "request": request(as_of="2026-08-02T10:00:00Z"),
        "response": {
            "status": "wait_for_trigger",
            "thesis": "Wait for price and regime confirmation.",
            "bull_case": ["price above MA20"],
            "bear_case": ["USD strength is elevated"],
            "risks": ["regime divergence"],
            "invalidation_conditions": ["price closes below MA20"],
            "confidence": 58,
            "what_would_change_the_view": ["regime confirmation"],
        },
        "outcome": {
            "observed_at": observed_at,
            "status": "closed",
            "realized_r": -0.4,
            "benchmark_excess": -0.2,
            "lesson": "Regime divergence outweighed the isolated technical signal.",
        },
        "quality": {"score": 88, "source_verified": True},
    }


def test_memory_store_retrieves_only_mature_point_in_time_records(tmp_path) -> None:
    store = BlumFinanceMemoryStore(tmp_path / "memory.jsonl")
    stored = store.add(memory_record())

    matches = store.retrieve(FinancialReasoningRequest.model_validate(request()), limit=3)

    assert stored.content_hash
    assert len(matches) == 1
    assert matches[0]["ticker"] == "EURUSD"
    assert matches[0]["outcome"]["realized_r"] == -0.4
    assert matches[0]["lesson"].startswith("Regime divergence")


def test_memory_store_rejects_outcome_that_predates_decision(tmp_path) -> None:
    store = BlumFinanceMemoryStore(tmp_path / "memory.jsonl")

    with pytest.raises(InvalidMemoryRecord, match="after the decision"):
        store.add(memory_record(observed_at="2026-08-02T09:00:00Z"))


def test_memory_store_does_not_leak_future_observations(tmp_path) -> None:
    store = BlumFinanceMemoryStore(tmp_path / "memory.jsonl")
    store.add(memory_record(observed_at="2026-08-02T15:00:00Z"))

    matches = store.retrieve(
        FinancialReasoningRequest.model_validate(
            request(as_of="2026-08-02T12:00:00Z")
        )
    )

    assert matches == []


def test_pipeline_injects_validated_memory_as_analogy_not_current_fact(tmp_path) -> None:
    store = BlumFinanceMemoryStore(tmp_path / "memory.jsonl")
    store.add(memory_record())
    captured: list[list[dict[str, str]]] = []

    def generator(messages: list[dict[str, str]]) -> str:
        captured.append(messages)
        return json.dumps(
            {
                "status": "wait_for_trigger",
                "thesis": "Current evidence remains incomplete.",
                "bull_case": ["price above MA20"],
                "bear_case": ["USD strength is elevated"],
                "risks": [],
                "invalidation_conditions": [],
                "confidence": 51,
                "what_would_change_the_view": ["price and regime confirmation"],
            }
        )

    pipeline = BlumFinancePipeline(generator=generator, memory_store=store)
    result = pipeline.generate(request())

    assert result.confidence == 51
    assert len(captured) == 1
    memory_messages = [
        item for item in captured[0] if "validated historical memory" in item["content"].lower()
    ]
    assert len(memory_messages) == 1
    assert "not current market facts" in memory_messages[0]["content"].lower()
    assert "Regime divergence outweighed" in memory_messages[0]["content"]


def test_store_imports_only_a_validated_contribution_bundle(tmp_path) -> None:
    bundle = build_contribution_bundle(
        memory_record(),
        output=tmp_path / "bundle.json",
        consent=True,
    )
    store = BlumFinanceMemoryStore(tmp_path / "memory.jsonl")

    stored = store.add_bundle(bundle.path)

    assert stored.content_hash
    assert len(store.retrieve(FinancialReasoningRequest.model_validate(request()))) == 1
