from app.core.config import get_settings
from app.services.persistence import pg_dump_command


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
