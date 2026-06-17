from __future__ import annotations

from datetime import datetime
from statistics import mean

import pandas as pd
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Asset, IntelligenceReport, PortfolioScenario, SignalSnapshot, WatchlistItem
from app.scoring.factor_engine import compute_opportunity_score
from app.services.accuracy import asset_accuracy_profile
from app.services.etf import list_etf_trends
from app.services.financial_brain_learning import active_model_weights
from app.services.live import live_news, market_sentiment
from app.services.macro import macro_overview
from app.services.market_data import market_snapshot_for_asset
from app.services.stock import stock_radar
from app.services.thesis_engine import build_asset_thesis, enrich_theme_lifecycle
from app.signals.engine import load_prices


DISCLAIMER = (
    "Educational research case study only. This is not financial advice, not a recommendation, "
    "and not an operational trading signal."
)


def executive_dashboard(db: Session) -> dict:
    opportunities = opportunity_radar(db, limit=18)
    narrative = market_narrative(db)
    community = community_sentiment(db)
    watchlist = list_watchlist(db, suggested_payload=opportunities)
    portfolio = portfolio_scenario(db, persist=False, radar_payload=opportunities)
    latest_reports = latest_intelligence_reports(db, limit=6)
    latest_backtests = latest_backtest_summaries(db, limit=6)
    risk_scores = [item["risk_score"] for item in opportunities["rows"]]
    return {
        "title": "AI Market Intelligence Officer",
        "generated_at": datetime.utcnow().isoformat(),
        "data_mode": opportunities["data_mode"],
        "market_mood": narrative["market_mood"],
        "dominant_narrative": narrative["dominant_theme"],
        "risk_level": aggregate_risk_label(mean(risk_scores) if risk_scores else 50),
        "top_opportunities_today": opportunities["rows"][:8],
        "sector_rotation": opportunities["sector_rotation"],
        "watchlist_alerts": watchlist["alerts"][:8],
        "best_ai_reports": latest_reports,
        "last_backtests": latest_backtests,
        "narrative": narrative,
        "community_sentiment": community,
        "portfolio_scenario": portfolio,
        "disclaimer": DISCLAIMER,
    }


def opportunity_radar(db: Session, limit: int = 30) -> dict:
    stocks = stock_radar(db, limit=max(limit, 40))
    etfs = list_etf_trends(db, limit=20)
    macro = macro_overview(db)
    macro_score = macro_context_score(macro)
    sector_scores = sector_score_map(stocks.get("sector_leaders", []))
    active_weights = active_model_weights(db)
    rows = []
    for row in stocks.get("rows", []):
        signal = row.get("signal")
        asset = row.get("asset") or {}
        sector_score = sector_scores.get(asset.get("sector"), 50)
        factors = compute_opportunity_score(asset, {**(signal or {}), **row}, row.get("market_snapshot") or {}, sector_score=sector_score, macro_score=macro_score, weights_override=active_weights)
        rows.append(opportunity_row(len(rows) + 1, row, factors, "equity"))
    for item in etfs:
        signal_like = {
            "score_breakdown": {
                "momentum_score": item.get("momentum_score", 0),
                "trend_score": item.get("confirmation_score", 0),
                "sentiment_score": item.get("thematic_score", 0),
                "etf_confirmation_score": item.get("confirmation_score", 0),
            },
            "risk_level": item.get("details", {}).get("risk_level", "Medium"),
            "technical_flags": {},
            "narrative_flags": {},
        }
        factors = compute_opportunity_score(item.get("asset") or {}, signal_like, item.get("market_snapshot") or {}, sector_score=item.get("confirmation_score", 50), macro_score=macro_score, weights_override=active_weights)
        rows.append(opportunity_row(len(rows) + 1, {"ticker": item["ticker"], "asset": item.get("asset"), "market_snapshot": item.get("market_snapshot"), "signal": signal_like, "why_watch": "ETF rotation proxy with thematic and momentum confirmation."}, factors, "etf"))
    rows = sorted(rows, key=lambda item: item["opportunity_score"], reverse=True)
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return {
        "status": "ready" if rows else "waiting_for_signals",
        "data_mode": "real_public_data" if rows else "insufficient_real_data",
        "rows": rows[:limit],
        "sector_rotation": sector_rotation(rows),
        "methodology": {
            "weights": rows[0]["weights"] if rows else {},
            "language_policy": "Research triage only: monitor, observe, setup, risk review. No buy/sell wording.",
            "factors": ["price momentum", "relative volume", "relative strength", "volatility", "sector trend", "news impact", "sentiment", "macro context", "drawdown risk"],
        },
        "disclaimer": DISCLAIMER,
    }


