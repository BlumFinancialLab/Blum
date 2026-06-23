from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from statistics import mean

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import (
    AllocationEfficiencyAudit,
    BusinessQualityScore,
    CapitalAllocationSnapshot,
    CapitalInteractionRisk,
    CashAllocationDecision,
    OpportunityCapitalScore,
    PortfolioAlphaScore,
    PortfolioCorrelation,
    PositionSizingOutcome,
    SizingLogicAllocation,
    TradingGame,
    TradingGameTrade,
)
from app.services.decision_intelligence import (
    BusinessQualityEngine,
    DecisionSuperiorityEngine,
    PortfolioIntelligenceEngine,
    decision_evidence_for_trade,
)
from app.services.learning_intelligence import (
    game_trades,
    latest_trading_game,
    round_or_none,
    statistical_confidence_label,
)
from app.services.trade_transparency import clamp, safe_float
from app.services.trading_intelligence_lab import executable_trades, metric_payload, sample_context


CAPITAL_ALLOCATION_POLICY = (
    "BLUM Capital Allocation Intelligence is paper-research only. It estimates how simulated capital should be "
    "distributed across opportunities, cash and sizing policies from stored evidence. It is not financial advice, "
    "does not execute trades and must reduce confidence when evidence is weak."
)


class AdaptiveCapitalAllocationEngine:
    """Adds portfolio-level capital intelligence on top of existing BLUM engines.

    This layer does not generate trades. It studies the decisions already produced
    by Trading Game, Decision Superiority, Business Quality and Portfolio
    Intelligence, then converts them into auditable capital-allocation evidence.
    """

    def dashboard(self, db: Session) -> dict:
        return {
            "status": "ok",
            "generated_at": datetime.utcnow().isoformat(),
            "policy": CAPITAL_ALLOCATION_POLICY,
            "allocation_plan": self.allocation_plan(db, persist=False),
            "cash_policy": self.cash_policy(db, persist=False),
            "allocation_efficiency": self.allocation_efficiency(db, persist=False),
            "sizing_logic": self.sizing_logic_effectiveness(db, persist=False),
            "interaction_risks": self.interaction_risks(db, persist=False),
        }

    def allocation_plan(self, db: Session, persist: bool = False, limit: int = 12) -> dict:
        game = latest_trading_game(db)
        opportunity_payload = self.opportunity_scores(db, persist=False, limit=max(limit * 3, 24))
        cash_payload = self.cash_policy(db, persist=False)
        opportunities = [row for row in opportunity_payload["rows"] if row["capital_score"] >= 35]
        deployable = safe_float(cash_payload.get("deployable_percent"), 0.0)
        selected = opportunities[:limit]
        score_sum = sum(max(1.0, safe_float(row["capital_score"])) for row in selected)

        allocations: list[dict] = []
        for row in selected:
            raw_weight = deployable * max(1.0, safe_float(row["capital_score"])) / score_sum if score_sum else 0.0
            weight = min(safe_float(row.get("max_weight"), 0.0), raw_weight)
            allocations.append(
                {
                    "ticker": row["ticker"],
                    "sector": row.get("sector"),
                    "setup_type": row.get("setup_type"),
                    "recommended_weight": round(weight, 4),
                    "capital_score": row["capital_score"],
                    "decision_state": row["decision_state"],
                    "reason": row["explanation"],
                    "evidence": row["evidence"],
                }
            )

        invested = sum(safe_float(item["recommended_weight"]) for item in allocations)
        cash_weight = round(max(safe_float(cash_payload["cash_reserve_percent"]), 100.0 - invested), 4)
        warnings = allocation_warnings(opportunity_payload, cash_payload, allocations)
        quality = allocation_quality_score(opportunity_payload, cash_payload, allocations)
        expected_alpha = mean([safe_float(row.get("risk_adjusted_alpha")) for row in selected]) if selected else None
        explanation = explain_allocation(quality, cash_weight, warnings)
        payload = {
            "status": "ok" if game else "no_game",
            "game_id": game.id if game else None,
            "mode": "historical_plus_live",
            "total_capital": safe_float(game.current_capital) if game else None,
            "cash_reserve_percent": cash_weight,
            "deployable_percent": round(max(0.0, 100.0 - cash_weight), 4),
            "allocation_quality_score": round(quality, 2),
            "expected_risk_adjusted_alpha": round_or_none(expected_alpha),
            "allocations": allocations,
            "cash_position": {
                "bucket": "cash",
                "recommended_weight": cash_weight,
                "decision_state": cash_payload.get("decision_state"),
                "reason": cash_payload.get("explanation"),
            },
            "benchmark_context": {
                "benchmark": game.benchmark_ticker if game else "SPY",
                "benchmark_return": game.benchmark_return if game else None,
                "alpha": game.alpha if game else None,
            },
            "warnings": warnings,
            "explanation": explanation,
            "policy": CAPITAL_ALLOCATION_POLICY,
        }
        if persist:
            db.add(
                CapitalAllocationSnapshot(
                    game_id=game.id if game else None,
                    mode=payload["mode"],
                    total_capital=payload["total_capital"],
                    cash_reserve_percent=payload["cash_reserve_percent"],
                    deployable_percent=payload["deployable_percent"],
                    allocation_quality_score=payload["allocation_quality_score"],
                    expected_risk_adjusted_alpha=payload["expected_risk_adjusted_alpha"],
                    benchmark_context=payload["benchmark_context"],
                    allocation_json={"allocations": allocations, "cash_position": payload["cash_position"]},
                    warnings_json={"warnings": warnings},
                    explanation=explanation,
                )
            )
            db.commit()
        return payload

    def opportunity_scores(self, db: Session, persist: bool = False, limit: int = 50) -> dict:
        game = latest_trading_game(db)
        rows = executable_trades(game_trades(db, game.id if game else None))
        grouped: dict[str, list[TradingGameTrade]] = defaultdict(list)
        for row in rows:
            grouped[row.ticker].append(row)

        portfolio_alpha = latest_portfolio_alpha(db)
        business_quality = latest_business_quality(db)
        if not portfolio_alpha and rows:
            portfolio_alpha = {item["ticker"]: item for item in PortfolioIntelligenceEngine().alpha_scores(db, persist=False)["rows"]}
        if not business_quality:
            business_quality = {item["ticker"]: item for item in BusinessQualityEngine().scores(db, limit=120, persist=False)["rows"]}

        scored = []
        for ticker, trades in grouped.items():
            latest = max(trades, key=lambda item: item.created_at or datetime.min)
            r_values = [safe_float(item.realized_r_multiple) for item in trades if item.realized_r_multiple is not None]
            excess_values = [safe_float(item.excess_return_vs_benchmark) for item in trades if item.excess_return_vs_benchmark is not None]
            hit_rate = sum(1 for item in r_values if item > 0) / len(r_values) if r_values else None
            average_r = mean(r_values) if r_values else None
            benchmark_excess = mean(excess_values) if excess_values else None
            drawdown = min([safe_float(item.pnl_percent) for item in trades if item.pnl_percent is not None], default=0.0)
            reproducibility = mean([safe_float(item.reproducibility_score) for item in trades]) if trades else 0.0
            trade_quality = mean([safe_float(item.trade_quality_score, 50.0) for item in trades]) if trades else 50.0
            alpha = portfolio_alpha.get(ticker, {})
            quality = business_quality.get(ticker, {})
            decision = safe_decision_evidence(db, latest)
            sample_penalty = sample_penalty_for(len(trades))
            cash_penalty = max(0.0, sample_penalty + (15 if drawdown <= -8 else 0) + (10 if safe_float(benchmark_excess) < 0 else 0))
            risk_adjusted_alpha = capital_alpha_score(average_r, benchmark_excess, drawdown)
            portfolio_fit = portfolio_fit_score(alpha, quality, decision, reproducibility)
            sizing_confidence = sizing_confidence_score(trades, latest)
            score = clamp(
                risk_adjusted_alpha * 0.28
                + portfolio_fit * 0.22
                + sizing_confidence * 0.18
                + trade_quality * 0.14
                + reproducibility * 0.12
                + safe_float(quality.get("business_quality_score"), 45.0) * 0.06
                - cash_penalty
            )
            max_weight = max_weight_for(score, drawdown, len(trades))
            decision_state = capital_decision_state(score, cash_penalty, max_weight)
            explanation = opportunity_explanation(ticker, score, average_r, benchmark_excess, cash_penalty, decision_state)
            scored.append(
                {
                    "ticker": ticker,
                    "sector": latest.sector,
                    "setup_type": latest.setup_type,
                    "sample_size": len(trades),
                    "capital_score": round(score, 2),
                    "recommended_weight": 0.0,
                    "max_weight": max_weight,
                    "cash_penalty": round(cash_penalty, 2),
                    "risk_adjusted_alpha": round(risk_adjusted_alpha, 2),
                    "portfolio_fit": round(portfolio_fit, 2),
                    "sizing_confidence": round(sizing_confidence, 2),
                    "decision_state": decision_state,
                    "explanation": explanation,
                    "evidence": {
                        "average_r": round_or_none(average_r),
                        "hit_rate": round_or_none(hit_rate),
                        "benchmark_excess": round_or_none(benchmark_excess),
                        "worst_pnl_percent": round_or_none(drawdown),
                        "reproducibility": round_or_none(reproducibility),
                        "trade_quality": round_or_none(trade_quality),
                        "business_quality_score": quality.get("business_quality_score"),
                        "portfolio_alpha_score": alpha.get("portfolio_alpha_score"),
                        "selection_quality": decision.get("selection_quality"),
                        "latest_trade_id": latest.id,
                    },
                }
            )
        scored = sorted(scored, key=lambda item: safe_float(item["capital_score"]), reverse=True)[:limit]
        if persist:
            for item in scored:
                db.add(
                    OpportunityCapitalScore(
                        game_id=game.id if game else None,
                        ticker=item["ticker"],
                        sector=item.get("sector"),
                        setup_type=item.get("setup_type"),
                        capital_score=item["capital_score"],
                        recommended_weight=item.get("recommended_weight", 0.0),
                        max_weight=item.get("max_weight", 0.0),
                        cash_penalty=item.get("cash_penalty", 0.0),
                        risk_adjusted_alpha=item.get("risk_adjusted_alpha"),
                        portfolio_fit=item.get("portfolio_fit"),
                        sizing_confidence=item.get("sizing_confidence"),
                        decision_state=item.get("decision_state", "monitor"),
                        evidence_json=item.get("evidence", {}),
                    )
                )
            db.commit()
        return {
            "status": "ok" if game else "no_game",
            "rows": scored,
            "sample_size": len(rows),
            "statistical_confidence": statistical_confidence_label(len(rows), sum(1 for row in rows if row.mode == "live_forward_paper"), sample_context(rows)),
            "policy": CAPITAL_ALLOCATION_POLICY,
        }

    def cash_policy(self, db: Session, persist: bool = False) -> dict:
        game = latest_trading_game(db)
        rows = executable_trades(game_trades(db, game.id if game else None))
        metrics = metric_payload(rows, "capital_allocation", str(game.id) if game else None, "all", None)
        recent = rows[-30:]
        stop_rate = sum(1 for row in recent if row.stop_hit) / len(recent) if recent else 0.0
        missed_rate = sum(1 for row in recent if row.missed_entry) / len(recent) if recent else 0.0
        expectancy = safe_float(metrics.get("expectancy_r"))
        benchmark_excess = safe_float(metrics.get("benchmark_excess"))
        drawdown = safe_float(metrics.get("max_drawdown"))
        sample_size = len(rows)
        cash = 18.0
        reasons = []
        if sample_size < 30:
            cash += 22
            reasons.append("Evidence sample is below 30 trades; BLUM keeps more capital in cash.")
        if expectancy <= 0:
            cash += 18
            reasons.append("Expectancy is not positive; capital deployment is penalized.")
        if benchmark_excess < 0:
            cash += 14
            reasons.append("Stored trades are underperforming the benchmark context.")
        if drawdown <= -10:
            cash += 12
            reasons.append("Drawdown is elevated; cash reserve is increased.")
        if stop_rate >= 0.35:
            cash += 10
            reasons.append("Recent stop-hit rate is high.")
        if missed_rate >= 0.35 and expectancy > 0:
            cash -= 6
            reasons.append("Missed-entry rate is high while expectancy is positive; small deployable reserve can be tested.")
        if sample_size >= 100 and expectancy > 0.25 and benchmark_excess > 0:
            cash -= 12
            reasons.append("Evidence is broader and benchmark-relative expectancy is positive.")
        cash = round(clamp(cash, 10, 85), 2)
        decision_state = cash_decision_state(cash, expectancy, benchmark_excess)
        market_regime = most_common([row.market_regime_at_entry for row in recent if row.market_regime_at_entry]) or "unknown"
        drawdown_state = "stress" if drawdown <= -10 else "normal" if drawdown > -5 else "elevated"
        payload = {
            "status": "ok" if game else "no_game",
            "game_id": game.id if game else None,
            "cash_reserve_percent": cash,
            "deployable_percent": round(100.0 - cash, 2),
            "decision_state": decision_state,
            "market_regime": market_regime,
            "drawdown_state": drawdown_state,
            "reasons": reasons or ["No strong cash override detected; reserve remains policy-based."],
            "explanation": cash_explanation(cash, decision_state, reasons),
            "evidence": {
                "sample_size": sample_size,
                "expectancy_r": round_or_none(expectancy),
                "benchmark_excess": round_or_none(benchmark_excess),
                "max_drawdown": round_or_none(drawdown),
                "recent_stop_rate": round_or_none(stop_rate),
                "recent_missed_entry_rate": round_or_none(missed_rate),
            },
            "policy": CAPITAL_ALLOCATION_POLICY,
        }
        if persist:
            db.add(
                CashAllocationDecision(
                    game_id=game.id if game else None,
                    cash_reserve_percent=payload["cash_reserve_percent"],
                    deployable_percent=payload["deployable_percent"],
                    decision_state=decision_state,
                    market_regime=market_regime,
                    drawdown_state=drawdown_state,
                    reasons_json=payload["reasons"],
                    evidence_json=payload["evidence"],
                )
            )
            db.commit()
        return payload

    def allocation_efficiency(self, db: Session, persist: bool = False) -> dict:
        game = latest_trading_game(db)
        rows = executable_trades(game_trades(db, game.id if game else None))
        trade_audits = [trade_allocation_audit(row) for row in rows]
        regret = sum(max(0.0, safe_float(item["ideal_pnl_eur"]) - safe_float(item["actual_pnl_eur"])) for item in trade_audits)
        total_capital = sum(max(0.01, safe_float(row.capital_before)) for row in rows)
        regret_rate = regret / total_capital * 100 if total_capital else 0.0
        score = clamp(100 - regret_rate * 18 - (20 if len(rows) < 30 else 0))
        underallocated = sorted([item for item in trade_audits if item["allocation_error"] == "underallocated_winner"], key=lambda item: safe_float(item["regret_eur"]), reverse=True)[:12]
        overallocated = sorted([item for item in trade_audits if item["allocation_error"] == "overallocated_loser"], key=lambda item: safe_float(item["regret_eur"]), reverse=True)[:12]
        benchmark_cost = mean([safe_float(row.excess_return_vs_benchmark) for row in rows if row.excess_return_vs_benchmark is not None]) if rows else None
        recommendations = allocation_efficiency_recommendations(score, underallocated, overallocated, rows)
        payload = {
            "status": "ok" if game else "no_game",
            "game_id": game.id if game else None,
            "sample_size": len(rows),
            "allocation_efficiency_score": round(score, 2),
            "allocation_regret_eur": round(regret, 4),
            "cash_drag_estimate": cash_drag_estimate(rows),
            "benchmark_opportunity_cost": round_or_none(benchmark_cost),
            "underallocated_winners": underallocated,
            "overallocated_losers": overallocated,
            "recommendations": recommendations,
            "explanation": f"Allocation Efficiency Score {score:.1f}/100. Estimated ex-post allocation regret is {regret:.2f} EUR across {len(rows)} executable trades.",
            "policy": CAPITAL_ALLOCATION_POLICY,
        }
        if persist:
            db.add(
                AllocationEfficiencyAudit(
                    game_id=game.id if game else None,
                    sample_size=len(rows),
                    allocation_efficiency_score=payload["allocation_efficiency_score"],
                    allocation_regret_eur=payload["allocation_regret_eur"],
                    cash_drag_estimate=payload["cash_drag_estimate"],
                    benchmark_opportunity_cost=payload["benchmark_opportunity_cost"],
                    underallocated_winners_json=underallocated,
                    overallocated_losers_json=overallocated,
                    recommendations_json=recommendations,
                    evidence_json={"trade_audit_sample": trade_audits[:80]},
                )
            )
            db.commit()
        return payload

    def sizing_logic_effectiveness(self, db: Session, persist: bool = False) -> dict:
        game = latest_trading_game(db)
        rows = executable_trades(game_trades(db, game.id if game else None))
        buckets: dict[str, list[TradingGameTrade]] = defaultdict(list)
        for row in rows:
            buckets[sizing_logic_for_trade(row)].append(row)
        output = []
        for logic, group in buckets.items():
            r_values = [safe_float(row.realized_r_multiple) for row in group if row.realized_r_multiple is not None]
            excess_values = [safe_float(row.excess_return_vs_benchmark) for row in group if row.excess_return_vs_benchmark is not None]
            hit_rate = sum(1 for value in r_values if value > 0) / len(r_values) if r_values else None
            max_drawdown = min([safe_float(row.pnl_percent) for row in group if row.pnl_percent is not None], default=0.0)
            avg_r = mean(r_values) if r_values else None
            benchmark_excess = mean(excess_values) if excess_values else None
            risk_adjusted = sizing_risk_adjusted_alpha(avg_r, benchmark_excess, max_drawdown)
            recommended_risk = recommended_risk_for_logic(risk_adjusted, len(group), max_drawdown)
            recommendation = sizing_recommendation(risk_adjusted, len(group), max_drawdown)
            output.append(
                {
                    "sizing_logic": logic,
                    "sample_size": len(group),
                    "average_r": round_or_none(avg_r),
                    "benchmark_excess": round_or_none(benchmark_excess),
                    "max_drawdown": round_or_none(max_drawdown),
                    "hit_rate": round_or_none(hit_rate),
                    "risk_adjusted_alpha": round(risk_adjusted, 2),
                    "recommended_risk_percent": recommended_risk,
                    "recommendation": recommendation,
                    "evidence": {
                        "tickers": sorted({row.ticker for row in group})[:20],
                        "warning": "Low sample; do not promote this sizing logic yet." if len(group) < 30 else None,
                    },
                }
            )
        output = sorted(output, key=lambda item: safe_float(item["risk_adjusted_alpha"]), reverse=True)
        if persist:
            for item in output:
                db.add(
                    SizingLogicAllocation(
                        game_id=game.id if game else None,
                        sizing_logic=item["sizing_logic"],
                        sample_size=item["sample_size"],
                        average_r=item["average_r"],
                        benchmark_excess=item["benchmark_excess"],
                        max_drawdown=item["max_drawdown"],
                        hit_rate=item["hit_rate"],
                        risk_adjusted_alpha=item["risk_adjusted_alpha"],
                        recommended_risk_percent=item["recommended_risk_percent"],
                        recommendation=item["recommendation"],
                        evidence_json=item["evidence"],
                    )
                )
            db.commit()
        return {"status": "ok" if game else "no_game", "rows": output, "policy": CAPITAL_ALLOCATION_POLICY}

    def interaction_risks(self, db: Session, persist: bool = False) -> dict:
        game = latest_trading_game(db)
        plan = self.allocation_plan(db, persist=False)
        weights = {item["ticker"]: safe_float(item["recommended_weight"]) for item in plan.get("allocations", [])}
        latest_correlations = correlation_lookup(db)
        rows = []
        tickers = list(weights)
        for index, ticker_a in enumerate(tickers):
            for ticker_b in tickers[index + 1 :]:
                key = tuple(sorted([ticker_a, ticker_b]))
                corr = latest_correlations.get(key)
                combined = weights[ticker_a] + weights[ticker_b]
                risk = interaction_risk_score(corr, combined)
                if risk >= 35:
                    rows.append(
                        {
                            "interaction_type": "correlation_concentration",
                            "entity_a": ticker_a,
                            "entity_b": ticker_b,
                            "risk_score": round(risk, 2),
                            "correlation": corr,
                            "combined_weight": round(combined, 4),
                            "recommendation": "Cap combined exposure or require stronger independent evidence." if risk >= 65 else "Monitor correlation before adding capital.",
                            "evidence": {"weights": {ticker_a: weights[ticker_a], ticker_b: weights[ticker_b]}},
                        }
                    )
        sector_weights = defaultdict(float)
        for item in plan.get("allocations", []):
            sector_weights[item.get("sector") or "Unknown"] += safe_float(item["recommended_weight"])
        for sector, weight in sector_weights.items():
            if weight >= 30:
                rows.append(
                    {
                        "interaction_type": "sector_concentration",
                        "entity_a": sector,
                        "entity_b": None,
                        "risk_score": round(clamp(weight * 1.4), 2),
                        "correlation": None,
                        "combined_weight": round(weight, 4),
                        "recommendation": "Sector allocation is high; require benchmark-relative confirmation before adding more.",
                        "evidence": {"sector_weight": weight},
                    }
                )
        rows = sorted(rows, key=lambda item: safe_float(item["risk_score"]), reverse=True)
        if persist:
            for item in rows:
                db.add(
                    CapitalInteractionRisk(
                        game_id=game.id if game else None,
                        interaction_type=item["interaction_type"],
                        entity_a=item["entity_a"],
                        entity_b=item.get("entity_b"),
                        risk_score=item["risk_score"],
                        correlation=item.get("correlation"),
                        combined_weight=item.get("combined_weight"),
                        recommendation=item["recommendation"],
                        evidence_json=item.get("evidence", {}),
                    )
                )
            db.commit()
        return {"status": "ok" if game else "no_game", "rows": rows, "policy": CAPITAL_ALLOCATION_POLICY}

    def recalculate(self, db: Session) -> dict:
        return {
            "status": "ok",
            "opportunity_scores": self.opportunity_scores(db, persist=True),
            "cash_policy": self.cash_policy(db, persist=True),
            "allocation_plan": self.allocation_plan(db, persist=True),
            "allocation_efficiency": self.allocation_efficiency(db, persist=True),
            "sizing_logic": self.sizing_logic_effectiveness(db, persist=True),
            "interaction_risks": self.interaction_risks(db, persist=True),
            "policy": CAPITAL_ALLOCATION_POLICY,
        }


