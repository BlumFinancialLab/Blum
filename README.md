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
| Accuracy layer | multi-provider checks, data quality, source credibility, macro/fundamental context and Blum Confidence Score |
| Strategic intelligence | Opportunity Radar, Market Narrative AI, Asset Intelligence Reports, watchlist, portfolio scenarios and community sentiment |
| Self-learning layer | signal outcome evaluation, accuracy memory, adaptive confidence, model weight versions and historical similarity cases |
| Chart intelligence | Qwen3-VL/InternVL3-ready visual chart analyst plus deterministic OHLCV technical engine |
| AI sentiment | FinBERT primary, VADER baseline |
| Semantic layer | sentence-transformers embeddings, semantic search, theme discovery |
| Reasoning | lightweight Qwen-compatible LLM evidence-only explanation layer |
| Financial Brain | finance-domain open model adapter, default `AdaptLLM/finance-chat` when enabled |
| BLUM Learning Loop | point-in-time historical simulation lab, outcome evaluation, mistake taxonomy, adaptive signal reliability and strategy memory |
| Time-series intelligence | statistical fallback compatible with future Chronos, TimesFM or PatchTST adapters |
| Deployment | Hugging Face Docker Space |

## AI Model Routing

Blum does not use one generic AI model for everything.

- FinBERT: financial sentiment for headlines, article summaries and company-linked news.
- VADER: baseline comparator and fallback.
- sentence-transformers: embeddings for semantic search, narrative clustering, recurring themes and links between assets, sectors and macro trends.
- Qwen-compatible lightweight LLM: structured explanations from retrieved evidence only.
- Blum Financial Brain: finance-domain reasoning adapter for regime interpretation, opportunity hypotheses, risk hypotheses and monitoring plans.
- Chart Vision Technical Analyst: Qwen3-VL primary VLM for visual chart interpretation when configured, InternVL3 fallback for low-confidence or failed primary visual reads.
- Deterministic Technical Analysis Engine: OHLCV-derived trend structure, levels, moving averages, RSI, MACD, Bollinger Bands, ATR, volume, gaps, divergences, volatility compression and risk/reward.
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
15. Run the 15-point accuracy and confidence audit.
16. Build the Strategic Intelligence dashboard: opportunity radar, narrative, watchlist alerts, portfolio scenario and similar-case validation.
17. Evaluate matured signal outcomes after 1D, 3D, 7D, 14D and 30D.
18. Update signal accuracy memory, source reliability, ticker/sector profiles and adaptive confidence adjustments.
19. Version scoring weights in the database when real matured outcomes justify recalibration.
20. Generate professional chart analysis from deterministic OHLCV evidence and optional Qwen3-VL/InternVL3 visual interpretation.
21. Persist chart analyses, technical levels, technical signals and chart pattern memory.
22. Run BLUM Learning Loop point-in-time simulations on random historical asset/date samples.
23. Hide future prices during prediction generation, then reveal future OHLCV only during outcome evaluation.
24. Classify mistakes, update strategy memory, recalibrate signal reliability and persist reversible model-weight versions.
25. Produce AI explanations using only retrieved evidence.

## Live Runtime

When the FastAPI application starts, APScheduler launches a background intelligence worker:

- `startup_pipeline`: news ingestion, historical price collection, signal generation and ETF trend update.
- `news_refresh`: public news refresh every 10 minutes by default.
- `market_refresh`: recent OHLCV refresh and signal regeneration every 45 minutes by default.
- `ipo_refresh`: SEC current filing refresh every 120 minutes by default.
- `data_gap_repair`: historical OHLCV continuity repair every 180 minutes by default.
- `accuracy_audit`: 15-point confidence audit every 240 minutes by default.
- `macro_refresh`: FRED public macro context refresh every 240 minutes by default.
- `fundamentals_refresh`: SEC companyfacts refresh every 720 minutes by default.
- `financial_brain_learning`: self-learning evaluation, memory refresh and confidence calibration every 360 minutes by default.
- `blum_point_in_time_learning_loop`: random historical point-in-time simulation, outcome evaluation and strategy-memory refresh every 360 minutes by default.

The dashboard polls live JSON endpoints every 30 seconds and shows worker state, latest public news, sentiment distribution, source/model diagnostics and signal readiness. No generated headlines, generated prices or fabricated sentiment are shown.

