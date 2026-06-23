from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from math import sqrt
from statistics import mean, median, pstdev

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import (
    AlphaCaptureMetric,
    Asset,
    BusinessQualityProfile,
    BusinessQualityScore,
    DecisionSuperiorityScore,
    DecisionUniverseSnapshot,
    FundamentalAlphaPattern,
    FundamentalSnapshot,
    ManagementQualityProfile,
    OpportunityPrecisionMetric,
    OpportunityRecallMetric,
    PortfolioAlphaScore,
    PortfolioContribution,
    PortfolioCorrelation,
    PortfolioQualityScore,
    PositionSizingOutcome,
    PriceHistory,
    RankingAccuracyMetric,
    SignalSnapshot,
    TradingGame,
    TradingGameTrade,
)
from app.services.learning_intelligence import (
    BenchmarkComparisonService,
    game_trades,
    latest_trading_game,
    round_or_none,
    statistical_confidence_label,
)
from app.services.trade_transparency import clamp, safe_float
from app.services.trading_intelligence_lab import executable_trades, metric_payload, sample_context


DECISION_INTELLIGENCE_POLICY = (
    "Decision Intelligence measures selection quality against available alternatives, business quality and portfolio context. "
    "It must report insufficient evidence instead of claiming decision superiority without comparable samples."
)


class DecisionSuperiorityEngine:
    """Measures whether BLUM selected the best available opportunity, not only whether a trade worked."""

    def dashboard(self, db: Session) -> dict:
        return {
            "status": "ok",
            "policy": DECISION_INTELLIGENCE_POLICY,
            "decision_superiority": self.score(db, persist=False),
            "universe_snapshots": self.universe_snapshots(db, persist=False),
            "top_missed_opportunities": self.top_missed_opportunities(db),
            "best_decisions": self.best_decisions(db),
            "worst_decisions": self.worst_decisions(db),
        }

    def score(self, db: Session, persist: bool = False) -> dict:
        game = latest_trading_game(db)
        rows = executable_trades(game_trades(db, game.id if game else None))
        decisions = [decision_evidence_for_trade(db, row) for row in rows]
        decisions = [item for item in decisions if item["candidate_count"] >= 2]
        metrics = decision_superiority_metrics(decisions, rows)
        components = decision_superiority_components(metrics, rows)
        score = weighted_average(
            [
                components["opportunity_recall"],
                components["opportunity_precision"],
                components["alpha_capture"],
                components["ranking_accuracy"],
                components["benchmark_excess"],
                components["live_validation"],
                components["regime_consistency"],
                components["reproducibility"],
                components["drawdown_control"],
            ]
        )
        warnings = decision_superiority_warnings(metrics, rows)
        classification = classify_decision_superiority(score)
        explanation = decision_superiority_explanation(score, classification, metrics, warnings)
        payload = {
            "status": "ok" if game else "no_game",
            "calculated_at": datetime.utcnow().isoformat(),
            "mode": "historical_plus_live",
            "scope": "global",
            "score": round(score, 2),
            "classification": classification,
            "components": components,
            "metrics": metrics,
            "warnings": warnings,
            "sample_size": len(decisions),
            "statistical_confidence": statistical_confidence_label(len(decisions), count_live(rows), sample_context(rows)),
            "explanation": explanation,
            "policy": DECISION_INTELLIGENCE_POLICY,
        }
        if persist:
            db.add(
                OpportunityRecallMetric(
                    sector="All",
                    setup="All",
                    regime="All",
                    timeframe="All",
                    captured_outperformers=metrics.get("captured_outperformers", 0),
                    total_outperformers=metrics.get("total_outperformers", 0),
                    opportunity_recall=metrics.get("opportunity_recall"),
                    evidence_json=metrics,
                )
            )
            db.add(
                OpportunityPrecisionMetric(
                    sector="All",
                    setup="All",
                    regime="All",
                    timeframe="All",
                    successful_opportunities=metrics.get("successful_opportunities", 0),
                    selected_opportunities=metrics.get("selected_opportunities", 0),
                    opportunity_precision=metrics.get("opportunity_precision"),
                    evidence_json=metrics,
                )
            )
            db.add(
                AlphaCaptureMetric(
                    ticker="All",
                    sector="All",
                    regime="All",
                    timeframe="All",
                    available_alpha=metrics.get("available_alpha"),
                    captured_alpha=metrics.get("captured_alpha"),
                    alpha_capture_rate=metrics.get("alpha_capture_rate"),
                    evidence_json=metrics,
                )
            )
            db.add(
                RankingAccuracyMetric(
                    sector="All",
                    setup="All",
                    regime="All",
                    timeframe="All",
                    sample_size=metrics.get("sample_size", 0),
                    top1_accuracy=metrics.get("top1_accuracy"),
                    top3_accuracy=None,
                    top5_accuracy=None,
                    ranking_correlation=metrics.get("ranking_accuracy"),
                    ranking_decay=None,
                    evidence_json=metrics,
                )
            )
            db.add(
                DecisionSuperiorityScore(
                    mode=payload["mode"],
                    scope=payload["scope"],
                    score=payload["score"],
                    classification=classification,
                    opportunity_recall=metrics.get("opportunity_recall"),
                    opportunity_precision=metrics.get("opportunity_precision"),
                    alpha_capture=metrics.get("alpha_capture_rate"),
                    ranking_accuracy=metrics.get("ranking_accuracy"),
                    benchmark_excess=metrics.get("benchmark_excess"),
                    live_validation=components["live_validation"],
                    regime_consistency=components["regime_consistency"],
                    reproducibility=components["reproducibility"],
                    drawdown_control=components["drawdown_control"],
                    explanation=explanation,
                    warnings_json={"warnings": warnings, "metrics": metrics},
                )
            )
            db.commit()
        return payload

    def universe_snapshots(self, db: Session, persist: bool = False) -> dict:
        game = latest_trading_game(db)
        rows = executable_trades(game_trades(db, game.id if game else None))[:80]
        snapshots = [decision_universe_snapshot_payload(db, row) for row in rows]
        if persist:
            for item in snapshots:
                db.add(
                    DecisionUniverseSnapshot(
                        timestamp=parse_dt(item["timestamp"]) or datetime.utcnow(),
                        market_regime=item.get("market_regime"),
                        volatility_regime=item.get("volatility_regime"),
                        selected_asset=item["selected_asset"],
                        selected_rank=item.get("selected_rank"),
                        selected_score=item.get("selected_score"),
                        total_candidates=item.get("total_candidates", 0),
                        candidates_json={"candidates": item.get("candidates", [])},
                        benchmark_snapshot=item.get("benchmark_snapshot", {}),
                    )
                )
            db.commit()
        return {"status": "ok" if game else "no_game", "snapshots": snapshots, "policy": DECISION_INTELLIGENCE_POLICY}

    def top_missed_opportunities(self, db: Session) -> list[dict]:
        rows = executable_trades(game_trades(db, latest_trading_game(db).id if latest_trading_game(db) else None))
        missed = []
        for row in rows:
            evidence = decision_evidence_for_trade(db, row)
            if evidence.get("missed_best"):
                missed.append(evidence)
        return sorted(missed, key=lambda item: safe_float(item.get("opportunity_gap")), reverse=True)[:12]

    def best_decisions(self, db: Session) -> list[dict]:
        rows = executable_trades(game_trades(db, latest_trading_game(db).id if latest_trading_game(db) else None))
        evidence = [decision_evidence_for_trade(db, row) for row in rows]
        return sorted(evidence, key=lambda item: safe_float(item.get("selection_quality")), reverse=True)[:12]

    def worst_decisions(self, db: Session) -> list[dict]:
        rows = executable_trades(game_trades(db, latest_trading_game(db).id if latest_trading_game(db) else None))
        evidence = [decision_evidence_for_trade(db, row) for row in rows]
        return sorted(evidence, key=lambda item: safe_float(item.get("selection_quality")))[:12]


