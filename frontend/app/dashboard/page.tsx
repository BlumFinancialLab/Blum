"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { DashboardOverview } from "@/lib/types";
import { LoadingState } from "@/components/LoadingState";
import { ScoreCard } from "@/components/ScoreCard";
import { SignalTable } from "@/components/SignalTable";

export default function DashboardPage() {
  const [data, setData] = useState<DashboardOverview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      setError("");
      setData(await api.overview());
    } catch (err) {
      setError((err as Error).message);
    }
  };

  useEffect(() => { load(); }, []);

  const runPipeline = async () => {
    setBusy(true);
    try {
      await api.marketUpdate();
      await api.newsUpdate();
      await api.runSignals();
      await load();
    } finally {
      setBusy(false);
    }
  };

  if (error) return <div className="empty-state">API error: {error}</div>;
  if (!data) return <LoadingState />;

  return (
    <>
      <div className="page-header">
        <div>
          <div className="kicker">Intelligence Dashboard</div>
          <h1>What should the research desk watch now?</h1>
        </div>
        <button className="button primary" onClick={runPipeline} disabled={busy}>{busy ? "Running pipeline..." : "Run full pipeline"}</button>
      </div>

      <section className="grid-4">
        <Metric label="Assets" value={data.market_pulse.asset_count} />
        <Metric label="News Articles" value={data.market_pulse.article_count} />
        <Metric label="Avg Sentiment" value={data.market_pulse.average_sentiment.toFixed(2)} />
        <Metric label="Signals" value={data.market_pulse.signal_count} />
      </section>

      <section className="grid-3" style={{ marginTop: 12 }}>
        {data.todays_strongest_signals.slice(0, 6).map((signal) => <ScoreCard signal={signal} key={signal.ticker} />)}
      </section>

      <section className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><span>Today&apos;s strongest signals</span></div>
        <SignalTable signals={data.todays_strongest_signals} />
      </section>
    </>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return <div className="metric-card"><span>{label}</span><strong>{value}</strong></div>;
}

