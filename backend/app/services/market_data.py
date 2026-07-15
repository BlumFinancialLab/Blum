from __future__ import annotations

from datetime import datetime
from statistics import median

from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Asset, PriceHistory, PriceProviderCheck
from app.providers.yfinance_provider import NasdaqHistoricalProvider, StooqProvider, YahooChartProvider, YFinanceProvider, to_price_rows


class MarketDataService:
    def __init__(self):
        self.settings = get_settings()
        self.providers = [StooqProvider(), NasdaqHistoricalProvider(), YahooChartProvider()]
        if self.settings.enable_yfinance_fallback:
            self.providers.append(YFinanceProvider())

    def update_prices(
        self,
        db: Session,
        tickers: list[str] | None = None,
        period: str = "max",
        limit: int | None = None,
        provider_validation_limit: int | None = None,
    ) -> dict:
        limit = limit or self.settings.max_update_assets
        query = select(Asset).where(Asset.is_active.is_(True)).order_by(Asset.asset_type, Asset.ticker)
        if tickers:
            query = query.where(Asset.ticker.in_([ticker.upper() for ticker in tickers]))
        assets = db.scalars(query.limit(limit)).all()
        inserted = 0
        updated_assets = 0
        provider_report: list[dict] = []
        remaining = {asset.ticker: asset for asset in assets}
        resolved_assets: dict[str, Asset] = {}
        for provider in self.providers:
            if not remaining:
                break
            requested = list(remaining)
            try:
                frames = provider.download_history(requested, period=period)
            except Exception as exc:
                provider_report.append(
                    {
                        "provider": provider.name,
                        "requested": len(requested),
                        "resolved": 0,
                        "status": "error",
                        "error": str(exc)[:220],
                    }
                )
                continue
            resolved = 0
            for ticker, frame in frames.items():
                asset = remaining.get(ticker)
                if asset is None or frame is None or frame.empty:
                    continue
                rows = to_price_rows(asset.id, frame, provider.name)
                rows = dedupe_price_rows(rows)
                if not rows:
                    continue
                min_date = min(row["date"] for row in rows)
                db.execute(delete(PriceHistory).where(PriceHistory.asset_id == asset.id, PriceHistory.date >= min_date))
                db.add_all([PriceHistory(**row) for row in rows])
                inserted += len(rows)
                updated_assets += 1
                resolved += 1
                resolved_assets[ticker] = asset
                remaining.pop(ticker, None)
            provider_report.append(
                {
                    "provider": provider.name,
                    "requested": len(requested),
                    "resolved": resolved,
                    "status": "ok" if resolved else "no_data",
                }
            )
        validation_assets = list(resolved_assets.values())
        if provider_validation_limit is not None:
            validation_assets = validation_assets[: max(0, provider_validation_limit)]
        provider_validation = self._record_provider_checks(db, validation_assets)
        db.commit()
        missing_assets = list(remaining)
        return {
            "providers": [provider.name for provider in self.providers],
            "data_mode": "real_public_data_only",
            "updated_assets": updated_assets,
            "price_rows": inserted,
            "period": period,
            "missing_assets": missing_assets,
            "provider_report": provider_report,
            "provider_validation": provider_validation,
            "provider_validation_sample": len(validation_assets),
            "warning": (
                "Some assets have no stored prices because every configured public provider failed or returned no data. No synthetic prices were generated."
                if missing_assets
                else ""
            ),
        }

    def _record_provider_checks(self, db: Session, assets: list[Asset]) -> dict:
        if not assets:
            return {"validated_assets": 0, "diagnostics": []}
        tickers = [asset.ticker for asset in assets]
        by_ticker: dict[str, list[dict]] = {ticker: [] for ticker in tickers}
        diagnostics = []
        for provider in self.providers:
            try:
                frames = provider.download_history(tickers, period="1mo")
            except Exception as exc:
                diagnostics.append({"provider": provider.name, "status": "error", "error": str(exc)[:180], "resolved": 0})
                continue
            resolved = 0
            for ticker, frame in frames.items():
                if frame is None or frame.empty or "Close" not in frame:
                    continue
                try:
                    latest_index, latest_row = next(frame.tail(1).iterrows())
                    close = float(latest_row.get("Close"))
                    point_date = latest_index.date()
                except Exception:
                    continue
                by_ticker.setdefault(ticker, []).append({"provider": provider.name, "date": point_date.isoformat(), "close": close})
                resolved += 1
            diagnostics.append({"provider": provider.name, "status": "ok" if resolved else "no_data", "resolved": resolved})
        inserted_or_updated = 0
        asset_map = {asset.ticker: asset for asset in assets}
        for ticker, observations in by_ticker.items():
            if not observations:
                continue
            asset = asset_map[ticker]
            latest_date = max(datetime.fromisoformat(item["date"]).date() for item in observations)
            latest_observations = [item for item in observations if item["date"] == latest_date.isoformat()]
            closes = [float(item["close"]) for item in latest_observations if item.get("close") is not None]
            if not closes:
                continue
            reference_close = float(median(closes))
            max_divergence = max(abs(close / reference_close - 1) * 100 for close in closes) if reference_close else None
            provider_count = len({item["provider"] for item in latest_observations})
            status = "multi_provider_validated" if provider_count >= 2 else "single_provider_checked"
            if max_divergence is not None and max_divergence >= 1.0 and provider_count >= 2:
                status = "divergence_review"
            existing = db.scalar(
                select(PriceProviderCheck)
                .where(PriceProviderCheck.asset_id == asset.id, PriceProviderCheck.date == latest_date)
                .limit(1)
            )
            payload = {
                "providers": latest_observations,
                "all_observations": observations,
                "policy": "Recent close comparison across available public providers. Missing providers are not filled.",
            }
            if existing:
                existing.provider_count = provider_count
                existing.reference_close = reference_close
                existing.max_divergence_pct = round(max_divergence or 0, 4)
                existing.status = status
                existing.observations = payload
                existing.created_at = datetime.utcnow()
            else:
                db.add(
                    PriceProviderCheck(
                        asset_id=asset.id,
                        ticker=asset.ticker,
                        date=latest_date,
                        provider_count=provider_count,
                        reference_close=reference_close,
                        max_divergence_pct=round(max_divergence or 0, 4),
                        status=status,
                        observations=payload,
                    )
                )
            inserted_or_updated += 1
        return {"validated_assets": inserted_or_updated, "diagnostics": diagnostics}