class BusinessQualityEngine:
    """Scores business quality from stored fundamental evidence and clearly penalizes missing data."""

    def dashboard(self, db: Session, limit: int = 40) -> dict:
        rows = self.scores(db, limit=limit, persist=False)["rows"]
        return {
            "status": "ok",
            "policy": DECISION_INTELLIGENCE_POLICY,
            "highest_quality_companies": rows[:12],
            "strongest_moats": sorted(rows, key=lambda item: safe_float(item.get("moat_quality")), reverse=True)[:12],
            "best_capital_allocation": sorted(rows, key=lambda item: safe_float(item.get("capital_allocation_quality")), reverse=True)[:12],
            "highest_fundamental_alpha_score": sorted(rows, key=lambda item: safe_float(item.get("fundamental_alpha_score")), reverse=True)[:12],
            "improving_businesses": [row for row in rows if row.get("trend_label") == "improving"][:12],
            "deteriorating_businesses": [row for row in rows if row.get("trend_label") == "deteriorating"][:12],
            "fundamental_alpha_patterns": self.fundamental_alpha_patterns(db, persist=False)["rows"],
        }

    def scores(self, db: Session, limit: int = 80, persist: bool = False) -> dict:
        assets = db.scalars(
            select(Asset)
            .where(Asset.asset_type == "Stock", Asset.is_active.is_(True))
            .order_by(Asset.ticker)
            .limit(limit)
        ).all()
        rows = [business_quality_for_asset(db, asset) for asset in assets]
        rows = sorted(rows, key=lambda item: safe_float(item.get("business_quality_score")), reverse=True)
        if persist:
            for item in rows:
                asset = db.scalar(select(Asset).where(Asset.ticker == item["ticker"]))
                db.add(
                    BusinessQualityProfile(
                        asset_id=asset.id if asset else None,
                        ticker=item["ticker"],
                        growth_quality=item.get("growth_quality"),
                        profitability_quality=item.get("profitability_quality"),
                        cash_flow_quality=item.get("cash_flow_quality"),
                        balance_sheet_quality=item.get("balance_sheet_quality"),
                        capital_allocation_quality=item.get("capital_allocation_quality"),
                        moat_quality=item.get("moat_quality"),
                        evidence_json=item.get("evidence", {}),
                    )
                )
                db.add(
                    ManagementQualityProfile(
                        asset_id=asset.id if asset else None,
                        ticker=item["ticker"],
                        insider_alignment=item.get("management_components", {}).get("insider_alignment"),
                        execution_consistency=item.get("management_components", {}).get("execution_consistency"),
                        earnings_delivery=item.get("management_components", {}).get("earnings_delivery"),
                        management_quality=item.get("management_quality"),
                        evidence_json=item.get("management_components", {}),
                    )
                )
                db.add(
                    BusinessQualityScore(
                        asset_id=asset.id if asset else None,
                        ticker=item["ticker"],
                        sector=item.get("sector"),
                        business_quality_score=item["business_quality_score"],
                        growth_quality=item.get("growth_quality"),
                        profitability_quality=item.get("profitability_quality"),
                        cash_flow_quality=item.get("cash_flow_quality"),
                        balance_sheet_quality=item.get("balance_sheet_quality"),
                        capital_allocation_quality=item.get("capital_allocation_quality"),
                        moat_quality=item.get("moat_quality"),
                        management_quality=item.get("management_quality"),
                        data_quality_score=item.get("data_quality_score", 0),
                        evidence_json=item.get("evidence", {}),
                    )
                )
            db.commit()
        return {"status": "ok", "rows": rows, "policy": DECISION_INTELLIGENCE_POLICY}

    def fundamental_alpha_patterns(self, db: Session, persist: bool = False) -> dict:
        rows = []
        trades = executable_trades(game_trades(db, latest_trading_game(db).id if latest_trading_game(db) else None))
        by_sector: dict[str, list[TradingGameTrade]] = defaultdict(list)
        for trade in trades:
            by_sector[trade.sector or "Unknown"].append(trade)
        for sector, group in by_sector.items():
            returns = [safe_float(row.pnl_percent if row.pnl_percent is not None else row.excess_return_vs_benchmark) for row in group]
            rows.append(
                {
                    "pattern_name": "quality_plus_positive_trade_outcome",
                    "sector": sector,
                    "timeframe": "trade_horizon",
                    "sample_size": len(group),
                    "average_forward_return": round_or_none(mean(returns) if returns else None),
                    "hit_rate": round_or_none(sum(1 for value in returns if value > 0) / max(1, len(returns))),
                    "evidence": {"tickers": sorted({row.ticker for row in group})[:20]},
                }
            )
        if persist:
            for item in rows:
                db.add(
                    FundamentalAlphaPattern(
                        pattern_name=item["pattern_name"],
                        sector=item.get("sector"),
                        timeframe=item.get("timeframe"),
                        sample_size=item["sample_size"],
                        average_forward_return=item.get("average_forward_return"),
                        hit_rate=item.get("hit_rate"),
                        evidence_json=item.get("evidence", {}),
                    )
                )
            db.commit()
        return {"status": "ok", "rows": rows, "policy": DECISION_INTELLIGENCE_POLICY}


