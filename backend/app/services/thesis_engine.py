from __future__ import annotations

from statistics import mean
from typing import Any

from app.models import Asset


DISCLAIMER = (
    "Educational research case study only. This thesis is not financial advice, "
    "not a recommendation and not an operational trading signal."
)

REGIME_LABELS = (
    "Bull Expansion",
    "Bull Maturity",
    "Bull Exhaustion",
    "Sideways",
    "Risk-Off",
    "Panic",
    "Recovery",
    "Rotation",
)


def build_asset_thesis(
    asset: Asset | dict,
    signal: dict | None = None,
    technical: dict | None = None,
    narrative: dict | None = None,
    related_news: list[dict] | None = None,
    market_context: dict | None = None,
    historical_similarity: dict | None = None,
    accuracy: dict | None = None,
) -> dict:
    """Build an evidence-bound financial thesis from existing Blum evidence.

    The function deliberately does not fetch new data or produce recommendations.
    It restructures existing signal, technical, narrative, market and memory
    evidence into an analyst-style thesis with explicit uncertainty.
    """

    signal = signal or {}
    technical = technical or {}
    narrative = narrative or {}
    related_news = related_news or []
    market_context = market_context or {}
    historical_similarity = historical_similarity or {}
    accuracy = accuracy or {}
    ticker = asset_value(asset, "ticker", "Asset")
    name = asset_value(asset, "name", ticker)
    sector = asset_value(asset, "sector", "Unknown sector")
    score = number(signal.get("blum_score"))
    confidence = number(signal.get("confidence_score"), number(accuracy.get("blum_confidence_score"), 0))
    classification = signal.get("classification") or "Insufficient Evidence"
    risk_level = signal.get("risk_level") or "Not Rated"
    breakdown = signal.get("score_breakdown") or {}

    facts = observed_facts(ticker, signal, technical, narrative, related_news, historical_similarity)
    causal = causal_reasoning(ticker, technical, narrative, related_news)
    narrative_analysis = analyze_narrative_state(narrative, related_news, sector=sector, ticker=ticker)
    regime = market_context.get("regime") or infer_asset_regime(signal, technical, narrative)
    market_read = market_context_read(regime, classification, risk_level)
    supporting = supporting_evidence(signal, technical, narrative, related_news, historical_similarity)
    contradicting = contradicting_evidence(signal, technical, narrative, related_news, accuracy, historical_similarity)
    uncertainty = uncertainty_points(signal, technical, narrative, related_news, historical_similarity, accuracy)
    missing = missing_information(signal, technical, narrative, related_news, historical_similarity, accuracy)
    confirmation = confirmation_conditions(technical, narrative, classification)
    invalidation = invalidation_conditions(technical, narrative, risk_level)
    risks = thesis_risks(signal, technical, narrative, accuracy, regime)
    missing_market = what_market_may_be_missing(ticker, technical, narrative, related_news, historical_similarity, breakdown)
    conviction = conviction_score(
        signal=signal,
        technical=technical,
        narrative=narrative,
        related_news=related_news,
        historical_similarity=historical_similarity,
        accuracy=accuracy,
        regime=regime,
        supporting=supporting,
        contradicting=contradicting,
        uncertainty=uncertainty,
    )
    executive = executive_thesis(ticker, name, classification, score, conviction["score"], regime, causal, supporting, contradicting)

    return {
        "ticker": ticker,
        "asset_name": name,
        "generated_from": "existing_blum_evidence",
        "executive_thesis": executive,
        "what_is_happening": what_is_happening(ticker, classification, signal, technical, narrative),
        "why_it_may_be_happening": causal["probable_causality"],
        "facts_observed": facts,
        "causal_reasoning": causal,
        "supporting_evidence": supporting,
        "contradicting_evidence": contradicting,
        "uncertainty_points": uncertainty,
        "missing_information": missing,
        "confirmation_conditions": confirmation,
        "invalidation_conditions": invalidation,
        "risks": risks,
        "market_context": {
            "regime": regime,
            "regime_classification_set": list(REGIME_LABELS),
            "interpretation": market_read,
            "signal_regime_adjustment": signal_regime_adjustment(classification, regime, risk_level),
        },
        "narrative_analysis": narrative_analysis,
        "historical_similarity": historical_similarity_read(historical_similarity),
        "what_the_market_may_be_missing": missing_market,
        "conviction": conviction,
        "conviction_score": conviction["score"],
        "conviction_reducers": conviction["reducers"],
        "intellectual_honesty": intellectual_honesty(signal, related_news, historical_similarity, contradicting, uncertainty, confidence),
        "final_blum_view": final_blum_view(ticker, classification, conviction, risks, invalidation),
        "disclaimer": DISCLAIMER,
    }


