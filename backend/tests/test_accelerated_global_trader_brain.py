from datetime import date, datetime, timedelta

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.engine.brain.trader_brain import alpha_benchmark_gap_payload, training_continuity_payload
from app.models import Asset, BlumLearningExperiment, LearningEvent, LearningFocusPriority, LearningRun, PriceHistory
from app.services.paper_forward_opportunity_scanner import (
    BLOCKED_CANDIDATE,
    DATA_BLOCKED_CANDIDATE,
    TRADE_CANDIDATE,
    BlumExperimentManagerAgent,
    BlumActionabilityAgent,
    BlumBenchmarkAgent,
    BlumDataAvailabilityAgent,
    BlumMarketUniverseAgent,
    BlumRiskRewardAgent,
    PaperForwardOpportunityScanner,
    ScannerThresholds,
    asset_class_key,
    benchmark_availability_map,
    market_key,
    parse_csv,
)


def test_run_once_uses_scanner_owned_universe(monkeypatch):
    calls = {"scanner_init_provider": "not-called", "scan_called": 0}

    class FakeScanner:
        def __init__(self, candidate_provider=None):
            calls["scanner_init_provider"] = candidate_provider

        def scan(self, db):
            calls["scan_called"] += 1
            return {
                "status": "ok",
                "candidate_payloads_for_persistence": [],
                "markets_scanned": ["us_equities"],
                "asset_classes_scanned": ["equities"],
                "skipped_markets": [],
                "best_cross_market_candidate": None,
                "reason_if_no_trade_candidates": "No test candidates.",
            }

    from app.services import live_forward_paper_trading as module

    monkeypatch.setattr(module, "PaperForwardOpportunityScanner", FakeScanner)
    with setup_db() as db:
        result = module.LiveForwardPaperTradingService().run_once(db)

    assert result["status"] == "ok"
    assert calls["scan_called"] == 1
    assert calls["scanner_init_provider"] is None


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def make_thresholds(
    *,
    enabled_markets: tuple[str, ...] = ("us_equities", "european_equities", "etfs"),
    enabled_asset_classes: tuple[str, ...] = ("equities",),
    max_assets_per_market: int = 10,
    require_benchmark: bool = False,
    min_confidence: float = 50.0,
    min_data_quality: float = 50.0,
    min_liquidity_score: float = 0.0,
    scan_stale_data_max_age_hours: float = 72.0,
    cross_market_ranking_enabled: bool = True,
) -> ScannerThresholds:
    return ScannerThresholds(
        min_confidence=min_confidence,
        min_risk_reward=1.0,
        min_data_quality=min_data_quality,
        max_candidates_per_run=30,
        allow_watchlist_candidates=True,
        allow_trade_candidates=True,
        enabled_markets=enabled_markets,
        enabled_asset_classes=enabled_asset_classes,
        require_benchmark=require_benchmark,
        min_liquidity_score=min_liquidity_score,
        max_assets_per_market=max_assets_per_market,
        scan_stale_data_max_age_hours=scan_stale_data_max_age_hours,
        cross_market_ranking_enabled=cross_market_ranking_enabled,
    )


def add_asset(db: Session, ticker: str, *, country: str, asset_type: str, exchange: str) -> Asset:
    asset = Asset(
        ticker=ticker,
        name=ticker,
        category=asset_type,
        sector="Technology",
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
            high=101.0,
            low=98.0,
            close=100.0,
            volume=1_000_000,
            provider="test",
        )
    )
    return asset


