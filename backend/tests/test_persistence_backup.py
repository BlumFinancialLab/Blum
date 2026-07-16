from app.core.config import get_settings
from app.services.persistence import database_persistence_status, pg_dump_command


def test_pg_dump_command_supports_compressed_custom_format(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:secret@127.0.0.1:5432/blum",
    )
    get_settings.cache_clear()

    args, env = pg_dump_command(custom_format=True)

    assert "--format=custom" in args
    assert "--compress=1" in args
    assert env["PGPASSWORD"] == "secret"
    get_settings.cache_clear()


def test_persistence_status_recognizes_persistent_embedded_cluster(monkeypatch, tmp_path) -> None:
    pgdata = tmp_path / "postgres_data"
    pgdata.mkdir()
    (pgdata / "PG_VERSION").write_text("15\n")
    monkeypatch.setenv("BLUM_EMBEDDED_PGDATA", str(pgdata))
    monkeypatch.setenv("BLUM_EMBEDDED_POSTGRES_BACKUP_FILE", str(tmp_path / "backup.dump"))

    status = database_persistence_status()

    assert status["mode"] == "persistent_embedded_postgres"
    assert status["embedded_cluster_exists"] is True
    assert status["strict_no_reset_mode"] is True
