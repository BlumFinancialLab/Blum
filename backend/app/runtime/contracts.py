from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.engine.contracts import ENGINE_VERSION, PROJECT_FEATURE_SET


@dataclass(frozen=True)
class RuntimeSurfaceContract:
    route: str
    name: str
    purpose: str
    source_contract: str
    primary: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RuntimeStatusContract:
    version: str
    feature_set: str
    owns_intelligence: bool
    responsibilities: list[str]
    primary_surfaces: list[RuntimeSurfaceContract] = field(default_factory=list)
    developer_surfaces: list[str] = field(default_factory=list)
    runtime_state: dict[str, Any] = field(default_factory=dict)
    policy: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["primary_surfaces"] = [surface.to_dict() for surface in self.primary_surfaces]
        return payload


def runtime_surfaces() -> list[RuntimeSurfaceContract]:
    return [
        RuntimeSurfaceContract("/", "Brain", "Show whether BLUM is becoming a better trader.", "engine.brain_status"),
        RuntimeSurfaceContract("/training-ground", "Training Ground", "Show autonomous research, validation and learning evidence.", "engine.learning_status"),
        RuntimeSurfaceContract("/paper-trading", "Paper Trading", "Show paper-only decisions, outcomes and lessons.", "engine.paper_trading_status"),
        RuntimeSurfaceContract("/alpha", "Alpha", "Show benchmark-relative evidence and truth-first alpha readiness.", "engine.alpha_status"),
    ]


def runtime_contract_defaults() -> dict:
    return {
        "version": ENGINE_VERSION,
        "feature_set": PROJECT_FEATURE_SET,
        "owns_intelligence": False,
        "responsibilities": [
            "api_delivery",
            "frontend",
            "scheduling",
            "snapshot_reading",
            "snapshot_production",
            "observability",
            "performance_monitoring",
            "developer_diagnostics",
        ],
        "developer_surfaces": [
            "/performance",
            "/brain/runtime-state",
            "/snapshots/health",
            "/learning/health",
        ],
    }
