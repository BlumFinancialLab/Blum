# Blum AI Financial Intelligence Roadmap

This roadmap is the execution plan for turning Blum into a credible open-source AI financial intelligence platform. Each phase should ship with working code, API coverage, UI coverage, documentation and explicit limitations.

## Phase 0 - Stabilize Docker Space Deployment

Goal: make the Hugging Face Docker Space build and boot reliably.

Deliverables:

- Confirm Docker build succeeds on Hugging Face Spaces.
- Verify FastAPI serves the exported Next.js frontend on port `7860`.
- Verify embedded PostgreSQL starts when `DATABASE_URL` is not provided.
- Verify `/health`, `/docs`, `/assets` and `/dashboard/overview`.
- Add lightweight demo mode if model dependencies exceed Space resources.
- Add clear build/runtime troubleshooting notes.

Exit criteria:

- Public Space loads without manual intervention.
- API docs are reachable.
- Seed asset universe is visible.
- No Gradio remnants remain in runtime metadata.

## Phase 1 - Data Ingestion Reliability

Goal: make prices, assets and news ingestion reliable enough for a serious demo.

Deliverables:

- Harden yfinance provider with retries, partial failures and provider status.
- Add incremental OHLCV updates instead of replacing recent rows blindly.
- Improve RSS source health diagnostics.
- Add article text extraction fallback with `newspaper3k` and BeautifulSoup.
- Add stronger duplicate detection across titles, URLs and canonical keys.
- Add source reliability and stale-data scoring.
- Add ingestion audit logs.

Exit criteria:

- `/market/update` reports per-ticker success/failure.
- `/news/update` reports source-level diagnostics.
- Duplicate articles are materially reduced.
- Failed feeds do not break the pipeline.

## Phase 2 - AI Model Productionization

Goal: make AI model usage explicit, measurable and robust under limited compute.

Deliverables:

- Add model availability endpoint.
- Add lazy loading and memory-aware fallback for FinBERT, embeddings and LLM.
- Persist model run metadata for every sentiment and AI insight.
- Add prompt templates with strict evidence-only formatting.
- Add deterministic fallback explanations for low-resource mode.
- Add batch sentiment processing for article updates.
- Add configurable model names through Space variables.

Exit criteria:

- `/ai/explain/{ticker}` returns structured JSON with models used.
- FinBERT is the primary sentiment engine when available.
- VADER is clearly labeled as baseline/fallback.
- No explanation claims facts absent from retrieved evidence.

## Phase 3 - Semantic Intelligence Layer

Goal: turn news embeddings into useful narrative intelligence, not just search.

Deliverables:

- Persist FAISS indexes by namespace or rebuild them efficiently at startup.
- Add semantic cluster snapshots in `ThemeCluster`.
- Link themes to assets, sectors, ETFs and macro drivers.
- Add theme trend over time.
- Add narrative intensity, recurrence and polarization metrics.
- Add `/themes/{label}` detail endpoint.
- Add UI for theme drill-down and related assets.

Exit criteria:

- Theme Explorer shows real cluster metadata.
- Semantic search returns relevant articles with similarity scores.
- Each high-scoring signal can cite related semantic themes.

## Phase 4 - Signal Engine Upgrade

Goal: make the Blum Intelligence Score more defensible and auditable.

Deliverables:

- Split score modules into separate files: momentum, trend, risk, technicals, sentiment, semantics, ETF and anomaly.
- Add score versioning.
- Store full score inputs and normalized factors.
- Add factor weights in config.
- Add confidence score distinct from signal score.
- Add signal lifecycle states: new, confirmed, faded, invalidated.
- Add price/sentiment divergence logic with explicit thresholds.

Exit criteria:

- Every score is reproducible from stored inputs.
- UI can show why each score changed.
- `/signals/{ticker}` includes score version and factor weights.

## Phase 5 - ETF And Sector Intelligence

Goal: make ETF confirmation a first-class intelligence layer.

Deliverables:

- Map stocks to confirming ETFs and sector proxies.
- Add stock/ETF correlation analysis.
- Add ETF rotation rankings by sector and theme.
- Add ETF confirmation score into every asset signal.
- Add sector heatmap and rotation charts.
- Add ETF vs benchmark comparison views.

Exit criteria:

- ETF Radar identifies rotation leaders.
- Asset Detail shows confirming or contradicting ETFs.
- Signal explanations reference ETF confirmation when available.

## Phase 6 - Backtesting And Validation

Goal: validate historical signal behavior without implying prediction or advice.

Deliverables:

- Add walk-forward validation by score threshold and classification.
- Add benchmark-relative forward returns.
- Add false positive analysis by signal type.
- Add max adverse/favorable excursion distributions.
- Add result storage by run configuration.
- Add backtest charts: equity curve, drawdown, forward return distribution.
- Add methodology caveats in UI and API.

Exit criteria:

- Backtest page can compare classifications historically.
- API reports hit rate, average forward return and benchmark-relative behavior.
- Disclaimer is visible on every validation output.

## Phase 7 - Frontend Intelligence UX

Goal: elevate the UI from technical demo to portfolio-grade case study.

Deliverables:

- Add skeleton loading and refined error states on every page.
- Add richer Plotly charts: RSI, MACD, Bollinger Bands, sentiment timeline, score history and correlation heatmap.
- Add sortable/filterable tables.
- Add advanced Signal Lab filters.
- Add exportable signal results.
- Add responsive refinements for tablet/mobile.
- Add screenshot placeholders or generated screenshots to README.

Exit criteria:

- Dashboard immediately communicates what to watch and why.
- Asset Detail explains price, sentiment, risk, news and ETF confirmation in one flow.
- UI remains dense but readable.

## Phase 8 - Provider Architecture

Goal: make the platform extensible beyond yfinance and RSS.

Deliverables:

- Define provider interfaces for market data, news, filings, transcripts, estimates and ownership.
- Add provider registry.
- Add mock provider for tests.
- Add optional adapters for filings and public company IR pages.
- Prepare connectors for future licensed data sources.

Exit criteria:

- New providers can be added without changing signal code.
- Provider status appears in API and UI.

## Phase 9 - Testing, Observability And Quality

Goal: make the codebase credible as an open-source engineering project.

Deliverables:

- Add backend unit tests for indicators, scoring, ingestion and API.
- Add frontend component tests where practical.
- Add smoke tests for Docker startup.
- Add structured logging.
- Add error telemetry fields in API responses.
- Add CI-ready commands in README.

Exit criteria:

- Core scoring and ingestion logic are covered by tests.
- Docker smoke test catches startup regressions.
- Contributors can run checks locally.

## Phase 10 - Open Source Polish

Goal: make the repository compelling as a public case study.

Deliverables:

- Add architecture diagram.
- Add screenshots.
- Add contribution guide.
- Add issue templates.
- Add model/data limitation section.
- Add changelog.
- Add clear demo setup instructions for low-resource and full-AI modes.

Exit criteria:

- A reviewer can understand the project, run it, inspect the architecture and contribute without needing private context.

## Working Rule

Every roadmap step should ship as a complete increment:

- backend logic;
- API endpoint or schema update when needed;
- frontend visibility when user-facing;
- documentation update;
- verification command;
- explicit limitation or disclaimer when relevant.

