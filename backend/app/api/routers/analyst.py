from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.analyst.dataset_pipeline import BlumAnalystDatasetPipeline
from app.core.config import get_settings
from app.core.database import get_db
from app.engine.contracts import PROJECT_FEATURE_SET
from app.engine.facade import BlumEngineFacade
from app.runtime.facade import BlumRuntimeFacade


settings = get_settings()
router = APIRouter(tags=["Analyst"])


@router.get("/analyst/status")
@router.get("/api/analyst/status")
def analyst_status(db: Session = Depends(get_db)) -> dict:
    return BlumAnalystDatasetPipeline().status(db)


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
