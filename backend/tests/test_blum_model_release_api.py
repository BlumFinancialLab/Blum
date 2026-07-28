from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.api.routers.analyst import (
    release_export_artifact,
    release_export_manifest,
    router,
)
from app.core.database import Base
from app.models import BlumDatasetExport


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_release_export_routes_are_explicit_and_read_routes_are_get_only() -> None:
    routes = {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}

    assert ("/api/analyst/release-export", ("POST",)) in routes
    assert (
        "/api/analyst/release-exports/{export_id}/manifest",
        ("GET",),
    ) in routes
    assert (
        "/api/analyst/release-exports/{export_id}/artifact",
        ("GET",),
    ) in routes


def test_manifest_get_reads_persisted_payload_without_writes() -> None:
    with setup_db() as db:
        export = BlumDatasetExport(
            export_name="release.tar.gz",
            format="tar.gz",
            record_count=30,
            file_path="/tmp/release.tar.gz",
            status="created",
            payload_summary={
                "release_safe": True,
                "manifest": {"schema_version": "blum-finance-manifest-v1"},
            },
        )
        db.add(export)
        db.commit()
        before = db.scalar(select(func.count(BlumDatasetExport.id)))

        payload = release_export_manifest(export.id, db=db)

        assert payload["schema_version"] == "blum-finance-manifest-v1"
        assert db.scalar(select(func.count(BlumDatasetExport.id))) == before


def test_artifact_download_rejects_internal_export(tmp_path: Path) -> None:
    internal = tmp_path / "internal.jsonl"
    internal.write_text("{}\n", encoding="utf-8")
    with setup_db() as db:
        export = BlumDatasetExport(
            export_name="internal.jsonl",
            format="jsonl",
            record_count=1,
            file_path=str(internal),
            status="created",
            payload_summary={"release_safe": False},
        )
        db.add(export)
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            release_export_artifact(export.id, db=db)

        assert exc_info.value.status_code == 403
