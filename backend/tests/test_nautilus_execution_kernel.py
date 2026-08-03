from datetime import datetime, timedelta

from app.services.deterministic_execution.contracts import (
    ExecutionIntent,
    InstrumentSpec,
    KernelRunRequest,
    MarketEvent,
)
from app.services.deterministic_execution.nautilus_kernel import NautilusExecutionKernel


NOW = datetime(2026, 8, 3, 12, 0)


def _instrument() -> InstrumentSpec:
    return InstrumentSpec(
        instrument_id="AAPL.BLUMSIM",
        symbol="AAPL",
        venue="BLUMSIM",
        asset_class="equity",
        base_currency=None,
        quote_currency="USD",
        price_precision=2,
        quantity_precision=4,
        tick_size=0.01,
        lot_size=0.0001,
        account_mode="cash",
    )


def _bars() -> tuple[MarketEvent, ...]:
    values = ((100, 101, 99, 100.5), (100.5, 103, 100, 102), (102, 104, 101, 103))
    return tuple(
        MarketEvent(
            instrument_id="AAPL.BLUMSIM",
            event_type="bar",
            timestamp=NOW + timedelta(minutes=index),
            open=o,
            high=h,
            low=l,
            close=c,
            volume=10_000,
            acquired_at=NOW + timedelta(minutes=index),
        )
        for index, (o, h, l, c) in enumerate(values)
    )


def _request(intent: ExecutionIntent) -> KernelRunRequest:
    return KernelRunRequest(
        run_id="run-1",
        environment="backtest",
        starting_balances={"USD": 10_000},
        instruments=(_instrument(),),
        market_events=_bars(),
        execution_intents=(intent,),
        runtime_now=NOW + timedelta(minutes=2),
    )


def test_market_execution_is_real_and_deterministic():
    intent = ExecutionIntent("d1", "AAPL.BLUMSIM", "BUY", "MARKET", 1, NOW, 100.5)
    kernel = NautilusExecutionKernel()

    first = kernel.run_replay(_request(intent))
    second = kernel.run_replay(_request(intent))

    assert first.status == "COMPLETED"
    assert any(event.event_type == "OrderFilled" for event in first.order_events)
    assert any(event.event_type == "PositionOpened" for event in first.position_events)
    assert first.reproducibility_fingerprint == second.reproducibility_fingerprint


def test_limit_and_stop_orders_use_matching_engine_semantics():
    kernel = NautilusExecutionKernel()
    limit = ExecutionIntent("limit", "AAPL.BLUMSIM", "BUY", "LIMIT", 1, NOW, 100.5, limit_price=100.0)
    stop = ExecutionIntent("stop", "AAPL.BLUMSIM", "BUY", "STOP", 1, NOW, 100.5, stop_price=102.0)

    limit_result = kernel.run_replay(_request(limit))
    stop_result = kernel.run_replay(_request(stop))

    assert any(event.event_type == "OrderFilled" and event.price == 100.0 for event in limit_result.order_events)
    assert any(event.event_type == "OrderFilled" for event in stop_result.order_events)


def test_unconfirmed_intent_never_becomes_an_order():
    intent = ExecutionIntent("d1", "AAPL.BLUMSIM", "BUY", "MARKET", 1, NOW, 100.5, confirmed=False)
    result = NautilusExecutionKernel().run_replay(_request(intent))
    assert result.status == "COMPLETED"
    assert result.order_events == ()


def test_runtime_clock_rejects_future_intent():
    intent = ExecutionIntent(
        "future",
        "AAPL.BLUMSIM",
        "BUY",
        "MARKET",
        1,
        NOW + timedelta(minutes=3),
        103,
    )
    result = NautilusExecutionKernel().run_replay(_request(intent))
    assert result.status == "INVALID"
    assert dict(result.diagnostics)["reason"] == "decision_timestamp_after_runtime_clock"
