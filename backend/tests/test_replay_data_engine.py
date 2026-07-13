from datetime import datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Asset, PriceHistory, ReplayMarketBar
from app.providers.replay_data_provider import ProviderBars, ReplayDataRequest
from app.services.replay_data import MultiProviderReplayDataService


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_asset(db: Session, ticker: str = "NVDA", market: str = "USA") -> Asset:
    asset = Asset(
        ticker=ticker,
        name=ticker,
        category="Stock",
        sector="Technology",
        country=market,
        asset_type="Stock",
        currency="USD" if market == "USA" else "EUR",
        exchange="NASDAQ" if market == "USA" else "MIL",
        is_active=True,
    )
    db.add(asset)
    db.flush()
    return asset


def replay_bar_values(asset_id: int) -> dict:
    return {
        "asset_id": asset_id,
        "source_symbol": "NVDA",
        "normalized_symbol": "NVDA",
        "market": "USA",
        "timeframe": "1m",
        "bar_timestamp": datetime(2026, 7, 10, 14, 31),
        "open": 160.0,
        "high": 161.0,
        "low": 159.5,
        "close": 160.5,
        "volume": 250_000,
        "provider": "test",
        "acquired_at": datetime(2026, 7, 10, 18, 0),
        "data_quality_score": 98.0,
        "source_metadata": {"license": "test fixture"},
    }


def test_replay_bar_keeps_intraday_timestamp_and_timeframe():
    with setup_db() as db:
        asset = seed_asset(db)
        timestamp = replay_bar_values(asset.id)["bar_timestamp"]
        db.add(ReplayMarketBar(**replay_bar_values(asset.id)))
        db.commit()
        row = db.scalar(select(ReplayMarketBar))

    assert row is not None
    assert row.bar_timestamp == timestamp
    assert row.timeframe == "1m"


def test_replay_bar_unique_key_prevents_duplicate_provider_bar():
    with setup_db() as db:
        asset = seed_asset(db)
        values = replay_bar_values(asset.id)
        db.add(ReplayMarketBar(**values))
        db.commit()
        db.add(ReplayMarketBar(**values))
        with pytest.raises(IntegrityError):
            db.commit()


class RecordingProvider:
    name = "recording"
    supported_timeframes = frozenset({"1m", "5m", "15m", "1d"})
    source_metadata = {"license": "test"}

    def __init__(self, bars: pd.DataFrame | None = None, blocker: str | None = None):
        self.bars = bars if bars is not None else pd.DataFrame()
        self.blocker = blocker
        self.requests: list[ReplayDataRequest] = []

    def fetch(self, request: ReplayDataRequest) -> ProviderBars:
        self.requests.append(request)
        return ProviderBars(
            provider=self.name,
            frame=self.bars,
            source_metadata=self.source_metadata,
            blockers=[self.blocker] if self.blocker else [],
        )


class RaisingProvider(RecordingProvider):
    def fetch(self, request: ReplayDataRequest) -> ProviderBars:
        self.requests.append(request)
        raise RuntimeError("provider transport failed")


def frame(start: datetime, periods: int, frequency: str) -> pd.DataFrame:
    index = pd.date_range(start=start, periods=periods, freq=frequency)
    return pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(periods)],
            "High": [101.0 + i for i in range(periods)],
            "Low": [99.0 + i for i in range(periods)],
            "Close": [100.5 + i for i in range(periods)],
            "Volume": [1000.0 + i for i in range(periods)],
        },
        index=index,
    )


def seed_replay_bars(db: Session, asset: Asset, start: datetime, count: int, timeframe: str = "5m") -> None:
    for index in range(count):
        timestamp = start + timedelta(minutes=5 * index)
        values = replay_bar_values(asset.id)
        values.update(
            timeframe=timeframe,
            bar_timestamp=timestamp,
            provider="local",
            close=100.0 + index,
        )
        db.add(ReplayMarketBar(**values))
    db.commit()


def test_db_coverage_is_used_before_provider_fetch():
    provider = RecordingProvider()
    start = datetime(2026, 7, 10, 14, 30)
    with setup_db() as db:
        asset = seed_asset(db)
        seed_replay_bars(db, asset, start, count=4)
        result = MultiProviderReplayDataService([provider]).ensure_coverage(
            db,
            asset=asset,
            timeframe="5m",
            start=start,
            end=start + timedelta(minutes=15),
        )

    assert provider.requests == []
    assert result.status == "READY"
    assert result.rows_available == 4


def test_missing_range_uses_fallback_and_persists_real_bars():
    start = datetime(2026, 7, 10, 8, 0)
    primary = RecordingProvider(blocker="PROVIDER_UNAVAILABLE")
    fallback = RecordingProvider(frame(start, periods=5, frequency="15min"))
    fallback.name = "fallback"
    with setup_db() as db:
        asset = seed_asset(db, "ENI.MI", "ITALY")
        result = MultiProviderReplayDataService([primary, fallback]).ensure_coverage(
            db,
            asset=asset,
            timeframe="15m",
            start=start,
            end=start + timedelta(hours=1),
        )
        rows = db.scalars(select(ReplayMarketBar).where(ReplayMarketBar.asset_id == asset.id)).all()

    assert result.provider == "fallback"
    assert result.rows_available == 5
    assert len(rows) == 5
    assert result.provider_attempts[0]["blockers"] == ["PROVIDER_UNAVAILABLE"]


def test_provider_exception_is_isolated_and_fallback_still_runs():
    start = datetime(2026, 7, 10, 8, 0)
    primary = RaisingProvider()
    fallback = RecordingProvider(frame(start, periods=5, frequency="15min"))
    fallback.name = "fallback"
    with setup_db() as db:
        asset = seed_asset(db, "ENI.MI", "ITALY")
        result = MultiProviderReplayDataService([primary, fallback]).ensure_coverage(
            db,
            asset=asset,
            timeframe="15m",
            start=start,
            end=start + timedelta(hours=1),
        )

    assert result.provider == "fallback"
    assert result.provider_attempts[0]["blockers"] == ["PROVIDER_UNAVAILABLE"]


def test_daily_replay_imports_existing_price_history_before_provider_fetch():
    provider = RecordingProvider()
    start = datetime(2026, 7, 7)
    with setup_db() as db:
        asset = seed_asset(db)
        for offset in range(4):
            timestamp = start + timedelta(days=offset)
            db.add(
                PriceHistory(
                    asset_id=asset.id,
                    date=timestamp.date(),
                    open=100.0 + offset,
                    high=102.0 + offset,
                    low=99.0 + offset,
                    close=101.0 + offset,
                    volume=1_000_000 + offset,
                    provider="stored_history",
                )
            )
        db.commit()

        result = MultiProviderReplayDataService([provider]).ensure_coverage(
            db,
            asset=asset,
            timeframe="1d",
            start=start,
            end=start + timedelta(days=3),
        )
        rows = db.scalars(
            select(ReplayMarketBar)
            .where(ReplayMarketBar.asset_id == asset.id, ReplayMarketBar.timeframe == "1d")
            .order_by(ReplayMarketBar.bar_timestamp)
        ).all()

    assert provider.requests == []
    assert result.status == "READY"
    assert result.provider == "price_history_bridge"
    assert len(rows) == 4
    assert rows[-1].close == 104.0
    assert rows[-1].source_metadata["source_table"] == "price_history"