def latest_portfolio_alpha(db: Session) -> dict[str, dict]:
    rows = db.scalars(select(PortfolioAlphaScore).order_by(desc(PortfolioAlphaScore.calculated_at)).limit(250)).all()
    output: dict[str, dict] = {}
    for row in rows:
        output.setdefault(
            row.ticker,
            {
                "ticker": row.ticker,
                "portfolio_alpha_score": row.portfolio_alpha_score,
                "marginal_return_score": row.marginal_return_score,
                "marginal_risk_score": row.marginal_risk_score,
                "benchmark_excess_score": row.benchmark_excess_score,
            },
        )
    return output


def latest_business_quality(db: Session) -> dict[str, dict]:
    rows = db.scalars(select(BusinessQualityScore).order_by(desc(BusinessQualityScore.calculated_at)).limit(500)).all()
    output: dict[str, dict] = {}
    for row in rows:
        output.setdefault(
            row.ticker,
            {
                "ticker": row.ticker,
                "business_quality_score": row.business_quality_score,
                "growth_quality": row.growth_quality,
                "profitability_quality": row.profitability_quality,
                "capital_allocation_quality": row.capital_allocation_quality,
            },
        )
    return output


def safe_decision_evidence(db: Session, trade: TradingGameTrade) -> dict:
    try:
        return decision_evidence_for_trade(db, trade)
    except Exception as exc:
        return {"status": "degraded", "error": f"{type(exc).__name__}: {exc}", "selection_quality": 45.0}


