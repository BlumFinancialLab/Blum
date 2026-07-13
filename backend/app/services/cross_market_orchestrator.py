from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.market_desks import DEFAULT_MARKET_DESK_AGENTS, MarketDeskRegistry, desk_candidate_score
from app.services.paper_forward_contracts import (
    BLOCKED_CANDIDATE,
    DATA_BLOCKED_CANDIDATE,
    TRADE_CANDIDATE,
    WATCHLIST_CANDIDATE,
)
from app.services.quant_edge import (
    APPROVED_FOR_PAPER,
    DATA_BLOCKED,
    REJECTED_INSUFFICIENT_SAMPLE,
    REJECTED_OVERFITTING_RISK,
    BlumQuantEdgeAgent,
)
from app.services.trading_intelligence_lab import ActionabilityPolicy, diagnose_candidate_actionability


@dataclass(frozen=True)
class OrchestratorLimits:
    max_candidates_per_agent: int
    max_candidates_per_market: int
    max_candidates_per_asset_class: int
    max_candidates_per_ticker: int
    cross_market_enabled: bool


class BlumCrossMarketOpportunityOrchestrator:
    def __init__(
        self,
        *,
        registry: MarketDeskRegistry | None = None,
        quant_edge_agent: BlumQuantEdgeAgent | None = None,
        limits: OrchestratorLimits | None = None,
    ):
        settings = get_settings()
        self.enabled_agent_names = parse_names(
            getattr(settings, "blum_enabled_market_desk_agents", ",".join(agent.__name__ for agent in DEFAULT_MARKET_DESK_AGENTS))
        )
        self.limits = limits or OrchestratorLimits(
            max_candidates_per_agent=max(1, int(getattr(settings, "blum_max_candidates_per_agent", 5))),
            max_candidates_per_market=max(1, int(getattr(settings, "blum_max_candidates_per_market", 8))),
            max_candidates_per_asset_class=max(1, int(getattr(settings, "blum_max_candidates_per_asset_class", 12))),
            max_candidates_per_ticker=max(1, int(getattr(settings, "blum_max_candidates_per_ticker", 1))),
            cross_market_enabled=bool(getattr(settings, "blum_cross_market_orchestrator_enabled", True)),
        )
        self.registry = registry or MarketDeskRegistry(
            agents=enabled_agents(
                self.enabled_agent_names,
                stale_after_hours=float(getattr(settings, "paper_forward_scan_stale_data_max_age_hours", 72.0)),
            )
        )
        self.quant_edge_agent = quant_edge_agent or BlumQuantEdgeAgent(
            min_score=float(getattr(settings, "blum_quant_edge_min_score", 60.0)),
            min_sample_size=max(1, int(getattr(settings, "blum_quant_edge_min_sample_size", 20))),
            reject_high_overfitting_risk=bool(getattr(settings, "blum_reject_high_overfitting_risk", True)),
            min_risk_reward=float(getattr(settings, "paper_forward_min_risk_reward", 1.0)),
        )
        self.actionability_policy = ActionabilityPolicy(
            minimum_data_quality=float(getattr(settings, "paper_forward_min_data_quality", 50.0)),
            minimum_confidence=float(getattr(settings, "paper_forward_min_confidence", 50.0)),
            minimum_reward_to_risk=float(getattr(settings, "paper_forward_min_risk_reward", 1.0)),
        )

    def run(self, db: Session, limit: int | None = None) -> dict:
        generated_at = datetime.utcnow().isoformat()
        requested_limit = max(1, int(limit or 30))
        discovery = self.registry.discover(db)
        agent_results: list[dict] = []
        failed_agents: list[dict] = []
        for agent in discovery.available_agents:
            try:
                agent_results.append(agent.scan(db, min(requested_limit, self.limits.max_candidates_per_agent)))
            except Exception as exc:
                failed_agents.append(
                    {
                        "agent_name": agent.agent_name,
                        "market": agent.market,
                        "benchmark": agent.benchmark,
                        "status": "PROVIDER_UNAVAILABLE",
                        "skipped_reason": f"{type(exc).__name__}: {exc}",
                    }
                )

        assessed = self._assess_opportunities(db, agent_results)
        selected, concentration_rejections, repeated_tickers = self._select(assessed, requested_limit)
        rejected = [row for row in assessed if row not in selected]
        selected_payloads = [row["candidate"] for row in selected]
        rejected_payloads = [row["candidate"] for row in rejected if row["classification"] != TRADE_CANDIDATE]
        persisted_payloads = [*selected_payloads, *rejected_payloads]
        agents_skipped = [*discovery.skipped_agents, *failed_agents]
        verdict_counts = Counter(row["quant_edge"]["verdict"] for row in assessed)
        opportunities_by_agent = {
            row["agent_name"]: {
                "market": row.get("market"),
                "asset_class": row.get("asset_class"),
                "assets_scanned": row.get("assets_scanned", 0),
                "opportunities_found": row.get("opportunities_found", 0),
                "trade_candidates": sum(1 for item in assessed if item["agent_name"] == row["agent_name"] and item["classification"] == TRADE_CANDIDATE),
                "watchlist_candidates": sum(1 for item in assessed if item["agent_name"] == row["agent_name"] and item["classification"] == WATCHLIST_CANDIDATE),
                "blocked_candidates": sum(1 for item in assessed if item["agent_name"] == row["agent_name"] and item["classification"] in {BLOCKED_CANDIDATE, DATA_BLOCKED_CANDIDATE}),
            }
            for row in agent_results
        }
        top = [public_opportunity(row) for row in selected]
        best_by_agent = {
            result["agent_name"]: result.get("best_opportunity")
            for result in agent_results
            if result.get("best_opportunity") is not None
        }
        selected_market_counts = Counter(row["market"] for row in selected)
        selected_class_counts = Counter(row["asset_class"] for row in selected)
        reason = reason_if_no_trade_candidates(assessed, selected, agents_skipped)
        return {
            "status": "ok",
            "generated_at": generated_at,
            "scanner": "BlumCrossMarketOpportunityOrchestrator",
            "enabled_market_desk_agents": list(self.enabled_agent_names),
            "agents_requested": len(self.enabled_agent_names),
            "agents_run": [row["agent_name"] for row in agent_results],
            "agents_skipped": agents_skipped,
            "opportunities_by_agent": opportunities_by_agent,
            "best_opportunity_by_agent": best_by_agent,
            "rejected_by_agent": rejected_by_agent(assessed),
            "top_cross_market_opportunities": top,
            "best_cross_market_candidate": top[0] if top else None,
            "candidate_payloads_for_persistence": persisted_payloads,
            "trade_candidate_count": sum(1 for row in selected if row["classification"] == TRADE_CANDIDATE),
            "watchlist_candidate_count": sum(1 for row in persisted_payloads if row.get("paper_forward_classification") == WATCHLIST_CANDIDATE),
            "blocked_candidate_count": sum(1 for row in persisted_payloads if row.get("paper_forward_classification") == BLOCKED_CANDIDATE),
            "data_blocked_candidate_count": sum(1 for row in persisted_payloads if row.get("paper_forward_classification") == DATA_BLOCKED_CANDIDATE),
            "rejected_no_edge_count": verdict_counts.get("REJECTED_NO_EDGE", 0),
            "rejected_overfitting_count": verdict_counts.get(REJECTED_OVERFITTING_RISK, 0),
            "rejected_insufficient_sample_count": verdict_counts.get(REJECTED_INSUFFICIENT_SAMPLE, 0),
            "quant_edge_summary": {
                "assessed_count": len(assessed),
                "approved_count": verdict_counts.get(APPROVED_FOR_PAPER, 0),
                "verdict_counts": dict(verdict_counts),
                "average_edge_score": average([row["quant_edge"].get("edge_score") for row in assessed]),
            },
            "diversification_summary": {
                "selected_by_market": dict(selected_market_counts),
                "selected_by_asset_class": dict(selected_class_counts),
                "concentration_rejections": concentration_rejections,
                "max_candidates_per_market": self.limits.max_candidates_per_market,
                "max_candidates_per_asset_class": self.limits.max_candidates_per_asset_class,
                "max_candidates_per_ticker": self.limits.max_candidates_per_ticker,
            },
            "repeated_ticker_warning": bool(repeated_tickers),
            "repeated_tickers": sorted(repeated_tickers),
            "reason_if_same_tickers_repeat": (
                "Repeated tickers were deduplicated before paper-forward persistence."
                if repeated_tickers
                else None
            ),
            "reason_if_no_trade_candidates": reason,
            "markets_scanned": sorted({row["market"] for row in agent_results}),
            "asset_classes_scanned": sorted({row.get("asset_class") or "unknown" for row in agent_results}),
            "skipped_markets": [
                {"market": row.get("market"), "reason": row.get("skipped_reason") or row.get("status")}
                for row in agents_skipped
            ],
            "scanned_count": len(assessed),
            "latest_trade_candidates": [row for row in top if row["classification"] == TRADE_CANDIDATE][:8],
            "latest_watchlist_candidates": [public_opportunity(row) for row in assessed if row["classification"] == WATCHLIST_CANDIDATE][:8],
            "latest_blocked_candidates": [public_opportunity(row) for row in assessed if row["classification"] == BLOCKED_CANDIDATE][:8],
            "latest_data_blocked_candidates": [public_opportunity(row) for row in assessed if row["classification"] == DATA_BLOCKED_CANDIDATE][:8],
        }

    def _assess_opportunities(self, db: Session, agent_results: list[dict]) -> list[dict]:
        output: list[dict] = []
        for result in agent_results:
            candidates = dedupe_agent_candidates(
                [
                    *(result.get("trade_candidates") or []),
                    *(result.get("watchlist_candidates") or []),
                    *(result.get("blocked_candidates") or []),
                ]
            )[: self.limits.max_candidates_per_agent]
            for candidate in candidates:
                diagnosis = diagnose_candidate_actionability(candidate, strict=True, policy=self.actionability_policy)
                quant_edge = self.quant_edge_agent.assess(db, candidate)
                classification = classification_for_assessment(quant_edge["verdict"], diagnosis)
                candidate_score = desk_candidate_score(candidate)
                edge_score = quant_edge.get("edge_score")
                score = round(candidate_score * 0.55 + float(edge_score if edge_score is not None else 0.0) * 0.45, 4)
                market = str(result["market"])
                asset_class = str((candidate.get("asset") or {}).get("asset_class") or result.get("asset_class") or "unknown")
                candidate_payload = {
                    **candidate,
                    "paper_forward_classification": classification,
                    "classification_reason": (
                        diagnosis.rejection_reason
                        if diagnosis.actionability_status != "ACTIONABLE"
                        else quant_edge.get("explanation")
                    ),
                    "quant_edge": quant_edge,
                    "actionability_diagnosis": diagnosis.to_dict(),
                    "cross_market_orchestrator": {
                        "agent_name": result["agent_name"],
                        "market": market,
                        "asset_class": asset_class,
                        "raw_score": candidate_score,
                        "global_score": score,
                        "normalized_score": score,
                        "normalization": "weighted_common_scale_0_100",
                    },
                }
                output.append(
                    {
                        "ticker": str(candidate.get("ticker") or "").upper(),
                        "agent_name": result["agent_name"],
                        "market": market,
                        "asset_class": asset_class,
                        "score": score,
                        "classification": classification,
                        "quant_edge": quant_edge,
                        "candidate": candidate_payload,
                    }
                )
        return sorted(output, key=lambda row: row["score"], reverse=True)

    def _select(self, assessed: list[dict], requested_limit: int) -> tuple[list[dict], int, set[str]]:
        ticker_seen: Counter = Counter()
        market_seen: Counter = Counter()
        class_seen: Counter = Counter()
        repeated_tickers = {ticker for ticker, count in Counter(row["ticker"] for row in assessed).items() if ticker and count > 1}
        selected: list[dict] = []
        concentration_rejections = 0
        for row in assessed:
            if row["classification"] != TRADE_CANDIDATE:
                continue
            if ticker_seen[row["ticker"]] >= self.limits.max_candidates_per_ticker:
                concentration_rejections += 1
                continue
            if market_seen[row["market"]] >= self.limits.max_candidates_per_market:
                concentration_rejections += 1
                continue
            if class_seen[row["asset_class"]] >= self.limits.max_candidates_per_asset_class:
                concentration_rejections += 1
                continue
            selected.append(row)
            ticker_seen[row["ticker"]] += 1
            market_seen[row["market"]] += 1
            class_seen[row["asset_class"]] += 1
            if len(selected) >= requested_limit:
                break
        return selected, concentration_rejections, repeated_tickers


