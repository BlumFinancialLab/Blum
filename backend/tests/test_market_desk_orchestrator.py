from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Asset, PriceHistory, RMultipleMetric
from app.services.market_desks import DAXAgent, MarketDeskRegistry, NasdaqAgent
from app.services.cross_market_orchestrator import BlumCrossMarketOpportunityOrchestrator, OrchestratorLimits
from app.services.quant_edge import (
    APPROVED_FOR_PAPER,
    REJECTED_INSUFFICIENT_SAMPLE,
    BlumQuantEdgeAgent,
)
from app.services.paper_forward_opportunity_scanner import PaperForwardOpportunityScanner


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def add_asset(
    db: Session,
    ticker: str,
    *,
    country: str = "USA",
    exchange: str = "NASDAQ",
    asset_type: str = "Stock",
    category: str = "Stock",
) -> Asset:
    asset = Asset(
        ticker=ticker,
        name=ticker,
        category=category,
        sector="Technology",
        industry="Software",
        country=country,
        asset_type=asset_type,
        currency="USD",
        exchange=exchange,
        is_active=True,
    )
    db.add(asset)
    db.flush()
    db.add(
        PriceHistory(
            asset_id=asset.id,
            date=date.today(),
            open=99.0,
            high=102.0,
            low=98.0,
            close=101.0,
            volume=2_000_000,
            provider="test",
        )
    )
    return asset


def candidate(ticker: str = "NVDA") -> dict:
    return {
        "ticker": ticker,
        "asset": {
            "ticker": ticker,
            "asset_type": "Stock",
            "asset_class": "equities",
            "market": "us_equities",
            "sector": "Technology",
        },
        "actionability": "active_setup",
        "confidence": 78.0,
        "sniper_score": 82.0,
        "setup": {"setup_type": "momentum_breakout"},
        "trade_plan": {
            "entry_trigger": "daily close above resistance",
            "invalidation_level": 96.0,
            "target_1": 110.0,
        },
        "price_context": {
            "latest_price": 100.0,
            "rows": 120,
            "data_quality_score": 90.0,
        },
        "risk_reward_ratio": 2.5,
        "data_quality_status": "OK",
    }


def test_registry_runs_only_desks_with_available_stored_data():
    with setup_db() as db:
        add_asset(db, "NVDA")
        db.commit()

        registry = MarketDeskRegistry(
            agents=[NasdaqAgent(candidate_evaluator=lambda _db, asset: candidate(asset.ticker)), DAXAgent()]
        )
        report = registry.discover(db)

    assert [agent.agent_name for agent in report.available_agents] == ["NasdaqAgent"]
    assert report.skipped_agents == [
        {
            "agent_name": "DAXAgent",
            "market": "dax",
            "benchmark": "^GDAXI",
            "status": "NO_ASSETS_CONFIGURED",
            "skipped_reason": "NO_ASSETS_CONFIGURED",
        }
    ]


def test_nasdaq_agent_returns_market_specific_auditable_result():
    with setup_db() as db:
        add_asset(db, "NVDA")
        db.commit()

        result = NasdaqAgent(candidate_evaluator=lambda _db, asset: candidate(asset.ticker)).scan(db, limit=5)

    assert result["agent_name"] == "NasdaqAgent"
    assert result["market"] == "nasdaq"
    assert result["benchmark"] == "QQQ"
    assert result["assets_scanned"] == 1
    assert result["opportunities_found"] == 1
    assert result["best_opportunity"]["ticker"] == "NVDA"
    assert result["market_specific_factors"] == ["growth_tech", "momentum", "rate_sensitivity", "drawdown_risk"]


def test_unavailable_agent_remains_skipped_when_reused_after_discovery():
    with setup_db() as db:
        agent = DAXAgent()

        availability = agent.availability(db)
        result = agent.scan(db, limit=5)

    assert availability["status"] == "NO_ASSETS_CONFIGURED"
    assert result["skipped_reason"] == "NO_ASSETS_CONFIGURED"
    assert result["opportunities_found"] == 0


def test_daily_bar_freshness_uses_end_of_market_date():
    with setup_db() as db:
        asset = add_asset(db, "NVDA")
        stored = db.query(PriceHistory).filter(PriceHistory.asset_id == asset.id).one()
        stored.date = date.today() - timedelta(days=4)
        db.commit()

        availability = NasdaqAgent(stale_after_hours=96.0).availability(db)

    assert availability["status"] == "AVAILABLE"
    assert availability["eligible_asset_count"] == 1


