from __future__ import annotations

from dataclasses import dataclass

from app.services.forex_contracts import PAIR_CONFIGS


@dataclass(frozen=True)
class ForexBrokerProfile:
    profile_name: str
    broker_name: str
    account_currency: str
    leverage: float
    maximum_internal_leverage: float
    margin_requirement: float
    stop_out_level: float
    commission_per_lot_round_trip: float
    minimum_commission: float
    spread_pips: dict[str, float]
    session_spread_multiplier: dict[str, float]
    slippage_pips: float
    swap_long: dict[str, float]
    swap_short: dict[str, float]
    triple_swap_day: int
    minimum_lot: float
    lot_step: float
    supported_order_types: tuple[str, ...]
    supports_partial_fills: bool = True
    maximum_immediate_fill_lots: float = 5.0
    execution_latency_ms: int = 120
    model_version: str = "forex-paper-execution-v1"


class BlumForexBrokerProfileService:
    def __init__(self) -> None:
        pairs = tuple(PAIR_CONFIGS)
        self._profiles = {
            "paper_eu_30x": ForexBrokerProfile(
                profile_name="paper_eu_30x",
                broker_name="BLUM realistic paper broker",
                account_currency="EUR",
                leverage=30.0,
                maximum_internal_leverage=15.0,
                margin_requirement=1 / 30,
                stop_out_level=0.5,
                commission_per_lot_round_trip=6.0,
                minimum_commission=0.02,
                spread_pips={pair: (0.8 if pair in {"EURUSD=X", "USDJPY=X"} else 1.2) for pair in pairs},
                session_spread_multiplier={"LONDON": 1.0, "LONDON_NEW_YORK_OVERLAP": 0.8, "NEW_YORK": 1.0, "ASIA": 1.35, "ROLLOVER": 2.5},
                slippage_pips=0.12,
                swap_long={pair: -0.7 for pair in pairs},
                swap_short={pair: -0.5 for pair in pairs},
                triple_swap_day=2,
                minimum_lot=0.01,
                lot_step=0.01,
                supported_order_types=("MARKET", "LIMIT", "STOP", "STOP_LIMIT"),
            )
        }

    def get(self, profile_name: str = "paper_eu_30x") -> ForexBrokerProfile:
        try:
            return self._profiles[profile_name]
        except KeyError as exc:
            raise KeyError(f"Unknown Forex broker profile: {profile_name}") from exc

    def estimate_spread_pips(
        self,
        pair: str,
        *,
        session: str,
        liquidity_score: float,
        volatility_score: float,
        event_impact: str,
        profile_name: str = "paper_eu_30x",
    ) -> float:
        """Versioned fallback spread estimate; observed bid/ask always takes precedence."""

        profile = self.get(profile_name)
        base = profile.spread_pips[pair]
        session_multiplier = profile.session_spread_multiplier.get(session, 1.5)
        liquidity_multiplier = 1.0 + max(0.0, 0.7 - liquidity_score) * 1.5
        volatility_multiplier = 1.0 + max(0.0, volatility_score - 0.5)
        event_multiplier = {"LOW_IMPACT": 1.0, "MEDIUM_IMPACT": 1.35, "HIGH_IMPACT": 2.5}.get(event_impact, 1.25)
        return base * session_multiplier * liquidity_multiplier * volatility_multiplier * event_multiplier