Every equity and ETF surface includes an explicit market snapshot when real OHLCV data is available: last price, currency, date, provider, volume and 1D/5D/1M performance. If public providers have not returned usable prices yet, the UI shows a real-data pending state instead of a fabricated value.

## Accuracy And Confidence Layer

Blum separates opportunity scoring from evidence quality. The **Blum Intelligence Score** ranks research candidates. The **Blum Confidence Score** measures whether the evidence behind an asset is complete, current and internally consistent.

The 15-point audit covers multi-provider price validation, corporate-action review, point-in-time consistency, per-asset data quality, entity resolution, source credibility, semantic news deduplication, structured event extraction, confidence-aware AI reasoning, contradiction checks, SEC fundamentals where available, FRED macro context, sector/ETF confirmation, historical signal validation and the final confidence label.

Missing public data lowers confidence instead of creating placeholders. No synthetic prices, headlines, filings, fundamentals, macro values or scores are generated.

## Strategic Intelligence Layer

Blum now exposes an **AI Market Intelligence Officer** surface. It answers: what should be monitored today, why it matters, which data confirms it and which risks limit conviction.

Strategic modules:

- **AI Opportunity Radar** ranks equities and ETFs for research attention using opportunity, trend, momentum, sentiment, news and risk scores.
- **Market Narrative AI** summarizes the dominant theme, emerging subthemes, beneficiary sectors, macro risks and contrary signals.
- **Asset Intelligence Report** builds a professional asset brief with overview, technical levels, sentiment, recent news, bullish/bearish scenarios, risks and similar-case validation.
- **Similar-Case Backtesting** uses real stored OHLCV when enough history exists. If sample depth is insufficient, it returns `demonstration_mode` statistics clearly labeled as non-production evidence.
- **Strategic Watchlist** stores monitored assets, score baseline, alert rules and simulated alerts.
- **AI Portfolio Scenario** produces a non-consultative hypothetical allocation with rationale, risk context, monitoring plan and defensive alternative.
- **Community & Sentiment Intelligence** summarizes public-news sentiment themes, discussed assets and possible hype-bubble review flags.

The wording policy explicitly avoids `buy`, `sell`, guaranteed profit or trading instructions. Surfaces use language such as monitor, observe, setup, scenario, risk review and research candidate.

## BLUM Chat

BLUM Chat is the conversational voice of the Blum analytical engine. It is not a generic chatbot. It is a multilingual financial intelligence assistant that retrieves internal Blum evidence and converts it into structured research dialogue.

Supported languages:

- Italian
- English
- German
- French
- Spanish

The chat pipeline:

1. Detects the user language.
2. Detects intent: asset analysis, comparison, opportunity search, narrative analysis or selective setup planning.
3. Extracts tickers, company names, ETFs, sectors and market terms such as FTSE MIB, DAX, S&P 500 and Nasdaq.
4. Retrieves Blum context: ranking, signals, OHLCV snapshots, deterministic technical analysis, SEC companyfacts fundamentals, news, sentiment, narratives, semantic evidence and reasoning memory.
5. Builds a structured answer with summary, observed data, technical analysis, fundamental analysis, sentiment/news/narrative, bull/base/bear scenario, relevant levels, risks, informational operating view and missing data.
6. Runs an anti-hallucination pass by surfacing missing prices, stale data, missing fundamentals, missing news or limited historical memory.
7. Stores chat sessions and messages in PostgreSQL for future personalization and training-memory workflows.

BLUM Chat includes an internal **Market Sniper Mode**. This is a selective research mode, not a trading signal. It identifies informational setup zones, confirmation conditions, invalidation, target zones, risk/reward geometry, confidence and what could go wrong. It never presents an order and never guarantees an outcome.

Open-source model interface:

- `LLMProvider` contract for OpenAI-compatible APIs, local models, Hugging Face Inference, Ollama, vLLM and llama.cpp.
- Deterministic evidence-bound fallback when no external model is configured.
- Future-compatible with Llama, Mistral, Qwen, DeepSeek, Phi, FinGPT and finance models hosted on Hugging Face.

Chat persistence tables:

- `chat_sessions`
- `chat_messages`

Primary endpoints:

- `POST /api/chat`
- `GET /api/chat/context`
- `GET /api/chat/assets/{ticker}`
- `GET /api/chat/signals/{ticker}`
- `GET /api/chat/history`
- Legacy compatible: `POST /chat/financial`

## Self-Learning Financial Brain

