from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


ALLOWED_ASSET_CLASSES = frozenset({"equity", "etf", "forex"})
ALLOWED_ENVIRONMENTS = frozenset({"backtest", "walk_forward", "paper"})


@dataclass(frozen=True)
class InstrumentSpec:
    instrument_id: str
    symbol: str
    venue: str
    asset_class: str
    base_currency: str | None
    quote_currency: str
    price_precision: int
    quantity_precision: int
    tick_size: float
    lot_size: float
    account_mode: str

    def __post_init__(self) -> None:
        asset_class = self.asset_class.lower()
        if asset_class not in ALLOWED_ASSET_CLASSES:
            raise ValueError(f"unsupported asset class: {self.asset_class}")
        if not self.instrument_id or not self.symbol or not self.venue:
            raise ValueError("instrument identity is required")
        if self.tick_size <= 0 or self.lot_size <= 0:
            raise ValueError("tick and lot sizes must be positive")
        if self.price_precision < 0 or self.quantity_precision < 0:
            raise ValueError("instrument precision cannot be negative")
        if asset_class == "forex" and not self.base_currency:
            raise ValueError("Forex instruments require a base currency")


@dataclass(frozen=True)
class MarketEvent:
    instrument_id: str
    event_type: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    bid: float | None = None
    ask: float | None = None
    source: str = "blum"
    acquired_at: datetime | None = None
    timeframe: str = "1m"

    def __post_init__(self) -> None:
        if self.event_type not in {"bar", "quote", "trade"}:
            raise ValueError(f"unsupported market event: {self.event_type}")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("market prices must be positive")
        if self.low > self.high:
            raise ValueError("market low cannot exceed high")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("market OHLC geometry is invalid")
        if self.volume < 0:
            raise ValueError("market volume cannot be negative")


@dataclass(frozen=True)
class ExecutionIntent:
    decision_id: str
    instrument_id: str
    side: str
    order_type: str
    quantity: float
    decision_timestamp: datetime
    theoretical_price: float
    limit_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    target_2_price: float | None = None
    trailing_offset: float | None = None
    time_in_force: str = "GTC"
    expires_at: datetime | None = None
    confirmed: bool = True
    reduce_only: bool = False
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.side.upper() not in {"BUY", "SELL", "SHORT", "SELL_SHORT"}:
            raise ValueError(f"unsupported order side: {self.side}")
        if self.order_type.upper() not in {"MARKET", "LIMIT", "STOP", "STOP_LIMIT"}:
            raise ValueError(f"unsupported order type: {self.order_type}")
        if self.quantity <= 0 or self.theoretical_price <= 0:
            raise ValueError("quantity and theoretical price must be positive")
        if self.expires_at is not None and self.expires_at <= self.decision_timestamp:
            raise ValueError("order expiry must follow the decision")


@dataclass(frozen=True)
class KernelRunRequest:
    run_id: str
    environment: str
    starting_balances: dict[str, float]
    instruments: tuple[InstrumentSpec, ...]
    market_events: tuple[MarketEvent, ...]
    execution_intents: tuple[ExecutionIntent, ...]
    runtime_now: datetime
    deterministic_seed: int = 7

    def __post_init__(self) -> None:
        if self.environment not in ALLOWED_ENVIRONMENTS:
            raise ValueError(f"unsupported execution environment: {self.environment}")
        if any(value < 0 for value in self.starting_balances.values()):
            raise ValueError("starting balances cannot be negative")
        timestamps = [event.timestamp for event in self.market_events]
        if timestamps != sorted(timestamps):
            raise ValueError("market events must be chronological")
        if any(timestamp > self.runtime_now for timestamp in timestamps):
            raise ValueError("market event exceeds runtime clock")
        instrument_ids = {item.instrument_id for item in self.instruments}
        if any(event.instrument_id not in instrument_ids for event in self.market_events):
            raise ValueError("market event instrument is not registered")
        if any(intent.instrument_id not in instrument_ids for intent in self.execution_intents):
            raise ValueError("execution intent instrument is not registered")


@dataclass(frozen=True)
class KernelOrderEvent:
    event_id: str
    order_id: str
    decision_id: str
    event_type: str
    timestamp: datetime
    quantity: float = 0.0
    price: float | None = None
    reason: str = ""
    payload: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class KernelPositionEvent:
    event_id: str
    position_id: str
    instrument_id: str
    event_type: str
    timestamp: datetime
    quantity: float
    average_price: float | None = None
    realized_pnl: float | None = None


@dataclass(frozen=True)
class KernelRunResult:
    run_id: str
    status: str
    order_events: tuple[KernelOrderEvent, ...] = ()
    position_events: tuple[KernelPositionEvent, ...] = ()
    final_balances: tuple[tuple[str, float], ...] = ()
    costs: tuple[tuple[str, float], ...] = ()
    reproducibility_fingerprint: str = ""
    diagnostics: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class KernelHealth:
    status: str
    available: bool
    version: str | None
    mode: str
    reason: str = ""
    capabilities: tuple[str, ...] = field(default_factory=tuple)


class ExecutionKernel(Protocol):
    def run_replay(self, request: KernelRunRequest) -> KernelRunResult: ...

    def run_paper_step(self, request: KernelRunRequest) -> KernelRunResult: ...

    def health(self) -> KernelHealth: ...
