from __future__ import annotations


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def scale(value, low: float, high: float, invert: bool = False) -> float:
    try:
        number = float(value)
    except Exception:
        return 50.0
    if high == low:
        return 50.0
    score = (number - low) / (high - low) * 100
    score = 100 - score if invert else score
    return clamp(score)


def avg(*values) -> float:
    clean = [float(value) for value in values if value is not None]
    return sum(clean) / len(clean) if clean else 0.0


def safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default

