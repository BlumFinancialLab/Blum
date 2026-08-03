from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DeterministicExecutionEvent, DeterministicExecutionRun
from app.services.deterministic_execution.contracts import KernelRunResult


class DeterministicExecutionRepository:
    """Append-only persistence for normalized deterministic execution evidence."""

    def persist_result(
        self,
        db: Session,
        result: KernelRunResult,
        *,
        environment: str,
        source_object_type: str | None = None,
        source_object_id: str | None = None,
    ) -> DeterministicExecutionRun:
        fingerprint = result.reproducibility_fingerprint or f"{result.run_id}:{result.status}"
        existing = db.scalar(
            select(DeterministicExecutionRun)
            .where(DeterministicExecutionRun.reproducibility_fingerprint == fingerprint)
            .limit(1)
        )
        if existing:
            return existing
        diagnostics = dict(result.diagnostics)
        row = DeterministicExecutionRun(
            run_uid=result.run_id,
            environment=environment,
            kernel_version=diagnostics.get("native_version"),
            status=result.status,
            source_object_type=source_object_type,
            source_object_id=source_object_id,
            reproducibility_fingerprint=fingerprint,
            order_event_count=len(result.order_events),
            position_event_count=len(result.position_events),
            costs_json=dict(result.costs),
            diagnostics_json=diagnostics,
            completed_at=datetime.utcnow(),
        )
        db.add(row)
        db.flush()
        for event in (*result.order_events, *result.position_events):
            payload = _json_safe(asdict(event))
            entity_type = "order" if "order_id" in payload else "position"
            entity_id = payload.get("order_id") or payload.get("position_id") or ""
            db.add(
                DeterministicExecutionEvent(
                    run_id=row.id,
                    event_uid=event.event_id,
                    event_type=event.event_type,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    decision_id=payload.get("decision_id"),
                    event_timestamp=event.timestamp,
                    payload_json=payload,
                )
            )
        db.commit()
        db.refresh(row)
        return row


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value

