from __future__ import annotations

from datetime import datetime
import re

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Asset, NewsArticle, NewsAssetLink, PriceHistory, SignalSnapshot
from app.services.live import market_sentiment
from app.services.market_data import market_snapshot_for_asset
from app.services.semantic import SemanticService
from app.services.strategic_intelligence import community_sentiment, market_narrative, opportunity_radar
from app.services.dashboard import signal_payload


DISCLAIMER = (
    "Research output only. This is not financial advice, not a recommendation, "
    "and not a guarantee of future performance."
)

MARKET_TERM_TICKERS = {
    "FTSE MIB": ["^FTSEMIB", "IMIB.MI", "ENEL.MI", "ENI.MI", "ISP.MI", "UCG.MI", "RACE.MI", "LDO.MI", "PRY.MI"],
    "FTSEMIB": ["^FTSEMIB", "IMIB.MI", "ENEL.MI", "ENI.MI", "ISP.MI", "UCG.MI", "RACE.MI", "LDO.MI", "PRY.MI"],
    "DAX": ["^GDAXI", "EXS1.DE", "SIE.DE", "SAP", "ALV.DE", "DTE.DE", "IFX.DE", "MBG.DE", "DBK.DE"],
    "GERMANY": ["^GDAXI", "EXS1.DE", "SIE.DE", "ALV.DE", "DTE.DE", "IFX.DE", "MBG.DE", "DBK.DE"],
    "GERMAN": ["^GDAXI", "EXS1.DE", "SIE.DE", "ALV.DE", "DTE.DE", "IFX.DE", "MBG.DE", "DBK.DE"],
    "ITALY": ["^FTSEMIB", "IMIB.MI", "ENEL.MI", "ENI.MI", "ISP.MI", "UCG.MI", "RACE.MI", "LDO.MI"],
    "ITALIAN": ["^FTSEMIB", "IMIB.MI", "ENEL.MI", "ENI.MI", "ISP.MI", "UCG.MI", "RACE.MI", "LDO.MI"],
    "EUROPE": ["^STOXX50E", "EXSA.DE", "^GDAXI", "^FTSEMIB", "^FCHI", "^FTSE", "SIE.DE", "ASML", "SAP", "MC.PA"],
    "EUROPEAN": ["^STOXX50E", "EXSA.DE", "^GDAXI", "^FTSEMIB", "^FCHI", "^FTSE", "SIE.DE", "ASML", "SAP", "MC.PA"],
}


def financial_chat_response(
    db: Session,
    message: str,
    tickers: list[str] | None = None,
    horizon: str = "multi-horizon",
    risk_profile: str = "balanced",
    include_semantic_search: bool = True,
) -> dict:
    assets = relevant_assets(db, message, tickers)
    opportunities = opportunity_radar(db, limit=18)
    narrative = market_narrative(db)
    community = community_sentiment(db)
    sentiment = market_sentiment(db, hours=48)
    semantic_hits = SemanticService().search(db, message, limit=8) if include_semantic_search else []
    asset_packets = [asset_context(db, asset) for asset in assets[:12]]
    candidates = rank_candidates(opportunities.get("rows", []), asset_packets)
    answer = build_answer(message, candidates, asset_packets, narrative, community, sentiment, horizon, risk_profile)
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "mode": "evidence_bound_financial_chat",
        "question": message,
        "answer": answer,
        "candidate_opportunities": candidates[:8],
        "asset_context": asset_packets,
        "market_context": {
            "narrative": narrative,
            "community_sentiment": community,
            "market_sentiment": sentiment,
        },
        "semantic_evidence": semantic_hits,
        "suggested_followups": suggested_followups(candidates, assets),
        "models_used": {
            "sentiment": "ProsusAI/finbert via stored sentiment rows",
            "embeddings": "sentence-transformers semantic search over stored news embeddings",
            "reasoning": "Blum deterministic evidence-bound analyst layer",
        },
        "governance": [
            "Distinguishes observed data from inference.",
            "Surfaces contradicting evidence and invalidation conditions.",
            "No direct buy/sell instruction and no performance guarantee.",
            "Uses only data stored or retrieved by Blum services.",
        ],
        "disclaimer": DISCLAIMER,
    }


def relevant_assets(db: Session, message: str, tickers: list[str] | None) -> list[Asset]:
    requested = {item.upper().strip() for item in tickers or [] if item.strip()}
    universe = db.scalars(select(Asset).where(Asset.is_active.is_(True))).all()
    text = f" {message.upper()} "
    requested.update(expand_market_terms(text))
    for asset in universe:
        if re.search(rf"(?<![A-Z0-9.]){re.escape(asset.ticker.upper())}(?![A-Z0-9.])", text):
            requested.add(asset.ticker.upper())
        elif asset.name and asset.name.upper() in text:
            requested.add(asset.ticker.upper())
    if requested:
        rows = db.scalars(select(Asset).where(Asset.ticker.in_(sorted(requested)))).all()
        return sorted(rows, key=lambda item: item.ticker)
    latest = db.execute(
        select(SignalSnapshot, Asset)
        .join(Asset, Asset.id == SignalSnapshot.asset_id)
        .order_by(desc(SignalSnapshot.blum_score), desc(SignalSnapshot.created_at))
        .limit(8)
    ).all()
    return [asset for _, asset in latest]