class PortfolioIntelligenceEngine:
    """Measures whether individual decisions improve the simulated portfolio."""

    def dashboard(self, db: Session) -> dict:
        return {
            "status": "ok",
            "policy": DECISION_INTELLIGENCE_POLICY,
            "portfolio_quality": self.quality_score(db, persist=False),
            "contributions": self.contributions(db, persist=False)["rows"],
            "correlations": self.correlations(db, persist=False)["rows"],
            "portfolio_alpha": self.alpha_scores(db, persist=False)["rows"],
            "position_sizing": self.position_sizing_outcomes(db, persist=False)["rows"],
        }

    def quality_score(self, db: Session, persist: bool = False) -> dict:
        game = latest_trading_game(db)
        rows = executable_trades(game_trades(db, game.id if game else None))
        metrics = metric_payload(rows, "portfolio", str(game.id) if game else None, "all", None)
        contributions = portfolio_contribution_rows(rows)
        concentration = concentration_score(contributions)
        diversification = clamp(100 - concentration)
        drawdown_control = clamp(100 + safe_float(metrics.get("max_drawdown")) * 3)
        alpha_generation = clamp(50 + safe_float(metrics.get("benchmark_excess")) * 2)
        capital_efficiency = clamp(50 + safe_float(metrics.get("expectancy_r")) * 25)
        score = weighted_average([diversification, drawdown_control, alpha_generation, capital_efficiency, safe_float(metrics.get("risk_reward_quality_score"), 50)])
        warnings = portfolio_warnings(rows, concentration, metrics)
        explanation = f"Portfolio Quality Score {score:.1f}/100. Diversification {diversification:.1f}, drawdown control {drawdown_control:.1f}, alpha generation {alpha_generation:.1f}."
        payload = {
            "status": "ok" if game else "no_game",
            "score": round(score, 2),
            "components": {
                "diversification": round(diversification, 2),
                "concentration_risk": round(concentration, 2),
                "drawdown_control": round(drawdown_control, 2),
                "alpha_generation": round(alpha_generation, 2),
                "benchmark_excess": round_or_none(metrics.get("benchmark_excess")),
                "capital_efficiency": round(capital_efficiency, 2),
            },
            "sample_size": len(rows),
            "warnings": warnings,
            "explanation": explanation,
            "policy": DECISION_INTELLIGENCE_POLICY,
        }
        if persist:
            db.add(
                PortfolioQualityScore(
                    game_id=game.id if game else None,
                    portfolio_quality_score=payload["score"],
                    diversification=payload["components"]["diversification"],
                    concentration_risk=payload["components"]["concentration_risk"],
                    drawdown_control=payload["components"]["drawdown_control"],
                    alpha_generation=payload["components"]["alpha_generation"],
                    benchmark_excess=payload["components"]["benchmark_excess"],
                    capital_efficiency=payload["components"]["capital_efficiency"],
                    explanation=explanation,
                    warnings_json={"warnings": warnings},
                )
            )
            db.commit()
        return payload

    def contributions(self, db: Session, persist: bool = False) -> dict:
        game = latest_trading_game(db)
        rows = portfolio_contribution_rows(executable_trades(game_trades(db, game.id if game else None)))
        if persist:
            for item in rows:
                db.add(
                    PortfolioContribution(
                        game_id=game.id if game else None,
                        ticker=item["ticker"],
                        sector=item.get("sector"),
                        return_contribution=item.get("return_contribution"),
                        risk_contribution=item.get("risk_contribution"),
                        drawdown_contribution=item.get("drawdown_contribution"),
                        alpha_contribution=item.get("alpha_contribution"),
                        evidence_json=item,
                    )
                )
            db.commit()
        return {"status": "ok" if game else "no_game", "rows": rows, "policy": DECISION_INTELLIGENCE_POLICY}

    def correlations(self, db: Session, persist: bool = False) -> dict:
        game = latest_trading_game(db)
        tickers = sorted({row.ticker for row in executable_trades(game_trades(db, game.id if game else None))})[:14]
        rows = correlation_rows(db, tickers)
        if persist:
            for item in rows:
                db.add(
                    PortfolioCorrelation(
                        scope=f"game:{game.id}" if game else "global",
                        asset_a=item["asset_a"],
                        asset_b=item["asset_b"],
                        correlation=item.get("correlation"),
                        correlation_type="price_return",
                        evidence_json=item.get("evidence", {}),
                    )
                )
            db.commit()
        return {"status": "ok" if game else "no_game", "rows": rows, "policy": DECISION_INTELLIGENCE_POLICY}

    def alpha_scores(self, db: Session, persist: bool = False) -> dict:
        game = latest_trading_game(db)
        contributions = portfolio_contribution_rows(executable_trades(game_trades(db, game.id if game else None)))
        rows = []
        for item in contributions:
            score = clamp(50 + safe_float(item.get("alpha_contribution")) * 2 - safe_float(item.get("risk_contribution")) * 0.2 + (20 if safe_float(item.get("return_contribution")) > 0 else -10))
            rows.append({**item, "portfolio_alpha_score": round(score, 2), "marginal_return_score": round(clamp(50 + safe_float(item.get("return_contribution")) * 2), 2), "marginal_risk_score": round(clamp(100 - safe_float(item.get("risk_contribution"))), 2), "diversification_score": None, "benchmark_excess_score": round(clamp(50 + safe_float(item.get("alpha_contribution")) * 2), 2)})
        rows = sorted(rows, key=lambda item: safe_float(item.get("portfolio_alpha_score")), reverse=True)
        if persist:
            for item in rows:
                db.add(
                    PortfolioAlphaScore(
                        game_id=game.id if game else None,
                        ticker=item["ticker"],
                        portfolio_alpha_score=item["portfolio_alpha_score"],
                        marginal_return_score=item.get("marginal_return_score"),
                        marginal_risk_score=item.get("marginal_risk_score"),
                        diversification_score=item.get("diversification_score"),
                        benchmark_excess_score=item.get("benchmark_excess_score"),
                        evidence_json=item,
                    )
                )
            db.commit()
        return {"status": "ok" if game else "no_game", "rows": rows, "policy": DECISION_INTELLIGENCE_POLICY}

    def position_sizing_outcomes(self, db: Session, persist: bool = False) -> dict:
        rows = executable_trades(game_trades(db, latest_trading_game(db).id if latest_trading_game(db) else None))
        buckets: dict[str, list[TradingGameTrade]] = defaultdict(list)
        for row in rows:
            logic = "confidence_adjusted" if safe_float(row.confidence_at_entry) >= 65 else "fixed_fractional"
            if safe_float(row.risk_percent) > 1.5:
                logic = "higher_risk_fractional"
            buckets[logic].append(row)
        output = []
        for logic, group in buckets.items():
            r_values = [safe_float(row.realized_r_multiple) for row in group if row.realized_r_multiple is not None]
            output.append(
                {
                    "sizing_logic": logic,
                    "timeframe": "trade_horizon",
                    "sample_size": len(group),
                    "average_r": round_or_none(mean(r_values) if r_values else None),
                    "drawdown_impact": round_or_none(min([safe_float(row.pnl_percent) for row in group], default=0)),
                    "capital_efficiency": round_or_none(mean([safe_float(row.net_pnl_eur if row.net_pnl_eur is not None else row.realized_pl) for row in group]) if group else None),
                    "evidence": {"tickers": sorted({row.ticker for row in group})[:16]},
                }
            )
        if persist:
            for item in output:
                db.add(
                    PositionSizingOutcome(
                        sizing_logic=item["sizing_logic"],
                        timeframe=item.get("timeframe"),
                        sample_size=item["sample_size"],
                        average_r=item.get("average_r"),
                        drawdown_impact=item.get("drawdown_impact"),
                        capital_efficiency=item.get("capital_efficiency"),
                        evidence_json=item.get("evidence", {}),
                    )
                )
            db.commit()
        return {"status": "ok", "rows": output, "policy": DECISION_INTELLIGENCE_POLICY}