def opportunity_row(rank: int, row: dict, factors: dict, module: str) -> dict:
    asset = row.get("asset") or {}
    snapshot = row.get("market_snapshot") or {}
    signal = row.get("signal") or {}
    technical = row.get("technical_flags") or {}
    return {
        "rank": rank,
        "module": module,
        "ticker": row.get("ticker") or asset.get("ticker"),
        "name": asset.get("name", "Unknown asset"),
        "sector": asset.get("sector", "Unknown"),
        "asset_type": asset.get("asset_type", module),
        "last_price": snapshot.get("price"),
        "currency": snapshot.get("currency"),
        "change_percent": snapshot.get("perf_1d"),
        "volume_relative": round((float(technical.get("volume_spike") or 0) / 100) + 1, 2),
        "opportunity_score": factors["opportunity_score"],
        "trend_score": factors["trend_score"],
        "momentum_score": factors["momentum_score"],
        "sentiment_score": factors["sentiment_score"],
        "news_score": factors["news_score"],
        "risk_score": factors["risk_score"],
        "status_label": factors["status_label"],
        "why_today": factors["why_today"],
        "watch_points": factors["watch_points"],
        "classification": signal.get("classification", "Research Watch"),
        "risk_level": signal.get("risk_level", "Medium"),
        "weights": factors["weights"],
        "data_status": snapshot.get("data_status", "unknown"),
    }


def market_narrative(db: Session) -> dict:
    sentiment = market_sentiment(db, hours=48)
    macro = macro_overview(db)
    stocks = stock_radar(db, limit=80)
    sectors = stocks.get("sector_leaders", [])
    themes = sentiment.get("themes", [])
    beneficiaries = [item["sector"] for item in sectors[:5]]
    linked_assets = [row["ticker"] for row in stocks.get("rows", [])[:10]]
    enriched_themes = [
        enrich_theme_lifecycle(theme, linked_assets=linked_assets, sectors=beneficiaries)
        for theme in themes
    ]
    dominant = enriched_themes[0] if enriched_themes else enrich_theme_lifecycle(
        {"theme": "Market Structure", "headline_count": 0, "avg_sentiment": 0},
        linked_assets=linked_assets,
        sectors=beneficiaries,
    )
    contrary = [
        row["ticker"]
        for row in stocks.get("rows", [])
        if row.get("signal", {}).get("classification") == "Sentiment Divergence"
    ][:8]
    risk_labels = macro.get("regime", {}).get("labels", [])
    summary = (
        f"The dominant market narrative is {dominant['theme']} with {dominant['headline_count']} linked headlines. "
        f"Sector leadership is concentrated in {', '.join(beneficiaries[:3]) or 'not enough confirmed sectors'}."
    )
    return {
        "dominant_theme": dominant,
        "emerging_subthemes": enriched_themes[1:7],
        "beneficiary_sectors": beneficiaries,
        "linked_assets": linked_assets,
        "macro_risks": risk_labels,
        "contrary_signals": contrary,
        "market_mood": mood_label(sentiment.get("average_sentiment", 0), risk_labels),
        "operating_summary": summary,
        "synthesis": build_narrative_synthesis(dominant, beneficiaries, risk_labels, contrary),
        "narrative_lifecycle_map": enriched_themes[:10],
        "data_mode": "real_public_data" if sentiment.get("article_count", 0) else "limited_news_evidence",
        "disclaimer": DISCLAIMER,
    }


