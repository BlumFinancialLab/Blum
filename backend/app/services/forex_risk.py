from __future__ import annotations

from dataclasses import dataclass

from app.services.forex_broker import ForexBrokerProfile
from app.services.forex_contracts import ForexTradeProposal, pair_config
from app.core.config import get_settings


@dataclass(frozen=True)
class ForexPortfolioState:
    equity: float
    daily_realized_pnl: float = 0.0
    open_positions: tuple[dict, ...] = ()
    used_margin: float = 0.0
    drawdown_percent: float = 0.0
    pair_correlations: dict[str, float] | None = None


@dataclass(frozen=True)
class ForexRiskDecision:
    decision: str
    quantity_lots: float
    risk_amount: float
    risk_percent: float
    margin_required: float
    exposure_by_currency: dict[str, float]
    blockers: tuple[str, ...]
    explanation: str


class BlumForexPortfolioRiskEngine:
    risk_per_trade_percent = 0.5
    daily_loss_limit_percent = 2.0
    max_open_positions = 4
    max_currency_exposure_multiple = 3.0

    def __init__(self) -> None:
        settings = get_settings()
        self.risk_per_trade_percent = min(0.5, max(0.05, float(settings.forex_risk_per_trade_percent)))
        self.daily_loss_limit_percent = min(2.0, max(0.25, float(settings.forex_daily_loss_limit_percent)))
        self.max_open_positions = min(4, max(1, int(settings.forex_max_open_positions)))

    def evaluate(self, proposal: ForexTradeProposal, state: ForexPortfolioState, broker: ForexBrokerProfile) -> ForexRiskDecision:
        exposures = self.currency_exposure(state.open_positions)
        if state.equity <= 0 or state.daily_realized_pnl <= -state.equity * self.daily_loss_limit_percent / 100:
            return self._reject("REJECT_DAILY_LOSS", exposures)
        if len(state.open_positions) >= self.max_open_positions:
            return self._reject("REJECT_MAX_POSITIONS", exposures)
        if any(item.get("pair") == proposal.pair for item in state.open_positions):
            return self._reject("REJECT_CURRENCY_EXPOSURE", exposures)
        config = pair_config(proposal.pair)
        stop_pips = abs(proposal.entry - proposal.stop) / config.pip_size
        evidence_multiplier = max(0.25, min(1.0, proposal.confidence))
        cost_multiplier = max(0.25, min(1.0, proposal.expected_net_pips / max(proposal.expected_gross_pips, 1e-9)))
        drawdown_multiplier = max(0.25, 1.0 - max(0.0, state.drawdown_percent) / 10.0)
        correlation = abs(float((state.pair_correlations or {}).get(proposal.pair, 0.0)))
        correlation_multiplier = 0.5 if correlation >= 0.8 else 1.0
        sizing_multiplier = min(evidence_multiplier, cost_multiplier, drawdown_multiplier, correlation_multiplier)
        effective_risk_percent = self.risk_per_trade_percent * sizing_multiplier
        risk_amount = state.equity * effective_risk_percent / 100
        lots = risk_amount / max(stop_pips * config.pip_value_per_standard_lot, 1e-9)
        lots = max(0.0, round(lots / config.lot_step) * config.lot_step)
        if lots < max(config.minimum_lot, broker.minimum_lot):
            return self._reject("REJECT_MARGIN", exposures)
        margin = abs(proposal.entry * lots * 100_000) * broker.margin_requirement
        notional = abs(proposal.entry * lots * 100_000)
        if margin + state.used_margin > state.equity or notional > state.equity * broker.maximum_internal_leverage:
            return self._reject("REJECT_MARGIN", exposures)
        projected = self._apply(exposures, proposal.pair, proposal.direction.value, proposal.entry * lots * 100_000)
        strongest = max((abs(value) for value in projected.values()), default=0.0)
        existing_notional = sum(abs(float(item.get("notional") or 0)) for item in state.open_positions)
        correlation_limited = correlation >= 0.8
        if correlation_limited or (existing_notional and strongest > max(state.equity * self.max_currency_exposure_multiple, existing_notional * 0.8)):
            reduced_lots = round(lots * 0.5 / config.lot_step) * config.lot_step
            if reduced_lots < config.minimum_lot:
                return self._reject("REJECT_CORRELATION" if correlation_limited else "REJECT_CURRENCY_EXPOSURE", exposures)
            return ForexRiskDecision(
                "APPROVE_REDUCED_SIZE",
                reduced_lots,
                risk_amount * 0.5,
                effective_risk_percent * 0.5,
                margin * 0.5,
                projected,
                ("CORRELATION_LIMIT",),
                "Pair correlation or clustered currency exposure reduced the evidence-adjusted position size",
            )
        return ForexRiskDecision(
            "APPROVE_FULL_SIZE",
            lots,
            risk_amount,
            effective_risk_percent,
            margin,
            projected,
            (),
            "Stop-based size adjusted for evidence, execution cost and drawdown",
        )

    def currency_exposure(self, positions: tuple[dict, ...]) -> dict[str, float]:
        result: dict[str, float] = {}
        for item in positions:
            try:
                result = self._apply(result, str(item["pair"]), str(item["direction"]), float(item.get("notional") or 0))
            except (KeyError, ValueError):
                continue
        return result

    def _apply(self, exposure: dict[str, float], pair: str, direction: str, notional: float) -> dict[str, float]:
        result = dict(exposure)
        config = pair_config(pair)
        sign = 1 if direction == "LONG" else -1
        result[config.base_currency] = result.get(config.base_currency, 0.0) + sign * notional
        result[config.quote_currency] = result.get(config.quote_currency, 0.0) - sign * notional
        return result

    def _reject(self, decision: str, exposure: dict[str, float]) -> ForexRiskDecision:
        blocker = {
            "REJECT_DAILY_LOSS": "DAILY_LOSS_LIMIT",
            "REJECT_MAX_POSITIONS": "MAX_POSITIONS",
            "REJECT_MARGIN": "MARGIN_LIMIT",
            "REJECT_CURRENCY_EXPOSURE": "CURRENCY_EXPOSURE_LIMIT",
            "REJECT_CORRELATION": "CORRELATION_LIMIT",
        }[decision]
        return ForexRiskDecision(decision, 0.0, 0.0, 0.0, 0.0, exposure, (blocker,), blocker)
