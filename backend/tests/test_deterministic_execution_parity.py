from datetime import datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import DeterministicExecutionEvent, DeterministicExecutionRun
from app.services.deterministic_execution.contracts import KernelOrderEvent, KernelRunResult
from app.services.deterministic_execution.parity import ExecutionParityEvaluator
from app.services.deterministic_execution.repository import DeterministicExecutionRepository


def _db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def _result() -> KernelRunResult:
    return KernelRunResult(
        run_id="r1",
        status="COMPLETED",
        order_events=(
            KernelOrderEvent("event-1", "order-1", "decision-1", "OrderFilled", datetime(2026, 8, 3), 2, 101.0),
        ),
        costs=(("USD", 0.1),),
        reproducibility_fingerprint="fingerprint-1",
    )


def test_repository_is_append_only_and_idempotent():
    db = _db()
    repository = DeterministicExecutionRepository()
    first = repository.persist_result(db, _result(), environment="backtest", source_object_type="trade", source_object_id="12")
    second = repository.persist_result(db, _result(), environment="backtest", source_object_type="trade", source_object_id="12")

    assert first.id == second.id
    assert len(db.scalars(select(DeterministicExecutionRun)).all()) == 1
    assert len(db.scalars(select(DeterministicExecutionEvent)).all()) == 1


def test_parity_compares_state_quantity_price_costs_and_outcome():
    result = _result()
    matching = {
        "state": "FILLED",
        "quantity": 2,
        "fill_price": 101,
        "costs": 0.1,
        "pnl": None,
        "exit_reason": "",
    }
    assert ExecutionParityEvaluator().compare(matching, result).status == "MATCH"

    divergent = dict(matching, fill_price=102)
    comparison = ExecutionParityEvaluator().compare(divergent, result)
    assert comparison.status == "DIVERGED"
    assert "fill_price" in comparison.reasons


def test_parity_requires_terminal_native_evidence():
    result = KernelRunResult("r2", "COMPLETED", reproducibility_fingerprint="empty")
    comparison = ExecutionParityEvaluator().compare({"state": "FILLED"}, result)
    assert comparison.status == "INSUFFICIENT_DATA"
