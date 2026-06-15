"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function MethodologyPage() {
  const [modelStatus, setModelStatus] = useState<any>(null);

  useEffect(() => {
    api.modelStatus().then(setModelStatus).catch(() => setModelStatus(null));
  }, []);

  return (
    <>
      <div className="page-header">
        <div><div className="kicker">Methodology</div><h1>Transparent architecture and scoring rules.</h1></div>
      </div>
      <section className="grid-2">
        {sections.map((section) => (
          <article className="panel" key={section.title}>
            <div className="panel-head"><span>{section.title}</span></div>
            <p>{section.body}</p>
          </article>
        ))}
      </section>
      <section className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><span>AI model status</span><strong>{modelStatus?.model_loading_enabled ? "model loading enabled" : "fallback-ready"}</strong></div>
        {!modelStatus && <div className="empty-state">Model status is not available yet.</div>}
        {modelStatus && (
          <>
            <div className="method-grid">
              {Object.entries(modelStatus.configured_models).map(([key, value]) => (
                <div key={key}>
                  <span>{key.replaceAll("_", " ")}</span>
                  <strong>{String(value)}</strong>
                </div>
              ))}
            </div>
            <div className="grid-3" style={{ marginTop: 10 }}>
              <ObservedModelPanel title="Sentiment records" rows={modelStatus.observed_models.sentiment} />
              <ObservedModelPanel title="Embedding records" rows={modelStatus.observed_models.embeddings} />
              <ObservedModelPanel title="Insight records" rows={modelStatus.observed_models.insights} />
            </div>
          </>
        )}
      </section>
      <section className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><span>Financial disclaimer</span></div>
        <p>
          This project is for educational, research and technical case-study purposes only. It is not financial advice,
          an investment recommendation, a trading signal, or a substitute for regulated research, due diligence,
          valuation work, risk management or professional advice.
        </p>
      </section>
    </>
  );
}

function ObservedModelPanel({ title, rows }: { title: string; rows: any[] }) {
  return (
    <div className="observed-model-panel">
      <div className="panel-head"><span>{title}</span><strong>{rows?.length ?? 0}</strong></div>
      <div className="brain-list dense">
        {!rows?.length && <div className="empty-state">No records observed yet.</div>}
        {rows?.map((row) => (
          <div key={row.model_name}>
            <strong>{row.model_name}</strong>
            <span>{row.records} records</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const sections = [
  { title: "Data workflow", body: "The backend seeds an asset universe, ingests public OHLCV history, collects public RSS news, deduplicates articles, links them to assets and persists all artifacts in PostgreSQL." },
  { title: "AI orchestration", body: "FinBERT handles financial sentiment, sentence-transformers handles embeddings and semantic search, a lightweight LLM creates evidence-only explanations, and the time-series layer computes anomalies, volatility regimes and scenarios." },
  { title: "Market Brain", body: "The Market Brain combines stock signals, ETF rotation, live news, sentiment, SEC filing evidence, forward scenarios, contradictions, risk alerts and change logs into one evidence-bound operating view." },
  { title: "IPO intelligence", body: "IPO Radar uses SEC EDGAR current filings and company submissions data for S-1, F-1 and 424B prospectus evidence. It never fabricates listing dates, valuations or tickers." },
  { title: "Signal scoring", body: "The Blum Intelligence Score combines momentum, trend quality, technical indicators, volatility/risk, sentiment trend, semantic intensity, ETF confirmation and anomaly pressure." },
  { title: "Explainability", body: "Each surfaced asset must expose why it appeared, which technical and narrative data support it, what contradicts it, what to monitor, and which risks limit confidence." },
  { title: "Backtesting", body: "Historical validation reports hit rate, forward returns, max adverse excursion, max favorable excursion, false positives and methodology limits. It does not promise future performance." },
  { title: "Provider architecture", body: "The first provider is yfinance. The backend isolates providers so future integrations can add licensed market data, estimates, filings, transcripts, ownership and portfolio systems." }
];
