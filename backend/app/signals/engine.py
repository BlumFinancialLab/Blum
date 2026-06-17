from __future__ import annotations

from datetime import datetime, timedelta
import pandas as pd
from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from app.ai.orchestrator import AIOrchestrator
from app.models import AccuracySnapshot, Asset, FundamentalSnapshot, NewsAssetLink, PriceHistory, SentimentAnalysis, SignalSnapshot, TechnicalIndicator
from app.services.blum_financial_model import capture_signal_reasoning
from app.services.thesis_engine import build_signal_thesis_payload
from app.signals.indicators import compute_indicators


SCORE_VERSION = "blum-thesis-score-v0.8"


class SignalEngine:
    def __init__(self, ai: AIOrchestrator | None = None):
        self.ai = ai or AIOrchestrator()

    def run(self, db: Session, tickers: list[str] | None = None, limit: int = 40) -> dict:
        query = select(Asset).where(Asset.is_active.is_(True)).order_by(Asset.ticker)
        if tickers:
            query = query.where(Asset.ticker.in_([ticker.upper() for ticker in tickers]))
        assets = db.scalars(query.limit(limit)).all()
        benchmark = db.scalar(select(Asset).where(Asset.ticker == "SPY"))
        benchmark_frame = load_prices(db, benchmark.id) if benchmark else None
        created = 0
        for asset in assets:
            frame = load_prices(db, asset.id)
            if frame.empty or len(frame) < 60:
                continue
            indicators = compute_indicators(frame, benchmark_frame)
            ts = self.ai.time_series.analyze(frame)
            narrative = self.narrative_features(db, asset)
            fundamentals = fundamental_features(db, asset)
            accuracy = accuracy_features(db, asset)
            narrative = {**narrative, "fundamentals": fundamentals, "accuracy_profile": accuracy}
            score = build_score(indicators, narrative, ts, asset, fundamentals, accuracy)
            previous = latest_signal_for_asset(db, asset.id)
            confidence = confidence_score(frame, indicators, narrative, ts, fundamentals, accuracy)
            score["confidence_score"] = confidence
            lifecycle = lifecycle_state(previous, score, confidence)
            thesis = build_signal_thesis_payload(asset, score, indicators, narrative, ts)
            narrative = {
                **narrative,
                "thesis": thesis,
                "narrative_lifecycle": thesis.get("narrative_analysis", {}),
                "conviction_score": thesis.get("conviction_score", 0),
            }
            explanation_stub = thesis.get("executive_thesis") or build_rule_explanation(asset, score, indicators, narrative, ts)
            snapshot = SignalSnapshot(
                asset_id=asset.id,
                ticker=asset.ticker,
                classification=score["classification"],
                blum_score=score["blum_score"],
                risk_level=score["risk_level"],
                time_horizon=score["time_horizon"],
                score_version=SCORE_VERSION,
                confidence_score=confidence,
                lifecycle_state=lifecycle,
                score_breakdown=score["score_breakdown"],
                technical_summary={**indicators, "time_series": ts},
                narrative_summary=narrative,
                explanation=explanation_stub,
                watch_points={"items": thesis_watch_points(thesis, indicators, narrative, score)},
            )
            db.add(snapshot)
            db.execute(delete(TechnicalIndicator).where(TechnicalIndicator.asset_id == asset.id, TechnicalIndicator.date == frame["date"].iloc[-1]))
            db.add(TechnicalIndicator(asset_id=asset.id, date=frame["date"].iloc[-1], indicators=indicators))
            db.flush()
            capture_signal_reasoning(db, snapshot, asset)
            created += 1
        db.commit()
        return {"signals_created": created, "assets_evaluated": len(assets)}

    def narrative_features(self, db: Session, asset: Asset) -> dict:
        since_30 = datetime.utcnow() - timedelta(days=30)
        since_7 = datetime.utcnow() - timedelta(days=7)
        linked_article_ids = [
            row[0]
            for row in db.execute(select(NewsAssetLink.article_id).where(NewsAssetLink.asset_id == asset.id)).all()
        ]
        if not linked_article_ids:
            return {
                "news_count_7d": 0,
                "news_count_30d": 0,
                "sentiment_7d": 0,
                "sentiment_30d": 0,
                "narrative_intensity": 0,
                "sentiment_polarization": 0,
                "semantic_trend_score": 0,
                "sentiment_divergence": False,
            }
        sentiments = db.execute(
            select(SentimentAnalysis.score, SentimentAnalysis.created_at)
            .where(SentimentAnalysis.article_id.in_(linked_article_ids))
            .order_by(SentimentAnalysis.created_at.desc())
        ).all()
        scores_7 = [float(score) for score, created in sentiments if created and created >= since_7]
        scores_30 = [float(score) for score, created in sentiments if created and created >= since_30]
        count_7 = len(scores_7)
        count_30 = len(scores_30)
        sentiment_7 = sum(scores_7) / count_7 if count_7 else 0.0
        sentiment_30 = sum(scores_30) / count_30 if count_30 else 0.0
        polarization = (max(scores_30) - min(scores_30)) if len(scores_30) > 1 else 0.0
        intensity = min(100, count_7 * 14 + count_30 * 2)
        semantic_trend = min(100, intensity * 0.55 + max(0, sentiment_7) * 45 + polarization * 8)
        return {
            "news_count_7d": count_7,
            "news_count_30d": count_30,
            "sentiment_7d": round(sentiment_7, 4),
            "sentiment_30d": round(sentiment_30, 4),
            "narrative_intensity": round(intensity, 2),
            "sentiment_polarization": round(polarization, 4),
            "semantic_trend_score": round(semantic_trend, 2),
            "sentiment_divergence": False,
        }