def expand_market_terms(text: str) -> set[str]:
    tickers: set[str] = set()
    for term, mapped_tickers in MARKET_TERM_TICKERS.items():
        if term in text:
            tickers.update(mapped_tickers)
    return tickers


def asset_context(db: Session, asset: Asset) -> dict:
    latest_signal = db.scalar(
        select(SignalSnapshot)
        .where(SignalSnapshot.asset_id == asset.id)
        .order_by(desc(SignalSnapshot.created_at))
        .limit(1)
    )
    price_rows = db.scalars(
        select(PriceHistory)
        .where(PriceHistory.asset_id == asset.id)
        .order_by(desc(PriceHistory.date))
        .limit(80)
    ).all()
    latest_news = related_articles(db, asset.id, limit=6)
    return {
        "ticker": asset.ticker,
        "name": asset.name,
        "asset_type": asset.asset_type,
        "sector": asset.sector,
        "industry": asset.industry,
        "country": asset.country,
        "market_snapshot": market_snapshot_for_asset(db, asset),
        "latest_signal": signal_payload(latest_signal, db) if latest_signal else None,
        "history_depth": {
            "rows": len(price_rows),
            "latest_date": price_rows[0].date.isoformat() if price_rows else None,
            "oldest_sample_date": price_rows[-1].date.isoformat() if price_rows else None,
        },
        "recent_news": latest_news,
    }


def related_articles(db: Session, asset_id: int, limit: int = 6) -> list[dict]:
    rows = db.execute(
        select(NewsArticle)
        .join(NewsAssetLink, NewsAssetLink.article_id == NewsArticle.id)
        .where(NewsAssetLink.asset_id == asset_id)
        .order_by(desc(NewsArticle.published_at), desc(NewsArticle.created_at))
        .limit(limit)
    ).scalars().all()
    return [
        {
            "id": row.id,
            "title": row.title,
            "source": row.source,
            "url": row.url,
            "published_at": row.published_at.isoformat() if row.published_at else None,
            "quality_score": row.quality_score,
            "themes": row.theme_tags.get("themes", []) if row.theme_tags else [],
        }
        for row in rows
    ]


def rank_candidates(rows: list[dict], asset_packets: list[dict]) -> list[dict]:
    by_ticker = {item["ticker"]: item for item in asset_packets}
    context_tickers = set(by_ticker)
    output = []
    for row in rows:
        ticker = row.get("ticker")
        if context_tickers and ticker not in context_tickers:
            continue
        packet = by_ticker.get(ticker, {})
        output.append(
            {
                "ticker": ticker,
                "name": row.get("name"),
                "sector": row.get("sector"),
                "asset_type": row.get("asset_type"),
                "opportunity_score": row.get("opportunity_score"),
                "risk_score": row.get("risk_score"),
                "momentum_score": row.get("momentum_score"),
                "sentiment_score": row.get("sentiment_score"),
                "news_score": row.get("news_score"),
                "classification": row.get("classification"),
                "risk_level": row.get("risk_level"),
                "why_today": row.get("why_today"),
                "price": (packet.get("market_snapshot") or {}).get("price"),
                "data_status": row.get("data_status"),
            }
        )
    if not output and asset_packets:
        for packet in asset_packets:
            signal = packet.get("latest_signal") or {}
            snapshot = packet.get("market_snapshot") or {}
            output.append(
                {
                    "ticker": packet["ticker"],
                    "name": packet["name"],
                    "sector": packet["sector"],
                    "asset_type": packet["asset_type"],
                    "opportunity_score": signal.get("blum_score"),
                    "risk_score": (signal.get("score_breakdown") or {}).get("risk_adjustment"),
                    "momentum_score": (signal.get("score_breakdown") or {}).get("momentum_score"),
                    "sentiment_score": (signal.get("score_breakdown") or {}).get("sentiment_score"),
                    "classification": signal.get("classification", "Under observation"),
                    "risk_level": signal.get("risk_level", "Unknown"),
                    "why_today": signal.get("explanation", "Asset selected from the current evidence set."),
                    "price": snapshot.get("price"),
                    "data_status": snapshot.get("data_status"),
                }
            )
    return sorted(output, key=lambda item: safe_float(item.get("opportunity_score")), reverse=True)


