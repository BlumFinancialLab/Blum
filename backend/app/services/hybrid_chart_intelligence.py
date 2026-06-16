from __future__ import annotations

import base64
from datetime import datetime
import hashlib
from statistics import mean

import pandas as pd
from sqlalchemy import delete, desc, func, select
from sqlalchemy.orm import Session

from app.models import (
    Asset,
    ChartAnalysis,
    ChartPatternMemory,
    NewsArticle,
    NewsAssetLink,
    SentimentAnalysis,
    TechnicalLevel,
    TechnicalSignal,
)
from app.services.chart_vision_engine import ChartVisionEngine
from app.services.financial_brain_learning import brain_asset_memory
from app.services.technical_analysis_engine import TechnicalAnalysisEngine, normalize_frame
from app.signals.engine import load_prices


DISCLAIMER = "This is technical analysis, not financial advice."


class HybridChartIntelligence:
    def __init__(self):
        self.technical = TechnicalAnalysisEngine()
        self.vision = ChartVisionEngine()

    def analyze_ticker(self, db: Session, asset: Asset, timeframe: str = "6M", period: str = "1y", include_visual: bool = True, persist: bool = True) -> dict:
        prices = load_prices(db, asset.id)
        frame = normalize_frame(prices, timeframe)
        deterministic = self.technical.analyze(frame, timeframe=timeframe)
        chart_image = generate_chart_svg_data_uri(asset.ticker, frame, deterministic)
        visual = self.vision.analyze_image(data_uri_payload_bytes(chart_image), ticker=asset.ticker, timeframe=timeframe, ohlcv_hint=compact_ohlcv_hint(deterministic)) if include_visual else disabled_visual(asset.ticker, timeframe)
        memory = safe_memory(db, asset)
        sentiment = sentiment_context(db, asset)
        similar = pattern_similarity(db, asset, deterministic, timeframe)
        hybrid = build_hybrid_report(asset, timeframe, visual, deterministic, memory, sentiment, similar)
        if persist:
            persist_chart_analysis(db, asset, timeframe, period, chart_image, visual, deterministic, hybrid)
        return {
            "ticker": asset.ticker,
            "timeframe": timeframe,
            "period": period,
            "chart_image": chart_image,
            "price_series": price_series(frame),
            "visual_analysis": visual,
            "deterministic_analysis": deterministic,
            "hybrid_analysis": hybrid,
            "confidence": hybrid["confidence_score"],
            "warnings": hybrid["warnings"],
            "disclaimer": DISCLAIMER,
        }

    def analyze_uploaded_image(
        self,
        db: Session,
        image_bytes: bytes,
        ticker: str | None = None,
        timeframe: str = "unknown",
        ohlcv_rows: list[dict] | None = None,
        persist: bool = True,
    ) -> dict:
        asset = db.scalar(select(Asset).where(Asset.ticker == ticker.upper())) if ticker else None
        frame = pd.DataFrame(ohlcv_rows or [])
        deterministic = self.technical.analyze(frame, timeframe=timeframe) if not frame.empty else {"status": "no_ohlcv_payload", "technical_summary": "No OHLCV payload was supplied; deterministic analysis unavailable."}
        visual = self.vision.analyze_image(image_bytes, ticker=ticker, timeframe=timeframe, ohlcv_hint=compact_ohlcv_hint(deterministic))
        memory = safe_memory(db, asset) if asset else {}
        sentiment = sentiment_context(db, asset) if asset else {}
        similar = pattern_similarity(db, asset, deterministic, timeframe) if asset else empty_similarity()
        hybrid = build_hybrid_report(asset, timeframe, visual, deterministic, memory, sentiment, similar)
        chart_image = f"data:image/unknown;base64,{base64.b64encode(image_bytes).decode('ascii')}"
        if persist and asset:
            persist_chart_analysis(db, asset, timeframe, timeframe, chart_image, visual, deterministic, hybrid, image_hash=hashlib.sha256(image_bytes).hexdigest())
        return {
            "ticker": ticker,
            "timeframe": timeframe,
            "visual_analysis": visual,
            "deterministic_analysis": deterministic,
            "hybrid_analysis": hybrid,
            "confidence": hybrid["confidence_score"],
            "warnings": hybrid["warnings"],
            "disclaimer": DISCLAIMER,
        }

    def latest_report(self, db: Session, asset: Asset, timeframe: str = "6M") -> dict:
        row = db.scalar(
            select(ChartAnalysis)
            .where(ChartAnalysis.ticker == asset.ticker, ChartAnalysis.timeframe == timeframe)
            .order_by(desc(ChartAnalysis.created_at))
            .limit(1)
        )
        if row:
            return serialize_chart_analysis(row)
        return self.analyze_ticker(db, asset, timeframe=timeframe, period=timeframe, include_visual=False, persist=True)

    def levels(self, db: Session, asset: Asset, timeframe: str = "6M") -> dict:
        row = db.scalar(select(TechnicalLevel).where(TechnicalLevel.ticker == asset.ticker, TechnicalLevel.timeframe == timeframe))
        if not row:
            self.analyze_ticker(db, asset, timeframe=timeframe, period=timeframe, include_visual=False, persist=True)
            row = db.scalar(select(TechnicalLevel).where(TechnicalLevel.ticker == asset.ticker, TechnicalLevel.timeframe == timeframe))
        return serialize_level(row) if row else {"ticker": asset.ticker, "timeframe": timeframe, "status": "unavailable"}

    def signals(self, db: Session, asset: Asset, timeframe: str = "6M", limit: int = 30) -> list[dict]:
        rows = db.scalars(
            select(TechnicalSignal)
            .where(TechnicalSignal.ticker == asset.ticker, TechnicalSignal.timeframe == timeframe)
            .order_by(desc(TechnicalSignal.created_at))
            .limit(limit)
        ).all()
        if not rows:
            self.analyze_ticker(db, asset, timeframe=timeframe, period=timeframe, include_visual=False, persist=True)
            rows = db.scalars(
                select(TechnicalSignal)
                .where(TechnicalSignal.ticker == asset.ticker, TechnicalSignal.timeframe == timeframe)
                .order_by(desc(TechnicalSignal.created_at))
                .limit(limit)
            ).all()
        return [serialize_signal(row) for row in rows]

    def history(self, db: Session, asset: Asset, limit: int = 30) -> list[dict]:
        rows = db.scalars(select(ChartAnalysis).where(ChartAnalysis.ticker == asset.ticker).order_by(desc(ChartAnalysis.created_at)).limit(limit)).all()
        return [serialize_chart_analysis(row, compact=True) for row in rows]