def build_signal_thesis_payload(asset: Asset, score: dict, technical: dict, narrative: dict, ts: dict) -> dict:
    signal_like = {
        "classification": score.get("classification"),
        "blum_score": score.get("blum_score"),
        "risk_level": score.get("risk_level"),
        "time_horizon": score.get("time_horizon"),
        "score_breakdown": score.get("score_breakdown", {}),
        "confidence_score": score.get("confidence_score"),
    }
    market_context = {"regime": time_series_to_market_regime(ts)}
    thesis = build_asset_thesis(
        asset=asset,
        signal=signal_like,
        technical={**technical, "time_series": ts},
        narrative=narrative,
        related_news=[],
        market_context=market_context,
        accuracy=narrative.get("accuracy_profile", {}),
    )
    return {
        "executive_thesis": thesis["executive_thesis"],
        "supporting_evidence": thesis["supporting_evidence"],
        "contradicting_evidence": thesis["contradicting_evidence"],
        "confirmation_conditions": thesis["confirmation_conditions"],
        "invalidation_conditions": thesis["invalidation_conditions"],
        "conviction_score": thesis["conviction_score"],
        "conviction_reducers": thesis["conviction_reducers"],
        "causal_reasoning": thesis["causal_reasoning"],
        "narrative_analysis": thesis["narrative_analysis"],
        "market_context": thesis["market_context"],
        "what_the_market_may_be_missing": thesis["what_the_market_may_be_missing"],
        "final_blum_view": thesis["final_blum_view"],
        "intellectual_honesty": thesis["intellectual_honesty"],
    }


def classify_market_regime(
    *,
    avg_score: float,
    sentiment_score: float,
    high_risk_ratio: float,
    etf_confirmation: float,
    quality_count: int,
    divergence_count: int,
    signal_count: int,
) -> str:
    if signal_count <= 0:
        return "Sideways"
    if sentiment_score <= -0.35 and avg_score < 48:
        return "Panic"
    if sentiment_score <= -0.16 and avg_score < 58:
        return "Risk-Off"
    if high_risk_ratio >= 0.36 and avg_score >= 62:
        return "Bull Exhaustion"
    if divergence_count >= 3 and avg_score >= 55:
        return "Bull Maturity"
    if sentiment_score >= 0.14 and avg_score >= 68 and etf_confirmation >= 58 and high_risk_ratio < 0.30:
        return "Bull Expansion"
    if quality_count >= 4 or etf_confirmation >= 62:
        return "Rotation"
    if avg_score >= 58 and sentiment_score > -0.05:
        return "Recovery"
    return "Sideways"


def enrich_theme_lifecycle(theme: dict, linked_assets: list[str] | None = None, sectors: list[str] | None = None) -> dict:
    label = theme.get("theme") or theme.get("label") or "Unknown"
    headline_count = int(number(theme.get("headline_count"), number(theme.get("article_count"), 0)))
    avg_sentiment = number(theme.get("avg_sentiment"), number(theme.get("sentiment_score"), 0))
    growth_velocity = narrative_velocity({
        "news_count_7d": theme.get("news_count_7d", headline_count),
        "news_count_30d": theme.get("news_count_30d", max(headline_count, 1) * 2),
    })
    intensity = clamp(headline_count * 12 + max(0, avg_sentiment) * 28)
    saturation = clamp(headline_count * 8)
    crowding = clamp(headline_count * 7 + max(0, avg_sentiment) * 20)
    return {
        **theme,
        "theme": label,
        "lifecycle": narrative_lifecycle(intensity, growth_velocity, saturation, crowding, avg_sentiment),
        "intensity": round(intensity, 1),
        "growth_velocity": round(growth_velocity, 3),
        "saturation": round(saturation, 1),
        "crowding": round(crowding, 1),
        "sectors_involved": sectors or [],
        "most_exposed_assets": linked_assets or [],
    }


