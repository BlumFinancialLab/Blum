from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionCostProfile:
    spread_bps: float
    slippage_bps: float
    commission_bps: float
    liquidity_penalty_bps: float
    gap_risk_bps: float
    profile_name: str

    @property
    def one_way_bps(self) -> float:
        return self.spread_bps / 2 + self.slippage_bps + self.commission_bps + self.liquidity_penalty_bps

    @property
    def total_round_trip_bps(self) -> float:
        return self.one_way_bps * 2 + self.gap_risk_bps

    def to_dict(self) -> dict:
        return {
            "profile_name": self.profile_name,
            "spread_bps": self.spread_bps,
            "slippage_bps": self.slippage_bps,
            "commission_bps": self.commission_bps,
            "liquidity_penalty_bps": self.liquidity_penalty_bps,
            "gap_risk_bps": self.gap_risk_bps,
            "one_way_bps": round(self.one_way_bps, 4),
            "total_round_trip_bps": round(self.total_round_trip_bps, 4),
        }


@dataclass(frozen=True)
class PositionSizeResult:
    units: float
    risk_amount: float
    risk_fraction: float
    notional: float
    multiplier: float
    blocker: str | None = None

    def to_dict(self) -> dict:
        return {
            "units": self.units,
            "risk_amount": self.risk_amount,
            "risk_fraction": self.risk_fraction,
            "notional": self.notional,
            "multiplier": self.multiplier,
            "blocker": self.blocker,
        }


class ReplayExecutionModel:
    def profile(self, *, market: str, asset_type: str, liquidity_score: float, session: str = "regular") -> ExecutionCostProfile:
        market_key = (market or "").upper()
        europe = market_key not in {"USA", "US", "UNITED STATES"}
        etf = (asset_type or "").lower() == "etf"
        liquid = liquidity_score >= 70
        if etf and liquid:
            base = (1.2, 0.8, 0.2, 0.2, 0.5, "liquid_etf")
        elif not europe and liquid:
            base = (1.5, 1.0, 0.2, 0.3, 0.8, "us_liquid_large_cap")
        elif europe and liquid:
            base = (3.0, 1.8, 0.5, 0.8, 1.5, "europe_liquid")
        elif europe:
            base = (8.0, 4.5, 0.8, 4.0, 4.0, "europe_less_liquid")
        else:
            base = (5.0, 3.0, 0.4, 2.5, 2.5, "us_less_liquid")
        session_penalty = 0.0 if session == "regular" else 3.0
        return ExecutionCostProfile(
            spread_bps=base[0] + session_penalty,
            slippage_bps=base[1] + session_penalty / 2,
            commission_bps=base[2],
            liquidity_penalty_bps=base[3] + max(0.0, 50 - liquidity_score) * 0.08,
            gap_risk_bps=base[4],
            profile_name=base[5],
        )


class ReplayPositionSizer:
    def __init__(self, max_risk_fraction: float = 0.01):
        self.max_risk_fraction = max(0.0, min(0.02, max_risk_fraction))

    def size(
        self,
        *,
        capital: float,
        entry: float,
        stop: float,
        atr: float,
        liquidity_score: float,
        confidence: float,
        edge_score: float,
        data_quality: float,
        regime_alignment: float,
    ) -> PositionSizeResult:
        risk_per_unit = abs(entry - stop)
        if capital <= 0 or entry <= 0 or risk_per_unit <= 0:
            return PositionSizeResult(0.0, 0.0, 0.0, 0.0, 0.0, "INVALID_RISK_GEOMETRY")
        if data_quality < 35:
            return PositionSizeResult(0.0, 0.0, 0.0, 0.0, 0.0, "DATA_QUALITY_LOW")
        liquidity_factor = _scale(liquidity_score, 0.25, 1.0)
        confidence_factor = _scale(confidence, 0.4, 1.0)
        edge_factor = _scale(edge_score, 0.4, 1.0)
        quality_factor = _scale(data_quality, 0.35, 1.0)
        regime_factor = _scale(regime_alignment, 0.4, 1.0)
        volatility_factor = max(0.35, min(1.0, risk_per_unit / max(atr, 0.01)))
        multiplier = liquidity_factor * confidence_factor * edge_factor * quality_factor * regime_factor * volatility_factor
        risk_fraction = self.max_risk_fraction * multiplier
        risk_amount = capital * risk_fraction
        units = risk_amount / risk_per_unit
        notional_cap = capital * min(1.0, max(0.1, liquidity_score / 100))
        units = min(units, notional_cap / entry)
        risk_amount = units * risk_per_unit
        return PositionSizeResult(
            units=round(max(0.0, units), 6),
            risk_amount=round(max(0.0, risk_amount), 4),
            risk_fraction=round(risk_amount / capital, 6),
            notional=round(units * entry, 4),
            multiplier=round(multiplier, 6),
        )


def _scale(value: float, floor: float, ceiling: float) -> float:
    return max(floor, min(ceiling, float(value or 0.0) / 100.0))
