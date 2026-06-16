from __future__ import annotations


OPPORTUNITY_WEIGHTS = {
    "momentum": 0.18,
    "trend": 0.16,
    "relative_strength": 0.12,
    "volume": 0.10,
    "sentiment": 0.13,
    "news": 0.10,
    "sector": 0.08,
    "macro": 0.06,
    "risk": 0.07,
}


RISK_WEIGHTS = {
    "volatility": 0.30,
    "drawdown": 0.25,
    "beta": 0.20,
    "overextension": 0.15,
    "evidence_gap": 0.10,
}


def normalized_weights(weights: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(value)) for value in weights.values()) or 1.0
    return {key: float(value) / total for key, value in weights.items()}

