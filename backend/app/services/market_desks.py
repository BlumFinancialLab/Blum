from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Asset, PriceHistory


CandidateEvaluator = Callable[[Session, Asset], dict]
AssetMatcher = Callable[[Asset], bool]


def normalized(value: object) -> str:
    return str(value or "").strip().lower()


class MarketDeskAgent(Protocol):
    agent_name: str
    market: str
    benchmark: str

    def availability(self, db: Session, *, asset_rows: list[tuple[Asset, date | None]] | None = None) -> dict: ...
    def scan(self, db: Session, limit: int) -> dict: ...


@dataclass(frozen=True)
class MarketDeskPolicy:
    agent_name: str
    market: str
    benchmark: str
    asset_class: str
    matcher: AssetMatcher
    market_specific_factors: tuple[str, ...]


@dataclass(frozen=True)
class MarketDeskDiscovery:
    available_agents: list[MarketDeskAgent]
    skipped_agents: list[dict]


class BaseMarketDeskAgent:
    policy: MarketDeskPolicy

    def __init__(
        self,
        *,
        candidate_evaluator: CandidateEvaluator | None = None,
        stale_after_hours: float = 96.0,
    ):
        self.candidate_evaluator = candidate_evaluator or evaluate_with_market_sniper
        self.stale_after_hours = max(0.0, float(stale_after_hours))
        self._eligible_assets: list[Asset] | None = None
        self._availability_status: str | None = None

    @property
    def agent_name(self) -> str:
        return self.policy.agent_name

    @property
    def market(self) -> str:
        return self.policy.market

    @property
    def benchmark(self) -> str:
        return self.policy.benchmark

    def availability(self, db: Session, *, asset_rows: list[tuple[Asset, date | None]] | None = None) -> dict:
        rows = asset_rows if asset_rows is not None else load_asset_availability(db)
        configured = [(asset, latest_date) for asset, latest_date in rows if self.policy.matcher(asset)]
        if not configured:
            self._eligible_assets = []
            self._availability_status = "NO_ASSETS_CONFIGURED"
            return self._availability_payload("NO_ASSETS_CONFIGURED", 0, 0)

        with_history = [(asset, latest_date) for asset, latest_date in configured if latest_date is not None]
        if not with_history:
            self._eligible_assets = []
            self._availability_status = "NO_PRICE_HISTORY"
            return self._availability_payload("NO_PRICE_HISTORY", len(configured), 0)

        eligible = [(asset, latest_date) for asset, latest_date in with_history if not self._is_stale(latest_date)]
        if not eligible:
            self._eligible_assets = []
            self._availability_status = "DATA_QUALITY_LOW"
            return self._availability_payload("DATA_QUALITY_LOW", len(configured), 0)

        self._eligible_assets = [asset for asset, _latest_date in eligible]
        self._availability_status = "AVAILABLE"
        return {
            **self._availability_payload("AVAILABLE", len(configured), len(eligible)),
            "eligible_assets": self._eligible_assets,
        }

    def scan(self, db: Session, limit: int) -> dict:
        availability = (
            {
                "status": "AVAILABLE",
                "eligible_assets": self._eligible_assets,
                "eligible_asset_count": len(self._eligible_assets),
            }
            if self._availability_status == "AVAILABLE" and self._eligible_assets is not None
            else self.availability(db)
        )
        if availability["status"] != "AVAILABLE":
            return self.skipped_result(availability["status"])

        opportunities: list[dict] = []
        data_blocked: list[dict] = []
        for asset in availability["eligible_assets"][: max(1, int(limit))]:
            try:
                candidate = normalize_candidate(self.candidate_evaluator(db, asset), asset, self.policy)
                opportunities.append(candidate)
            except Exception as exc:
                data_blocked.append(
                    {
                        "ticker": asset.ticker,
                        "status": "PROVIDER_UNAVAILABLE",
                        "reason": f"{type(exc).__name__}: {exc}",
                    }
                )

        ranked = sorted(opportunities, key=desk_candidate_score, reverse=True)
        trade_candidates = [row for row in ranked if candidate_actionability(row) in {"active_setup", "actionable_if_confirmed"}]
        watchlist_candidates = [row for row in ranked if candidate_actionability(row) in {"watch", "wait_for_trigger", "waiting_for_trigger"}]
        blocked_candidates = [row for row in ranked if row not in trade_candidates and row not in watchlist_candidates]
        quality_scores = [candidate_data_quality(row) for row in ranked if candidate_data_quality(row) is not None]
        return {
            "agent_name": self.agent_name,
            "market": self.market,
            "benchmark": self.benchmark,
            "asset_class": self.policy.asset_class,
            "assets_scanned": len(opportunities) + len(data_blocked),
            "opportunities_found": len(opportunities),
            "trade_candidates": trade_candidates,
            "watchlist_candidates": watchlist_candidates,
            "blocked_candidates": blocked_candidates,
            "data_blocked_candidates": data_blocked,
            "best_opportunity": ranked[0] if ranked else None,
            "market_regime": market_regime_from_candidates(ranked),
            "market_specific_factors": list(self.policy.market_specific_factors),
            "data_quality_summary": {
                "status": "OK" if opportunities else "PROVIDER_UNAVAILABLE" if data_blocked else "NO_OPPORTUNITIES",
                "eligible_assets": availability["eligible_asset_count"],
                "average_score": round(sum(quality_scores) / len(quality_scores), 4) if quality_scores else None,
            },
            "skipped_reason": None,
        }

    def skipped_result(self, reason: str) -> dict:
        return {
            "agent_name": self.agent_name,
            "market": self.market,
            "benchmark": self.benchmark,
            "asset_class": self.policy.asset_class,
            "assets_scanned": 0,
            "opportunities_found": 0,
            "trade_candidates": [],
            "watchlist_candidates": [],
            "blocked_candidates": [],
            "data_blocked_candidates": [],
            "best_opportunity": None,
            "market_regime": "unknown",
            "market_specific_factors": list(self.policy.market_specific_factors),
            "data_quality_summary": {"status": reason, "eligible_assets": 0, "average_score": None},
            "skipped_reason": reason,
        }

    def _is_stale(self, latest_date: date) -> bool:
        if self.stale_after_hours <= 0:
            return False
        latest = datetime.combine(latest_date, datetime.min.time())
        return latest < datetime.utcnow() - timedelta(hours=self.stale_after_hours)

    def _availability_payload(self, status: str, configured_count: int, eligible_count: int) -> dict:
        return {
            "agent_name": self.agent_name,
            "market": self.market,
            "benchmark": self.benchmark,
            "status": status,
            "skipped_reason": None if status == "AVAILABLE" else status,
            "configured_asset_count": configured_count,
            "eligible_asset_count": eligible_count,
        }


