from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
START_SCRIPT = ROOT / "scripts" / "start.sh"


def test_embedded_postgres_backup_uses_custom_format_and_is_atomic() -> None:
    source = START_SCRIPT.read_text()

    assert 'BLUM_DB_BACKUP_SECONDS="${BLUM_DB_BACKUP_SECONDS:-1800}"' in source
    assert 'pg_dump -Fc -Z1 blum' in source
    assert '"${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}.tmp"' in source


def test_embedded_postgres_restore_supports_custom_and_bootstrap_fallbacks() -> None:
    source = START_SCRIPT.read_text()

    assert 'embedded_postgres_blum.dump' in source
    assert 'pg_restore -d blum' in source
    assert 'embedded_postgres_blum.sql.gz' in source
    assert 'gzip -dc "${BLUM_COMPRESSED_POSTGRES_BACKUP_FILE}"' in source
    assert 'embedded_postgres_blum.sql.gz.parts-ready' in source
    assert '"${BLUM_COMPRESSED_POSTGRES_PART_PREFIX}".part-*' in source
    assert 'embedded_postgres_blum.sql"' in source
    assert 'Restoring legacy PostgreSQL backup' in source
    assert "BLUM_LEGACY_POSTGRES_BACKUP_FILE" in source
