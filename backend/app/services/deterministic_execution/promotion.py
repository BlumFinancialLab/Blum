from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ExecutionKernelState, ExecutionParityComparison


class ExecutionKernelPromotionService:
    """Evidence gate for reversible shadow-to-authoritative-paper promotion."""

    def __init__(self, *, min_samples: int | None = None, min_agreement: float = 0.99) -> None:
        settings = get_settings()
        self.min_samples = min_samples if min_samples is not None else settings.blum_nautilus_min_parity_samples
        self.min_agreement = min_agreement
        self.auto_promote = settings.blum_nautilus_authoritative_auto_promote

    def state(self, db: Session) -> ExecutionKernelState:
        row = db.scalar(select(ExecutionKernelState).where(ExecutionKernelState.state_key == "primary").limit(1))
        if row is None:
            row = ExecutionKernelState(state_key="primary", mode="SHADOW")
            db.add(row)
            db.commit()
            db.refresh(row)
        return row

    def evaluate(self, db: Session) -> dict:
        state = self.state(db)
        rows = db.scalars(select(ExecutionParityComparison).order_by(ExecutionParityComparison.id)).all()
        terminal = [row for row in rows if row.status in {"MATCH", "DIVERGED"}]
        invalid = [row for row in rows if row.status == "INVALID"]
        if invalid and state.mode == "AUTHORITATIVE_PAPER":
            return self.rollback(db, "invalid_parity_evidence")
        sample_size = len(terminal)
        matched = sum(row.status == "MATCH" for row in terminal)
        agreement = matched / sample_size if sample_size else 0.0
        asset_classes = sorted({str(row.asset_class) for row in terminal if row.asset_class})
        regimes = sorted({str(row.regime) for row in terminal if row.regime})
        blockers: list[str] = []
        if sample_size < self.min_samples:
            blockers.append("minimum_sample_size")
        if agreement < self.min_agreement:
            blockers.append("state_agreement")
        if not ({"equity", "etf"} & set(asset_classes)) or "forex" not in asset_classes:
            blockers.append("cross_asset_coverage")
        if len(regimes) < 2:
            blockers.append("regime_coverage")
        state.sample_size = sample_size
        state.matched_samples = matched
        state.state_agreement_rate = agreement
        state.asset_classes_json = asset_classes
        state.regimes_json = regimes
        state.warnings_json = blockers
        if not blockers and self.auto_promote and state.mode == "SHADOW":
            state.previous_mode = state.mode
            state.mode = "AUTHORITATIVE_PAPER"
            state.promoted_at = datetime.utcnow()
        db.commit()
        return self._payload(state)

    def rollback(self, db: Session, reason: str) -> dict:
        state = self.state(db)
        state.previous_mode = state.mode
        state.mode = "SHADOW"
        state.rollback_reason = reason
        state.quarantined_at = datetime.utcnow()
        warnings = list(state.warnings_json or [])
        if reason not in warnings:
            warnings.append(reason)
        state.warnings_json = warnings
        db.commit()
        return self._payload(state)

    @staticmethod
    def _payload(state: ExecutionKernelState) -> dict:
        return {
            "mode": state.mode,
            "previous_mode": state.previous_mode,
            "sample_size": state.sample_size,
            "matched_samples": state.matched_samples,
            "state_agreement_rate": state.state_agreement_rate,
            "asset_classes": state.asset_classes_json or [],
            "regimes": state.regimes_json or [],
            "warnings": state.warnings_json or [],
            "rollback_reason": state.rollback_reason,
            "live_execution": False,
        }