Blum now includes a measurable self-learning layer called **Blum Financial Brain**. This is not artificial consciousness and not autonomous trading. It is a controlled financial intelligence memory that checks whether prior signals were useful after real market outcomes arrive.

The learning engine evaluates each signal after:

- 1 trading-day horizon proxy;
- 3-day horizon;
- 7-day horizon;
- 14-day horizon;
- 30-day horizon.

Each evaluation stores ticker, signal type, initial confidence, initial sentiment, initial momentum, news evidence, expected direction, price at signal, price after horizon, max drawdown, max upside, realized return, post-signal volatility, outcome, explanation quality and data quality.

The memory layer persists:

- `signal_evaluations`
- `signal_outcomes`
- `model_weight_versions`
- `learning_events`
- `historical_similarity_cases`
- `confidence_adjustments`
- `source_reliability_scores`
- `ticker_accuracy_profiles`
- `sector_accuracy_profiles`

Adaptive confidence combines historical accuracy, sector and ticker memory, linked source reliability, price/news coherence, volatility and similar past cases. The system can increase or reduce confidence, but every adjustment is logged and explainable.

Weight recalibration is database-only and reversible. Blum can create a new `model_weight_versions` row after enough matured outcomes exist, but it does not modify source code, execute trades or generate deterministic financial recommendations. If there is not enough historical evidence, it explicitly returns `insufficient_sample`.

The UI exposes:

- Dashboard: Financial Brain status, learning state, historical accuracy, 7D/30D success rate, calibration, best/weakest signal types, data quality and drift warning.
- Asset Detail: Blum Memory, historical similarity, confidence evolution, outcome history and what was learned.
- Signal Lab: pre-signal confidence, post-evaluation result, learning impact, weight status, similar past evidence and invalidating conditions.

Governance rules are enforced in product language and API output: no absolute certainty, no direct financial advice, no autonomous trading, no self-modifying code and clear separation between observed data, inference and hypothesis.

## BLUM Learning Loop

BLUM Learning Loop is a separate point-in-time simulation lab. It does not try to create a fake 100% win rate. Its objective is to improve statistical edge, reduce false positives, calibrate confidence and document which reasoning patterns work or fail under different regimes.

Each cycle:

1. Selects a random active stock or ETF with sufficient stored historical OHLCV.
2. Selects a historical analysis date with enough future data available for later evaluation.
3. Builds a point-in-time packet using only data known on or before that date.
4. Generates short, mid and long horizon predictions.
5. Persists the forecast before outcome evaluation.
6. Reveals future OHLCV only to evaluate the forecast.
7. Measures direction correctness, target hit, invalidation hit, max favorable excursion, max adverse excursion, drawdown, realized return, false positives, false negatives, missed opportunities and confidence calibration.
8. Classifies mistakes such as weak volume confirmation, sentiment overestimation, volatility expansion, support/resistance failure, overconfidence or insufficient data.
9. Updates strategy memory and signal-factor reliability.
10. Writes a new model-weight version when enough historical outcomes justify a gradual recalibration.

New persistence tables:

- `learning_runs`
- `historical_predictions`
- `prediction_outcomes`
- `mistake_analysis`
- `signal_performance`
- `strategy_memory`
- `model_versions`
- `learning_metrics`

Configuration:

```bash
export LEARNING_LOOP_ENABLED=true
export LEARNING_BATCH_SIZE=100
export LEARNING_MAX_DAILY_RUNS=1000
export LEARNING_RANDOM_SEED=
export LEARNING_MIN_HISTORY_YEARS=3
export LEARNING_ASSET_UNIVERSE=stocks,etfs
export LEARNING_EVALUATION_MODE=walk_forward
```

The loop includes anti-overfitting controls:

- temporal point-in-time sampling;
- walk-forward evaluation;
- sample-size guardrails;
- multi-ticker, multi-sector and multi-regime coverage metrics;
- warnings for suspiciously perfect small-sample hit rates;
- confidence updates that are gradual and reversible;
- no self-modifying source code;
- no autonomous trading.

The chatbot reads BLUM Learning Loop memory when answering setup-quality questions such as: “This setup has worked in the past?”, “What is the historical false-positive risk?”, “What has BLUM learned about this pattern?” and “Which factor should reduce confidence?”.

## Blum Financial Model

Blum now includes the foundation for a proprietary reasoning model called **Blum Financial Model**. This is not another chatbot layer and it does not train automatically inside the Space. It is the infrastructure that preserves, evaluates and exports Blum's accumulated financial reasoning so a future **Blum Analyst** model can be trained from Blum's own thesis history.

