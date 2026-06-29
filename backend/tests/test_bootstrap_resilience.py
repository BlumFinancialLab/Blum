from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Asset, PriceHistory
from app.services import bootstrap


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def seed_asset(db: Session) -> None:
    db.add(
        Asset(
            ticker="SPY",
            name="SPDR S&P 500 ETF",
            category="ETF",
            sector="Broad Market",
            industry="",
            country="US",
            asset_type="ETF",
            exchange="NYSE",
        )
    )
    db.commit()


def test_historical_seed_git_lfs_pointer_does_not_break_startup(tmp_path, monkeypatch):
    pointer = tmp_path / "historical_prices_seed.csv.gz"
    pointer.write_text(
        "\n".join(
            [
                "version https://git-lfs.github.com/spec/v1",
                "oid sha256:abcdef",
                "size 123456",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(bootstrap, "HISTORICAL_PRICE_CACHE", pointer)

    with make_session() as db:
        seed_asset(db)
        result = bootstrap.seed_historical_prices(db)
        price_count = db.scalar(select(PriceHistory).limit(1))

    assert result["cache_status"] == "git_lfs_pointer"
    assert result["inserted_rows"] == 0
    assert result["diagnostics"]["pointer_detected"] is True
    assert "No synthetic prices" in result["data_policy"]
    assert price_count is None


def test_historical_seed_invalid_gzip_does_not_break_startup(tmp_path, monkeypatch):
    corrupt = tmp_path / "historical_prices_seed.csv.gz"
    corrupt.write_bytes(b"not a gzip payload")
    monkeypatch.setattr(bootstrap, "HISTORICAL_PRICE_CACHE", corrupt)

    with make_session() as db:
        seed_asset(db)
        result = bootstrap.seed_historical_prices(db)
        price_count = db.scalar(select(PriceHistory).limit(1))

    assert result["cache_status"] == "invalid"
    assert result["inserted_rows"] == 0
    assert "could not be loaded" in result["message"]
    assert "No synthetic prices" in result["data_policy"]
    assert price_count is None
