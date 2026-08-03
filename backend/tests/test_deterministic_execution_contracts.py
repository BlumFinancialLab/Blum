from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta

import pytest

from app.services.deterministic_execution.contracts import (
    ExecutionIntent,
    InstrumentSpec,
    KernelRunRequest,
    MarketEvent,
)
from app.services.deterministic_execution.kernel import kernel_health


NOW = datetime(2026, 8, 3, 9, 30)


def instrument(**overrides) -> InstrumentSpec:
    payload = {
        "instrument_id": "AAPL.NASDAQ",
        "symbol": "AAPL",
        "venue": "NASDAQ",
        "asset_class": "equity",
        "base_currency": None,
        "quote_currency": "USD",
        "price_precision": 2,
        "quantity_precision": 6,
        "tick_size": 0.01,
        "lot_size": 0.000001,
        "account_mode": "cash",
    }
    payload.update(overrides)
    return InstrumentSpec(**payload)


def test_execution_contracts_are_immutable() -> None:
    spec = instrument()

    with pytest.raises(FrozenInstanceError):
        spec.symbol = "MSFT"  # type: ignore[misc]


def test_instrument_rejects_crypto_and_unknown_asset_classes() -> None:
    with pytest.raises(ValueError, match="unsupported asset class"):
        instrument(asset_class="crypto")

    with pytest.raises(ValueError, match="unsupported asset class"):
        instrument(asset_class="option")


def test_run_request_requires_strictly_ordered_point_in_time_events() -> None:
    spec = instrument()
    intent = ExecutionIntent(
        decision_id="decision-1",
        instrument_id=spec.instrument_id,
        side="BUY",
        order_type="LIMIT",
        quantity=1.0,
        decision_timestamp=NOW,
        theoretical_price=100.0,
        limit_price=100.0,
        stop_price=98.0,
        target_price=104.0,
    )
    first = MarketEvent(spec.instrument_id, "bar", NOW + timedelta(minutes=2), 100, 101, 99, 100.5, 10_000)
    second = MarketEvent(spec.instrument_id, "bar", NOW + timedelta(minutes=1), 100, 101, 99, 100.5, 10_000)

    with pytest.raises(ValueError, match="chronological"):
        KernelRunRequest(
            run_id="run-1",
            environment="backtest",
            starting_balances={"USD": 1000.0},
            instruments=(spec,),
            market_events=(first, second),
            execution_intents=(intent,),
            runtime_now=NOW + timedelta(minutes=3),
        )


def test_run_request_rejects_events_after_runtime_clock() -> None:
    spec = instrument()
    future = MarketEvent(spec.instrument_id, "bar", NOW + timedelta(minutes=5), 100, 101, 99, 100.5, 10_000)

    with pytest.raises(ValueError, match="runtime clock"):
        KernelRunRequest(
            run_id="run-2",
            environment="paper",
            starting_balances={"USD": 1000.0},
            instruments=(spec,),
            market_events=(future,),
            execution_intents=(),
            runtime_now=NOW + timedelta(minutes=4),
        )


def test_kernel_health_is_unavailable_when_dependency_loader_fails() -> None:
    health = kernel_health(loader=lambda: (_ for _ in ()).throw(ImportError("missing")))

    assert health.status == "UNAVAILABLE"
    assert health.available is False
    assert health.version is None
    assert "missing" in health.reason