def candidate_payload(
    *,
    ticker: str = "NVDA",
    stop: float | None = 96.0,
    actionability: str = "active_setup",
    confidence: float = 78.0,
    asset: dict | None = None,
    price_context: dict | None = None,
    data_quality_status: str | None = None,
) -> dict:
    trade_plan = {
        "direction": "long",
        "entry_trigger": "breakout confirmation",
        "target_1": 110.0,
        "target_2": 116.0,
    }
    if stop is not None:
        trade_plan["invalidation_level"] = stop
    payload = {
        "ticker": ticker,
        "asset": {
            "ticker": ticker,
            "name": ticker,
            "asset_type": "Stock",
            "market": "us_equities",
            "exchange": "NASDAQ",
            "currency": "USD",
            "country": "USA",
            "sector": "Technology",
        },
        "actionability": actionability,
        "confidence": confidence,
        "sniper_score": 82.0,
        "setup": {"setup_type": "momentum_breakout"},
        "trade_plan": trade_plan,
        "price_context": {
            "latest_price": 100.0,
            "latest_volume": 2_500_000,
            "rows": 120,
            "data_quality_score": 90.0,
        },
        "explanation": "Stored evidence supports a paper-forward candidate.",
    }
    if asset:
        payload["asset"] = {**payload["asset"], **asset}
    if price_context:
        payload["price_context"] = {**payload["price_context"], **price_context}
    if data_quality_status:
        payload["data_quality_status"] = data_quality_status
    return payload


def test_raw_candidates_builds_universe_before_legacy_sources(monkeypatch):
    calls: list[str] = []

    class FakeUniverseAgent:
        def __init__(self, thresholds):
            self.thresholds = thresholds

        def build(self, db):
            calls.append("universe")
            return {
                "eligible_asset_objects": [],
                "markets_scanned": ["us_equities"],
                "asset_classes_scanned": ["equities"],
            }

    class FakeMarketSniperEngine:
        def candidates(self, db, limit, persist=False):
            calls.append("sniper")
            return {"candidates": [candidate_payload(ticker="AAPL")]}

    from app.services import paper_forward_opportunity_scanner as module

    monkeypatch.setattr(module, "BlumMarketUniverseAgent", FakeUniverseAgent)
    monkeypatch.setattr("app.services.market_sniper.MarketSniperEngine", FakeMarketSniperEngine)
    scanner = PaperForwardOpportunityScanner()

    with setup_db() as db:
        candidates = scanner.raw_candidates(db, limit=1)

    assert [row.get("ticker") for row in candidates] == ["AAPL"]
    assert calls == ["universe", "sniper"]
    assert scanner.last_universe_report["markets_scanned"] == ["us_equities"]


def test_sniper_candidate_outside_enabled_universe_is_data_blocked(monkeypatch):
    class FakeMarketSniperEngine:
        def candidates(self, db, limit, persist=False):
            return {
                "candidates": [
                    candidate_payload(
                        ticker="SAP",
                        asset={"country": "Germany", "exchange": "XETRA", "market": "european_equities"},
                    )
                ]
            }

    monkeypatch.setattr("app.services.market_sniper.MarketSniperEngine", FakeMarketSniperEngine)
    scanner = PaperForwardOpportunityScanner()
    scanner.thresholds = make_thresholds(enabled_markets=("us_equities",), enabled_asset_classes=("equities",))

    with setup_db() as db:
        add_asset(db, "SAP", country="Germany", asset_type="Stock", exchange="XETRA")
        db.commit()
        report = scanner.scan(db, limit=1)

    assert report["trade_candidate_count"] == 0
    assert report["data_blocked_candidate_count"] == 1
    assert report["candidate_payloads_for_persistence"][0]["paper_forward_classification"] == DATA_BLOCKED_CANDIDATE
    assert report["candidate_payloads_for_persistence"][0]["data_quality_status"] == "MARKET_NOT_ENABLED"


