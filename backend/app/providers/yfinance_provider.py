from __future__ import annotations

from datetime import date
import pandas as pd
import yfinance as yf


class YFinanceProvider:
    name = "yfinance"

    def download_history(self, tickers: list[str], period: str = "2y", interval: str = "1d") -> dict[str, pd.DataFrame]:
        if not tickers:
            return {}
        data = yf.download(
            tickers=" ".join(tickers),
            period=period,
            interval=interval,
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        if data is None or data.empty:
            return {}
        frames: dict[str, pd.DataFrame] = {}
        for ticker in tickers:
            try:
                frame = data[ticker].copy() if isinstance(data.columns, pd.MultiIndex) else data.copy()
                frame = frame[["Open", "High", "Low", "Close", "Volume"]].apply(pd.to_numeric, errors="coerce")
                frame = frame.dropna(subset=["Close"])
                if not frame.empty:
                    frames[ticker] = frame
            except Exception:
                continue
        return frames


def to_price_rows(asset_id: int, frame: pd.DataFrame, provider: str = "yfinance") -> list[dict]:
    rows: list[dict] = []
    for idx, row in frame.iterrows():
        point_date = pd.Timestamp(idx).date()
        if not isinstance(point_date, date):
            continue
        rows.append(
            {
                "asset_id": asset_id,
                "date": point_date,
                "open": _float_or_none(row.get("Open")),
                "high": _float_or_none(row.get("High")),
                "low": _float_or_none(row.get("Low")),
                "close": float(row.get("Close")),
                "volume": _float_or_none(row.get("Volume")),
                "provider": provider,
            }
        )
    return rows


def _float_or_none(value):
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None

