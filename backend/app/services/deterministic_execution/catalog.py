from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Callable, Protocol

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.models import ReplayMarketBar
from app.services.deterministic_execution.contracts import InstrumentSpec, MarketEvent
from app.services.deterministic_execution.instruments import BlumInstrumentMapper


class CatalogWriter(Protocol):
    def write(self, instrument: InstrumentSpec, events: tuple[MarketEvent, ...]) -> None: ...


@dataclass(frozen=True)
class CatalogProjectionResult:
    status: str
    cursor: dict[str, int]
    rows_read: int = 0
    rows_written: int = 0
    rows_rejected: int = 0
    reason: str = ""


class NautilusParquetCatalogWriter:
    """Thin infrastructure adapter around Nautilus' append-oriented Parquet catalog."""

    def __init__(self, path: str) -> None:
        from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

        Path(path).mkdir(parents=True, exist_ok=True)
        self.catalog = ParquetDataCatalog(path)

    def write(self, instrument: InstrumentSpec, events: tuple[MarketEvent, ...]) -> None:
        from app.services.deterministic_execution.nautilus_kernel import (
            to_nautilus_bars,
            to_nautilus_instrument,
        )

        native_instrument = to_nautilus_instrument(instrument, events[0].timestamp)
        native_bars = to_nautilus_bars(instrument, events)
        # Instruments and bars are both persisted as native Nautilus objects.
        self.catalog.write_data([native_instrument])
        self.catalog.write_data(native_bars)


class NautilusMarketDataProjector:
    """Projects bounded, point-in-time replay bars into the execution catalog."""

    def __init__(
        self,
        *,
        writer: CatalogWriter | None = None,
        writer_factory: Callable[[str], CatalogWriter | None] | None = None,
        mapper: BlumInstrumentMapper | None = None,
    ) -> None:
        self._writer = writer
        self._writer_factory = writer_factory or self._default_writer
        self._mapper = mapper or BlumInstrumentMapper()

    def project(
        self,
        db: Session,
        *,
        cursor: dict[str, int] | None,
        limit: int,
        runtime_now: datetime,
    ) -> CatalogProjectionResult:
        current_cursor = dict(cursor or {"replay_market_bar_id": 0})
        writer = self._writer or self._writer_factory(get_settings().blum_nautilus_catalog_path)
        if writer is None:
            return CatalogProjectionResult("UNAVAILABLE", current_cursor, reason="Nautilus catalog unavailable")

        last_id = int(current_cursor.get("replay_market_bar_id", 0))
        rows = db.scalars(
            select(ReplayMarketBar)
            .options(joinedload(ReplayMarketBar.asset))
            .where(
                and_(
                    ReplayMarketBar.id > last_id,
                    ReplayMarketBar.bar_timestamp <= runtime_now,
                    ReplayMarketBar.acquired_at <= runtime_now,
                )
            )
            .order_by(ReplayMarketBar.id)
            .limit(max(1, min(int(limit), 10_000)))
        ).all()
        grouped: dict[str, tuple[InstrumentSpec, list[MarketEvent]]] = {}
        rejected = 0
        seen: set[tuple[str, datetime]] = set()
        for row in rows:
            try:
                instrument = self._mapper.map_asset(row.asset)
                event = self._event(row, instrument)
            except (TypeError, ValueError):
                rejected += 1
                continue
            duplicate_key = (instrument.instrument_id, event.timestamp)
            if duplicate_key in seen:
                rejected += 1
                continue
            seen.add(duplicate_key)
            grouped.setdefault(instrument.instrument_id, (instrument, []))[1].append(event)

        written = 0
        for instrument, events in grouped.values():
            ordered = tuple(sorted(events, key=lambda item: item.timestamp))
            writer.write(instrument, ordered)
            written += len(ordered)
        if rows:
            current_cursor["replay_market_bar_id"] = rows[-1].id
        return CatalogProjectionResult(
            status="READY",
            cursor=current_cursor,
            rows_read=len(rows),
            rows_written=written,
            rows_rejected=rejected,
        )

    @staticmethod
    def _event(row: ReplayMarketBar, instrument: InstrumentSpec) -> MarketEvent:
        timestamp = row.bar_timestamp
        if isinstance(timestamp, date) and not isinstance(timestamp, datetime):
            timestamp = datetime.combine(timestamp, time.min)
        close = float(row.close)
        return MarketEvent(
            instrument_id=instrument.instrument_id,
            event_type="bar",
            timestamp=timestamp,
            open=float(row.open if row.open is not None else close),
            high=float(row.high if row.high is not None else close),
            low=float(row.low if row.low is not None else close),
            close=close,
            volume=float(row.volume or 0.0),
            source=row.provider,
            acquired_at=row.acquired_at,
        )

    @staticmethod
    def _default_writer(path: str) -> CatalogWriter | None:
        try:
            return NautilusParquetCatalogWriter(path)
        except (ImportError, ModuleNotFoundError, OSError):
            return None
