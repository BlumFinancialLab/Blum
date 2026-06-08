from __future__ import annotations

from functools import cached_property
import math

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from app.core.config import get_settings


class FinancialSentimentModel:
    """Financial sentiment adapter.

    FinBERT is the primary engine. VADER remains available as a transparent baseline
    and fallback when model loading is not available in a constrained demo runtime.
    """

    def __init__(self):
        self.settings = get_settings()
        self.vader = SentimentIntensityAnalyzer()

    @cached_property
    def finbert(self):
        if not self.settings.enable_model_loading:
            return None
        try:
            from transformers import pipeline

            return pipeline(
                "text-classification",
                model=self.settings.finbert_model,
                tokenizer=self.settings.finbert_model,
                truncation=True,
                top_k=None,
            )
        except Exception:
            return None

    def analyze(self, text: str) -> dict:
        text = (text or "")[:1800]
        vader_score = self.vader.polarity_scores(text)["compound"]
        baseline = self._label_from_score(vader_score)
        model = self.finbert
        if model is None:
            return {
                "model_name": "vader-baseline",
                "label": baseline,
                "score": round(vader_score, 4),
                "confidence": abs(vader_score),
                "baseline_vader": round(vader_score, 4),
                "raw": {"fallback": True},
            }
        try:
            result = model(text)[0]
            if isinstance(result, list):
                result = sorted(result, key=lambda item: item.get("score", 0), reverse=True)[0]
            label = normalize_finbert_label(result.get("label", "neutral"))
            confidence = float(result.get("score", 0.0))
            signed_score = confidence if label == "positive" else -confidence if label == "negative" else 0.0
            return {
                "model_name": self.settings.finbert_model,
                "label": label,
                "score": round(signed_score, 4),
                "confidence": round(confidence, 4),
                "baseline_vader": round(vader_score, 4),
                "raw": result,
            }
        except Exception:
            return {
                "model_name": "vader-baseline",
                "label": baseline,
                "score": round(vader_score, 4),
                "confidence": abs(vader_score),
                "baseline_vader": round(vader_score, 4),
                "raw": {"fallback": True},
            }

    def _label_from_score(self, value: float) -> str:
        if value > 0.18:
            return "positive"
        if value < -0.18:
            return "negative"
        return "neutral"


def normalize_finbert_label(label: str) -> str:
    value = label.lower()
    if "pos" in value:
        return "positive"
    if "neg" in value:
        return "negative"
    return "neutral"


def average_sentiment(rows: list[float]) -> float:
    values = [float(x) for x in rows if x is not None and math.isfinite(float(x))]
    if not values:
        return 0.0
    return sum(values) / len(values)

