from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.central_brain_runtime import SnapshotProducerService
from app.services.copy_readiness_evidence import (
    BlumCopyReadinessEngine,
    CopyReadinessQueryService,
    CopyReadinessSummaryService,
    StrategyEvidenceProjector,
)
from app.services.dashboard_snapshots import DashboardSnapshotService


router = APIRouter(prefix="/api/copy-readiness", tags=["Copy Readiness"])


@router.get("/strategies")
def strategies(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    return CopyReadinessQueryService().strategies(db, limit=limit, offset=offset)


@router.get("/strategies/{strategy_id}")
def strategy_detail(strategy_id: str, db: Session = Depends(get_db)) -> dict:
    payload = CopyReadinessQueryService().strategy(db, strategy_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Copy-readiness strategy not found.")
    return payload


@router.get("/strategies/{strategy_id}/timeline")
def strategy_timeline(
    strategy_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    return CopyReadinessQueryService().timeline(db, strategy_id, limit=limit, offset=offset)


@router.post("/recalculate")
def recalculate(
    max_items: int = Query(default=500, ge=1, le=500),
    max_strategies: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    """Run bounded evidence projection and refresh compact read snapshots."""

    try:
        projection = StrategyEvidenceProjector().project(db, max_items=max_items)
        readiness = BlumCopyReadinessEngine().recalculate(db, max_strategies=max_strategies)
        summary = CopyReadinessSummaryService().summary(db)
        DashboardSnapshotService().write(
            db,
            "copy_readiness_summary",
            summary,
            source_modules={"producer": "copy_readiness_recalculate", "mode": "bounded_manual_command"},
            ttl_seconds=900,
        )
        snapshots = SnapshotProducerService().produce_many(
            db,
            ["paper_forward_snapshot", "trader_alpha_summary"],
            max_items=2,
        )
        db.commit()
        return {
            "status": "completed",
            "projection": projection,
            "readiness": readiness,
            "summary": summary,
            "snapshots": snapshots,
        }
    except Exception:
        db.rollback()
        raise

