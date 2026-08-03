from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hmac
import hashlib
import json
import math
from typing import Any, Iterable, Mapping, Protocol, Sequence


ACTIVE_JOB_STATUSES = {
    "planned",
    "snapshot_publishing",
    "snapshot_published",
    "training_queued",
    "training_running",
    "evaluation_queued",
    "evaluation_running",
    "promotion_queued",
    "promotion_running",
    "rollback_queued",
    "rollback_running",
}

CRITICAL_FLAG_KEYS = {
    "contaminated",
    "quarantined",
    "temporal_leakage",
    "lineage_leakage",
    "unverifiable_source",
    "unlicensed_source",
    "alpha_contaminated",
    "directional_accounting_invalid",
    "privacy_violation",
    "pii_present",
}

NEGATIVE_BOOLEAN_KEYS = {
    "source_verified",
    "license_ok",
    "privacy_ok",
    "temporal_integrity_ok",
    "directional_accounting_ok",
}


@dataclass(frozen=True)
class TrainingPolicy:
    enabled: bool
    minimum_examples: int = 250
    minimum_matured_ratio: float = 0.80
    minimum_days_between_runs: int = 30
    minimum_quality: float = 70.0


@dataclass(frozen=True)
class TrainingStats:
    approved_examples: int
    matured_examples: int
    active_jobs: int
    critical_quality_failures: int
    last_launched_at: datetime | None
    token_configured: bool

    @property
    def matured_ratio(self) -> float:
        if self.approved_examples <= 0:
            return 0.0
        return max(0.0, min(1.0, self.matured_examples / self.approved_examples))


@dataclass(frozen=True)
class ReadinessResult:
    eligible: bool
    blockers: tuple[str, ...]
    approved_examples: int
    matured_examples: int
    matured_ratio: float
    next_eligible_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "blockers": list(self.blockers),
            "approved_examples": self.approved_examples,
            "matured_examples": self.matured_examples,
            "matured_ratio": round(self.matured_ratio, 6),
            "next_eligible_at": self.next_eligible_at.isoformat() if self.next_eligible_at else None,
        }


def evaluate_readiness(
    stats: TrainingStats,
    policy: TrainingPolicy,
    *,
    now: datetime | None = None,
) -> ReadinessResult:
    current = _ensure_aware(now or datetime.now(timezone.utc))
    blockers: list[str] = []
    next_eligible_at: datetime | None = None

    if not policy.enabled or not stats.token_configured:
        blockers.append("feature_disabled_or_token_missing")
    if stats.approved_examples < max(1, policy.minimum_examples):
        blockers.append("insufficient_approved_examples")
    if stats.matured_ratio < max(0.0, min(1.0, policy.minimum_matured_ratio)):
        blockers.append("insufficient_matured_outcomes")
    if stats.active_jobs > 0:
        blockers.append("training_job_already_active")
    if stats.critical_quality_failures > 0:
        blockers.append("critical_quality_gate_failure")
    if stats.last_launched_at is not None:
        last = _ensure_aware(stats.last_launched_at)
        next_eligible_at = last + timedelta(days=max(0, policy.minimum_days_between_runs))
        if current < next_eligible_at:
            blockers.append("training_cooldown_active")

    return ReadinessResult(
        eligible=not blockers,
        blockers=tuple(blockers),
        approved_examples=stats.approved_examples,
        matured_examples=stats.matured_examples,
        matured_ratio=stats.matured_ratio,
        next_eligible_at=next_eligible_at,
    )


@dataclass(frozen=True)
class SnapshotPolicy:
    minimum_quality: float = 70.0
    require_matured_outcome: bool = True
    train_percent: int = 80
    validation_percent: int = 10
    test_percent: int = 10
    schema_version: str = "blum-finance-reasoning-v2"
    quality_gate_version: str = "blum-hf-quality-v1"

    def __post_init__(self) -> None:
        if self.train_percent + self.validation_percent + self.test_percent != 100:
            raise ValueError("Snapshot split percentages must total 100")
        if min(self.train_percent, self.validation_percent, self.test_percent) < 0:
            raise ValueError("Snapshot split percentages cannot be negative")


@dataclass(frozen=True)
class SnapshotArtifact:
    snapshot_hash: str
    records: dict[str, tuple[dict[str, Any], ...]]
    files: dict[str, bytes]
    manifest: dict[str, Any]

    @property
    def revision(self) -> str:
        return f"snapshot-{self.snapshot_hash[:12]}"


