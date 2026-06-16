from __future__ import annotations

from datetime import datetime
import math
from statistics import mean

import numpy as np
import pandas as pd

from app.signals.indicators import compute_indicators


TIMEFRAME_LIMITS = {
    "1D": 96,
    "5D": 120,
    "1M": 42,
    "3M": 84,
    "6M": 150,
    "YTD": 260,
    "1Y": 260,
    "5Y": 1260,
}


class TechnicalAnalysisEngine:
    def analyze(self, price_frame: pd.DataFrame, timeframe: str = "6M", benchmark_frame: pd.DataFrame | None = None) -> dict:
        df = normalize_frame(price_frame, timeframe)
        if df.empty or len(df) < 20:
            return insufficient_analysis(timeframe, len(df))
        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        open_ = df["open"].astype(float)
        volume = df["volume"].fillna(0).astype(float)
        indicators = compute_indicators(df, benchmark_frame)
        pivots = pivot_points(df)
        levels = key_levels(df, pivots)
        ma = moving_averages(close)
        momentum = momentum_block(close, indicators)
        volume_block = volume_analysis(volume, close)
        volatility = volatility_block(df, indicators)
        structure = trend_structure(df, pivots, ma, indicators)
        patterns = pattern_detection(df, pivots, ma, levels, volatility, volume_block)
        divergences = divergence_detection(df, indicators)
        gaps = gap_detection(open_, close, high, low)
        consolidation = consolidation_zones(df, volatility)
        accumulation = accumulation_distribution(df)
        risk_reward = risk_reward_estimate(close.iloc[-1], levels, volatility, structure)
        breakout_probability = breakout_probability_score(structure, momentum, volume_block, volatility, levels, close.iloc[-1])
        trend_strength = trend_strength_score(structure, momentum, volatility, volume_block, ma)
        pullback = pullback_quality(close, ma, levels, indicators)
        signals = technical_signals(structure, momentum, volume_block, volatility, patterns, divergences, breakout_probability, risk_reward)
        report = analyst_summary(structure, momentum, volume_block, volatility, levels, signals, breakout_probability, risk_reward)
        return {
            "status": "ready",
            "generated_at": datetime.utcnow().isoformat(),
            "timeframe": timeframe,
            "observed_rows": int(len(df)),
            "last_price": round(float(close.iloc[-1]), 4),
            "trend_direction": structure["trend_direction"],
            "trend_structure": structure,
            "moving_averages": ma,
            "momentum": momentum,
            "volatility": volatility,
            "volume": volume_block,
            "levels": levels,
            "support_levels": levels["support_levels"],
            "resistance_levels": levels["resistance_levels"],
            "breakout_level": levels["breakout_level"],
            "breakdown_level": levels["breakdown_level"],
            "invalidation_level": levels["invalidation_level"],
            "technical_indicators": {
                "rsi": indicators.get("rsi"),
                "macd": indicators.get("macd"),
                "macd_signal": indicators.get("macd_signal"),
                "macd_hist": indicators.get("macd_hist"),
                "bollinger_upper": indicators.get("bollinger_upper"),
                "bollinger_mid": indicators.get("bollinger_mid"),
                "bollinger_lower": indicators.get("bollinger_lower"),
                "atr": indicators.get("atr"),
                "atr_percent": indicators.get("atr_percent"),
                "adx": indicators.get("adx"),
            },
            "patterns": patterns,
            "gap_detection": gaps,
            "consolidation_zones": consolidation,
            "accumulation_distribution": accumulation,
            "divergences": divergences,
            "breakout_probability": breakout_probability,
            "pullback_quality": pullback,
            "trend_strength_score": trend_strength,
            "risk_reward_estimate": risk_reward,
            "signals": signals,
            "technical_summary": report,
            "evidence_policy": {
                "calculated_data": ["OHLCV-derived indicators", "support/resistance", "volatility", "volume", "risk/reward"],
                "inference": ["trend quality", "breakout probability", "pullback quality", "pattern labels"],
                "uncertainty": ["technical analysis is probabilistic", "levels are zones, not exact guarantees"],
            },
            "warning": "This is technical analysis, not financial advice.",
        }


