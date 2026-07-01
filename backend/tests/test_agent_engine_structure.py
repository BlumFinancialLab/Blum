from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.engine.agents.registry import agent_boundaries, agent_registry, collect_agent_evidence
from app.engine.facade import BlumEngineFacade
from app.main import app


REQUESTED_AGENTS = {
    "market_agent",
    "news_agent",
    "technical_agent",
    "fundamental_agent",
    "pattern_agent",
    "decision_agent",
    "risk_agent",
    "portfolio_agent",
    "paper_trading_agent",
    "learning_agent",
    "research_agent",
    "memory_agent",
    "alpha_agent",
    "validation_agent",
    "dataset_agent",
}


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def first_endpoint_module(path: str) -> str:
    for route in app.routes:
        if getattr(route, "path", None) == path:
            return route.endpoint.__module__
    raise AssertionError(f"Route not found: {path}")


def test_agent_boundaries_match_requested_clean_agent_set():
    boundaries = agent_boundaries()
    names = {boundary["name"] for boundary in boundaries}

    assert names == REQUESTED_AGENTS
    assert all(boundary["responsibility"] for boundary in boundaries)
    assert all(boundary["publishes"] for boundary in boundaries)
    assert all(boundary["implemented"] is True for boundary in boundaries)


def test_agent_registry_produces_structured_evidence_without_ui_ownership():
    with setup_db() as db:
        payload = collect_agent_evidence(db, limit=3)

    assert payload["status"] == "ready"
    assert payload["agent_count"] == 15
    assert payload["implemented_agent_count"] == 15
    assert len(payload["evidence"]) == 15
    assert "UI" in payload["policy"] or "ui" in payload["policy"].lower()
    for item in payload["evidence"]:
        assert item["agent"] in REQUESTED_AGENTS
        assert item["responsibility"]
        assert item["evidence_type"]
        assert isinstance(item["payload"], dict)
        assert "render" not in item["responsibility"].lower()


def test_engine_contract_exposes_agent_boundaries_and_facade_collects_subset():
    contract = BlumEngineFacade().contract()

    assert {agent["name"] for agent in contract["agents"]} == REQUESTED_AGENTS
    with setup_db() as db:
        payload = BlumEngineFacade().agent_evidence(db, agents=["learning_agent", "dataset_agent"], limit=2)

    assert [item["agent"] for item in payload["evidence"]] == ["learning_agent", "dataset_agent"]
    assert payload["warnings"] == []


def test_agent_endpoint_is_bounded_runtime_endpoint_not_legacy_router():
    assert first_endpoint_module("/api/engine/agents") == "app.api.routers.runtime"


def test_agent_modules_do_not_import_frontend_or_next_runtime():
    root = Path(__file__).resolve().parents[1] / "app" / "engine" / "agents"
    for path in root.glob("*.py"):
        text = path.read_text().lower()
        assert "frontend" not in text
        assert "react" not in text
        assert "next/" not in text
        assert "tsx" not in text


def test_registered_agents_are_not_empty_middlemen():
    for agent in agent_registry().values():
        cls = agent.__class__
        assert "collect" in cls.__dict__, f"{cls.__name__} must own its evidence collection."
        assert len(cls.__dict__["collect"].__code__.co_names) > 3