The model layer captures every persisted asset thesis into a proprietary knowledge record with:

- market context: timestamp, market regime, volatility regime, sector context, macro placeholders, breadth context and risk sentiment;
- asset context: ticker, sector, industry, price action, volume profile, technical indicators, sentiment indicators and news indicators;
- Blum reasoning: executive thesis, why now, supporting evidence, contradicting evidence, risks, invalidation conditions, narrative analysis, confidence and conviction score;
- prediction horizons: 1D, 3D, 7D, 14D and 30D outcome-evaluation slots;
- thesis quality: reasoning depth, consistency, contradiction handling, confidence calibration, historical alignment, narrative quality and explainability quality;
- self critique: analyst view, skeptic view, historical view and balanced final view;
- training sample: JSON-ready input/output and chat messages for future supervised fine-tuning or preference learning.

New persistence tables include:

- `blum_knowledge_records`
- `blum_thesis_outcomes`
- `blum_reasoning_memory`
- `blum_training_examples`
- `blum_thesis_quality_scores`
- `blum_self_critiques`
- `blum_narrative_memory`
- `blum_regime_memory`
- `blum_knowledge_graph_nodes`
- `blum_knowledge_graph_edges`
- `blum_dataset_exports`
- `blum_model_training_jobs`

The reasoning model APIs are backend-only:

- `GET /model/status`
- `POST /model/capture/{ticker}`
- `POST /model/capture-all`
- `POST /model/evaluate-outcomes`
- `POST /model/run-learning-cycle`
- `GET /model/knowledge`
- `GET /model/knowledge/{record_id}`
- `GET /model/memory/search?q=...`
- `POST /model/dataset/build`
- `POST /model/training/export`
- `GET /model/training/manifest`
- `POST /model/training/jobs`
- `GET /model/quality`
- `GET /model/self-critique/{record_id}`
- `GET /model/narratives`
- `GET /model/regimes`
- `GET /model/graph`

Training export uses JSONL and targets future Hugging Face training workflows for Qwen, Llama or Mistral with LoRA, full fine-tuning, DPO or preference learning. The Space only creates dataset and job-plan records; it does not launch fine-tuning automatically.

The objective is not to predict stock prices. The objective is to learn how Blum reasons: explain, contextualize, compare, critique, calibrate confidence and improve future thesis quality.

The autonomous Blum Financial Model cycle is server-side and evidence-bound. When `BLUM_ENABLE_LEARNING_LOOP=true`, it runs on startup, during market refresh and on its own interval controlled by `BLUM_MODEL_CYCLE_MINUTES` and `BLUM_MODEL_CYCLE_LIMIT`. Each cycle captures recent signal reasoning, evaluates matured thesis outcomes, refreshes training examples and logs a `blum_model_autonomous_cycle` learning event. It updates database memory only; it does not self-modify source code and it does not execute trades.

## Autonomous Research Engine

Blum now runs a server-side autonomous research cycle by default. Manual refresh buttons are diagnostics; normal operation does not require user input. The default cycle is controlled by:

```bash
export BLUM_ENABLE_AUTONOMOUS_ENGINE=true
export BLUM_AUTONOMOUS_CYCLE_MINUTES=20
export BLUM_AUTONOMOUS_REPAIR_LIMIT=20
```

The autonomous cycle executes in this strict order:

1. Refresh Hugging Face financial dataset catalog.
2. Update macro context.
3. Update SEC companyfacts fundamentals.
4. Repair historical market-memory gaps for missing, short or stale OHLCV assets.
5. Run an incremental price refresh. Deep `max` backfill is used only when the stored memory is not sufficiently hydrated.
6. Ingest public news and sentiment.
7. Generate signal snapshots.
8. Update ETF intelligence.
9. Update IPO radar.
10. Run accuracy audit.
11. Run Blum Financial Model reasoning and outcome learning.
12. Run BLUM Learning Loop point-in-time historical simulation batch.
13. Persist embedded PostgreSQL backup when configured.

Every cycle creates an `autonomous_engine_runs` row and a `learning_events` audit entry. `/pipeline/status` exposes the current stage, completed stages and compact stage diagnostics while the worker is running. Deep historical backfill is processed in batches so startup remains observable and the engine keeps cycling. If a provider fails, the run is marked `degraded` with the failing stage and traceback, rather than hiding the issue.