def build_snapshot(
    raw_rows: Iterable[Mapping[str, Any]],
    policy: SnapshotPolicy,
    *,
    code_revision: str = "unknown",
    parent_model_repository: str = "Italianhype/Blum-Finance-4B",
    parent_model_revision: str = "main",
) -> SnapshotArtifact:
    accepted_by_lineage: dict[str, dict[str, Any]] = {}
    rejection_reasons: dict[str, int] = {}

    for raw in raw_rows:
        normalized = _normalize_candidate(raw)
        reason = _rejection_reason(normalized, policy)
        if reason is not None:
            rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
            continue
        lineage = normalized["lineage_key"]
        current = accepted_by_lineage.get(lineage)
        if current is None:
            accepted_by_lineage[lineage] = normalized
            continue
        if _candidate_rank(normalized) > _candidate_rank(current):
            accepted_by_lineage[lineage] = normalized
        rejection_reasons["duplicate_lineage"] = rejection_reasons.get("duplicate_lineage", 0) + 1

    grouped: dict[str, list[dict[str, Any]]] = {"train": [], "validation": [], "test": []}
    temporal_rows = sorted(
        accepted_by_lineage.items(),
        key=lambda item: (str(item[1].get("created_at") or ""), item[0]),
    )
    for index, (lineage, row) in enumerate(temporal_rows):
        split = _temporal_split_for_index(index, len(temporal_rows), policy)
        learning_context = _learning_context(row["outcomes"])
        record = {
            "schema_version": policy.schema_version,
            "lineage_key": lineage,
            "example_id": row["example_id"],
            "knowledge_record_id": row["knowledge_record_id"],
            "created_at": row["created_at"],
            "task_type": row["task_type"],
            "input": row["input"],
            "output": row["output"],
            "messages": _with_outcome_reflection(row["messages"], learning_context),
            "preference": row["preference"],
            "quality": row["quality"],
            "outcomes": row["outcomes"],
            "learning_context": learning_context,
            "provenance": row["provenance"],
        }
        grouped[split].append(record)

    canonical_files: dict[str, bytes] = {}
    frozen_records: dict[str, tuple[dict[str, Any], ...]] = {}
    for split in ("train", "validation", "test"):
        ordered = tuple(sorted(grouped[split], key=lambda row: (row["lineage_key"], str(row["example_id"]))))
        frozen_records[split] = ordered
        canonical_files[f"data/{split}.jsonl"] = _jsonl_bytes(ordered)

    digest = hashlib.sha256()
    for path in sorted(canonical_files):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(canonical_files[path])
        digest.update(b"\0")
    snapshot_hash = digest.hexdigest()

    total_input = len(accepted_by_lineage) + sum(rejection_reasons.values())
    split_counts = {name: len(rows) for name, rows in frozen_records.items()}
    snapshot_as_of = max(
        (str(row.get("created_at") or "") for rows in frozen_records.values() for row in rows),
        default=None,
    )
    manifest = {
        "schema_version": policy.schema_version,
        "snapshot_hash": snapshot_hash,
        "revision": f"snapshot-{snapshot_hash[:12]}",
        "code_revision": code_revision,
        "snapshot_as_of": snapshot_as_of,
        "parent_model": {
            "repository": parent_model_repository,
            "revision": parent_model_revision,
        },
        "quality_policy": {
            "minimum_quality": policy.minimum_quality,
            "require_matured_outcome": policy.require_matured_outcome,
            "quality_gate_version": policy.quality_gate_version,
            "critical_flag_keys": sorted(CRITICAL_FLAG_KEYS),
        },
        "accepted_rows": len(accepted_by_lineage),
        "rejected_rows": sum(rejection_reasons.values()),
        "input_rows": total_input,
        "rejection_reasons": dict(sorted(rejection_reasons.items())),
        "split_counts": split_counts,
        "split_strategy": "grouped_temporal_holdout",
        "split_periods": {
            name: {
                "start": min((str(row.get("created_at") or "") for row in rows), default=None),
                "end": max((str(row.get("created_at") or "") for row in rows), default=None),
            }
            for name, rows in frozen_records.items()
        },
        "lineage_leakage": False,
        "temporal_leakage": False,
        "files": {
            path: {
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
            }
            for path, content in sorted(canonical_files.items())
        },
    }
    all_files = dict(canonical_files)
    all_files["manifest.json"] = (_canonical_json(manifest) + "\n").encode("utf-8")
    return SnapshotArtifact(snapshot_hash=snapshot_hash, records=frozen_records, files=all_files, manifest=manifest)