class DecisionIntelligenceDashboardService:
    def dashboard(self, db: Session) -> dict:
        return {
            "status": "ok",
            "generated_at": datetime.utcnow().isoformat(),
            "decision": DecisionSuperiorityEngine().dashboard(db),
            "business_quality": BusinessQualityEngine().dashboard(db),
            "portfolio": PortfolioIntelligenceEngine().dashboard(db),
            "policy": DECISION_INTELLIGENCE_POLICY,
        }


def decision_universe_snapshot_payload(db: Session, trade: TradingGameTrade) -> dict:
    evidence = decision_evidence_for_trade(db, trade)
    return {
        "timestamp": (trade.entry_date or trade.created_at.date()).isoformat() if hasattr((trade.entry_date or trade.created_at), "isoformat") else datetime.utcnow().isoformat(),
        "market_regime": trade.market_regime_at_entry or "unknown",
        "volatility_regime": volatility_regime_for_trade(trade),
        "selected_asset": trade.ticker,
        "selected_rank": evidence.get("selected_rank"),
        "selected_score": evidence.get("selected_score"),
        "total_candidates": evidence.get("candidate_count", 0),
        "candidates": evidence.get("candidates", [])[:20],
        "benchmark_snapshot": {"benchmark": trade.benchmark_ticker or "SPY", "benchmark_return": trade.benchmark_return_same_period or trade.benchmark_return},
    }