def normalize_frame(price_frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if price_frame is None or price_frame.empty:
        return pd.DataFrame()
    df = price_frame.sort_values("date").copy()
    for column in ["open", "high", "low", "close"]:
        if column not in df:
            df[column] = df["close"]
    if "volume" not in df:
        df["volume"] = 0.0
    df = df.dropna(subset=["close"])
    limit = TIMEFRAME_LIMITS.get(timeframe.upper(), 150)
    if timeframe.upper() == "YTD":
        dates = pd.to_datetime(df["date"])
        current_year = dates.iloc[-1].year
        ytd = df[dates.dt.year == current_year]
        return ytd.tail(limit) if len(ytd) >= 20 else df.tail(limit)
    return df.tail(limit)


def insufficient_analysis(timeframe: str, rows: int) -> dict:
    return {
        "status": "insufficient_price_history",
        "generated_at": datetime.utcnow().isoformat(),
        "timeframe": timeframe,
        "observed_rows": rows,
        "confidence": 0,
        "technical_summary": "Not enough stored OHLCV rows to produce a professional technical analysis.",
        "warning": "This is technical analysis, not financial advice.",
    }


def moving_averages(close: pd.Series) -> dict:
    def ema(span: int) -> float | None:
        return round(float(close.ewm(span=span, adjust=False).mean().iloc[-1]), 4) if len(close) >= max(3, span // 3) else None

    def sma(window: int) -> float | None:
        if len(close) < window:
            return round(float(close.mean()), 4)
        return round(float(close.rolling(window).mean().iloc[-1]), 4)

    last = float(close.iloc[-1])
    values = {
        "ema9": ema(9),
        "ema21": ema(21),
        "ema50": ema(50),
        "ema200": ema(200),
        "sma20": sma(20),
        "sma50": sma(50),
        "sma200": sma(200),
    }
    values["price_vs_ema21_pct"] = pct(values["ema21"], last) if values["ema21"] else None
    values["price_vs_sma50_pct"] = pct(values["sma50"], last) if values["sma50"] else None
    values["alignment"] = ma_alignment(last, values)
    return values


def ma_alignment(last: float, ma: dict) -> str:
    ema9 = ma.get("ema9") or last
    ema21 = ma.get("ema21") or last
    ema50 = ma.get("ema50") or last
    sma200 = ma.get("sma200") or last
    if last > ema9 > ema21 > ema50 > sma200:
        return "bullish_stack"
    if last < ema9 < ema21 < ema50 < sma200:
        return "bearish_stack"
    if last > ema21 and ema21 > ema50:
        return "constructive"
    if last < ema21 and ema21 < ema50:
        return "deteriorating"
    return "mixed"


def pivot_points(df: pd.DataFrame, window: int = 3) -> dict:
    highs = []
    lows = []
    high = df["high"].astype(float).reset_index(drop=True)
    low = df["low"].astype(float).reset_index(drop=True)
    dates = df["date"].reset_index(drop=True)
    for index in range(window, len(df) - window):
        h = high.iloc[index]
        l = low.iloc[index]
        if h >= high.iloc[index - window : index + window + 1].max():
            highs.append({"index": index, "date": str(dates.iloc[index]), "price": round(float(h), 4)})
        if l <= low.iloc[index - window : index + window + 1].min():
            lows.append({"index": index, "date": str(dates.iloc[index]), "price": round(float(l), 4)})
    return {"highs": highs[-10:], "lows": lows[-10:]}


def key_levels(df: pd.DataFrame, pivots: dict) -> dict:
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    last = float(close.iloc[-1])
    pivot_supports = [item["price"] for item in pivots["lows"] if item["price"] <= last * 1.03]
    pivot_resistances = [item["price"] for item in pivots["highs"] if item["price"] >= last * 0.97]
    supports = sorted(set(round(float(value), 4) for value in pivot_supports + [low.tail(20).min(), close.tail(60).quantile(0.18)] if value < last), reverse=True)[:4]
    resistances = sorted(set(round(float(value), 4) for value in pivot_resistances + [high.tail(20).max(), close.tail(60).quantile(0.82)] if value > last))[:4]
    if not supports:
        supports = [round(float(low.tail(30).min()), 4)]
    if not resistances:
        resistances = [round(float(high.tail(30).max()), 4)]
    return {
        "support_levels": [{"level": value, "distance_pct": round(pct(last, value), 2), "source": "pivot_or_distribution"} for value in supports],
        "resistance_levels": [{"level": value, "distance_pct": round(pct(last, value), 2), "source": "pivot_or_distribution"} for value in resistances],
        "breakout_level": resistances[0] if resistances else None,
        "breakdown_level": supports[0] if supports else None,
        "invalidation_level": supports[0] if supports else None,
        "nearest_support": supports[0] if supports else None,
        "nearest_resistance": resistances[0] if resistances else None,
    }


def trend_structure(df: pd.DataFrame, pivots: dict, ma: dict, indicators: dict) -> dict:
    highs = pivots["highs"]
    lows = pivots["lows"]
    higher_highs = count_progression(highs, "up")
    lower_highs = count_progression(highs, "down")
    higher_lows = count_progression(lows, "up")
    lower_lows = count_progression(lows, "down")
    close = df["close"].astype(float)
    slope_20 = series_slope(close.tail(min(40, len(close))))
    alignment = ma.get("alignment", "mixed")
    if higher_highs >= 2 and higher_lows >= 2 and alignment in {"bullish_stack", "constructive"}:
        direction = "uptrend"
    elif lower_highs >= 2 and lower_lows >= 2 and alignment in {"bearish_stack", "deteriorating"}:
        direction = "downtrend"
    elif abs(slope_20) < 0.08:
        direction = "range_or_consolidation"
    elif slope_20 > 0:
        direction = "uptrend_attempt"
    else:
        direction = "downtrend_attempt"
    return {
        "trend_direction": direction,
        "higher_highs": higher_highs,
        "higher_lows": higher_lows,
        "lower_highs": lower_highs,
        "lower_lows": lower_lows,
        "slope_20": round(slope_20, 4),
        "ma_alignment": alignment,
        "adx": indicators.get("adx"),
        "structure_comment": structure_comment(direction, higher_highs, higher_lows, lower_highs, lower_lows),
    }


def momentum_block(close: pd.Series, indicators: dict) -> dict:
    rsi = float(indicators.get("rsi") or 50)
    macd_hist = float(indicators.get("macd_hist") or 0)
    perf_5d = float(indicators.get("perf_5d") or 0)
    perf_1m = float(indicators.get("perf_1m") or 0)
    state = "neutral"
    if rsi >= 58 and macd_hist > 0 and perf_5d > 0:
        state = "improving"
    if rsi >= 68:
        state = "extended_positive"
    if rsi <= 42 and macd_hist < 0:
        state = "weakening"
    if rsi <= 32:
        state = "oversold"
    return {
        "state": state,
        "rsi": round(rsi, 2),
        "macd_hist": round(macd_hist, 4),
        "perf_5d": round(perf_5d, 3),
        "perf_1m": round(perf_1m, 3),
        "rate_of_change_20": round(return_pct(close, min(20, len(close) - 1)), 3),
    }


def volume_analysis(volume: pd.Series, close: pd.Series) -> dict:
    recent = volume.tail(10)
    baseline = volume.tail(60).iloc[:-10] if len(volume) > 20 else volume
    baseline_mean = float(baseline.mean()) if len(baseline) else 0.0
    rel = float(recent.mean() / baseline_mean) if baseline_mean else 0.0
    up_volume = volume[close.diff() > 0].tail(30).sum()
    down_volume = volume[close.diff() < 0].tail(30).sum()
    pressure = "balanced"
    if up_volume > down_volume * 1.2:
        pressure = "accumulation_bias"
    if down_volume > up_volume * 1.2:
        pressure = "distribution_bias"
    return {
        "relative_volume": round(rel, 3),
        "volume_state": "expanding" if rel >= 1.25 else "contracting" if rel <= 0.75 else "normal",
        "up_down_volume_pressure": pressure,
        "latest_volume": round(float(volume.iloc[-1]), 2) if len(volume) else 0,
        "average_volume_50": round(float(volume.tail(50).mean()), 2) if len(volume) else 0,
    }


def volatility_block(df: pd.DataFrame, indicators: dict) -> dict:
    close = df["close"].astype(float)
    returns = close.pct_change().dropna()
    realized = float(returns.tail(30).std() * math.sqrt(252) * 100) if len(returns) > 5 else 0.0
    atr_pct = float(indicators.get("atr_percent") or 0)
    bb_upper = float(indicators.get("bollinger_upper") or 0)
    bb_lower = float(indicators.get("bollinger_lower") or 0)
    last = float(close.iloc[-1])
    bb_width = ((bb_upper - bb_lower) / last * 100) if last and bb_upper and bb_lower else 0.0
    historical_width = (close.rolling(20).std() / close.rolling(20).mean() * 100).dropna()
    compression = bool(len(historical_width) and bb_width <= historical_width.tail(120).quantile(0.25))
    regime = "normal"
    if realized > 45 or atr_pct > 5:
        regime = "high"
    elif realized < 18 and atr_pct < 2.5:
        regime = "low"
    return {
        "regime": regime,
        "realized_volatility_30d": round(realized, 3),
        "atr_percent": round(atr_pct, 3),
        "bollinger_width_pct": round(bb_width, 3),
        "volatility_compression": compression,
    }


def pattern_detection(df: pd.DataFrame, pivots: dict, ma: dict, levels: dict, volatility: dict, volume: dict) -> list[dict]:
    close = df["close"].astype(float)
    last = float(close.iloc[-1])
    patterns = []
    if volatility["volatility_compression"]:
        patterns.append({"pattern": "volatility_compression", "direction": "neutral", "confidence": 66, "evidence": "Bollinger width is in the lower historical quartile."})
    if levels.get("breakout_level") and last > float(levels["breakout_level"]) * 0.995 and volume["relative_volume"] >= 1.1:
        patterns.append({"pattern": "breakout_test", "direction": "bullish", "confidence": 62, "evidence": "Price is pressing against nearest resistance with volume support."})
    if levels.get("breakdown_level") and last < float(levels["breakdown_level"]) * 1.005:
        patterns.append({"pattern": "support_test", "direction": "bearish", "confidence": 58, "evidence": "Price is testing nearest support; failure would weaken structure."})
    if ma.get("alignment") == "bullish_stack":
        patterns.append({"pattern": "moving_average_bullish_stack", "direction": "bullish", "confidence": 72, "evidence": "Price and moving averages are stacked in constructive order."})
    if ma.get("alignment") == "bearish_stack":
        patterns.append({"pattern": "moving_average_bearish_stack", "direction": "bearish", "confidence": 72, "evidence": "Price and moving averages are stacked in deteriorating order."})
    if not patterns:
        patterns.append({"pattern": "mixed_structure", "direction": "neutral", "confidence": 50, "evidence": "No dominant continuation or reversal pattern is statistically clear."})
    return patterns


def divergence_detection(df: pd.DataFrame, indicators: dict) -> dict:
    close = df["close"].astype(float)
    rsi_series = rsi_series_calc(close)
    macd_hist = macd_hist_series(close)
    price_lookback = close.tail(40)
    bullish_rsi = bool(price_lookback.iloc[-1] <= price_lookback.quantile(0.35) and rsi_series.tail(40).iloc[-1] > rsi_series.tail(40).quantile(0.45))
    bearish_rsi = bool(price_lookback.iloc[-1] >= price_lookback.quantile(0.65) and rsi_series.tail(40).iloc[-1] < rsi_series.tail(40).quantile(0.55))
    bullish_macd = bool(price_lookback.iloc[-1] <= price_lookback.quantile(0.35) and macd_hist.tail(40).iloc[-1] > macd_hist.tail(40).quantile(0.45))
    bearish_macd = bool(price_lookback.iloc[-1] >= price_lookback.quantile(0.65) and macd_hist.tail(40).iloc[-1] < macd_hist.tail(40).quantile(0.55))
    return {
        "price_rsi": "bullish_divergence" if bullish_rsi else "bearish_divergence" if bearish_rsi else "none_detected",
        "price_macd": "bullish_divergence" if bullish_macd else "bearish_divergence" if bearish_macd else "none_detected",
        "notes": "Divergence is inferred from recent quantile behavior and should be confirmed with price action.",
    }


def gap_detection(open_: pd.Series, close: pd.Series, high: pd.Series, low: pd.Series) -> dict:
    if len(open_) < 3:
        return {"latest_gap_pct": 0, "gap_type": "insufficient_history"}
    latest_gap = (float(open_.iloc[-1]) / float(close.iloc[-2]) - 1) * 100 if close.iloc[-2] else 0
    gap_type = "none"
    if latest_gap > 1.5:
        gap_type = "gap_up"
    elif latest_gap < -1.5:
        gap_type = "gap_down"
    filled = bool(low.iloc[-1] <= close.iloc[-2] <= high.iloc[-1])
    return {"latest_gap_pct": round(latest_gap, 3), "gap_type": gap_type, "gap_filled_intraday": filled}


def consolidation_zones(df: pd.DataFrame, volatility: dict) -> list[dict]:
    close = df["close"].astype(float)
    zones = []
    for window in [20, 40, 60]:
        if len(close) < window:
            continue
        sample = close.tail(window)
        width = (sample.max() / sample.min() - 1) * 100 if sample.min() else 0
        if width <= max(8, volatility.get("atr_percent", 2) * 4):
            zones.append({"window": window, "low": round(float(sample.min()), 4), "high": round(float(sample.max()), 4), "width_pct": round(width, 3)})
    return zones[:3]


def accumulation_distribution(df: pd.DataFrame) -> dict:
    close = df["close"].astype(float)
    volume = df["volume"].fillna(0).astype(float)
    money_flow = ((close - close.shift()) * volume).tail(30).sum()
    total_volume = volume.tail(30).sum() or 1
    score = float(money_flow / total_volume)
    state = "balanced"
    if score > 0:
        state = "accumulation_bias"
    if score < 0:
        state = "distribution_bias"
    return {"state": state, "pressure_score": round(score, 4)}


def risk_reward_estimate(last: float, levels: dict, volatility: dict, structure: dict) -> dict:
    support = levels.get("nearest_support")
    resistance = levels.get("nearest_resistance")
    downside = abs(pct(last, support)) if support else None
    upside = abs(pct(last, resistance)) if resistance else None
    ratio = round((upside / downside), 2) if upside is not None and downside and downside > 0 else None
    label = "unbalanced"
    if ratio is not None and ratio >= 1.8:
        label = "favorable"
    elif ratio is not None and ratio >= 1.0:
        label = "balanced"
    if volatility["regime"] == "high":
        label = f"{label}_high_volatility"
    return {
        "nearest_support": support,
        "nearest_resistance": resistance,
        "downside_to_support_pct": round(downside, 3) if downside is not None else None,
        "upside_to_resistance_pct": round(upside, 3) if upside is not None else None,
        "reward_to_risk": ratio,
        "label": label,
    }


def breakout_probability_score(structure: dict, momentum: dict, volume: dict, volatility: dict, levels: dict, last: float) -> dict:
    score = 45.0
    if structure["trend_direction"] in {"uptrend", "uptrend_attempt"}:
        score += 14
    if momentum["state"] in {"improving", "extended_positive"}:
        score += 12
    if volume["volume_state"] == "expanding":
        score += 10
    if volatility["volatility_compression"]:
        score += 8
    resistance = levels.get("nearest_resistance")
    if resistance:
        distance = abs(pct(last, resistance))
        if distance <= 3:
            score += 6
        elif distance > 12:
            score -= 8
    if momentum["state"] == "extended_positive":
        score -= 5
    return {"score": round(max(0, min(100, score)), 1), "method": "weighted trend, momentum, volume, volatility and distance-to-resistance model"}


def pullback_quality(close: pd.Series, ma: dict, levels: dict, indicators: dict) -> dict:
    last = float(close.iloc[-1])
    ema21 = ma.get("ema21")
    support = levels.get("nearest_support")
    rsi = float(indicators.get("rsi") or 50)
    quality = 50.0
    if ema21 and abs(pct(last, ema21)) <= 3:
        quality += 18
    if support and abs(pct(last, support)) <= 4:
        quality += 14
    if 38 <= rsi <= 58:
        quality += 12
    if rsi > 70:
        quality -= 18
    return {"score": round(max(0, min(100, quality)), 1), "comment": "Higher score means pullback is closer to logical support without excessive momentum damage."}


def trend_strength_score(structure: dict, momentum: dict, volatility: dict, volume: dict, ma: dict) -> float:
    score = 45.0
    if structure["trend_direction"] == "uptrend":
        score += 22
    elif structure["trend_direction"] == "downtrend":
        score -= 18
    elif structure["trend_direction"] in {"uptrend_attempt", "downtrend_attempt"}:
        score += 4
    if ma.get("alignment") == "bullish_stack":
        score += 16
    if ma.get("alignment") == "bearish_stack":
        score -= 16
    if momentum["state"] == "improving":
        score += 10
    if volume["volume_state"] == "expanding":
        score += 5
    if volatility["regime"] == "high":
        score -= 8
    return round(max(0, min(100, score)), 1)


def technical_signals(structure: dict, momentum: dict, volume: dict, volatility: dict, patterns: list[dict], divergences: dict, breakout_probability: dict, risk_reward: dict) -> list[dict]:
    signals = []
    if breakout_probability["score"] >= 70:
        signals.append({"signal_type": "breakout_watch", "direction": "bullish", "confidence": breakout_probability["score"], "evidence": "Trend, momentum, volume or compression support a breakout watch."})
    if structure["trend_direction"] in {"downtrend", "downtrend_attempt"} and momentum["state"] in {"weakening", "oversold"}:
        signals.append({"signal_type": "downtrend_pressure", "direction": "bearish", "confidence": 68, "evidence": "Structure and momentum remain weak."})
    if volatility["volatility_compression"]:
        signals.append({"signal_type": "volatility_compression", "direction": "neutral", "confidence": 64, "evidence": "Compressed volatility can precede directional expansion."})
    if divergences["price_rsi"] != "none_detected" or divergences["price_macd"] != "none_detected":
        direction = "bullish" if "bullish" in (divergences["price_rsi"] + divergences["price_macd"]) else "bearish"
        signals.append({"signal_type": "momentum_divergence", "direction": direction, "confidence": 58, "evidence": f"RSI/MACD divergence state: {divergences['price_rsi']} / {divergences['price_macd']}."})
    if risk_reward.get("label", "").startswith("favorable"):
        signals.append({"signal_type": "favorable_risk_reward_zone", "direction": "neutral", "confidence": 60, "evidence": "Nearest support/resistance geometry is favorable, pending confirmation."})
    if not signals:
        strongest = max(patterns, key=lambda item: item.get("confidence", 0))
        signals.append({"signal_type": strongest["pattern"], "direction": strongest["direction"], "confidence": strongest["confidence"], "evidence": strongest["evidence"]})
    return signals


def analyst_summary(structure: dict, momentum: dict, volume: dict, volatility: dict, levels: dict, signals: list[dict], breakout_probability: dict, risk_reward: dict) -> str:
    support = levels.get("nearest_support")
    resistance = levels.get("nearest_resistance")
    return (
        f"Blum detects a {structure['trend_direction'].replace('_', ' ')} with {momentum['state'].replace('_', ' ')} momentum. "
        f"Nearest support is near {support if support is not None else 'n/a'} and resistance is near {resistance if resistance is not None else 'n/a'}. "
        f"Volume is {volume['volume_state']} with {volume['up_down_volume_pressure'].replace('_', ' ')}. "
        f"Volatility regime is {volatility['regime']} and breakout probability is {breakout_probability['score']:.1f}/100. "
        f"Risk/reward is {risk_reward.get('label', 'not rated').replace('_', ' ')}. "
        f"Primary signal: {signals[0]['signal_type'].replace('_', ' ')}."
    )


def structure_comment(direction: str, higher_highs: int, higher_lows: int, lower_highs: int, lower_lows: int) -> str:
    return (
        f"Structure classified as {direction}. Recent pivots show {higher_highs} higher highs, "
        f"{higher_lows} higher lows, {lower_highs} lower highs and {lower_lows} lower lows."
    )


def count_progression(items: list[dict], direction: str) -> int:
    count = 0
    for previous, current in zip(items[-5:], items[-4:]):
        if direction == "up" and current["price"] > previous["price"]:
            count += 1
        if direction == "down" and current["price"] < previous["price"]:
            count += 1
    return count


def rsi_series_calc(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = -delta.clip(upper=0).rolling(window).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)


def macd_hist_series(close: pd.Series) -> pd.Series:
    fast = close.ewm(span=12, adjust=False).mean()
    slow = close.ewm(span=26, adjust=False).mean()
    line = fast - slow
    signal = line.ewm(span=9, adjust=False).mean()
    return (line - signal).fillna(0)


def series_slope(series: pd.Series) -> float:
    if len(series) < 3:
        return 0.0
    y = series.astype(float).values
    x = np.arange(len(y))
    return float(np.polyfit(x, y, 1)[0] / max(abs(y[-1]), 1e-9) * 100)


def return_pct(close: pd.Series, periods: int) -> float:
    if len(close) <= periods or periods <= 0:
        return 0.0
    base = float(close.iloc[-periods - 1])
    return (float(close.iloc[-1]) / base - 1) * 100 if base else 0.0


def pct(start: float | None, end: float | None) -> float:
    if start is None or end is None or not start:
        return 0.0
    return (float(end) / float(start) - 1) * 100
