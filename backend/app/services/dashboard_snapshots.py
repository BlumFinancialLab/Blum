from __future__ import annotations

from datetime import datetime, timedelta
import time

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import DashboardSnapshot


class DashboardSnapshotService:
    """Small stale-safe snapshot store for dashboard loading surfaces."""

    def latest(self, db: Session, snapshot_type: str) -> dict:
        row = db.scalar(
            select(DashboardSnapshot)
            .where(DashboardSnapshot.snapshot_type == snapshot_type)
            .order_by(desc(DashboardSnapshot.created_at))
            .limit(1)
        )
        if row is None:
            return {
                "status": "missing",
                "snapshot_type": snapshot_type,
                "payload": None,
                "warning": "No dashboard snapshot has been written yet.",
            }
        now = datetime.utcnow()
        is_stale = bool(row.is_stale or (row.expires_at is not None and row.expires_at < now))
        return {
            "status": "stale" if is_stale else "ready",
            "snapshot_type": row.snapshot_type,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "is_stale": is_stale,
            "payload": row.payload_json or {},
            "source_modules": row.source_modules_json or {},
            "computation_duration_ms": row.computation_duration_ms,
            "warnings": row.warnings_json or [],
        }

    def write(
        self,
        db: Session,
        snapshot_type: str,
        payload: dict,
        *,
        source_modules: dict | None = None,
        ttl_seconds: int = 300,
        warnings: list[str] | None = None,
        computation_duration_ms: float | None = None,
    ) -> dict:
        started = time.perf_counter()
        row = DashboardSnapshot(
            snapshot_type=snapshot_type,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(seconds=max(1, ttl_seconds)),
            payload_json=payload,
            source_modules_json=source_modules or {},
            is_stale=False,
            computation_duration_ms=computation_duration_ms,
            warnings_json=warnings or [],
        )
        if row.computation_duration_ms is None:
            row.computation_duration_ms = round((time.perf_counter() - started) * 1000, 3)
        db.add(row)
        db.commit()
        return self.latest(db, snapshot_type)
