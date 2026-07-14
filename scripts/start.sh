#!/usr/bin/env bash
set -euo pipefail

export PORT="${PORT:-7860}"
export BLUM_PERSIST_DIR="${BLUM_PERSIST_DIR:-/data/blum}"
export BLUM_DB_BACKUP_SECONDS="${BLUM_DB_BACKUP_SECONDS:-1800}"
RESTORE_STATUS_PID=""

start_restore_status_server() {
  local status_dir="/tmp/blum-restore-status"
  mkdir -p "${status_dir}"
  cat > "${status_dir}/index.html" <<'EOF'
<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>BLUM startup</title></head>
  <body style="margin:0;background:#080b0e;color:#e8eef2;font-family:system-ui,sans-serif;display:grid;min-height:100vh;place-items:center">
    <main style="max-width:620px;padding:32px"><p style="color:#72d6a3;font-weight:700">BLUM · TRADER BRAIN</p><h1>BLUM is restoring its learning memory</h1><p style="color:#9aa7b2;line-height:1.6">The API will start automatically when the persisted market history has been restored. No learning data is being discarded.</p></main>
  </body>
</html>
EOF
  (cd "${status_dir}" && python3 -m http.server "${PORT}" --bind 0.0.0.0 >/tmp/blum-restore-status.log 2>&1) &
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

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "No DATABASE_URL provided. Starting embedded PostgreSQL for the Hugging Face Docker demo."
  mkdir -p "${BLUM_PERSIST_DIR}" || true
  service postgresql start
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
    su postgres -c "pg_restore -d blum" < "${BLUM_EMBEDDED_POSTGRES_BACKUP_FILE}" || echo "Custom backup restore failed; continuing with migrations."
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