def test_candidate_provider_candidate_outside_enabled_universe_is_data_blocked():
    scanner = PaperForwardOpportunityScanner(
        candidate_provider=lambda _db, _limit: [
            candidate_payload(
                ticker="SAP",
                asset={"country": "Germany", "exchange": "XETRA", "market": "european_equities"},
            )
        ]
    )
    scanner.thresholds = make_thresholds(enabled_markets=("us_equities",), enabled_asset_classes=("equities",))

    with setup_db() as db:
        add_asset(db, "SAP", country="Germany", asset_type="Stock", exchange="XETRA")
        db.commit()
        report = scanner.scan(db, limit=1)

    assert report["trade_candidate_count"] == 0
    assert report["data_blocked_candidate_count"] == 1
    assert report["candidate_payloads_for_persistence"][0]["paper_forward_classification"] == DATA_BLOCKED_CANDIDATE
    assert report["candidate_payloads_for_persistence"][0]["data_quality_status"] == "MARKET_NOT_ENABLED"


def test_cross_market_ranking_can_be_disabled():
    scanner = PaperForwardOpportunityScanner(
        candidate_provider=lambda _db, _limit: [
            candidate_payload(ticker="AAPL", confidence=55.0),
            candidate_payload(ticker="NVDA", confidence=90.0),
        ]
    )
    scanner.thresholds = make_thresholds(cross_market_ranking_enabled=False)

    with setup_db() as db:
        add_asset(db, "AAPL", country="USA", asset_type="Stock", exchange="NASDAQ")
        add_asset(db, "NVDA", country="USA", asset_type="Stock", exchange="NASDAQ")
        db.commit()
        report = scanner.scan(db, limit=2)

    assert report["best_cross_market_candidate"]["ticker"] == "AAPL"


def test_required_stale_benchmark_is_data_blocked_with_clear_blocker():
    scanner = PaperForwardOpportunityScanner(
        candidate_provider=lambda _db, _limit: [candidate_payload(ticker="AAPL")]
    )
    scanner.thresholds = make_thresholds(require_benchmark=True, scan_stale_data_max_age_hours=24.0)

    with setup_db() as db:
        add_asset(db, "AAPL", country="USA", asset_type="Stock", exchange="NASDAQ")
        benchmark = Asset(
            ticker="QQQ",
            name="QQQ",
            category="ETF",
            sector="Technology",
            country="USA",
            asset_type="ETF",
            currency="USD",
            exchange="NASDAQ",
            is_active=True,
        )
        db.add(benchmark)
        db.flush()
        db.add(
            PriceHistory(
                asset_id=benchmark.id,
                date=date.today() - timedelta(days=10),
                open=99.0,
                high=101.0,
                low=98.0,
                close=100.0,
                volume=1_000_000,
                provider="test",
                created_at=datetime.utcnow(),
            )
        )
        db.commit()
        report = scanner.scan(db, limit=1)

    assert report["trade_candidate_count"] == 0
    assert report["data_blocked_candidate_count"] == 1
    assert report["candidate_payloads_for_persistence"][0]["data_quality_status"] == "BENCHMARK_STALE"
    assert report["candidate_payloads_for_persistence"][0]["benchmark_context"]["benchmark_blocker"] == "BENCHMARK_STALE"


def test_parse_csv_normalizes_values():
    assert parse_csv(" US_Equities, etfs ,, Crypto ") == ("us_equities", "etfs", "crypto")


def test_market_universe_agent_uses_enabled_markets():
    with setup_db() as db:
        add_asset(db, "AAPL", country="USA", asset_type="Stock", exchange="NASDAQ")
        add_asset(db, "SAP", country="Germany", asset_type="Stock", exchange="XETRA")
        add_asset(db, "QQQ", country="USA", asset_type="ETF", exchange="NASDAQ")
        db.commit()

        universe = BlumMarketUniverseAgent(make_thresholds(enabled_markets=("us_equities",))).build(db)

        assert universe["markets_requested"] == ["us_equities"]
        assert universe["markets_scanned"] == ["us_equities"]
        assert universe["asset_classes_scanned"] == ["equities"]
        assert universe["eligible_assets"] == ["AAPL"]
        assert [asset.ticker for asset in universe["eligible_asset_objects"]] == ["AAPL"]
        skipped_tickers = {item["ticker"]: item["reason"] for item in universe["skipped_assets_with_reasons"]}
        assert skipped_tickers["SAP"] == "MARKET_NOT_ENABLED"
        assert skipped_tickers["QQQ"] == "ASSET_CLASS_NOT_ENABLED"


