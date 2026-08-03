from __future__ import annotations

import re

from app.models import Asset
from app.services.deterministic_execution.contracts import InstrumentSpec


_CRYPTO_MARKERS = ("BTC", "ETH", "USDT", "USDC", "CRYPTO")


class BlumInstrumentMapper:
    """Maps BLUM assets into stable execution identities without venue adapters."""

    def map_asset(self, asset: Asset) -> InstrumentSpec:
        asset_type = str(asset.asset_type or asset.category or "").strip().lower()
        ticker = str(asset.ticker or "").strip().upper()
        if self._is_crypto(ticker, asset_type):
            raise ValueError("crypto instruments are outside the BLUM execution-core scope")
        if self._is_forex(ticker, asset_type):
            base, quote = self._forex_currencies(ticker)
            symbol = f"{base}{quote}"
            precision = 3 if quote == "JPY" else 5
            return InstrumentSpec(
                instrument_id=f"{symbol}.BLUMFX",
                symbol=symbol,
                venue="BLUMFX",
                asset_class="forex",
                base_currency=base,
                quote_currency=quote,
                price_precision=precision,
                quantity_precision=0,
                tick_size=10 ** -precision,
                lot_size=1_000.0,
                account_mode="margin",
            )
        normalized_type = "etf" if asset_type == "etf" else "equity"
        symbol = re.sub(r"[^A-Z0-9.-]", "", ticker)
        if not symbol:
            raise ValueError("asset ticker is required")
        return InstrumentSpec(
            instrument_id=f"{symbol}.BLUMSIM",
            symbol=symbol,
            venue="BLUMSIM",
            asset_class=normalized_type,
            base_currency=None,
            quote_currency=str(asset.currency or "USD").upper(),
            price_precision=2,
            quantity_precision=4,
            tick_size=0.01,
            lot_size=0.0001,
            account_mode="cash",
        )

    @staticmethod
    def _is_crypto(ticker: str, asset_type: str) -> bool:
        if "crypto" in asset_type:
            return True
        return "-" in ticker and any(marker in ticker for marker in _CRYPTO_MARKERS)

    @staticmethod
    def _is_forex(ticker: str, asset_type: str) -> bool:
        if any(marker in asset_type for marker in ("forex", "fx", "currency")):
            return True
        compact = re.sub(r"[^A-Z]", "", ticker.replace("=X", ""))
        return ticker.endswith("=X") and len(compact) == 6

    @staticmethod
    def _forex_currencies(ticker: str) -> tuple[str, str]:
        compact = re.sub(r"[^A-Z]", "", ticker.replace("=X", ""))
        if len(compact) != 6:
            raise ValueError(f"invalid fiat Forex symbol: {ticker}")
        return compact[:3], compact[3:]

