from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import (
    BackgroundJobState,
    DeterministicExecutionRun,
    ExecutionKernelState,
    ExecutionParityComparison,
    ReplayMarketBar,
)
from app.services.dashboard_snapshots import DashboardSnapshotService
from app.services.deterministic_execution.kernel import kernel_health


SNAPSHOT_TYPE = "deterministic_execution_summary"


class DeterministicExecutionSnapshotService:
    """Compact read model for execution-kernel status and promotion evidence."""

    def build(self, db: Session) -> dict:
        health = kernel_health(mode="shadow")
        state = db.scalar(select(ExecutionKernelState).where(ExecutionKernelState.state_key == "primary").limit(1))
        latest_run = db.scalar(select(DeterministicExecutionRun).order_by(desc(DeterministicExecutionRun.created_at)).limit(1))
        latest_job = db.scalar(
            select(BackgroundJobState)
            .where(BackgroundJobState.job_name == "deterministic_execution_core")
            .order_by(desc(BackgroundJobState.last_started_at))
            .limit(1)
        )
        run_total = int(db.scalar(select(func.count(DeterministicExecutionRun.id))) or 0)
        run_completed = int(
            db.scalar(select(func.count(DeterministicExecutionRun.id)).where(DeterministicExecutionRun.status == "COMPLETED")) or 0
        )
        parity_total = int(db.scalar(select(func.count(ExecutionParityComparison.id))) or 0)
        parity_match = int(
            db.scalar(select(func.count(ExecutionParityComparison.id)).where(ExecutionParityComparison.status == "MATCH")) or 0
        )
        violations = int(
            db.scalar(
                select(func.count(ExecutionParityComparison.id)).where(
                    ExecutionParityComparison.status.in_(("DIVERGED", "INVALID"))
                )
            )
            or 0
        )
        catalog_latest = db.scalar(select(func.max(ReplayMarketBar.bar_timestamp)))
        mode = state.mode if state else "SHADOW"
        blockers = list(state.warnings_json or []) if state else ["minimum_sample_size", "cross_asset_coverage"]
        status = "UNAVAILABLE" if not health.available else "READY" if run_total else "INITIALIZING"
        return {
            "status": status,
            "kernel": {
                "name": "nautilus_trader",
                "version": health.version,
                "available": health.available,
                "reason": health.reason,
            },
            "mode": mode,
            "authoritative_scope": "paper_only" if mode == "AUTHORITATIVE_PAPER" else "none",
            "live_execution": False,
            "runs": {
                "total": run_total,
                "completed": run_completed,
                "failed": run_total - run_completed,
                "latest_at": latest_run.created_at.isoformat() if latest_run and latest_run.created_at else None,
                "latest_status": latest_run.status if latest_run else None,
                "latest_fingerprint": latest_run.reproducibility_fingerprint if latest_run else None,
            },
            "parity": {
                "sample_size": parity_total,
                "matched": parity_match,
                "agreement_rate": parity_match / parity_total if parity_total else 0.0,
                "violations": violations,
                "required_samples": 100,
            },
            "coverage": {
                "asset_classes": list(state.asset_classes_json or []) if state else [],
                "regimes": list(state.regimes_json or []) if state else [],
            },
            "catalog": {
                "latest_bar_at": catalog_latest.isoformat() if catalog_latest else None,
                "cursor": dict(latest_job.cursor_json or {}) if latest_job else {},
            },
            "worker": {
                "status": latest_job.status if latest_job else "not_started",
                "last_started_at": latest_job.last_started_at.isoformat() if latest_job and latest_job.last_started_at else None,
                "last_completed_at": latest_job.last_completed_at.isoformat() if latest_job and latest_job.last_completed_at else None,
                "duration_ms": latest_job.duration_ms if latest_job else None,
                "error": latest_job.error_message if latest_job else "",
            },
            "blockers": blockers,
            "next_action": "Collect terminal cross-asset parity evidence." if blockers else "Continue monitoring paper parity and rollback invariants.",
            "policy": "Shadow evidence only until reversible promotion gates pass; crypto, brokers and real-money execution are excluded.",
        }

    def latest(self, db: Session) -> dict:
        snapshot = DashboardSnapshotService().latest(db, SNAPSHOT_TYPE)
        if snapshot["status"] == "missing":
            return {
                "snapshot_status": "missing",
                "status": "INITIALIZING",
                "mode": "SHADOW",
                "runs": {"total": 0, "completed": 0, "failed": 0},
                "blockers": ["snapshot_not_produced"],
                "policy": "GET is read-only; wait for the background snapshot producer.",
            }
        payload = dict(snapshot.get("payload") or {})
        payload.update(
            {
                "snapshot_status": snapshot["status"],
                "snapshot_created_at": snapshot.get("created_at"),
                "is_stale": snapshot.get("is_stale", False),
                "snapshot_warnings": snapshot.get("warnings") or [],
            }
        )
        return payload
