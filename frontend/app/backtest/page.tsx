"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { PlotPanel } from "@/components/PlotPanel";

export default function BacktestPage() {
  const [ticker, setTicker] = useState("NVDA");
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try { setResult(await api.backtest(ticker.toUpperCase())); } finally { setBusy(false); }
  };
  const metrics = result?.metrics ?? {};
  return (
    <>
      <div className="page-header">
        <div><div className="kicker">Backtest</div><h1>Historical validation, not performance prediction.</h1></div>
      </div>
      <div className="control-row">
        <input className="input" value={ticker} onChange={(e) => setTicker(e.target.value)} />
        <button className="button primary" onClick={run}>{busy ? "Running..." : "Run validation"}</button>
      </div>
      {result && (
        <>
          <section className="grid-4">
            <Metric label="Signals" value={metrics.signal_count ?? 0} />
            <Metric label="Hit Rate 20D" value={`${((metrics.hit_rate_20d ?? 0) * 100).toFixed(1)}%`} />
            <Metric label="Avg Forward 20D" value={`${(metrics.average_forward_return_20d ?? 0).toFixed(2)}%`} />
            <Metric label="False Positive 20D" value={`${((metrics.false_positive_rate_20d ?? 0) * 100).toFixed(1)}%`} />
          </section>
          <section className="grid-2" style={{ marginTop: 12 }}>
            <PlotPanel title="Best Signals" data={[{ x: (result.best_signals ?? []).map((r: any) => r.date), y: (result.best_signals ?? []).map((r: any) => r.forward_return_20d), type: "bar", marker: { color: "#20e070" } }]} />
            <PlotPanel title="Worst Signals" data={[{ x: (result.worst_signals ?? []).map((r: any) => r.date), y: (result.worst_signals ?? []).map((r: any) => r.forward_return_20d), type: "bar", marker: { color: "#ff4d5e" } }]} />
          </section>
          <p>{result.disclaimer}</p>
        </>
      )}
    </>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div className="metric-card"><span>{label}</span><strong>{value}</strong></div>;
}