def observed_facts(ticker: str, signal: dict, technical: dict, narrative: dict, related_news: list[dict], historical: dict) -> list[str]:
    fundamentals = narrative.get("fundamentals") or {}
    facts = [
        f"{ticker} classification is {signal.get('classification', 'Insufficient Evidence')}.",
        f"Blum score is {display(signal.get('blum_score'))} and confidence is {display(signal.get('confidence_score'))}.",
        f"5D performance is {display(technical.get('perf_5d'))}% and 1M performance is {display(technical.get('perf_1m'))}%.",
        f"7D sentiment is {display(narrative.get('sentiment_7d'))} across {int(number(narrative.get('news_count_7d')))} linked recent news records.",
        f"Stored related news items supplied to the thesis: {len(related_news)}.",
    ]
    if fundamentals.get("status") == "ready":
        facts.append(f"SEC fundamental score is {display(fundamentals.get('fundamental_score'))} from provider {fundamentals.get('provider', 'unknown')}.")
    if historical:
        facts.append(f"Historical similarity data mode is {historical.get('data_mode', historical.get('statistical_reliability', 'available'))}.")
    return facts


def causal_reasoning(ticker: str, technical: dict, narrative: dict, related_news: list[dict]) -> dict:
    perf_5d = number(technical.get("perf_5d"))
    perf_1m = number(technical.get("perf_1m"))
    sentiment_7d = number(narrative.get("sentiment_7d"))
    news_7d = number(narrative.get("news_count_7d"))
    intensity = number(narrative.get("narrative_intensity"))
    observed_event = strongest_news_event(related_news)

    facts = []
    possible_causes = []
    secondary = []
    correlations = []

    if abs(perf_5d) >= 3:
        facts.append(f"Recent price move is material at {perf_5d:.2f}% over 5D.")
    if news_7d >= 2:
        facts.append(f"News coverage is active with {int(news_7d)} linked 7D records.")
    if observed_event:
        possible_causes.append(f"External news catalyst may be present: {observed_event}.")
    if perf_5d > 2 and sentiment_7d > 0.12:
        possible_causes.append("Positive narrative flow may be reinforcing price momentum.")
        correlations.append("Price strength and sentiment are aligned.")
    elif perf_5d > 2 and sentiment_7d <= 0:
        possible_causes.append("Price may be leading the narrative, or the move may be technical/positioning-driven rather than news-driven.")
        correlations.append("Price strength is not yet confirmed by sentiment.")
    elif perf_5d < -2 and sentiment_7d > 0.12:
        possible_causes.append("News sentiment may be lagging price weakness or focusing on long-term positives while market action discounts near-term risk.")
        correlations.append("Sentiment and price are diverging.")
    elif abs(perf_5d) < 2 and intensity >= 45:
        possible_causes.append("Narrative attention is rising before a decisive price response.")
        correlations.append("News intensity is more visible than price momentum.")
    else:
        possible_causes.append("Available evidence does not support a single dominant causal driver.")

    if abs(perf_1m) >= 8:
        secondary.append("A larger 1M move can change positioning, volatility and crowding even if fundamentals are unchanged.")
    if news_7d == 0:
        secondary.append("Thin news evidence increases the chance that price action is being interpreted without a confirmed catalyst.")
    if not secondary:
        secondary.append("Secondary effects are not dominant from the current evidence set.")

    return {
        "facts_observed": facts or ["No single causal fact is strong enough to dominate the thesis."],
        "possible_causes": possible_causes,
        "secondary_effects": secondary,
        "correlations": correlations or ["No robust price/news correlation is visible yet."],
        "price_caused_sentiment": "possible" if perf_5d > 3 and news_7d >= 1 and sentiment_7d > 0 else "not established",
        "sentiment_caused_price": "possible" if news_7d >= 3 and sentiment_7d > 0.18 and perf_5d > 1 else "not established",
        "external_event_explains_both": "possible" if observed_event else "not observed",
        "probable_causality": probable_causality(perf_5d, sentiment_7d, news_7d, observed_event),
        "intellectual_honesty": "Causality is treated as probabilistic; Blum does not infer a direct cause unless price, news timing and sentiment are aligned.",
    }


