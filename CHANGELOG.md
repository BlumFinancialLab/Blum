# Changelog

## v2.0.0 | project-split

- Introduced the formal BLUM Engine / BLUM Analyst / BLUM Runtime architecture split.
- Added `backend/app/engine` with headless Engine contracts, module catalog, event contract and `BlumEngineFacade`.
- Added `backend/app/runtime` with runtime responsibility contracts and `BlumRuntimeFacade`.
- Added `backend/app/analyst` with the future `Italianhype/Blum-Analyst` dataset contract and export pipeline wrapper.
- Added API endpoints:
  - `GET /api/engine/status`
  - `GET /api/engine/contracts`
  - `GET /api/runtime/status`
  - `GET /api/runtime/contracts`
  - `GET /api/analyst/status`
  - `GET /api/architecture/contracts`
- Updated runtime identity to `2.0.0 | project-split`.
- Kept existing application APIs and financial services backward-compatible.
- Updated the training dataset export script to route through the Analyst dataset boundary.

## v1.1.0 | trader-brain

- Re-centered BLUM around one product objective: becoming progressively better at paper-trading decisions through evidence and learning.
- Added `TraderBrainService`, a read-only master read model for Brain, Training Ground, Paper Trading and Alpha pages.
- Added API endpoints:
  - `GET /api/trader-brain/brain`
  - `GET /api/trader-brain/training-ground`
  - `GET /api/trader-brain/paper-trading`
  - `GET /api/trader-brain/alpha`
- Added runtime snapshot types for Trader Brain, Training Ground, Paper Trading and Alpha summaries.
- Simplified primary navigation to four pages: Brain, Training, Paper Trading and Alpha.
- Replaced legacy `/dashboard`, `/learning` and `/copy-trading` pages with lightweight aliases to the new product pages.
- Kept all backend engines, APIs and historical data intact for compatibility.
- Added architecture review document for the Trader Brain refactor.

## v1.0.0 | alpha-operating-system

- Promoted runtime identity from `market-sniper-engine-v1` to `alpha-operating-system`.
- Added Trading Game readiness diagnostics so the Learning page explains whether evidence is ready, building, stale, insufficient, failed or data-quality blocked.
- Added compact brain command endpoints for Command Center capability status, learning evolution, benchmark truth and copy readiness.
- Added Alpha Readiness, Edge Map and Alpha Gates read-only services.
- Added paper-copy persistent models and paper-copy operating endpoints.
- Updated Learning Trading Game tab to load readiness first and avoid permanent generic loading.
- Updated Copy Trading page to read the paper-copy operating summary.
- Preserved existing Trading Game, Learning Loop, Market Sniper, Decision Intelligence and snapshot-first runtime behavior.
