from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Asset, LearningEvent, LearningFocusPriority, PriceHistory
from app.services.trading_intelligence_lab import ActionabilityPolicy, diagnose_candidate_actionability, risk_reward_ratio_from_plan, safe_float


settings = get_settings()


TRADE_CANDIDATE = "TRADE_CANDIDATE"
WATCHLIST_CANDIDATE = "WATCHLIST_CANDIDATE"
BLOCKED_CANDIDATE = "BLOCKED_CANDIDATE"
DATA_BLOCKED_CANDIDATE = "DATA_BLOCKED_CANDIDATE"
SUPPORTED_CLASSIFICATIONS = {TRADE_CANDIDATE, WATCHLIST_CANDIDATE, BLOCKED_CANDIDATE, DATA_BLOCKED_CANDIDATE}
DATA_BLOCKING_QUALITY_STATUSES = {
    "MARKET_DATA_UNAVAILABLE",
    "OHLCV_MISSING",
    "LOW_DATA_QUALITY",
    "STALE_PRICE_DATA",
    "MARKET_NOT_ENABLED",
    "ASSET_CLASS_NOT_ENABLED",
    "MAX_ASSETS_PER_MARKET_REACHED",
    "NO_ELIGIBLE_STORED_PRICE_HISTORY",
    "NO_ASSETS_CONFIGURED",
    "BENCHMARK_UNAVAILABLE",
    "BENCHMARK_STALE",
    "BENCHMARK_PRICE_MISSING",
    "BENCHMARK_MISSING",
    "PROVIDER_UNAVAILABLE",
    "UNSUPPORTED_MARKET_DATA",
}
DATA_BLOCKING_TRADABILITY_STATUSES = {"NOT_TRADABLE_NO_PRICE"}
BLOCKING_TRADABILITY_STATUSES = {"LIQUIDITY_UNKNOWN"}
PASSING_TRADABILITY_STATUSES = {"", "TRADABLE_FOR_PAPER", "PAPER_ONLY_ASSET_CLASS"}


CandidateProvider = Callable[[Session, int], list[dict]]


@dataclass(frozen=True)
class ScannerThresholds:
    min_confidence: float
    min_risk_reward: float
    min_data_quality: float
    max_candidates_per_run: int
    allow_watchlist_candidates: bool
    allow_trade_candidates: bool
    enabled_markets: tuple[str, ...]
    enabled_asset_classes: tuple[str, ...]
    require_benchmark: bool
    min_liquidity_score: float
    max_assets_per_market: int
    scan_stale_data_max_age_hours: float
    cross_market_ranking_enabled: bool

    def to_dict(self) -> dict:
        return {
            "paper_forward_min_confidence": self.min_confidence,
            "paper_forward_min_risk_reward": self.min_risk_reward,
            "paper_forward_min_data_quality": self.min_data_quality,
            "paper_forward_max_candidates_per_run": self.max_candidates_per_run,
            "paper_forward_allow_watchlist_candidates": self.allow_watchlist_candidates,
            "paper_forward_allow_trade_candidates": self.allow_trade_candidates,
            "paper_forward_enabled_markets": list(self.enabled_markets),
            "paper_forward_enabled_asset_classes": list(self.enabled_asset_classes),
            "paper_forward_require_benchmark": self.require_benchmark,
            "paper_forward_min_liquidity_score": self.min_liquidity_score,
            "paper_forward_max_assets_per_market": self.max_assets_per_market,
            "paper_forward_scan_stale_data_max_age_hours": self.scan_stale_data_max_age_hours,
            "paper_forward_cross_market_ranking_enabled": self.cross_market_ranking_enabled,
        }


class BlumBenchmarkAgent:
    """Resolve benchmark context for a paper-forward candidate."""

    def assess(self, candidate: dict, asset: Asset | None, benchmarks: dict[str, bool | dict]) -> dict:
        ticker = normalize_ticker(candidate.get("ticker"))
        asset_payload = candidate.get("asset") if isinstance(candidate.get("asset"), dict) else {}
        asset_type = asset_payload.get("asset_type") or getattr(asset, "asset_type", None) or "Unknown"
        market = market_key(asset or asset_payload)
        asset_class = asset_class_key(asset or asset_payload)
        benchmark = benchmark_for(asset_type=asset_type, market=market, sector=asset_payload.get("sector") or getattr(asset, "sector", ""))
        benchmark_status = benchmarks.get(normalize_ticker(benchmark))
        if isinstance(benchmark_status, dict):
            benchmark_available = bool(benchmark_status.get("benchmark_available"))
            benchmark_blocker = str(benchmark_status.get("benchmark_blocker") or "")
            latest_benchmark_date = benchmark_status.get("latest_benchmark_date")
        else:
            benchmark_available = bool(benchmark_status)
            benchmark_blocker = "" if benchmark_available else "BENCHMARK_UNAVAILABLE"
            latest_benchmark_date = None
        return {
            "ticker": ticker,
            "asset_type": asset_type,
            "market": market,
            "asset_class": asset_class,
            "benchmark_asset": benchmark,
            "benchmark_available": benchmark_available,
            "benchmark_blocker": benchmark_blocker,
            "latest_benchmark_date": latest_benchmark_date,
        }


class BlumDataAvailabilityAgent:
    """Assess stored market data quality and paper tradability."""

    def __init__(self, thresholds: ScannerThresholds):
        self.thresholds = thresholds

    def assess(self, candidate: dict, benchmark_context: dict) -> dict:
        price_context = candidate.get("price_context") if isinstance(candidate.get("price_context"), dict) else {}
        latest_price = safe_float(price_context.get("latest_price"), None)
        latest_volume = safe_float(price_context.get("latest_volume"), None)
        liquidity_score = liquidity_score_for(price_context, latest_price, latest_volume)
        upstream_status = str(candidate.get("data_quality_status") or price_context.get("data_quality_status") or "").strip().upper()
        if data_quality_blocker({"data_quality_status": upstream_status}):
            data_quality_status = upstream_status
        else:
            data_quality_status = data_quality_status_for(
                price_context,
                bool(benchmark_context.get("benchmark_available")),
                self.thresholds.require_benchmark,
                min_data_quality=self.thresholds.min_data_quality,
                max_stale_hours=self.thresholds.scan_stale_data_max_age_hours,
            )
        benchmark_blocker = str(benchmark_context.get("benchmark_blocker") or "").strip().upper()
        if self.thresholds.require_benchmark and benchmark_blocker in DATA_BLOCKING_QUALITY_STATUSES:
            data_quality_status = benchmark_blocker
        tradability_status = tradability_status_for(
            str(benchmark_context.get("asset_type") or "Unknown"),
            latest_price,
            liquidity_score,
            self.thresholds.min_liquidity_score,
        )
        return {
            "latest_price": latest_price,
            "latest_volume": latest_volume,
            "liquidity_context": {"liquidity_score": liquidity_score, "latest_volume": latest_volume},
            "data_quality_status": data_quality_status,
            "tradability_status": tradability_status,
        }