def stock(asset: Asset) -> bool:
    return "stock" in normalized(asset.asset_type) or "equity" in normalized(asset.asset_type)


def country_is(*names: str) -> AssetMatcher:
    allowed = {normalized(name) for name in names}
    return lambda asset: stock(asset) and normalized(asset.country) in allowed


def exchange_contains(*names: str) -> AssetMatcher:
    needles = tuple(normalized(name) for name in names)
    return lambda asset: stock(asset) and any(needle in normalized(asset.exchange) for needle in needles)


def category_contains(*names: str) -> AssetMatcher:
    needles = tuple(normalized(name) for name in names)
    return lambda asset: any(needle in normalized(asset.category) for needle in needles)


def asset_type_contains(*names: str) -> AssetMatcher:
    needles = tuple(normalized(name) for name in names)
    return lambda asset: any(needle in f"{normalized(asset.asset_type)} {normalized(asset.category)}" for needle in needles)


class FTSEMIBAgent(BaseMarketDeskAgent):
    policy = MarketDeskPolicy("FTSEMIBAgent", "ftse_mib", "FTSEMIB.MI", "equities", country_is("Italy"), ("relative_strength", "europe_rates", "sector_concentration", "liquidity"))


class DAXAgent(BaseMarketDeskAgent):
    policy = MarketDeskPolicy("DAXAgent", "dax", "^GDAXI", "equities", country_is("Germany"), ("export_sensitivity", "cyclical_sensitivity", "relative_strength", "volatility"))


class CAC40Agent(BaseMarketDeskAgent):
    policy = MarketDeskPolicy("CAC40Agent", "cac_40", "^FCHI", "equities", country_is("France"), ("europe_rates", "global_demand", "relative_strength", "volatility"))


class IBEX35Agent(BaseMarketDeskAgent):
    policy = MarketDeskPolicy("IBEX35Agent", "ibex_35", "^IBEX", "equities", country_is("Spain"), ("banks", "utilities", "europe_rates", "relative_strength"))


class SMIAgent(BaseMarketDeskAgent):
    policy = MarketDeskPolicy("SMIAgent", "smi", "^SSMI", "equities", country_is("Switzerland"), ("defensive_quality", "currency_sensitivity", "relative_strength", "volatility"))


