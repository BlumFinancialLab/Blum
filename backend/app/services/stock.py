from __future__ import annotations

from statistics import mean

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ingestion.news_ingestor import NewsIngestor
from app.models import Asset, SignalSnapshot
from app.services.market_data import MarketDataService, market_snapshot_for_asset
from app.signals.engine import SignalEngine


settings = get_settings()


def stock_radar(db: Session, limit: int = 80) -> dict:
    stocks = db.scalars(
        select(Asset)
        .where(Asset.asset_type == "Stock", Asset.is_active.is_(True))
        .order_by(Asset.sector, Asset.ticker)
        .limit(limit)
    ).all()
    latest_signals = latest_stock_signals(db, stocks)
    rows = [stock_row(db, asset, latest_signals.get(asset.id)) for asset in stocks]
    ready_rows = [row for row in rows if row["signal"] is not None]
    ranked = sorted(ready_rows, key=lambda row: row["signal"]["blum_score"], reverse=True)
    return {
        "status": "ready" if ranked else "waiting_for_signals",
        "summary": radar_summary(rows, ranked),
        "sections": {
            "strongest_signals": ranked[:12],
            "narrative_breakouts": [row for row in ranked if row["signal"]["classification"] == "Narrative Breakout"][:12],
            "technical_breakouts": [row for row in ranked if row["signal"]["classification"] == "Technical Breakout"][:12],
            "sentiment_divergence": [row for row in ranked if row["signal"]["classification"] == "Sentiment Divergence"][:12],
            "quality_momentum": quality_momentum(ranked)[:12],
            "high_risk_momentum": high_risk_momentum(ranked)[:12],
            "quiet_accumulation": quiet_accumulation(ranked)[:12],
            "contrarian_setups": contrarian_setups(ranked)[:12],
        },
        "sector_leaders": sector_leaders(ranked),
        "rows": ranked,
        "data_gaps": [row for row in rows if row["signal"] is None],
    }


def update_stock_radar(db: Session, limit: int = 36) -> dict:
    stocks = db.scalars(
        select(Asset)
        .where(Asset.asset_type == "Stock", Asset.is_active.is_(True))
        .order_by(Asset.sector, Asset.ticker)
        .limit(limit)
    ).all()
    tickers = [asset.ticker for asset in stocks]
    market = MarketDataService().update_prices(db, tickers=tickers + [settings.default_benchmark], period=settings.historical_price_period, limit=len(tickers) + 1)
    news = NewsIngestor().update_news(db, lookback_hours=168, limit_per_feed=25, tickers=tickers)
    signals = SignalEngine().run(db, tickers=tickers, limit=len(tickers))
    return {
        "market_update": market,
        "news_update": news,
        "signal_run": signals,
        "radar": stock_radar(db, limit=limit),
    }


def latest_stock_signals(db: Session, stocks: list[Asset]) -> dict[int, SignalSnapshot]:
    ids = [asset.id for asset in stocks]
    if not ids:
        return {}
    signals = db.scalars(
        select(SignalSnapshot)
        .where(SignalSnapshot.asset_id.in_(ids))
        .order_by(desc(SignalSnapshot.created_at), desc(SignalSnapshot.blum_score))
    ).all()
    latest: dict[int, SignalSnapshot] = {}
    for signal in signals:
        latest.setdefault(signal.asset_id, signal)
    return latest


def stock_row(db: Session, asset: Asset, signal: SignalSnapshot | None) -> dict:
    snapshot = market_snapshot_for_asset(db, asset)
    if signal is None:
        return {
            "ticker": asset.ticker,
            "asset": asset_payload(asset),
            "market_snapshot": snapshot,
            "signal": None,
            "research_priority": "Insufficient Evidence",
            "radar_tags": ["Needs Signal"],
            "why_watch": "No signal snapshot exists yet. Run Stock Radar update to hydrate real prices, news and signal factors.",
        }
    technical = signal.technical_summary or {}
    narrative = signal.narrative_summary or {}
    breakdown = signal.score_breakdown or {}
    return {
        "ticker": asset.ticker,
        "asset": asset_payload(asset),
        "market_snapshot": snapshot,
        "signal": {
            "classification": signal.classification,
            "blum_score": signal.blum_score,
            "risk_level": signal.risk_level,
            "time_horizon": signal.time_horizon,
            "score_breakdown": breakdown,
            "created_at": signal.created_at,
        },
        "factor_scores": {
            "momentum": round(float(breakdown.get("momentum_score", 0)), 1),
            "trend": round(float(breakdown.get("trend_score", 0)), 1),
            "sentiment": round(float(breakdown.get("sentiment_score", 0)), 1),
            "volatility": round(float(breakdown.get("volatility_score", 0)), 1),
            "anomaly": round(float(breakdown.get("anomaly_score", 0)), 1),
            "semantic": round(float(breakdown.get("semantic_trend_score", 0)), 1),
        },
        "technical_flags": {
            "above_sma20": bool(technical.get("above_sma20")),
            "above_sma50": bool(technical.get("above_sma50")),
            "above_sma200": bool(technical.get("above_sma200")),
            "rsi": technical.get("rsi"),
            "macd_hist": technical.get("macd_hist"),
            "support": technical.get("support"),
            "resistance": technical.get("resistance"),
            "volume_spike": technical.get("volume_spike"),
            "historical_volatility": technical.get("historical_volatility"),
            "recent_drawdown": technical.get("recent_drawdown"),
        },
        "narrative_flags": {
            "news_count_7d": narrative.get("news_count_7d", 0),
            "news_count_30d": narrative.get("news_count_30d", 0),
            "sentiment_7d": narrative.get("sentiment_7d", 0),
            "sentiment_30d": narrative.get("sentiment_30d", 0),
            "narrative_intensity": narrative.get("narrative_intensity", 0),
            "semantic_trend_score": narrative.get("semantic_trend_score", 0),
            "sentiment_divergence": narrative.get("sentiment_divergence", False),
        },
        "research_priority": research_priority(signal, snapshot),
        "radar_tags": radar_tags(signal, technical, narrative),
        "why_watch": signal.explanation,
    }


