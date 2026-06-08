from __future__ import annotations

from functools import cached_property
import json

from app.core.config import get_settings


class ReasoningModel:
    """Lightweight LLM layer for structured explanations from retrieved evidence only."""

    def __init__(self):
        self.settings = get_settings()
        self.model_name = self.settings.llm_model

    @cached_property
    def generator(self):
        if not self.settings.enable_model_loading:
            return None
        try:
            from transformers import pipeline

            return pipeline(
                "text-generation",
                model=self.settings.llm_model,
                tokenizer=self.settings.llm_model,
                max_new_tokens=320,
                do_sample=False,
            )
        except Exception:
            return None

    def explain(self, evidence: dict) -> dict:
        prompt = build_prompt(evidence)
        if self.generator is not None:
            try:
                output = self.generator(prompt)[0]["generated_text"]
                response = output.split("JSON_OUTPUT:")[-1].strip()
                parsed = extract_json(response)
                if parsed:
                    parsed["model_name"] = self.model_name
                    return parsed
            except Exception:
                pass
        return deterministic_explanation(evidence)


def build_prompt(evidence: dict) -> str:
    payload = json.dumps(evidence, ensure_ascii=False)[:5000]
    return (
        "You are an open-source financial intelligence reasoning layer. "
        "Use only the JSON evidence. Do not invent facts, forecasts, prices, or recommendations. "
        "Return concise JSON with reason, watch_points, risk_level, time_horizon, and monitor_next.\n"
        f"EVIDENCE:\n{payload}\nJSON_OUTPUT:"
    )


def extract_json(text: str) -> dict | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except Exception:
        return None


def deterministic_explanation(evidence: dict) -> dict:
    signal = evidence.get("signal", {})
    technical = evidence.get("technical", {})
    narrative = evidence.get("narrative", {})
    ticker = evidence.get("ticker", "asset")
    reason = (
        f"{ticker} surfaced because the composite engine found {signal.get('classification', 'a watchlist signal')} "
        f"with momentum {signal.get('score_breakdown', {}).get('momentum_score', 0):.0f}, "
        f"trend {signal.get('score_breakdown', {}).get('trend_score', 0):.0f}, "
        f"sentiment {signal.get('score_breakdown', {}).get('sentiment_score', 0):.0f}, "
        f"and anomaly pressure {signal.get('score_breakdown', {}).get('anomaly_score', 0):.0f}."
    )
    watch_points = [
        f"Monitor support near {technical.get('support', 'recent support')} and resistance near {technical.get('resistance', 'recent resistance')}.",
        "Check whether sentiment keeps confirming the price move over the next 7 to 30 days.",
        "Watch ETF and sector confirmation before treating the signal as durable.",
    ]
    if narrative.get("sentiment_divergence"):
        watch_points.append("Price and narrative are diverging; require confirmation before escalating.")
    return {
        "model_name": "deterministic-evidence-reasoner",
        "reason": reason,
        "watch_points": watch_points,
        "risk_level": signal.get("risk_level", "Medium"),
        "time_horizon": signal.get("time_horizon", "Short/Medium term"),
        "monitor_next": ["news intensity", "SMA20 hold", "volume confirmation", "ETF confirmation"],
    }

