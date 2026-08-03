from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Asset, ReplayMarketBar
from app.services.deterministic_execution.catalog import NautilusMarketDataProjector
from app.services.deterministic_execution.instruments import BlumInstrumentMapper


class RecordingWriter:
    def __init__(self) -> None:
        self.events = []

    def write(self, instrument, events) -> None:
        self.events.extend(events)


def _db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def _asset(ticker: str, asset_type: str, currency: str = "USD") -> Asset:
    return Asset(
        ticker=ticker,
        name=ticker,
        category=asset_type,
        sector="",
        country="US",
        asset_type=asset_type,
        currency=currency,
        exchange="",
    )


def test_maps_supported_instruments_and_rejects_crypto():
    mapper = BlumInstrumentMapper()
    equity = mapper.map_asset(_asset("AAPL", "equity"))
    etf = mapper.map_asset(_asset("SPY", "etf"))
    forex = mapper.map_asset(_asset("EURUSD=X", "forex"))

    assert equity.instrument_id == "AAPL.BLUMSIM"
    assert etf.asset_class == "etf"
    assert forex.instrument_id == "EURUSD.BLUMFX"
    assert forex.base_currency == "EUR"
    assert forex.quote_currency == "USD"
    assert forex.price_precision == 5

    with pytest.raises(ValueError, match="crypto"):
        mapper.map_asset(_asset("BTC-USD", "crypto"))


def test_projection_is_bounded_resumable_and_point_in_time():
    db = _db()
    asset = _asset("EURUSD=X", "forex")
    db.add(asset)
    db.flush()
    now = datetime(2026, 8, 3, 12, 0)
    for index, minute in enumerate((0, 1, 2)):
        db.add(
            ReplayMarketBar(
                asset_id=asset.id,
                source_symbol=asset.ticker,
                normalized_symbol="EURUSD",
                market="forex",
                timeframe="1m",
                bar_timestamp=now + timedelta(minutes=minute),
                open=1.1 + index * 0.001,
                high=1.101 + index * 0.001,
                low=1.099 + index * 0.001,
                close=1.1005 + index * 0.001,
                volume=1000,
                provider="test",
                acquired_at=now + timedelta(minutes=minute),
                data_quality_score=90,
            )
        )
    db.commit()
    writer = RecordingWriter()
    projector = NautilusMarketDataProjector(writer=writer)

    first = projector.project(db, cursor=None, limit=1, runtime_now=now + timedelta(minutes=1))
    second = projector.project(db, cursor=first.cursor, limit=10, runtime_now=now + timedelta(minutes=1))

    assert first.rows_written == 1
    assert second.rows_written == 1
    assert [event.timestamp for event in writer.events] == [now, now + timedelta(minutes=1)]
    assert second.cursor["replay_market_bar_id"] > first.cursor["replay_market_bar_id"]


def test_unavailable_writer_does_not_advance_cursor():
    db = _db()
    result = NautilusMarketDataProjector(writer=None, writer_factory=lambda _: None).project(
        db,
        cursor={"replay_market_bar_id": 7},
        limit=5,
        runtime_now=datetime(2026, 8, 3),
    )
    assert result.status == "UNAVAILABLE"
    assert result.cursor == {"replay_market_bar_id": 7}