def test_quant_edge_rejects_candidate_when_sample_is_insufficient():
    with setup_db() as db:
        assessment = BlumQuantEdgeAgent(min_score=60.0, min_sample_size=20).assess(db, candidate())

    assert assessment["verdict"] == REJECTED_INSUFFICIENT_SAMPLE
    assert assessment["sample_size"] == 0
    assert assessment["edge_score"] is None


def test_quant_edge_approves_positive_stored_setup_evidence():
    with setup_db() as db:
        db.add(
            RMultipleMetric(
                setup_type="momentum_breakout",
                timeframe="daily",
                market_regime="risk_on",
                sector="Technology",
                sample_count=60,
                hit_rate=0.58,
                average_r=0.72,
                median_r=0.44,
                max_drawdown_r=-4.2,
                profit_factor=1.85,
                payoff_ratio=1.65,
                expectancy_r=0.42,
                evidence={"walk_forward_score": 74.0, "stability_score": 71.0},
            )
        )
        db.commit()

        assessment = BlumQuantEdgeAgent(min_score=60.0, min_sample_size=20).assess(db, candidate())

    assert assessment["verdict"] == APPROVED_FOR_PAPER
    assert assessment["sample_size"] == 60
    assert assessment["win_rate"] == 58.0
    assert assessment["expectancy"] == 0.42
    assert assessment["profit_factor"] == 1.85
    assert assessment["edge_score"] >= 60.0


class FakeAgent:
    def __init__(self, name: str, market: str, asset_class: str, candidates: list[dict]):
        self.agent_name = name
        self.market = market
        self.benchmark = "SPY"
        self.asset_class = asset_class
        self._candidates = candidates

    def scan(self, db, limit):
        rows = self._candidates[:limit]
        return {
            "agent_name": self.agent_name,
            "market": self.market,
            "benchmark": self.benchmark,
            "asset_class": self.asset_class,
            "assets_scanned": len(rows),
            "opportunities_found": len(rows),
            "trade_candidates": rows,
            "watchlist_candidates": [],
            "blocked_candidates": [],
            "data_blocked_candidates": [],
            "best_opportunity": rows[0] if rows else None,
            "market_regime": "risk_on",
            "data_quality_summary": {"status": "OK"},
            "skipped_reason": None,
        }


class FakeRegistry:
    def __init__(self, agents, skipped=None):
        self.agents = agents
        self.skipped = skipped or []

    def discover(self, db):
        from app.services.market_desks import MarketDeskDiscovery

        return MarketDeskDiscovery(self.agents, self.skipped)


class FakeQuant:
    def assess(self, db, row):
        approved = row["ticker"] != "WEAK"
        return {
            "verdict": APPROVED_FOR_PAPER if approved else "REJECTED_NO_EDGE",
            "sample_size": 80,
            "edge_score": 78.0 if approved else 31.0,
            "expectancy": 0.35 if approved else -0.1,
            "overfitting_risk": 20.0,
            "explanation": "stored test evidence",
        }


def test_orchestrator_requires_quant_approval_and_deduplicates_tickers():
    nvda = candidate("NVDA")
    duplicate_nvda = {**candidate("NVDA"), "confidence": 60.0}
    weak = candidate("WEAK")
    registry = FakeRegistry(
        [
            FakeAgent("NasdaqAgent", "nasdaq", "equities", [nvda, weak]),
            FakeAgent("ETFDeskAgent", "etfs", "etfs", [duplicate_nvda]),
        ]
    )
    orchestrator = BlumCrossMarketOpportunityOrchestrator(
        registry=registry,
        quant_edge_agent=FakeQuant(),
        limits=OrchestratorLimits(3, 3, 3, 1, True),
    )

    with setup_db() as db:
        report = orchestrator.run(db, limit=10)

    assert report["agents_run"] == ["NasdaqAgent", "ETFDeskAgent"]
    assert [row["ticker"] for row in report["top_cross_market_opportunities"]] == ["NVDA"]
    assert report["candidate_payloads_for_persistence"][0]["paper_forward_classification"] == "TRADE_CANDIDATE"
    assert report["candidate_payloads_for_persistence"][0]["quant_edge"]["verdict"] == APPROVED_FOR_PAPER
    assert report["rejected_no_edge_count"] == 1
    assert report["repeated_ticker_warning"] is True