def supporting_evidence(signal: dict, technical: dict, narrative: dict, related_news: list[dict], historical: dict) -> list[str]:
    rows = []
    breakdown = signal.get("score_breakdown") or {}
    fundamentals = narrative.get("fundamentals") or {}
    if number(breakdown.get("momentum_score")) >= 60:
        rows.append(f"Momentum score is {number(breakdown.get('momentum_score')):.1f}.")
    if number(breakdown.get("trend_score")) >= 60:
        rows.append(f"Trend score is {number(breakdown.get('trend_score')):.1f}; price structure is supportive.")
    if number(breakdown.get("sentiment_score")) >= 58 or number(narrative.get("sentiment_7d")) > 0.12:
        rows.append(f"Sentiment confirms part of the thesis with 7D sentiment {number(narrative.get('sentiment_7d')):.2f}.")
    if technical.get("above_sma20") and technical.get("above_sma50"):
        rows.append("Price is above both SMA20 and SMA50.")
    if number(narrative.get("news_count_7d")) >= 2:
        rows.append(f"News flow is active with {int(number(narrative.get('news_count_7d')))} linked 7D records.")
    if number(breakdown.get("fundamental_score"), number(fundamentals.get("fundamental_score"))) >= 62:
        rows.append(f"Fundamental evidence is supportive with score {number(breakdown.get('fundamental_score'), number(fundamentals.get('fundamental_score'))):.1f}.")
    if related_news:
        best = max(related_news, key=lambda item: number(item.get("quality_score")))
        rows.append(f"Highest-quality linked news source is {best.get('source', 'unknown')} with quality {display(best.get('quality_score'))}.")
    if historical.get("case_count"):
        rows.append(f"Historical similar-case sample contains {historical.get('case_count')} cases.")
    return rows or ["No strong independent confirmation is available yet."]


def contradicting_evidence(signal: dict, technical: dict, narrative: dict, related_news: list[dict], accuracy: dict, historical: dict) -> list[str]:
    rows = []
    fundamentals = narrative.get("fundamentals") or {}
    perf_5d = number(technical.get("perf_5d"))
    sentiment_7d = number(narrative.get("sentiment_7d"))
    if perf_5d > 4 and sentiment_7d < -0.12:
        rows.append("Price is rising while recent sentiment is negative.")
    if perf_5d < -4 and sentiment_7d > 0.12:
        rows.append("Price is weakening while recent sentiment is positive.")
    if number(technical.get("rsi"), 50) >= 72:
        rows.append("RSI is elevated, increasing the risk of crowded short-term momentum.")
    if signal.get("risk_level") == "High":
        rows.append("The latest signal is explicitly marked High risk.")
    if fundamentals.get("status") == "missing":
        rows.append("Fundamental evidence is missing, so the thesis is less complete.")
    elif number(fundamentals.get("fundamental_score")) < 45:
        rows.append("Fundamental score is weak relative to the technical or narrative setup.")
    if number(accuracy.get("blum_confidence_score"), 100) < 55:
        rows.append("Evidence confidence is limited by data quality checks.")
    if historical.get("data_mode") == "demonstration_mode":
        rows.append("Similar-case evidence is demonstrative, not a robust production sample.")
    if not related_news and number(narrative.get("news_count_7d")) == 0:
        rows.append("No recent linked news is available to explain the setup.")
    return rows or ["No major contradiction is visible from the current stored evidence, but absence of contradiction is not proof."]


def uncertainty_points(signal: dict, technical: dict, narrative: dict, related_news: list[dict], historical: dict, accuracy: dict) -> list[str]:
    rows = []
    if not signal or signal.get("classification") == "Insufficient Evidence":
        rows.append("A complete signal snapshot is not available.")
    if number(narrative.get("news_count_30d")) < 3:
        rows.append("Narrative sample depth is thin.")
    if len(related_news) < 2:
        rows.append("Few linked articles are available for source triangulation.")
    if historical.get("case_count", 0) and historical.get("case_count", 0) < 12:
        rows.append("Historical similarity sample is small.")
    if number(accuracy.get("blum_confidence_score"), 100) < 60:
        rows.append("Evidence quality score is below institutional confidence thresholds.")
    return rows or ["Main uncertainty is whether current alignment persists after the next data refresh."]