def build_hybrid_report(asset: Asset | None, timeframe: str, visual: dict, deterministic: dict, memory: dict, sentiment: dict, similar: dict) -> dict:
    bullish = []
    bearish = []
    neutral = []
    if deterministic.get("status") == "ready":
        for signal in deterministic.get("signals", []):
            target = bullish if signal.get("direction") == "bullish" else bearish if signal.get("direction") == "bearish" else neutral
            target.append(signal.get("evidence", signal.get("signal_type", "technical signal")))
        if deterministic.get("trend_direction") in {"uptrend", "uptrend_attempt"}:
            bullish.append(f"Calculated trend is {deterministic.get('trend_direction')}.")
        if deterministic.get("trend_direction") in {"downtrend", "downtrend_attempt"}:
            bearish.append(f"Calculated trend is {deterministic.get('trend_direction')}.")
    bullish += visual.get("bullish_evidence", [])[:4]
    bearish += visual.get("bearish_evidence", [])[:4]
    neutral += visual.get("neutral_evidence", [])[:4]
    if sentiment.get("average_sentiment") is not None:
        if sentiment["average_sentiment"] > 0.15:
            bullish.append("Recent linked news sentiment is constructive.")
        elif sentiment["average_sentiment"] < -0.15:
            bearish.append("Recent linked news sentiment is negative.")
        else:
            neutral.append("Recent linked news sentiment is mixed.")
    contradictions = contradiction_checks(visual, deterministic, sentiment)
    confirmations = confirmation_checks(visual, deterministic, sentiment, similar)
    confidence = hybrid_confidence(visual, deterministic, sentiment, similar, contradictions)
    levels = deterministic.get("levels", {})
    return {
        "trend_summary": deterministic.get("technical_summary") or visual.get("technical_summary") or "Technical evidence is still being collected.",
        "key_levels": {
            "support_1": first_level(levels.get("support_levels"), 0),
            "support_2": first_level(levels.get("support_levels"), 1),
            "resistance_1": first_level(levels.get("resistance_levels"), 0),
            "resistance_2": first_level(levels.get("resistance_levels"), 1),
            "breakout_level": levels.get("breakout_level"),
            "breakdown_level": levels.get("breakdown_level"),
            "invalidation_level": levels.get("invalidation_level"),
        },
        "technical_signals": deterministic.get("signals", []),
        "confirmation_signals": confirmations,
        "contradiction_signals": contradictions,
        "invalidation_level": levels.get("invalidation_level"),
        "risk_zone": risk_zone(deterministic),
        "opportunity_zone": opportunity_zone(deterministic),
        "confidence_score": confidence,
        "timeframe_relevance": timeframe_relevance(timeframe, deterministic),
        "possible_scenarios": scenarios(deterministic, sentiment, similar),
        "what_to_watch_next": watch_next(deterministic, sentiment, contradictions),
        "bullish_evidence": dedupe(bullish)[:8],
        "bearish_evidence": dedupe(bearish)[:8],
        "neutral_evidence": dedupe(neutral)[:8],
        "analyst_report": analyst_report(asset, deterministic, sentiment, similar, confidence),
        "historical_similarity": similar,
        "memory_context": {
            "blum_memory_summary": memory.get("blum_memory_summary"),
            "confidence_evolution": memory.get("confidence_evolution", [])[:5],
        },
        "evidence_policy": {
            "calculated_data": deterministic.get("evidence_policy", {}).get("calculated_data", []),
            "visual_observations": ["Qwen3-VL/InternVL visual output"] if visual.get("mode") in {"remote", "local"} else [],
            "inference": ["hybrid confidence", "scenario framing", "breakout probability", "risk/reward interpretation"],
            "hypothesis": ["historical similarity is probabilistic and not a forecast"],
        },
        "warnings": warnings(visual, deterministic),
        "disclaimer": DISCLAIMER,
    }


