#!/usr/bin/env bash
set -euo pipefail

export PORT="${PORT:-7860}"
export BLUM_PERSIST_DIR="${BLUM_PERSIST_DIR:-/data/blum}"
export BLUM_DB_BACKUP_SECONDS="${BLUM_DB_BACKUP_SECONDS:-300}"

backup_embedded_postgres() {
  if [[ -n "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE:-}" ]]; then
    mkdir -p "$(dirname "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}")" || true
    if su postgres -c "pg_dump blum" > "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}.tmp"; then
      mv "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}.tmp" "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}"
      echo "Embedded PostgreSQL backup updated at ${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}."
    else
      echo "Embedded PostgreSQL backup failed; keeping previous backup if present."
      rm -f "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}.tmp"
    fi
  fi
}

start_backup_loop() {
  if [[ -n "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE:-}" ]]; then
    (
      while true; do
        sleep "${BLUM_DB_BACKUP_SECONDS}"
        backup_embedded_postgres
      done
    ) &
  fi
}

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "No DATABASE_URL provided. Starting embedded PostgreSQL for the Hugging Face Docker demo."
  mkdir -p "${BLUM_PERSIST_DIR}" || true
  service postgresql start
  su postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='blum'\" | grep -q 1 || createdb blum"
  su postgres -c "psql -c \"ALTER USER postgres PASSWORD 'postgres';\""
  export BLUM_EMBEDDED_POSTGRES_BACKUP_FILE="${BLUM_PERSIST_DIR}/embedded_postgres_blum.sql"
  TABLE_COUNT="$(su postgres -c "psql -d blum -tAc \"SELECT count(*) FROM information_schema.tables WHERE table_schema='public';\"" | tr -d '[:space:]')"
  if [[ "${TABLE_COUNT:-0}" == "0" && -s "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}" ]]; then
    echo "Restoring embedded PostgreSQL backup from ${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}."
    su postgres -c "psql -d blum" < "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}" || echo "Backup restore failed; continuing with migrations."
  elif [[ ! -s "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}" ]]; then
    echo "No embedded PostgreSQL backup found yet. A new backup will be written periodically."
  else
    echo "Embedded PostgreSQL already contains tables; skipping restore."
  fi
  export DATABASE_URL="postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/blum"
  start_backup_loop
else
  echo "Using external PostgreSQL DATABASE_URL."
fi

echo "Applying Alembic migrations."
cd /app/backend
alembic -c alembic.ini upgrade head

cd /app
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
