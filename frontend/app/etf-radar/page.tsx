"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { LoadingState } from "@/components/LoadingState";
import { PlotPanel } from "@/components/PlotPanel";

export default function EtfRadarPage() {
  const [rows, setRows] = useState<any[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.etfTrends().then(setRows).catch((err) => setError((err as Error).message)); }, []);
  if (error) return <div className="empty-state">API error: {error}</div>;
  if (!rows) return <LoadingState label="Loading ETF radar" />;
  return (
    <>
      <div className="page-header">
        <div><div className="kicker">ETF Radar</div><h1>ETF rotation and sector confirmation.</h1></div>
      </div>
      <section className="grid-2">
        <PlotPanel
          title="ETF Confirmation Ranking"
          data={[{ x: rows.map((r) => r.confirmation_score), y: rows.map((r) => r.ticker), type: "bar", orientation: "h", marker: { color: "#20e070" } }]}
          layout={{ xaxis: { range: [0, 100] } }}
        />
        <PlotPanel
          title="Momentum vs Theme"
          data={[{ x: rows.map((r) => r.momentum_score), y: rows.map((r) => r.thematic_score), text: rows.map((r) => r.ticker), type: "scatter", mode: "markers+text", marker: { size: 13, color: "#ffb000" } }]}
        />
      </section>
      <section className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><span>ETF rotation leaders</span></div>
        <div className="table-shell">
          <table className="intel-table">
            <thead><tr><th>ETF</th><th>Category</th><th>Momentum</th><th>Theme</th><th>Confirmation</th><th>Read-through</th></tr></thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.ticker}-${row.created_at}`}>
                  <td className="asset-link">{row.ticker}</td>
                  <td>{row.category}</td>
                  <td>{row.momentum_score}</td>
                  <td>{row.thematic_score}</td>
                  <td><strong className="score-number">{row.confirmation_score}</strong></td>
                  <td>{row.details?.classification ?? "ETF trend confirmation"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