def persist_chart_analysis(db: Session, asset: Asset, timeframe: str, period: str, chart_image: str, visual: dict, deterministic: dict, hybrid: dict, image_hash: str | None = None) -> None:
    image_hash = image_hash or hashlib.sha256(chart_image.encode("utf-8")).hexdigest()
    analysis = ChartAnalysis(
        asset_id=asset.id,
        ticker=asset.ticker,
        timeframe=timeframe,
        period=period,
        image_hash=image_hash,
        model_used=visual.get("model_used", "deterministic_technical_analysis"),
        visual_analysis_json=visual,
        deterministic_analysis_json=deterministic,
        hybrid_analysis_json=hybrid,
        chart_image=chart_image,
        confidence=float(hybrid.get("confidence_score") or 0),
    )
    db.add(analysis)
    persist_levels(db, asset, timeframe, deterministic)
    persist_signals(db, asset, timeframe, deterministic)
    persist_pattern_memory(db, asset, timeframe, deterministic, hybrid)
    db.commit()


def persist_levels(db: Session, asset: Asset, timeframe: str, deterministic: dict) -> None:
    levels = deterministic.get("levels", {})
    row = db.scalar(select(TechnicalLevel).where(TechnicalLevel.ticker == asset.ticker, TechnicalLevel.timeframe == timeframe))
    if row is None:
        row = TechnicalLevel(asset_id=asset.id, ticker=asset.ticker, timeframe=timeframe)
        db.add(row)
    row.asset_id = asset.id
    row.support_levels_json = levels.get("support_levels", [])
    row.resistance_levels_json = levels.get("resistance_levels", [])
    row.breakout_level = levels.get("breakout_level")
    row.breakdown_level = levels.get("breakdown_level")
    row.invalidation_level = levels.get("invalidation_level")
    row.updated_at = datetime.utcnow()


def persist_signals(db: Session, asset: Asset, timeframe: str, deterministic: dict) -> None:
    db.execute(delete(TechnicalSignal).where(TechnicalSignal.ticker == asset.ticker, TechnicalSignal.timeframe == timeframe))
    invalidation = deterministic.get("levels", {}).get("invalidation_level")
    for item in deterministic.get("signals", [])[:12]:
        db.add(
            TechnicalSignal(
                asset_id=asset.id,
                ticker=asset.ticker,
                timeframe=timeframe,
                signal_type=item.get("signal_type", "technical_signal"),
                direction=item.get("direction", "neutral"),
                confidence=float(item.get("confidence") or 0),
                evidence_json=item,
                invalidation_level=invalidation,
            )
        )