def dedupe_price_rows(rows: list[dict]) -> list[dict]:
    """Keep the provider's last observation for each asset/date pair."""

    unique: dict[tuple[int, object], dict] = {}
    for row in rows:
        asset_id = row.get("asset_id")
        point_date = row.get("date")
        if asset_id is None or point_date is None:
            continue
        unique[(int(asset_id), point_date)] = row
    return sorted(unique.values(), key=lambda row: (row["asset_id"], row["date"]))


def latest_price_payload(db: Session, ticker: str) -> dict | None:
    asset = db.scalar(select(Asset).where(Asset.ticker == ticker.upper()))
    if not asset:
        return None
    return market_snapshot_for_asset(db, asset)


def market_snapshot_for_asset(db: Session, asset: Asset) -> dict:
    rows = db.scalars(
        select(PriceHistory)
        .where(PriceHistory.asset_id == asset.id)
        .order_by(desc(PriceHistory.date))
        .limit(24)
    ).all()
    if not rows:
        return {
            "ticker": asset.ticker,
            "currency": asset.currency,
            "data_status": "missing_price_history",
            "price": None,
            "date": None,
            "volume": None,
            "provider": None,
            "perf_1d": None,
            "perf_5d": None,
            "perf_1m": None,
        }
    latest = rows[0]
    return {
        "ticker": asset.ticker,
        "currency": asset.currency,
        "data_status": "ready",
        "price": round(float(latest.close), 4),
        "date": str(latest.date),
        "volume": latest.volume,
        "provider": latest.provider,
        "perf_1d": pct_change(rows, 1),
        "perf_5d": pct_change(rows, 5),
        "perf_1m": pct_change(rows, 21),
    }


def pct_change(rows: list[PriceHistory], offset: int) -> float | None:
    if len(rows) <= offset:
        return None
    current = float(rows[0].close)
    previous = float(rows[offset].close)
    if previous == 0:
        return None
    return round((current / previous - 1) * 100, 4)
