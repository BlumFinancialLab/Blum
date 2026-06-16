from __future__ import annotations


def opportunity_label(score: float, risk_score: float) -> str:
    if risk_score >= 74 and score >= 68:
        return "High-risk setup to monitor"
    if score >= 82:
        return "Priority setup to monitor"
    if score >= 70:
        return "In acceleration"
    if score >= 58:
        return "Under observation"
    if score >= 46:
        return "Selective monitoring"
    return "Low priority today"


def build_score_explanation(ticker: str, factors: dict, score: float) -> str:
    drivers = []
    if factors["momentum_score"] >= 65:
        drivers.append(f"price momentum is elevated ({factors['momentum_score']:.0f}/100)")
    if factors["trend_score"] >= 65:
        drivers.append(f"trend quality is constructive ({factors['trend_score']:.0f}/100)")
    if factors["volume_score"] >= 65:
        drivers.append(f"relative volume is active ({factors['volume_score']:.0f}/100)")
    if factors["sentiment_score"] >= 60:
        drivers.append(f"sentiment is supportive ({factors['sentiment_score']:.0f}/100)")
    if factors["news_score"] >= 60:
        drivers.append(f"news intensity is above baseline ({factors['news_score']:.0f}/100)")
    if factors["risk_score"] >= 70:
        drivers.append(f"risk pressure is high ({factors['risk_score']:.0f}/100)")
    if not drivers:
        drivers.append("the factor stack is mixed and requires more confirmation")
    return f"{ticker} scores {score:.0f}/100 because " + ", ".join(drivers[:4]) + "."


def watch_points_from_factors(factors: dict) -> list[str]:
    points = []
    if factors["risk_score"] >= 70:
        points.append("Monitor volatility and drawdown before escalating conviction.")
    if factors["volume_score"] >= 70:
        points.append("Check whether elevated volume persists beyond one session.")
    if factors["sentiment_score"] < 45 and factors["momentum_score"] >= 65:
        points.append("Price strength is not fully confirmed by sentiment.")
    if factors["trend_score"] >= 65:
        points.append("Watch trend support near the latest moving-average zone.")
    if not points:
        points.append("Wait for stronger price, news or sentiment confirmation.")
    return points