def decision_evidence_for_trade(db: Session, trade: TradingGameTrade) -> dict:
    candidates = candidate_returns_for_trade(db, trade)
    selected_score = safe_float(trade.sniper_score_at_entry if trade.sniper_score_at_entry is not None else trade.opportunity_score_at_entry)
    if not any(item["ticker"] == trade.ticker for item in candidates):
        candidates.append(
            {
                "ticker": trade.ticker,
                "score": selected_score,
                "realized_return": selected_return(trade),
                "sector": trade.sector,
                "selected": True,
            }
        )
    candidates = dedupe_candidates(candidates)
    ranked = sorted(candidates, key=lambda item: safe_float(item.get("score")), reverse=True)
    realized_sorted = sorted(candidates, key=lambda item: safe_float(item.get("realized_return")), reverse=True)
    selected = next((item for item in ranked if item["ticker"] == trade.ticker), ranked[0] if ranked else None)
    selected_rank = next((index + 1 for index, item in enumerate(ranked) if item["ticker"] == trade.ticker), None)
    best = realized_sorted[0] if realized_sorted else selected
    selected_ret = safe_float(selected.get("realized_return") if selected else selected_return(trade))
    best_ret = safe_float(best.get("realized_return") if best else selected_ret)
    benchmark = safe_float(trade.benchmark_return_same_period if trade.benchmark_return_same_period is not None else trade.benchmark_return)
    opportunity_gap = max(0.0, best_ret - selected_ret)
    selected_outperformed = selected_ret > benchmark and selected_ret > 0
    missed_best = bool(best and best.get("ticker") != trade.ticker and opportunity_gap > 1.0)
    top_score_ticker = ranked[0]["ticker"] if ranked else None
    best_return_ticker = best["ticker"] if best else None
    return {
        "trade_id": trade.id,
        "ticker": trade.ticker,
        "setup_type": trade.setup_type,
        "sector": trade.sector,
        "regime": trade.market_regime_at_entry,
        "timeframe": trade.timeframe,
        "selected_rank": selected_rank,
        "selected_score": round_or_none(selected_score),
        "selected_return": round_or_none(selected_ret),
        "best_available_ticker": best_return_ticker,
        "best_available_return": round_or_none(best_ret),
        "top_ranked_ticker": top_score_ticker,
        "benchmark_return": round_or_none(benchmark),
        "opportunity_gap": round_or_none(opportunity_gap),
        "selected_outperformed": selected_outperformed,
        "missed_best": missed_best,
        "candidate_count": len(candidates),
        "ranking_correct": top_score_ticker == best_return_ticker if top_score_ticker and best_return_ticker else None,
        "selection_quality": round_or_none(clamp(100 - opportunity_gap * 4 + (15 if selected_outperformed else -10))),
        "candidates": ranked[:20],
    }


def candidate_returns_for_trade(db: Session, trade: TradingGameTrade) -> list[dict]:
    start = trade.entry_date or (trade.created_at.date() if trade.created_at else None)
    end = trade.exit_date or (start + timedelta(days=30) if start else None)
    if not start or not end:
        return []
    signal_candidates = db.scalars(
        select(SignalSnapshot)
        .where(SignalSnapshot.created_at <= datetime.combine(start, datetime.max.time()))
        .order_by(desc(SignalSnapshot.created_at), desc(SignalSnapshot.blum_score))
        .limit(80)
    ).all()
    seen = set()
    output = []
    for signal in signal_candidates:
        if signal.ticker in seen:
            continue
        seen.add(signal.ticker)
        realized = ticker_return_between(db, signal.ticker, start, end)
        if realized is None:
            continue
        output.append({"ticker": signal.ticker, "score": safe_float(signal.blum_score), "realized_return": round(realized, 4), "sector": signal.asset.sector if signal.asset else None, "selected": signal.ticker == trade.ticker})
        if len(output) >= 20:
            break
    if len(output) < 2:
        same_day = db.scalars(select(TradingGameTrade).where(TradingGameTrade.entry_date == start).limit(30)).all()
        for row in same_day:
            if row.ticker in seen:
                continue
            seen.add(row.ticker)
            output.append({"ticker": row.ticker, "score": safe_float(row.sniper_score_at_entry if row.sniper_score_at_entry is not None else row.opportunity_score_at_entry), "realized_return": selected_return(row), "sector": row.sector, "selected": row.ticker == trade.ticker})
    return output