def test_market_key_classifies_volatility_before_indexes():
    assert market_key({"asset_type": "Volatility Index", "category": "VIX"}) == "volatility"


def test_asset_class_key_classifies_volatility_before_indexes():
    assert asset_class_key({"asset_type": "Volatility Index", "category": "VIX"}) == "volatility"


def test_market_universe_agent_build_uses_bounded_query_count_and_market_cap():
    with setup_db() as db:
        add_asset(db, "AAPL", country="USA", asset_type="Stock", exchange="NASDAQ")
        add_asset(db, "MSFT", country="USA", asset_type="Stock", exchange="NASDAQ")
        add_asset(db, "NVDA", country="USA", asset_type="Stock", exchange="NASDAQ")
        db.commit()

        statements = []

        def capture_select(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(db.bind, "before_cursor_execute", capture_select)
        try:
            universe = BlumMarketUniverseAgent(
                make_thresholds(enabled_markets=("us_equities",), enabled_asset_classes=("equities",))
            ).build(db)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture_select)

        assert universe["eligible_assets"] == ["AAPL", "MSFT", "NVDA"]
        assert len(statements) == 1

        capped = BlumMarketUniverseAgent(
            make_thresholds(
                enabled_markets=("us_equities",),
                enabled_asset_classes=("equities",),
                max_assets_per_market=2,
            )
        ).build(db)
        assert capped["eligible_assets"] == ["AAPL", "MSFT"]


def test_market_universe_freshness_uses_market_date_not_import_timestamp():
    with setup_db() as db:
        asset = Asset(
            ticker="OLD",
            name="OLD",
            category="Stock",
            sector="Technology",
            country="USA",
            asset_type="Stock",
            currency="USD",
            exchange="NASDAQ",
            is_active=True,
        )
        db.add(asset)
        db.flush()
        db.add(
            PriceHistory(
                asset_id=asset.id,
                date=date.today() - timedelta(days=10),
                open=99.0,
                high=101.0,
                low=98.0,
                close=100.0,
                volume=1_000_000,
                provider="test",
                created_at=datetime.utcnow(),
            )
        )
        db.commit()

        universe = BlumMarketUniverseAgent(
            make_thresholds(
                enabled_markets=("us_equities",),
                enabled_asset_classes=("equities",),
                scan_stale_data_max_age_hours=24.0,
            )
        ).build(db)

        assert universe["eligible_assets"] == []
        assert universe["skipped_assets_with_reasons"][0]["ticker"] == "OLD"
        assert universe["skipped_assets_with_reasons"][0]["reason"] == "STALE_PRICE_DATA"


def test_task2_agents_are_concrete_collaborators():
    thresholds = make_thresholds()

    benchmark = BlumBenchmarkAgent().assess(candidate_payload(), None, {"QQQ": True})
    missing_benchmark = BlumBenchmarkAgent().assess(candidate_payload(), None, {})
    data_availability = BlumDataAvailabilityAgent(make_thresholds(min_liquidity_score=80.0)).assess(
        candidate_payload(price_context={"rows": 0, "latest_volume": 100_000}),
        {"benchmark_available": True, "asset_type": "Stock"},
    )
    risk_reward = BlumRiskRewardAgent().assess(candidate_payload(), 100.0)

    assert benchmark["benchmark_asset"] == "QQQ"
    assert benchmark["benchmark_available"] is True
    assert missing_benchmark["benchmark_available"] is False
    assert data_availability["data_quality_status"] == "OHLCV_MISSING"
    assert data_availability["tradability_status"] == "LIQUIDITY_UNKNOWN"
    assert risk_reward["risk_reward_ratio"] == 2.5
    assert risk_reward["stop_price"] == 96.0
    assert BlumActionabilityAgent(thresholds).diagnose(candidate_payload()).actionability_status == "ACTIONABLE"
    low_confidence = BlumActionabilityAgent(make_thresholds(min_confidence=90.0)).diagnose(candidate_payload())
    missing_stop = BlumActionabilityAgent(thresholds).diagnose(candidate_payload(stop=None))
    assert low_confidence.actionability_status == "REJECTED_LOW_CONFIDENCE"
    assert missing_stop.actionability_status == "REJECTED_NO_STOP"
    assert "invalidation_or_stop" in missing_stop.missing_fields


