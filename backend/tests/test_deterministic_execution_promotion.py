from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import DeterministicExecutionRun, ExecutionParityComparison
from app.services.deterministic_execution.contracts import ExecutionIntent
from app.services.deterministic_execution.instruments import BlumInstrumentMapper
from app.services.deterministic_execution.promotion import ExecutionKernelPromotionService
from app.services.deterministic_execution.risk import BlumNautilusRiskBridge
from backend.tests.test_deterministic_execution_catalog import _asset


def _db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_risk_bridge_honors_stricter_gate_and_runtime_halt():
    spec = BlumInstrumentMapper().map_asset(_asset("AAPL", "equity"))
    intent = ExecutionIntent("d", spec.instrument_id, "BUY", "MARKET", 2, datetime(2026, 8, 3), 100)
    bridge = BlumNautilusRiskBridge()

    assert not bridge.evaluate(spec, intent, capital=100, runtime_state="RUNNING", existing_approved=True).allowed
    assert not bridge.evaluate(spec, intent, capital=10_000, runtime_state="HALTED", existing_approved=True).allowed
    assert not bridge.evaluate(spec, intent, capital=10_000, runtime_state="RUNNING", existing_approved=False).allowed


def test_promotion_requires_minimum_cross_asset_evidence():
    db = _db()
    service = ExecutionKernelPromotionService(min_samples=4, min_agreement=0.99)
    run = DeterministicExecutionRun(
        run_uid="r",
        environment="paper",
        status="COMPLETED",
        reproducibility_fingerprint="fp",
        completed_at=datetime.utcnow(),
    )
    db.add(run)
    db.flush()
    for index in range(3):
        db.add(
            ExecutionParityComparison(
                run_id=run.id,
                source_object_type="trade",
                source_object_id=str(index),
                asset_class="equity",
                regime="risk_on",
                status="MATCH",
                state_agreement=True,
            )
        )
    db.commit()
    assert service.evaluate(db)["mode"] == "SHADOW"

    db.add(
        ExecutionParityComparison(
            run_id=run.id,
            source_object_type="trade",
            source_object_id="fx",
            asset_class="forex",
            regime="range",
            status="MATCH",
            state_agreement=True,
        )
    )
    db.commit()
    assert service.evaluate(db)["mode"] == "AUTHORITATIVE_PAPER"


def test_divergence_rolls_authoritative_mode_back_to_shadow():
    db = _db()
    service = ExecutionKernelPromotionService(min_samples=1, min_agreement=0.0)
    state = service.state(db)
    state.mode = "AUTHORITATIVE_PAPER"
    db.commit()

    result = service.rollback(db, "duplicate_fill_invariant")
    assert result["mode"] == "SHADOW"
    assert result["rollback_reason"] == "duplicate_fill_invariant"
