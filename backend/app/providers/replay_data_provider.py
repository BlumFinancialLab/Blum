from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import quote

import pandas as pd
import requests
import yfinance as yf

from app.providers.yfinance_provider import NasdaqHistoricalProvider, StooqProvider, provider_headers


REPLAY_TIMEFRAMES = frozenset({"1d", "15m", "5m", "1m"})


@dataclass(frozen=True)
class ReplayDataRequest:
    source_symbol: str
    normalized_symbol: str
    market: str
    timeframe: str
    start: datetime
    end: datetime


@dataclass
class ProviderBars:
    provider: str
    frame: pd.DataFrame = field(default_factory=pd.DataFrame)
    source_metadata: dict = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)


class ReplayDataProvider(Protocol):
    name: str
    supported_timeframes: frozenset[str]
    source_metadata: dict

    def fetch(self, request: ReplayDataRequest) -> ProviderBars: ...


class YahooReplayDataProvider:
    name = "yahoo_chart"
    supported_timeframes = REPLAY_TIMEFRAMES
    source_metadata = {
        "source": "Yahoo Finance chart API",
        "license": "Public endpoint; downstream use remains subject to provider terms.",
        "intraday_retention": "Provider-defined and potentially shorter than the requested range.",
    }

    def fetch(self, request: ReplayDataRequest) -> ProviderBars:
        if request.timeframe not in self.supported_timeframes:
            return ProviderBars(self.name, source_metadata=self.source_metadata, blockers=["UNSUPPORTED_TIMEFRAME"])
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(request.source_symbol)}"
        params = {
            "period1": int(_as_utc(request.start).timestamp()),
            "period2": int(_as_utc(request.end).timestamp()) + 1,
            "interval": request.timeframe,
            "includePrePost": "false",
            "events": "div,splits",
        }
        try:
            response = requests.get(url, params=params, headers=provider_headers(), timeout=12)
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return ProviderBars(self.name, source_metadata=self.source_metadata, blockers=["PROVIDER_UNAVAILABLE"])
        result = payload.get("chart", {}).get("result") or []
        if not result:
            error = payload.get("chart", {}).get("error") or {}
            blocker = "NO_INTRADAY_HISTORY" if request.timeframe != "1d" else "COVERAGE_INCOMPLETE"
            metadata = {**self.source_metadata, "provider_error": error}
            return ProviderBars(self.name, source_metadata=metadata, blockers=[blocker])
        data = result[0]
        timestamps = data.get("timestamp") or []
        quotes = (data.get("indicators", {}).get("quote") or [{}])[0]
        if not timestamps or not quotes:
            return ProviderBars(self.name, source_metadata=self.source_metadata, blockers=["COVERAGE_INCOMPLETE"])
        frame = pd.DataFrame(
            {
                "Open": quotes.get("open", []),
                "High": quotes.get("high", []),
                "Low": quotes.get("low", []),
                "Close": quotes.get("close", []),
                "Volume": quotes.get("volume", []),
            },
            index=pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(None),
        )
        return ProviderBars(self.name, normalize_replay_frame(frame), self.source_metadata, [])


class YFinanceReplayDataProvider:
    name = "yfinance"
    supported_timeframes = REPLAY_TIMEFRAMES
    source_metadata = {
        "source": "yfinance",
        "license": "Open-source adapter; underlying market data remains subject to source terms.",
    }

    def fetch(self, request: ReplayDataRequest) -> ProviderBars:
        try:
            frame = yf.download(
                request.source_symbol,
                start=request.start,
                end=request.end,
                interval=request.timeframe,
                auto_adjust=True,
                progress=False,
                threads=False,
            )
        except Exception:
            return ProviderBars(self.name, source_metadata=self.source_metadata, blockers=["PROVIDER_UNAVAILABLE"])
        if frame is None or frame.empty:
            blocker = "NO_INTRADAY_HISTORY" if request.timeframe != "1d" else "COVERAGE_INCOMPLETE"
            return ProviderBars(self.name, source_metadata=self.source_metadata, blockers=[blocker])
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)
        return ProviderBars(self.name, normalize_replay_frame(frame), self.source_metadata, [])


class DailyProviderReplayAdapter:
    supported_timeframes = frozenset({"1d"})

    def __init__(self, provider):
        self.provider = provider
        self.name = provider.name
        self.source_metadata = {
            "source": provider.name,
            "license": "Public daily history; use subject to source terms.",
        }

    def fetch(self, request: ReplayDataRequest) -> ProviderBars:
        if request.timeframe != "1d":
            return ProviderBars(self.name, source_metadata=self.source_metadata, blockers=["UNSUPPORTED_TIMEFRAME"])
        years = max(1, int((request.end - request.start).days / 365.25) + 1)
        try:
            frames = self.provider.download_history([request.source_symbol], period=f"{years}y", interval="1d")
        except Exception:
            return ProviderBars(self.name, source_metadata=self.source_metadata, blockers=["PROVIDER_UNAVAILABLE"])
        frame = frames.get(request.source_symbol)
        if frame is None or frame.empty:
            return ProviderBars(self.name, source_metadata=self.source_metadata, blockers=["COVERAGE_INCOMPLETE"])
        normalized = normalize_replay_frame(frame)
        mask = (normalized.index >= _naive_utc(request.start)) & (normalized.index <= _naive_utc(request.end))
        return ProviderBars(self.name, normalized.loc[mask], self.source_metadata, [])


def default_replay_providers(*, include_yfinance: bool = True) -> list[ReplayDataProvider]:
    providers: list[ReplayDataProvider] = [YahooReplayDataProvider()]
    if include_yfinance:
        providers.append(YFinanceReplayDataProvider())
    providers.extend([DailyProviderReplayAdapter(StooqProvider()), DailyProviderReplayAdapter(NasdaqHistoricalProvider())])
    return providers


def normalize_replay_frame(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    required = ["Open", "High", "Low", "Close", "Volume"]
    for column in required:
        if column not in output:
            output[column] = None
    output = output[required].apply(pd.to_numeric, errors="coerce")
    output = output.dropna(subset=["Close"])
    index = pd.to_datetime(output.index, errors="coerce", utc=True)
    output.index = index.tz_convert(None)
    output = output[~output.index.isna()]
    output = output[~output.index.duplicated(keep="last")].sort_index()
    invalid = (
        (output["High"].notna() & output["Low"].notna() & (output["High"] < output["Low"]))
        | (output["Open"].notna() & output["High"].notna() & (output["Open"] > output["High"]))
        | (output["Close"].notna() & output["Low"].notna() & (output["Close"] < output["Low"]))
    )
    return output.loc[~invalid]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _naive_utc(value: datetime) -> datetime:
    return _as_utc(value).replace(tzinfo=None)