def decision_superiority_metrics(decisions: list[dict], rows: list[TradingGameTrade]) -> dict:
    if not decisions:
        return {"status": "insufficient_evidence", "sample_size": 0}
    outperformers = [item for item in decisions if item.get("best_available_return") is not None and safe_float(item.get("best_available_return")) > safe_float(item.get("benchmark_return"))]
    captured = [item for item in outperformers if item.get("selected_outperformed")]
    selected_success = [item for item in decisions if item.get("selected_outperformed")]
    available_alpha = sum(max(0, safe_float(item.get("best_available_return")) - safe_float(item.get("benchmark_return"))) for item in decisions)
    captured_alpha = sum(max(0, safe_float(item.get("selected_return")) - safe_float(item.get("benchmark_return"))) for item in decisions)
    ranking_known = [item for item in decisions if item.get("ranking_correct") is not None]
    ranking_accuracy = sum(1 for item in ranking_known if item.get("ranking_correct")) / max(1, len(ranking_known))
    benchmark_excess_values = [safe_float(row.excess_return_vs_benchmark) for row in rows if row.excess_return_vs_benchmark is not None]
    return {
        "status": "ok",
        "sample_size": len(decisions),
        "opportunity_recall": round_or_none(len(captured) / max(1, len(outperformers))),
        "captured_outperformers": len(captured),
        "total_outperformers": len(outperformers),
        "opportunity_precision": round_or_none(len(selected_success) / max(1, len(decisions))),
        "successful_opportunities": len(selected_success),
        "selected_opportunities": len(decisions),
        "alpha_capture_rate": round_or_none(captured_alpha / available_alpha if available_alpha else None),
        "available_alpha": round_or_none(available_alpha),
        "captured_alpha": round_or_none(captured_alpha),
        "ranking_accuracy": round_or_none(ranking_accuracy),
        "top1_accuracy": round_or_none(ranking_accuracy),
        "missed_opportunities": sum(1 for item in decisions if item.get("missed_best")),
        "benchmark_excess": round_or_none(mean(benchmark_excess_values) if benchmark_excess_values else None),
    }


def decision_superiority_components(metrics: dict, rows: list[TradingGameTrade]) -> dict:
    if metrics.get("status") == "insufficient_evidence":
        return {key: 0 for key in ["opportunity_recall", "opportunity_precision", "alpha_capture", "ranking_accuracy", "benchmark_excess", "live_validation", "regime_consistency", "reproducibility", "drawdown_control"]}
    live = [row for row in rows if row.mode == "live_forward_paper"]
    regimes = {row.market_regime_at_entry for row in rows if row.market_regime_at_entry}
    reproducibility = mean([safe_float(row.reproducibility_score) for row in rows]) if rows else 0
    drawdown_values = [safe_float(row.max_adverse_excursion) for row in rows if row.max_adverse_excursion is not None]
    return {
        "opportunity_recall": round(clamp(safe_float(metrics.get("opportunity_recall")) * 100), 2),
        "opportunity_precision": round(clamp(safe_float(metrics.get("opportunity_precision")) * 100), 2),
        "alpha_capture": round(clamp(safe_float(metrics.get("alpha_capture_rate")) * 100), 2),
        "ranking_accuracy": round(clamp(safe_float(metrics.get("ranking_accuracy")) * 100), 2),
        "benchmark_excess": round(clamp(50 + safe_float(metrics.get("benchmark_excess")) * 3), 2),
        "live_validation": round(clamp(min(100, len(live) * 3)), 2),
        "regime_consistency": round(clamp(len(regimes) * 18), 2),
        "reproducibility": round(clamp(reproducibility), 2),
        "drawdown_control": round(clamp(100 + (min(drawdown_values) if drawdown_values else 0) * 2), 2),
    }


def decision_superiority_warnings(metrics: dict, rows: list[TradingGameTrade]) -> list[str]:
    warnings = []
    if metrics.get("sample_size", 0) < 30:
        warnings.append("Insufficient comparable decision samples for a strong superiority claim.")
    if count_live(rows) < 30:
        warnings.append("Live forward evidence is not mature enough to validate selection superiority.")
    if safe_float(metrics.get("alpha_capture_rate")) < 0.5 and metrics.get("alpha_capture_rate") is not None:
        warnings.append("BLUM is leaving more than half of available alpha uncaptured in comparable samples.")
    if safe_float(metrics.get("ranking_accuracy")) < 0.5 and metrics.get("ranking_accuracy") is not None:
        warnings.append("Ranking accuracy is weak; BLUM may identify candidates but order them poorly.")
    return warnings