def load_prices(db: Session, asset_id: int) -> pd.DataFrame:
    rows = db.execute(
        select(PriceHistory.date, PriceHistory.open, PriceHistory.high, PriceHistory.low, PriceHistory.close, PriceHistory.volume)
        .where(PriceHistory.asset_id == asset_id)
        .order_by(PriceHistory.date)
    ).all()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])


def build_score(indicators: dict, narrative: dict, ts: dict, asset: Asset, fundamentals: dict | None = None, accuracy: dict | None = None) -> dict:
    fundamentals = fundamentals or {}
    accuracy = accuracy or {}
    momentum_score = avg(
        scale(indicators.get("perf_5d"), -8, 8),
        scale(indicators.get("perf_1m"), -14, 16),
        scale(indicators.get("perf_3m"), -24, 28),
        scale(indicators.get("relative_strength_vs_benchmark"), -18, 18),
    )
    trend_score = avg(
        100 if indicators.get("above_sma20") else 35,
        100 if indicators.get("above_sma50") else 35,
        95 if indicators.get("above_sma200") else 30,
        scale(indicators.get("adx") or 18, 10, 38),
        scale(indicators.get("trend_persistence"), 48, 74),
    )
    sentiment_score = avg(
        scale(narrative.get("sentiment_7d"), -0.8, 0.8),
        scale(narrative.get("sentiment_30d"), -0.7, 0.7),
        scale(narrative.get("narrative_intensity"), 0, 100),
    )
    volatility_score = avg(
        scale(indicators.get("historical_volatility"), 70, 12),
        scale(indicators.get("downside_volatility"), 55, 8),
        scale(indicators.get("max_drawdown"), -70, -8),
        scale(indicators.get("atr_percent"), 8, 1.2),
    )
    anomaly_score = avg(
        scale(abs(indicators.get("gap_anomaly", 0)), 0, 3),
        scale(abs(indicators.get("volume_spike", 0)), 0, 180),
        ts.get("anomaly_score", 0),
    )
    semantic_trend_score = narrative.get("semantic_trend_score", 0)
    etf_confirmation_score = etf_confirmation_proxy(asset, indicators)
    fundamental_score = float(fundamentals.get("fundamental_score", 45.0) or 45.0)
    historical_accuracy_score = float(accuracy.get("accuracy_score", 50.0) or 50.0)
    risk_adjustment = avg(volatility_score, scale(indicators.get("beta_vs_benchmark"), 2.1, 0.55), scale(indicators.get("recent_drawdown"), -30, 0))
    blum_score = (
        momentum_score * 0.16
        + trend_score * 0.16
        + sentiment_score * 0.13
        + volatility_score * 0.10
        + anomaly_score * 0.09
        + semantic_trend_score * 0.10
        + etf_confirmation_score * 0.07
        + fundamental_score * 0.10
        + historical_accuracy_score * 0.06
        + risk_adjustment * 0.03
    )
    classification = classify_signal(blum_score, indicators, narrative, anomaly_score)
    return {
        "blum_score": round(max(0, min(100, blum_score)), 1),
        "classification": classification,
        "risk_level": risk_level(indicators, volatility_score),
        "time_horizon": "Short/Medium term" if momentum_score > trend_score else "Medium/Long term",
        "score_breakdown": {
            "momentum_score": round(momentum_score, 1),
            "trend_score": round(trend_score, 1),
            "sentiment_score": round(sentiment_score, 1),
            "volatility_score": round(volatility_score, 1),
            "anomaly_score": round(anomaly_score, 1),
            "semantic_trend_score": round(semantic_trend_score, 1),
            "etf_confirmation_score": round(etf_confirmation_score, 1),
            "fundamental_score": round(fundamental_score, 1),
            "historical_accuracy_score": round(historical_accuracy_score, 1),
            "risk_adjustment": round(risk_adjustment, 1),
        },
    }


