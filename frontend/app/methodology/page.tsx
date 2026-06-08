export default function MethodologyPage() {
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

const sections = [
  { title: "Data workflow", body: "The backend seeds an asset universe, ingests yfinance OHLCV history, collects public RSS news, deduplicates articles, links them to assets and persists all artifacts in PostgreSQL." },
  { title: "AI orchestration", body: "FinBERT handles financial sentiment, sentence-transformers handles embeddings and semantic search, a lightweight LLM creates evidence-only explanations, and the time-series layer computes anomalies, volatility regimes and scenarios." },
  { title: "Signal scoring", body: "The Blum Intelligence Score combines momentum, trend quality, technical indicators, volatility/risk, sentiment trend, semantic intensity, ETF confirmation and anomaly pressure." },
  { title: "Explainability", body: "Each surfaced asset must expose why it appeared, which technical and narrative data support it, what contradicts it, what to monitor, and which risks limit confidence." },
  { title: "Backtesting", body: "Historical validation reports hit rate, forward returns, max adverse excursion, max favorable excursion, false positives and methodology limits. It does not promise future performance." },
  { title: "Provider architecture", body: "The first provider is yfinance. The backend isolates providers so future integrations can add licensed market data, estimates, filings, transcripts, ownership and portfolio systems." }
];