def business_quality_for_asset(db: Session, asset: Asset) -> dict:
    snapshots = db.scalars(select(FundamentalSnapshot).where(FundamentalSnapshot.asset_id == asset.id).order_by(desc(FundamentalSnapshot.period_end), desc(FundamentalSnapshot.created_at)).limit(6)).all()
    latest = snapshots[0] if snapshots else None
    metrics = latest.metrics if latest else {}
    data_quality = safe_float(latest.quality_score if latest else 0)
    revenue = metric_value(metrics, "revenue")
    net_income = metric_value(metrics, "net_income")
    operating_income = metric_value(metrics, "operating_income")
    operating_cash_flow = metric_value(metrics, "operating_cash_flow")
    capex = abs(metric_value(metrics, "capex") or 0)
    assets = metric_value(metrics, "assets")
    liabilities = metric_value(metrics, "liabilities")
    equity = metric_value(metrics, "equity")
    fcf = operating_cash_flow - capex if operating_cash_flow is not None else None
    growth = trend_score([metric_value(row.metrics, "revenue") for row in snapshots])
    profitability = clamp(45 + ratio_pct(net_income, revenue) * 2 + ratio_pct(operating_income, revenue))
    cash_flow = clamp(45 + ratio_pct(fcf, revenue) * 2)
    balance = clamp(55 + ratio_pct(equity, assets) - ratio_pct(liabilities, assets) * 0.35)
    capital_allocation = clamp(50 + ratio_pct(fcf, assets) * 3)
    moat = moat_score(asset, profitability, cash_flow)
    management = management_score(data_quality, growth, profitability)
    raw_score = weighted_average([growth, profitability, cash_flow, balance, capital_allocation, moat, management])
    score = clamp(raw_score * (0.45 + min(0.55, data_quality / 100)))
    status = "ready" if latest else "insufficient_fundamental_evidence"
    trend = "improving" if growth >= 62 and profitability >= 55 else "deteriorating" if growth < 38 or profitability < 35 else "stable"
    return {
        "ticker": asset.ticker,
        "name": asset.name,
        "sector": asset.sector,
        "business_quality_score": round(score, 2),
        "growth_quality": round(growth, 2),
        "profitability_quality": round(profitability, 2),
        "cash_flow_quality": round(cash_flow, 2),
        "balance_sheet_quality": round(balance, 2),
        "capital_allocation_quality": round(capital_allocation, 2),
        "moat_quality": round(moat, 2),
        "management_quality": round(management, 2),
        "fundamental_alpha_score": round(clamp(score * 0.65 + growth * 0.2 + cash_flow * 0.15), 2),
        "data_quality_score": round(data_quality, 2),
        "status": status,
        "trend_label": trend,
        "evidence": {
            "period_end": latest.period_end.isoformat() if latest and latest.period_end else None,
            "provider": latest.provider if latest else None,
            "metrics_available": sorted(metrics.keys()) if isinstance(metrics, dict) else [],
            "warning": None if latest else "No stored fundamental snapshot; score is penalized and should not be treated as business-quality proof.",
        },
        "management_components": {
            "insider_alignment": None,
            "execution_consistency": round(clamp((data_quality + growth) / 2), 2),
            "earnings_delivery": None,
        },
    }


def portfolio_contribution_rows(rows: list[TradingGameTrade]) -> list[dict]:
    total_pl = sum(safe_float(row.net_pnl_eur if row.net_pnl_eur is not None else row.realized_pl) for row in rows)
    total_risk = sum(abs(safe_float(row.max_adverse_excursion if row.max_adverse_excursion is not None else row.risk_amount)) for row in rows)
    grouped: dict[str, list[TradingGameTrade]] = defaultdict(list)
    for row in rows:
        grouped[row.ticker].append(row)
    output = []
    for ticker, group in grouped.items():
        pl = sum(safe_float(row.net_pnl_eur if row.net_pnl_eur is not None else row.realized_pl) for row in group)
        risk = sum(abs(safe_float(row.max_adverse_excursion if row.max_adverse_excursion is not None else row.risk_amount)) for row in group)
        alpha = sum(safe_float(row.excess_return_vs_benchmark) for row in group if row.excess_return_vs_benchmark is not None)
        output.append(
            {
                "ticker": ticker,
                "sector": group[0].sector,
                "trades": len(group),
                "return_contribution": round_or_none(pl / total_pl * 100 if total_pl else None),
                "risk_contribution": round_or_none(risk / total_risk * 100 if total_risk else None),
                "drawdown_contribution": round_or_none(min([safe_float(row.pnl_percent) for row in group], default=0)),
                "alpha_contribution": round_or_none(alpha / max(1, len(group))),
            }
        )
    return sorted(output, key=lambda item: abs(safe_float(item.get("return_contribution"))), reverse=True)


def correlation_rows(db: Session, tickers: list[str]) -> list[dict]:
    output = []
    series = {ticker: daily_returns(db, ticker) for ticker in tickers}
    for index, ticker_a in enumerate(tickers):
        for ticker_b in tickers[index + 1 :]:
            corr = pearson(series.get(ticker_a, []), series.get(ticker_b, []))
            output.append({"asset_a": ticker_a, "asset_b": ticker_b, "correlation": round_or_none(corr), "evidence": {"points": min(len(series.get(ticker_a, [])), len(series.get(ticker_b, [])))}})
    return sorted(output, key=lambda item: abs(safe_float(item.get("correlation"))), reverse=True)[:40]


def candidate_scope_metric_rows(decisions: list[dict], key: str) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in decisions:
        grouped[str(item.get(key) or "Unknown")].append(item)
    return [{"scope": key, "entity": entity, **decision_superiority_metrics(items, [])} for entity, items in grouped.items()]


def classify_decision_superiority(score: float) -> str:
    if score <= 20:
        return "Weak"
    if score <= 40:
        return "Experimental"
    if score <= 60:
        return "Learning"
    if score <= 75:
        return "Competitive"
    if score <= 90:
        return "Strong Alpha Research"
    return "Exceptional"


def decision_superiority_explanation(score: float, classification: str, metrics: dict, warnings: list[str]) -> str:
    if metrics.get("status") == "insufficient_evidence":
        return "Insufficient evidence. BLUM does not yet have enough comparable decision snapshots to claim selection superiority."
    base = f"Decision Superiority Score {score:.1f}/100 ({classification}). Opportunity recall {pct(metrics.get('opportunity_recall'))}, precision {pct(metrics.get('opportunity_precision'))}, alpha capture {pct(metrics.get('alpha_capture_rate'))}."
    if warnings:
        base += f" Main warning: {warnings[0]}"
    return base


