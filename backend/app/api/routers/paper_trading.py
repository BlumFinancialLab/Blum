from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.engine.facade import BlumEngineFacade


router = APIRouter(tags=["Paper Trading"])


@router.get("/trader-brain/paper-trading")
@router.get("/api/trader-brain/paper-trading")
def paper_trading(
    limit: int = Query(default=20, ge=1, le=80),
    db: Session = Depends(get_db),
) -> dict:
    return BlumEngineFacade().paper_trading_snapshot(db, limit=limit)


@router.get("/api/paper-trading/snapshot")
def paper_trading_snapshot(
    limit: int = Query(default=20, ge=1, le=80),
    db: Session = Depends(get_db),
) -> dict:
    return BlumEngineFacade().paper_trading_snapshot(db, limit=limit)
