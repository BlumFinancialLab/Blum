from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Asset, LearningEvent, PriceHistory
from app.services.trading_intelligence_lab import ActionabilityPolicy, diagnose_candidate_actionability, risk_reward_ratio_from_plan, safe_float


settings = get_settings()


TRADE_CANDIDATE = "TRADE_CANDIDATE"
WATCHLIST_CANDIDATE = "WATCHLIST_CANDIDATE"
BLOCKED_CANDIDATE = "BLOCKED_CANDIDATE"
DATA_BLOCKED_CANDIDATE = "DATA_BLOCKED_CANDIDATE"
SUPPORTED_CLASSIFICATIONS = {TRADE_CANDIDATE, WATCHLIST_CANDIDATE, BLOCKED_CANDIDATE, DATA_BLOCKED_CANDIDATE}


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
        }


class PaperForwardOpportunityScanner:
    """Classify current market evidence into auditable paper-forward candidates.

    The scanner does not open positions. It only turns existing BLUM market
    intelligence into classified candidate payloads and a cross-market report.
    """

    def __init__(self, *, candidate_provider: CandidateProvider | None = None):
        self.candidate_provider = candidate_provider
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
        )

    def scan(self, db: Session, *, limit: int | None = None) -> dict:
        max_items = max(1, min(int(limit or self.thresholds.max_candidates_per_run), self.thresholds.max_candidates_per_run))
        raw_candidates = self.raw_candidates(db, max_items)
        assets_by_ticker = assets_for_candidates(db, raw_candidates)
        benchmark_availability = benchmark_availability_map(db)

        classified: list[dict] = []
        for rank, candidate in enumerate(raw_candidates, start=1):
            enriched = self.enrich_candidate(candidate, assets_by_ticker.get(normalize_ticker(candidate.get("ticker"))), benchmark_availability)
            classified.append(self.classify_candidate(enriched, rank))

        summary = self.summary(db, classified)
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
                    "scanner": summary["scanner"],
                    "scanned_count": summary["scanned_count"],
                    "trade_candidate_count": summary["trade_candidate_count"],
                    "watchlist_candidate_count": summary["watchlist_candidate_count"],
                    "blocked_candidate_count": summary["blocked_candidate_count"],
                    "data_blocked_candidate_count": summary["data_blocked_candidate_count"],
                    "top_blockers": summary["top_blockers"],
                    "markets_scanned": summary["markets_scanned"],
                    "asset_classes_scanned": summary["asset_classes_scanned"],
                    "thresholds": summary["thresholds"],
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
        if self.candidate_provider is not None:
            return dedupe_candidates(self.candidate_provider(db, limit))[:limit]

        from app.services.market_sniper import MarketSniperEngine

        engine = MarketSniperEngine()
        candidates: list[dict] = []
        seen: set[str] = set()

        def add(item: dict, source: str) -> None:
            ticker = normalize_ticker(item.get("ticker"))
            if not ticker or ticker in seen:
                return
            payload = {**item, "scouting_source": source, "scouting_policy": "global_market_universe_stored_evidence_only"}
            seen.add(ticker)
            candidates.append(payload)

        try:
            payload = engine.candidates(db, limit=limit, persist=False)
            for item in payload.get("candidates", []) or []:
                add(item, "market_sniper_ranked_signals")
        except Exception as exc:
            db.add(scanner_event("MARKET_SKIPPED", "market_sniper_ranked_signals", f"{type(exc).__name__}: {exc}", {"source": "market_sniper"}))

        if len(candidates) < limit:
            for asset in market_universe_assets(db, self.thresholds, limit=max(limit * 5, limit)):
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
        asset_type = asset_payload.get("asset_type") or getattr(asset, "asset_type", None) or "Unknown"
        market = market_key(asset or asset_payload)
        asset_class = asset_class_key(asset or asset_payload)
        benchmark = benchmark_for(asset_type=asset_type, market=market, sector=asset_payload.get("sector") or getattr(asset, "sector", ""))
        benchmark_available = bool(benchmarks.get(normalize_ticker(benchmark)))
        price_context = candidate.get("price_context") if isinstance(candidate.get("price_context"), dict) else {}
        latest_price = safe_float(price_context.get("latest_price"), None)
        latest_volume = safe_float(price_context.get("latest_volume"), None)
        liquidity_score = liquidity_score_for(price_context, latest_price, latest_volume)
        data_quality_status = data_quality_status_for(price_context, benchmark_available, self.thresholds.require_benchmark)
        tradability_status = tradability_status_for(asset_type, latest_price, liquidity_score, self.thresholds.min_liquidity_score)
        plan = candidate.get("trade_plan") if isinstance(candidate.get("trade_plan"), dict) else {}
        risk_reward = risk_reward_ratio_from_plan(plan, latest_price)
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
            "liquidity_context": {"liquidity_score": liquidity_score, "latest_volume": latest_volume},
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
            "liquidity_score": liquidity_score,
        }
        return {
            **candidate,
            "ticker": ticker,
            "asset": enriched_asset,
            "price_context": enriched_price_context,
            "benchmark_asset": benchmark,
            "benchmark_available": benchmark_available,
            "liquidity_context": enriched_asset["liquidity_context"],
            "data_quality_status": data_quality_status,
            "tradability_status": tradability_status,
            "risk_reward_ratio": risk_reward,
        }

    def classify_candidate(self, candidate: dict, rank: int) -> dict:
        policy = ActionabilityPolicy(
            minimum_data_quality=self.thresholds.min_data_quality,
            minimum_confidence=self.thresholds.min_confidence,
            minimum_reward_to_risk=self.thresholds.min_risk_reward,
        )
        diagnosis = diagnose_candidate_actionability(candidate, strict=True, policy=policy)
        asset = candidate.get("asset") or {}
        hard_data_block = candidate.get("data_quality_status") in {
            "MARKET_DATA_UNAVAILABLE",
            "UNSUPPORTED_MARKET_DATA",
            "BENCHMARK_UNAVAILABLE",
            "PROVIDER_UNAVAILABLE",
        }
        if self.thresholds.require_benchmark and not candidate.get("benchmark_available"):
            hard_data_block = True
        if hard_data_block or diagnosis.actionability_status == "DATA_BLOCKED":
            classification = DATA_BLOCKED_CANDIDATE
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
        trade_items = sorted([item for item in classified if item["classification"] == TRADE_CANDIDATE], key=lambda item: item["score"], reverse=True)
        watch_items = sorted([item for item in classified if item["classification"] == WATCHLIST_CANDIDATE], key=lambda item: item["score"], reverse=True)
        blocked_items = sorted([item for item in classified if item["classification"] == BLOCKED_CANDIDATE], key=lambda item: item["score"], reverse=True)
        data_blocked_items = sorted([item for item in classified if item["classification"] == DATA_BLOCKED_CANDIDATE], key=lambda item: item["score"], reverse=True)
        best_cross_market = sorted(classified, key=lambda item: item["score"], reverse=True)[0] if classified else None
        configured_market_report = configured_market_coverage(db, self.thresholds, classified)
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
            "assets_scanned_by_market": configured_market_report["assets_scanned_by_market"],
            "trade_candidates_by_market": classification_by_market(classified, TRADE_CANDIDATE),
            "watchlist_candidates_by_market": classification_by_market(classified, WATCHLIST_CANDIDATE),
            "blocked_candidates_by_market": classification_by_market(classified, BLOCKED_CANDIDATE),
            "data_blocked_candidates_by_market": classification_by_market(classified, DATA_BLOCKED_CANDIDATE),
            "skipped_markets": configured_market_report["skipped_markets"],
            "reason_if_markets_were_skipped": configured_market_report["reason_if_markets_were_skipped"],
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


