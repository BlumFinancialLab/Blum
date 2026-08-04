#!/usr/bin/env bash
set -euo pipefail

export PORT="${PORT:-7860}"
export BLUM_PERSIST_DIR="${BLUM_PERSIST_DIR:-/data/blum}"
export BLUM_DB_BACKUP_SECONDS="${BLUM_DB_BACKUP_SECONDS:-1800}"
export BLUM_DB_RESTORE_JOBS="${BLUM_DB_RESTORE_JOBS:-2}"
export BLUM_POSTGRES_DATA_DIR="${BLUM_POSTGRES_DATA_DIR:-${BLUM_PERSIST_DIR}/postgresql/15/main}"
export BLUM_POSTGRES_BIN_DIR="${BLUM_POSTGRES_BIN_DIR:-/usr/lib/postgresql/15/bin}"
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

recover_stale_postmaster_pid() {
  local pid_file="${BLUM_POSTGRES_DATA_DIR}/postmaster.pid"
  local postmaster_pid=""

  [[ -s "${pid_file}" ]] || return 0
  postmaster_pid="$(head -n 1 "${pid_file}" | tr -d '[:space:]')"
  if [[ "${postmaster_pid}" =~ ^[0-9]+$ ]] && kill -0 "${postmaster_pid}" 2>/dev/null; then
    echo "PostgreSQL process ${postmaster_pid} is still active; preserving its postmaster.pid."
    return 0
  fi

  echo "Removing stale PostgreSQL postmaster.pid from persistent storage."
  rm -f "${BLUM_POSTGRES_DATA_DIR}/postmaster.pid"
}

start_embedded_postgres() {
  mkdir -p "${BLUM_POSTGRES_DATA_DIR}"
  chown -R postgres:postgres "${BLUM_POSTGRES_DATA_DIR}"
  chmod 700 "${BLUM_POSTGRES_DATA_DIR}"

  if [[ ! -s "${BLUM_POSTGRES_DATA_DIR}/PG_VERSION" ]]; then
    echo "Initializing persistent PostgreSQL cluster at ${BLUM_POSTGRES_DATA_DIR}."
    su postgres -c "'${BLUM_POSTGRES_BIN_DIR}/initdb' -D '${BLUM_POSTGRES_DATA_DIR}' --auth-local=trust --auth-host=scram-sha-256"
  fi

  recover_stale_postmaster_pid
  su postgres -c "'${BLUM_POSTGRES_BIN_DIR}/pg_ctl' -D '${BLUM_POSTGRES_DATA_DIR}' -o \"-c listen_addresses=127.0.0.1 -p 5432\" -w start"
}

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "No DATABASE_URL provided. Starting embedded PostgreSQL for the Hugging Face Docker demo."
  mkdir -p "${BLUM_PERSIST_DIR}" || true
  start_embedded_postgres
  su postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='blum'\" | grep -q 1 || createdb blum"
  su postgres -c "psql -c \"ALTER USER postgres PASSWORD 'postgres';\""
  export BLUM_EMBEDDED_POSTGRES_BACKUP_FILE="${BLUM_PERSIST_DIR}/embedded_postgres_blum.dump"
  export BLUM_COMPRESSED_POSTGRES_BACKUP_FILE="${BLUM_PERSIST_DIR}/embedded_postgres_blum.sql.gz"
  export BLUM_COMPRESSED_POSTGRES_PART_PREFIX="${BLUM_PERSIST_DIR}/embedded_postgres_blum.sql.gz"
  export BLUM_COMPRESSED_POSTGRES_PARTS_READY_FILE="${BLUM_PERSIST_DIR}/embedded_postgres_blum.sql.gz.parts-ready"
  export BLUM_LEGACY_POSTGRES_BACKUP_FILE="${BLUM_PERSIST_DIR}/embedded_postgres_blum.sql"
  TABLE_COUNT="$(su postgres -c "psql -d blum -tAc \"SELECT count(*) FROM information_schema.tables WHERE table_schema='public';\"" | tr -d '[:space:]')"
  if [[ "${TABLE_COUNT:-0}" == "0" ]] && { [[ -s "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}" ]] || [[ -s "${BLUM_COMPRESSED_POSTGRES_BACKUP_FILE}" ]] || [[ -s "${BLUM_COMPRESSED_POSTGRES_PARTS_READY_FILE}" ]] || [[ -s "${BLUM_LEGACY_POSTGRES_BACKUP_FILE}" ]]; }; then
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
    echo "Embedded PostgreSQL already contains tables; skipping restore."
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
