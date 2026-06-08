from __future__ import annotations

from datetime import datetime
import pandas as pd
from sqlalchemy.orm import Session

from sqlalchemy import select

from app.models import Asset, BacktestResult
from app.signals.engine import load_prices


def run_simple_backtest(db: Session, asset_id: int, ticker: str, benchmark: str = "SPY") -> dict:
    prices = load_prices(db, asset_id)
    if prices.empty or len(prices) < 260:
        return {"ticker": ticker, "status": "insufficient_history"}
    prices = prices.sort_values("date").reset_index(drop=True)
    close = prices["close"].astype(float)
    benchmark_asset = db.scalar(select(Asset).where(Asset.ticker == benchmark))
    benchmark_prices = load_prices(db, benchmark_asset.id).sort_values("date").reset_index(drop=True) if benchmark_asset else pd.DataFrame()
    benchmark_by_date = dict(zip(benchmark_prices["date"], benchmark_prices["close"].astype(float))) if not benchmark_prices.empty else {}
    momentum = close.pct_change(21)
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    signals = (momentum > 0.04) & (sma50 > sma200)
    rows = []
    for idx in range(220, len(prices) - 60):
        if not bool(signals.iloc[idx]):
            continue
        entry = close.iloc[idx]
        forward = close.iloc[idx + 1 : idx + 61]
        current_date = prices["date"].iloc[idx]
        row = {
            "date": str(current_date),
            "forward_return_5d": pct(entry, close.iloc[idx + 5]) if idx + 5 < len(close) else None,
            "forward_return_20d": pct(entry, close.iloc[idx + 20]) if idx + 20 < len(close) else None,
            "forward_return_60d": pct(entry, close.iloc[idx + 60]) if idx + 60 < len(close) else None,
            "max_adverse_excursion": pct(entry, forward.min()),
            "max_favorable_excursion": pct(entry, forward.max()),
        }
        row.update(benchmark_forward(prices, benchmark_by_date, idx, current_date))
        rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        metrics = {"signal_count": 0, "hit_rate_20d": 0, "average_forward_return_20d": 0}
    else:
        metrics = {
            "signal_count": int(len(frame)),
            "hit_rate_5d": round(float((frame["forward_return_5d"] > 0).mean()), 4),
            "hit_rate_20d": round(float((frame["forward_return_20d"] > 0).mean()), 4),
            "hit_rate_60d": round(float((frame["forward_return_60d"] > 0).mean()), 4),
            "average_forward_return_5d": round(float(frame["forward_return_5d"].mean()), 4),
            "average_forward_return_20d": round(float(frame["forward_return_20d"].mean()), 4),
            "average_forward_return_60d": round(float(frame["forward_return_60d"].mean()), 4),
            "average_excess_return_20d": round(float(frame["excess_return_20d"].dropna().mean()), 4) if "excess_return_20d" in frame else None,
            "max_adverse_excursion": round(float(frame["max_adverse_excursion"].min()), 4),
            "max_favorable_excursion": round(float(frame["max_favorable_excursion"].max()), 4),
            "false_positive_rate_20d": round(float((frame["forward_return_20d"] <= 0).mean()), 4),
        }
    result = {
        "ticker": ticker,
        "benchmark": benchmark,
        "method": "Momentum > 4% over 1M and SMA50 above SMA200",
        "metrics": metrics,
        "best_signals": frame.sort_values("forward_return_20d", ascending=False).head(5).to_dict("records") if not frame.empty else [],
        "worst_signals": frame.sort_values("forward_return_20d", ascending=True).head(5).to_dict("records") if not frame.empty else [],
        "disclaimer": "Backtest validates historical signal behavior only. It does not predict or guarantee future returns.",
    }
    db.add(BacktestResult(run_name=f"{ticker} simple validation", benchmark=benchmark, parameters={"ticker": ticker}, metrics=metrics, results=result))
    db.commit()
    return result


def pct(entry: float, exit_value: float) -> float:
    if entry == 0:
        return 0.0
    return round((float(exit_value) / float(entry) - 1) * 100, 4)


def benchmark_forward(prices: pd.DataFrame, benchmark_by_date: dict, idx: int, current_date) -> dict:
    start = benchmark_by_date.get(current_date)
    if start is None:
        return {"benchmark_return_20d": None, "excess_return_20d": None}
    forward_date = prices["date"].iloc[idx + 20] if idx + 20 < len(prices) else None
    end = benchmark_by_date.get(forward_date)
    if end is None:
        return {"benchmark_return_20d": None, "excess_return_20d": None}
    benchmark_return = pct(start, end)
    asset_return = pct(float(prices["close"].iloc[idx]), float(prices["close"].iloc[idx + 20]))
    return {"benchmark_return_20d": benchmark_return, "excess_return_20d": round(asset_return - benchmark_return, 4)}
