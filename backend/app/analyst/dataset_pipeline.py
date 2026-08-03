from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from pathlib import Path
import tarfile

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analyst.contracts import analyst_dataset_contract
from app.analyst.release_dataset import build_release_dataset
from app.core.config import get_settings
from app.models import BlumDatasetExport
from app.services.blum_financial_model import export_training_jsonl, training_manifest
from app.analyst.hf_training_runtime import BlumHFTrainingService


class BlumAnalystDatasetPipeline:
    """Dataset pipeline boundary for the future BLUM Analyst model.

    This service prepares and reports on training data. It intentionally does
    not start fine-tuning, require GPU, or make model outputs authoritative.
    """

    def contract(self) -> dict:
        return analyst_dataset_contract(get_settings().blum_analyst_repository).to_dict()

    def status(self, db: Session) -> dict:
        settings = get_settings()
        manifest = training_manifest()
        manifest["target_repository"] = settings.blum_analyst_repository
        hf_training = BlumHFTrainingService().configuration_status()
        return {
            "status": "ready",
            "contract": self.contract(),
            "training_manifest": manifest,
            "automatic_training_enabled": bool(settings.hf_training_enabled and settings.hf_training_auto_launch),
            "automatic_dataset_snapshots_enabled": settings.hf_dataset_snapshot_enabled,
            "community_memory_policy": "opt_in_pull_request_quarantine",
            "model_repository": settings.hf_training_champion_repository,
            "hf_training": hf_training,
            "policy": "The Space prepares validated snapshots. Fine-tuning and evaluation run only in isolated Hugging Face Jobs; production promotion is manual.",
        }

    def export(self, db: Session, *, limit: int = 1000, min_quality: float = 60.0, export_name: str | None = None) -> dict:
        result = export_training_jsonl(db, limit=limit, min_quality=min_quality, export_name=export_name)
        result["target_model_repository"] = get_settings().blum_analyst_repository
        result["contract"] = self.contract()
        result["policy"] = "Exported dataset is for supervised or preference training review; no training job was started."
        return result

    def export_release(
        self,
        db: Session,
        *,
        source_revision: str,
        min_score: float = 70.0,
        limit: int = 10_000,
    ) -> dict:
        filters = {
            "source_revision": source_revision,
            "min_score": float(min_score),
            "limit": int(limit),
            "release_safe": True,
        }
        existing = db.scalar(
            select(BlumDatasetExport)
            .where(
                BlumDatasetExport.format == "tar.gz",
                BlumDatasetExport.status == "created",
            )
            .order_by(BlumDatasetExport.created_at.desc())
            .limit(1)
        )
        if (
            existing is not None
            and existing.filters == filters
            and Path(existing.file_path).is_file()
        ):
            return self._serialize_release_export(existing, reused=True)

        root = Path(get_settings().training_export_dir) / "blum_finance_release"
        export_key = f"{source_revision[:12]}-{int(min_score)}-{limit}"
        dataset_dir = root / export_key
        dataset_dir.mkdir(parents=True, exist_ok=True)
        manifest = build_release_dataset(
            db,
            source_revision=source_revision,
            output_dir=dataset_dir,
            min_score=min_score,
            limit=limit,
        )
        archive_path = root / f"{export_key}.tar.gz"
        with tarfile.open(archive_path, "w:gz") as archive:
            for path in sorted(dataset_dir.iterdir()):
                if path.is_file():
                    archive.add(path, arcname=path.name)
        archive_sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        payload_manifest = manifest.model_dump(mode="json")
        export = BlumDatasetExport(
            export_name=archive_path.name,
            format="tar.gz",
            record_count=sum(manifest.split_counts.values()),
            file_path=str(archive_path),
            filters=filters,
            status="created",
            payload_summary={
                "release_safe": True,
                "manifest": payload_manifest,
                "archive_sha256": archive_sha256,
                "generated_at": datetime.now(UTC).isoformat(),
                "target_model_repository": get_settings().blum_model_repository,
                "target_dataset_repository": "Italianhype/Blum-Finance-Reasoning",
            },
        )
        db.add(export)
        db.commit()
        return self._serialize_release_export(export, reused=False)

    @staticmethod
    def _serialize_release_export(row: BlumDatasetExport, *, reused: bool) -> dict:
        payload = row.payload_summary or {}
        return {
            "status": "ready",
            "export_id": row.id,
            "export_name": row.export_name,
            "record_count": row.record_count,
            "manifest": payload.get("manifest", {}),
            "archive_sha256": payload.get("archive_sha256"),
            "reused": reused,
            "download_path": f"/api/analyst/release-exports/{row.id}/artifact",
        }
