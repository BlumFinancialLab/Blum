from __future__ import annotations

from typing import Protocol

import pandas as pd


class MarketDataProvider(Protocol):
    """Provider contract for public or premium market data adapters."""

    name: str

    def download_history(self, tickers: list[str], period: str = "2y", interval: str = "1d") -> dict[str, pd.DataFrame]:
        """Return OHLCV frames keyed by ticker. Providers must not fabricate missing prices."""
        ...