def benchmark_availability_map(db: Session) -> dict[str, bool]:
    rows = db.execute(select(Asset.ticker, func.count(PriceHistory.id)).join(PriceHistory, PriceHistory.asset_id == Asset.id).group_by(Asset.ticker)).all()
    return {normalize_ticker(ticker): count > 0 for ticker, count in rows}


def market_universe_assets(db: Session, thresholds: ScannerThresholds, *, limit: int) -> list[Asset]:
    assets = db.scalars(select(Asset).where(Asset.is_active.is_(True)).order_by(Asset.asset_type, Asset.ticker).limit(limit * 3)).all()
    filtered = []
    for asset in assets:
        if asset_class_key(asset) not in thresholds.enabled_asset_classes:
            continue
        if market_key(asset) not in thresholds.enabled_markets:
            continue
        filtered.append(asset)
        if len(filtered) >= limit:
            break
    return filtered


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
    if "volatility" in asset_type or "vix" in category:
        return "volatility"
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


def data_quality_status_for(price_context: dict, benchmark_available: bool, require_benchmark: bool) -> str:
    latest_price = safe_float(price_context.get("latest_price"), None)
    rows = int(safe_float(price_context.get("rows"), 0) or 0)
    data_quality = safe_float(price_context.get("data_quality_score"), None)
    if latest_price is None or latest_price <= 0:
        return "MARKET_DATA_UNAVAILABLE"
    if rows <= 0:
        return "OHLCV_MISSING"
    if data_quality is not None and data_quality < settings.paper_forward_min_data_quality:
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
        return candidate.get("data_quality_status") or diagnosis.rejection_reason
    return diagnosis.rejection_reason


def blocker_for(classification: str, diagnosis, candidate: dict) -> str:
    if classification == TRADE_CANDIDATE:
        return ""
    if classification == WATCHLIST_CANDIDATE:
        return "waiting_for_entry_or_near_threshold"
    if classification == DATA_BLOCKED_CANDIDATE:
        return candidate.get("data_quality_status") or diagnosis.rejection_reason
    return diagnosis.rejection_reason


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