New APIs:

- `GET /autonomous/status`
- `POST /autonomous/run`
- `GET /datasets/sources`
- `POST /datasets/refresh`

## Hugging Face Dataset Intelligence

Blum catalogs real Hugging Face datasets for historical prices, SEC filings, earnings transcripts, finance reasoning and benchmark evidence. The catalog is metadata-first and incremental by design: large corpora are validated through Dataset Viewer/parquet metadata before any targeted ingestion is attempted.

Initial curated sources include:

- `defeatbeta/yahoo-finance-data`
- `paperswithbacktest/Stocks-Daily-Price`
- `TeraflopAI/SEC-EDGAR`
- `kurry/sp500_earnings_transcripts`
- `glopardo/sp500-earnings-transcripts`
- `paperswithbacktest/Stocks-Quarterly-Earnings`
- `c3po-ai/edgar-corpus`
- `PatronusAI/financebench`
- `BUPT-Reasoning-Lab/FinanceReasoning`
- `jlh-ibm/earnings_call`
- `younginpiniti/us-stocks-daily-all`
- `sfd-anonymous/edgar-forecast-benchmark`

The catalog is stored in `external_dataset_sources` with dataset id, source domain, license, priority, ingestion mode, Dataset Viewer status, parquet metadata and usage policy. Blum does not copy massive datasets blindly and does not fabricate missing evidence.

## Chart Vision Technical Analyst

Blum includes a dedicated technical chart intelligence module. It is designed to read financial chart images when a vision model is configured, but it never relies only on visual interpretation.

The module combines:

- **Qwen3-VL** as the primary configurable vision-language model for chart screenshots.
- **InternVL3** as a fallback model for low-confidence or failed visual interpretation.
- A deterministic OHLCV technical analysis engine for objective indicator and level calculation.
- Blum Financial Brain memory for historical context and similarity.
- Existing sentiment/news context for confirmation or contradiction checks.

The deterministic engine calculates:

- trend direction;
- higher highs, higher lows, lower highs and lower lows;
- support and resistance zones;
- EMA 9/21/50/200 and SMA 20/50/200;
- RSI, MACD, Bollinger Bands and ATR;
- relative volume and volume pressure;
- volatility regime and compression;
- gaps, consolidation zones and pullback quality;
- accumulation/distribution bias;
- price/RSI and price/MACD divergences;
- breakout probability;
- trend strength;
- risk/reward geometry.

The hybrid layer outputs trend summary, key levels, bullish/bearish/neutral evidence, confirmation signals, contradiction signals, invalidation level, risk zone, opportunity zone, confidence, scenarios, what to watch next and historical chart similarity.

Model serving is configurable:

```bash
export CHART_VISION_MODEL=Qwen/Qwen3-VL
export CHART_VISION_FALLBACK_MODEL=OpenGVLab/InternVL3
export CHART_VISION_MODE=disabled   # local | remote | disabled
export CHART_VISION_MIN_CONFIDENCE=0.70
export CHART_VISION_REMOTE_URL=
export CHART_VISION_REMOTE_TOKEN=
```

Default Docker demo behavior is `CHART_VISION_MODE=disabled`, so the app remains reliable on CPU Spaces. The UI displays: `Vision model unavailable, deterministic analysis active`. Use `remote` mode for a production VLM endpoint.

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
- `GET /data/coverage`
- `POST /data/repair`
- `GET /accuracy/overview`
- `POST /accuracy/run`
- `GET /accuracy/{ticker}`
- `GET /validation/signals`
- `GET /macro/overview`
- `POST /macro/update`
- `GET /fundamentals/{ticker}`
- `POST /fundamentals/update`
- `GET /intelligence/executive`
- `GET /intelligence/opportunities`
- `GET /intelligence/narrative`
- `GET /intelligence/community`
- `GET /intelligence/watchlist`
- `POST /intelligence/watchlist/{ticker}`
- `GET /intelligence/portfolio-scenario`
- `GET /intelligence/reports/{ticker}`
- `GET /intelligence/backtest/{ticker}`
- `POST /api/chat`
- `GET /api/chat/context`
- `GET /api/chat/assets/{ticker}`
- `GET /api/chat/signals/{ticker}`
- `GET /api/chat/history`
- `POST /chat/financial`
- `GET /brain/status`
- `GET /brain/accuracy`
- `GET /brain/learning-events`
- `GET /brain/signal-evaluations`
- `GET /brain/asset-memory/{ticker}`
- `GET /brain/confidence-history/{ticker}`
- `POST /brain/evaluate-signals`
- `POST /brain/recalculate-weights`
- `POST /brain/run-learning-cycle`
- `GET /learning/status`
- `GET /learning/dashboard`
- `GET /learning/runs`
- `GET /learning/predictions`
- `GET /learning/memory`
- `POST /learning/run-cycle`
- `POST /chart/analyze-image`
- `POST /chart/analyze-ticker`
- `GET /chart/technical-report/{ticker}`
- `GET /chart/levels/{ticker}`
- `GET /chart/signals/{ticker}`
- `GET /chart/history/{ticker}`
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
- Executive Dashboard
- AI Opportunity Radar
- Market Narrative AI
- Asset Intelligence Report
- AI Portfolio Scenario
- Market Brain
- BLUM Learning Loop
- Chart Analyst
- BLUM Chat
- Asset Detail
- Blum Memory
- Stock Radar
- ETF Radar
- IPO Radar
- Narratives / Theme Explorer (`/narratives`, backed by `/themes` API)
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

