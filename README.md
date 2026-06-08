---
title: Blum AI Financial Intelligence
emoji: 📈
colorFrom: yellow
colorTo: gray
sdk: docker
app_port: 7860
short_description: Open-source AI market intelligence case study.
tags: [financial-analysis, finance, stock-market, ai, fastapi, nextjs, postgresql, sentiment-analysis, time-series, data-visualization]
pinned: false
---

# Blum AI Financial Intelligence

Blum is an open-source technical case study for AI financial intelligence. It is designed to analyze equities and ETFs, filter watchlist candidates, explain market narratives, build transparent signals and validate signal behavior historically.

This is not a consumer trading app and not a simple dashboard. The project is a full-stack platform that demonstrates how specialized AI modules, quantitative finance features, semantic news analysis and explainable research workflows can be assembled into a credible market intelligence system.

## Architecture

| Layer | Stack |
| --- | --- |
| Frontend | Next.js, React, Plotly, dark financial intelligence UI |
| Backend | FastAPI, Pydantic, APScheduler live services |
| Database | PostgreSQL, SQLAlchemy, Alembic |
| Market data | yfinance, Yahoo Chart API and Stooq provider chain |
| News ingestion | RSS feeds, public web-search RSS, deduplication, ticker linking |
| AI sentiment | FinBERT primary, VADER baseline |
| Semantic layer | sentence-transformers embeddings, semantic search, theme discovery |
| Reasoning | lightweight Qwen-compatible LLM evidence-only explanation layer |
| Time-series intelligence | statistical fallback compatible with future Chronos, TimesFM or PatchTST adapters |
| Deployment | Hugging Face Docker Space |

## AI Model Routing

Blum does not use one generic AI model for everything.

- FinBERT: financial sentiment for headlines, article summaries and company-linked news.
- VADER: baseline comparator and fallback.
- sentence-transformers: embeddings for semantic search, narrative clustering, recurring themes and links between assets, sectors and macro trends.
- Qwen-compatible lightweight LLM: structured explanations from retrieved evidence only.
- Statistical time-series module: anomalies, volatility regimes and scenario bands, ready for Chronos, TimesFM or PatchTST integration.
- Rule-based quantitative engine: scoring, ranking, risk controls and classifications.

## Data Workflow

1. Seed the asset universe with stocks, ETFs, sectors, countries, industries and descriptions.
2. Download OHLCV price history from yfinance, Yahoo Chart API and Stooq public daily data, using maximum available history when requested.
3. Store prices in PostgreSQL.
4. Start the live pipeline on application boot.
5. Fetch public RSS news plus dynamic public web-search RSS queries for assets and financial themes.
6. Deduplicate articles.
7. Link articles to tickers and sectors.
8. Run FinBERT sentiment and VADER baseline.
9. Generate embeddings for semantic retrieval.
10. Compute technical indicators and time-series anomalies.
11. Generate signal snapshots with a Blum Intelligence Score.
12. Produce AI explanations using only retrieved evidence.

## Live Runtime

When the FastAPI application starts, APScheduler launches a background intelligence worker:

- `startup_pipeline`: news ingestion, historical price collection, signal generation and ETF trend update.
- `news_refresh`: public news refresh every 10 minutes by default.
- `market_refresh`: recent OHLCV refresh and signal regeneration every 45 minutes by default.

The dashboard polls live JSON endpoints every 30 seconds and shows worker state, latest public news, sentiment distribution, source/model diagnostics and signal readiness. No generated headlines, generated prices or fabricated sentiment are shown.

Every equity and ETF surface includes an explicit market snapshot when real OHLCV data is available: last price, currency, date, provider, volume and 1D/5D/1M performance. If public providers have not returned usable prices yet, the UI shows a real-data pending state instead of a fabricated value.

## Signal Methodology

The signal engine combines:

- momentum: 1D, 5D, 1M, 3M, 6M, YTD and relative strength;
- trend quality: SMA/EMA structure, slopes, ADX, persistence and drawdown;
- volatility and risk: historical volatility, ATR, beta, downside volatility, gaps and volume spikes;
- technical indicators: RSI, MACD, Bollinger Bands, support and resistance;
- news and sentiment: FinBERT sentiment, VADER baseline, 7D/30D sentiment trend and news intensity;
- semantic themes: recurring narratives such as AI, rates, earnings, guidance, geopolitics, M&A, regulation, supply chain and innovation;
- ETF intelligence: ETF momentum, thematic confirmation and rotation;
- anomaly detection: price, volume, news and narrative divergences.

