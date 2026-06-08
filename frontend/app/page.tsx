import Link from "next/link";

export default function HomePage() {
  return (
    <>
      <section className="hero">
        <div>
          <div className="kicker">Open-source AI financial intelligence case study</div>
          <h1>Blum turns public market data into explainable equity and ETF intelligence.</h1>
          <p>
            This project is a technical case study, not a consumer trading app. It combines public RSS ingestion,
            yfinance market data, PostgreSQL persistence, modular quantitative scoring, FinBERT sentiment,
            sentence-transformer semantic search, a lightweight LLM reasoning layer and time-series anomaly analysis.
          </p>
          <div className="control-row">
            <Link className="button primary" href="/dashboard">Open Intelligence Dashboard</Link>
            <Link className="button" href="/methodology">Read Methodology</Link>
          </div>
        </div>
        <div className="architecture-card">
          <div><span>Frontend</span><strong>Next.js</strong></div>
          <div><span>Backend</span><strong>FastAPI</strong></div>
          <div><span>Database</span><strong>PostgreSQL + Alembic</strong></div>
          <div><span>AI sentiment</span><strong>FinBERT</strong></div>
          <div><span>Semantic layer</span><strong>Sentence Transformers</strong></div>
          <div><span>Reasoning</span><strong>Qwen-compatible LLM</strong></div>
          <div><span>Deployment</span><strong>Docker Space</strong></div>
        </div>
      </section>

      <section className="grid-3" style={{ marginTop: 14 }}>
        {[
          ["Market Universe", "Stocks, ETFs, sectors, countries, themes and exchanges are normalized into a PostgreSQL asset universe."],
          ["Signal Engine", "Momentum, trend quality, volatility, technical indicators, semantic news intensity, ETF confirmation and anomalies produce a Blum Intelligence Score."],
          ["Explainability", "Each surfaced asset includes why it emerged, what confirms it, what contradicts it, risk level, watch points and next evidence to monitor."]
        ].map(([title, body]) => (
          <article className="panel" key={title}>
            <div className="panel-head"><span>{title}</span></div>
            <p>{body}</p>
          </article>
        ))}
      </section>
    </>
  );
}

