from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.engine.facade import BlumEngineFacade


router = APIRouter(tags=["Trader Brain"])


@router.get("/trader-brain/brain")
@router.get("/api/trader-brain/brain")
def trader_brain(db: Session = Depends(get_db)) -> dict:
    return BlumEngineFacade().brain_snapshot(db)


@router.get("/api/brain/snapshot")
def brain_snapshot(db: Session = Depends(get_db)) -> dict:
    return BlumEngineFacade().brain_snapshot(db)
