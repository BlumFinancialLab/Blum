from __future__ import annotations

from dataclasses import dataclass

from app.services.deterministic_execution.contracts import KernelRunResult


TERMINAL_ORDER_STATES = {
    "OrderFilled": "FILLED",
    "OrderCanceled": "CANCELED",
    "OrderExpired": "EXPIRED",
    "OrderRejected": "REJECTED",
    "OrderDenied": "DENIED",
}


@dataclass(frozen=True)
class ParityResult:
    status: str
    reasons: tuple[str, ...]
    metrics: tuple[tuple[str, float | bool | None], ...]


class ExecutionParityEvaluator:
    def compare(self, authoritative: dict, shadow: KernelRunResult) -> ParityResult:
        terminal = [event for event in shadow.order_events if event.event_type in TERMINAL_ORDER_STATES]
        if shadow.status != "COMPLETED" or not terminal:
            return ParityResult("INSUFFICIENT_DATA", ("missing_terminal_shadow_event",), ())
        last = terminal[-1]
        native_state = TERMINAL_ORDER_STATES[last.event_type]
        shadow_costs = sum(value for _, value in shadow.costs)
        shadow_pnl = next(
            (event.realized_pnl for event in reversed(shadow.position_events) if event.realized_pnl is not None),
            None,
        )
        metrics = {
            "state_agreement": str(authoritative.get("state", "")).upper() == native_state,
            "quantity_difference": _difference(authoritative.get("quantity"), last.quantity),
            "fill_price_difference": _difference(authoritative.get("fill_price"), last.price),
            "cost_difference": _difference(authoritative.get("costs"), shadow_costs),
            "pnl_difference": _difference(authoritative.get("pnl"), shadow_pnl),
        }
        reasons: list[str] = []
        if not metrics["state_agreement"]:
            reasons.append("state")
        for key in ("quantity_difference", "fill_price_difference", "cost_difference", "pnl_difference"):
            value = metrics[key]
            if value is not None and abs(float(value)) > 1e-8:
                reasons.append(key.removesuffix("_difference"))
        authoritative_exit = str(authoritative.get("exit_reason") or "")
        if authoritative_exit and authoritative_exit != last.reason:
            reasons.append("exit_reason")
        return ParityResult(
            "MATCH" if not reasons else "DIVERGED",
            tuple(reasons),
            tuple(metrics.items()),
        )


def _difference(left, right) -> float | None:
    if left is None and right is None:
        return None
    if left is None or right is None:
        return None
    return float(right) - float(left)