class BlumRiskRewardAgent:
    """Compute risk/reward context using the lab's canonical trade-plan rules."""

    def assess(self, candidate: dict, latest_price: float | None) -> dict:
        plan = candidate.get("trade_plan") if isinstance(candidate.get("trade_plan"), dict) else {}
        risk_reward = risk_reward_ratio_from_plan(plan, latest_price)
        return {
            "risk_reward_ratio": risk_reward,
            "entry_trigger": plan.get("entry_trigger") or plan.get("confirmation_condition"),
            "stop_price": plan.get("invalidation_level") or plan.get("stop_price") or plan.get("stop_loss"),
            "target_1": plan.get("target_1"),
            "target_2": plan.get("target_2"),
        }


class BlumActionabilityAgent:
    """Diagnose actionability without creating scanner or settings coupling."""

    def __init__(self, thresholds: ScannerThresholds):
        self.thresholds = thresholds

    def diagnose(self, candidate: dict):
        policy = ActionabilityPolicy(
            minimum_data_quality=self.thresholds.min_data_quality,
            minimum_confidence=self.thresholds.min_confidence,
            minimum_reward_to_risk=self.thresholds.min_risk_reward,
        )
        return diagnose_candidate_actionability(candidate, strict=True, policy=policy)


class BlumCrossMarketRankerAgent:
    """Order classified opportunities without hiding the scanner input order when disabled."""

    def __init__(self, thresholds: ScannerThresholds):
        self.thresholds = thresholds

    def rank(self, classified: list[dict]) -> list[dict]:
        if not self.thresholds.cross_market_ranking_enabled:
            return list(classified)
        return sorted(classified, key=lambda item: item["score"], reverse=True)


class BlumLearningAccelerationAgent:
    """Create bounded learning-focus metadata from stored evidence only."""

    def accelerate(self, db: Session, *, scanner_summary: dict) -> dict:
        if not settings.blum_learning_acceleration_enabled:
            return {"enabled": False, "status": "disabled", "batches_scheduled": 0, "batches_completed": 0}

        max_batches = max(1, int(settings.blum_learning_acceleration_max_batches_per_run))
        top_blockers = scanner_summary.get("top_blockers") or []
        repeated_blockers = [row for row in top_blockers if int(row.get("count") or 0) >= 2][:max_batches]
        focus_rows = db.scalars(
            select(LearningFocusPriority)
            .where(LearningFocusPriority.status.in_(["active", "proposed"]))
            .order_by(desc(LearningFocusPriority.expected_learning_value), desc(LearningFocusPriority.created_at))
            .limit(max_batches)
        ).all()

        priority_setups = [str(row.target) for row in focus_rows if row.target][:max_batches]
        batches = min(max_batches, len(focus_rows) + len(repeated_blockers))
        return {
            "enabled": True,
            "last_run_at": datetime.utcnow().isoformat(),
            "status": "ready" if batches else "no_evidence",
            "learning_acceleration_mode": "bounded_replay_planning",
            "additional_replay_batches_scheduled": batches,
            "additional_walk_forward_batches_scheduled": min(len(focus_rows), max_batches),
            "batches_scheduled": batches,
            "batches_completed": 0,
            "priority_markets": scanner_summary.get("markets_scanned") or [],
            "priority_asset_classes": scanner_summary.get("asset_classes_scanned") or [],
            "priority_setups": priority_setups,
            "uncertainty_targets": [row.target for row in focus_rows if row.priority_type in {"weak_promising_setup", "weakness_replay"}],
            "missed_opportunity_targets": [row.target for row in focus_rows if "missed" in str(row.priority_type or "")],
            "repeated_blockers": repeated_blockers,
            "estimated_learning_gain": round(sum(float(row.expected_learning_value or 0.0) for row in focus_rows), 4),
            "safety_limits_applied": {
                "max_batches_per_run": max_batches,
                "max_assets_per_run": settings.blum_learning_acceleration_max_assets_per_run,
                "max_runtime_seconds": settings.blum_learning_acceleration_max_runtime_seconds,
                "budget_guard_enabled": settings.blum_learning_acceleration_budget_guard_enabled,
            },
            "next_acceleration_action": "Run bounded replay or walk-forward validation from backend scheduler/manual endpoint.",
        }


class BlumExperimentManagerAgent:
    """Propose reversible experiments from acceleration metadata."""

    def propose(self, db: Session, *, acceleration_report: dict) -> dict:
        if not settings.blum_experiment_manager_enabled:
            return {"enabled": False, "status": "disabled", "active_experiments": [], "completed_experiments": []}

        priorities = acceleration_report.get("priority_setups") or []
        experiments = [
            {
                "experiment_id": f"exp-{normalize_ticker(target) or 'UNKNOWN'}",
                "hypothesis": f"Replay {target} and compare entry trigger quality versus benchmark-relative outcome.",
                "setup_type": target,
                "training_window": "stored_historical_replay",
                "validation_window": "walk_forward_when_available",
                "benchmark": settings.default_benchmark,
                "status": "proposed",
            }
            for target in priorities[: max(1, int(settings.blum_experiment_max_active_experiments))]
        ]
        return {
            "enabled": True,
            "status": "proposed" if experiments else "no_priority",
            "active_experiments": experiments,
            "completed_experiments": [],
            "best_experiment": experiments[0] if experiments else None,
            "rejected_experiments": [],
            "promoted_rules": [],
            "blocked_promotions_reason": "Experiments require out-of-sample evidence before rule promotion.",
        }


