from __future__ import annotations

from app.ai.embeddings import EmbeddingModel
from app.ai.financial_brain import FinancialBrainModel
from app.ai.llm import ReasoningModel
from app.ai.sentiment import FinancialSentimentModel
from app.ai.time_series import TimeSeriesIntelligence
from app.services.thesis_engine import build_asset_thesis


class AIOrchestrator:
    """Task router for specialized AI modules.

    FinBERT handles financial sentiment, sentence-transformers handles semantic
    search and clustering, the reasoning LLM writes explanations from retrieved
    evidence, and the time-series module handles anomalies/regime/scenarios.
    """

    def __init__(self):
        self.sentiment = FinancialSentimentModel()
        self.embeddings = EmbeddingModel()
        self.reasoning = ReasoningModel()
        self.time_series = TimeSeriesIntelligence()
        self.financial_brain = FinancialBrainModel()

    def generate_asset_insight(
        self,
        ticker: str,
        signal: dict,
        technical: dict,
        narrative: dict,
        related_news: list[dict],
        market_context: dict | None = None,
        historical_similarity: dict | None = None,
        accuracy: dict | None = None,
    ) -> dict:
        evidence = {
            "ticker": ticker,
            "signal": signal,
            "technical": technical,
            "narrative": narrative,
            "related_news": related_news[:8],
        }
        explanation = self.reasoning.explain(evidence)
        asset = signal.get("asset") or {"ticker": ticker, "name": ticker, "sector": "Unknown"}
        thesis = build_asset_thesis(
            asset=asset,
            signal=signal,
            technical=technical,
            narrative=narrative,
            related_news=related_news,
            market_context=market_context,
            historical_similarity=historical_similarity,
            accuracy=accuracy,
        )
        return {
            "ticker": ticker,
            "classification": signal.get("classification", "Neutral"),
            "blum_score": signal.get("blum_score", 0),
            "reason": explanation.get("reason", thesis["executive_thesis"]),
            "thesis": thesis,
            "executive_thesis": thesis["executive_thesis"],
            "conviction_score": thesis["conviction_score"],
            "supporting_evidence": thesis["supporting_evidence"],
            "contradicting_evidence": thesis["contradicting_evidence"],
            "what_the_market_may_be_missing": thesis["what_the_market_may_be_missing"],
            "final_blum_view": thesis["final_blum_view"],
            "watch_points": explanation.get("watch_points", []),
            "risk_level": explanation.get("risk_level", signal.get("risk_level", "Medium")),
            "time_horizon": explanation.get("time_horizon", signal.get("time_horizon", "Short/Medium term")),
            "monitor_next": explanation.get("monitor_next", []),
            "models_used": {
                "sentiment": self.sentiment.settings.finbert_model,
                "embeddings": self.embeddings.model_name,
                "reasoning": explanation.get("model_name", self.reasoning.model_name),
                "time_series": self.time_series.model_name,
            },
        }

    def generate_market_brain_insight(self, market_packet: dict) -> dict:
        return self.financial_brain.analyze_market(market_packet)