def missing_information(signal: dict, technical: dict, narrative: dict, related_news: list[dict], historical: dict, accuracy: dict) -> list[str]:
    rows = []
    fundamentals = narrative.get("fundamentals") or {}
    if fundamentals.get("status") != "ready":
        rows.append("Fundamental confirmation is not fully connected to the signal.")
    if number(narrative.get("news_count_7d")) == 0:
        rows.append("Recent source-backed catalyst is missing.")
    if historical.get("data_mode") in {"demonstration_mode", None, ""}:
        rows.append("Robust historical case evidence is missing or limited.")
    if not related_news:
        rows.append("Related news details are missing from the current evidence packet.")
    return rows or ["No critical missing information was detected, but additional source diversity would improve the thesis."]


def confirmation_conditions(technical: dict, narrative: dict, classification: str) -> list[str]:
    rows = [
        f"Price remains above support near {display(technical.get('support'))}.",
        f"Resistance near {display(technical.get('resistance'))} is cleared or respected according to the setup.",
        "News sentiment remains consistent across the next refresh windows.",
    ]
    if "Breakout" in classification:
        rows.append("Breakout is confirmed by relative volume rather than price alone.")
    if number(narrative.get("news_count_7d")) < 2:
        rows.append("At least two independent source-backed news records link to the asset.")
    return rows


def invalidation_conditions(technical: dict, narrative: dict, risk_level: str) -> list[str]:
    rows = [
        f"Loss of support near {display(technical.get('support'))}.",
        "Sentiment turns negative while price momentum fades.",
        "ETF or sector confirmation fails to appear after the next market refresh.",
    ]
    if risk_level == "High":
        rows.append("Volatility expands further without a compensating increase in evidence quality.")
    if number(narrative.get("sentiment_7d")) > 0:
        rows.append("Positive narrative becomes crowded but no longer improves price structure.")
    return rows


def thesis_risks(signal: dict, technical: dict, narrative: dict, accuracy: dict, regime: str) -> list[str]:
    rows = []
    fundamentals = narrative.get("fundamentals") or {}
    if signal.get("risk_level") == "High":
        rows.append("High signal risk can make the thesis unstable even when momentum is strong.")
    if regime in {"Risk-Off", "Panic", "Bull Exhaustion"}:
        rows.append(f"Current market regime ({regime}) reduces tolerance for weak or crowded setups.")
    if number(technical.get("historical_volatility")) >= 55:
        rows.append("Historical volatility is elevated.")
    if number(accuracy.get("blum_confidence_score"), 100) < 55:
        rows.append("Data quality limits conviction.")
    if number(narrative.get("sentiment_polarization")) > 0.8:
        rows.append("Sentiment polarization is high; narrative interpretation may be unstable.")
    if fundamentals.get("status") == "missing":
        rows.append("Fundamental coverage is missing or incomplete.")
    return rows or ["No dominant single risk, but thesis quality depends on continued evidence alignment."]


def what_market_may_be_missing(ticker: str, technical: dict, narrative: dict, related_news: list[dict], historical: dict, breakdown: dict) -> list[str]:
    rows = []
    perf_5d = number(technical.get("perf_5d"))
    sentiment_7d = number(narrative.get("sentiment_7d"))
    semantic = number(breakdown.get("semantic_trend_score"), number(narrative.get("semantic_trend_score")))
    etf = number(breakdown.get("etf_confirmation_score"))
    if semantic >= 60 and perf_5d < 2:
        rows.append("Narrative/semantic pressure is stronger than price response; the market may not have fully repriced the theme yet.")
    if etf >= 60 and number(breakdown.get("momentum_score")) < 55:
        rows.append("ETF confirmation may be stronger than the single-name move.")
    if sentiment_7d > 0.18 and perf_5d <= 0:
        rows.append("Positive sentiment exists despite weak price action; this may be either an overlooked setup or a value trap.")
    if perf_5d > 4 and sentiment_7d <= 0:
        rows.append("Price strength may be occurring before broad narrative recognition.")
    if related_news and max(number(item.get("quality_score")) for item in related_news) >= 75:
        rows.append("A high-quality source is present; lower-quality headline counts may understate the evidence.")
    if historical.get("positive_outcome_probability_20d") and historical.get("positive_outcome_probability_20d") < 0.5:
        rows.append("Similar historical setups were not consistently positive; the market may be over-extrapolating the current story.")
    return rows or [f"No clear market blind spot is visible for {ticker}; Blum treats this as a monitor-only thesis."]