def sample_penalty_for(sample_size: int) -> float:
    if sample_size < 3:
        return 25.0
    if sample_size < 10:
        return 14.0
    if sample_size < 30:
        return 7.0
    return 0.0


def capital_alpha_score(average_r: float | None, benchmark_excess: float | None, drawdown: float | None) -> float:
    return clamp(50 + safe_float(average_r) * 18 + safe_float(benchmark_excess) * 0.8 + safe_float(drawdown) * 0.7)


def portfolio_fit_score(alpha: dict, quality: dict, decision: dict, reproducibility: float) -> float:
    return clamp(
        safe_float(alpha.get("portfolio_alpha_score"), 45.0) * 0.35
        + safe_float(quality.get("business_quality_score"), 45.0) * 0.25
        + safe_float(decision.get("selection_quality"), 45.0) * 0.25
        + safe_float(reproducibility) * 0.15
    )


def sizing_confidence_score(trades: list[TradingGameTrade], latest: TradingGameTrade) -> float:
    hit_rate = sum(1 for row in trades if safe_float(row.realized_r_multiple) > 0) / max(1, len(trades))
    avg_risk = mean([safe_float(row.risk_percent) for row in trades]) if trades else 0.0
    confidence = safe_float(latest.confidence_at_entry, 50.0)
    return clamp(40 + hit_rate * 35 + confidence * 0.25 - max(0.0, avg_risk - 1.5) * 12)