def enabled_agents(names: tuple[str, ...], *, stale_after_hours: float = 72.0) -> list:
    by_name = {agent_type.__name__.lower(): agent_type for agent_type in DEFAULT_MARKET_DESK_AGENTS}
    output = []
    for name in names:
        agent_type = by_name.get(name.lower())
        if agent_type is not None:
            output.append(agent_type(stale_after_hours=stale_after_hours))
    return output


def parse_names(value: object) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in str(value or "").split(",") if item.strip()))


def classification_for(verdict: str) -> str:
    if verdict == APPROVED_FOR_PAPER:
        return TRADE_CANDIDATE
    if verdict in {REJECTED_INSUFFICIENT_SAMPLE, "WATCHLIST_ONLY"}:
        return WATCHLIST_CANDIDATE
    if verdict == DATA_BLOCKED:
        return DATA_BLOCKED_CANDIDATE
    return BLOCKED_CANDIDATE


def classification_for_assessment(verdict: str, diagnosis) -> str:
    if diagnosis.actionability_status == "DATA_BLOCKED":
        return DATA_BLOCKED_CANDIDATE
    if diagnosis.actionability_status != "ACTIONABLE":
        return WATCHLIST_CANDIDATE if diagnosis.should_wait else BLOCKED_CANDIDATE
    return classification_for(verdict)


