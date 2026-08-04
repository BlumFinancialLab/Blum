---
title: Blum AI Financial Intelligence
emoji: 📈
colorFrom: yellow
colorTo: gray
sdk: docker
app_port: 7860
short_description: Open-source evidence-bound financial decision intelligence.
tags: [financial-analysis, quantitative-finance, algorithmic-trading, paper-trading, ai, fastapi, nextjs, forex, stock-market]
pinned: false
---

<div align="center">

# BLUM

### Open-source financial decision intelligence

BLUM studies markets, records decisions, simulates execution and learns from
measured outcomes. It is designed to explain whether its reasoning is improving,
not to manufacture confidence or promise returns.

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-2563eb.svg)](LICENSE)
[![GitHub](https://img.shields.io/github/stars/BlumFinancialLab/Blum?style=flat&label=GitHub)](https://github.com/BlumFinancialLab/Blum)
[![Hugging Face Space](https://img.shields.io/badge/Hugging%20Face-live%20Space-f5c518.svg)](https://huggingface.co/spaces/Italianhype/Blum)
[![Model](https://img.shields.io/badge/model-BLUM%20Finance-f97316.svg)](https://huggingface.co/Italianhype/Blum)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776ab.svg)](https://www.python.org/)
[![FastAPI + Next.js](https://img.shields.io/badge/runtime-FastAPI%20%2B%20Next.js-111827.svg)](#architecture)

[Live application](https://italianhype-blum.hf.space) ·
[Documentation](#documentation) ·
[Model](https://huggingface.co/Italianhype/Blum) ·
[Discussions](https://github.com/BlumFinancialLab/Blum/discussions) ·
[Contributing](CONTRIBUTING.md)

</div>

## What BLUM is

BLUM is an open-source research system for quantitative finance, financial
machine learning, equities and Forex paper trading. Its core loop is explicit:

```text
Market evidence -> thesis -> risk-gated decision -> paper execution
                -> measured outcome -> learning -> next experiment
```

The system combines technical, fundamental, narrative, regime, benchmark and
portfolio evidence. Every trading result remains paper-only, timestamped and
auditable. Stored outcomes can influence future confidence and research
priorities, but BLUM never rewrites its own source code.

## Product surfaces

| Surface | Question answered | Live view |
| --- | --- | --- |
| **Brain** | Is decision quality improving? | [Open Brain](https://italianhype-blum.hf.space/brain) |
| **Training Ground** | What is BLUM testing and learning? | [Open Training Ground](https://italianhype-blum.hf.space/training-ground) |
| **Paper Trading** | Which decisions were opened, closed or rejected, and why? | [Open Paper Trading](https://italianhype-blum.hf.space/paper-trading) |
| **Alpha** | Does stored evidence beat relevant benchmarks? | [Open Alpha](https://italianhype-blum.hf.space/alpha) |

The public UI reads compact snapshots. Training, research and trade evaluation
continue in background workers and are never triggered by page rendering.

## Evidence before claims

BLUM separates four evidence classes rather than combining them into one score:

1. historical replay;
2. purged or walk-forward validation;
3. paper-forward outcomes;
4. live-forward evidence when available.

Every performance surface should expose sample size, benchmark, period,
transaction-cost assumptions and reliability warnings. Historical success is
not treated as forward alpha. Missing evidence is reported as missing, not
replaced with synthetic results.

## Architecture

BLUM uses three boundaries with one source of financial truth:

```mermaid
flowchart LR
    Data["Market, news and filing evidence"] --> Engine["BLUM Engine"]
    Engine --> Decisions["Theses, decisions and risk plans"]
    Decisions --> Paper["Paper execution and outcomes"]
    Paper --> Learning["Learning and validation"]
    Learning --> Memory["Versioned evidence memory"]
    Memory --> Engine
    Engine --> Snapshots["Read-only snapshots"]
    Snapshots --> Runtime["BLUM Runtime"]
    Runtime --> UI["Brain · Training · Paper Trading · Alpha"]
    Engine --> Dataset["Curated reasoning dataset"]
    Dataset --> Analyst["BLUM Finance model"]
    Analyst -->|"Advisory reasoning only"| Engine
```

- **BLUM Engine** owns evidence, decisions, learning, risk, portfolio logic and
  benchmark validation.
- **BLUM Runtime** owns APIs, scheduling, snapshots, observability and the web
  interface. It does not own financial truth.
- **BLUM Finance model** learns BLUM's evidence-bound reasoning format. Its
  output remains advisory until the Engine validates it.

Read [Architecture](docs/ARCHITECTURE.md) for module boundaries and event flow.

## Core capabilities

- point-in-time market, news, filing and sentiment evidence;
- multi-engine bull, bear and neutral thesis competition;
- equities, ETF and Forex opportunity research;
- deterministic risk gates and paper execution simulation;
- spread, slippage, fees, partial-fill and benchmark accounting;
- historical replay, walk-forward and paper-forward evidence separation;
- decision, trade, engine-vote and learning attribution;
- confidence calibration and regime-aware reliability;
- autonomous research priorities and champion/challenger policies;
- snapshot-first FastAPI and Next.js runtime;
- governed reasoning-dataset and model-release pipeline.

## Quick start

Docker is the supported reproducible path:

```bash
git clone https://github.com/BlumFinancialLab/Blum.git
cd Blum
docker build -t blum .
docker run --rm -p 7860:7860 blum
```

Open `http://localhost:7860`. The first image build installs CPU machine-learning
and quantitative dependencies and can take several minutes.

Without `DATABASE_URL`, the container starts an embedded PostgreSQL instance for
research use. On deployments with persistent `/data`, BLUM asynchronously keeps
a physical recovery image for fast local startup and an atomic logical dump as
fallback. PostgreSQL itself remains on local disk because network-mounted Space
storage is not a safe database data directory. Use an external PostgreSQL
database for durable multi-replica deployments:

```bash
docker run --rm -p 7860:7860 \
  -e DATABASE_URL=postgresql+psycopg2://user:password@host:5432/blum \
  blum
```

Configuration belongs in environment variables or deployment secrets. Never
commit market-provider, model-provider or database credentials.

## Repository and deployment flow

[GitHub](https://github.com/BlumFinancialLab/Blum) is canonical. The
[Hugging Face Space](https://huggingface.co/spaces/Italianhype/Blum) is the
public Docker deployment.

A scheduled GitHub workflow reads the public HF Git history:

- equal or older HF history produces no change;
- a strictly newer HF history fast-forwards GitHub after Git LFS transfer;
- divergent histories create a protected review branch and pull request;
- canonical `main` is never force-pushed.

See [Deployment and synchronization](docs/DEPLOYMENT.md).

## Model and datasets

- [BLUM Finance 4B](https://huggingface.co/Italianhype/Blum): downloadable
  evidence-bound reasoning model.
- [BLUM Finance Reasoning](https://huggingface.co/datasets/Italianhype/Blum-Finance-Reasoning):
  versioned training and evaluation examples.
- [BLUM Finance Memory](https://huggingface.co/datasets/Italianhype/Blum-Finance-Memory):
  opt-in, quarantined community contributions.

Inference does not send telemetry by default. Community evidence requires an
explicit redacted contribution flow and never changes active weights merely
because it was uploaded.

## Documentation

| Document | Purpose |
| --- | --- |
| [Architecture](docs/ARCHITECTURE.md) | Engine, Runtime, Analyst and data-flow boundaries |
| [Research methodology](docs/RESEARCH_METHODOLOGY.md) | Evidence, validation and anti-bias rules |
| [Deployment](docs/DEPLOYMENT.md) | Docker, HF and repository synchronization |
| [Engineering standards](ENGINEERING_STANDARDS.md) | Production and evidence requirements |
| [Roadmap](ROADMAP.md) | Current engineering direction |
| [Changelog](CHANGELOG.md) | Shipped changes |
| [Project reference](docs/PROJECT_REFERENCE.md) | Full historical subsystem and release reference |
| [Model release report](BLUM_FINANCE_MODEL_RELEASE_REPORT.md) | Dataset, evaluation and release limitations |

## Contributing

Contributions should improve measured decision quality, evidence integrity,
risk control, reproducibility or runtime reliability. Start with
[CONTRIBUTING.md](CONTRIBUTING.md), use
[Discussions](https://github.com/BlumFinancialLab/Blum/discussions) for research
questions and submit reproducible defects through
[Issues](https://github.com/BlumFinancialLab/Blum/issues).

Project decisions follow [GOVERNANCE.md](GOVERNANCE.md). Security issues must be
reported privately according to [SECURITY.md](SECURITY.md).

## Safety boundary

BLUM is research and paper-trading software. It does not connect to a broker or
execute real-money orders in the supported open-source configuration. It does
not provide investment advice, guarantee profit or claim market outperformance
without sufficient stored evidence.

Models, datasets and third-party market sources may have licenses or usage terms
separate from the Apache-2.0 application license. Review their cards and terms
before redistribution or commercial use.

## License

Application source is licensed under [Apache-2.0](LICENSE).

Copyright 2026 BLUM Financial Lab contributors.