Optional self-learning cadence:

```bash
export BLUM_ENABLE_LEARNING_LOOP=true
export BLUM_LEARNING_LOOP_MINUTES=360
export LEARNING_BATCH_SIZE=100
export LEARNING_MAX_DAILY_RUNS=1000
export LEARNING_MIN_HISTORY_YEARS=3
export LEARNING_ASSET_UNIVERSE=stocks,etfs
export LEARNING_EVALUATION_MODE=walk_forward
export BLUM_MODEL_CYCLE_MINUTES=5
export BLUM_MODEL_CYCLE_LIMIT=120
export BLUM_ENABLE_HF_DATASET_CATALOG=true
export BLUM_HF_DATASET_REFRESH_HOURS=24
```

The learning loops only update database memory, confidence adjustments, proprietary reasoning examples and reversible scoring-weight versions.

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

For Hugging Face Docker demos without an external database, the startup script writes periodic embedded PostgreSQL backups to `/data/blum/embedded_postgres_blum.sql` and restores them on startup when the public schema is empty. This protects the learning memory only when Hugging Face persistent storage is enabled for the `/data` mount. The strict no-reset configuration is still an external `DATABASE_URL`.

## Hugging Face Spaces Deployment

Use a Docker Space. Upload the repository with:

- `Dockerfile`
- `requirements.txt`
- `backend/`
- `frontend/`
- `scripts/`
- `package.json`
- `README.md`

## Deployment Visibility

The UI exposes `/system/status` in the sidebar and dashboard. If the GUI looks unchanged after an upload, check:

- `app_version` must show the latest deployed version.
- `feature_set` must show the expected feature bundle.
- `persistence.mode` must be `external_postgres` for strict no-reset durability, or `embedded_postgres` with a populated backup file plus persistent `/data` storage for demo durability.
- `GET /autonomous/status` shows the latest autonomous run, stage diagnostics, readiness score and dataset catalog status.
- `POST /system/persistence/backup` exists as an administrative recovery endpoint; normal operation persists through the autonomous worker.
- `Financial Brain` shows `fallback mode` unless `BLUM_ENABLE_FINANCIAL_BRAIN_MODEL=true`.
- Hugging Face serves the previous Docker image until the new build finishes successfully.
- Existing Market Brain snapshots are refreshed by the autonomous worker after deployment.
- Hard-refresh the browser if old static Next.js chunks are cached.

The Space serves the FastAPI backend and the exported Next.js frontend on port `7860`.

## Backtesting and Validation

Backtesting is included for research validation only. It reports historical hit rate, average forward return over 5D/20D/60D, max adverse excursion, max favorable excursion and false positives. It does not predict or guarantee future returns.

## Limitations

- Public RSS, Google News RSS search, Yahoo and Stooq are demo-grade public data sources, not licensed institutional feeds.
- SEC EDGAR current feeds are public filing evidence. They do not cover private-company rumor, expected listings without filings or licensed IPO calendars.
- The system does not generate synthetic prices. If public providers fail or rate-limit, the affected assets are reported as missing instead of being filled with fake data.
- FinBERT, embeddings and LLM model loading depend on runtime memory and Hugging Face model availability.
- Qwen3-VL and InternVL3 chart vision are optional because multimodal models can exceed CPU Space resources. Deterministic OHLCV technical analysis remains active without them.
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
