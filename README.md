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
| Backend | FastAPI, Pydantic, APScheduler-ready services |
| Database | PostgreSQL, SQLAlchemy, Alembic |
| Market data | yfinance provider module, designed for future providers |
| News ingestion | RSS feeds, deduplication, ticker linking |
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
2. Download OHLCV price history from yfinance.
3. Store prices in PostgreSQL.
4. Fetch public RSS news.
5. Deduplicate articles.
6. Link articles to tickers and sectors.
7. Run FinBERT sentiment and VADER baseline.
8. Generate embeddings for semantic retrieval.
9. Compute technical indicators and time-series anomalies.
10. Generate signal snapshots with a Blum Intelligence Score.
11. Produce AI explanations using only retrieved evidence.

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
- `POST /signals/run`
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

- Public RSS and yfinance are demo-grade public data sources, not licensed institutional feeds.
- FinBERT, embeddings and LLM model loading depend on runtime memory and Hugging Face model availability.
- The reasoning layer must not invent data; it is constrained to retrieved evidence.
- Signal classifications are research triage outputs, not investment recommendations.
- PostgreSQL is the database layer; the Docker demo can start an embedded PostgreSQL instance for Hugging Face convenience.

## Financial Disclaimer

This project is for educational, research and technical case-study purposes only. It does not constitute financial advice, investment advice, a recommendation, a trading signal, portfolio guidance or an offer to buy or sell any security. Always perform independent research and consult qualified professionals before making financial decisions.

## Roadmap

- Add provider adapters for filings, transcripts, estimates and ownership.
- Add real vector indexes with FAISS persisted by asset and article namespace.
- Add Chronos, TimesFM or PatchTST time-series adapters when demo resources allow.
- Add portfolio watchlist import/export.
- Add more rigorous walk-forward validation.
- Add source reliability scoring and stale-data controls.
- Add contributor-friendly plugin system for data providers and model adapters.

## Contributing

Contributions should preserve the project philosophy: transparent evidence, modular models, explainable scoring, no fabricated data and no investment recommendations.