def _normalize_candidate(raw: Mapping[str, Any]) -> dict[str, Any]:
    lineage = str(
        raw.get("lineage_key")
        or raw.get("reasoning_hash")
        or raw.get("knowledge_record_id")
        or raw.get("example_id")
        or ""
    ).strip()
    messages = raw.get("messages") or []
    if isinstance(messages, Mapping):
        messages = messages.get("items") or []
    outcomes = raw.get("outcomes") or []
    if isinstance(outcomes, Mapping):
        outcomes = outcomes.get("items") or []
    flags = raw.get("flags") or {}
    provenance = raw.get("provenance") or {}
    if not isinstance(flags, Mapping):
        flags = {}
    if not isinstance(provenance, Mapping):
        provenance = {}
    return {
        "example_id": raw.get("example_id"),
        "knowledge_record_id": raw.get("knowledge_record_id"),
        "lineage_key": lineage,
        "created_at": str(raw.get("created_at") or ""),
        "quality": _safe_float(raw.get("quality"), default=0.0),
        "task_type": str(raw.get("task_type") or "financial_thesis_generation"),
        "messages": list(messages) if isinstance(messages, Sequence) and not isinstance(messages, (str, bytes)) else [],
        "input": _json_mapping(raw.get("input")),
        "output": _json_mapping(raw.get("output")),
        "preference": _json_mapping(raw.get("preference")),
        "outcomes": list(outcomes) if isinstance(outcomes, Sequence) and not isinstance(outcomes, (str, bytes)) else [],
        "flags": dict(flags),
        "provenance": dict(provenance),
    }


def _rejection_reason(row: Mapping[str, Any], policy: SnapshotPolicy) -> str | None:
    if not row.get("lineage_key") or not row.get("messages") or not row.get("input") or not row.get("output"):
        return "missing_required_training_content"
    if _contains_critical_flag(row.get("flags") or {}) or _contains_critical_flag(row.get("provenance") or {}):
        return "critical_safety_or_provenance_flag"
    if _safe_float(row.get("quality"), default=0.0) < policy.minimum_quality:
        return "quality_below_threshold"
    if policy.require_matured_outcome and not _has_matured_outcome(row.get("outcomes") or []):
        return "immature_outcome"
    return None


def _contains_critical_flag(payload: Mapping[str, Any]) -> bool:
    for key, value in _walk_mapping(payload):
        normalized = key.strip().lower()
        if normalized in CRITICAL_FLAG_KEYS and _truthy(value):
            return True
        if normalized in NEGATIVE_BOOLEAN_KEYS and value is False:
            return True
    return False


def _walk_mapping(payload: Mapping[str, Any]) -> Iterable[tuple[str, Any]]:
    for key, value in payload.items():
        yield str(key), value
        if isinstance(value, Mapping):
            yield from _walk_mapping(value)


def _has_matured_outcome(outcomes: Sequence[Any]) -> bool:
    for outcome in outcomes:
        if not isinstance(outcome, Mapping):
            continue
        if outcome.get("realized_return") is not None:
            return True
        label = str(outcome.get("outcome") or outcome.get("status") or "").strip().lower()
        if label and label not in {"pending", "inconclusive", "unresolved", "not_matured"}:
            return True
    return False


def _learning_context(outcomes: Sequence[Any]) -> dict[str, Any] | None:
    matured = [dict(item) for item in outcomes if isinstance(item, Mapping) and _outcome_is_mature(item)]
    if not matured:
        return None
    latest = max(matured, key=lambda item: str(item.get("updated_at") or ""))
    success = latest.get("success")
    label = str(latest.get("outcome") or latest.get("status") or "").strip().lower()
    if success is True or label in {"correct", "win", "target_hit", "confirmed", "outperformed"}:
        assessment = "confirmed"
        confidence_direction = "increase"
    elif success is False or label in {"incorrect", "loss", "stopped_out", "invalidated", "underperformed"}:
        assessment = "contradicted"
        confidence_direction = "decrease"
    else:
        assessment = "mixed"
        confidence_direction = "hold"
    horizon = latest.get("horizon_days")
    lesson = (
        f"The stored {horizon}-day outcome {assessment} this thesis. "
        "Treat it as one observation and update confidence only after similar independent outcomes."
    )
    return {
        "context_type": "validated_post_outcome_evidence",
        "outcome_assessment": assessment,
        "confidence_direction": confidence_direction,
        "lesson": lesson,
        "sample_warning": "A single matured thesis is evidence, not a general trading rule.",
        "outcomes": matured,
    }


