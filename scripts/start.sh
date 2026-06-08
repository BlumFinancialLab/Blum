#!/usr/bin/env bash
set -euo pipefail

export PORT="${PORT:-7860}"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "No DATABASE_URL provided. Starting embedded PostgreSQL for the Hugging Face Docker demo."
  service postgresql start
  su postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='blum'\" | grep -q 1 || createdb blum"
  su postgres -c "psql -c \"ALTER USER postgres PASSWORD 'postgres';\""
  export DATABASE_URL="postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/blum"
else
  echo "Using external PostgreSQL DATABASE_URL."
fi

echo "Applying Alembic migrations."
cd /app/backend
alembic -c alembic.ini upgrade head

cd /app
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