def selected_return(trade: TradingGameTrade) -> float:
    if trade.pnl_percent is not None:
        return safe_float(trade.pnl_percent)
    if trade.entry_price and trade.exit_price:
        return (trade.exit_price / trade.entry_price - 1) * 100
    return safe_float(trade.excess_return_vs_benchmark if trade.excess_return_vs_benchmark is not None else trade.realized_r_multiple)


def ticker_return_between(db: Session, ticker: str, start: date, end: date) -> float | None:
    asset = db.scalar(select(Asset).where(Asset.ticker == ticker))
    if not asset:
        return None
    start_row = db.scalar(select(PriceHistory).where(PriceHistory.asset_id == asset.id, PriceHistory.date >= start).order_by(PriceHistory.date).limit(1))
    end_row = db.scalar(select(PriceHistory).where(PriceHistory.asset_id == asset.id, PriceHistory.date <= end).order_by(desc(PriceHistory.date)).limit(1))
    if not start_row or not end_row or not start_row.close:
        return None
    return (safe_float(end_row.close) / safe_float(start_row.close) - 1) * 100


def dedupe_candidates(candidates: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    for item in candidates:
        ticker = item.get("ticker")
        if not ticker:
            continue
        if ticker not in best or safe_float(item.get("score")) > safe_float(best[ticker].get("score")):
            best[ticker] = item
    return list(best.values())


def weighted_average(values: list[float | None]) -> float:
    clean = [safe_float(value) for value in values if value is not None]
    return clamp(mean(clean) if clean else 0)


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{safe_float(value) * 100:.1f}%"


def count_live(rows: list[TradingGameTrade]) -> int:
    return sum(1 for row in rows if row.mode == "live_forward_paper")


def volatility_regime_for_trade(trade: TradingGameTrade) -> str:
    mae = abs(safe_float(trade.max_adverse_excursion))
    if mae >= 10:
        return "high_volatility"
    if mae <= 2:
        return "low_volatility"
    return "normal_volatility"


def metric_value(metrics: dict, key: str) -> float | None:
    raw = metrics.get(key) if isinstance(metrics, dict) else None
    if isinstance(raw, dict):
        raw = raw.get("value")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def ratio_pct(numerator: float | None, denominator: float | None) -> float:
    if numerator is None or denominator in (None, 0):
        return 0.0
    return numerator / denominator * 100


def trend_score(values: list[float | None]) -> float:
    clean = [float(value) for value in values if value not in (None, 0)]
    if len(clean) < 2:
        return 45.0
    latest, oldest = clean[0], clean[-1]
    if oldest == 0:
        return 45.0
    return clamp(50 + (latest / oldest - 1) * 100)


def moat_score(asset: Asset, profitability: float, cash_flow: float) -> float:
    text = f"{asset.category} {asset.sector} {asset.industry} {asset.description}".lower()
    boost = 0
    for token in ["platform", "ecosystem", "semiconductor", "cloud", "security", "defense", "luxury", "healthcare", "ai"]:
        if token in text:
            boost += 4
    return clamp(45 + boost + (profitability - 50) * 0.25 + (cash_flow - 50) * 0.2)


def management_score(data_quality: float, growth: float, profitability: float) -> float:
    return clamp(42 + data_quality * 0.25 + growth * 0.2 + profitability * 0.2)


def concentration_score(contributions: list[dict]) -> float:
    values = sorted([abs(safe_float(item.get("return_contribution"))) for item in contributions], reverse=True)
    if not values:
        return 100.0
    return clamp(sum(values[:3]))


def portfolio_warnings(rows: list[TradingGameTrade], concentration: float, metrics: dict) -> list[str]:
    warnings = []
    if len(rows) < 30:
        warnings.append("Portfolio evidence is still low sample.")
    if concentration >= 70:
        warnings.append("Portfolio result is concentrated in the top contributors.")
    if safe_float(metrics.get("benchmark_excess")) < 0:
        warnings.append("Portfolio is underperforming its benchmark context.")
    return warnings


def daily_returns(db: Session, ticker: str) -> list[float]:
    asset = db.scalar(select(Asset).where(Asset.ticker == ticker))
    if not asset:
        return []
    rows = db.scalars(select(PriceHistory).where(PriceHistory.asset_id == asset.id).order_by(desc(PriceHistory.date)).limit(260)).all()
    values = [safe_float(row.close) for row in reversed(rows) if row.close]
    return [(values[index] / values[index - 1] - 1) * 100 for index in range(1, len(values)) if values[index - 1]]


def pearson(a: list[float], b: list[float]) -> float | None:
    n = min(len(a), len(b))
    if n < 20:
        return None
    x, y = a[-n:], b[-n:]
    mean_x, mean_y = mean(x), mean(y)
    numerator = sum((xv - mean_x) * (yv - mean_y) for xv, yv in zip(x, y))
    den_x = sqrt(sum((xv - mean_x) ** 2 for xv in x))
    den_y = sqrt(sum((yv - mean_y) ** 2 for yv in y))
    if den_x == 0 or den_y == 0:
        return None
    return numerator / (den_x * den_y)


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if isinstance(parsed, datetime) else datetime.combine(parsed, datetime.min.time())
    except ValueError:
        return None
