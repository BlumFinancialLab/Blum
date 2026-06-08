from __future__ import annotations

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller


class TimeSeriesIntelligence:
    """Model-compatible time-series layer.

    The interface is ready for Chronos, TimesFM or PatchTST. The demo fallback uses
    transparent statistical methods for anomalies, volatility regimes and scenarios.
    """

    model_name = "statistical-fallback"

    def analyze(self, prices: pd.DataFrame) -> dict:
        if prices is None or prices.empty or "close" not in prices:
            return {"regime": "unknown", "anomaly_score": 0, "scenarios": []}
        close = prices["close"].astype(float).dropna()
        returns = close.pct_change().dropna()
        if len(returns) < 40:
            return {"regime": "insufficient_history", "anomaly_score": 0, "scenarios": []}
        z_return = zscore(returns.iloc[-1], returns.tail(252))
        realized_vol = returns.tail(20).std() * np.sqrt(252)
        long_vol = returns.tail(252).std() * np.sqrt(252)
        vol_ratio = float(realized_vol / long_vol) if long_vol else 1.0
        regime = "high_volatility" if vol_ratio > 1.35 else "low_volatility" if vol_ratio < 0.75 else "normal_volatility"
        try:
            stationarity_p = float(adfuller(close.tail(min(len(close), 252)))[1])
        except Exception:
            stationarity_p = 1.0
        anomaly_score = min(100, abs(z_return) * 28 + max(0, vol_ratio - 1) * 28)
        scenarios = scenario_pack(close, returns)
        return {
            "model_name": self.model_name,
            "regime": regime,
            "return_zscore": round(float(z_return), 3),
            "volatility_ratio": round(float(vol_ratio), 3),
            "stationarity_pvalue": round(stationarity_p, 4),
            "anomaly_score": round(float(anomaly_score), 1),
            "scenarios": scenarios,
        }


def zscore(value: float, series: pd.Series) -> float:
    std = float(series.std())
    if std == 0:
        return 0.0
    return (float(value) - float(series.mean())) / std


def scenario_pack(close: pd.Series, returns: pd.Series) -> list[dict]:
    recent = returns.tail(252)
    last = float(close.iloc[-1])
    vol = float(recent.std()) if len(recent) else 0.0
    drift = float(recent.mean()) if len(recent) else 0.0
    return [
        {"name": "base_path", "horizon_days": 20, "level": round(last * (1 + drift * 20), 2), "method": "rolling drift"},
        {"name": "upside_vol_band", "horizon_days": 20, "level": round(last * (1 + drift * 20 + vol * np.sqrt(20)), 2), "method": "one volatility band"},
        {"name": "downside_vol_band", "horizon_days": 20, "level": round(last * (1 + drift * 20 - vol * np.sqrt(20)), 2), "method": "one volatility band"},
    ]

