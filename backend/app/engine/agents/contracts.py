from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from sqlalchemy.orm import Session


AgentName = Literal[
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
]


@dataclass(frozen=True)
class AgentBoundary:
    name: AgentName
    display_name: str
    responsibility: str
    consumes: list[str] = field(default_factory=list)
    publishes: list[str] = field(default_factory=list)
    implemented: bool = False
    implementation_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentEvidence:
    agent: AgentName
    responsibility: str
    evidence_type: str
    status: str
    payload: dict[str, Any]
    confidence: float | None = None
    sample_size: int | None = None
    warnings: list[str] = field(default_factory=list)
    produced_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EngineAgent(Protocol):
    name: AgentName
    display_name: str
    responsibility: str
    evidence_type: str

    def collect(self, db: Session, *, limit: int = 8) -> AgentEvidence:
        """Collect structured evidence without owning UI or starting heavy jobs."""
