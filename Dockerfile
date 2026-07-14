FROM node:20-bookworm-slim AS frontend
WORKDIR /workspace/frontend
COPY frontend/package.json ./
RUN npm install
COPY frontend ./
RUN npm run build

FROM python:3.11-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    NEXT_TELEMETRY_DISABLED=1 \
    TOKENIZERS_PARALLELISM=false \
    PAPER_FORWARD_LIFECYCLE_ENABLED=true \
    PAPER_FORWARD_MAX_HOLDING_DAYS=10 \
    BLUM_SEED_HISTORICAL_PRICES_ON_STARTUP=false \
    BLUM_SEED_SIGNALS_ON_STARTUP=false \
    BLUM_SEED_ACCURACY_ON_STARTUP=false \
    PORT=7860

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    gcc \
    g++ \
    libpq-dev \
    postgresql \
    postgresql-contrib \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.5.1
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY scripts ./scripts
COPY --from=frontend /workspace/frontend/out ./backend/app/static

RUN chmod +x /app/scripts/start.sh

EXPOSE 7860
CMD ["/app/scripts/start.sh"]
