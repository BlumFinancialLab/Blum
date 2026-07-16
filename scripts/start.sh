#!/usr/bin/env bash
set -euo pipefail

export PORT="${PORT:-7860}"
export BLUM_PERSIST_DIR="${BLUM_PERSIST_DIR:-/data/blum}"
export BLUM_EMBEDDED_PGDATA="${BLUM_EMBEDDED_PGDATA:-${BLUM_PERSIST_DIR}/postgres_data}"
export BLUM_DB_BACKUP_SECONDS="${BLUM_DB_BACKUP_SECONDS:-1800}"
export BLUM_DB_RESTORE_JOBS="${BLUM_DB_RESTORE_JOBS:-2}"
RESTORE_STATUS_PID=""

start_restore_status_server() {
  python3 /app/scripts/restore_status_server.py >/tmp/blum-restore-status.log 2>&1 &
  RESTORE_STATUS_PID=$!
}

stop_restore_status_server() {
  if [[ -n "${RESTORE_STATUS_PID}" ]] && kill -0 "${RESTORE_STATUS_PID}" 2>/dev/null; then
    kill "${RESTORE_STATUS_PID}" 2>/dev/null || true
    wait "${RESTORE_STATUS_PID}" 2>/dev/null || true
  fi
  RESTORE_STATUS_PID=""
}

backup_embedded_postgres() {
  if [[ -n "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE:-}" ]]; then
    mkdir -p "$(dirname "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}")" || true
    if su postgres -c "pg_dump -Fc -Z1 blum" > "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}.tmp"; then
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

start_persistent_postgres() {
  local pg_bin
  pg_bin="$(pg_config --bindir)"
  mkdir -p "${BLUM_EMBEDDED_PGDATA}" /var/run/postgresql
  chown postgres:postgres "${BLUM_EMBEDDED_PGDATA}" /var/run/postgresql
  chmod 700 "${BLUM_EMBEDDED_PGDATA}"

  if [[ ! -s "${BLUM_EMBEDDED_PGDATA}/PG_VERSION" ]]; then
    echo "Initializing persistent embedded PostgreSQL at ${BLUM_EMBEDDED_PGDATA}."
    su postgres -c "'${pg_bin}/initdb' -D '${BLUM_EMBEDDED_PGDATA}' --auth-local=trust --auth-host=scram-sha-256"
  fi

  if su postgres -c "'${pg_bin}/pg_isready' -q -h 127.0.0.1 -p 5432"; then
    return
  fi
  rm -f "${BLUM_EMBEDDED_PGDATA}/postmaster.pid"
  su postgres -c "'${pg_bin}/pg_ctl' -D '${BLUM_EMBEDDED_PGDATA}' -o '-c listen_addresses=127.0.0.1 -p 5432 -k /var/run/postgresql' -w start"
}

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "No DATABASE_URL provided. Starting persistent embedded PostgreSQL for the Hugging Face Docker demo."
  mkdir -p "${BLUM_PERSIST_DIR}" || true
  export PGDATA="${BLUM_EMBEDDED_PGDATA}"
  export BLUM_EMBEDDED_POSTGRES_BACKUP_FILE="${BLUM_PERSIST_DIR}/embedded_postgres_blum.dump"
  export BLUM_COMPRESSED_POSTGRES_BACKUP_FILE="${BLUM_PERSIST_DIR}/embedded_postgres_blum.sql.gz"
  export BLUM_COMPRESSED_POSTGRES_PART_PREFIX="${BLUM_PERSIST_DIR}/embedded_postgres_blum.sql.gz"
  export BLUM_COMPRESSED_POSTGRES_PARTS_READY_FILE="${BLUM_PERSIST_DIR}/embedded_postgres_blum.sql.gz.parts-ready"
  export BLUM_LEGACY_POSTGRES_BACKUP_FILE="${BLUM_PERSIST_DIR}/embedded_postgres_blum.sql"
  if [[ ! -s "${BLUM_EMBEDDED_PGDATA}/PG_VERSION" ]] && { [[ -s "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}" ]] || [[ -s "${BLUM_COMPRESSED_POSTGRES_BACKUP_FILE}" ]] || [[ -s "${BLUM_COMPRESSED_POSTGRES_PARTS_READY_FILE}" ]] || [[ -s "${BLUM_LEGACY_POSTGRES_BACKUP_FILE}" ]]; }; then
    start_restore_status_server
  fi
  start_persistent_postgres
  su postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='blum'\" | grep -q 1 || createdb blum"
  su postgres -c "psql -c \"ALTER USER postgres PASSWORD 'postgres';\""
  TABLE_COUNT="$(su postgres -c "psql -d blum -tAc \"SELECT count(*) FROM information_schema.tables WHERE table_schema='public';\"" | tr -d '[:space:]')"
  if [[ "${TABLE_COUNT:-0}" == "0" && -z "${RESTORE_STATUS_PID}" ]] && { [[ -s "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}" ]] || [[ -s "${BLUM_COMPRESSED_POSTGRES_BACKUP_FILE}" ]] || [[ -s "${BLUM_COMPRESSED_POSTGRES_PARTS_READY_FILE}" ]] || [[ -s "${BLUM_LEGACY_POSTGRES_BACKUP_FILE}" ]]; }; then
    start_restore_status_server
  fi
  if [[ "${TABLE_COUNT:-0}" == "0" && -s "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}" ]]; then
    echo "Restoring embedded PostgreSQL backup from ${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}."
    chmod a+r "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}" || true
    su postgres -c "pg_restore --jobs=${BLUM_DB_RESTORE_JOBS} --exit-on-error -d blum '${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}'" || echo "Custom backup restore failed; continuing with migrations."
  elif [[ "${TABLE_COUNT:-0}" == "0" && -s "${BLUM_COMPRESSED_POSTGRES_BACKUP_FILE}" ]]; then
    echo "Restoring compressed PostgreSQL bootstrap from ${BLUM_COMPRESSED_POSTGRES_BACKUP_FILE}."
    gzip -dc "${BLUM_COMPRESSED_POSTGRES_BACKUP_FILE}" | su postgres -c "psql -d blum" || echo "Compressed backup restore failed; continuing with migrations."
  elif [[ "${TABLE_COUNT:-0}" == "0" && -s "${BLUM_COMPRESSED_POSTGRES_PARTS_READY_FILE}" ]]; then
    echo "Restoring segmented PostgreSQL bootstrap from ${BLUM_COMPRESSED_POSTGRES_PART_PREFIX}.part-* ."
    cat "${BLUM_COMPRESSED_POSTGRES_PART_PREFIX}".part-* | gzip -dc | su postgres -c "psql -d blum" || echo "Segmented backup restore failed; continuing with migrations."
  elif [[ "${TABLE_COUNT:-0}" == "0" && -s "${BLUM_LEGACY_POSTGRES_BACKUP_FILE}" ]]; then
    echo "Restoring legacy PostgreSQL backup from ${BLUM_LEGACY_POSTGRES_BACKUP_FILE}."
    su postgres -c "psql -d blum" < "${BLUM_LEGACY_POSTGRES_BACKUP_FILE}" || echo "Legacy backup restore failed; continuing with migrations."
  elif [[ ! -s "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}" && ! -s "${BLUM_COMPRESSED_POSTGRES_BACKUP_FILE}" && ! -s "${BLUM_LEGACY_POSTGRES_BACKUP_FILE}" ]]; then
    echo "No embedded PostgreSQL backup found yet. A new backup will be written periodically."
  else
    echo "Persistent embedded PostgreSQL already contains tables; skipping restore."
  fi
  stop_restore_status_server
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
