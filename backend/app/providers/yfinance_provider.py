from __future__ import annotations

from datetime import date
from io import StringIO
import time
from urllib.parse import quote

import pandas as pd
import requests
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


class YahooChartProvider:
    name = "yahoo_chart"

    def download_history(self, tickers: list[str], period: str = "2y", interval: str = "1d") -> dict[str, pd.DataFrame]:
        frames: dict[str, pd.DataFrame] = {}
        for ticker in tickers:
            try:
                frame = self._download_symbol(ticker, period=period, interval=interval)
            except Exception:
                continue
            if frame is not None and not frame.empty:
                frames[ticker] = frame
            time.sleep(0.08)
        return frames

    def _download_symbol(self, ticker: str, period: str, interval: str) -> pd.DataFrame:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker)}"
        params = {
            "range": yahoo_range(period),
            "interval": interval,
            "includePrePost": "false",
            "events": "div,splits",
        }
        response = requests.get(url, params=params, headers=provider_headers(), timeout=10)
        response.raise_for_status()
        payload = response.json()
        result = payload.get("chart", {}).get("result", [])
        if not result:
            return pd.DataFrame()
        data = result[0]
        timestamps = data.get("timestamp", [])
        quote_block = data.get("indicators", {}).get("quote", [{}])[0]
        if not timestamps or not quote_block:
            return pd.DataFrame()
        frame = pd.DataFrame(
            {
                "Open": quote_block.get("open", []),
                "High": quote_block.get("high", []),
                "Low": quote_block.get("low", []),
                "Close": quote_block.get("close", []),
                "Volume": quote_block.get("volume", []),
            },
            index=pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(None).normalize(),
        )
        return normalize_frame(frame)


class NasdaqHistoricalProvider:
    name = "nasdaq_api"

    def download_history(self, tickers: list[str], period: str = "2y", interval: str = "1d") -> dict[str, pd.DataFrame]:
        if interval != "1d":
            return {}
        frames: dict[str, pd.DataFrame] = {}
        for ticker in tickers:
            if "." in ticker:
                continue
            try:
                frame = self._download_symbol(ticker, period=period)
            except Exception:
                continue
            if frame is not None and not frame.empty:
                frames[ticker] = frame
            time.sleep(0.12)
        return frames

    def _download_symbol(self, ticker: str, period: str) -> pd.DataFrame:
        today = date.today()
        start = period_start_date(period, today)
        for asset_class in ("stocks", "etf"):
            url = f"https://api.nasdaq.com/api/quote/{quote(ticker)}/historical"
            params = {
                "assetclass": asset_class,
                "fromdate": start.isoformat(),
                "todate": today.isoformat(),
                "limit": "9999",
            }
            try:
                response = requests.get(url, params=params, headers=nasdaq_headers(), timeout=12)
                response.raise_for_status()
                rows = response.json().get("data", {}).get("tradesTable", {}).get("rows", [])
            except Exception:
                continue
            if not rows:
                continue
            records = []
            for row in rows:
                parsed_date = pd.to_datetime(row.get("date"), errors="coerce")
                close = parse_market_number(row.get("close"))
                if pd.isna(parsed_date) or close is None:
                    continue
                records.append(
                    {
                        "Date": parsed_date,
                        "Open": parse_market_number(row.get("open")),
                        "High": parse_market_number(row.get("high")),
                        "Low": parse_market_number(row.get("low")),
                        "Close": close,
                        "Volume": parse_market_number(row.get("volume")),
                    }
                )
            if not records:
                continue
            frame = pd.DataFrame(records).dropna(subset=["Date", "Close"]).set_index("Date")
            return normalize_frame(frame)
        return pd.DataFrame()


class StooqProvider:
    name = "stooq"

    def download_history(self, tickers: list[str], period: str = "2y", interval: str = "1d") -> dict[str, pd.DataFrame]:
        if interval != "1d":
            return {}
        frames: dict[str, pd.DataFrame] = {}
        for ticker in tickers:
            try:
                frame = self._download_symbol(ticker, period)
            except Exception:
                continue
            if frame is not None and not frame.empty:
                frames[ticker] = frame
            time.sleep(0.08)
        return frames

    def _download_symbol(self, ticker: str, period: str) -> pd.DataFrame:
        for candidate in stooq_candidates(ticker):
            for base_url in ("https://stooq.com", "https://stooq.pl"):
                url = f"{base_url}/q/d/l/?s={quote(candidate)}&i=d"
                try:
                    response = requests.get(url, headers=provider_headers(), timeout=12)
                except Exception:
                    continue
                if response.status_code >= 400 or not response.text or "No data" in response.text[:120]:
                    continue
                frame = pd.read_csv(StringIO(response.text))
                if frame.empty or "Date" not in frame or "Close" not in frame:
                    continue
                frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
                frame = frame.dropna(subset=["Date", "Close"]).set_index("Date")
                frame = frame.rename(columns={column: column.capitalize() for column in frame.columns})
                frame = normalize_frame(frame)
                if frame.empty:
                    continue
                return filter_period(frame, period)
        return pd.DataFrame()


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


def normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = ["Open", "High", "Low", "Close", "Volume"]
    for column in required:
        if column not in frame:
            frame[column] = None
    frame = frame[required].apply(pd.to_numeric, errors="coerce")
    frame = frame.dropna(subset=["Close"])
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    return frame


def yahoo_range(period: str) -> str:
    normalized = (period or "2y").lower()
    allowed = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}
    return normalized if normalized in allowed else "2y"


def period_to_days(period: str) -> int:
    normalized = (period or "2y").lower()
    if normalized.endswith("mo"):
        return max(60, int(normalized[:-2]) * 21)
    if normalized.endswith("y"):
        return max(252, int(normalized[:-1]) * 252)
    if normalized == "max":
        return 1260
    return 520


def period_start_date(period: str, today: date) -> date:
    normalized = (period or "2y").lower()
    if normalized == "max":
        return date(1990, 1, 1)
    days = period_to_days(normalized)
    return today - pd.Timedelta(days=int(days * 1.55)).to_pytimedelta()


def filter_period(frame: pd.DataFrame, period: str) -> pd.DataFrame:
    if (period or "").lower() == "max":
        return frame
    days = period_to_days(period)
    cutoff = pd.Timestamp.utcnow().tz_localize(None).normalize() - pd.Timedelta(days=int(days * 1.55))
    return frame[frame.index >= cutoff]


def stooq_candidates(ticker: str) -> list[str]:
    raw = ticker.lower()
    suffix_map = {
        ".pa": ".fr",
        ".de": ".de",
        ".mi": ".it",
        ".as": ".nl",
        ".sw": ".ch",
        ".l": ".uk",
    }
    candidates: list[str] = []
    if "." in raw:
        for source_suffix, stooq_suffix in suffix_map.items():
            if raw.endswith(source_suffix):
                candidates.append(raw[: -len(source_suffix)] + stooq_suffix)
        candidates.append(raw)
    else:
        candidates.append(f"{raw}.us")
        candidates.append(raw)
    return list(dict.fromkeys(candidates))


def provider_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    }


def nasdaq_headers() -> dict[str, str]:
    headers = provider_headers()
    headers.update(
        {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.nasdaq.com",
            "Referer": "https://www.nasdaq.com/",
        }
    )
    return headers


def parse_market_number(value) -> float | None:
    if value is None:
        return None
    cleaned = str(value).replace("$", "").replace(",", "").replace("%", "").strip()
    if cleaned in {"", "N/A", "NaN", "--"}:
        return None
    try:
        return float(cleaned)
    except Exception:
        return None
