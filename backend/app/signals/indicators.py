from __future__ import annotations

import math
import numpy as np
import pandas as pd

try:
    import ta
except Exception:
    ta = None


def compute_indicators(price_frame: pd.DataFrame, benchmark_frame: pd.DataFrame | None = None) -> dict:
    if price_frame is None or price_frame.empty:
        return {}
    df = price_frame.sort_values("date").copy()
    close = df["close"].astype(float)
    high = df["high"].astype(float) if "high" in df else close
    low = df["low"].astype(float) if "low" in df else close
    volume = df["volume"].fillna(0).astype(float) if "volume" in df else pd.Series(index=df.index, data=0.0)
    returns = close.pct_change()
    last = float(close.iloc[-1])
    high_52w = float(close.tail(252).max()) if len(close) else last
    sma20 = rolling_mean(close, 20)
    sma50 = rolling_mean(close, 50)
    sma200 = rolling_mean(close, 200)
    ema21 = float(close.ewm(span=21).mean().iloc[-1])
    ema63 = float(close.ewm(span=63).mean().iloc[-1])
    rsi = rsi_value(close)
    macd_line, macd_signal, macd_hist = macd(close)
    bb_upper, bb_mid, bb_lower = bollinger(close)
    atr = atr_value(high, low, close)
    adx = adx_value(high, low, close)
    support = float(close.tail(60).quantile(0.18))
    resistance = float(close.tail(60).quantile(0.82))
    benchmark_return = relative_strength(close, benchmark_frame)
    return {
        "last": round(last, 4),
        "perf_1d": round(return_pct(close, 1), 4),
        "perf_5d": round(return_pct(close, 5), 4),
        "perf_1m": round(return_pct(close, 21), 4),
        "perf_3m": round(return_pct(close, 63), 4),
        "perf_6m": round(return_pct(close, 126), 4),
        "perf_ytd": round(ytd_return(df, close), 4),
        "distance_52w_high": round((last / high_52w - 1) * 100 if high_52w else 0, 4),
        "sma20": round(sma20, 4),
        "sma50": round(sma50, 4),
        "sma200": round(sma200, 4) if sma200 else None,
        "ema21": round(ema21, 4),
        "ema63": round(ema63, 4),
        "sma20_slope": round(slope(close.rolling(20).mean().dropna().tail(20)), 4),
        "sma50_slope": round(slope(close.rolling(50).mean().dropna().tail(30)), 4),
        "above_sma20": last > sma20 if sma20 else False,
        "above_sma50": last > sma50 if sma50 else False,
        "above_sma200": last > sma200 if sma200 else False,
        "relative_strength_vs_benchmark": round(benchmark_return, 4),
        "rsi": round(rsi, 3),
        "macd": round(macd_line, 4),
        "macd_signal": round(macd_signal, 4),
        "macd_hist": round(macd_hist, 4),
        "bollinger_upper": round(bb_upper, 4),
        "bollinger_mid": round(bb_mid, 4),
        "bollinger_lower": round(bb_lower, 4),
        "bollinger_position": round((last - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5, 4),
        "atr": round(atr, 4),
        "adx": round(adx, 3) if adx is not None else None,
        "historical_volatility": round(float(returns.tail(63).std() * math.sqrt(252) * 100), 4),
        "downside_volatility": round(float(returns[returns < 0].tail(126).std() * math.sqrt(252) * 100), 4),
        "max_drawdown": round(max_drawdown(close), 4),
        "recent_drawdown": round((last / close.tail(63).max() - 1) * 100, 4),
        "atr_percent": round((atr / last) * 100 if last else 0, 4),
        "volume_spike": round(volume_spike(volume), 4),
        "gap_anomaly": round(gap_anomaly(df), 4),
        "beta_vs_benchmark": round(beta_vs_benchmark(close, benchmark_frame), 4),
        "support": round(support, 4),
        "resistance": round(resistance, 4),
        "trend_persistence": round(trend_persistence(close), 4),
        "movement_stability": round(movement_stability(returns), 4),
    }


def rolling_mean(series: pd.Series, window: int) -> float:
    if len(series) < window:
        return float(series.mean())
    return float(series.rolling(window).mean().iloc[-1])


def return_pct(close: pd.Series, periods: int) -> float:
    if len(close) <= periods:
        return 0.0
    base = float(close.iloc[-periods - 1])
    if base == 0:
        return 0.0
    return (float(close.iloc[-1]) / base - 1) * 100


def ytd_return(df: pd.DataFrame, close: pd.Series) -> float:
    dates = pd.to_datetime(df["date"])
    current_year = dates.iloc[-1].year
    ytd = close[dates.dt.year == current_year]
    if len(ytd) < 2:
        return 0.0
    return (float(ytd.iloc[-1]) / float(ytd.iloc[0]) - 1) * 100


def slope(series: pd.Series) -> float:
    if len(series) < 3:
        return 0.0
    y = series.astype(float).values
    x = np.arange(len(y))
    return float(np.polyfit(x, y, 1)[0] / max(abs(y[-1]), 1e-9) * 100)


def rsi_value(close: pd.Series, window: int = 14) -> float:
    if ta is not None:
        try:
            return float(ta.momentum.RSIIndicator(close, window=window).rsi().iloc[-1])
        except Exception:
            pass
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = -delta.clip(upper=0).rolling(window).mean()
    rs = gain / loss.replace(0, np.nan)
    return float((100 - (100 / (1 + rs))).iloc[-1])


def macd(close: pd.Series) -> tuple[float, float, float]:
    fast = close.ewm(span=12).mean()
    slow = close.ewm(span=26).mean()
    line = fast - slow
    signal = line.ewm(span=9).mean()
    hist = line - signal
    return float(line.iloc[-1]), float(signal.iloc[-1]), float(hist.iloc[-1])


def bollinger(close: pd.Series, window: int = 20) -> tuple[float, float, float]:
    mid = close.rolling(window).mean()
    std = close.rolling(window).std()
    upper = mid + std * 2
    lower = mid - std * 2
    return float(upper.iloc[-1]), float(mid.iloc[-1]), float(lower.iloc[-1])


def atr_value(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> float:
    if ta is not None:
        try:
            return float(ta.volatility.AverageTrueRange(high, low, close, window=window).average_true_range().iloc[-1])
        except Exception:
            pass
    tr = pd.concat([(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    return float(tr.rolling(window).mean().iloc[-1])


def adx_value(high: pd.Series, low: pd.Series, close: pd.Series) -> float | None:
    if ta is None:
        return None
    try:
        return float(ta.trend.ADXIndicator(high, low, close).adx().iloc[-1])
    except Exception:
        return None


def max_drawdown(close: pd.Series) -> float:
    dd = close / close.cummax() - 1
    return float(dd.min() * 100)


def volume_spike(volume: pd.Series) -> float:
    if len(volume) < 30:
        return 0.0
    baseline = float(volume.tail(31).iloc[:-1].mean())
    if baseline == 0:
        return 0.0
    return (float(volume.iloc[-1]) / baseline - 1) * 100


def gap_anomaly(df: pd.DataFrame) -> float:
    if len(df) < 30 or "open" not in df:
        return 0.0
    gaps = (df["open"].astype(float) / df["close"].astype(float).shift(1) - 1).dropna()
    if gaps.empty or gaps.std() == 0:
        return 0.0
    return float(abs((gaps.iloc[-1] - gaps.mean()) / gaps.std()))


def beta_vs_benchmark(close: pd.Series, benchmark_frame: pd.DataFrame | None) -> float:
    if benchmark_frame is None or benchmark_frame.empty:
        return 1.0
    benchmark = benchmark_frame.sort_values("date")["close"].astype(float)
    paired = pd.concat([close.pct_change().rename("asset"), benchmark.pct_change().rename("benchmark")], axis=1).dropna()
    if len(paired) < 60 or paired["benchmark"].var() == 0:
        return 1.0
    return float(paired["asset"].cov(paired["benchmark"]) / paired["benchmark"].var())


def relative_strength(close: pd.Series, benchmark_frame: pd.DataFrame | None) -> float:
    if benchmark_frame is None or benchmark_frame.empty:
        return 0.0
    benchmark = benchmark_frame.sort_values("date")["close"].astype(float)
    asset_return = return_pct(close, min(126, len(close) - 1))
    benchmark_return = return_pct(benchmark, min(126, len(benchmark) - 1))
    return asset_return - benchmark_return


def trend_persistence(close: pd.Series) -> float:
    if len(close) < 40:
        return 0.0
    changes = close.diff().tail(40)
    dominant = max((changes > 0).mean(), (changes < 0).mean())
    return float(dominant * 100)


def movement_stability(returns: pd.Series) -> float:
    sample = returns.dropna().tail(63)
    if len(sample) < 20:
        return 50.0
    return float(max(0, 100 - sample.std() * math.sqrt(252) * 100))

