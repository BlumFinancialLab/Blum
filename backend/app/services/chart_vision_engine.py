from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

import requests

from app.core.config import get_settings


CHART_VISION_PROMPT = (
    "You are an expert institutional technical analyst. Analyze this financial chart with maximum precision. "
    "Identify trend, structure, support, resistance, breakout/breakdown, volume behavior, volatility compression, "
    "candlestick signals, moving average behavior, momentum signals, divergences, continuation/reversal patterns, "
    "and invalidation levels. Distinguish between what is visually observable and what is inferred. "
    "Do not invent data not visible in the chart. Return structured JSON with: chart_type, timeframe_detected, "
    "asset_detected, visible_indicators, trend_structure, support_levels, resistance_levels, chart_patterns, "
    "candlestick_patterns, volume_analysis, momentum_interpretation, volatility_interpretation, bullish_evidence, "
    "bearish_evidence, neutral_evidence, invalidation_levels, technical_summary, confidence, uncertainty_notes."
)


class ChartVisionEngine:
    def __init__(self):
        self.settings = get_settings()

    def status(self) -> dict:
        return {
            "mode": self.settings.chart_vision_mode,
            "primary_model": self.settings.chart_vision_model,
            "fallback_model": self.settings.chart_vision_fallback_model,
            "remote_configured": bool(self.settings.chart_vision_remote_url),
            "min_confidence": self.settings.chart_vision_min_confidence,
            "runtime_policy": "Vision is optional. If unavailable, deterministic OHLCV analysis remains active.",
        }

    def analyze_image(self, image_bytes: bytes, ticker: str | None = None, timeframe: str | None = None, ohlcv_hint: dict | None = None) -> dict:
        image_hash = hashlib.sha256(image_bytes).hexdigest()
        if self.settings.chart_vision_mode == "remote" and self.settings.chart_vision_remote_url:
            remote = self._remote_inference(image_bytes, ticker=ticker, timeframe=timeframe, ohlcv_hint=ohlcv_hint)
            remote["image_hash"] = image_hash
            if confidence_meets_threshold(remote.get("confidence"), self.settings.chart_vision_min_confidence):
                return normalize_visual_analysis(remote, image_hash, self.settings.chart_vision_model)
            fallback = self._remote_inference(image_bytes, ticker=ticker, timeframe=timeframe, ohlcv_hint=ohlcv_hint, fallback=True)
            fallback["image_hash"] = image_hash
            return normalize_visual_analysis(fallback, image_hash, self.settings.chart_vision_fallback_model)
        if self.settings.chart_vision_mode == "local":
            local = self._local_inference(image_bytes, ticker=ticker, timeframe=timeframe, ohlcv_hint=ohlcv_hint)
            local["image_hash"] = image_hash
            return normalize_visual_analysis(local, image_hash, local.get("model_used", self.settings.chart_vision_model))
        return disabled_visual_analysis(image_hash, ticker, timeframe)

    def _remote_inference(self, image_bytes: bytes, ticker: str | None, timeframe: str | None, ohlcv_hint: dict | None, fallback: bool = False) -> dict:
        model = self.settings.chart_vision_fallback_model if fallback else self.settings.chart_vision_model
        headers = {"Content-Type": "application/json"}
        if self.settings.chart_vision_remote_token:
            headers["Authorization"] = f"Bearer {self.settings.chart_vision_remote_token}"
        payload = {
            "model": model,
            "prompt": CHART_VISION_PROMPT,
            "image_base64": base64.b64encode(image_bytes).decode("ascii"),
            "ticker": ticker,
            "timeframe": timeframe,
            "ohlcv_hint": ohlcv_hint or {},
            "response_format": "json",
        }
        try:
            response = requests.post(self.settings.chart_vision_remote_url, headers=headers, json=payload, timeout=90)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and "visual_analysis" in data:
                data = data["visual_analysis"]
            if isinstance(data, str):
                data = json.loads(data)
            data["model_used"] = model
            data["mode"] = "remote"
            return data
        except Exception as exc:
            return unavailable_visual_analysis(ticker, timeframe, model, f"Remote chart vision failed: {type(exc).__name__}: {str(exc)}")

    def _local_inference(self, image_bytes: bytes, ticker: str | None, timeframe: str | None, ohlcv_hint: dict | None) -> dict:
        try:
            import torch
        except Exception as exc:
            return unavailable_visual_analysis(ticker, timeframe, self.settings.chart_vision_model, f"PyTorch unavailable: {type(exc).__name__}: {str(exc)}")
        if not torch.cuda.is_available():
            return unavailable_visual_analysis(ticker, timeframe, self.settings.chart_vision_model, "No GPU detected. Local Qwen3-VL inference is disabled to keep the Space responsive.")
        return unavailable_visual_analysis(
            ticker,
            timeframe,
            self.settings.chart_vision_model,
            "Local VLM adapter is configured but not activated in this CPU demo. Use CHART_VISION_MODE=remote for production-grade VLM serving.",
        )