def _with_outcome_reflection(
    messages: Sequence[Any],
    learning_context: Mapping[str, Any] | None,
) -> list[Any]:
    original = [dict(item) if isinstance(item, Mapping) else item for item in messages]
    if not learning_context:
        return original
    observed = {
        "context_type": learning_context["context_type"],
        "instruction": (
            "Audit the preceding thesis using only this subsequently observed outcome. "
            "Do not rewrite the historical decision with hindsight."
        ),
        "outcomes": learning_context["outcomes"],
    }
    reflection = {
        key: learning_context[key]
        for key in (
            "outcome_assessment",
            "confidence_direction",
            "lesson",
            "sample_warning",
        )
    }
    return [
        *original,
        {"role": "user", "content": _canonical_json(observed)},
        {"role": "assistant", "content": _canonical_json(reflection)},
    ]


def _outcome_is_mature(outcome: Mapping[str, Any]) -> bool:
    if outcome.get("realized_return") is not None:
        return True
    label = str(outcome.get("outcome") or outcome.get("status") or "").strip().lower()
    return bool(label and label not in {"pending", "inconclusive", "unresolved", "not_matured"})


def _candidate_rank(row: Mapping[str, Any]) -> tuple[float, str, str]:
    return (
        _safe_float(row.get("quality"), default=0.0),
        str(row.get("created_at") or ""),
        str(row.get("example_id") or ""),
    )


def _temporal_split_for_index(index: int, total: int, policy: SnapshotPolicy) -> str:
    if total <= 1:
        return "train"
    if total == 2:
        return "train" if index == 0 else "test"
    train_end = max(1, min(total - 2, int(total * policy.train_percent / 100)))
    validation_end = max(
        train_end + 1,
        min(
            total - 1,
            int(total * (policy.train_percent + policy.validation_percent) / 100),
        ),
    )
    if index < train_end:
        return "train"
    if index < validation_end:
        return "validation"
    return "test"


def _jsonl_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    if not rows:
        return b""
    return ("\n".join(_canonical_json(row) for row in rows) + "\n").encode("utf-8")


@dataclass(frozen=True)
class JobLaunchRequest:
    script: str
    job_kind: str
    dataset_repository: str
    dataset_revision: str
    champion_repository: str
    champion_revision: str
    challenger_repository: str
    candidate_revision: str
    flavor: str = "a10g-large"
    timeout: str = "8h"
    image: str | None = None
    extra_env: Mapping[str, str] = field(default_factory=dict)
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class JobLaunchResult:
    remote_job_id: str
    remote_job_url: str
    remote_status: str


class JobsClientProtocol(Protocol):
    def run_uv_job(self, script: str, **kwargs: Any) -> Any: ...


class HuggingFaceJobLauncher:
    def __init__(self, *, client: JobsClientProtocol, token: str) -> None:
        if not token:
            raise ValueError("HF_TOKEN is required to launch Hugging Face Jobs")
        self.client = client
        self._token = token

    def launch(self, request: JobLaunchRequest) -> JobLaunchResult:
        env = {
            "BLUM_JOB_KIND": request.job_kind,
            "BLUM_DATASET_REPOSITORY": request.dataset_repository,
            "BLUM_DATASET_REVISION": request.dataset_revision,
            "BLUM_CHAMPION_REPOSITORY": request.champion_repository,
            "BLUM_CHAMPION_REVISION": request.champion_revision,
            "BLUM_CHALLENGER_REPOSITORY": request.challenger_repository,
            "BLUM_CANDIDATE_REVISION": request.candidate_revision,
            **{str(key): str(value) for key, value in request.extra_env.items()},
        }
        kwargs: dict[str, Any] = {
            "env": env,
            "secrets": {"HF_TOKEN": self._token},
            "flavor": request.flavor,
            "timeout": request.timeout,
            "labels": {
                "project": "blum",
                "blum-job-kind": request.job_kind,
                "dataset-revision": request.dataset_revision[:63],
                "candidate-revision": request.candidate_revision[:63],
            },
        }
        if request.image:
            kwargs["image"] = request.image
        if request.dependencies:
            kwargs["dependencies"] = list(request.dependencies)
        job = self.client.run_uv_job(request.script, **kwargs)
        status = getattr(getattr(job, "status", None), "stage", None) or "UNKNOWN"
        return JobLaunchResult(
            remote_job_id=str(getattr(job, "id")),
            remote_job_url=str(getattr(job, "url", "")),
            remote_status=str(status),
        )


