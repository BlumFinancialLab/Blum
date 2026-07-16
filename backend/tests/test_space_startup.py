from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
START_SCRIPT = ROOT / "scripts" / "start.sh"
RESTORE_STATUS_SERVER = ROOT / "scripts" / "restore_status_server.py"


def test_embedded_postgres_backup_uses_custom_format_and_is_atomic() -> None:
    source = START_SCRIPT.read_text()

    assert 'BLUM_DB_BACKUP_SECONDS="${BLUM_DB_BACKUP_SECONDS:-1800}"' in source
    assert 'pg_dump -Fc -Z1 blum' in source
    assert '"${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}.tmp"' in source


def test_embedded_postgres_restore_supports_custom_and_bootstrap_fallbacks() -> None:
    source = START_SCRIPT.read_text()

    assert 'embedded_postgres_blum.dump' in source
    assert 'BLUM_DB_RESTORE_JOBS="${BLUM_DB_RESTORE_JOBS:-2}"' in source
    assert 'pg_restore --jobs=${BLUM_DB_RESTORE_JOBS} --exit-on-error -d blum' in source
    assert '< "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}"' not in source
    assert 'embedded_postgres_blum.sql.gz' in source
    assert 'gzip -dc "${BLUM_COMPRESSED_POSTGRES_BACKUP_FILE}"' in source
    assert 'embedded_postgres_blum.sql.gz.parts-ready' in source
    assert '"${BLUM_COMPRESSED_POSTGRES_PART_PREFIX}".part-*' in source
    assert 'embedded_postgres_blum.sql"' in source
    assert 'Restoring legacy PostgreSQL backup' in source
    assert "BLUM_LEGACY_POSTGRES_BACKUP_FILE" in source
    assert 'su postgres -c "psql -d blum" < "${BLUM_LEGACY_POSTGRES_BACKUP_FILE}"' in source
    assert 'psql -d blum < \\"${BLUM_LEGACY_POSTGRES_BACKUP_FILE}\\"' not in source


def test_restore_exposes_a_non_blank_status_page_before_the_api_is_ready() -> None:
    source = START_SCRIPT.read_text()
    status_server = RESTORE_STATUS_SERVER.read_text()

    assert "start_restore_status_server" in source
    assert "restore_status_server.py" in source
    assert '"/health", "/startup/status"' in status_server
    assert '"healthy": True' in status_server
    assert '"api_ready": False' in status_server
    assert "BLUM is restoring its learning memory" in status_server
    assert "stop_restore_status_server" in source