def conviction_score(**kwargs) -> dict:
    signal = kwargs["signal"]
    technical = kwargs["technical"]
    narrative = kwargs["narrative"]
    historical = kwargs["historical_similarity"]
    accuracy = kwargs["accuracy"]
    supporting = kwargs["supporting"]
    contradicting = kwargs["contradicting"]
    uncertainty = kwargs["uncertainty"]
    regime = kwargs["regime"]
    breakdown = signal.get("score_breakdown") or {}
    evidence_quality = number(accuracy.get("blum_confidence_score"), number(signal.get("confidence_score"), 0))
    independent_confirmations = sum(
        [
            number(breakdown.get("momentum_score")) >= 60,
            number(breakdown.get("trend_score")) >= 60,
            number(breakdown.get("sentiment_score")) >= 58 or number(narrative.get("sentiment_7d")) > 0.12,
            number(breakdown.get("etf_confirmation_score")) >= 55,
            number(breakdown.get("fundamental_score")) >= 62,
            number(historical.get("case_count")) >= 12,
        ]
    )
    confirmation_score = independent_confirmations / 6 * 100
    contradiction_score = clamp(100 - max(0, len(contradicting) - 1) * 18)
    narrative_score = clamp(number(breakdown.get("semantic_trend_score"), number(narrative.get("semantic_trend_score"))))
    technical_score = mean_safe([number(breakdown.get("momentum_score")), number(breakdown.get("trend_score"))])
    historical_score = 50
    if historical.get("data_mode") == "real_historical_cases":
        historical_score = clamp(50 + number(historical.get("positive_outcome_probability_20d")) * 50 + min(15, number(historical.get("case_count")) / 3))
    context_score = 70 if regime in {"Bull Expansion", "Rotation", "Recovery"} else 55 if regime in {"Sideways", "Bull Maturity"} else 38
    raw = mean_safe([evidence_quality, confirmation_score, contradiction_score, narrative_score, technical_score, historical_score, context_score])
    reducers = []
    if evidence_quality < 55:
        reducers.append("Evidence quality is below the preferred threshold.")
    if len(contradicting) > 1:
        reducers.append("Contradicting evidence exists and must be resolved.")
    if len(uncertainty) > 2:
        reducers.append("Multiple uncertainty points reduce thesis strength.")
    if regime in {"Risk-Off", "Panic", "Bull Exhaustion"}:
        reducers.append(f"Market regime {regime} reduces conviction for aggressive interpretations.")
    return {
        "score": round(clamp(raw), 1),
        "label": "High" if raw >= 74 else "Medium" if raw >= 54 else "Low",
        "meaning": "Measures thesis strength, not probability of profit.",
        "components": {
            "evidence_quality": round(evidence_quality, 1),
            "independent_confirmations": round(confirmation_score, 1),
            "absence_of_contradictions": round(contradiction_score, 1),
            "narrative_coherence": round(narrative_score, 1),
            "technical_coherence": round(technical_score, 1),
            "historical_support": round(historical_score, 1),
            "market_context": round(context_score, 1),
            "fundamental_support": round(number(breakdown.get("fundamental_score")), 1),
        },
        "reducers": reducers or ["No major conviction reducer was detected, but the thesis remains conditional."],
    }


def analyze_narrative_state(narrative: dict, related_news: list[dict], sector: str, ticker: str) -> dict:
    intensity = clamp(number(narrative.get("narrative_intensity")) or len(related_news) * 14)
    velocity = narrative_velocity(narrative)
    saturation = clamp(number(narrative.get("news_count_30d")) * 7 + len(related_news) * 4)
    crowding = clamp(max(0, number(narrative.get("sentiment_7d"))) * 35 + number(narrative.get("news_count_7d")) * 10)
    sentiment = number(narrative.get("sentiment_7d"))
    return {
        "lifecycle": narrative_lifecycle(intensity, velocity, saturation, crowding, sentiment),
        "intensity": round(intensity, 1),
        "growth_velocity": round(velocity, 3),
        "saturation": round(saturation, 1),
        "crowding": round(crowding, 1),
        "sectors_involved": [sector] if sector else [],
        "most_exposed_assets": [ticker],
        "interpretation": narrative_interpretation(intensity, velocity, saturation, crowding, sentiment),
    }


def narrative_velocity(narrative: dict) -> float:
    count_7 = number(narrative.get("news_count_7d"))
    count_30 = number(narrative.get("news_count_30d"))
    expected_7 = max(1.0, count_30 * 7 / 30)
    return (count_7 - expected_7) / expected_7


