from __future__ import annotations

import csv
from datetime import date
import gzip
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import Base, engine
from app.data.seed_assets import SEED_ASSETS
from app.models import Asset, PriceHistory, SignalSnapshot
from app.signals.engine import SignalEngine


HISTORICAL_PRICE_CACHE = Path(__file__).resolve().parents[1] / "data" / "historical_prices_seed.csv.gz"


def create_schema() -> None:
    Base.metadata.create_all(bind=engine)


def seed_asset_universe(db: Session) -> int:
    inserted = 0
    existing = set(db.scalars(select(Asset.ticker)).all())
    for item in SEED_ASSETS:
        if item["ticker"] in existing:
            continue
        db.add(Asset(**item))
        inserted += 1
    db.commit()
    return inserted


def bootstrap_database(db: Session) -> dict:
    settings = get_settings()
    create_schema()
    inserted = seed_asset_universe(db)
    historical = {"enabled": settings.seed_historical_prices_on_startup, "inserted_rows": 0, "cache_status": "disabled"}
    if settings.seed_historical_prices_on_startup:
        historical = seed_historical_prices(db)
    signals = {"enabled": settings.seed_signals_on_startup, "signals_created": 0, "status": "disabled"}
    if settings.seed_signals_on_startup:
        signals = seed_startup_signals(db)
    return {"schema_ready": True, "seeded_assets": inserted, "historical_prices": historical, "startup_signals": signals}


def seed_historical_prices(db: Session) -> dict:
    if not HISTORICAL_PRICE_CACHE.exists():
        return {
            "enabled": True,
            "cache_status": "missing",
            "cache_file": str(HISTORICAL_PRICE_CACHE),
            "inserted_rows": 0,
            "message": "Historical price cache is not packaged in this build.",
        }
    asset_ids = dict(db.execute(select(Asset.ticker, Asset.id)).all())
    inserted = 0
    skipped = 0
    tickers: set[str] = set()
    rows: list[dict] = []
    with gzip.open(HISTORICAL_PRICE_CACHE, "rt", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for item in reader:
            ticker = (item.get("ticker") or "").upper()
            asset_id = asset_ids.get(ticker)
            if not asset_id:
                skipped += 1
                continue
            row = price_row_from_cache(asset_id, item)
            if not row:
                skipped += 1
                continue
            tickers.add(ticker)
            rows.append(row)
            if len(rows) >= 5000:
                inserted += insert_price_rows(db, rows)
                rows.clear()
    if rows:
        inserted += insert_price_rows(db, rows)
    db.commit()
    return {
        "enabled": True,
        "cache_status": "loaded",
        "cache_file": HISTORICAL_PRICE_CACHE.name,
        "inserted_rows": inserted,
        "skipped_rows": skipped,
        "covered_assets": len(tickers),
        "data_policy": "Versioned OHLCV cache built from public historical sources. No synthetic market data.",
    }


def seed_startup_signals(db: Session) -> dict:
    signal_count = int(db.scalar(select(func.count(SignalSnapshot.id))) or 0)
    price_count = int(db.scalar(select(func.count(PriceHistory.id))) or 0)
    if signal_count > 0:
        return {"enabled": True, "status": "already_available", "signals_created": 0, "existing_signals": signal_count}
    if price_count == 0:
        return {"enabled": True, "status": "no_price_history", "signals_created": 0}
    result = SignalEngine().run(db, limit=80)
    return {"enabled": True, "status": "created", **result}


def price_row_from_cache(asset_id: int, item: dict) -> dict | None:
    try:
        close = float(item["close"])
        return {
            "asset_id": asset_id,
            "date": date.fromisoformat(item["date"]),
            "open": float_or_none(item.get("open")),
            "high": float_or_none(item.get("high")),
            "low": float_or_none(item.get("low")),
            "close": close,
            "volume": float_or_none(item.get("volume")),
            "provider": item.get("provider") or "historical_cache",
        }
    except Exception:
        return None


def insert_price_rows(db: Session, rows: list[dict]) -> int:
    if not rows:
        return 0
    if db.bind and db.bind.dialect.name == "postgresql":
        statement = pg_insert(PriceHistory).values(rows).on_conflict_do_nothing(index_elements=["asset_id", "date"])
        result = db.execute(statement)
        return int(result.rowcount or 0)
    inserted = 0
    for row in rows:
        exists = db.scalar(
            select(PriceHistory.id)
            .where(PriceHistory.asset_id == row["asset_id"], PriceHistory.date == row["date"])
            .limit(1)
        )
        if exists:
            continue
        db.add(PriceHistory(**row))
        inserted += 1
    return inserted


def float_or_none(value) -> float | None:
    if value in {None, "", "None", "nan", "NaN"}:
        return None
    try:
        return float(value)
    except Exception:
        return None