def test_orchestrator_enforces_per_market_limit_after_global_ranking():
    first = candidate("NVDA")
    second = {**candidate("MSFT"), "sniper_score": 75.0, "confidence": 72.0}
    etf = {**candidate("XLK"), "sniper_score": 70.0, "confidence": 70.0, "asset": {**candidate()["asset"], "asset_class": "etfs", "market": "etfs"}}
    registry = FakeRegistry(
        [
            FakeAgent("NasdaqAgent", "nasdaq", "equities", [first, second]),
            FakeAgent("ETFDeskAgent", "etfs", "etfs", [etf]),
        ]
    )
    orchestrator = BlumCrossMarketOpportunityOrchestrator(
        registry=registry,
        quant_edge_agent=FakeQuant(),
        limits=OrchestratorLimits(3, 1, 2, 1, True),
    )

    with setup_db() as db:
        report = orchestrator.run(db, limit=10)

    assert [row["ticker"] for row in report["top_cross_market_opportunities"]] == ["NVDA", "XLK"]
    assert report["diversification_summary"]["selected_by_market"] == {"nasdaq": 1, "etfs": 1}
    assert report["diversification_summary"]["concentration_rejections"] == 1


def test_quant_approval_cannot_promote_candidate_without_invalidation():
    no_stop = candidate("NVDA")
    no_stop["trade_plan"] = {"entry_trigger": "daily close above resistance", "target_1": 110.0}
    orchestrator = BlumCrossMarketOpportunityOrchestrator(
        registry=FakeRegistry([FakeAgent("NasdaqAgent", "nasdaq", "equities", [no_stop])]),
        quant_edge_agent=FakeQuant(),
        limits=OrchestratorLimits(3, 3, 3, 1, True),
    )

    with setup_db() as db:
        report = orchestrator.run(db, limit=10)

    assert report["trade_candidate_count"] == 0
    assert report["candidate_payloads_for_persistence"][0]["paper_forward_classification"] == "BLOCKED_CANDIDATE"
    assert report["candidate_payloads_for_persistence"][0]["actionability_diagnosis"]["rejection_reason"] == "missing_invalidation_or_stop"


def test_default_scanner_delegates_to_cross_market_orchestrator(monkeypatch):
    calls = {"run": 0}

    class FakeOrchestrator:
        def run(self, db, limit=None):
            calls["run"] += 1
            return {
                "status": "ok",
                "generated_at": "2026-07-13T10:00:00",
                "scanner": "BlumCrossMarketOpportunityOrchestrator",
                "enabled_market_desk_agents": ["NasdaqAgent"],
                "agents_requested": 1,
                "agents_run": ["NasdaqAgent"],
                "agents_skipped": [],
                "opportunities_by_agent": {"NasdaqAgent": {"trade_candidates": 0}},
                "best_opportunity_by_agent": {},
                "rejected_by_agent": {},
                "top_cross_market_opportunities": [],
                "best_cross_market_candidate": None,
                "candidate_payloads_for_persistence": [],
                "trade_candidate_count": 0,
                "watchlist_candidate_count": 0,
                "blocked_candidate_count": 0,
                "data_blocked_candidate_count": 0,
                "rejected_no_edge_count": 0,
                "rejected_overfitting_count": 0,
                "rejected_insufficient_sample_count": 0,
                "quant_edge_summary": {"assessed_count": 0},
                "diversification_summary": {"selected_by_market": {}},
                "repeated_ticker_warning": False,
                "reason_if_same_tickers_repeat": None,
                "reason_if_no_trade_candidates": "No eligible stored market data.",
                "markets_scanned": ["nasdaq"],
                "asset_classes_scanned": ["equities"],
                "skipped_markets": [],
                "scanned_count": 0,
                "latest_trade_candidates": [],
                "latest_watchlist_candidates": [],
                "latest_blocked_candidates": [],
                "latest_data_blocked_candidates": [],
            }

    monkeypatch.setattr("app.services.paper_forward_opportunity_scanner.settings.blum_cross_market_orchestrator_enabled", True)
    scanner = PaperForwardOpportunityScanner(orchestrator=FakeOrchestrator())
    with setup_db() as db:
        report = scanner.scan(db)

    assert calls["run"] == 1
    assert report["scanner"] == "BlumCrossMarketOpportunityOrchestrator"
    assert report["agents_run"] == ["NasdaqAgent"]
    assert report["candidate_payloads_for_persistence"] == []