def narrative_lifecycle(intensity: float, velocity: float, saturation: float, crowding: float, sentiment: float) -> str:
    if intensity < 18 and velocity >= 0:
        return "Emerging"
    if velocity >= 1.15 and intensity >= 35:
        return "Accelerating"
    if velocity >= 0.25:
        return "Growing"
    if crowding >= 72 and saturation >= 65:
        return "Crowded"
    if intensity >= 58 and abs(velocity) < 0.25:
        return "Mature"
    if velocity <= -0.55 and sentiment <= 0:
        return "Dying"
    if velocity < -0.20:
        return "Weakening"
    return "Mature"


def narrative_interpretation(intensity: float, velocity: float, saturation: float, crowding: float, sentiment: float) -> str:
    lifecycle = narrative_lifecycle(intensity, velocity, saturation, crowding, sentiment)
    if lifecycle == "Accelerating":
        return "Narrative attention is expanding quickly; verify whether price and volume confirm the story."
    if lifecycle == "Crowded":
        return "Narrative is visible and potentially crowded; require stricter invalidation rules."
    if lifecycle == "Weakening":
        return "Narrative attention is fading; avoid relying on old catalysts."
    if lifecycle == "Emerging":
        return "Narrative is early or thin; useful for monitoring, not enough for strong conviction."
    return "Narrative is established; focus on whether incremental evidence still improves."


def historical_similarity_read(historical: dict) -> dict:
    if not historical:
        return {
            "status": "missing",
            "explanation": "No historical similarity packet was supplied to this thesis.",
        }
    return {
        "status": historical.get("data_mode", "available"),
        "similar_cases_found": historical.get("case_count", 0),
        "average_forward_return_20d": historical.get("avg_forward_return_20d"),
        "success_rate": historical.get("positive_outcome_probability_20d"),
        "average_drawdown": historical.get("average_drawdown"),
        "reliability": historical.get("statistical_reliability"),
        "explanation": historical.get("reason") or historical.get("method") or "Historical setup comparison supplied by Blum memory/backtest.",
    }


def executive_thesis(ticker: str, name: str, classification: str, score: float, conviction: float, regime: str, causal: dict, supporting: list[str], contradicting: list[str]) -> str:
    support_text = supporting[0] if supporting else "supporting evidence is still forming"
    contradiction_text = contradicting[0] if contradicting else "no major contradiction is visible"
    return (
        f"{ticker} ({name}) is a {classification} research setup with Blum score {score:.1f} "
        f"and thesis conviction {conviction:.1f}/100 in a {regime} regime. "
        f"The working explanation is: {causal['probable_causality']} "
        f"Primary support: {support_text} Main challenge: {contradiction_text}"
    )


def what_is_happening(ticker: str, classification: str, signal: dict, technical: dict, narrative: dict) -> str:
    return (
        f"{ticker} is currently framed as {classification}. Price momentum is {display(technical.get('perf_5d'))}% over 5D, "
        f"news intensity is {display(narrative.get('narrative_intensity'))}, and risk is {signal.get('risk_level', 'Not Rated')}."
    )


def intellectual_honesty(signal: dict, related_news: list[dict], historical: dict, contradicting: list[str], uncertainty: list[str], confidence: float) -> list[str]:
    rows = []
    if confidence < 50:
        rows.append("Confidence is low; the thesis should be read as an evidence checklist, not a strong conclusion.")
    if len(related_news) < 2:
        rows.append("Source triangulation is limited.")
    if historical.get("data_mode") == "demonstration_mode" or not historical:
        rows.append("Historical support is limited or demonstrative.")
    if contradicting:
        rows.append("Alternative explanations exist and are shown explicitly in contradicting evidence.")
    if signal.get("classification") == "Insufficient Evidence":
        rows.append("The asset should not be ranked as an active opportunity until price/news/signal evidence improves.")
    return rows or ["The thesis is conditional and should be re-evaluated as fresh evidence arrives."]