def classify_signal(score: float, indicators: dict, narrative: dict, anomaly_score: float) -> str:
    price_positive = indicators.get("perf_5d", 0) > 2 and indicators.get("above_sma20")
    sentiment_positive = narrative.get("sentiment_7d", 0) > 0.2 and narrative.get("news_count_7d", 0) >= 2
    if score >= 78 and price_positive and sentiment_positive:
        return "Narrative Breakout"
    if score >= 74 and indicators.get("above_sma20") and indicators.get("above_sma50") and indicators.get("macd_hist", 0) > 0:
        return "Technical Breakout"
    if indicators.get("perf_5d", 0) > 4 and narrative.get("sentiment_7d", 0) < -0.15:
        return "Sentiment Divergence"
    if anomaly_score >= 72 and score >= 62:
        return "High Risk / High Momentum"
    if score >= 82:
        return "Strong Watch"
    if score >= 65:
        return "Watch"
    if score >= 54 and indicators.get("rsi", 50) < 36 and narrative.get("sentiment_7d", 0) > 0:
        return "Contrarian Setup"
    if score < 42:
        return "Avoid / Too Risky"
    return "Neutral"


def risk_level(indicators: dict, volatility_score: float) -> str:
    if indicators.get("historical_volatility", 0) > 55 or indicators.get("beta_vs_benchmark", 1) > 1.8:
        return "High"
    if volatility_score > 62 and indicators.get("recent_drawdown", 0) > -14:
        return "Low"
    return "Medium"


def watch_points(indicators: dict, narrative: dict, score: dict) -> list[str]:
    points = [
        f"Monitor SMA20 near {indicators.get('sma20')}.",
        f"Watch support {indicators.get('support')} and resistance {indicators.get('resistance')}.",
        "Check whether ETF or sector confirmation persists.",
    ]
    if indicators.get("rsi", 50) > 70:
        points.append("RSI is elevated; require disciplined entry and trend confirmation.")
    if narrative.get("news_count_7d", 0) == 0:
        points.append("No recent linked news; signal is mostly price-driven.")
    if score.get("classification") == "Sentiment Divergence":
        points.append("Narrative and price are diverging; monitor for reversal or catch-up.")
    return points


def thesis_watch_points(thesis: dict, indicators: dict, narrative: dict, score: dict) -> list[str]:
    points = []
    points.extend(thesis.get("confirmation_conditions", [])[:2])
    points.extend(thesis.get("invalidation_conditions", [])[:2])
    points.extend(watch_points(indicators, narrative, score))
    deduped = []
    for point in points:
        if point and point not in deduped:
            deduped.append(point)
    return deduped[:8]


def build_rule_explanation(asset: Asset, score: dict, indicators: dict, narrative: dict, ts: dict) -> str:
    return (
        f"{asset.ticker} is classified as {score['classification']} with a Blum Intelligence Score of "
        f"{score['blum_score']}. The engine combines momentum, trend quality, sentiment, volatility, "
        f"semantic intensity, ETF confirmation, fundamentals, historical accuracy and anomaly pressure. Current 5D performance is "
        f"{indicators.get('perf_5d', 0):.2f}%, 1M performance is {indicators.get('perf_1m', 0):.2f}%, "
        f"7D sentiment is {narrative.get('sentiment_7d', 0):.2f}, and the time-series regime is "
        f"{ts.get('regime', 'unknown')}."
    )


def latest_signal_for_asset(db: Session, asset_id: int) -> SignalSnapshot | None:
    return db.scalar(
        select(SignalSnapshot)
        .where(SignalSnapshot.asset_id == asset_id)
        .order_by(desc(SignalSnapshot.created_at))
        .limit(1)
    )


def confidence_score(frame: pd.DataFrame, indicators: dict, narrative: dict, ts: dict, fundamentals: dict | None = None, accuracy: dict | None = None) -> float:
    fundamentals = fundamentals or {}
    accuracy = accuracy or {}
    history_depth = scale(len(frame), 60, 900)
    indicator_completeness = sum(1 for key in ["sma20", "sma50", "sma200", "rsi", "macd_hist", "atr_percent", "support", "resistance"] if indicators.get(key) is not None) / 8 * 100
    news_support = scale(narrative.get("news_count_30d", 0), 0, 12)
    sentiment_quality = scale(abs(narrative.get("sentiment_30d", 0)), 0, 0.55)
    time_series_depth = 80 if ts.get("regime") not in {"unknown", "insufficient_history"} else 35
    fundamental_quality = float(fundamentals.get("quality_score", 0.0) or 0.0)
    historical_accuracy = float(accuracy.get("accuracy_score", 50.0) or 50.0)
    return round(avg(history_depth, indicator_completeness, news_support, sentiment_quality, time_series_depth, fundamental_quality, historical_accuracy), 1)