def test_enrich_candidate_adds_agent_contexts_and_preserves_live_candidate_keys():
    scanner = PaperForwardOpportunityScanner()
    scanner.thresholds = make_thresholds()

    enriched = scanner.enrich_candidate(candidate_payload(), None, {"QQQ": True})

    for key in (
        "asset",
        "price_context",
        "benchmark_asset",
        "benchmark_available",
        "risk_reward_ratio",
    ):
        assert key in enriched
    for key in (
        "benchmark_context",
        "data_availability",
        "risk_reward",
        "data_quality_status",
        "tradability_status",
    ):
        assert key in enriched
    assert enriched["benchmark_context"]["benchmark_asset"] == "QQQ"
    assert enriched["benchmark_context"]["benchmark_available"] is True
    assert enriched["data_availability"]["data_quality_status"] == "OK"
    assert enriched["risk_reward"]["risk_reward_ratio"] == 2.5
    assert enriched["asset"]["benchmark_asset"] == "QQQ"
    assert enriched["price_context"]["benchmark_available"] is True


def test_classify_candidate_promotes_valid_candidate_to_trade_candidate():
    scanner = PaperForwardOpportunityScanner()
    scanner.thresholds = make_thresholds()
    enriched = scanner.enrich_candidate(candidate_payload(), None, {"QQQ": True})

    classified = scanner.classify_candidate(enriched, rank=1)

    assert classified["classification"] == TRADE_CANDIDATE
    assert classified["blocker"] == ""
    assert classified["candidate"]["paper_forward_classification"] == TRADE_CANDIDATE
    assert classified["candidate"]["opportunity_scanner"]["classification"] == TRADE_CANDIDATE


def test_classify_candidate_missing_stop_is_blocked_with_blocker():
    scanner = PaperForwardOpportunityScanner()
    scanner.thresholds = make_thresholds()
    enriched = scanner.enrich_candidate(candidate_payload(stop=None), None, {"QQQ": True})

    classified = scanner.classify_candidate(enriched, rank=1)

    assert classified["classification"] != TRADE_CANDIDATE
    assert classified["blocker"] == "missing_invalidation_or_stop"


def test_classify_candidate_missing_required_benchmark_is_data_blocked_with_benchmark_blocker():
    scanner = PaperForwardOpportunityScanner()
    scanner.thresholds = make_thresholds(require_benchmark=True)
    enriched = scanner.enrich_candidate(candidate_payload(), None, {})

    classified = scanner.classify_candidate(enriched, rank=1)

    assert classified["classification"] == DATA_BLOCKED_CANDIDATE
    assert classified["blocker"] == "BENCHMARK_UNAVAILABLE"
    assert classified["candidate"]["data_quality_status"] == "BENCHMARK_UNAVAILABLE"