class EuroStoxx50Agent(BaseMarketDeskAgent):
    policy = MarketDeskPolicy("EuroStoxx50Agent", "euro_stoxx_50", "^STOXX50E", "equities", country_is("Italy", "Germany", "France", "Spain", "Netherlands", "Belgium"), ("europe_breadth", "sector_leadership", "relative_strength", "rates"))


class WallStreetAgent(BaseMarketDeskAgent):
    policy = MarketDeskPolicy("WallStreetAgent", "wall_street", "SPY", "equities", country_is("USA", "United States"), ("liquidity", "sector_leadership", "earnings_risk", "relative_strength"))


class SP500Agent(BaseMarketDeskAgent):
    policy = MarketDeskPolicy("SP500Agent", "sp500", "SPY", "equities", category_contains("s&p 500", "sp500"), ("large_cap", "breadth", "sector_leadership", "benchmark_excess"))


class NasdaqAgent(BaseMarketDeskAgent):
    policy = MarketDeskPolicy("NasdaqAgent", "nasdaq", "QQQ", "equities", exchange_contains("nasdaq"), ("growth_tech", "momentum", "rate_sensitivity", "drawdown_risk"))


class DowJonesAgent(BaseMarketDeskAgent):
    policy = MarketDeskPolicy("DowJonesAgent", "dow_jones", "DIA", "equities", category_contains("dow", "djia"), ("quality_large_cap", "industrial_sensitivity", "dividend_quality", "relative_strength"))


class Russell2000Agent(BaseMarketDeskAgent):
    policy = MarketDeskPolicy("Russell2000Agent", "russell_2000", "IWM", "equities", category_contains("russell", "small cap"), ("small_cap", "domestic_growth", "rates", "liquidity"))


class NikkeiAgent(BaseMarketDeskAgent):
    policy = MarketDeskPolicy("NikkeiAgent", "nikkei", "^N225", "equities", country_is("Japan"), ("yen_sensitivity", "export_sensitivity", "relative_strength", "volatility"))


class HangSengAgent(BaseMarketDeskAgent):
    policy = MarketDeskPolicy("HangSengAgent", "hang_seng", "^HSI", "equities", country_is("Hong Kong"), ("china_sensitivity", "property_risk", "liquidity", "relative_strength"))


class IndiaNiftyAgent(BaseMarketDeskAgent):
    policy = MarketDeskPolicy("IndiaNiftyAgent", "india_nifty", "^NSEI", "equities", country_is("India"), ("domestic_growth", "foreign_flows", "valuation", "relative_strength"))


class ChinaAAgent(BaseMarketDeskAgent):
    policy = MarketDeskPolicy("ChinaAAgent", "china_a", "000001.SS", "equities", country_is("China"), ("policy_sensitivity", "liquidity", "property_risk", "relative_strength"))


class EmergingMarketsAgent(BaseMarketDeskAgent):
    policy = MarketDeskPolicy("EmergingMarketsAgent", "emerging_markets", "EEM", "equities", category_contains("emerging"), ("usd_sensitivity", "commodity_sensitivity", "country_risk", "relative_strength"))


class ETFDeskAgent(BaseMarketDeskAgent):
    policy = MarketDeskPolicy("ETFDeskAgent", "etfs", "SPY", "etfs", asset_type_contains("etf", "fund"), ("rotation", "relative_strength", "liquidity", "tracking_risk"))


class CryptoDeskAgent(BaseMarketDeskAgent):
    policy = MarketDeskPolicy("CryptoDeskAgent", "crypto", "BTC-USD", "crypto", asset_type_contains("crypto"), ("twenty_four_seven", "volatility", "liquidity", "regime_risk"))


class ForexDeskAgent(BaseMarketDeskAgent):
    policy = MarketDeskPolicy("ForexDeskAgent", "forex", "UUP", "forex", asset_type_contains("forex", "currency"), ("currency_strength", "rates_proxy", "macro", "volatility"))


class CommodityDeskAgent(BaseMarketDeskAgent):
    policy = MarketDeskPolicy("CommodityDeskAgent", "commodities", "DBC", "commodities", asset_type_contains("commodity", "gold", "oil", "metal"), ("macro_sensitivity", "term_structure", "volatility", "usd_sensitivity"))


class RatesBondProxyAgent(BaseMarketDeskAgent):
    policy = MarketDeskPolicy("RatesBondProxyAgent", "rates_bonds", "TLT", "bonds", asset_type_contains("bond", "fixed income", "rate"), ("duration", "yield_curve", "inflation", "rate_sensitivity"))


