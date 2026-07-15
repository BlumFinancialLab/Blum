from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from typing import Sequence


@dataclass(frozen=True)
class ExecutionOrderRequest:
    order_key: str
    ticker: str
    side: str
    order_type: str
    decision_timestamp: datetime
    theoretical_price: float
    quantity: float
    limit_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    max_participation_rate: float = 0.05
    commission_bps: float = 0.0
    latency_bars: int = 0
    currency: str = "USD"
    account_currency: str = "USD"
    fx_rate: float | None = 1.0


@dataclass(frozen=True)
class ExecutionMarketBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    spread_bps: float
    volatility_bps: float
    session: str = "regular"
    is_halted: bool = False


@dataclass(frozen=True)
class ExecutionFill:
    timestamp: datetime
    quantity: float
    reference_price: float
    executed_price: float
    spread_bps: float
    slippage_bps: float
    commission_bps: float
    participation_rate: float


@dataclass(frozen=True)
class ExecutionCostBreakdown:
    spread_cost: float = 0.0
    slippage_cost: float = 0.0
    commission_cost: float = 0.0
    fx_cost: float = 0.0
    borrow_cost: float = 0.0
    gap_cost: float = 0.0

    @property
    def total_cost(self) -> float:
        return round(self.spread_cost + self.slippage_cost + self.commission_cost + self.fx_cost + self.borrow_cost + self.gap_cost, 8)


@dataclass(frozen=True)
class ExecutionDecision:
    status: str
    reason: str
    theoretical_price: float
    average_fill_price: float | None
    filled_quantity: float
    remaining_quantity: float
    fills: tuple[ExecutionFill, ...]
    costs: ExecutionCostBreakdown