def normalize_visual_analysis(payload: dict, image_hash: str, model_used: str) -> dict:
    base = empty_visual_contract()
    base.update({key: payload.get(key, base[key]) for key in base})
    base["image_hash"] = image_hash
    base["model_used"] = payload.get("model_used") or model_used
    base["mode"] = payload.get("mode", "remote")
    base["confidence"] = safe_confidence(base.get("confidence"))
    base["uncertainty_notes"] = normalize_list(base.get("uncertainty_notes"))
    return base


def disabled_visual_analysis(image_hash: str, ticker: str | None, timeframe: str | None) -> dict:
    payload = empty_visual_contract()
    payload.update(
        {
            "image_hash": image_hash,
            "model_used": "chart_vision_disabled",
            "mode": "disabled",
            "asset_detected": ticker or "",
            "timeframe_detected": timeframe or "unknown",
            "technical_summary": "Vision model unavailable, deterministic analysis active.",
            "confidence": 0.0,
            "uncertainty_notes": [
                "CHART_VISION_MODE is disabled.",
                "No visual levels are inferred from the uploaded chart.",
                "Use deterministic OHLCV analysis for calculated technical evidence.",
            ],
        }
    )
    return payload


def unavailable_visual_analysis(ticker: str | None, timeframe: str | None, model: str, reason: str) -> dict:
    payload = empty_visual_contract()
    payload.update(
        {
            "model_used": model,
            "mode": "unavailable",
            "asset_detected": ticker or "",
            "timeframe_detected": timeframe or "unknown",
            "technical_summary": "Vision model unavailable, deterministic analysis active.",
            "confidence": 0.0,
            "uncertainty_notes": [reason],
        }
    )
    return payload


def empty_visual_contract() -> dict[str, Any]:
    return {
        "chart_type": "unknown",
        "timeframe_detected": "unknown",
        "asset_detected": "",
        "visible_indicators": [],
        "trend_structure": {},
        "support_levels": [],
        "resistance_levels": [],
        "chart_patterns": [],
        "candlestick_patterns": [],
        "volume_analysis": {},
        "momentum_interpretation": {},
        "volatility_interpretation": {},
        "bullish_evidence": [],
        "bearish_evidence": [],
        "neutral_evidence": [],
        "invalidation_levels": [],
        "technical_summary": "",
        "confidence": 0.0,
        "uncertainty_notes": [],
    }


def safe_confidence(value: Any) -> float:
    try:
        numeric = float(value)
        if numeric <= 1:
            numeric *= 100
        return round(max(0, min(100, numeric)), 1)
    except (TypeError, ValueError):
        return 0.0


def confidence_meets_threshold(value: Any, threshold: float) -> bool:
    confidence = safe_confidence(value)
    threshold_pct = threshold * 100 if threshold <= 1 else threshold
    return confidence >= threshold_pct


def normalize_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [str(value)]
