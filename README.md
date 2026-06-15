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
| Filing intelligence | SEC EDGAR current filing feeds for S-1, F-1 and 424B prospectus forms |
| AI sentiment | FinBERT primary, VADER baseline |
| Semantic layer | sentence-transformers embeddings, semantic search, theme discovery |
| Reasoning | lightweight Qwen-compatible LLM evidence-only explanation layer |
| Financial Brain | finance-domain open model adapter, default `AdaptLLM/finance-chat` when enabled |
| Time-series intelligence | statistical fallback compatible with future Chronos, TimesFM or PatchTST adapters |
| Deployment | Hugging Face Docker Space |

## AI Model Routing

Blum does not use one generic AI model for everything.

- FinBERT: financial sentiment for headlines, article summaries and company-linked news.
- VADER: baseline comparator and fallback.
- sentence-transformers: embeddings for semantic search, narrative clustering, recurring themes and links between assets, sectors and macro trends.
- Qwen-compatible lightweight LLM: structured explanations from retrieved evidence only.
- Blum Financial Brain: finance-domain reasoning adapter for regime interpretation, opportunity hypotheses, risk hypotheses and monitoring plans.
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
12. Scan SEC EDGAR current filings for IPO and final prospectus evidence.
13. Score IPO/pre-listing candidates through a separate readiness, probability, narrative and risk model.
14. Build a Market Brain snapshot that combines stocks, ETFs, news, sentiment, IPO evidence, scenarios and risk alerts.
15. Produce AI explanations using only retrieved evidence.

## Live Runtime

When the FastAPI application starts, APScheduler launches a background intelligence worker:

- `startup_pipeline`: news ingestion, historical price collection, signal generation and ETF trend update.
- `news_refresh`: public news refresh every 10 minutes by default.
- `market_refresh`: recent OHLCV refresh and signal regeneration every 45 minutes by default.
- `ipo_refresh`: SEC current filing refresh every 120 minutes by default.

The dashboard polls live JSON endpoints every 30 seconds and shows worker state, latest public news, sentiment distribution, source/model diagnostics and signal readiness. No generated headlines, generated prices or fabricated sentiment are shown.

Every equity and ETF surface includes an explicit market snapshot when real OHLCV data is available: last price, currency, date, provider, volume and 1D/5D/1M performance. If public providers have not returned usable prices yet, the UI shows a real-data pending state instead of a fabricated value.

## Market Brain

The Market Brain is Blum's high-level reasoning orchestrator. It is not a single model that invents an answer. It combines:

- latest stock signal snapshots;
- ETF rotation and thematic confirmation;
- market-wide FinBERT/VADER sentiment records;
- live public news intensity;
- stored OHLCV-derived trend and risk metrics;
- SEC IPO/pre-listing filing evidence;
- explicit evidence gaps and source diagnostics.

The output includes current regime, forward scenarios, opportunity stack, risk alerts, model stack and an evidence ledger. It is a research-priority engine, not a recommendation system.

The Brain also persists snapshot history and compares each run with the previous one. The change log highlights regime changes, score movement, top stock/ETF/IPO leader changes and risk-count shifts. A contradiction engine flags price/sentiment conflicts, overbought high-risk setups and market-wide narrative conflicts. An event graph links themes, stocks, ETFs, IPO candidates and live news into a compact intelligence map.

### Blum Financial Brain

Blum includes a dedicated financial-domain AI brain adapter. The default configured open model is `AdaptLLM/finance-chat`, a finance-domain chat model. It is opt-in through `BLUM_ENABLE_FINANCIAL_BRAIN_MODEL=true` because 7B finance models can exceed free CPU Space resources. When the model is disabled or cannot load, Blum serves the same JSON contract through a deterministic evidence engine, clearly labeled as fallback.

The Financial Brain produces market thesis, regime interpretation, opportunity hypotheses, risk hypotheses, contradictions to resolve, monitoring plan, confidence and limitations. It receives only the Market Brain evidence packet and is instructed not to invent prices, target prices, listing dates, valuations, forecasts or recommendations.

## IPO And Pre-Listing Intelligence

IPO Radar scans SEC EDGAR current filing feeds for `S-1`, `S-1/A`, `F-1`, `F-1/A`, `424B1` and `424B4` forms. It also surfaces stored public news narratives that mention IPOs, listings, prospectuses, market debuts and SPACs.

For deeper issuer history, the backend can query the official SEC company submissions API at `data.sec.gov`. The IPO Radar UI exposes SEC filing history and can persist additional IPO-related filings into PostgreSQL.

The IPO score separates:

- readiness score;
- listing probability proxy;
- narrative heat;
- filing quality;
- valuation or risk-term pressure;
- final opportunity score.

No listing date, valuation, ticker or private-company claim is fabricated. Empty radar sections mean no public evidence has been stored yet.

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
- `GET /themes/{label}`
- `GET /etf-trends`
- `GET /stock-radar`
- `POST /stock-radar/update`
- `GET /ipo-radar`
- `POST /ipo-radar/update`
- `GET /ipo-radar/sec-submissions/{cik}`
- `GET /market-brain`
- `GET /market-brain/latest`
- `GET /market-brain/history`
- `POST /market-brain/run`
- `GET /ai/models/status`
- `GET /dashboard/overview`
- `GET /ai/explain/{ticker}`
- `POST /backtest/{ticker}`

Interactive API docs are available at `/docs`.

`GET /ai/explain/{ticker}` is auto-hydrating: if no signal snapshot exists yet, the backend attempts on-demand real public price hydration, ticker-specific news ingestion and signal generation before returning an explanation. If verified data is still insufficient, it returns an `Insufficient Evidence` explanation with provider diagnostics instead of fabricating a signal.

## Frontend Pages

- Case Study Home
- Intelligence Dashboard
- Market Brain
- Asset Detail
- Stock Radar
- ETF Radar
- IPO Radar
- Theme Explorer
- Signal Lab
- Backtest
- Methodology

The UI is intentionally dense, dark and technical: Bloomberg-style information density, Linear/Vercel-style cleanliness, TradingView-style chart clarity and OpenBB-style open-source posture.

Signal surfaces include score version, confidence score and lifecycle state (`new`, `confirmed`, `strengthening`, `active`, `faded`, `invalidated`) so the platform can show whether a signal is emerging, durable or deteriorating.

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

Optional full Financial Brain model loading:

```bash
export BLUM_ENABLE_FINANCIAL_BRAIN_MODEL=true
export BLUM_FINANCIAL_BRAIN_MODEL=AdaptLLM/finance-chat
```

Keep this disabled on constrained CPU demos unless enough memory is available. The deterministic Financial Brain fallback remains evidence-bound and transparent.

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
- SEC EDGAR current feeds are public filing evidence. They do not cover private-company rumor, expected listings without filings or licensed IPO calendars.
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