def final_blum_view(ticker: str, classification: str, conviction: dict, risks: list[str], invalidation: list[str]) -> str:
    if classification == "Insufficient Evidence" or conviction["score"] < 40:
        stance = "monitor only until evidence quality improves"
    elif conviction["score"] >= 74:
        stance = "strong attention candidate, subject to invalidation checks"
    elif conviction["score"] >= 54:
        stance = "watch candidate with conditional confirmation requirements"
    else:
        stance = "research watch, not enough thesis strength for escalation"
    return (
        f"Blum view on {ticker}: {stance}. Main risk: {risks[0] if risks else 'risk evidence is still forming'}. "
        f"Invalidation starts with: {invalidation[0] if invalidation else 'missing invalidation evidence'}."
    )


def probable_causality(perf_5d: float, sentiment_7d: float, news_7d: float, event: str | None) -> str:
    if event and news_7d >= 2 and abs(perf_5d) >= 2:
        return "An external event may be driving both sentiment and price; confirm timing before assigning causality."
    if perf_5d > 2 and sentiment_7d > 0.12 and news_7d >= 2:
        return "Sentiment/news and price are mutually reinforcing, but direct causality remains probabilistic."
    if perf_5d > 2 and sentiment_7d <= 0:
        return "The move appears more price-led or technical than narrative-led."
    if perf_5d < -2 and sentiment_7d > 0.12:
        return "The market may be discounting risks that the positive narrative has not absorbed."
    if news_7d >= 3 and abs(perf_5d) < 2:
        return "Narrative activity is visible but has not yet translated into a decisive price move."
    return "Current evidence does not isolate a dominant cause."


def market_context_read(regime: str, classification: str, risk_level: str) -> str:
    if regime in {"Panic", "Risk-Off"}:
        return "Signals require higher evidence quality because broad risk appetite is weak."
    if regime == "Bull Exhaustion":
        return "Momentum may work briefly but crowding and volatility deserve stricter invalidation rules."
    if regime == "Rotation":
        return "Sector and ETF confirmation matter more than isolated single-name strength."
    if regime == "Bull Expansion":
        return "Aligned technical and narrative setups can receive more attention if risk remains controlled."
    if regime == "Recovery":
        return "Early improvement can be meaningful, but durability is not yet proven."
    return f"{classification} with {risk_level} risk should be evaluated selectively."


def signal_regime_adjustment(classification: str, regime: str, risk_level: str) -> str:
    if regime in {"Risk-Off", "Panic"} and "Breakout" in classification:
        return "Breakout signal is discounted because the regime is defensive."
    if regime == "Bull Exhaustion" and risk_level == "High":
        return "High-risk momentum is penalized because the regime may be late-cycle or crowded."
    if regime == "Rotation":
        return "Signal is upgraded only if sector/ETF confirmation persists."
    if regime == "Bull Expansion":
        return "Signal receives contextual support if news and volume remain aligned."
    return "No material regime adjustment beyond standard confirmation checks."


def infer_asset_regime(signal: dict, technical: dict, narrative: dict) -> str:
    score = number(signal.get("blum_score"))
    sentiment = number(narrative.get("sentiment_7d"))
    risk = signal.get("risk_level")
    if sentiment < -0.25 and score < 48:
        return "Risk-Off"
    if risk == "High" and score >= 62:
        return "Bull Exhaustion"
    if score >= 68 and sentiment >= 0.12:
        return "Bull Expansion"
    if number(technical.get("perf_1m")) > 6 and sentiment < 0:
        return "Bull Maturity"
    if score >= 55 and sentiment > -0.05:
        return "Recovery"
    return "Sideways"


def time_series_to_market_regime(ts: dict) -> str:
    regime = str(ts.get("regime", "unknown")).lower()
    anomaly = number(ts.get("anomaly_score"))
    if anomaly >= 75 and "high" in regime:
        return "Panic"
    if "high" in regime:
        return "Risk-Off"
    if "low" in regime:
        return "Sideways"
    return "Rotation"


def strongest_news_event(related_news: list[dict]) -> str | None:
    if not related_news:
        return None
    best = max(related_news, key=lambda item: number(item.get("quality_score")))
    title = best.get("title")
    source = best.get("source")
    if not title:
        return None
    return f"{title[:140]} ({source or 'unknown source'})"


def asset_value(asset: Asset | dict, key: str, default: Any = None) -> Any:
    if isinstance(asset, dict):
        return asset.get(key, default)
    return getattr(asset, key, default)


def number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def display(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.2f}"
    except Exception:
        return str(value)


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def mean_safe(values: list[float]) -> float:
    valid = [float(value) for value in values if value is not None]
    return mean(valid) if valid else 0.0