def asset_intelligence_report(db: Session, asset: Asset, persist: bool = True) -> dict:
    signal = db.scalar(select(SignalSnapshot).where(SignalSnapshot.asset_id == asset.id).order_by(desc(SignalSnapshot.created_at)).limit(1))
    snapshot = market_snapshot_for_asset(db, asset)
    news = linked_news_for_asset(db, asset, limit=8)
    accuracy = asset_accuracy_profile(db, asset, persist=False)
    backtest = similar_cases_backtest(db, asset)
    technical = (signal.technical_summary or {}) if signal else {}
    narrative = (signal.narrative_summary or {}) if signal else {}
    signal_dict = signal_report_payload(signal, asset) if signal else {
        "classification": "Insufficient Evidence",
        "blum_score": 0,
        "risk_level": "Not Rated",
        "time_horizon": "Not Rated",
        "score_breakdown": {},
        "confidence_score": accuracy.get("blum_confidence_score", 0),
        "asset": asset_dict(asset),
    }
    thesis = build_asset_thesis(
        asset=asset,
        signal=signal_dict,
        technical=technical,
        narrative=narrative,
        related_news=news,
        market_context={},
        historical_similarity=backtest,
        accuracy=accuracy,
    )
    report = {
        "ticker": asset.ticker,
        "title": f"{asset.ticker} Asset Intelligence Report",
        "generated_at": datetime.utcnow().isoformat(),
        "data_mode": "real_public_data" if signal else "limited_real_data",
        "overview": asset.description,
        "why_in_radar": thesis["executive_thesis"],
        "thesis": thesis,
        "executive_thesis": thesis["executive_thesis"],
        "supporting_evidence": thesis["supporting_evidence"],
        "contradicting_evidence": thesis["contradicting_evidence"],
        "market_context": thesis["market_context"],
        "historical_similarity": thesis["historical_similarity"],
        "narrative_analysis": thesis["narrative_analysis"],
        "what_the_market_may_be_missing": thesis["what_the_market_may_be_missing"],
        "invalidation_conditions": thesis["invalidation_conditions"],
        "conviction": thesis["conviction"],
        "final_blum_view": thesis["final_blum_view"],
        "technical_snapshot": technical,
        "sentiment_snapshot": narrative,
        "recent_news": news,
        "risk_review": risk_review(signal, accuracy),
        "bullish_scenario": bullish_scenario(asset, signal, technical, narrative),
        "bearish_scenario": bearish_scenario(asset, signal, technical, narrative),
        "technical_levels": {
            "support": technical.get("support"),
            "resistance": technical.get("resistance"),
            "sma20": technical.get("sma20"),
            "sma50": technical.get("sma50"),
            "sma200": technical.get("sma200"),
        },
        "similar_signal_history": backtest,
        "ai_conclusion": thesis["final_blum_view"],
        "disclaimer": DISCLAIMER,
    }
    if persist:
        db.add(
            IntelligenceReport(
                asset_id=asset.id,
                ticker=asset.ticker,
                report_type="asset_intelligence",
                title=report["title"],
                summary=report["ai_conclusion"],
                structured_output=report,
                data_mode=report["data_mode"],
            )
        )
        db.commit()
    return report


def similar_cases_backtest(db: Session, asset: Asset) -> dict:
    prices = load_prices(db, asset.id)
    if prices.empty or len(prices) < 260:
        return demonstration_backtest(asset.ticker, "Insufficient stored price history for statistically meaningful similar-case testing.")
    prices = prices.sort_values("date").reset_index(drop=True)
    close = prices["close"].astype(float)
    returns_20 = close.pct_change(20)
    volume = prices["volume"].fillna(0).astype(float)
    volume_ratio = volume / volume.rolling(50).mean()
    candidates = (returns_20 > 0.05) & (volume_ratio > 1.2)
    rows = []
    for idx in range(80, len(prices) - 21):
        if not bool(candidates.iloc[idx]):
            continue
        entry = close.iloc[idx]
        forward = close.iloc[idx + 1 : idx + 22]
        rows.append(
            {
                "date": str(prices["date"].iloc[idx]),
                "forward_return_5d": pct(entry, close.iloc[idx + 5]),
                "forward_return_10d": pct(entry, close.iloc[idx + 10]),
                "forward_return_20d": pct(entry, close.iloc[idx + 20]),
                "max_drawdown": pct(entry, forward.min()),
                "best_case": pct(entry, forward.max()),
            }
        )
    if len(rows) < 8:
        return demonstration_backtest(asset.ticker, "Fewer than eight real similar cases were found; demo statistics are shown separately.")
    frame = pd.DataFrame(rows)
    return {
        "data_mode": "real_historical_cases",
        "case_count": int(len(frame)),
        "avg_forward_return_5d": round(float(frame["forward_return_5d"].mean()), 3),
        "avg_forward_return_10d": round(float(frame["forward_return_10d"].mean()), 3),
        "avg_forward_return_20d": round(float(frame["forward_return_20d"].mean()), 3),
        "positive_outcome_probability_20d": round(float((frame["forward_return_20d"] > 0).mean()), 4),
        "average_drawdown": round(float(frame["max_drawdown"].mean()), 3),
        "best_case": round(float(frame["best_case"].max()), 3),
        "worst_case": round(float(frame["max_drawdown"].min()), 3),
        "statistical_reliability": reliability_label(len(frame)),
        "method": "Similar case proxy: 20D momentum above 5% with volume ratio above 1.2x.",
        "disclaimer": DISCLAIMER,
    }