class VolatilityDeskAgent(BaseMarketDeskAgent):
    policy = MarketDeskPolicy("VolatilityDeskAgent", "volatility", "^VIX", "volatility", asset_type_contains("volatility", "vix"), ("term_structure", "risk_off", "mean_reversion", "event_risk"))


DEFAULT_MARKET_DESK_AGENTS = (
    FTSEMIBAgent,
    DAXAgent,
    CAC40Agent,
    IBEX35Agent,
    SMIAgent,
    EuroStoxx50Agent,
    WallStreetAgent,
    SP500Agent,
    NasdaqAgent,
    DowJonesAgent,
    Russell2000Agent,
    NikkeiAgent,
    HangSengAgent,
    IndiaNiftyAgent,
    ChinaAAgent,
    EmergingMarketsAgent,
    ETFDeskAgent,
    CryptoDeskAgent,
    ForexDeskAgent,
    CommodityDeskAgent,
    RatesBondProxyAgent,
    VolatilityDeskAgent,
)


class MarketDeskRegistry:
    def __init__(self, agents: list[MarketDeskAgent] | None = None):
        self.agents = agents if agents is not None else [agent_type() for agent_type in DEFAULT_MARKET_DESK_AGENTS]

    def discover(self, db: Session) -> MarketDeskDiscovery:
        asset_rows = load_asset_availability(db)
        available: list[MarketDeskAgent] = []
        skipped: list[dict] = []
        for agent in self.agents:
            status = agent.availability(db, asset_rows=asset_rows)
            if status["status"] == "AVAILABLE":
                available.append(agent)
                continue
            skipped.append(
                {
                    "agent_name": agent.agent_name,
                    "market": agent.market,
                    "benchmark": agent.benchmark,
                    "status": status["status"],
                    "skipped_reason": status["skipped_reason"],
                }
            )
        return MarketDeskDiscovery(available_agents=available, skipped_agents=skipped)


def load_asset_availability(db: Session) -> list[tuple[Asset, date | None]]:
    latest = (
        select(PriceHistory.asset_id.label("asset_id"), func.max(PriceHistory.date).label("latest_date"))
        .group_by(PriceHistory.asset_id)
        .subquery()
    )
    return list(
        db.execute(
            select(Asset, latest.c.latest_date)
            .outerjoin(latest, latest.c.asset_id == Asset.id)
            .where(Asset.is_active.is_(True))
            .order_by(Asset.ticker)
        ).all()
    )


def evaluate_with_market_sniper(db: Session, asset: Asset) -> dict:
    from app.services.market_sniper import MarketSniperEngine

    return MarketSniperEngine().evaluate_asset(db, asset, persist=False)


def normalize_candidate(candidate: dict, asset: Asset, policy: MarketDeskPolicy) -> dict:
    asset_payload = candidate.get("asset") if isinstance(candidate.get("asset"), dict) else {}
    return {
        **candidate,
        "ticker": str(candidate.get("ticker") or asset.ticker).upper(),
        "asset": {
            **asset_payload,
            "ticker": asset.ticker,
            "name": asset.name,
            "asset_type": asset.asset_type,
            "asset_class": policy.asset_class,
            "market": policy.market,
            "sector": asset.sector,
            "industry": asset.industry,
            "country": asset.country,
            "exchange": asset.exchange,
            "currency": asset.currency,
        },
        "benchmark_asset": policy.benchmark,
        "market_desk": {
            "agent_name": policy.agent_name,
            "market": policy.market,
            "benchmark": policy.benchmark,
            "market_specific_factors": list(policy.market_specific_factors),
        },
    }


def desk_candidate_score(candidate: dict) -> float:
    return max(float(candidate.get("sniper_score") or 0.0), float(candidate.get("confidence") or 0.0))


def candidate_actionability(candidate: dict) -> str:
    return str(candidate.get("actionability") or candidate.get("actionability_state") or "").strip().lower()


def candidate_data_quality(candidate: dict) -> float | None:
    context = candidate.get("price_context") if isinstance(candidate.get("price_context"), dict) else {}
    value = context.get("data_quality_score")
    return float(value) if value is not None else None


def market_regime_from_candidates(candidates: list[dict]) -> str:
    for candidate in candidates:
        value = candidate.get("market_regime") or (candidate.get("regime") or {}).get("primary")
        if value:
            return str(value)
    return "unknown"
