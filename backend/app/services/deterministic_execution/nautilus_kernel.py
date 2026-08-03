from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.core.config import get_settings
from app.services.deterministic_execution.contracts import (
    ExecutionIntent,
    InstrumentSpec,
    KernelHealth,
    KernelRunRequest,
    KernelRunResult,
    MarketEvent,
)
from app.services.deterministic_execution.kernel import kernel_health
from app.services.deterministic_execution.normalization import (
    normalize_native_events,
    parse_commissions,
    reproducibility_fingerprint,
)


def _ns(value: datetime) -> int:
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return int(aware.timestamp() * 1_000_000_000)


def _fixed(value: float, precision: int) -> str:
    return f"{float(value):.{precision}f}"


def to_nautilus_instrument(spec: InstrumentSpec, timestamp: datetime):
    from nautilus_trader.model.currencies import Currency
    from nautilus_trader.model.identifiers import InstrumentId, Symbol
    from nautilus_trader.model.instruments import CurrencyPair, Equity
    from nautilus_trader.model.objects import Price, Quantity

    instrument_id = InstrumentId.from_str(spec.instrument_id)
    ts = _ns(timestamp)
    maker_fee = Decimal("0.0001")
    taker_fee = Decimal("0.0005")
    if spec.asset_class == "forex":
        return CurrencyPair(
            instrument_id=instrument_id,
            raw_symbol=Symbol(spec.symbol),
            base_currency=Currency.from_str(str(spec.base_currency)),
            quote_currency=Currency.from_str(spec.quote_currency),
            price_precision=spec.price_precision,
            size_precision=spec.quantity_precision,
            price_increment=Price.from_str(_fixed(spec.tick_size, spec.price_precision)),
            size_increment=Quantity.from_str(_fixed(1, spec.quantity_precision)),
            lot_size=Quantity.from_str(_fixed(spec.lot_size, spec.quantity_precision)),
            ts_event=ts,
            ts_init=ts,
            margin_init=Decimal("0.02"),
            margin_maint=Decimal("0.01"),
            maker_fee=maker_fee,
            taker_fee=taker_fee,
        )
    return Equity(
        instrument_id=instrument_id,
        raw_symbol=Symbol(spec.symbol),
        currency=Currency.from_str(spec.quote_currency),
        price_precision=spec.price_precision,
        price_increment=Price.from_str(_fixed(spec.tick_size, spec.price_precision)),
        lot_size=Quantity.from_str("1"),
        ts_event=ts,
        ts_init=ts,
        maker_fee=maker_fee,
        taker_fee=taker_fee,
    )


def to_nautilus_bars(spec: InstrumentSpec, events: tuple[MarketEvent, ...]) -> list:
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.model.objects import Price, Quantity

    bars = []
    for event in events:
        bar_type = BarType.from_str(_bar_type(spec.instrument_id, event.timeframe))
        timestamp = _ns(event.timestamp)
        quantity_precision = _native_quantity_precision(spec)
        volume = max(event.volume, 10 ** -quantity_precision)
        bars.append(
            Bar(
                bar_type=bar_type,
                open=Price.from_str(_fixed(event.open, spec.price_precision)),
                high=Price.from_str(_fixed(event.high, spec.price_precision)),
                low=Price.from_str(_fixed(event.low, spec.price_precision)),
                close=Price.from_str(_fixed(event.close, spec.price_precision)),
                volume=Quantity.from_str(_fixed(volume, quantity_precision)),
                ts_event=timestamp,
                ts_init=timestamp,
            )
        )
    return bars


def _bar_type(instrument_id: str, timeframe: str) -> str:
    normalized = timeframe.strip().lower()
    units = {"m": "MINUTE", "h": "HOUR", "d": "DAY"}
    unit = normalized[-1:] if normalized[-1:] in units else "m"
    step = int(normalized[:-1] or 1) if normalized[:-1].isdigit() else 1
    return f"{instrument_id}-{step}-{units[unit]}-LAST-EXTERNAL"


def _native_quantity_precision(spec: InstrumentSpec) -> int:
    # Nautilus' generic Equity currently models whole-share size precision.
    return spec.quantity_precision if spec.asset_class == "forex" else 0