def demonstration_backtest(ticker: str, reason: str) -> dict:
    return {
        "data_mode": "demonstration_mode",
        "case_count": 18,
        "avg_forward_return_5d": 0.8,
        "avg_forward_return_10d": 1.6,
        "avg_forward_return_20d": 2.7,
        "positive_outcome_probability_20d": 0.58,
        "average_drawdown": -3.4,
        "best_case": 9.2,
        "worst_case": -8.1,
        "statistical_reliability": "Demonstration only",
        "reason": reason,
        "method": f"{ticker} demo fallback. Not used as production evidence.",
        "disclaimer": DISCLAIMER,
    }


def list_watchlist(db: Session, suggested_payload: dict | None = None) -> dict:
    rows = db.scalars(select(WatchlistItem).order_by(desc(WatchlistItem.updated_at), desc(WatchlistItem.created_at)).limit(80)).all()
    if not rows:
        seed = (suggested_payload or opportunity_radar(db, limit=8))["rows"][:5]
        return {
            "status": "empty_seeded_view",
            "items": [],
            "suggested_items": seed,
            "alerts": [{"ticker": item["ticker"], "message": f"{item['ticker']} is a suggested monitor candidate: {item['status_label']}."} for item in seed],
            "disclaimer": DISCLAIMER,
        }
    items = []
    alerts = []
    for item in rows:
        asset = item.asset or db.scalar(select(Asset).where(Asset.ticker == item.ticker))
        snapshot = market_snapshot_for_asset(db, asset) if asset else {}
        signal = db.scalar(select(SignalSnapshot).where(SignalSnapshot.ticker == item.ticker).order_by(desc(SignalSnapshot.created_at)).limit(1))
        current_score = float(signal.blum_score) if signal else item.last_score
        payload = {
            "ticker": item.ticker,
            "name": asset.name if asset else item.ticker,
            "sector": asset.sector if asset else "Unknown",
            "status": item.status,
            "thesis": item.thesis,
            "last_score": item.last_score,
            "current_score": current_score,
            "market_snapshot": snapshot,
            "alert_rules": item.alert_rules,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        items.append(payload)
        if current_score and item.last_score and current_score - item.last_score >= 8:
            alerts.append({"ticker": item.ticker, "message": "Score acceleration versus watchlist baseline.", "severity": "Medium"})
        if snapshot.get("perf_1d") and abs(float(snapshot["perf_1d"])) >= 3:
            alerts.append({"ticker": item.ticker, "message": f"1D move is {snapshot['perf_1d']:.2f}%.", "severity": "Low"})
    return {"status": "ready", "items": items, "alerts": alerts, "disclaimer": DISCLAIMER}


def add_watchlist_item(db: Session, asset: Asset, thesis: str = "") -> dict:
    signal = db.scalar(select(SignalSnapshot).where(SignalSnapshot.asset_id == asset.id).order_by(desc(SignalSnapshot.created_at)).limit(1))
    item = WatchlistItem(
        asset_id=asset.id,
        ticker=asset.ticker,
        thesis=thesis or f"Monitor {asset.ticker} for score, trend and narrative changes.",
        last_score=float(signal.blum_score) if signal else None,
        alert_rules={"score_change": 8, "one_day_move": 3, "risk_language": "monitor only"},
        metadata_payload={"source": "manual_or_ui_add", "disclaimer": DISCLAIMER},
    )
    try:
        with db.begin_nested():
            db.add(item)
            db.flush()
    except IntegrityError:
        existing = db.scalar(select(WatchlistItem).where(WatchlistItem.ticker == asset.ticker, WatchlistItem.watchlist_name == "Strategic Watchlist"))
        if existing:
            existing.status = "active"
            existing.thesis = thesis or existing.thesis
            existing.updated_at = datetime.utcnow()
    db.commit()
    return list_watchlist(db)


def portfolio_scenario(db: Session, risk_profile: str = "balanced", persist: bool = True, radar_payload: dict | None = None) -> dict:
    radar = radar_payload or opportunity_radar(db, limit=30)
    rows = radar["rows"]
    sectors: dict[str, list[dict]] = {}
    for row in rows:
        sectors.setdefault(row["sector"], []).append(row)
    ranked = sorted(
        [{"sector": sector, "score": mean([item["opportunity_score"] for item in items]), "leaders": [item["ticker"] for item in items[:3]]} for sector, items in sectors.items()],
        key=lambda item: item["score"],
        reverse=True,
    )
    allocation = scenario_allocation(ranked, risk_profile)
    scenario = {
        "scenario_name": f"AI Market Intelligence Scenario - {risk_profile.title()}",
        "risk_profile": risk_profile,
        "time_horizon": "Research horizon: 20D to 90D. Not a portfolio recommendation.",
        "allocation": allocation,
        "rationale": [f"{item['bucket']} receives {item['weight']}% because {item['rationale']}" for item in allocation],
        "monitor": ["market breadth", "macro stress labels", "ETF confirmation", "news sentiment persistence", "drawdown behavior"],
        "defensive_alternative": defensive_allocation(),
        "data_mode": radar["data_mode"],
        "disclaimer": DISCLAIMER,
    }
    if persist:
        db.add(
            PortfolioScenario(
                scenario_name=scenario["scenario_name"],
                risk_profile=risk_profile,
                allocation={"items": allocation},
                rationale={"items": scenario["rationale"], "monitor": scenario["monitor"]},
                disclaimer=DISCLAIMER,
                data_mode=scenario["data_mode"],
            )
        )
        db.commit()
    return scenario


def community_sentiment(db: Session) -> dict:
    sentiment = market_sentiment(db, hours=48)
    news = live_news(db, limit=120)
    asset_counts: dict[str, int] = {}
    hype = []
    for article in news:
        for asset in article.get("linked_assets", []):
            asset_counts[asset["ticker"]] = asset_counts.get(asset["ticker"], 0) + 1
    for ticker, count in sorted(asset_counts.items(), key=lambda item: item[1], reverse=True)[:12]:
        hype.append({"ticker": ticker, "discussion_count": count, "hype_bubble_risk": "Review" if count >= 5 else "Low"})
    return {
        "data_mode": "real_public_news_sentiment",
        "themes_rising": sentiment.get("themes", [])[:6],
        "themes_falling": sorted(sentiment.get("themes", []), key=lambda item: item.get("avg_sentiment", 0))[:6],
        "most_discussed_assets": hype,
        "rank_change_policy": "Rank change requires persisted historical community snapshots; current build reports current rank only.",
        "average_sentiment": sentiment.get("average_sentiment", 0),
        "possible_hype_bubbles": [item for item in hype if item["hype_bubble_risk"] == "Review"],
        "disclaimer": DISCLAIMER,
    }


def latest_intelligence_reports(db: Session, limit: int = 6) -> list[dict]:
    rows = db.scalars(select(IntelligenceReport).order_by(desc(IntelligenceReport.created_at)).limit(limit)).all()
    return [
        {
            "ticker": row.ticker,
            "title": row.title,
            "summary": row.summary,
            "report_type": row.report_type,
            "data_mode": row.data_mode,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


def latest_backtest_summaries(db: Session, limit: int = 6) -> list[dict]:
    from app.models import BacktestResult

    rows = db.scalars(select(BacktestResult).order_by(desc(BacktestResult.created_at)).limit(limit)).all()
    return [
        {
            "run_name": row.run_name,
            "benchmark": row.benchmark,
            "metrics": row.metrics,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


def sector_score_map(leaders: list[dict]) -> dict[str, float]:
    return {item["sector"]: float(item.get("average_score", 50)) for item in leaders}


def sector_rotation(rows: list[dict]) -> list[dict]:
    sectors: dict[str, list[dict]] = {}
    for row in rows:
        sectors.setdefault(row["sector"], []).append(row)
    output = []
    for sector, items in sectors.items():
        output.append(
            {
                "sector": sector,
                "average_opportunity": round(mean([item["opportunity_score"] for item in items]), 1),
                "average_risk": round(mean([item["risk_score"] for item in items]), 1),
                "leaders": [item["ticker"] for item in sorted(items, key=lambda value: value["opportunity_score"], reverse=True)[:4]],
            }
        )
    return sorted(output, key=lambda item: item["average_opportunity"], reverse=True)[:10]


def macro_context_score(macro: dict) -> float:
    labels = macro.get("regime", {}).get("labels", [])
    base = float(macro.get("coverage_score", 50))
    if "elevated_volatility" in labels:
        base -= 10
    if "inverted_curve" in labels:
        base -= 5
    return max(25, min(85, base))


def mood_label(sentiment: float, risk_labels: list[str]) -> str:
    if "elevated_volatility" in risk_labels:
        return "Risk-aware"
    if sentiment >= 0.18:
        return "Constructive"
    if sentiment <= -0.18:
        return "Defensive"
    return "Balanced"


def aggregate_risk_label(score: float) -> str:
    if score >= 70:
        return "Elevated"
    if score >= 52:
        return "Balanced"
    return "Contained"


def build_narrative_synthesis(dominant: dict, sectors: list[str], risks: list[str], contrary: list[str]) -> str:
    risk_text = ", ".join(risks) if risks else "no dominant macro stress label"
    sector_text = ", ".join(sectors[:4]) if sectors else "sector evidence is still forming"
    contrary_text = ", ".join(contrary[:5]) if contrary else "no major contrary signal cluster"
    return (
        f"The market narrative is centered on {dominant.get('theme')} with beneficiary sectors around {sector_text}. "
        f"Macro risk context shows {risk_text}. Contrary checks: {contrary_text}."
    )


def risk_review(signal: SignalSnapshot | None, accuracy: dict) -> list[str]:
    risks = []
    if signal and signal.risk_level == "High":
        risks.append("Signal is high risk; monitor volatility and drawdown before acting on the thesis.")
    if accuracy.get("blum_confidence_score", 0) < 55:
        risks.append("Evidence confidence is limited; data quality must improve before stronger interpretation.")
    if signal and (signal.technical_summary or {}).get("rsi", 50) > 70:
        risks.append("RSI is elevated and can increase reversal risk.")
    return risks or ["No single dominant risk flag, but the setup still requires continuous monitoring."]


def bullish_scenario(asset: Asset, signal: SignalSnapshot | None, technical: dict, narrative: dict) -> str:
    if not signal:
        return f"{asset.ticker} needs a confirmed signal snapshot before a constructive scenario can be framed."
    return (
        f"{asset.ticker} remains constructive if price holds above the moving-average support zone, "
        f"news intensity persists and sector/ETF confirmation does not fade."
    )


def bearish_scenario(asset: Asset, signal: SignalSnapshot | None, technical: dict, narrative: dict) -> str:
    if not signal:
        return f"{asset.ticker} remains a data-watch item until price and narrative evidence improves."
    return (
        f"{asset.ticker} weakens if it loses support near {technical.get('support')}, sentiment turns negative, "
        "or volume confirms distribution rather than accumulation."
    )


def ai_conclusion(asset: Asset, signal: SignalSnapshot | None, accuracy: dict, backtest: dict) -> str:
    if not signal:
        return f"{asset.ticker} is not ready for a full strategic read. Monitor data hydration, news linkage and signal creation."
    return (
        f"{asset.ticker} is a {signal.classification} setup to monitor, not a recommendation. "
        f"Blum score is {signal.blum_score:.1f}, evidence confidence is {accuracy.get('blum_confidence_score', 0):.1f}, "
        f"and similar-case testing is {backtest.get('data_mode')}."
    )


def asset_dict(asset: Asset) -> dict:
    return {
        "ticker": asset.ticker,
        "name": asset.name,
        "category": asset.category,
        "sector": asset.sector,
        "industry": asset.industry,
        "country": asset.country,
        "asset_type": asset.asset_type,
        "currency": asset.currency,
        "exchange": asset.exchange,
        "description": asset.description,
    }


def signal_report_payload(signal: SignalSnapshot, asset: Asset) -> dict:
    return {
        "ticker": signal.ticker,
        "classification": signal.classification,
        "blum_score": signal.blum_score,
        "risk_level": signal.risk_level,
        "time_horizon": signal.time_horizon,
        "score_version": signal.score_version,
        "confidence_score": signal.confidence_score,
        "lifecycle_state": signal.lifecycle_state,
        "score_breakdown": signal.score_breakdown,
        "explanation": signal.explanation,
        "watch_points": signal.watch_points,
        "created_at": signal.created_at.isoformat() if signal.created_at else None,
        "asset": asset_dict(asset),
    }


def linked_news_for_asset(db: Session, asset: Asset, limit: int) -> list[dict]:
    from app.models import NewsArticle, NewsAssetLink

    rows = db.execute(
        select(NewsArticle, NewsAssetLink)
        .join(NewsAssetLink, NewsAssetLink.article_id == NewsArticle.id)
        .where(NewsAssetLink.asset_id == asset.id)
        .order_by(desc(NewsArticle.published_at), desc(NewsArticle.created_at))
        .limit(limit)
    ).all()
    return [
        {
            "title": article.title,
            "source": article.source,
            "published_at": article.published_at.isoformat() if article.published_at else None,
            "url": article.url,
            "quality_score": article.quality_score,
            "theme_tags": article.theme_tags,
            "relevance_score": link.relevance_score,
        }
        for article, link in rows
    ]


def scenario_allocation(ranked_sectors: list[dict], risk_profile: str) -> list[dict]:
    if not ranked_sectors:
        return defensive_allocation()
    leaders = ranked_sectors[:4]
    cash = 20 if risk_profile == "balanced" else 30 if risk_profile == "defensive" else 12
    remaining = 100 - cash
    weights = [0.38, 0.27, 0.20, 0.15]
    allocation = []
    for sector, weight in zip(leaders, weights):
        allocation.append(
            {
                "bucket": sector["sector"],
                "weight": round(remaining * weight),
                "leaders": sector["leaders"],
                "rationale": f"average opportunity score is {sector['score']:.1f} with leaders {', '.join(sector['leaders'][:3])}",
            }
        )
    used = sum(item["weight"] for item in allocation)
    allocation.append({"bucket": "Cash / dry powder", "weight": max(0, 100 - used), "leaders": [], "rationale": "keeps scenario non-operational and risk-aware"})
    return allocation


def defensive_allocation() -> list[dict]:
    return [
        {"bucket": "Broad market ETF", "weight": 30, "leaders": ["SPY"], "rationale": "broad exposure proxy"},
        {"bucket": "Quality / Healthcare", "weight": 20, "leaders": ["XLV"], "rationale": "defensive sector proxy"},
        {"bucket": "Treasury / duration watch", "weight": 20, "leaders": ["TLT"], "rationale": "macro hedge proxy"},
        {"bucket": "Gold / diversifier", "weight": 10, "leaders": ["GLD"], "rationale": "risk diversifier proxy"},
        {"bucket": "Cash / dry powder", "weight": 20, "leaders": [], "rationale": "scenario reserve"},
    ]


def reliability_label(case_count: int) -> str:
    if case_count >= 60:
        return "High sample depth"
    if case_count >= 25:
        return "Moderate sample depth"
    return "Low sample depth"


def pct(entry: float, exit_value: float) -> float:
    if entry == 0:
        return 0.0
    return round((float(exit_value) / float(entry) - 1) * 100, 4)