class PaperForwardOpportunityScanner:
    """Classify current market evidence into auditable paper-forward candidates.

    The scanner does not open positions. It only turns existing BLUM market
    intelligence into classified candidate payloads and a cross-market report.
    """

    def __init__(self, *, candidate_provider: CandidateProvider | None = None):
        self.candidate_provider = candidate_provider
        self.last_universe_report: dict | None = None
        self.learning_acceleration_agent = BlumLearningAccelerationAgent()
        self.experiment_manager_agent = BlumExperimentManagerAgent()
        self.thresholds = ScannerThresholds(
            min_confidence=float(settings.paper_forward_min_confidence),
            min_risk_reward=float(settings.paper_forward_min_risk_reward),
            min_data_quality=float(settings.paper_forward_min_data_quality),
            max_candidates_per_run=max(1, int(settings.paper_forward_max_candidates_per_run)),
            allow_watchlist_candidates=bool(settings.paper_forward_allow_watchlist_candidates),
            allow_trade_candidates=bool(settings.paper_forward_allow_trade_candidates),
            enabled_markets=parse_csv(settings.paper_forward_enabled_markets),
            enabled_asset_classes=parse_csv(settings.paper_forward_enabled_asset_classes),
            require_benchmark=bool(settings.paper_forward_require_benchmark),
            min_liquidity_score=float(settings.paper_forward_min_liquidity_score),
            max_assets_per_market=max(1, int(settings.paper_forward_max_assets_per_market)),
            scan_stale_data_max_age_hours=max(0.0, float(settings.paper_forward_scan_stale_data_max_age_hours)),
            cross_market_ranking_enabled=bool(settings.paper_forward_cross_market_ranking_enabled),
        )

    def scan(self, db: Session, *, limit: int | None = None) -> dict:
        max_items = max(1, min(int(limit or self.thresholds.max_candidates_per_run), self.thresholds.max_candidates_per_run))
        raw_candidates = self.raw_candidates(db, max_items)
        assets_by_ticker = assets_for_candidates(db, raw_candidates)
        benchmark_availability = benchmark_availability_details_map(
            db,
            required_benchmark_tickers(raw_candidates, assets_by_ticker),
            max_stale_hours=self.thresholds.scan_stale_data_max_age_hours,
        )

        classified: list[dict] = []
        for rank, candidate in enumerate(raw_candidates, start=1):
            enriched = self.enrich_candidate(candidate, assets_by_ticker.get(normalize_ticker(candidate.get("ticker"))), benchmark_availability)
            classified.append(self.classify_candidate(enriched, rank))

        summary = self.summary(db, classified)
        summary["learning_acceleration"] = self.learning_acceleration_agent.accelerate(db, scanner_summary=summary)
        summary["experiment_manager"] = self.experiment_manager_agent.propose(db, acceleration_report=summary["learning_acceleration"])
        db.add(
            LearningEvent(
                event_type="paper_forward_opportunity_scan_completed",
                severity="Info",
                title="Paper-forward opportunity scan completed",
                description=summary["reason_if_no_trade_candidates"] or "Paper-forward scan produced classified opportunities.",
                payload={
                    "scanned_count": summary["scanned_count"],
                    "trade_candidate_count": summary["trade_candidate_count"],
                    "watchlist_candidate_count": summary["watchlist_candidate_count"],
                    "blocked_candidate_count": summary["blocked_candidate_count"],
                    "data_blocked_candidate_count": summary["data_blocked_candidate_count"],
                    "markets_scanned": summary["markets_scanned"],
                    "asset_classes_scanned": summary["asset_classes_scanned"],
                    "skipped_markets": summary["skipped_markets"],
                    "thresholds": summary["thresholds"],
                    "learning_acceleration": summary["learning_acceleration"],
                    "experiment_manager": summary["experiment_manager"],
                },
            )
        )
        db.add(
            LearningEvent(
                event_type="OPPORTUNITY_SCANNED",
                severity="Info",
                title="Paper-forward opportunities scanned",
                description=summary["reason_if_no_trade_candidates"] or "Paper-forward scanner classified current stored market opportunities.",
                payload={
                    "generated_at": summary["generated_at"],
                    "scanner": summary["scanner"],
                    "scanned_count": summary["scanned_count"],
                    "trade_candidate_count": summary["trade_candidate_count"],
                    "watchlist_candidate_count": summary["watchlist_candidate_count"],
                    "blocked_candidate_count": summary["blocked_candidate_count"],
                    "data_blocked_candidate_count": summary["data_blocked_candidate_count"],
                    "top_blockers": summary["top_blockers"],
                    "best_trade_candidate": summary["best_trade_candidate"],
                    "best_watchlist_candidate": summary["best_watchlist_candidate"],
                    "best_cross_market_candidate": summary["best_cross_market_candidate"],
                    "reason_if_no_trade_candidates": summary["reason_if_no_trade_candidates"],
                    "markets_scanned": summary["markets_scanned"],
                    "asset_classes_scanned": summary["asset_classes_scanned"],
                    "assets_scanned_by_market": summary["assets_scanned_by_market"],
                    "trade_candidates_by_market": summary["trade_candidates_by_market"],
                    "watchlist_candidates_by_market": summary["watchlist_candidates_by_market"],
                    "blocked_candidates_by_market": summary["blocked_candidates_by_market"],
                    "data_blocked_candidates_by_market": summary["data_blocked_candidates_by_market"],
                    "skipped_markets": summary["skipped_markets"],
                    "reason_if_markets_were_skipped": summary["reason_if_markets_were_skipped"],
                    "next_possible_action": summary["next_possible_action"],
                    "thresholds": summary["thresholds"],
                    "learning_acceleration": summary["learning_acceleration"],
                    "experiment_manager": summary["experiment_manager"],
                },
            )
        )
        if summary.get("best_cross_market_candidate"):
            db.add(
                LearningEvent(
                    event_type="CROSS_MARKET_RANKED",
                    severity="Info",
                    title="Paper-forward cross-market ranking completed",
                    description="Best current paper-forward candidate selected from the cross-market scan.",
                    payload={
                        "best_cross_market_candidate": summary["best_cross_market_candidate"],
                        "markets_scanned": summary["markets_scanned"],
                        "asset_classes_scanned": summary["asset_classes_scanned"],
                    },
                )
            )
        for skipped_market in summary.get("skipped_markets", []) or []:
            db.add(
                LearningEvent(
                    event_type="MARKET_SKIPPED",
                    severity="Warning",
                    title=f"{skipped_market.get('market', 'unknown')} market skipped",
                    description=skipped_market.get("reason") or "Market skipped during paper-forward opportunity scan.",
                    payload=skipped_market,
                )
            )
        return summary

    def raw_candidates(self, db: Session, limit: int) -> list[dict]:
        universe = BlumMarketUniverseAgent(self.thresholds).build(db)
        self.last_universe_report = universe
        eligible_tickers = {normalize_ticker(asset.ticker) for asset in universe.get("eligible_asset_objects", [])}
        skipped_reasons = {
            normalize_ticker(row.get("ticker")): str(row.get("reason") or "MARKET_DATA_UNAVAILABLE")
            for row in universe.get("skipped_assets_with_reasons", [])
            if normalize_ticker(row.get("ticker"))
        }
        candidates: list[dict] = []
        seen: set[str] = set()

        def add(item: dict, source: str) -> None:
            ticker = normalize_ticker(item.get("ticker"))
            if not ticker or ticker in seen:
                return
            if ticker not in eligible_tickers:
                item = out_of_universe_payload(item, skipped_reasons.get(ticker, "MARKET_DATA_UNAVAILABLE"))
            payload = {**item, "scouting_source": source, "scouting_policy": "global_market_universe_stored_evidence_only"}
            seen.add(ticker)
            candidates.append(payload)

        if self.candidate_provider is not None:
            for item in dedupe_candidates(self.candidate_provider(db, limit)):
                add(item, "candidate_provider")
                if len(candidates) >= limit:
                    break
            return candidates[:limit]

        from app.services.market_sniper import MarketSniperEngine

        engine = MarketSniperEngine()

        try:
            payload = engine.candidates(db, limit=limit, persist=False)
            for item in payload.get("candidates", []) or []:
                add(item, "market_sniper_ranked_signals")
        except Exception as exc:
            db.add(scanner_event("MARKET_SKIPPED", "market_sniper_ranked_signals", f"{type(exc).__name__}: {exc}", {"source": "market_sniper"}))

        if len(candidates) < limit:
            for asset in (universe.get("eligible_asset_objects") or [])[: max(limit * 5, limit)]:
                if normalize_ticker(asset.ticker) in seen:
                    continue
                try:
                    add(engine.evaluate_asset(db, asset, persist=False), "global_ohlcv_universe")
                except Exception as exc:
                    add(data_blocked_payload(asset, f"UNSUPPORTED_MARKET_DATA: {type(exc).__name__}: {exc}"), "global_ohlcv_universe")
                if len(candidates) >= limit:
                    break
        return candidates[:limit]

    def enrich_candidate(self, candidate: dict, asset: Asset | None, benchmarks: dict[str, bool]) -> dict:
        ticker = normalize_ticker(candidate.get("ticker"))
        asset_payload = candidate.get("asset") if isinstance(candidate.get("asset"), dict) else {}
        benchmark_context = BlumBenchmarkAgent().assess(candidate, asset, benchmarks)
        asset_type = benchmark_context["asset_type"]
        market = benchmark_context["market"]
        asset_class = benchmark_context["asset_class"]
        benchmark = benchmark_context["benchmark_asset"]
        benchmark_available = benchmark_context["benchmark_available"]
        price_context = candidate.get("price_context") if isinstance(candidate.get("price_context"), dict) else {}
        data_availability = BlumDataAvailabilityAgent(self.thresholds).assess(candidate, benchmark_context)
        latest_price = data_availability["latest_price"]
        liquidity_context = data_availability["liquidity_context"]
        data_quality_status = data_availability["data_quality_status"]
        tradability_status = data_availability["tradability_status"]
        risk_reward = BlumRiskRewardAgent().assess(candidate, latest_price)
        enriched_asset = {
            **asset_payload,
            "ticker": ticker,
            "name": asset_payload.get("name") or getattr(asset, "name", ticker),
            "asset_type": asset_type,
            "market": market,
            "exchange": asset_payload.get("exchange") or getattr(asset, "exchange", ""),
            "currency": asset_payload.get("currency") or getattr(asset, "currency", ""),
            "country": asset_payload.get("country") or getattr(asset, "country", ""),
            "sector": asset_payload.get("sector") or getattr(asset, "sector", ""),
            "industry": asset_payload.get("industry") or getattr(asset, "industry", ""),
            "asset_class": asset_class,
            "benchmark_asset": benchmark,
            "benchmark_available": benchmark_available,
            "liquidity_context": liquidity_context,
            "data_quality_status": data_quality_status,
            "tradability_status": tradability_status,
        }
        enriched_price_context = {
            **price_context,
            "latest_price": latest_price,
            "benchmark_asset": benchmark,
            "benchmark_available": benchmark_available,
            "data_quality_status": data_quality_status,
            "tradability_status": tradability_status,
            "liquidity_score": liquidity_context["liquidity_score"],
        }
        return {
            **candidate,
            "ticker": ticker,
            "asset": enriched_asset,
            "price_context": enriched_price_context,
            "benchmark_asset": benchmark,
            "benchmark_available": benchmark_available,
            "benchmark_context": benchmark_context,
            "data_availability": data_availability,
            "liquidity_context": enriched_asset["liquidity_context"],
            "data_quality_status": data_quality_status,
            "tradability_status": tradability_status,
            "risk_reward": risk_reward,
            "risk_reward_ratio": risk_reward["risk_reward_ratio"],
        }

    def classify_candidate(self, candidate: dict, rank: int) -> dict:
        diagnosis = BlumActionabilityAgent(self.thresholds).diagnose(candidate)
        asset = candidate.get("asset") or {}
        data_blocker = data_quality_blocker(candidate) or data_tradability_blocker(candidate)
        tradability_blocker_status = tradability_blocker(candidate)
        if self.thresholds.require_benchmark and not candidate.get("benchmark_available"):
            data_blocker = data_blocker or "BENCHMARK_UNAVAILABLE"
        if data_blocker or diagnosis.actionability_status == "DATA_BLOCKED":
            classification = DATA_BLOCKED_CANDIDATE
        elif tradability_blocker_status:
            classification = BLOCKED_CANDIDATE
        elif diagnosis.actionability_status == "ACTIONABLE" and self.thresholds.allow_trade_candidates:
            classification = TRADE_CANDIDATE
        elif (diagnosis.should_wait or near_candidate(diagnosis, self.thresholds)) and self.thresholds.allow_watchlist_candidates:
            classification = WATCHLIST_CANDIDATE
        else:
            classification = BLOCKED_CANDIDATE

        score = score_for(candidate, diagnosis, classification)
        candidate_payload = {
            **candidate,
            "paper_forward_classification": classification,
            "classification_reason": classification_reason(classification, diagnosis, candidate),
            "scanner_rank": rank,
            "tradability_status": candidate.get("tradability_status"),
            "data_quality_status": candidate.get("data_quality_status"),
            "asset": {
                **asset,
                "benchmark_asset": candidate.get("benchmark_asset"),
                "data_quality_status": candidate.get("data_quality_status"),
                "tradability_status": candidate.get("tradability_status"),
            },
            "opportunity_scanner": {
                "classification": classification,
                "rank": rank,
                "score": score,
                "thresholds": self.thresholds.to_dict(),
                "diagnosis": diagnosis.to_dict(),
                "market": asset.get("market"),
                "asset_class": asset.get("asset_class"),
                "benchmark_asset": candidate.get("benchmark_asset"),
            },
        }
        return {
            "classification": classification,
            "candidate": candidate_payload,
            "diagnosis": diagnosis.to_dict(),
            "rank": rank,
            "ticker": candidate.get("ticker"),
            "market": asset.get("market") or "unknown",
            "asset_class": asset.get("asset_class") or "unknown",
            "asset_type": asset.get("asset_type") or "Unknown",
            "score": score,
            "blocker": blocker_for(classification, diagnosis, candidate_payload),
        }

    def summary(self, db: Session, classified: list[dict]) -> dict:
        counts = Counter(item["classification"] for item in classified)
        by_market = grouped_counts(classified, "market")
        by_class = grouped_counts(classified, "asset_class")
        ranked_items = BlumCrossMarketRankerAgent(self.thresholds).rank(classified)
        trade_items = [item for item in ranked_items if item["classification"] == TRADE_CANDIDATE]
        watch_items = [item for item in ranked_items if item["classification"] == WATCHLIST_CANDIDATE]
        blocked_items = [item for item in ranked_items if item["classification"] == BLOCKED_CANDIDATE]
        data_blocked_items = [item for item in ranked_items if item["classification"] == DATA_BLOCKED_CANDIDATE]
        best_cross_market = ranked_items[0] if ranked_items else None
        configured_market_report = self.last_universe_report or configured_market_coverage(db, self.thresholds, classified)
        skipped_markets = configured_market_report.get("skipped_markets") or configured_market_report.get("markets_skipped") or []
        skipped_reason = configured_market_report.get("reason_if_markets_were_skipped") or skipped_reason_text(skipped_markets)
        top_blockers = [{"reason": reason, "count": count} for reason, count in Counter(item["blocker"] for item in classified if item["blocker"]).most_common(8)]
        reason = no_trade_reason(counts, top_blockers)
        return {
            "status": "ok",
            "generated_at": datetime.utcnow().isoformat(),
            "scanner": "PaperForwardOpportunityScanner",
            "thresholds": self.thresholds.to_dict(),
            "scanned_count": len(classified),
            "trade_candidate_count": counts.get(TRADE_CANDIDATE, 0),
            "watchlist_candidate_count": counts.get(WATCHLIST_CANDIDATE, 0),
            "blocked_candidate_count": counts.get(BLOCKED_CANDIDATE, 0),
            "data_blocked_candidate_count": counts.get(DATA_BLOCKED_CANDIDATE, 0),
            "created_trade_candidates": [],
            "created_watchlist_candidates": [],
            "created_blocked_candidates": [],
            "created_data_blocked_candidates": [],
            "duplicates": [],
            "top_blockers": top_blockers,
            "best_trade_candidate": scanner_item_payload(trade_items[0]) if trade_items else None,
            "best_watchlist_candidate": scanner_item_payload(watch_items[0]) if watch_items else None,
            "best_cross_market_candidate": scanner_item_payload(best_cross_market) if best_cross_market else None,
            "reason_if_no_trade_candidates": reason,
            "markets_scanned": configured_market_report["markets_scanned"],
            "asset_classes_scanned": configured_market_report["asset_classes_scanned"],
            "assets_scanned_by_market": configured_market_report.get("assets_scanned_by_market") or configured_market_report.get("assets_by_market") or {},
            "trade_candidates_by_market": classification_by_market(classified, TRADE_CANDIDATE),
            "watchlist_candidates_by_market": classification_by_market(classified, WATCHLIST_CANDIDATE),
            "blocked_candidates_by_market": classification_by_market(classified, BLOCKED_CANDIDATE),
            "data_blocked_candidates_by_market": classification_by_market(classified, DATA_BLOCKED_CANDIDATE),
            "skipped_markets": skipped_markets,
            "reason_if_markets_were_skipped": skipped_reason,
            "latest_trade_candidates": [scanner_item_payload(item) for item in trade_items[:8]],
            "latest_watchlist_candidates": [scanner_item_payload(item) for item in watch_items[:8]],
            "latest_blocked_candidates": [scanner_item_payload(item) for item in blocked_items[:8]],
            "latest_data_blocked_candidates": [scanner_item_payload(item) for item in data_blocked_items[:8]],
            "blocker_breakdown": top_blockers,
            "candidate_payloads_for_persistence": [item["candidate"] for item in classified],
            "next_possible_action": next_possible_action(counts, top_blockers),
        }