def test_classify_candidate_blocks_agent_data_quality_statuses():
    scanner = PaperForwardOpportunityScanner()
    scanner.thresholds = make_thresholds()
    cases = [
        ("OHLCV_MISSING", candidate_payload(price_context={"rows": 0})),
        ("LOW_DATA_QUALITY", candidate_payload(price_context={"data_quality_score": 20.0})),
        ("PROVIDER_UNAVAILABLE", candidate_payload(data_quality_status="PROVIDER_UNAVAILABLE")),
        ("UNSUPPORTED_MARKET_DATA", candidate_payload(data_quality_status="UNSUPPORTED_MARKET_DATA")),
    ]

    for expected_blocker, payload in cases:
        enriched = scanner.enrich_candidate(payload, None, {"QQQ": True})
        classified = scanner.classify_candidate(enriched, rank=1)

        assert classified["classification"] == DATA_BLOCKED_CANDIDATE
        assert classified["blocker"] == expected_blocker
        assert classified["candidate"]["paper_forward_classification"] != TRADE_CANDIDATE


def test_classify_candidate_blocks_configured_liquidity_failure_with_clear_blocker():
    scanner = PaperForwardOpportunityScanner()
    scanner.thresholds = make_thresholds(min_liquidity_score=90.0)
    enriched = scanner.enrich_candidate(candidate_payload(price_context={"latest_volume": 100_000}), None, {"QQQ": True})

    classified = scanner.classify_candidate(enriched, rank=1)

    assert classified["classification"] == BLOCKED_CANDIDATE
    assert classified["blocker"] == "LIQUIDITY_UNKNOWN"
    assert classified["candidate"]["paper_forward_classification"] != TRADE_CANDIDATE


def test_classify_candidate_blocks_stale_price_data_with_clear_blocker():
    scanner = PaperForwardOpportunityScanner()
    scanner.thresholds = make_thresholds(scan_stale_data_max_age_hours=24.0)
    enriched = scanner.enrich_candidate(
        candidate_payload(price_context={"latest_date": "2026-06-20T00:00:00"}),
        None,
        {"QQQ": True},
    )

    classified = scanner.classify_candidate(enriched, rank=1)

    assert classified["classification"] == DATA_BLOCKED_CANDIDATE
    assert classified["blocker"] == "STALE_PRICE_DATA"
    assert classified["candidate"]["paper_forward_classification"] != TRADE_CANDIDATE


def test_benchmark_availability_map_limits_to_requested_benchmarks():
    with setup_db() as db:
        add_asset(db, "QQQ", country="USA", asset_type="ETF", exchange="NASDAQ")
        add_asset(db, "SPY", country="USA", asset_type="ETF", exchange="NYSE")
        add_asset(db, "GLD", country="USA", asset_type="ETF", exchange="NYSE")
        db.commit()

        availability = benchmark_availability_map(db, ["QQQ", "SPY"])

        assert availability == {"QQQ": True, "SPY": True}


def test_learning_acceleration_report_is_bounded():
    scanner = PaperForwardOpportunityScanner(candidate_provider=lambda db, limit: [])
    with setup_db() as db:
        report = scanner.learning_acceleration_agent.accelerate(
            db,
            scanner_summary={"top_blockers": [{"reason": "MISSING_ENTRY", "count": 3}]},
            execute=False,
        )

    assert report["enabled"] is True
    assert report["status"] in {"SCHEDULED", "COMPLETED", "THROTTLED", "NO_EVIDENCE", "scheduled", "ready", "throttled", "no_evidence"}
    assert report["safety_limits_applied"]["max_runtime_seconds"] > 0
    assert "priority_setups" in report
    assert "repeated_blockers" in report


