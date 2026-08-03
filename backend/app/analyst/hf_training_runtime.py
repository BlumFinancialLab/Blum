from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hmac
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
from typing import Any, Mapping

from huggingface_hub import CommitOperationAdd, HfApi
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.analyst.hf_job_scripts import load_job_script
from app.analyst.hf_training import (
    ACTIVE_JOB_STATUSES,
    EvaluationGate,
    HuggingFaceJobLauncher,
    JobLaunchRequest,
    SnapshotArtifact,
    SnapshotPolicy,
    TrainingPolicy,
    TrainingStats,
    build_promotion_request,
    build_snapshot,
    evaluate_candidate,
    evaluate_readiness,
)
from app.core.config import get_settings
from app.models import (
    BlumDatasetExport,
    BlumKnowledgeRecord,
    BlumModelTrainingJob,
    BlumThesisOutcome,
    BlumTrainingExample,
    TrainingExampleQualityScore,
)


FAILED_REMOTE_STAGES = {"ERROR", "CANCELED", "DELETED"}


class LocalSnapshotPublisher:
    """Persist immutable training snapshots without requiring Hub credentials."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def publish(self, snapshot: SnapshotArtifact) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self.root / snapshot.revision
        manifest_path = destination / "manifest.json"
        archive_path = self.root / f"{snapshot.revision}.tar.gz"
        if manifest_path.is_file():
            try:
                existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = {}
            if existing.get("snapshot_hash") == snapshot.snapshot_hash and archive_path.is_file():
                return self._result("already_published", snapshot, manifest_path, archive_path)

        temporary_root = Path(tempfile.mkdtemp(prefix=f".{snapshot.revision}-", dir=self.root))
        temporary_archive = self.root / f".{snapshot.revision}.tar.gz.tmp"
        try:
            for relative, content in snapshot.files.items():
                target = temporary_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            if destination.exists():
                shutil.rmtree(destination)
            os.replace(temporary_root, destination)
            with tarfile.open(temporary_archive, "w:gz") as archive:
                archive.add(destination, arcname=snapshot.revision)
            os.replace(temporary_archive, archive_path)
        finally:
            if temporary_root.exists():
                shutil.rmtree(temporary_root, ignore_errors=True)
            temporary_archive.unlink(missing_ok=True)
        return self._result("published", snapshot, manifest_path, archive_path)

    @staticmethod
    def _result(
        status: str,
        snapshot: SnapshotArtifact,
        manifest_path: Path,
        archive_path: Path,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "revision": snapshot.revision,
            "snapshot_hash": snapshot.snapshot_hash,
            "accepted_rows": int(snapshot.manifest["accepted_rows"]),
            "manifest_path": str(manifest_path),
            "archive_path": str(archive_path),
        }


class HubDatasetPublisher:
    def __init__(self, *, api: HfApi, token: str) -> None:
        self.api = api
        self.token = token

    def publish(self, repository: str, snapshot: SnapshotArtifact) -> dict[str, Any]:
        self.api.create_repo(repository, repo_type="dataset", token=self.token, exist_ok=True)
        self.api.create_branch(
            repository,
            repo_type="dataset",
            branch=snapshot.revision,
            token=self.token,
            exist_ok=True,
        )
        if self.api.file_exists(
            repository,
            "manifest.json",
            repo_type="dataset",
            revision=snapshot.revision,
            token=self.token,
        ):
            info = self.api.repo_info(
                repository,
                repo_type="dataset",
                revision=snapshot.revision,
                token=self.token,
            )
            return {
                "status": "already_published",
                "repository": repository,
                "revision": snapshot.revision,
                "commit": info.sha,
            }

        operations = [
            CommitOperationAdd(path_in_repo=path, path_or_fileobj=content)
            for path, content in sorted(snapshot.files.items())
        ]
        operations.append(
            CommitOperationAdd(
                path_in_repo="README.md",
                path_or_fileobj=_dataset_readme(repository, snapshot).encode("utf-8"),
            )
        )
        commit = self.api.create_commit(
            repository,
            repo_type="dataset",
            revision=snapshot.revision,
            token=self.token,
            operations=operations,
            commit_message=f"Publish BLUM reasoning snapshot {snapshot.snapshot_hash[:12]}",
            commit_description="Immutable, outcome-matured and lineage-safe BLUM training snapshot.",
        )
        return {
            "status": "published",
            "repository": repository,
            "revision": snapshot.revision,
            "commit": getattr(commit, "oid", None) or getattr(commit, "commit_id", None),
            "url": getattr(commit, "commit_url", None),
        }


class BlumHFTrainingService:
    """Production boundary between the BLUM Space and external Hugging Face Jobs.

    The Space prepares data and records state. GPU training, evaluation, promotion,
    and rollback happen in isolated Jobs and never inside the web process.
    """

    def __init__(self, *, api: HfApi | None = None, token: str | None = None) -> None:
        self.settings = get_settings()
        self.token = (token if token is not None else os.getenv("HF_TOKEN", "")).strip()
        self.api = api or HfApi(token=self.token or None)

    def training_policy(self) -> TrainingPolicy:
        return TrainingPolicy(
            enabled=self.settings.hf_training_enabled,
            minimum_examples=self.settings.hf_training_minimum_examples,
            minimum_matured_ratio=self.settings.hf_training_minimum_matured_ratio,
            minimum_days_between_runs=self.settings.hf_training_minimum_days_between_runs,
            minimum_quality=self.settings.hf_training_minimum_quality,
        )

    def snapshot_policy(self, *, require_matured_outcome: bool = True) -> SnapshotPolicy:
        return SnapshotPolicy(
            minimum_quality=self.settings.hf_training_minimum_quality,
            require_matured_outcome=require_matured_outcome,
        )

    def configuration_status(self) -> dict[str, Any]:
        return {
            "enabled": self.settings.hf_training_enabled,
            "auto_launch": self.settings.hf_training_auto_launch,
            "scheduler_enabled": self.settings.hf_training_scheduler_enabled,
            "continual_snapshot_enabled": self.settings.hf_dataset_snapshot_enabled,
            "continual_snapshot": self.local_snapshot_status(),
            "token_configured": bool(self.token),
            "repositories": {
                "dataset": self.settings.hf_training_dataset_repository,
                "champion": self.settings.hf_training_champion_repository,
                "challenger": self.settings.hf_training_challenger_repository,
                "mlx": self.settings.hf_training_mlx_repository,
            },
            "governance": {
                "training_inside_space": False,
                "automatic_promotion": False,
                "manual_promotion_required": True,
                "rollback_required": True,
            },
        }

    def status(self, db: Session) -> dict[str, Any]:
        rows = self.collect_candidates(db)
        stats = self._training_stats(db, rows)
        readiness = evaluate_readiness(stats, self.training_policy())
        recent_jobs = db.scalars(
            select(BlumModelTrainingJob)
            .order_by(desc(BlumModelTrainingJob.created_at))
            .limit(10)
        ).all()
        return {
            "status": "ready" if readiness.eligible else "blocked",
            **self.configuration_status(),
            "readiness": readiness.to_dict(),
            "policy": asdict(self.training_policy()),
            "recent_jobs": [serialize_training_job(row) for row in recent_jobs],
        }

    def collect_candidates(self, db: Session) -> list[dict[str, Any]]:
        limit = max(1, self.settings.hf_training_max_examples)
        examples = db.scalars(
            select(BlumTrainingExample)
            .where(BlumTrainingExample.export_ready.is_(True))
            .order_by(desc(BlumTrainingExample.created_at))
            .limit(limit)
        ).all()
        if not examples:
            return []

        example_ids = [row.id for row in examples]
        knowledge_ids = [row.knowledge_record_id for row in examples if row.knowledge_record_id is not None]
        records = {
            row.id: row
            for row in db.scalars(select(BlumKnowledgeRecord).where(BlumKnowledgeRecord.id.in_(knowledge_ids))).all()
        } if knowledge_ids else {}
        quality_rows = {
            row.training_example_id: row
            for row in db.scalars(
                select(TrainingExampleQualityScore).where(TrainingExampleQualityScore.training_example_id.in_(example_ids))
            ).all()
        }
        outcomes_by_record: dict[int, list[dict[str, Any]]] = {}
        if knowledge_ids:
            outcomes = db.scalars(
                select(BlumThesisOutcome)
                .where(BlumThesisOutcome.knowledge_record_id.in_(knowledge_ids))
                .order_by(BlumThesisOutcome.knowledge_record_id, BlumThesisOutcome.horizon_days)
            ).all()
            for outcome in outcomes:
                outcomes_by_record.setdefault(outcome.knowledge_record_id, []).append(
                    {
                        "horizon_days": outcome.horizon_days,
                        "realized_return": outcome.realized_return,
                        "max_drawdown": outcome.max_drawdown,
                        "max_upside": outcome.max_upside,
                        "outcome": outcome.outcome,
                        "success": outcome.success,
                        "updated_at": _iso(outcome.updated_at),
                    }
                )

        candidates: list[dict[str, Any]] = []
        for example in examples:
            record = records.get(example.knowledge_record_id)
            quality_row = quality_rows.get(example.id)
            quality_payload = example.quality_scores or {}
            quality = (
                float(quality_row.final_training_value_score)
                if quality_row is not None
                else _quality_from_payload(quality_payload)
            )
            flags: dict[str, Any] = {}
            if quality_row is not None and quality_row.exclusion_reason:
                flags["quality_exclusion_reason"] = quality_row.exclusion_reason
                if not quality_row.include_in_sft:
                    flags["quarantined"] = True
            for payload in (example.input_payload, example.output_payload, example.preference_payload, quality_payload):
                _merge_safety_flags(flags, payload or {})

            provenance = {}
            if isinstance(example.input_payload, Mapping):
                source = example.input_payload.get("provenance") or example.input_payload.get("sources")
                if source:
                    provenance["sources"] = source
            candidates.append(
                {
                    "example_id": example.id,
                    "knowledge_record_id": example.knowledge_record_id,
                    "lineage_key": (record.reasoning_hash if record is not None else f"example:{example.id}"),
                    "created_at": _iso(example.created_at),
                    "quality": quality,
                    "task_type": example.task_type,
                    "messages": (example.messages or {}).get("items", []),
                    "input": example.input_payload or {},
                    "output": example.output_payload or {},
                    "preference": example.preference_payload or {},
                    "outcomes": outcomes_by_record.get(example.knowledge_record_id or -1, []),
                    "flags": flags,
                    "provenance": provenance,
                }
            )
        return candidates

    def build_local_snapshot(self, db: Session) -> SnapshotArtifact:
        champion_revision = self._configured_champion_revision(db) or "main"
        return build_snapshot(
            self.collect_candidates(db),
            self.snapshot_policy(require_matured_outcome=True),
            code_revision=os.getenv("SPACE_REVISION", os.getenv("COMMIT_SHA", "unknown")),
            parent_model_repository=self.settings.hf_training_champion_repository,
            parent_model_revision=champion_revision,
        )

    def persist_local_snapshot(self, db: Session) -> dict[str, Any]:
        if not self.settings.hf_dataset_snapshot_enabled:
            return {"status": "disabled", "reason": "continual_snapshot_disabled"}
        snapshot = self.build_local_snapshot(db)
        if int(snapshot.manifest.get("accepted_rows") or 0) <= 0:
            return {
                "status": "blocked",
                "reason": "no_approved_matured_examples",
                "manifest": snapshot.manifest,
            }
        return LocalSnapshotPublisher(self.settings.hf_dataset_snapshot_dir).publish(snapshot)

    def local_snapshot_status(self) -> dict[str, Any]:
        root = Path(self.settings.hf_dataset_snapshot_dir).expanduser().resolve()
        if not root.is_dir():
            return {"status": "missing", "reason": "no_local_snapshot"}
        manifests = sorted(
            root.glob("snapshot-*/manifest.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not manifests:
            return {"status": "missing", "reason": "no_local_snapshot"}
        manifest_path = manifests[0].resolve()
        if root not in manifest_path.parents:
            return {"status": "invalid", "reason": "snapshot_path_outside_root"}
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"status": "invalid", "reason": f"{type(exc).__name__}: {exc}"}
        revision = str(manifest.get("revision") or manifest_path.parent.name)
        archive_path = (root / f"{revision}.tar.gz").resolve()
        return {
            "status": "ready" if archive_path.is_file() else "incomplete",
            "revision": revision,
            "snapshot_hash": manifest.get("snapshot_hash"),
            "accepted_rows": manifest.get("accepted_rows"),
            "split_counts": manifest.get("split_counts") or {},
            "snapshot_as_of": manifest.get("snapshot_as_of"),
            "manifest_path": str(manifest_path),
            "archive_path": str(archive_path) if archive_path.is_file() else None,
        }

    def local_snapshot_archive(self) -> Path | None:
        status = self.local_snapshot_status()
        path = status.get("archive_path")
        if status.get("status") != "ready" or not path:
            return None
        root = Path(self.settings.hf_dataset_snapshot_dir).expanduser().resolve()
        archive = Path(str(path)).resolve()
        if root not in archive.parents or not archive.is_file():
            return None
        return archive

    def publish_snapshot(self, db: Session) -> dict[str, Any]:
        self._require_enabled_and_token()
        snapshot = self.build_local_snapshot(db)
        if snapshot.manifest["accepted_rows"] <= 0:
            return {"status": "blocked", "reason": "no_approved_matured_examples", "manifest": snapshot.manifest}
        published = HubDatasetPublisher(api=self.api, token=self.token).publish(
            self.settings.hf_training_dataset_repository,
            snapshot,
        )
        export = self._persist_dataset_export(db, snapshot, published)
        return {**published, "export_id": export.id, "manifest": snapshot.manifest}

    def launch(self, db: Session) -> dict[str, Any]:
        self._require_enabled_and_token()
        candidates = self.collect_candidates(db)
        stats = self._training_stats(db, candidates)
        readiness = evaluate_readiness(stats, self.training_policy())
        if not readiness.eligible:
            return {"status": "blocked", "readiness": readiness.to_dict()}

        snapshot = build_snapshot(
            candidates,
            self.snapshot_policy(require_matured_outcome=True),
            code_revision=os.getenv("SPACE_REVISION", os.getenv("COMMIT_SHA", "unknown")),
            parent_model_repository=self.settings.hf_training_champion_repository,
            parent_model_revision="pending-resolution",
        )
        split_counts = snapshot.manifest["split_counts"]
        if split_counts["train"] <= 0 or split_counts["test"] <= 0:
            return {
                "status": "blocked",
                "reason": "dataset_split_incomplete",
                "split_counts": split_counts,
                "manifest": snapshot.manifest,
            }
        duplicate = self._job_for_snapshot_hash(db, snapshot.snapshot_hash)
        if duplicate is not None:
            return {"status": "idempotent", "job": serialize_training_job(duplicate)}

        champion_info = self.api.repo_info(
            self.settings.hf_training_champion_repository,
            repo_type="model",
            revision="main",
            token=self.token,
        )
        champion_revision = champion_info.sha
        snapshot = build_snapshot(
            candidates,
            self.snapshot_policy(require_matured_outcome=True),
            code_revision=os.getenv("SPACE_REVISION", os.getenv("COMMIT_SHA", "unknown")),
            parent_model_repository=self.settings.hf_training_champion_repository,
            parent_model_revision=champion_revision,
        )
        published = HubDatasetPublisher(api=self.api, token=self.token).publish(
            self.settings.hf_training_dataset_repository,
            snapshot,
        )
        export = self._persist_dataset_export(db, snapshot, published)
        candidate_revision = f"candidate-{snapshot.snapshot_hash[:12]}"
        job = BlumModelTrainingJob(
            job_name=f"blum-challenger-{snapshot.snapshot_hash[:12]}",
            model_family="Qwen3",
            base_model=self.settings.hf_training_champion_repository,
            method="LoRA-SFT",
            dataset_export_id=export.id,
            status="planned",
            training_config={
                "pipeline_version": "blum-hf-champion-challenger-v1",
                "dataset_repository": self.settings.hf_training_dataset_repository,
                "dataset_revision": snapshot.revision,
                "dataset_hash": snapshot.snapshot_hash,
                "dataset_commit": published.get("commit"),
                "champion_repository": self.settings.hf_training_champion_repository,
                "champion_revision": champion_revision,
                "challenger_repository": self.settings.hf_training_challenger_repository,
                "candidate_revision": candidate_revision,
                "snapshot_manifest": snapshot.manifest,
                "launched_at": _iso(datetime.now(timezone.utc)),
            },
            metrics={},
        )
        db.add(job)
        db.commit()

        try:
            launched = self._launcher().launch(
                JobLaunchRequest(
                    script=load_job_script("training"),
                    job_kind="training",
                    dataset_repository=self.settings.hf_training_dataset_repository,
                    dataset_revision=snapshot.revision,
                    champion_repository=self.settings.hf_training_champion_repository,
                    champion_revision=champion_revision,
                    challenger_repository=self.settings.hf_training_challenger_repository,
                    candidate_revision=candidate_revision,
                    flavor=self.settings.hf_training_hardware,
                    timeout=self.settings.hf_training_timeout,
                    image=self.settings.hf_training_job_image,
                    extra_env={
                        "BLUM_BASE_MODEL": self.settings.hf_training_champion_repository,
                        "BLUM_TRAINING_SEED": "3407",
                    },
                )
            )
            job.status = "training_queued"
            job.training_config = {
                **(job.training_config or {}),
                "remote_training_job_id": launched.remote_job_id,
                "remote_training_job_url": launched.remote_job_url,
                "remote_training_status": launched.remote_status,
            }
        except Exception as exc:  # network/provider boundary
            job.status = "launch_failed"
            job.metrics = {"launch_error": f"{type(exc).__name__}: {exc}"}
        db.commit()
        return {"status": job.status, "job": serialize_training_job(job)}

    def sync(self, db: Session, *, job_id: int | None = None) -> dict[str, Any]:
        self._require_enabled_and_token()
        if job_id is not None:
            jobs = [db.get(BlumModelTrainingJob, job_id)]
        else:
            jobs = db.scalars(
                select(BlumModelTrainingJob)
                .where(BlumModelTrainingJob.status.in_(ACTIVE_JOB_STATUSES))
                .order_by(BlumModelTrainingJob.created_at)
            ).all()
        results = []
        for job in [row for row in jobs if row is not None]:
            results.append(self._sync_job(db, job))
        return {"status": "ok", "jobs": results}

    def promote(self, db: Session, *, job_id: int, supplied_admin_key: str) -> dict[str, Any]:
        self._require_enabled_and_token()
        job = db.get(BlumModelTrainingJob, job_id)
        if job is None:
            raise LookupError(f"BLUM training job {job_id} was not found")
        if job.status != "eligible":
            raise ValueError(f"BLUM training job {job_id} is not eligible for promotion")
        config = job.training_config or {}
        request = build_promotion_request(
            metrics=job.metrics or {},
            admin_key=self.settings.hf_training_admin_key,
            supplied_admin_key=supplied_admin_key,
            champion_repository=self.settings.hf_training_champion_repository,
            champion_revision=str(config.get("champion_revision") or "main"),
            challenger_repository=self.settings.hf_training_challenger_repository,
            candidate_revision=str(config.get("candidate_revision") or ""),
        )
        launch = self._launcher().launch(
            JobLaunchRequest(
                script=load_job_script("promotion"),
                job_kind="promotion",
                dataset_repository=str(config.get("dataset_repository") or self.settings.hf_training_dataset_repository),
                dataset_revision=str(config.get("dataset_revision") or "unknown"),
                champion_repository=self.settings.hf_training_champion_repository,
                champion_revision=str(config.get("champion_revision") or "main"),
                challenger_repository=self.settings.hf_training_challenger_repository,
                candidate_revision=request.source_revision,
                flavor="cpu-upgrade",
                timeout="4h",
                extra_env={
                    "BLUM_PROMOTION_SOURCE_REPOSITORY": request.source_repository,
                    "BLUM_PROMOTION_SOURCE_REVISION": request.source_revision,
                    "BLUM_PROMOTION_DESTINATION_REPOSITORY": request.destination_repository,
                    "BLUM_PROMOTION_DESTINATION_REVISION": request.destination_revision,
                    "BLUM_PROMOTION_BACKUP_TAG": request.backup_tag,
                },
            )
        )
        job.status = "promotion_queued"
        job.training_config = {
            **config,
            "remote_promotion_job_id": launch.remote_job_id,
            "remote_promotion_job_url": launch.remote_job_url,
            "champion_backup_tag": request.backup_tag,
        }
        db.commit()
        return {"status": job.status, "job": serialize_training_job(job)}

    def rollback(
        self,
        db: Session,
        *,
        job_id: int,
        backup_tag: str,
        supplied_admin_key: str,
    ) -> dict[str, Any]:
        self._require_enabled_and_token()
        self._require_admin_key(supplied_admin_key)
        job = db.get(BlumModelTrainingJob, job_id)
        if job is None:
            raise LookupError(f"BLUM training job {job_id} was not found")
        if not backup_tag.startswith("champion-backup-"):
            raise ValueError("Rollback tag must be a BLUM champion backup tag")
        config = job.training_config or {}
        launch = self._launcher().launch(
            JobLaunchRequest(
                script=load_job_script("rollback"),
                job_kind="rollback",
                dataset_repository=str(config.get("dataset_repository") or self.settings.hf_training_dataset_repository),
                dataset_revision=str(config.get("dataset_revision") or "unknown"),
                champion_repository=self.settings.hf_training_champion_repository,
                champion_revision=backup_tag,
                challenger_repository=self.settings.hf_training_champion_repository,
                candidate_revision=backup_tag,
                flavor="cpu-upgrade",
                timeout="4h",
                extra_env={
                    "BLUM_PROMOTION_SOURCE_REPOSITORY": self.settings.hf_training_champion_repository,
                    "BLUM_PROMOTION_SOURCE_REVISION": backup_tag,
                    "BLUM_PROMOTION_DESTINATION_REPOSITORY": self.settings.hf_training_champion_repository,
                    "BLUM_PROMOTION_DESTINATION_REVISION": "main",
                    "BLUM_PROMOTION_BACKUP_TAG": "",
                },
            )
        )
        job.status = "rollback_queued"
        job.training_config = {
            **config,
            "remote_rollback_job_id": launch.remote_job_id,
            "remote_rollback_job_url": launch.remote_job_url,
            "rollback_source_tag": backup_tag,
        }
        db.commit()
        return {"status": job.status, "job": serialize_training_job(job)}

    def supervise(self, db: Session) -> dict[str, Any]:
        try:
            local_snapshot = self.persist_local_snapshot(db)
        except Exception as exc:
            local_snapshot = {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}
        if not self.settings.hf_training_enabled or not self.token:
            training = {"status": "disabled", "token_configured": bool(self.token)}
            status = "snapshot_ready" if local_snapshot.get("status") in {"published", "already_published"} else "degraded"
            return {"status": status, "local_snapshot": local_snapshot, "training": training}
        synced = self.sync(db)
        launch = None
        if self.settings.hf_training_auto_launch:
            launch = self.launch(db)
        return {
            "status": "ok",
            "local_snapshot": local_snapshot,
            "training": {"status": "enabled", "sync": synced, "launch": launch},
        }

    def _sync_job(self, db: Session, job: BlumModelTrainingJob) -> dict[str, Any]:
        config = dict(job.training_config or {})
        if config.get("remote_rollback_job_id") and job.status in {"rollback_queued", "rollback_running"}:
            remote = self.api.inspect_job(job_id=config["remote_rollback_job_id"], token=self.token)
            stage = _remote_stage(remote)
            job.status = "rolled_back" if stage == "COMPLETED" else ("rollback_failed" if stage in FAILED_REMOTE_STAGES else "rollback_running")
            config["remote_rollback_status"] = stage
            if stage == "COMPLETED":
                config["rolled_back_champion_revision"] = self.api.repo_info(
                    self.settings.hf_training_champion_repository,
                    repo_type="model",
                    revision="main",
                    token=self.token,
                ).sha
        elif config.get("remote_promotion_job_id") and job.status in {"promotion_queued", "promotion_running"}:
            remote = self.api.inspect_job(job_id=config["remote_promotion_job_id"], token=self.token)
            stage = _remote_stage(remote)
            job.status = "promoted" if stage == "COMPLETED" else ("promotion_failed" if stage in FAILED_REMOTE_STAGES else "promotion_running")
            config["remote_promotion_status"] = stage
            if stage == "COMPLETED":
                config["promoted_champion_revision"] = self.api.repo_info(
                    self.settings.hf_training_champion_repository,
                    repo_type="model",
                    revision="main",
                    token=self.token,
                ).sha
        elif config.get("remote_evaluation_job_id"):
            remote = self.api.inspect_job(job_id=config["remote_evaluation_job_id"], token=self.token)
            stage = _remote_stage(remote)
            config["remote_evaluation_status"] = stage
            if stage == "COMPLETED":
                try:
                    metrics = self._load_evaluation(config)
                    gate = evaluate_candidate(metrics, EvaluationGate())
                    job.metrics = {**metrics, "promotion_gate": {"eligible": gate.eligible, "blockers": list(gate.blockers)}}
                    job.status = "eligible" if gate.eligible else "rejected"
                except Exception as exc:
                    job.status = "evaluation_artifact_missing"
                    job.metrics = {**(job.metrics or {}), "evaluation_artifact_error": f"{type(exc).__name__}: {exc}"}
            elif stage in FAILED_REMOTE_STAGES:
                job.status = "evaluation_failed"
            else:
                job.status = "evaluation_running"
        elif config.get("remote_training_job_id"):
            remote = self.api.inspect_job(job_id=config["remote_training_job_id"], token=self.token)
            stage = _remote_stage(remote)
            config["remote_training_status"] = stage
            if stage == "COMPLETED":
                try:
                    evaluation = self._launcher().launch(
                        JobLaunchRequest(
                            script=load_job_script("evaluation"),
                            job_kind="evaluation",
                            dataset_repository=str(config["dataset_repository"]),
                            dataset_revision=str(config["dataset_revision"]),
                            champion_repository=str(config["champion_repository"]),
                            champion_revision=str(config["champion_revision"]),
                            challenger_repository=str(config["challenger_repository"]),
                            candidate_revision=str(config["candidate_revision"]),
                            flavor=self.settings.hf_training_hardware,
                            timeout=self.settings.hf_training_timeout,
                            image=self.settings.hf_training_job_image,
                            extra_env={"BLUM_EVAL_MAX_EXAMPLES": str(self.settings.hf_training_eval_max_examples)},
                        )
                    )
                    config["remote_evaluation_job_id"] = evaluation.remote_job_id
                    config["remote_evaluation_job_url"] = evaluation.remote_job_url
                    job.status = "evaluation_queued"
                except Exception as exc:
                    job.status = "evaluation_launch_failed"
                    job.metrics = {**(job.metrics or {}), "evaluation_launch_error": f"{type(exc).__name__}: {exc}"}
            elif stage in FAILED_REMOTE_STAGES:
                job.status = "training_failed"
            else:
                job.status = "training_running"
        job.training_config = config
        db.commit()
        return serialize_training_job(job)

    def _load_evaluation(self, config: Mapping[str, Any]) -> dict[str, Any]:
        path = self.api.hf_hub_download(
            repo_id=str(config["challenger_repository"]),
            repo_type="model",
            revision=str(config["candidate_revision"]),
            filename="evaluation/evaluation.json",
            token=self.token,
        )
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def _training_stats(self, db: Session, candidates: list[dict[str, Any]]) -> TrainingStats:
        approved = build_snapshot(candidates, self.snapshot_policy(require_matured_outcome=False))
        matured = build_snapshot(candidates, self.snapshot_policy(require_matured_outcome=True))
        active_jobs = len(
            db.scalars(
                select(BlumModelTrainingJob.id).where(BlumModelTrainingJob.status.in_(ACTIVE_JOB_STATUSES))
            ).all()
        )
        recent = db.scalars(
            select(BlumModelTrainingJob)
            .order_by(desc(BlumModelTrainingJob.created_at))
            .limit(100)
        ).all()
        last_launched_at = None
        for row in recent:
            if (row.training_config or {}).get("remote_training_job_id"):
                last_launched_at = row.created_at
                break
        critical = int(bool(approved.manifest.get("lineage_leakage") or approved.manifest.get("temporal_leakage")))
        return TrainingStats(
            approved_examples=int(approved.manifest["accepted_rows"]),
            matured_examples=int(matured.manifest["accepted_rows"]),
            active_jobs=active_jobs,
            critical_quality_failures=critical,
            last_launched_at=last_launched_at,
            token_configured=bool(self.token),
        )

    def _job_for_snapshot_hash(self, db: Session, snapshot_hash: str) -> BlumModelTrainingJob | None:
        jobs = db.scalars(
            select(BlumModelTrainingJob)
            .order_by(desc(BlumModelTrainingJob.created_at))
            .limit(250)
        ).all()
        for job in jobs:
            if (job.training_config or {}).get("dataset_hash") == snapshot_hash and job.status not in {
                "launch_failed",
                "training_failed",
                "evaluation_failed",
                "rejected",
            }:
                return job
        return None

    def _persist_dataset_export(
        self,
        db: Session,
        snapshot: SnapshotArtifact,
        published: Mapping[str, Any],
    ) -> BlumDatasetExport:
        existing = db.scalars(
            select(BlumDatasetExport)
            .order_by(desc(BlumDatasetExport.created_at))
            .limit(250)
        ).all()
        for row in existing:
            if (row.payload_summary or {}).get("snapshot_hash") == snapshot.snapshot_hash:
                return row
        export = BlumDatasetExport(
            export_name=f"blum-finance-reasoning-{snapshot.snapshot_hash[:12]}",
            format="jsonl+manifest",
            record_count=int(snapshot.manifest["accepted_rows"]),
            file_path=f"hf://{self.settings.hf_training_dataset_repository}@{snapshot.revision}",
            filters=snapshot.manifest["quality_policy"],
            status="published",
            payload_summary={
                "snapshot_hash": snapshot.snapshot_hash,
                "revision": snapshot.revision,
                "commit": published.get("commit"),
                "manifest": snapshot.manifest,
            },
        )
        db.add(export)
        db.commit()
        return export

    def _configured_champion_revision(self, db: Session) -> str | None:
        jobs = db.scalars(
            select(BlumModelTrainingJob)
            .where(BlumModelTrainingJob.status == "promoted")
            .order_by(desc(BlumModelTrainingJob.updated_at))
            .limit(1)
        ).all()
        if not jobs:
            return None
        config = jobs[0].training_config or {}
        return str(config.get("promoted_champion_revision") or config.get("candidate_revision") or "") or None

    def _launcher(self) -> HuggingFaceJobLauncher:
        return HuggingFaceJobLauncher(client=self.api, token=self.token)

    def _require_enabled_and_token(self) -> None:
        if not self.settings.hf_training_enabled:
            raise RuntimeError("BLUM Hugging Face training is disabled")
        if not self.token:
            raise RuntimeError("HF_TOKEN is not configured")

    def _require_admin_key(self, supplied: str) -> None:
        expected = self.settings.hf_training_admin_key
        if not expected or not hmac.compare_digest(supplied or "", expected):
            raise PermissionError("Invalid BLUM HF training admin key")


def serialize_training_job(job: BlumModelTrainingJob) -> dict[str, Any]:
    config = dict(job.training_config or {})
    redacted = {key: value for key, value in config.items() if "token" not in key.lower() and "secret" not in key.lower()}
    return {
        "id": job.id,
        "job_name": job.job_name,
        "model_family": job.model_family,
        "base_model": job.base_model,
        "method": job.method,
        "dataset_export_id": job.dataset_export_id,
        "status": job.status,
        "training_config": redacted,
        "metrics": job.metrics or {},
        "created_at": _iso(job.created_at),
        "updated_at": _iso(job.updated_at),
    }


def _dataset_readme(repository: str, snapshot: SnapshotArtifact) -> str:
    counts = snapshot.manifest["split_counts"]
    return f"""---