class NautilusExecutionKernel:
    """Runs frozen BLUM decisions through Nautilus' deterministic matching engine."""

    def health(self) -> KernelHealth:
        return kernel_health(mode=get_settings().blum_nautilus_mode)

    def run_replay(self, request: KernelRunRequest) -> KernelRunResult:
        return self._run(request)

    def run_paper_step(self, request: KernelRunRequest) -> KernelRunResult:
        return self._run(request)

    def _run(self, request: KernelRunRequest) -> KernelRunResult:
        if any(intent.decision_timestamp > request.runtime_now for intent in request.execution_intents):
            return KernelRunResult(
                run_id=request.run_id,
                status="INVALID",
                diagnostics=(("reason", "decision_timestamp_after_runtime_clock"),),
            )
        health = self.health()
        if not health.available:
            return KernelRunResult(request.run_id, "UNAVAILABLE", diagnostics=(("reason", health.reason),))

        engine = None
        try:
            engine, strategies, venues = self._build_engine(request)
            engine.run()
            captured: list[object] = []
            decision_by_order: dict[str, str] = {}
            for strategy in strategies:
                captured.extend(strategy.captured_events)
                decision_by_order.update(strategy.decision_by_order)
            order_events, position_events = normalize_native_events(captured, decision_by_order)
            fill_rows = engine.trader.generate_order_fills_report().to_dict("records")
            costs = parse_commissions(fill_rows)
            return KernelRunResult(
                run_id=request.run_id,
                status="COMPLETED",
                order_events=order_events,
                position_events=position_events,
                costs=costs,
                reproducibility_fingerprint=reproducibility_fingerprint(order_events, position_events, costs),
                diagnostics=(("native_version", health.version or "unknown"), ("mode", health.mode)),
            )
        except Exception as exc:
            return KernelRunResult(
                request.run_id,
                "FAILED",
                diagnostics=(("reason", f"{type(exc).__name__}: {exc}"),),
            )
        finally:
            if engine is not None:
                engine.dispose()

    def _build_engine(self, request: KernelRunRequest):
        from nautilus_trader.backtest.config import BacktestEngineConfig
        from nautilus_trader.backtest.engine import BacktestEngine
        from nautilus_trader.backtest.models import FillModel
        from nautilus_trader.common.config import LoggingConfig
        from nautilus_trader.model.currencies import Currency
        from nautilus_trader.model.enums import AccountType, OmsType
        from nautilus_trader.model.identifiers import TraderId, Venue
        from nautilus_trader.model.objects import Money

        engine = BacktestEngine(
            BacktestEngineConfig(
                trader_id=TraderId("BLUM-001"),
                run_analysis=False,
                logging=LoggingConfig(bypass_logging=True),
            )
        )
        specs = {item.instrument_id: item for item in request.instruments}
        events_by_instrument: dict[str, list[MarketEvent]] = {}
        for event in request.market_events:
            events_by_instrument.setdefault(event.instrument_id, []).append(event)
        venues: dict[str, Any] = {}
        for spec in request.instruments:
            venue = venues.get(spec.venue)
            if venue is None:
                venue = Venue(spec.venue)
                currencies = {spec.quote_currency}
                starting = [
                    Money(float(request.starting_balances.get(currency, 0.0)), Currency.from_str(currency))
                    for currency in sorted(currencies)
                ]
                engine.add_venue(
                    venue=venue,
                    oms_type=OmsType.NETTING,
                    account_type=AccountType.MARGIN if spec.account_mode == "margin" else AccountType.CASH,
                    starting_balances=starting,
                    base_currency=Currency.from_str(spec.quote_currency),
                    default_leverage=Decimal("30") if spec.account_mode == "margin" else None,
                    fill_model=FillModel(prob_fill_on_limit=1.0, prob_slippage=0.0, random_seed=request.deterministic_seed),
                    bar_adaptive_high_low_ordering=True,
                    liquidity_consumption=True,
                    use_reduce_only=False,
                )
                venues[spec.venue] = venue
            first_timestamp = events_by_instrument[spec.instrument_id][0].timestamp
            engine.add_instrument(to_nautilus_instrument(spec, first_timestamp))
        all_bars = []
        for instrument_id, events in events_by_instrument.items():
            all_bars.extend(to_nautilus_bars(specs[instrument_id], tuple(events)))
        if not all_bars:
            raise ValueError("no market events supplied")
        engine.add_data(all_bars, sort=True)

        strategies = []
        for spec in request.instruments:
            intents = tuple(item for item in request.execution_intents if item.instrument_id == spec.instrument_id)
            timeframes = tuple(
                sorted({item.timeframe for item in events_by_instrument.get(spec.instrument_id, ())})
            )
            strategy = _FrozenIntentStrategy(spec, intents, timeframes)
            engine.add_strategy(strategy)
            strategies.append(strategy)
        return engine, strategies, venues