class RealisticExecutionEngine:
    def evaluate(self, request: ExecutionOrderRequest, bars: Sequence[ExecutionMarketBar]) -> ExecutionDecision:
        if request.quantity <= 0 or request.theoretical_price <= 0:
            return self._empty(request, "REJECTED", "INVALID_ORDER")
        if request.currency != request.account_currency and (request.fx_rate is None or request.fx_rate <= 0):
            return self._empty(request, "REJECTED", "FX_RATE_UNAVAILABLE")
        eligible = [bar for bar in sorted(bars, key=lambda item: item.timestamp) if bar.timestamp > request.decision_timestamp and not bar.is_halted]
        latency = max(0, int(request.latency_bars))
        eligible = eligible[latency:]
        if not eligible:
            return self._empty(request, "SUBMITTED", "NO_LATER_EXECUTABLE_BAR")

        remaining = float(request.quantity)
        fills: list[ExecutionFill] = []
        for market_bar in eligible:
            if remaining <= 1e-9:
                break
            if not self._is_triggered(request, market_bar):
                continue
            capacity = max(0.0, float(market_bar.volume)) * max(0.0, min(0.25, float(request.max_participation_rate)))
            quantity = min(remaining, capacity)
            if quantity <= 0:
                continue
            participation = quantity / max(1.0, float(market_bar.volume))
            slippage_bps = self.dynamic_slippage_bps(market_bar.volatility_bps, participation)
            reference = self._reference_price(request, market_bar)
            adverse_bps = max(0.0, float(market_bar.spread_bps)) / 2.0 + slippage_bps
            direction = 1.0 if request.side.upper() == "BUY" else -1.0
            executed = reference * (1.0 + direction * adverse_bps / 10_000.0)
            if request.order_type.upper() == "LIMIT" and request.limit_price is not None:
                executed = min(executed, request.limit_price) if direction > 0 else max(executed, request.limit_price)
            fills.append(
                ExecutionFill(
                    timestamp=market_bar.timestamp,
                    quantity=round(quantity, 8),
                    reference_price=round(reference, 8),
                    executed_price=round(executed, 8),
                    spread_bps=round(float(market_bar.spread_bps), 8),
                    slippage_bps=round(slippage_bps, 8),
                    commission_bps=round(max(0.0, request.commission_bps), 8),
                    participation_rate=round(participation, 8),
                )
            )
            remaining -= quantity

        if not fills:
            return self._empty(request, "SUBMITTED", "ORDER_NOT_FILLED")
        filled = sum(fill.quantity for fill in fills)
        average = sum(fill.executed_price * fill.quantity for fill in fills) / filled
        costs = self._costs(fills, request)
        status = "FILLED" if remaining <= 1e-9 else "PARTIALLY_FILLED"
        return ExecutionDecision(status, status, request.theoretical_price, round(average, 8), round(filled, 8), round(max(0.0, remaining), 8), tuple(fills), costs)

    def evaluate_exit(
        self,
        *,
        side: str,
        quantity: float,
        entry_price: float,
        stop_price: float,
        target_price: float,
        decision_timestamp: datetime,
        bars: Sequence[ExecutionMarketBar],
        commission_bps: float = 0.0,
    ) -> ExecutionDecision:
        for market_bar in sorted(bars, key=lambda item: item.timestamp):
            if market_bar.timestamp <= decision_timestamp or market_bar.is_halted:
                continue
            is_long = side.upper() == "LONG"
            stop_hit = market_bar.low <= stop_price if is_long else market_bar.high >= stop_price
            target_hit = market_bar.high >= target_price if is_long else market_bar.low <= target_price
            if not stop_hit and not target_hit:
                continue
            reason = "STOP_HIT" if stop_hit else "TARGET_HIT"
            trigger = stop_price if stop_hit else target_price
            if stop_hit and ((is_long and market_bar.open < stop_price) or (not is_long and market_bar.open > stop_price)):
                trigger = market_bar.open
            exit_side = "SELL" if is_long else "BUY"
            request = ExecutionOrderRequest(
                order_key=f"exit:{decision_timestamp.isoformat()}",
                ticker="position",
                side=exit_side,
                order_type="MARKET",
                decision_timestamp=decision_timestamp,
                theoretical_price=trigger,
                quantity=quantity,
                max_participation_rate=1.0,
                commission_bps=commission_bps,
            )
            reference = float(trigger)
            participation = min(1.0, quantity / max(1.0, market_bar.volume))
            slippage = self.dynamic_slippage_bps(market_bar.volatility_bps, participation)
            adverse = market_bar.spread_bps / 2.0 + slippage
            direction = 1.0 if exit_side == "BUY" else -1.0
            executed = reference * (1.0 + direction * adverse / 10_000.0)
            fill = ExecutionFill(market_bar.timestamp, quantity, reference, executed, market_bar.spread_bps, slippage, commission_bps, participation)
            return ExecutionDecision("CLOSED", reason, entry_price, round(executed, 8), quantity, 0.0, (fill,), self._costs([fill], request))
        request = ExecutionOrderRequest("exit", "position", "SELL", "MARKET", decision_timestamp, entry_price, quantity)
        return self._empty(request, "OPEN", "NO_EXIT_TRIGGER")

    @staticmethod
    def dynamic_slippage_bps(volatility_bps: float, participation_rate: float) -> float:
        participation = max(0.0, min(1.0, float(participation_rate)))
        return round(max(0.25, max(0.0, float(volatility_bps)) * sqrt(participation) * 0.12 + participation * 8.0), 8)

    @staticmethod
    def _is_triggered(request: ExecutionOrderRequest, market_bar: ExecutionMarketBar) -> bool:
        order_type = request.order_type.upper()
        if order_type == "MARKET":
            return True
        if order_type == "LIMIT" and request.limit_price is not None:
            return market_bar.low <= request.limit_price if request.side.upper() == "BUY" else market_bar.high >= request.limit_price
        if order_type in {"STOP", "STOP_LIMIT"} and request.stop_price is not None:
            return market_bar.high >= request.stop_price if request.side.upper() == "BUY" else market_bar.low <= request.stop_price
        return False

    @staticmethod
    def _reference_price(request: ExecutionOrderRequest, market_bar: ExecutionMarketBar) -> float:
        order_type = request.order_type.upper()
        if order_type == "MARKET":
            return float(market_bar.open)
        if order_type == "LIMIT" and request.limit_price is not None:
            if request.side.upper() == "BUY":
                return min(float(request.limit_price), float(market_bar.open))
            return max(float(request.limit_price), float(market_bar.open))
        return float(request.stop_price or market_bar.open)

    @staticmethod
    def _costs(fills: Sequence[ExecutionFill], request: ExecutionOrderRequest) -> ExecutionCostBreakdown:
        spread = slippage = commission = 0.0
        fx_rate = float(request.fx_rate or 1.0)
        for fill in fills:
            notional = abs(fill.executed_price * fill.quantity) / fx_rate
            spread += notional * fill.spread_bps / 20_000.0
            slippage += notional * fill.slippage_bps / 10_000.0
            commission += notional * fill.commission_bps / 10_000.0
        return ExecutionCostBreakdown(round(spread, 8), round(slippage, 8), round(commission, 8))

    @staticmethod
    def _empty(request: ExecutionOrderRequest, status: str, reason: str) -> ExecutionDecision:
        return ExecutionDecision(status, reason, request.theoretical_price, None, 0.0, max(0.0, request.quantity), (), ExecutionCostBreakdown())