license: other
task_categories:
- text-generation
language:
- en
- it
pretty_name: BLUM Finance Reasoning
---

# BLUM Finance Reasoning

Immutable, outcome-matured reasoning snapshot generated by the BLUM Space.

- Repository: `{repository}`
- Revision: `{snapshot.revision}`
- Snapshot SHA-256: `{snapshot.snapshot_hash}`
- Train: {counts['train']}
- Validation: {counts['validation']}
- Test: {counts['test']}

The split is grouped by thesis lineage. Records from one lineage never cross splits. See `manifest.json` for provenance and quality-gate metadata.
"""


def _remote_stage(job: Any) -> str:
    return str(getattr(getattr(job, "status", None), "stage", "UNKNOWN")).upper()


def _quality_from_payload(payload: Mapping[str, Any]) -> float:
    for key in ("final_training_value_score", "overall_score", "overall", "quality_score"):
        value = payload.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    numeric = [float(value) for value in payload.values() if isinstance(value, (int, float))]
    return sum(numeric) / len(numeric) if numeric else 0.0


def _merge_safety_flags(target: dict[str, Any], payload: Mapping[str, Any]) -> None:
    for key, value in payload.items():
        normalized = str(key).lower()
        if any(marker in normalized for marker in ("contamin", "quarant", "leakage", "verified", "license", "privacy", "directional_accounting")):
            target[str(key)] = value
        if isinstance(value, Mapping):
            _merge_safety_flags(target, value)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value)