def radar_summary(rows: list[dict], ranked: list[dict]) -> dict:
    scores = [float(row["signal"]["blum_score"]) for row in ranked if row.get("signal")]
    ready_prices = [row for row in rows if row["market_snapshot"].get("data_status") == "ready"]
    return {
        "stock_count": len(rows),
        "signal_count": len(ranked),
        "missing_signal_count": len(rows) - len(ranked),
        "priced_count": len(ready_prices),
        "average_score": round(mean(scores), 2) if scores else 0,
        "top_score": round(max(scores), 2) if scores else 0,
        "high_risk_count": len([row for row in ranked if row["signal"]["risk_level"] == "High"]),
        "positive_1d_count": len([row for row in rows if numeric(row["market_snapshot"].get("perf_1d")) > 0]),
    }


def quality_momentum(rows: list[dict]) -> list[dict]:
    return [
        row for row in rows
        if row["factor_scores"]["momentum"] >= 58
        and row["factor_scores"]["trend"] >= 62
        and row["signal"]["risk_level"] in {"Low", "Medium"}
    ]


def high_risk_momentum(rows: list[dict]) -> list[dict]:
    return [
        row for row in rows
        if row["factor_scores"]["momentum"] >= 58 and row["signal"]["risk_level"] == "High"
    ]


def quiet_accumulation(rows: list[dict]) -> list[dict]:
    return [
        row for row in rows
        if row["technical_flags"]["above_sma20"]
        and row["technical_flags"]["above_sma50"]
        and numeric(row["narrative_flags"]["narrative_intensity"]) < 35
        and row["factor_scores"]["trend"] >= 60
    ]


def contrarian_setups(rows: list[dict]) -> list[dict]:
    return [
        row for row in rows
        if row["signal"]["classification"] == "Contrarian Setup"
        or (numeric(row["technical_flags"]["rsi"]) < 38 and numeric(row["narrative_flags"]["sentiment_7d"]) >= 0)
    ]


def sector_leaders(rows: list[dict]) -> list[dict]:
    sectors: dict[str, list[dict]] = {}
    for row in rows:
        sectors.setdefault(row["asset"]["sector"], []).append(row)
    leaders = []
    for sector, sector_rows in sectors.items():
        scores = [float(row["signal"]["blum_score"]) for row in sector_rows]
        top = max(sector_rows, key=lambda row: row["signal"]["blum_score"])
        leaders.append(
            {
                "sector": sector,
                "asset_count": len(sector_rows),
                "average_score": round(mean(scores), 2),
                "leader": top["ticker"],
                "leader_score": top["signal"]["blum_score"],
                "leader_price": top["market_snapshot"],
            }
        )
    return sorted(leaders, key=lambda item: item["average_score"], reverse=True)


def research_priority(signal: SignalSnapshot, snapshot: dict) -> str:
    score = float(signal.blum_score)
    if snapshot.get("data_status") != "ready":
        return "Data Watch"
    if signal.risk_level == "High" and score >= 70:
        return "Risk Review"
    if score >= 78:
        return "Priority A"
    if score >= 65:
        return "Priority B"
    if score >= 54:
        return "Priority C"
    return "Monitor"


def radar_tags(signal: SignalSnapshot, technical: dict, narrative: dict) -> list[str]:
    tags = [signal.classification, signal.risk_level]
    if technical.get("above_sma20") and technical.get("above_sma50"):
        tags.append("Trend Confirmed")
    if technical.get("above_sma200"):
        tags.append("Above SMA200")
    if numeric(technical.get("rsi")) > 70:
        tags.append("RSI Elevated")
    if numeric(technical.get("rsi")) < 35:
        tags.append("RSI Depressed")
    if numeric(technical.get("volume_spike")) > 80:
        tags.append("Volume Spike")
    if numeric(narrative.get("sentiment_7d")) > 0.2:
        tags.append("Positive Sentiment")
    if numeric(narrative.get("sentiment_7d")) < -0.2:
        tags.append("Negative Sentiment")
    if numeric(narrative.get("news_count_7d")) >= 3:
        tags.append("News Active")
    if narrative.get("sentiment_divergence"):
        tags.append("Price/Sentiment Divergence")
    return list(dict.fromkeys(tags))


def asset_payload(asset: Asset) -> dict:
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


def numeric(value) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except Exception:
        return 0.0