def max_weight_for(score: float, drawdown: float, sample_size: int) -> float:
    cap = 4.0 + score * 0.18
    if sample_size < 10:
        cap *= 0.55
    if drawdown <= -10:
        cap *= 0.6
    return round(clamp(cap, 0.0, 18.0), 4)


def capital_decision_state(score: float, cash_penalty: float, max_weight: float) -> str:
    if score < 35 or max_weight <= 1:
        return "cash_only_watch"
    if cash_penalty >= 20:
        return "research_only"
    if score >= 72:
        return "priority_allocation_candidate"
    if score >= 55:
        return "measured_allocation_candidate"
    return "monitor"


def opportunity_explanation(ticker: str, score: float, average_r: float | None, benchmark_excess: float | None, cash_penalty: float, decision_state: str) -> str:
    return (
        f"{ticker} capital score {score:.1f}/100 ({decision_state}). "
        f"Average R {round_or_none(average_r)}, benchmark excess {round_or_none(benchmark_excess)}; "
        f"cash penalty {cash_penalty:.1f} reflects sample size, drawdown and benchmark evidence."
    )


def allocation_warnings(opportunities: dict, cash_policy: dict, allocations: list[dict]) -> list[str]:
    warnings = []
    if opportunities.get("sample_size", 0) < 30:
        warnings.append("Capital allocation evidence is low sample; weights are capped and cash is elevated.")
    if safe_float(cash_policy.get("cash_reserve_percent")) >= 50:
        warnings.append("Cash reserve is high because BLUM does not yet have enough robust deployable evidence.")
    if not allocations:
        warnings.append("No opportunity cleared the minimum capital-score threshold.")
    if any(safe_float(item.get("recommended_weight")) >= 15 for item in allocations):
        warnings.append("One or more allocations are near the single-position cap; monitor concentration.")
    return warnings


