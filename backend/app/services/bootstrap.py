from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import Base, engine
from app.data.seed_assets import SEED_ASSETS
from app.models import Asset


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
    create_schema()
    inserted = seed_asset_universe(db)
    return {"schema_ready": True, "seeded_assets": inserted}

