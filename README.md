---
title: Blum Alpha Terminal
emoji: 📈
colorFrom: yellow
colorTo: gray
sdk: gradio
sdk_version: 5.34.0
app_file: app.py
short_description: Live market news and stock sentiment dashboard.
tags: [financial-analysis, finance, stock-market, market-analysis, sentiment-analysis, time-series, data-visualization, gradio]
pinned: false
---

# Blum Alpha Terminal

Autonomous public-market intelligence dashboard for liquid stocks and ETFs.

Release-style features:

- live public RSS news polling on app open and refresh;
- broad multi-desk RSS source network across markets, macro, central banks, regulators, commodities, crypto, company news and earnings;
- concurrent source collection with source health monitoring;
- backend realtime cache with lightweight frontend polling;
- financial news refinery with quality scoring, catalyst classification and deduplication;
- autonomous stock and ETF universe, so the user does not need to pick tickers first;
- market theme classification and sentiment;
- historical price and technical state via Yahoo Finance;
- 5-minute intraday chart panels through a lightweight Yahoo chart API adapter;
- market regime inference from equity beta, credit, duration and news tone;
- stable single-page dashboard with manual refresh;
- separate full-width short-term tactical queue and long-term investment queue;
- research queues with why-now, catalyst, setup and first rejection risk;
- terminal-style cockpit with chart wall, sector heatmap, source network and live headline radar.

Limit: this is a public-data research triage tool not financial advice.