def allocation_quality_score(opportunities: dict, cash_policy: dict, allocations: list[dict]) -> float:
    if not allocations:
        return 0.0
    avg_score = mean([safe_float(item["capital_score"]) for item in allocations])
    cash_penalty = max(0.0, safe_float(cash_policy.get("cash_reserve_percent")) - 25) * 0.45
    sample_penalty = 18 if opportunities.get("sample_size", 0) < 30 else 0
    return clamp(avg_score - cash_penalty - sample_penalty)


def explain_allocation(quality: float, cash_weight: float, warnings: list[str]) -> str:
    text = f"Capital Allocation Quality is {quality:.1f}/100 with {cash_weight:.1f}% cash reserve."
    if warnings:
        text += f" Main warning: {warnings[0]}"
    return text


def cash_decision_state(cash: float, expectancy: float, benchmark_excess: float) -> str:
    if cash >= 65:
        return "defensive_cash"
    if cash >= 45:
        return "partial_cash"
    if expectancy > 0 and benchmark_excess > 0:
        return "selective_deployment"
    return "balanced_cash"


def cash_explanation(cash: float, decision_state: str, reasons: list[str]) -> str:
    return f"Cash policy is {decision_state}: {cash:.1f}% reserve. " + (reasons[0] if reasons else "No strong reserve override detected.")