def lifecycle_state(previous: SignalSnapshot | None, score: dict, confidence: float) -> str:
    current_score = float(score.get("blum_score", 0))
    if previous is None:
        return "new"
    previous_score = float(previous.blum_score)
    if previous_score >= 65 and current_score < 42:
        return "invalidated"
    if previous_score - current_score >= 12:
        return "faded"
    if previous.classification == score.get("classification") and current_score >= previous_score - 5 and confidence >= 50:
        return "confirmed"
    if current_score - previous_score >= 10:
        return "strengthening"
    return "active"


def etf_confirmation_proxy(asset: Asset, indicators: dict) -> float:
    base = scale(indicators.get("relative_strength_vs_benchmark"), -12, 12)
    if asset.asset_type == "ETF":
        return avg(base, scale(indicators.get("perf_1m"), -10, 14), 100 if indicators.get("above_sma50") else 35)
    return base


def fundamental_features(db: Session, asset: Asset) -> dict:
    snapshot = db.scalar(
        select(FundamentalSnapshot)
        .where(FundamentalSnapshot.asset_id == asset.id)
        .order_by(desc(FundamentalSnapshot.period_end), desc(FundamentalSnapshot.created_at))
        .limit(1)
    )
    if snapshot is None:
        return {"status": "missing", "quality_score": 0.0, "fundamental_score": 42.0, "issues": ["No SEC fundamental snapshot is stored."]}
    metrics = snapshot.metrics or {}
    revenue = metric_value(metrics, "revenue")
    net_income = metric_value(metrics, "net_income")
    assets = metric_value(metrics, "assets")
    liabilities = metric_value(metrics, "liabilities")
    operating_cash_flow = metric_value(metrics, "operating_cash_flow")
    profit_margin = net_income / revenue if revenue else None
    leverage = liabilities / assets if assets else None
    cash_conversion = operating_cash_flow / net_income if operating_cash_flow is not None and net_income and net_income > 0 else None
    score = avg(
        float(snapshot.quality_score or 0.0),
        scale(profit_margin, -0.18, 0.30) if profit_margin is not None else 45,
        scale(1 - leverage, 0.05, 0.72) if leverage is not None else 45,
        scale(cash_conversion, 0.25, 1.45) if cash_conversion is not None else 45,
    )
    return {
        "status": "ready",
        "provider": snapshot.provider,
        "period_end": snapshot.period_end.isoformat() if snapshot.period_end else None,
        "quality_score": float(snapshot.quality_score or 0.0),
        "fundamental_score": round(score, 1),
        "profit_margin": round(profit_margin, 4) if profit_margin is not None else None,
        "liabilities_to_assets": round(leverage, 4) if leverage is not None else None,
        "cash_conversion": round(cash_conversion, 4) if cash_conversion is not None else None,
        "data_policy": "SEC companyfacts metrics only. Missing values are not estimated.",
    }


def accuracy_features(db: Session, asset: Asset) -> dict:
    snapshot = db.scalar(
        select(AccuracySnapshot)
        .where(AccuracySnapshot.asset_id == asset.id, AccuracySnapshot.scope == "asset")
        .order_by(desc(AccuracySnapshot.created_at))
        .limit(1)
    )
    if snapshot is None:
        return {"status": "missing", "accuracy_score": 50.0, "confidence_label": "Unknown"}
    return {
        "status": "ready",
        "accuracy_score": float(snapshot.score or 50.0),
        "confidence_label": snapshot.confidence_label,
        "components": snapshot.components,
        "issues": snapshot.issues,
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
    }


def metric_value(metrics: dict, key: str) -> float | None:
    payload = metrics.get(key)
    if not isinstance(payload, dict):
        return None
    try:
        return float(payload.get("value"))
    except Exception:
        return None


def scale(value, low: float, high: float) -> float:
    try:
        number = float(value)
    except Exception:
        return 50.0
    if high == low:
        return 50.0
    result = (number - low) / (high - low) * 100
    return max(0.0, min(100.0, result))


def avg(*values: float) -> float:
    valid = [float(v) for v in values if v is not None]
    return sum(valid) / len(valid) if valid else 0.0