def scanner_event(event_type: str, title: str, description: str, payload: dict) -> LearningEvent:
    return LearningEvent(event_type=event_type, severity="Warning", title=title, description=description, payload=payload)


def dedupe_candidates(rows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    output: list[dict] = []
    for row in rows:
        ticker = normalize_ticker(row.get("ticker"))
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        output.append(row)
    return output


def out_of_universe_payload(candidate: dict, reason: str) -> dict:
    asset = candidate.get("asset") if isinstance(candidate.get("asset"), dict) else {}
    price_context = candidate.get("price_context") if isinstance(candidate.get("price_context"), dict) else {}
    return {
        **candidate,
        "asset": asset,
        "actionability": "avoid",
        "data_quality_status": reason,
        "tradability_status": candidate.get("tradability_status") or "NOT_TRADABLE_NO_PRICE",
        "price_context": {**price_context, "data_quality_status": reason},
        "explanation": f"Blocked by configured scanner universe: {reason}.",
        "scanner_universe_blocker": reason,
    }


def parse_csv(value: str | None) -> tuple[str, ...]:
    return tuple(item.strip().lower() for item in str(value or "").split(",") if item.strip())


def normalize_ticker(value: object) -> str:
    return str(value or "").strip().upper()


def assets_for_candidates(db: Session, candidates: list[dict]) -> dict[str, Asset]:
    tickers = [normalize_ticker(row.get("ticker")) for row in candidates if normalize_ticker(row.get("ticker"))]
    if not tickers:
        return {}
    rows = db.scalars(select(Asset).where(Asset.ticker.in_(tickers))).all()
    return {normalize_ticker(row.ticker): row for row in rows}


def required_benchmark_tickers(candidates: list[dict], assets_by_ticker: dict[str, Asset]) -> list[str]:
    tickers: list[str] = []
    seen: set[str] = set()
    agent = BlumBenchmarkAgent()
    for candidate in candidates:
        ticker = normalize_ticker(candidate.get("ticker"))
        benchmark = normalize_ticker(agent.assess(candidate, assets_by_ticker.get(ticker), {})["benchmark_asset"])
        if benchmark and benchmark not in seen:
            seen.add(benchmark)
            tickers.append(benchmark)
    return tickers


def benchmark_availability_details_map(
    db: Session,
    benchmark_tickers: list[str] | tuple[str, ...] | set[str] | None = None,
    *,
    max_stale_hours: float | None = None,
) -> dict[str, dict]:
    query = (
        select(
            Asset.ticker,
            func.count(PriceHistory.id).label("rows_count"),
            func.max(PriceHistory.date).label("latest_market_date"),
        )
        .join(PriceHistory, PriceHistory.asset_id == Asset.id)
        .group_by(Asset.ticker)
    )
    if benchmark_tickers is not None:
        normalized = sorted({normalize_ticker(ticker) for ticker in benchmark_tickers if normalize_ticker(ticker)})
        if not normalized:
            return {}
        query = query.where(Asset.ticker.in_(normalized))
    rows = db.execute(query).all()
    output: dict[str, dict] = {}
    for ticker, count, latest_market_date in rows:
        latest_dt = parse_market_datetime(latest_market_date)
        is_stale = False
        if max_stale_hours and max_stale_hours > 0 and latest_dt is not None:
            is_stale = latest_dt < datetime.utcnow() - timedelta(hours=max_stale_hours)
        if count <= 0:
            blocker = "BENCHMARK_PRICE_MISSING"
        elif is_stale:
            blocker = "BENCHMARK_STALE"
        else:
            blocker = ""
        output[normalize_ticker(ticker)] = {
            "benchmark_available": bool(count > 0 and not is_stale),
            "benchmark_blocker": blocker,
            "latest_benchmark_date": latest_dt.isoformat() if latest_dt else None,
            "rows": int(count or 0),
        }
    return output


def benchmark_availability_map(db: Session, benchmark_tickers: list[str] | tuple[str, ...] | set[str] | None = None) -> dict[str, bool]:
    details = benchmark_availability_details_map(db, benchmark_tickers)
    return {ticker: bool(payload.get("benchmark_available")) for ticker, payload in details.items()}


class BlumMarketUniverseAgent:
    """Build the bounded stored-data universe available to the scanner."""

    def __init__(self, thresholds: ScannerThresholds):
        self.thresholds = thresholds

    def build(self, db: Session) -> dict:
        requested_markets = list(self.thresholds.enabled_markets)
        requested_asset_classes = list(self.thresholds.enabled_asset_classes)
        latest_price_history = (
            select(
                PriceHistory.asset_id.label("asset_id"),
                func.max(PriceHistory.date).label("latest_market_date"),
            )
            .group_by(PriceHistory.asset_id)
            .subquery()
        )
        asset_rows = db.execute(
            select(Asset, latest_price_history.c.latest_market_date)
            .join(latest_price_history, latest_price_history.c.asset_id == Asset.id)
            .where(Asset.is_active.is_(True))
            .order_by(Asset.ticker)
        ).all()

        eligible: list[Asset] = []
        skipped_assets: list[dict] = []
        assets_by_market: dict[str, list[str]] = defaultdict(list)
        assets_by_asset_class: dict[str, list[str]] = defaultdict(list)
        per_market_counts: dict[str, int] = defaultdict(int)

        for asset, latest_market_date in asset_rows:
            ticker = normalize_ticker(asset.ticker)
            market = market_key(asset)
            asset_class = asset_class_key(asset)
            skip_reason = self._skip_reason(market, asset_class, per_market_counts[market], latest_market_date)
            if skip_reason:
                skipped_assets.append(
                    {
                        "ticker": ticker,
                        "market": market,
                        "asset_class": asset_class,
                        "reason": skip_reason,
                    }
                )
                continue

            eligible.append(asset)
            per_market_counts[market] += 1
            assets_by_market[market].append(ticker)
            assets_by_asset_class[asset_class].append(ticker)

        markets_scanned = ordered_requested_keys(requested_markets, assets_by_market)
        asset_classes_scanned = ordered_requested_keys(requested_asset_classes, assets_by_asset_class)
        markets_skipped = skipped_requested_keys(requested_markets, markets_scanned, "market")
        asset_classes_skipped = skipped_requested_keys(requested_asset_classes, asset_classes_scanned, "asset_class")

        return {
            "markets_requested": requested_markets,
            "markets_scanned": markets_scanned,
            "markets_skipped": markets_skipped,
            "reason_if_markets_were_skipped": skipped_reason_text(markets_skipped),
            "asset_classes_requested": requested_asset_classes,
            "asset_classes_scanned": asset_classes_scanned,
            "asset_classes_skipped": asset_classes_skipped,
            "reason_if_asset_classes_were_skipped": skipped_reason_text(asset_classes_skipped),
            "assets_by_market": dict(assets_by_market),
            "assets_by_asset_class": dict(assets_by_asset_class),
            "total_assets_discovered": len(asset_rows),
            "total_assets_eligible": len(eligible),
            "skipped_assets_with_reasons": skipped_assets,
            "eligible_assets": [normalize_ticker(asset.ticker) for asset in eligible],
            "eligible_asset_objects": eligible,
        }

    def _skip_reason(self, market: str, asset_class: str, current_market_count: int, latest_market_date) -> str:
        if asset_class not in self.thresholds.enabled_asset_classes:
            return "ASSET_CLASS_NOT_ENABLED"
        if market not in self.thresholds.enabled_markets:
            return "MARKET_NOT_ENABLED"
        if current_market_count >= self.thresholds.max_assets_per_market:
            return "MAX_ASSETS_PER_MARKET_REACHED"
        latest_dt = parse_market_datetime(latest_market_date)
        if self.thresholds.scan_stale_data_max_age_hours > 0 and latest_dt is not None:
            stale_after = datetime.utcnow() - timedelta(hours=self.thresholds.scan_stale_data_max_age_hours)
            if latest_dt < stale_after:
                return "STALE_PRICE_DATA"
        return ""


def ordered_requested_keys(requested: list[str], grouped: dict[str, list[str]]) -> list[str]:
    return [key for key in requested if grouped.get(key)]


def skipped_requested_keys(requested: list[str], scanned: list[str], kind: str) -> list[dict]:
    scanned_set = set(scanned)
    return [{kind: key, "reason": "NO_ELIGIBLE_STORED_PRICE_HISTORY"} for key in requested if key not in scanned_set]


def skipped_reason_text(skipped: list[dict]) -> str:
    if not skipped:
        return ""
    return "; ".join(f"{next((value for key, value in item.items() if key != 'reason'), 'unknown')}: {item['reason']}" for item in skipped)


def market_universe_assets(db: Session, thresholds: ScannerThresholds, *, limit: int) -> list[Asset]:
    return BlumMarketUniverseAgent(thresholds).build(db)["eligible_asset_objects"][:limit]



def market_key(asset: Asset | dict) -> str:
    asset_type = value_from(asset, "asset_type").lower()
    category = value_from(asset, "category").lower()
    country = value_from(asset, "country").lower()
    exchange = value_from(asset, "exchange").lower()
    if "crypto" in asset_type or "crypto" in category:
        return "crypto"
    if "forex" in asset_type or "fx" in category:
        return "forex"
    if "commodity" in asset_type or "commodity" in category:
        return "commodities"
    if "bond" in asset_type or "rate" in category or "treasury" in category:
        return "bonds"
    if "volatility" in asset_type or "volatility" in category or "vix" in asset_type or "vix" in category:
        return "volatility"
    if "index" in asset_type:
        return "indexes"
    if "etf" in asset_type:
        return "etfs"
    if country in {"usa", "us", "united states"} or exchange in {"nyse", "nasdaq", "amex"}:
        return "us_equities"
    if country in {"germany", "france", "italy", "spain", "netherlands", "united kingdom", "uk"}:
        return "european_equities"
    return "global_equities"


def asset_class_key(asset: Asset | dict) -> str:
    asset_type = value_from(asset, "asset_type").lower()
    category = value_from(asset, "category").lower()
    if "stock" in asset_type or "equity" in asset_type:
        return "equities"
    if "etf" in asset_type:
        return "etfs"
    if "volatility" in asset_type or "volatility" in category or "vix" in asset_type or "vix" in category:
        return "volatility"
    if "index" in asset_type:
        return "indexes"
    if "commodity" in asset_type or "commodity" in category:
        return "commodities"
    if "forex" in asset_type or "fx" in category:
        return "forex"
    if "crypto" in asset_type or "crypto" in category:
        return "crypto"
    if "bond" in asset_type or "rate" in category or "treasury" in category:
        return "bonds"
    return "equities" if not asset_type else asset_type.replace(" ", "_")


def value_from(asset: Asset | dict, key: str) -> str:
    if isinstance(asset, dict):
        return str(asset.get(key) or "")
    return str(getattr(asset, key, "") or "")


def benchmark_for(*, asset_type: str, market: str, sector: str = "") -> str:
    normalized_sector = str(sector or "").lower()
    normalized_type = str(asset_type or "").lower()
    if market == "crypto":
        return "BTC-USD"
    if market == "forex":
        return "UUP"
    if market == "commodities":
        return "GLD"
    if market == "bonds":
        return "TLT"
    if market == "indexes":
        return settings.default_benchmark
    if "etf" in normalized_type and "technology" in normalized_sector:
        return "QQQ"
    if "technology" in normalized_sector or "semiconductor" in normalized_sector:
        return "QQQ"
    return settings.default_benchmark


def parse_market_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
        return datetime(int(value.year), int(value.month), int(value.day))
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return None


def stale_price_data(price_context: dict, max_stale_hours: float | None) -> bool:
    if not max_stale_hours or max_stale_hours <= 0:
        return False
    latest_dt = parse_market_datetime(price_context.get("latest_date") or price_context.get("date") or price_context.get("as_of"))
    if latest_dt is None:
        return False
    return latest_dt < datetime.utcnow() - timedelta(hours=max_stale_hours)


def data_quality_status_for(price_context: dict, benchmark_available: bool, require_benchmark: bool, *, min_data_quality: float | None = None, max_stale_hours: float | None = None) -> str:
    latest_price = safe_float(price_context.get("latest_price"), None)
    rows = int(safe_float(price_context.get("rows"), 0) or 0)
    data_quality = safe_float(price_context.get("data_quality_score"), None)
    if latest_price is None or latest_price <= 0:
        return "MARKET_DATA_UNAVAILABLE"
    if rows <= 0:
        return "OHLCV_MISSING"
    if stale_price_data(price_context, max_stale_hours):
        return "STALE_PRICE_DATA"
    data_quality_floor = settings.paper_forward_min_data_quality if min_data_quality is None else min_data_quality
    if data_quality is not None and data_quality < data_quality_floor:
        return "LOW_DATA_QUALITY"
    if require_benchmark and not benchmark_available:
        return "BENCHMARK_UNAVAILABLE"
    return "OK"


def tradability_status_for(asset_type: str, price: float | None, liquidity_score: float, min_liquidity: float) -> str:
    if price is None or price <= 0:
        return "NOT_TRADABLE_NO_PRICE"
    if liquidity_score < min_liquidity:
        return "LIQUIDITY_UNKNOWN"
    if asset_class_key({"asset_type": asset_type}) in {"forex", "crypto", "commodities", "bonds", "volatility"}:
        return "PAPER_ONLY_ASSET_CLASS"
    return "TRADABLE_FOR_PAPER"


def liquidity_score_for(price_context: dict, price: float | None, latest_volume: float | None) -> float:
    if latest_volume is None:
        latest_volume = safe_float(price_context.get("volume"), None)
    if latest_volume is None:
        return 50.0 if price and price > 0 else 0.0
    if latest_volume >= 2_000_000:
        return 100.0
    if latest_volume >= 500_000:
        return 80.0
    if latest_volume >= 100_000:
        return 60.0
    return 35.0


def near_candidate(diagnosis, thresholds: ScannerThresholds) -> bool:
    confidence = diagnosis.confidence or 0.0
    risk_reward = diagnosis.risk_reward_ratio or 0.0
    if diagnosis.actionability_status in {"REJECTED_LOW_CONFIDENCE", "REJECTED_BAD_RISK_REWARD", "REJECTED_INSUFFICIENT_EVIDENCE"}:
        return confidence >= thresholds.min_confidence * 0.8 and risk_reward >= thresholds.min_risk_reward * 0.75
    return False


def classification_reason(classification: str, diagnosis, candidate: dict) -> str:
    if classification == TRADE_CANDIDATE:
        return "All critical paper-forward requirements passed: entry, stop, target, risk/reward, confidence and market data."
    if classification == WATCHLIST_CANDIDATE:
        return f"Interesting but not ready: {diagnosis.rejection_reason}."
    if classification == DATA_BLOCKED_CANDIDATE:
        return data_quality_blocker(candidate) or data_tradability_blocker(candidate) or diagnosis.rejection_reason
    if classification == BLOCKED_CANDIDATE:
        return tradability_blocker(candidate) or diagnosis.rejection_reason
    return diagnosis.rejection_reason


def blocker_for(classification: str, diagnosis, candidate: dict) -> str:
    if classification == TRADE_CANDIDATE:
        return ""
    if classification == WATCHLIST_CANDIDATE:
        return "waiting_for_entry_or_near_threshold"
    if classification == DATA_BLOCKED_CANDIDATE:
        return data_quality_blocker(candidate) or data_tradability_blocker(candidate) or diagnosis.rejection_reason
    if classification == BLOCKED_CANDIDATE:
        return tradability_blocker(candidate) or diagnosis.rejection_reason
    return diagnosis.rejection_reason


def normalized_status(value: object) -> str:
    return str(value or "").strip().upper()


def data_quality_blocker(candidate: dict) -> str:
    status = normalized_status(candidate.get("data_quality_status"))
    for blocker in DATA_BLOCKING_QUALITY_STATUSES:
        if status == blocker or status.startswith(f"{blocker}:"):
            return status
    return ""


def data_tradability_blocker(candidate: dict) -> str:
    status = normalized_status(candidate.get("tradability_status"))
    return status if status in DATA_BLOCKING_TRADABILITY_STATUSES else ""


def tradability_blocker(candidate: dict) -> str:
    status = normalized_status(candidate.get("tradability_status"))
    if status in PASSING_TRADABILITY_STATUSES or status in DATA_BLOCKING_TRADABILITY_STATUSES:
        return ""
    if status in BLOCKING_TRADABILITY_STATUSES:
        return status
    return status


def score_for(candidate: dict, diagnosis, classification: str) -> float:
    base = safe_float(candidate.get("sniper_score"), 0.0)
    confidence = diagnosis.confidence or safe_float(candidate.get("confidence"), 0.0)
    reward = diagnosis.risk_reward_ratio or safe_float(candidate.get("risk_reward_ratio"), 0.0)
    data_quality = diagnosis.data_quality_score or safe_float((candidate.get("price_context") or {}).get("data_quality_score"), 0.0)
    penalty = {TRADE_CANDIDATE: 0, WATCHLIST_CANDIDATE: 8, BLOCKED_CANDIDATE: 18, DATA_BLOCKED_CANDIDATE: 30}.get(classification, 20)
    return round(max(0.0, min(100.0, base * 0.45 + confidence * 0.25 + min(100, reward * 20) * 0.2 + data_quality * 0.1 - penalty)), 4)


def grouped_counts(classified: list[dict], key: str) -> dict:
    output: dict[str, int] = defaultdict(int)
    for item in classified:
        output[str(item.get(key) or "unknown")] += 1
    return dict(output)


def classification_by_market(classified: list[dict], classification: str) -> dict:
    counts: dict[str, int] = defaultdict(int)
    for item in classified:
        if item["classification"] == classification:
            counts[item["market"]] += 1
    return dict(counts)


def configured_market_coverage(db: Session, thresholds: ScannerThresholds, classified: list[dict]) -> dict:
    markets_scanned = sorted({item["market"] for item in classified})
    classes_scanned = sorted({item["asset_class"] for item in classified})
    assets_by_market = grouped_counts(classified, "market")
    skipped = []
    for market in thresholds.enabled_markets:
        if market in markets_scanned:
            continue
        asset_count = int(db.scalar(select(func.count(Asset.id)).where(Asset.is_active.is_(True))) or 0)
        skipped.append({"market": market, "reason": "MARKET_DATA_UNAVAILABLE" if asset_count else "UNSUPPORTED_MARKET_DATA"})
    reason = "; ".join(f"{item['market']}: {item['reason']}" for item in skipped) if skipped else ""
    return {
        "markets_scanned": markets_scanned,
        "asset_classes_scanned": classes_scanned,
        "assets_scanned_by_market": assets_by_market,
        "skipped_markets": skipped,
        "reason_if_markets_were_skipped": reason,
    }


def no_trade_reason(counts: Counter, top_blockers: list[dict]) -> str:
    if counts.get(TRADE_CANDIDATE, 0):
        return ""
    if not top_blockers:
        return "No trade candidates created because no scannable market evidence was available."
    fragments = [f"{item['count']} {item['reason']}" for item in top_blockers[:5]]
    return "No trade candidates created because " + ", ".join(fragments) + "."


def next_possible_action(counts: Counter, top_blockers: list[dict]) -> str:
    if counts.get(TRADE_CANDIDATE, 0):
        return "Freeze trade candidates and wait for lifecycle trigger evaluation."
    if counts.get(WATCHLIST_CANDIDATE, 0):
        return "Monitor watchlist candidates until entry triggers and risk/reward improve."
    if top_blockers:
        return f"Investigate top blocker: {top_blockers[0]['reason']}."
    return "Hydrate more market data before the next scan."


def scanner_item_payload(item: dict | None) -> dict | None:
    if item is None:
        return None
    candidate = item["candidate"]
    asset = candidate.get("asset") or {}
    plan = candidate.get("trade_plan") or {}
    return {
        "ticker": item["ticker"],
        "classification": item["classification"],
        "rank": item["rank"],
        "score": item["score"],
        "asset_type": item["asset_type"],
        "market": item["market"],
        "asset_class": item["asset_class"],
        "exchange": asset.get("exchange"),
        "currency": asset.get("currency"),
        "benchmark_asset": candidate.get("benchmark_asset"),
        "setup_type": (candidate.get("setup") or {}).get("setup_type"),
        "direction": plan.get("direction") or "long",
        "entry_type": plan.get("entry_type") or "conditional",
        "entry_trigger": plan.get("entry_trigger") or plan.get("confirmation_condition"),
        "entry_price": (candidate.get("price_context") or {}).get("latest_price"),
        "stop_price": plan.get("invalidation_level") or plan.get("stop_price") or plan.get("stop_loss"),
        "target_1": plan.get("target_1"),
        "target_2": plan.get("target_2"),
        "risk_reward_ratio": item["diagnosis"].get("risk_reward_ratio"),
        "expected_holding_days": plan.get("expected_holding_days") or plan.get("expected_holding_period"),
        "confidence": item["diagnosis"].get("confidence") or candidate.get("confidence"),
        "data_quality_status": candidate.get("data_quality_status"),
        "tradability_status": candidate.get("tradability_status"),
        "actionability_reason": candidate.get("classification_reason"),
        "reason_for_trade": candidate.get("explanation"),
        "reason_against_trade": item["blocker"],
        "model_version_used": (candidate.get("feedback_loop") or {}).get("model_version_used"),
        "weights_used": (candidate.get("feedback_loop") or {}).get("weights_used"),
        "memory_adjustments": (candidate.get("feedback_loop") or {}).get("learning_memory_used"),
        "research_priority_used": (candidate.get("feedback_loop") or {}).get("research_priority_used"),
    }


def data_blocked_payload(asset: Asset, reason: str) -> dict:
    return {
        "ticker": asset.ticker,
        "asset": {
            "ticker": asset.ticker,
            "name": asset.name,
            "asset_type": asset.asset_type,
            "sector": asset.sector,
            "industry": asset.industry,
            "country": asset.country,
            "exchange": asset.exchange,
            "currency": asset.currency,
        },
        "actionability": "avoid",
        "confidence": 0.0,
        "sniper_score": 0.0,
        "setup": {"setup_type": "data_blocked"},
        "trade_plan": {},
        "price_context": {"latest_price": None, "rows": 0, "data_quality_score": 0.0},
        "data_quality_status": reason,
        "tradability_status": "NOT_TRADABLE_NO_PRICE",
        "explanation": reason,
    }
