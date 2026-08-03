from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.services.deterministic_execution.contracts import ExecutionIntent, InstrumentSpec


@dataclass(frozen=True)
class RiskBridgeDecision:
    allowed: bool
    action: str
    reasons: tuple[str, ...]
    max_notional: float
    requested_notional: float


class BlumNautilusRiskBridge:
    """Combines BLUM authority with native execution constraints; stricter gate wins."""

    def evaluate(
        self,
        spec: InstrumentSpec,
        intent: ExecutionIntent,
        *,
        capital: float,
        runtime_state: str,
        existing_approved: bool,
        fx_rate_available: bool = True,
    ) -> RiskBridgeDecision:
        reasons: list[str] = []
        state = runtime_state.upper()
        notional = intent.quantity * intent.theoretical_price
        leverage = 30.0 if spec.asset_class == "forex" else 1.0
        max_notional = max(0.0, capital) * leverage
        if not existing_approved:
            reasons.append("blum_risk_gate_denied")
        if state in {"HALTED", "QUARANTINED", "FAILED"}:
            reasons.append("runtime_not_open_for_risk")
        if state == "REDUCING" and not intent.reduce_only:
            reasons.append("runtime_reducing_only")
        if not intent.confirmed:
            reasons.append("unconfirmed_intent")
        if notional > max_notional + 1e-9:
            reasons.append("notional_exceeds_capital_limit")
        if spec.quote_currency != "USD" and not fx_rate_available:
            reasons.append("missing_point_in_time_fx")
        if not _aligned(intent.quantity, spec.lot_size):
            reasons.append("quantity_not_aligned_to_lot")
        if not _aligned(intent.theoretical_price, spec.tick_size):
            reasons.append("price_not_aligned_to_tick")
        return RiskBridgeDecision(
            allowed=not reasons,
            action="ALLOW" if not reasons else "DENY",
            reasons=tuple(reasons),
            max_notional=max_notional,
            requested_notional=notional,
        )


def _aligned(value: float, increment: float) -> bool:
    if increment <= 0:
        return False
    ratio = Decimal(str(value)) / Decimal(str(increment))
    return abs(ratio - ratio.to_integral_value()) <= Decimal("0.00000001")

