from __future__ import annotations

from app.scoring.explanations import build_score_explanation, opportunity_label, watch_points_from_factors
from app.scoring.normalization import avg, clamp, safe_float, scale
from app.scoring.weights import OPPORTUNITY_WEIGHTS, normalized_weights


def compute_opportunity_score(asset: dict, signal: dict | None, market_snapshot: dict, sector_score: float = 50, macro_score: float = 50) -> dict:
    breakdown = (signal or {}).get("score_breakdown") or {}
    narrative = (signal or {}).get("narrative_flags") or {}
    technical = (signal or {}).get("technical_flags") or {}
    momentum = avg(
        safe_float(breakdown.get("momentum_score")),
        scale(market_snapshot.get("perf_5d"), -8, 8),
        scale(market_snapshot.get("perf_1m"), -14, 16),
    )
    trend = avg(safe_float(breakdown.get("trend_score")), 82 if technical.get("above_sma20") else 42, 82 if technical.get("above_sma50") else 42)
    relative_strength = safe_float(breakdown.get("etf_confirmation_score"), 50)
    volume = avg(scale(technical.get("volume_spike"), 0, 180), 72 if safe_float(market_snapshot.get("volume")) > 0 else 38)
    sentiment = avg(safe_float(breakdown.get("sentiment_score")), scale(narrative.get("sentiment_7d"), -0.6, 0.6))
    news = avg(scale(narrative.get("news_count_7d"), 0, 6), scale(narrative.get("narrative_intensity"), 0, 100))
    risk = compute_risk_score(signal, technical)
    weights = normalized_weights(OPPORTUNITY_WEIGHTS)
    opportunity = (
        momentum * weights["momentum"]
        + trend * weights["trend"]
        + relative_strength * weights["relative_strength"]
        + volume * weights["volume"]
        + sentiment * weights["sentiment"]
        + news * weights["news"]
        + sector_score * weights["sector"]
        + macro_score * weights["macro"]
        + (100 - risk) * weights["risk"]
    )
    factors = {
        "opportunity_score": round(clamp(opportunity), 1),
        "trend_score": round(clamp(trend), 1),
        "momentum_score": round(clamp(momentum), 1),
        "sentiment_score": round(clamp(sentiment), 1),
        "news_score": round(clamp(news), 1),
        "risk_score": round(clamp(risk), 1),
        "relative_strength_score": round(clamp(relative_strength), 1),
        "volume_score": round(clamp(volume), 1),
        "sector_score": round(clamp(sector_score), 1),
        "macro_score": round(clamp(macro_score), 1),
    }
    ticker = asset.get("ticker", "")
    return {
        **factors,
        "status_label": opportunity_label(factors["opportunity_score"], factors["risk_score"]),
        "why_today": build_score_explanation(ticker, factors, factors["opportunity_score"]),
        "watch_points": watch_points_from_factors(factors),
        "weights": weights,
    }


def compute_risk_score(signal: dict | None, technical: dict) -> float:
    if signal and signal.get("risk_level") == "High":
        base = 78
    elif signal and signal.get("risk_level") == "Low":
        base = 35
    else:
        base = 52
    volatility = scale(technical.get("historical_volatility"), 12, 70)
    drawdown = scale(abs(safe_float(technical.get("recent_drawdown"))), 0, 30)
    overextension = scale(technical.get("rsi"), 58, 78)
    return avg(base, volatility, drawdown, overextension)