def dedupe_agent_candidates(rows: list[dict]) -> list[dict]:
    output: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        ticker = str(row.get("ticker") or "").upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        output.append(row)
    return output


def public_opportunity(row: dict) -> dict:
    candidate = row["candidate"]
    return {
        "ticker": row["ticker"],
        "agent_name": row["agent_name"],
        "market": row["market"],
        "asset_class": row["asset_class"],
        "classification": row["classification"],
        "score": row["score"],
        "normalized_score": row["score"],
        "setup_type": (candidate.get("setup") or {}).get("setup_type"),
        "benchmark_asset": candidate.get("benchmark_asset"),
        "confidence": candidate.get("confidence"),
        "sniper_score": candidate.get("sniper_score"),
        "quant_edge": row["quant_edge"],
        "classification_reason": candidate.get("classification_reason"),
    }


def rejected_by_agent(rows: list[dict]) -> dict:
    grouped: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        if row["classification"] != TRADE_CANDIDATE:
            grouped[row["agent_name"]][row["quant_edge"]["verdict"]] += 1
    return {agent: dict(counts) for agent, counts in grouped.items()}


def reason_if_no_trade_candidates(assessed: list[dict], selected: list[dict], skipped: list[dict]) -> str:
    if selected:
        return ""
    if not assessed and skipped:
        return "No market desk had eligible stored market data."
    if not assessed:
        return "Available market desks found no current opportunities."
    counts = Counter(row["quant_edge"]["verdict"] for row in assessed)
    return "No trade candidates passed Quant Edge validation: " + ", ".join(f"{count} {verdict}" for verdict, count in counts.most_common()) + "."


def average(values: list[float | None]) -> float | None:
    usable = [float(value) for value in values if value is not None]
    return round(sum(usable) / len(usable), 4) if usable else None
