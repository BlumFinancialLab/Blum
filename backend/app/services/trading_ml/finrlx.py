"""Optional, paper-only FinRL-X policy challenger boundary.

The application never imports FinRL-X or a deep-learning runtime. A configured
external runner receives immutable JSON and may return only normalized policy
advice. BLUM remains authoritative for blockers, risk, sizing, and execution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
from typing import Any, Mapping

from app.core.config import get_settings
from app.services.trading_ml.contracts import FeatureSchema


FINRLX_UPSTREAM_REPOSITORY = "AI4Finance-Foundation/FinRL-Trading"
FINRLX_UPSTREAM_REVISION = "e65d6f0483ead7d2ef4a5fc940cdf960392a25c1"
SUPPORTED_ALGORITHMS = frozenset({"PPO", "SAC", "TD3", "DDPG", "A2C", "DETERMINISTIC"})
FORBIDDEN_OUTPUT_FIELDS = frozenset(
    {
        "borrow",
        "broker_order",
        "commission",
        "entry",
        "leverage",
        "lots",
        "margin",
        "notional",
        "order",
        "position_size",
        "quantity",
        "slippage",
        "stop",
        "stop_loss",
        "target",
        "target_1",
        "target_2",
    }
)


class InvalidFinRLXArtifact(ValueError):
    """Raised before an untrusted or incompatible artifact can be used."""


@dataclass(frozen=True)
class FinRLXArtifactManifest:
    provider: str
    upstream_repository: str
    upstream_revision: str
    algorithm: str
    market_family: str
    feature_schema_hash: str
    action_schema: str
    artifact_path: str
    artifact_sha256: str
    sample_count: int
    paper_only: bool

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuantPolicyProposal:
    status: str
    action: str
    directional_score: float
    confidence: float | None = None
    uncertainty: float | None = None
    target_weights: tuple[tuple[str, float], ...] = ()
    reason: str = ""
    model: str | None = None
    guardrails: tuple[str, ...] = ()
    paper_only: bool = True

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["target_weights"] = dict(self.target_weights)
        return payload


class FinRLXArtifactValidator:
    def __init__(
        self,
        *,
        root: str | Path,
        expected_feature_schema_hash: str,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.expected_feature_schema_hash = expected_feature_schema_hash

    def validate(
        self,
        manifest_path: str | Path,
        *,
        market_family: str,
    ) -> FinRLXArtifactManifest:
        path = Path(manifest_path).expanduser().resolve()
        if not path.is_relative_to(self.root):
            raise InvalidFinRLXArtifact("manifest path is outside the trusted artifact root")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidFinRLXArtifact(f"manifest is unreadable: {type(exc).__name__}") from exc
        if not isinstance(raw, dict):
            raise InvalidFinRLXArtifact("manifest must be a JSON object")
        try:
            paper_only = raw["paper_only"]
            if not isinstance(paper_only, bool):
                raise TypeError("paper_only must be boolean")
            manifest = FinRLXArtifactManifest(
                provider=str(raw["provider"]),
                upstream_repository=str(raw["upstream_repository"]),
                upstream_revision=str(raw["upstream_revision"]),
                algorithm=str(raw["algorithm"]).upper(),
                market_family=str(raw["market_family"]).lower(),
                feature_schema_hash=str(raw["feature_schema_hash"]),
                action_schema=str(raw["action_schema"]),
                artifact_path=str(raw["artifact_path"]),
                artifact_sha256=str(raw["artifact_sha256"]).lower(),
                sample_count=int(raw["sample_count"]),
                paper_only=paper_only,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidFinRLXArtifact(f"manifest contract is invalid: {exc}") from exc

        if manifest.provider.lower() != "finrlx":
            raise InvalidFinRLXArtifact("provider is not finrlx")
        if manifest.upstream_repository != FINRLX_UPSTREAM_REPOSITORY:
            raise InvalidFinRLXArtifact("upstream repository is not trusted")
        if manifest.upstream_revision != FINRLX_UPSTREAM_REVISION:
            raise InvalidFinRLXArtifact("upstream revision is not pinned")
        if manifest.algorithm not in SUPPORTED_ALGORITHMS:
            raise InvalidFinRLXArtifact(f"algorithm {manifest.algorithm} is unsupported")
        if manifest.market_family != market_family.lower():
            raise InvalidFinRLXArtifact("market family does not match the requested market")
        if manifest.feature_schema_hash != self.expected_feature_schema_hash:
            raise InvalidFinRLXArtifact("feature schema hash mismatch")
        expected_action_schema = (
            "directional_score_v1" if market_family.lower() == "forex" else "target_weights_v1"
        )
        if manifest.action_schema != expected_action_schema:
            raise InvalidFinRLXArtifact("action schema is incompatible")
        if not manifest.paper_only:
            raise InvalidFinRLXArtifact("paper-only policy is required")
        if manifest.sample_count < 1:
            raise InvalidFinRLXArtifact("sample count must be positive")

        artifact = (path.parent / manifest.artifact_path).resolve()
        if not artifact.is_relative_to(self.root):
            raise InvalidFinRLXArtifact("artifact path is outside the trusted artifact root")
        try:
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        except OSError as exc:
            raise InvalidFinRLXArtifact("artifact is unreadable") from exc
        if digest != manifest.artifact_sha256:
            raise InvalidFinRLXArtifact("artifact hash mismatch")
        return manifest


class FinRLXQuantEngine:
    """Bounded external policy runner with deterministic BLUM authority."""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        runner_command: str | None = None,
        artifact_root: str | Path | None = None,
        manifest_path: str | Path | None = None,
        feature_schema_hash: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        settings = get_settings()
        self.enabled = settings.finrlx_enabled if enabled is None else bool(enabled)
        self.runner_command = (
            settings.finrlx_runner_command if runner_command is None else runner_command
        ).strip()
        self.artifact_root = Path(
            artifact_root or settings.finrlx_artifact_root
        ).expanduser().resolve()
        configured_manifest = (
            settings.finrlx_manifest_path if manifest_path is None else str(manifest_path)
        )
        self.manifest_path = (
            Path(configured_manifest).expanduser().resolve()
            if configured_manifest
            else None
        )
        self.feature_schema_hash = (
            feature_schema_hash
            or settings.finrlx_feature_schema_hash
            or FeatureSchema.current().hash
        )
        self.timeout_seconds = max(
            1,
            int(timeout_seconds or settings.finrlx_timeout_seconds),
        )
        self.validator = FinRLXArtifactValidator(
            root=self.artifact_root,
            expected_feature_schema_hash=self.feature_schema_hash,
        )

    def status(self) -> dict[str, Any]:
        if not self.enabled:
            return {
                "status": "DISABLED",
                "reason": "FinRL-X challenger is opt-in.",
                "paper_only": True,
            }
        command = self._command()
        if not command:
            return {
                "status": "UNAVAILABLE",
                "reason": "Configured FinRL-X runner is not executable.",
                "paper_only": True,
            }
        if self.manifest_path is None:
            return {
                "status": "NO_VALIDATED_ARTIFACT",
                "runner": command[0],
                "paper_only": True,
            }
        try:
            manifest = self.validator.validate(
                self.manifest_path,
                market_family=self._manifest_market_family(),
            )
        except InvalidFinRLXArtifact as exc:
            return {
                "status": "REJECTED",
                "reason": str(exc),
                "paper_only": True,
            }
        return {
            "status": "READY_SHADOW",
            "runner": command[0],
            "manifest": manifest.to_payload(),
            "paper_only": True,
        }

    def propose(
        self,
        *,
        market_family: str,
        features: Mapping[str, object],
        context: Mapping[str, object] | None = None,
        deterministic_blockers: tuple[str, ...] | list[str] = (),
    ) -> QuantPolicyProposal:
        if deterministic_blockers:
            return self._hold(
                "BLOCKED",
                "Deterministic BLUM blocker preserved before external inference.",
                ("EXISTING_BLOCKER_PRESERVED", "DETERMINISTIC_AUTHORITY"),
            )
        if not self.enabled:
            return self._hold("DISABLED", "FinRL-X challenger is disabled.")
        command = self._command()
        if not command:
            return self._hold("UNAVAILABLE", "FinRL-X runner is unavailable.")
        if self.manifest_path is None:
            return self._hold(
                "NO_VALIDATED_ARTIFACT",
                "No validated FinRL-X artifact is configured.",
            )
        try:
            manifest = self.validator.validate(
                self.manifest_path,
                market_family=market_family,
            )
            raw = self._invoke(
                {
                    "operation": "propose",
                    "market_family": market_family,
                    "features": dict(features),
                    "context": dict(context or {}),
                    "manifest": manifest.to_payload(),
                },
                timeout_seconds=min(5, self.timeout_seconds),
            )
            return self._normalize_proposal(raw, manifest)
        except InvalidFinRLXArtifact as exc:
            return self._hold("REJECTED", str(exc), ("ARTIFACT_REJECTED",))
        except subprocess.TimeoutExpired:
            return self._hold("TIMEOUT", "FinRL-X inference exceeded its time budget.")
        except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
            return self._hold(
                "FAILED",
                f"FinRL-X inference failed: {type(exc).__name__}.",
            )

    def run_training(
        self,
        *,
        market_family: str,
        request: Mapping[str, object],
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"status": "DISABLED", "paper_only": True}
        if not self._command():
            return {"status": "UNAVAILABLE", "paper_only": True}
        try:
            result = self._invoke(
                {
                    "operation": "train",
                    "market_family": market_family,
                    "request": dict(request),
                    "constraints": {
                        "paper_only": True,
                        "upstream_revision": FINRLX_UPSTREAM_REVISION,
                        "feature_schema_hash": self.feature_schema_hash,
                    },
                },
                timeout_seconds=self.timeout_seconds,
            )
            manifest_path = result.get("manifest_path")
            if not manifest_path:
                raise InvalidFinRLXArtifact("runner did not publish a manifest path")
            manifest = self.validator.validate(
                str(manifest_path),
                market_family=market_family,
            )
            self.manifest_path = Path(str(manifest_path)).expanduser().resolve()
            return {
                "status": "VALIDATED_SHADOW",
                "manifest": manifest.to_payload(),
                "paper_only": True,
            }
        except InvalidFinRLXArtifact as exc:
            return {"status": "REJECTED", "reason": str(exc), "paper_only": True}
        except subprocess.TimeoutExpired:
            return {
                "status": "TIMEOUT",
                "reason": "FinRL-X training exceeded its bounded time budget.",
                "paper_only": True,
            }
        except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
            return {
                "status": "FAILED",
                "reason": f"{type(exc).__name__}: {exc}",
                "paper_only": True,
            }

    def _command(self) -> list[str]:
        if not self.runner_command:
            return []
        try:
            command = shlex.split(self.runner_command)
        except ValueError:
            return []
        if not command:
            return []
        executable = Path(command[0]).expanduser()
        if not executable.is_absolute() or not executable.is_file():
            return []
        if not executable.stat().st_mode & 0o111:
            return []
        command[0] = str(executable.resolve())
        return command

    def _invoke(
        self,
        request: Mapping[str, object],
        *,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        command = self._command()
        if not command:
            raise OSError("runner is unavailable")
        completed = subprocess.run(
            command,
            input=json.dumps(request, sort_keys=True),
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout_seconds,
            shell=False,
        )
        result = json.loads(completed.stdout)
        if not isinstance(result, dict):
            raise ValueError("runner output must be a JSON object")
        return result

    def _normalize_proposal(
        self,
        raw: Mapping[str, object],
        manifest: FinRLXArtifactManifest,
    ) -> QuantPolicyProposal:
        if self._contains_forbidden_field(raw):
            return self._hold(
                "REJECTED",
                "External policy attempted to control execution or risk.",
                ("FORBIDDEN_EXECUTION_FIELD", "DETERMINISTIC_AUTHORITY"),
            )
        score = _bounded_float(raw.get("directional_score"), minimum=-1.0, maximum=1.0)
        confidence = _optional_bounded_float(raw.get("confidence"))
        uncertainty = _optional_bounded_float(raw.get("uncertainty"))
        weights: tuple[tuple[str, float], ...] = ()
        if manifest.market_family == "equity":
            weights = _normalize_weights(raw.get("target_weights"))
            action = "TARGET_WEIGHTS" if weights else "HOLD"
        else:
            action = "LONG" if score > 0.05 else "SHORT" if score < -0.05 else "HOLD"
        return QuantPolicyProposal(
            status="SHADOW",
            action=action,
            directional_score=round(score, 6),
            confidence=confidence,
            uncertainty=uncertainty,
            target_weights=weights,
            reason=str(raw.get("reason") or "External quantitative shadow proposal."),
            model=f"finrlx:{manifest.algorithm}:{manifest.artifact_sha256[:12]}",
            guardrails=("PAPER_ONLY", "SHADOW_ONLY", "DETERMINISTIC_AUTHORITY"),
            paper_only=True,
        )

    @classmethod
    def _contains_forbidden_field(cls, value: object) -> bool:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if str(key).lower() in FORBIDDEN_OUTPUT_FIELDS:
                    return True
                if cls._contains_forbidden_field(item):
                    return True
        elif isinstance(value, (list, tuple)):
            return any(cls._contains_forbidden_field(item) for item in value)
        return False

    def _manifest_market_family(self) -> str:
        if self.manifest_path is None:
            return "forex"
        try:
            raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return str(raw.get("market_family") or "forex")
        except (OSError, json.JSONDecodeError):
            return "forex"

    @staticmethod
    def _hold(
        status: str,
        reason: str,
        guardrails: tuple[str, ...] = ("DETERMINISTIC_AUTHORITY",),
    ) -> QuantPolicyProposal:
        return QuantPolicyProposal(
            status=status,
            action="HOLD",
            directional_score=0.0,
            reason=reason,
            guardrails=guardrails,
            paper_only=True,
        )


def _bounded_float(value: object, *, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value if value is not None else 0.0)
    except (TypeError, ValueError):
        parsed = 0.0
    return max(minimum, min(maximum, parsed))


def _optional_bounded_float(value: object) -> float | None:
    if value is None:
        return None
    return round(_bounded_float(value, minimum=0.0, maximum=1.0), 6)


def _normalize_weights(value: object) -> tuple[tuple[str, float], ...]:
    if not isinstance(value, Mapping):
        return ()
    parsed = {
        str(key): _bounded_float(weight, minimum=-1.0, maximum=1.0)
        for key, weight in value.items()
    }
    gross = sum(abs(weight) for weight in parsed.values())
    if gross > 1.0:
        parsed = {key: weight / gross for key, weight in parsed.items()}
    return tuple(sorted((key, round(weight, 6)) for key, weight in parsed.items()))