@dataclass(frozen=True)
class EvaluationGate:
    minimum_structured_validity: float = 0.99
    minimum_directional_accounting: float = 1.0
    maximum_temporal_leakage: int = 0
    maximum_critical_regressions: int = 0
    allow_aggregate_regression: float = 0.0
    allow_no_fabrication_regression: float = 0.0


@dataclass(frozen=True)
class GateResult:
    eligible: bool
    blockers: tuple[str, ...]


def evaluate_candidate(metrics: Mapping[str, Any], gate: EvaluationGate) -> GateResult:
    candidate = _json_mapping(metrics.get("candidate"))
    champion = _json_mapping(metrics.get("champion"))
    blockers: list[str] = []

    candidate_aggregate = _safe_float(candidate.get("aggregate_contract_score"), default=-math.inf)
    champion_aggregate = _safe_float(champion.get("aggregate_contract_score"), default=-math.inf)
    if candidate_aggregate + gate.allow_aggregate_regression < champion_aggregate:
        blockers.append("aggregate_contract_regression")

    if _safe_float(candidate.get("structured_validity"), default=0.0) < gate.minimum_structured_validity:
        blockers.append("structured_validity_below_gate")

    candidate_fabrication = _safe_float(candidate.get("no_fabrication"), default=0.0)
    champion_fabrication = _safe_float(champion.get("no_fabrication"), default=0.0)
    if candidate_fabrication + gate.allow_no_fabrication_regression < champion_fabrication:
        blockers.append("no_fabrication_regression")

    if _safe_float(candidate.get("directional_accounting"), default=0.0) < gate.minimum_directional_accounting:
        blockers.append("directional_accounting_below_gate")

    if int(_safe_float(candidate.get("critical_regressions"), default=999)) > gate.maximum_critical_regressions:
        blockers.append("critical_regressions_present")

    if int(_safe_float(metrics.get("temporal_leakage"), default=999)) > gate.maximum_temporal_leakage:
        blockers.append("temporal_leakage_detected")

    return GateResult(eligible=not blockers, blockers=tuple(blockers))


def assert_promotion_allowed(metrics: Mapping[str, Any], gate: EvaluationGate) -> GateResult:
    result = evaluate_candidate(metrics, gate)
    if not result.eligible:
        raise ValueError(",".join(result.blockers))
    return result


@dataclass(frozen=True)
class PromotionRequest:
    job_kind: str
    source_repository: str
    source_revision: str
    destination_repository: str
    destination_revision: str
    backup_tag: str
    metrics: Mapping[str, Any]


def build_promotion_request(
    *,
    metrics: Mapping[str, Any],
    admin_key: str,
    supplied_admin_key: str,
    champion_repository: str,
    champion_revision: str,
    challenger_repository: str,
    candidate_revision: str,
    now: datetime | None = None,
    gate: EvaluationGate | None = None,
) -> PromotionRequest:
    if not admin_key or not hmac.compare_digest(supplied_admin_key or "", admin_key):
        raise PermissionError("Invalid BLUM HF training admin key")
    assert_promotion_allowed(metrics, gate or EvaluationGate())
    timestamp = _ensure_aware(now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    return PromotionRequest(
        job_kind="promotion",
        source_repository=challenger_repository,
        source_revision=candidate_revision,
        destination_repository=champion_repository,
        destination_revision="main",
        backup_tag=f"champion-backup-{timestamp}-{champion_revision[:8]}",
        metrics=dict(metrics),
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _json_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_float(value: Any, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on", "failed", "invalid"}
    return bool(value)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