The final score is called the **Blum Intelligence Score**. It produces explainable classifications:

- Strong Watch
- Watch
- Neutral
- Avoid / Too Risky
- Contrarian Setup
- Narrative Breakout
- Technical Breakout
- Sentiment Divergence

## API Endpoints

FastAPI exposes clean JSON endpoints:

- `GET /assets`
- `GET /assets/{ticker}`
- `POST /market/update`
- `POST /news/update`
- `GET /news/live`
- `GET /sentiment/market`
- `POST /signals/run`
- `POST /pipeline/run`
- `GET /pipeline/status`
- `GET /signals/top`
- `GET /signals/{ticker}`
- `GET /sentiment/{ticker}`
- `POST /semantic-search`
- `GET /related-news?ticker=NVDA`
- `GET /themes`
- `GET /etf-trends`
- `GET /dashboard/overview`
- `GET /ai/explain/{ticker}`
- `POST /backtest/{ticker}`

Interactive API docs are available at `/docs`.

`GET /ai/explain/{ticker}` is auto-hydrating: if no signal snapshot exists yet, the backend attempts on-demand real public price hydration, ticker-specific news ingestion and signal generation before returning an explanation. If verified data is still insufficient, it returns an `Insufficient Evidence` explanation with provider diagnostics instead of fabricating a signal.

## Frontend Pages

- Case Study Home
- Intelligence Dashboard
- Asset Detail
- ETF Radar
- Theme Explorer
- Signal Lab
- Backtest
- Methodology

The UI is intentionally dense, dark and technical: Bloomberg-style information density, Linear/Vercel-style cleanliness, TradingView-style chart clarity and OpenBB-style open-source posture.

## Local Setup

```bash
cd hf-blum-mvp
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm --prefix frontend install
npm --prefix frontend run build
export DATABASE_URL=postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/blum
PYTHONPATH=backend uvicorn app.main:app --host 0.0.0.0 --port 7860
```

## Docker

```bash
cd hf-blum-mvp
docker build -t blum-ai-financial-intelligence .
docker run --rm -p 7860:7860 blum-ai-financial-intelligence
```

If `DATABASE_URL` is not set, the Docker demo starts an embedded PostgreSQL instance inside the container. For production-like use, provide an external PostgreSQL database:

```bash
docker run --rm -p 7860:7860 \
  -e DATABASE_URL=postgresql+psycopg2://user:password@host:5432/blum \
  blum-ai-financial-intelligence
```

## Hugging Face Spaces Deployment

Use a Docker Space. Upload the repository with:

- `Dockerfile`
- `requirements.txt`
- `backend/`
- `frontend/`
- `scripts/`
- `package.json`
- `README.md`

The Space serves the FastAPI backend and the exported Next.js frontend on port `7860`.

## Backtesting and Validation

Backtesting is included for research validation only. It reports historical hit rate, average forward return over 5D/20D/60D, max adverse excursion, max favorable excursion and false positives. It does not predict or guarantee future returns.

## Limitations

- Public RSS, Google News RSS search, Yahoo and Stooq are demo-grade public data sources, not licensed institutional feeds.
- The system does not generate synthetic prices. If public providers fail or rate-limit, the affected assets are reported as missing instead of being filled with fake data.
- FinBERT, embeddings and LLM model loading depend on runtime memory and Hugging Face model availability.
- The reasoning layer must not invent data; it is constrained to retrieved evidence.
- Signal classifications are research triage outputs, not investment recommendations.
- PostgreSQL is the database layer; the Docker demo can start an embedded PostgreSQL instance for Hugging Face convenience.

## Financial Disclaimer

This project is for educational, research and technical case-study purposes only. It does not constitute financial advice, investment advice, a recommendation, a trading signal, portfolio guidance or an offer to buy or sell any security. Always perform independent research and consult qualified professionals before making financial decisions.

## Roadmap

The execution roadmap is tracked in [`ROADMAP.md`](ROADMAP.md). It covers Docker Space stabilization, data ingestion reliability, AI model productionization, semantic intelligence, signal engine upgrades, ETF intelligence, backtesting, frontend UX, provider architecture, testing and open-source polish.

## Engineering Standards

Development standards are tracked in [`ENGINEERING_STANDARDS.md`](ENGINEERING_STANDARDS.md). The project explicitly rejects placeholders, fabricated data and synthetic market-data fallbacks. Every shipped increment should be evidence-bound, efficient, explainable and verified.

## Contributing

Contributions should preserve the project philosophy: transparent evidence, modular models, explainable scoring, no fabricated data and no investment recommendations.
