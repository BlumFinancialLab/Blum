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
    git \
    libpq-dev \
    postgresql \
    postgresql-contrib \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.5.1
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir --no-deps \
    "git+https://github.com/AI4Finance-Foundation/FinRL-Trading.git@e65d6f0483ead7d2ef4a5fc940cdf960392a25c1"

COPY backend ./backend
COPY scripts ./scripts
COPY --from=frontend /workspace/frontend/out ./backend/app/static

ENV BLUM_FINRLX_ENABLED=true \
    BLUM_FINRLX_RUNNER_COMMAND=/app/scripts/finrlx_runner.py \
    BLUM_FINRLX_ARTIFACT_ROOT=/data/trading_ml/finrlx \
    BLUM_FOREX_HISTORY_ENABLED=true \
    BLUM_FOREX_HISTORY_SOURCE_PATH=/app/backend/app/data/forex/Forex_sample_dataset.csv

RUN chmod +x /app/scripts/start.sh /app/scripts/finrlx_runner.py

EXPOSE 7860
CMD ["/app/scripts/start.sh"]