def _build_order(strategy, spec: InstrumentSpec, intent: ExecutionIntent):
    from nautilus_trader.model.enums import OrderSide, OrderType, TimeInForce
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.model.objects import Price, Quantity

    instrument_id = InstrumentId.from_str(spec.instrument_id)
    side = OrderSide.BUY if intent.side.upper() == "BUY" else OrderSide.SELL
    quantity = Quantity.from_str(_fixed(intent.quantity, _native_quantity_precision(spec)))
    tif = getattr(TimeInForce, intent.time_in_force.upper(), TimeInForce.GTC)
    tags = [f"BLUM:{intent.decision_id}"]
    price = lambda value: Price.from_str(_fixed(float(value), spec.price_precision))
    order_type = intent.order_type.upper()
    if intent.stop_price and intent.target_price and order_type in {"MARKET", "LIMIT"}:
        return strategy.order_factory.bracket(
            instrument_id=instrument_id,
            order_side=side,
            quantity=quantity,
            entry_order_type=OrderType.MARKET if order_type == "MARKET" else OrderType.LIMIT,
            entry_price=price(intent.limit_price) if intent.limit_price else None,
            time_in_force=tif,
            tp_price=price(intent.target_price),
            sl_trigger_price=price(intent.stop_price),
            entry_tags=tags,
            tp_tags=tags,
            sl_tags=tags,
        )
    if order_type == "MARKET":
        return strategy.order_factory.market(instrument_id, side, quantity, time_in_force=tif, tags=tags)
    if order_type == "LIMIT":
        return strategy.order_factory.limit(instrument_id, side, quantity, price(intent.limit_price), time_in_force=tif, tags=tags)
    if order_type == "STOP":
        return strategy.order_factory.stop_market(instrument_id, side, quantity, price(intent.stop_price), time_in_force=tif, tags=tags)
    return strategy.order_factory.stop_limit(
        instrument_id,
        side,
        quantity,
        price(intent.limit_price),
        price(intent.stop_price),
        time_in_force=tif,
        tags=tags,
    )


def _orders(value: object) -> tuple:
    orders = getattr(value, "orders", None)
    return tuple(orders) if orders is not None else (value,)


def _event_datetime_ns(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1_000_000_000, tz=timezone.utc).replace(tzinfo=None)


def _strategy_base():
    from nautilus_trader.trading.strategy import Strategy

    return Strategy


class _FrozenIntentStrategy(_strategy_base()):
    def __init__(
        self,
        spec: InstrumentSpec,
        intents: tuple[ExecutionIntent, ...],
        timeframes: tuple[str, ...],
    ) -> None:
        super().__init__()
        self.spec = spec
        self.intents = tuple(sorted(intents, key=lambda item: item.decision_timestamp))
        self.timeframes = timeframes
        self.submitted: set[str] = set()
        self.captured_events: list[object] = []
        self.decision_by_order: dict[str, str] = {}

    def on_start(self) -> None:
        from nautilus_trader.model.data import BarType

        for timeframe in self.timeframes:
            self.subscribe_bars(BarType.from_str(_bar_type(self.spec.instrument_id, timeframe)))

    def on_bar(self, bar) -> None:
        timestamp = _event_datetime_ns(bar.ts_event)
        for intent in self.intents:
            if not intent.confirmed or intent.decision_id in self.submitted:
                continue
            if intent.decision_timestamp > timestamp:
                continue
            if intent.expires_at and timestamp > intent.expires_at:
                self.submitted.add(intent.decision_id)
                continue
            order_or_list = _build_order(self, self.spec, intent)
            for order in _orders(order_or_list):
                self.decision_by_order[str(order.client_order_id)] = intent.decision_id
            if hasattr(order_or_list, "orders"):
                self.submit_order_list(order_or_list)
            else:
                self.submit_order(order_or_list)
            self.submitted.add(intent.decision_id)

    def on_event(self, event) -> None:
        self.captured_events.append(event)