def build_answer(
    message: str,
    candidates: list[dict],
    asset_packets: list[dict],
    narrative: dict,
    community: dict,
    sentiment: dict,
    horizon: str,
    risk_profile: str,
) -> dict:
    top = candidates[:5]
    dominant = narrative.get("dominant_theme", {}) if isinstance(narrative, dict) else {}
    market_mood = narrative.get("market_mood", "mixed") if isinstance(narrative, dict) else "mixed"
    thesis = (
        f"Blum sees the current research question through a {market_mood} market lens. "
        f"The dominant narrative is {dominant.get('theme', 'not clearly established')} with "
        f"{dominant.get('headline_count', 0)} linked headlines. The strongest candidates are "
        f"{', '.join(item['ticker'] for item in top if item.get('ticker')) or 'not yet conclusive'}."
    )
    support = []
    contradictions = []
    for item in top:
        support.append(
            f"{item.get('ticker')}: score {item.get('opportunity_score', 'n/a')}, "
            f"momentum {item.get('momentum_score', 'n/a')}, sentiment {item.get('sentiment_score', 'n/a')}, "
            f"classification {item.get('classification', 'n/a')}."
        )
        if item.get("risk_level") in {"High", "Very High"} or safe_float(item.get("risk_score")) > 70:
            contradictions.append(f"{item.get('ticker')}: risk score/risk level is elevated and should reduce conviction.")
        if item.get("data_status") and item.get("data_status") != "ready":
            contradictions.append(f"{item.get('ticker')}: market data status is {item.get('data_status')}.")
    if not contradictions:
        contradictions.append("No severe contradiction is dominant in the retrieved evidence, but macro/news data can change quickly.")
    return {
        "executive_view": thesis,
        "opportunity_lens": "Focus on statistically interesting setups, not deterministic predictions.",
        "supporting_evidence": support[:8],
        "contradicting_evidence": contradictions[:8],
        "bull_case": scenario_text(top, "bull"),
        "base_case": scenario_text(top, "base"),
        "bear_case": scenario_text(top, "bear"),
        "risk_reward_view": risk_reward_view(top, risk_profile, horizon),
        "what_to_monitor": monitor_points(top, asset_packets, sentiment, community),
        "answer_to_user": (
            "Use the candidates as a research queue: verify price confirmation, volume confirmation, "
            "news quality, sector confirmation and invalidation levels before making any decision."
        ),
        "intellectual_honesty": "If evidence coverage is missing, stale, or contradictory, Blum lowers conviction instead of forcing a conclusion.",
    }


def scenario_text(candidates: list[dict], mode: str) -> str:
    tickers = ", ".join(item.get("ticker", "") for item in candidates[:3] if item.get("ticker")) or "the monitored set"
    if mode == "bull":
        return f"{tickers}: continuation scenario requires price momentum, sentiment and sector confirmation to remain aligned."
    if mode == "bear":
        return f"{tickers}: downside scenario is driven by failed technical confirmation, negative news acceleration or higher volatility."
    return f"{tickers}: base case is selective monitoring until the evidence stack improves or deteriorates."


def risk_reward_view(candidates: list[dict], risk_profile: str, horizon: str) -> str:
    if not candidates:
        return "No candidate has enough retrieved evidence for a ranked risk/reward view."
    high_risk = [item["ticker"] for item in candidates if safe_float(item.get("risk_score")) > 70]
    return (
        f"For a {risk_profile} profile and {horizon} horizon, prioritize high score candidates with controlled risk. "
        f"High-risk names requiring extra validation: {', '.join(high_risk[:5]) or 'none in the top evidence set'}."
    )


def monitor_points(candidates: list[dict], asset_packets: list[dict], sentiment: dict, community: dict) -> list[str]:
    points = [
        "Confirm whether news intensity is rising with source quality, not only headline count.",
        "Check if sentiment confirms price action instead of merely reacting to it.",
        "Require sector or ETF confirmation for single-name signals.",
        "Watch volatility expansion and drawdown risk after the signal.",
    ]
    if sentiment.get("article_count", 0) == 0:
        points.append("Market-wide sentiment evidence is currently thin.")
    if community.get("possible_hype_bubbles"):
        points.append("Review possible hype-bubble flags before increasing conviction.")
    for packet in asset_packets[:3]:
        snapshot = packet.get("market_snapshot", {})
        if snapshot.get("data_status") != "ready":
            points.append(f"{packet['ticker']}: wait for market data readiness before treating analysis as complete.")
    return points


def suggested_followups(candidates: list[dict], assets: list[Asset]) -> list[str]:
    tickers = [item.get("ticker") for item in candidates[:3] if item.get("ticker")]
    if tickers:
        return [
            f"Build a bull/base/bear thesis for {tickers[0]}.",
            f"Compare risk-adjusted opportunity between {' and '.join(tickers[:2])}.",
            "Which contradicting evidence would invalidate the top setup?",
            "What is the strongest European market signal today?",
        ]
    if assets:
        return [f"What changed in {assets[0].ticker} recently?", "Which sector has the cleanest evidence stack?"]
    return ["What should I monitor today?", "Where is sentiment diverging from price?"]


def safe_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