def test_learning_acceleration_executes_bounded_learning_batches(monkeypatch):
    calls: list[dict] = []

    class FakeLearningLoopService:
        def run_batch(self, db, batch_size=None, trigger="manual", sniper_simulation_limit=None):
            calls.append({"batch_size": batch_size, "trigger": trigger, "sniper_simulation_limit": sniper_simulation_limit})
            return {
                "status": "ok",
                "run_id": f"accelerated-{len(calls)}",
                "reports_created": 2,
                "batch_size": batch_size,
                "model_version": {"status": "skipped", "reason": "threshold_not_met"},
            }

    from app.services import paper_forward_opportunity_scanner as module

    monkeypatch.setattr(module, "LearningLoopService", FakeLearningLoopService)
    with setup_db() as db:
        db.add(
            LearningFocusPriority(
                priority_type="missed_entry_replay",
                target="momentum_breakout",
                reason="missed entries need replay",
                expected_learning_value=88.0,
                urgency="high",
                status="active",
            )
        )
        db.commit()

        report = PaperForwardOpportunityScanner(candidate_provider=lambda db, limit: []).learning_acceleration_agent.accelerate(
            db,
            scanner_summary={
                "top_blockers": [{"reason": "STALE_PRICE_DATA", "count": 3}],
                "markets_scanned": ["us_equities"],
                "asset_classes_scanned": ["equities"],
            },
            execute=True,
        )

        event_row = db.scalar(select(LearningEvent).where(LearningEvent.event_type == "blum_learning_acceleration_completed").limit(1))

    assert calls
    assert len(calls) <= report["safety_limits_applied"]["max_batches_per_run"]
    assert calls[0]["trigger"] == "learning_acceleration"
    assert report["status"] == "COMPLETED"
    assert report["batches_requested"] >= 1
    assert report["batches_completed"] == len(calls)
    assert report["learning_runs"][0]["run_id"] == "accelerated-1"
    assert report["memory_updates"] >= 0
    assert event_row is not None


def test_experiment_manager_persists_structured_experiments():
    with setup_db() as db:
        report = {
            "priority_markets": ["us_equities"],
            "priority_asset_classes": ["equities"],
            "priority_setups": ["momentum_breakout"],
            "learning_runs": [{"status": "ok", "run_id": "learn-test", "reports_created": 3}],
            "batches_completed": 1,
        }

        payload = BlumExperimentManagerAgent().propose(db, acceleration_report=report)
        row = db.scalar(select(BlumLearningExperiment).where(BlumLearningExperiment.target_setup == "momentum_breakout").limit(1))

    assert payload["experiments_created"] == 1
    assert payload["experiments_completed"] == 1
    assert row is not None
    assert row.status == "COMPLETED"
    assert row.hypothesis
    assert row.benchmark_asset == "SPY"
    assert row.result_summary["run_id"] == "learn-test"
    assert row.next_action


def test_budget_wait_with_recent_productive_run_is_throttled():
    with setup_db() as db:
        productive = LearningRun(
            run_id="productive-run",
            trigger="scheduled",
            status="completed",
            predictions_created=5,
            outcomes_evaluated=5,
            memory_updates=2,
            started_at=datetime.utcnow() - timedelta(hours=2),
            completed_at=datetime.utcnow() - timedelta(hours=2),
        )
        latest = LearningRun(
            run_id="budget-wait-run",
            trigger="scheduled",
            status="budget_wait",
            predictions_created=0,
            outcomes_evaluated=0,
            memory_updates=0,
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            summary={"budget_wait_reason": "daily budget reached", "next_allowed_at": "2026-07-04T00:00:00"},
        )
        db.add_all([productive, latest])
        db.flush()

        payload = training_continuity_payload(db, latest)

    assert payload["status"] == "THROTTLED"
    assert payload["last_productive_predictions"] == 5
    assert payload["last_productive_outcomes"] == 5
    assert payload["latest_budget_wait_reason"] == "daily budget reached"
    assert payload["learning_throttle_active"] is True


def test_alpha_benchmark_gap_reports_missing_not_zero():
    payload = alpha_benchmark_gap_payload(
        sample_size=12,
        blum_return=0.15,
        benchmark_return=None,
        benchmark_excess=None,
    )

    assert payload["benchmark_available"] is False
    assert payload["walk_forward_benchmark_return"] is None
    assert payload["benchmark_blocker"] == "WALK_FORWARD_BENCHMARK_MISSING"
    assert payload["benchmark_comparison_real"] is False
