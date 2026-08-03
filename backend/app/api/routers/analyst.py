from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Header
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.analyst.dataset_pipeline import BlumAnalystDatasetPipeline
from app.analyst.hf_training_runtime import BlumHFTrainingService
from app.core.config import get_settings
from app.core.database import get_db
from app.engine.contracts import PROJECT_FEATURE_SET
from app.engine.facade import BlumEngineFacade
from app.models import BlumDatasetExport
from app.runtime.facade import BlumRuntimeFacade


settings = get_settings()
router = APIRouter(tags=["Analyst"])


@router.get("/analyst/status")
@router.get("/api/analyst/status")
def analyst_status(db: Session = Depends(get_db)) -> dict:
    return BlumAnalystDatasetPipeline().status(db)


@router.post("/api/analyst/release-export")
def create_release_export(
    source_revision: str = Query(..., pattern=r"^[0-9a-f]{40}$"),
    min_score: float = Query(default=70.0, ge=0, le=100),
    limit: int = Query(default=10_000, ge=3, le=25_000),
    db: Session = Depends(get_db),
) -> dict:
    return BlumAnalystDatasetPipeline().export_release(
        db,
        source_revision=source_revision,
        min_score=min_score,
        limit=limit,
    )


@router.get("/api/analyst/release-exports/{export_id}/manifest")
def release_export_manifest(
    export_id: int,
    db: Session = Depends(get_db),
) -> dict:
    row = _release_export_or_404(db, export_id)
    return dict((row.payload_summary or {}).get("manifest") or {})


@router.get("/api/analyst/release-exports/{export_id}/artifact")
def release_export_artifact(
    export_id: int,
    db: Session = Depends(get_db),
) -> FileResponse:
    row = _release_export_or_404(db, export_id)
    payload = row.payload_summary or {}
    if not payload.get("release_safe"):
        raise HTTPException(status_code=403, detail="Only redacted release-safe exports can be downloaded.")
    path = Path(row.file_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Release artifact is no longer available.")
    return FileResponse(
        path,
        media_type="application/gzip",
        filename=row.export_name,
        headers={"X-BLUM-ARTIFACT-SHA256": str(payload.get("archive_sha256") or "")},
    )


def _release_export_or_404(db: Session, export_id: int) -> BlumDatasetExport:
    row = db.get(BlumDatasetExport, export_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown dataset export: {export_id}")
    return row


@router.get("/architecture/contracts")
@router.get("/api/architecture/contracts")
def architecture_contracts() -> dict:
    return {
        "version": settings.app_version,
        "feature_set": PROJECT_FEATURE_SET,
        "engine": BlumEngineFacade().contract(),
        "runtime": BlumRuntimeFacade().contract(),
        "analyst": BlumAnalystDatasetPipeline().contract(),
        "policy": "Engine owns truth, Analyst learns reasoning, Runtime observes and renders.",
    }

@router.get("/analyst/hf-training/status")
@router.get("/api/analyst/hf-training/status")
def hf_training_status(db: Session = Depends(get_db)) -> dict:
    return BlumHFTrainingService().status(db)


@router.get("/analyst/hf-training/local-snapshot")
@router.get("/api/analyst/hf-training/local-snapshot")
def hf_training_local_snapshot() -> dict:
    return BlumHFTrainingService().local_snapshot_status()


@router.get("/analyst/hf-training/local-snapshot/archive")
@router.get("/api/analyst/hf-training/local-snapshot/archive")
def hf_training_local_snapshot_archive() -> FileResponse:
    archive = BlumHFTrainingService().local_snapshot_archive()
    if archive is None:
        raise HTTPException(status_code=404, detail="No local continual-learning snapshot is ready.")
    return FileResponse(
        archive,
        media_type="application/gzip",
        filename=archive.name,
    )


@router.post("/analyst/hf-training/snapshot")
@router.post("/api/analyst/hf-training/snapshot")
def hf_training_snapshot(
    publish: bool = Query(default=False),
    persist_local: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    service = BlumHFTrainingService()
    try:
        if publish and persist_local:
            raise ValueError("publish and persist_local are mutually exclusive")
        if publish:
            return service.publish_snapshot(db)
        if persist_local:
            return service.persist_local_snapshot(db)
        snapshot = service.build_local_snapshot(db)
        return {"status": "dry_run", "revision": snapshot.revision, "manifest": snapshot.manifest}
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/analyst/hf-training/launch")
@router.post("/api/analyst/hf-training/launch")
def hf_training_launch(db: Session = Depends(get_db)) -> dict:
    try:
        return BlumHFTrainingService().launch(db)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/analyst/hf-training/sync")
@router.post("/api/analyst/hf-training/sync")
def hf_training_sync(
    job_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return BlumHFTrainingService().sync(db, job_id=job_id)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/analyst/hf-training/promote/{job_id}")
@router.post("/api/analyst/hf-training/promote/{job_id}")
def hf_training_promote(
    job_id: int,
    admin_key: str = Header(default="", alias="X-BLUM-Admin-Key"),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return BlumHFTrainingService().promote(db, job_id=job_id, supplied_admin_key=admin_key)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/analyst/hf-training/rollback/{job_id}")
@router.post("/api/analyst/hf-training/rollback/{job_id}")
def hf_training_rollback(
    job_id: int,
    backup_tag: str = Query(min_length=1),
    admin_key: str = Header(default="", alias="X-BLUM-Admin-Key"),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return BlumHFTrainingService().rollback(
            db,
            job_id=job_id,
            backup_tag=backup_tag,
            supplied_admin_key=admin_key,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