def most_common(values: list[str]) -> str | None:
    if not values:
        return None
    counts = defaultdict(int)
    for value in values:
        counts[value] += 1
    return sorted(counts.items(), key=lambda item: item[1], reverse=True)[0][0]


def trade_allocation_audit(trade: TradingGameTrade) -> dict:
    actual_risk = safe_float(trade.risk_percent)
    ideal_risk = ideal_risk_percent(trade)
    capital = max(0.01, safe_float(trade.capital_before))
    actual_pnl = safe_float(trade.net_pnl_eur if trade.net_pnl_eur is not None else trade.realized_pl)
    ideal_pnl = capital * ideal_risk / 100 * safe_float(trade.realized_r_multiple)
    regret = max(0.0, ideal_pnl - actual_pnl)
    allocation_error = "efficient"
    if ideal_risk > actual_risk and safe_float(trade.realized_r_multiple) > 0:
        allocation_error = "underallocated_winner"
    elif ideal_risk < actual_risk and safe_float(trade.realized_r_multiple) <= 0:
        allocation_error = "overallocated_loser"
    return {
        "trade_id": trade.id,
        "ticker": trade.ticker,
        "setup_type": trade.setup_type,
        "actual_risk_percent": round(actual_risk, 4),
        "ideal_risk_percent": round(ideal_risk, 4),
        "actual_pnl_eur": round(actual_pnl, 4),
        "ideal_pnl_eur": round(ideal_pnl, 4),
        "regret_eur": round(regret, 4),
        "r_multiple": trade.realized_r_multiple,
        "benchmark_excess": trade.excess_return_vs_benchmark,
        "allocation_error": allocation_error,
    }


