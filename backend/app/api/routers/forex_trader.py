from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.forex_trader import BlumForexTradingScheduler, ForexTraderSnapshotService


router = APIRouter(prefix="/api/forex-trader", tags=["Forex Trader"])


@router.get("/snapshot")
def snapshot(db: Session = Depends(get_db)) -> dict:
    return ForexTraderSnapshotService().latest(db)


@router.post("/run-cycle")
def run_cycle(db: Session = Depends(get_db)) -> dict:
    return BlumForexTradingScheduler().run_once(db)


@router.post("/start")
def start(db: Session = Depends(get_db)) -> dict:
    return BlumForexTradingScheduler().start(db)


@router.post("/pause")
def pause(db: Session = Depends(get_db)) -> dict:
    return BlumForexTradingScheduler().pause(db)


@router.post("/resume")
def resume(db: Session = Depends(get_db)) -> dict:
    return BlumForexTradingScheduler().resume(db)


@router.post("/emergency-stop")
def emergency_stop(db: Session = Depends(get_db)) -> dict:
    return BlumForexTradingScheduler().emergency_stop(db)