def persist_pattern_memory(db: Session, asset: Asset, timeframe: str, deterministic: dict, hybrid: dict) -> None:
    pattern = primary_pattern(deterministic)
    db.add(
        ChartPatternMemory(
            asset_id=asset.id,
            ticker=asset.ticker,
            timeframe=timeframe,
            pattern_type=pattern,
            setup_embedding=pattern_embedding(deterministic, hybrid),
            outcome_1d=None,
            outcome_7d=None,
            outcome_30d=None,
            max_drawdown=None,
            success=None,
        )
    )


def sentiment_context(db: Session, asset: Asset) -> dict:
    linked_ids = [row[0] for row in db.execute(select(NewsAssetLink.article_id).where(NewsAssetLink.asset_id == asset.id)).all()]
    if not linked_ids:
        return {"article_count": 0, "average_sentiment": None, "latest_news": []}
    rows = db.execute(
        select(SentimentAnalysis.score, NewsArticle.title, NewsArticle.source, NewsArticle.published_at)
        .join(NewsArticle, NewsArticle.id == SentimentAnalysis.article_id)
        .where(SentimentAnalysis.article_id.in_(linked_ids))
        .order_by(desc(SentimentAnalysis.created_at))
        .limit(30)
    ).all()
    scores = [float(score) for score, *_ in rows if score is not None]
    return {
        "article_count": len(rows),
        "average_sentiment": round(mean(scores), 4) if scores else None,
        "latest_news": [{"title": title, "source": source, "published_at": published_at.isoformat() if published_at else None} for _, title, source, published_at in rows[:6]],
    }


def pattern_similarity(db: Session, asset: Asset, deterministic: dict, timeframe: str) -> dict:
    pattern = primary_pattern(deterministic)
    rows = db.scalars(
        select(ChartPatternMemory)
        .where(ChartPatternMemory.pattern_type == pattern, ChartPatternMemory.ticker != asset.ticker)
        .order_by(desc(ChartPatternMemory.created_at))
        .limit(80)
    ).all()
    mature = [row for row in rows if row.success is not None]
    success_rate = sum(1 for row in mature if row.success) / len(mature) if mature else None
    returns_7d = [row.outcome_7d for row in mature if row.outcome_7d is not None]
    drawdowns = [row.max_drawdown for row in mature if row.max_drawdown is not None]
    return {
        "pattern_type": pattern,
        "similar_chart_setups": len(rows),
        "mature_cases": len(mature),
        "average_forward_return_7d": round(mean(returns_7d), 3) if returns_7d else None,
        "success_rate": round(success_rate, 4) if success_rate is not None else None,
        "average_drawdown": round(mean(drawdowns), 3) if drawdowns else None,
        "reliability_score": reliability_score(len(mature), success_rate),
        "explanation": "Chart pattern memory is populated from stored Blum chart analyses and matures as future OHLCV outcomes become available.",
    }