def ideal_risk_percent(trade: TradingGameTrade) -> float:
    r = safe_float(trade.realized_r_multiple)
    excess = safe_float(trade.excess_return_vs_benchmark)
    if r <= -0.25 or trade.stop_hit:
        return 0.0
    if r >= 2 and excess >= 0:
        return 1.8
    if r >= 1:
        return 1.25
    if r > 0:
        return 0.75
    return 0.25


def cash_drag_estimate(rows: list[TradingGameTrade]) -> float | None:
    no_trade = [row for row in rows if row.decision_state in {"avoid", "wait_for_trigger"}]
    missed = [row for row in no_trade if row.missed_entry or safe_float(row.realized_r_multiple) > 0.75]
    if not no_trade:
        return None
    return round(sum(max(0.0, safe_float(row.realized_r_multiple)) for row in missed), 4)


def allocation_efficiency_recommendations(score: float, underallocated: list[dict], overallocated: list[dict], rows: list[TradingGameTrade]) -> list[str]:
    recommendations = []
    if score < 60:
        recommendations.append("Run more allocation audits before increasing deployment; current capital placement is not efficient enough.")
    if underallocated:
        recommendations.append("Study underallocated winners to identify conditions where capital deserved a larger risk budget.")
    if overallocated:
        recommendations.append("Tighten no-trade and sizing rules for setups that consumed risk budget and produced negative R.")
    if len(rows) < 50:
        recommendations.append("Sample size is still limited; keep allocation changes conservative.")
    return recommendations or ["No immediate capital-allocation correction detected."]


