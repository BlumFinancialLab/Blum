from __future__ import annotations

from datetime import datetime
import os
import subprocess
from urllib.parse import unquote, urlparse

from app.core.config import get_settings


def database_persistence_status() -> dict:
    backup_file = os.getenv("BLUM_EMBEDDED_POSTGRES_BACKUP_FILE")
    backup_exists = bool(backup_file and os.path.exists(backup_file))
    backup_size = os.path.getsize(backup_file) if backup_exists and backup_file else 0
    uses_external_database = bool(os.getenv("DATABASE_URL")) and not backup_file
    mode = "external_postgres" if uses_external_database else "embedded_postgres"
    return {
        "mode": mode,
        "external_database_configured": uses_external_database,
        "embedded_backup_file": backup_file,
        "embedded_backup_exists": backup_exists,
        "embedded_backup_size_bytes": backup_size,
        "embedded_backup_interval_seconds": safe_int(os.getenv("BLUM_DB_BACKUP_SECONDS"), 300),
        "persistent_dir": os.getenv("BLUM_PERSIST_DIR", "/data/blum"),
        "strict_no_reset_mode": uses_external_database,
        "last_backup_attempt": os.getenv("BLUM_LAST_BACKUP_ATTEMPT"),
        "durability_note": (
            "External DATABASE_URL is the strict no-reset mode. Embedded PostgreSQL backup can recover learning state only "
            "when Hugging Face persistent storage is enabled for the /data mount."
        ),
    }


def backup_embedded_postgres_if_configured(reason: str = "manual") -> dict:
    backup_file = os.getenv("BLUM_EMBEDDED_POSTGRES_BACKUP_FILE")
    if not backup_file:
        return {"status": "skipped", "reason": "embedded PostgreSQL backup file is not configured"}

    os.makedirs(os.path.dirname(backup_file), exist_ok=True)
    tmp_file = f"{backup_file}.tmp"
    custom_format = backup_file.endswith(".dump")
    args, env = pg_dump_command(custom_format=custom_format)
    started_at = datetime.utcnow().isoformat()
    os.environ["BLUM_LAST_BACKUP_ATTEMPT"] = started_at
    try:
        with open(tmp_file, "wb") as handle:
            result = subprocess.run(
                args,
                stdout=handle,
                stderr=subprocess.PIPE,
                env=env,
                timeout=safe_int(os.getenv("BLUM_DB_BACKUP_TIMEOUT_SECONDS"), 900),
                check=False,
            )
        if result.returncode != 0:
            safe_unlink(tmp_file)
            return {
                "status": "error",
                "reason": reason,
                "started_at": started_at,
                "stderr": result.stderr.decode("utf-8", errors="replace")[-1200:],
            }
        os.replace(tmp_file, backup_file)
        return {
            "status": "ok",
            "reason": reason,
            "started_at": started_at,
            "backup_file": backup_file,
            "backup_size_bytes": os.path.getsize(backup_file),
        }
    except Exception as exc:
        safe_unlink(tmp_file)
        return {"status": "error", "reason": reason, "started_at": started_at, "error": f"{type(exc).__name__}: {exc}"}


def pg_dump_command(*, custom_format: bool = False) -> tuple[list[str], dict[str, str]]:
    settings = get_settings()
    raw_url = settings.database_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    parsed = urlparse(raw_url)
    database = parsed.path.lstrip("/") or "blum"
    args = [
        "pg_dump",
        "-h",
        parsed.hostname or "127.0.0.1",
        "-p",
        str(parsed.port or 5432),
        "-U",
        unquote(parsed.username or "postgres"),
        "-d",
        database,
    ]
    if custom_format:
        args.extend(["--format=custom", "--compress=1"])
    env = dict(os.environ)
    if parsed.password:
        env["PGPASSWORD"] = unquote(parsed.password)
    return args, env


def safe_unlink(path: str) -> None:
    try:
        if os.path.exists(path):
            os.unlink(path)
    except OSError:
        pass


def safe_int(value: str | None, default: int) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default