def generate_chart_svg_data_uri(ticker: str, frame: pd.DataFrame, deterministic: dict) -> str:
    if frame.empty:
        svg = "<svg xmlns='http://www.w3.org/2000/svg' width='960' height='520'><rect width='100%' height='100%' fill='#07090d'/><text x='40' y='80' fill='#ffb000'>No price data</text></svg>"
        return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
    df = frame.tail(160).reset_index(drop=True)
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    width = 960
    height = 520
    pad_x = 54
    pad_y = 42
    min_price = float(low.min())
    max_price = float(high.max())
    scale = (height - pad_y * 2) / max(max_price - min_price, 1e-9)

    def x(index: int) -> float:
        return pad_x + index * ((width - pad_x * 2) / max(len(df) - 1, 1))

    def y(price: float) -> float:
        return height - pad_y - ((price - min_price) * scale)

    line_points = " ".join(f"{x(i):.2f},{y(float(price)):.2f}" for i, price in enumerate(close))
    level_lines = []
    levels = deterministic.get("levels", {})
    for item in (levels.get("support_levels") or [])[:2]:
        py = y(float(item["level"]))
        level_lines.append(f"<line x1='{pad_x}' x2='{width-pad_x}' y1='{py:.2f}' y2='{py:.2f}' stroke='#20e070' stroke-width='1' stroke-dasharray='6 6'/>")
    for item in (levels.get("resistance_levels") or [])[:2]:
        py = y(float(item["level"]))
        level_lines.append(f"<line x1='{pad_x}' x2='{width-pad_x}' y1='{py:.2f}' y2='{py:.2f}' stroke='#ff4d5e' stroke-width='1' stroke-dasharray='6 6'/>")
    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">
      <rect width="100%" height="100%" fill="#07090d"/>
      <g stroke="rgba(255,255,255,.08)" stroke-width="1">
        <line x1="{pad_x}" x2="{width-pad_x}" y1="{pad_y}" y2="{pad_y}"/>
        <line x1="{pad_x}" x2="{width-pad_x}" y1="{height-pad_y}" y2="{height-pad_y}"/>
        <line x1="{pad_x}" x2="{pad_x}" y1="{pad_y}" y2="{height-pad_y}"/>
        <line x1="{width-pad_x}" x2="{width-pad_x}" y1="{pad_y}" y2="{height-pad_y}"/>
      </g>
      {''.join(level_lines)}
      <polyline points="{line_points}" fill="none" stroke="#ffb000" stroke-width="2.4"/>
      <text x="{pad_x}" y="28" fill="#eef3fa" font-family="Inter, system-ui" font-size="18" font-weight="800">{ticker} Technical Chart</text>
      <text x="{width-pad_x-220}" y="28" fill="#8f9bad" font-family="Inter, system-ui" font-size="12">Generated by Blum Chart Analyst</text>
    </svg>
    """
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def data_uri_payload_bytes(data_uri: str) -> bytes:
    if "," not in data_uri:
        return data_uri.encode("utf-8")
    return base64.b64decode(data_uri.split(",", 1)[1])


def build_levels_overlay(deterministic: dict) -> dict:
    levels = deterministic.get("levels", {})
    return {
        "support": levels.get("support_levels", [])[:3],
        "resistance": levels.get("resistance_levels", [])[:3],
        "breakout_level": levels.get("breakout_level"),
        "breakdown_level": levels.get("breakdown_level"),
        "invalidation_level": levels.get("invalidation_level"),
    }


def price_series(frame: pd.DataFrame) -> list[dict]:
    if frame.empty:
        return []
    return [
        {
            "date": str(row.date),
            "open": float(row.open) if row.open is not None else None,
            "high": float(row.high) if row.high is not None else None,
            "low": float(row.low) if row.low is not None else None,
            "close": float(row.close),
            "volume": float(row.volume) if row.volume is not None else None,
        }
        for row in frame.itertuples(index=False)
    ]


def compact_ohlcv_hint(deterministic: dict) -> dict:
    return {
        "status": deterministic.get("status"),
        "trend_direction": deterministic.get("trend_direction"),
        "levels": deterministic.get("levels", {}),
        "momentum": deterministic.get("momentum", {}),
        "volatility": deterministic.get("volatility", {}),
    }


def disabled_visual(ticker: str, timeframe: str) -> dict:
    return {
        "mode": "not_requested",
        "model_used": "not_requested",
        "asset_detected": ticker,
        "timeframe_detected": timeframe,
        "confidence": 0,
        "technical_summary": "Visual interpretation was not requested for this run.",
        "bullish_evidence": [],
        "bearish_evidence": [],
        "neutral_evidence": [],
        "uncertainty_notes": ["Deterministic technical analysis only."],
    }


def safe_memory(db: Session, asset: Asset | None) -> dict:
    if not asset:
        return {}
    try:
        return brain_asset_memory(db, asset)
    except Exception:
        return {}


def first_level(levels: list | None, index: int) -> float | None:
    if not levels or len(levels) <= index:
        return None
    item = levels[index]
    return item.get("level") if isinstance(item, dict) else item


def confirmation_checks(visual: dict, deterministic: dict, sentiment: dict, similar: dict) -> list[str]:
    checks = []
    if visual.get("mode") in {"remote", "local"} and deterministic.get("status") == "ready":
        checks.append("Visual chart interpretation and OHLCV engine are both available for cross-check.")
    if deterministic.get("trend_direction") in {"uptrend", "uptrend_attempt"} and sentiment.get("average_sentiment", 0) > 0:
        checks.append("Technical trend and linked news sentiment are aligned constructively.")
    if similar.get("success_rate") is not None and similar["success_rate"] >= 0.55:
        checks.append("Historical chart pattern memory has positive follow-through in matured cases.")
    return checks or ["No high-conviction cross-domain confirmation is available yet."]


def contradiction_checks(visual: dict, deterministic: dict, sentiment: dict) -> list[str]:
    checks = []
    if deterministic.get("trend_direction") in {"uptrend", "uptrend_attempt"} and sentiment.get("average_sentiment", 0) < -0.2:
        checks.append("Price structure is constructive while linked news sentiment is negative.")
    if deterministic.get("trend_direction") in {"downtrend", "downtrend_attempt"} and sentiment.get("average_sentiment", 0) > 0.2:
        checks.append("Price structure is deteriorating while linked news sentiment is positive.")
    visual_summary = str(visual.get("technical_summary", "")).lower()
    if "bearish" in visual_summary and deterministic.get("trend_direction") in {"uptrend", "uptrend_attempt"}:
        checks.append("Vision output appears more bearish than deterministic OHLCV trend structure.")
    return checks


def hybrid_confidence(visual: dict, deterministic: dict, sentiment: dict, similar: dict, contradictions: list[str]) -> float:
    confidence = 35.0
    if deterministic.get("status") == "ready":
        confidence += 35
        confidence += min(15, float(deterministic.get("trend_strength_score") or 0) * 0.15)
    if visual.get("mode") in {"remote", "local"}:
        confidence += min(12, float(visual.get("confidence") or 0) * 0.12)
    if sentiment.get("article_count", 0) > 0:
        confidence += 5
    if similar.get("mature_cases", 0) >= 5:
        confidence += min(8, similar["mature_cases"])
    confidence -= len(contradictions) * 8
    return round(max(0, min(100, confidence)), 1)


def risk_zone(deterministic: dict) -> dict:
    rr = deterministic.get("risk_reward_estimate", {})
    return {
        "zone": rr.get("nearest_support"),
        "description": "Risk increases below nearest support or invalidation level.",
        "downside_to_support_pct": rr.get("downside_to_support_pct"),
    }


def opportunity_zone(deterministic: dict) -> dict:
    rr = deterministic.get("risk_reward_estimate", {})
    return {
        "zone": rr.get("nearest_resistance"),
        "description": "Opportunity improves if price confirms above resistance with volume expansion.",
        "upside_to_resistance_pct": rr.get("upside_to_resistance_pct"),
    }


def timeframe_relevance(timeframe: str, deterministic: dict) -> str:
    if timeframe in {"1D", "5D", "1M"}:
        return "short_term_execution_context"
    if timeframe in {"3M", "6M", "YTD"}:
        return "swing_to_position_context"
    return "strategic_trend_context"


def scenarios(deterministic: dict, sentiment: dict, similar: dict) -> list[dict]:
    levels = deterministic.get("levels", {})
    return [
        {
            "name": "Bullish confirmation",
            "condition": f"Confirmed breakout above {levels.get('breakout_level')} with relative volume expansion.",
            "impact": "Confidence rises if momentum and volume confirm the move.",
        },
        {
            "name": "Bearish invalidation",
            "condition": f"Failure below {levels.get('invalidation_level')} or breakdown level {levels.get('breakdown_level')}.",
            "impact": "Setup weakens and risk controls become more important.",
        },
        {
            "name": "Base-building continuation",
            "condition": "Price remains above support while volatility compresses and news flow stays neutral-to-positive.",
            "impact": "Setup remains on watch without requiring immediate directional conclusion.",
        },
    ]


def watch_next(deterministic: dict, sentiment: dict, contradictions: list[str]) -> list[str]:
    levels = deterministic.get("levels", {})
    watch = [
        f"Breakout level near {levels.get('breakout_level')}.",
        f"Support and invalidation near {levels.get('invalidation_level')}.",
        "Relative volume expansion on any breakout attempt.",
        "RSI/MACD confirmation or divergence resolution.",
    ]
    if sentiment.get("article_count", 0) > 0:
        watch.append("Whether news sentiment confirms or contradicts price action.")
    if contradictions:
        watch.append("Resolve cross-domain contradictions before increasing confidence.")
    return watch


def analyst_report(asset: Asset | None, deterministic: dict, sentiment: dict, similar: dict, confidence: float) -> str:
    ticker = asset.ticker if asset else "the instrument"
    levels = deterministic.get("levels", {})
    trend = deterministic.get("trend_direction", "unknown")
    momentum = deterministic.get("momentum", {}).get("state", "unknown")
    volume = deterministic.get("volume", {}).get("volume_state", "unknown")
    return (
        f"Blum detects {trend.replace('_', ' ')} on {ticker}, with {momentum.replace('_', ' ')} momentum and {volume} volume. "
        f"Resistance is near {levels.get('breakout_level')} and support is near {levels.get('invalidation_level')}. "
        f"A confirmed breakout above resistance with relative volume expansion would increase technical confidence; failure below support would invalidate the setup. "
        f"Current hybrid technical confidence is {confidence:.1f}/100. Historical chart memory found {similar.get('similar_chart_setups', 0)} similar stored setups."
    )


def warnings(visual: dict, deterministic: dict) -> list[str]:
    output = [DISCLAIMER]
    if visual.get("mode") not in {"remote", "local"}:
        output.append("Vision model unavailable, deterministic analysis active.")
    if deterministic.get("status") != "ready":
        output.append("Deterministic technical analysis is limited because stored OHLCV data is insufficient.")
    return output


def primary_pattern(deterministic: dict) -> str:
    patterns = deterministic.get("patterns", [])
    if not patterns:
        return deterministic.get("trend_direction", "unknown_pattern")
    return patterns[0].get("pattern", "unknown_pattern")


def pattern_embedding(deterministic: dict, hybrid: dict) -> dict:
    return {
        "trend": deterministic.get("trend_direction"),
        "momentum": deterministic.get("momentum", {}).get("state"),
        "volatility": deterministic.get("volatility", {}).get("regime"),
        "breakout_probability": deterministic.get("breakout_probability", {}).get("score"),
        "risk_reward": deterministic.get("risk_reward_estimate", {}).get("reward_to_risk"),
        "confidence": hybrid.get("confidence_score"),
    }


def reliability_score(mature_cases: int, success_rate: float | None) -> float:
    if not mature_cases or success_rate is None:
        return 0.0
    depth = min(35, mature_cases * 4)
    return round(depth + success_rate * 65, 1)


def empty_similarity() -> dict:
    return {
        "pattern_type": "unknown",
        "similar_chart_setups": 0,
        "mature_cases": 0,
        "average_forward_return_7d": None,
        "success_rate": None,
        "average_drawdown": None,
        "reliability_score": 0,
        "explanation": "No ticker-linked chart pattern memory is available.",
    }


def dedupe(items: list) -> list:
    seen = set()
    out = []
    for item in items:
        text = str(item)
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def serialize_chart_analysis(row: ChartAnalysis, compact: bool = False) -> dict:
    payload = {
        "id": row.id,
        "ticker": row.ticker,
        "timeframe": row.timeframe,
        "period": row.period,
        "image_hash": row.image_hash,
        "model_used": row.model_used,
        "confidence": row.confidence,
        "created_at": row.created_at.isoformat(),
        "hybrid_analysis": row.hybrid_analysis_json,
        "visual_analysis": row.visual_analysis_json,
        "deterministic_analysis": row.deterministic_analysis_json,
        "disclaimer": DISCLAIMER,
    }
    if not compact:
        payload["chart_image"] = row.chart_image
        payload["price_series"] = []
    return payload


def serialize_level(row: TechnicalLevel) -> dict:
    return {
        "ticker": row.ticker,
        "timeframe": row.timeframe,
        "support_levels": row.support_levels_json,
        "resistance_levels": row.resistance_levels_json,
        "breakout_level": row.breakout_level,
        "breakdown_level": row.breakdown_level,
        "invalidation_level": row.invalidation_level,
        "updated_at": row.updated_at.isoformat(),
    }


def serialize_signal(row: TechnicalSignal) -> dict:
    return {
        "ticker": row.ticker,
        "timeframe": row.timeframe,
        "signal_type": row.signal_type,
        "direction": row.direction,
        "confidence": row.confidence,
        "evidence": row.evidence_json,
        "invalidation_level": row.invalidation_level,
        "created_at": row.created_at.isoformat(),
    }