def sizing_logic_for_trade(trade: TradingGameTrade) -> str:
    if trade.decision_state in {"avoid", "wait_for_trigger"}:
        return "cash_or_no_trade"
    if safe_float(trade.risk_percent) <= 0.5:
        return "defensive_fractional"
    if safe_float(trade.confidence_at_entry) >= 65 and safe_float(trade.risk_percent) <= 1.5:
        return "confidence_adjusted_fractional"
    if safe_float(trade.risk_percent) > 1.5:
        return "aggressive_fractional"
    return "fixed_fractional"


def sizing_risk_adjusted_alpha(avg_r: float | None, benchmark_excess: float | None, max_drawdown: float | None) -> float:
    return clamp(50 + safe_float(avg_r) * 22 + safe_float(benchmark_excess) * 0.9 + safe_float(max_drawdown) * 0.55)


def recommended_risk_for_logic(score: float, sample_size: int, max_drawdown: float) -> float:
    if sample_size < 30:
        return 0.5
    if score >= 70 and max_drawdown > -8:
        return 1.25
    if score >= 55:
        return 1.0
    return 0.35


def sizing_recommendation(score: float, sample_size: int, max_drawdown: float) -> str:
    if sample_size < 30:
        return "collect_more_samples"
    if score >= 70 and max_drawdown > -8:
        return "eligible_for_measured_increase"
    if score < 45 or max_drawdown <= -12:
        return "reduce_or_freeze"
    return "maintain"


def correlation_lookup(db: Session) -> dict[tuple[str, str], float | None]:
    rows = db.scalars(select(PortfolioCorrelation).order_by(desc(PortfolioCorrelation.calculated_at)).limit(300)).all()
    output: dict[tuple[str, str], float | None] = {}
    for row in rows:
        key = tuple(sorted([row.asset_a, row.asset_b]))
        output.setdefault(key, row.correlation)
    if output:
        return output
    generated = PortfolioIntelligenceEngine().correlations(db, persist=False)["rows"]
    return {tuple(sorted([row["asset_a"], row["asset_b"]])): row.get("correlation") for row in generated}


def interaction_risk_score(correlation: float | None, combined_weight: float) -> float:
    corr = abs(safe_float(correlation))
    if correlation is None:
        corr = 0.35
    return clamp(combined_weight * 1.2 + corr * 55)
