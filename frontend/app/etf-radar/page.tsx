"use client";

import type { CSSProperties } from "react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { LoadingState } from "@/components/LoadingState";
import { formatPrice, MarketSnapshotStrip } from "@/components/MarketSnapshotStrip";
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
      {!rows.length && (
        <section className="panel readiness-panel" style={{ marginBottom: 12 }}>
          <div className="panel-head"><span>ETF readiness</span><strong>No ETF trends yet</strong></div>
          <p>
            ETF rotation appears after the real-data pipeline stores prices and signal context for ETF instruments.
            No synthetic ETF confirmation scores are displayed.
          </p>
        </section>
      )}
      <section className="grid-3" style={{ marginBottom: 12 }}>
        {rows.slice(0, 6).map((row) => (
          <article className="score-card" key={`etf-card-${row.ticker}-${row.created_at}`}>
            <div className="score-card-top">
              <div>
                <span>ETF | {row.asset?.sector ?? row.category}</span>
                <h3>{row.ticker}</h3>
                <p className="asset-subtitle">{row.asset?.name ?? row.category}</p>
              </div>
              <div className="score-ring" style={{ "--score": row.confirmation_score } as CSSProperties}>
                <strong>{Math.round(row.confirmation_score)}</strong>
              </div>
            </div>
            <MarketSnapshotStrip snapshot={row.market_snapshot} compact />
            <div className="mini-metrics">
              <div><span>Category</span><strong>{row.category}</strong></div>
              <div><span>Exchange</span><strong>{row.asset?.exchange ?? "n/a"}</strong></div>
              <div><span>Momentum</span><strong>{row.momentum_score}</strong></div>
              <div><span>Theme</span><strong>{row.thematic_score}</strong></div>
            </div>
          </article>
        ))}
      </section>
      <section className="grid-2">
        <PlotPanel
          title="ETF Confirmation Ranking"
          data={[{ x: rows.map((r) => r.confirmation_score), y: rows.map((r) => r.ticker), type: "bar", orientation: "h", marker: { color: "#20e070" } }]}
          layout={{ xaxis: { range: [0, 100] } }}
          emptyMessage="ETF confirmation ranking appears after ETF trend snapshots are available."
        />
        <PlotPanel
          title="Momentum vs Theme"
          data={[{ x: rows.map((r) => r.momentum_score), y: rows.map((r) => r.thematic_score), text: rows.map((r) => r.ticker), type: "scatter", mode: "markers+text", marker: { size: 13, color: "#ffb000" } }]}
          emptyMessage="Momentum/theme scatter requires real ETF trend rows."
        />
      </section>
      <section className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><span>ETF rotation leaders</span></div>
        {rows.length ? <div className="table-shell">
          <table className="intel-table">
            <thead><tr><th>ETF</th><th>Price</th><th>Category</th><th>Momentum</th><th>Theme</th><th>Confirmation</th><th>Read-through</th></tr></thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.ticker}-${row.created_at}`}>
                  <td>
                    <span className="asset-link">{row.ticker}</span>
                    <span>{row.asset?.name ?? "ETF metadata pending"}</span>
                    <span>{row.asset?.exchange ?? "Exchange n/a"} | {row.asset?.country ?? "Country n/a"}</span>
                  </td>
                  <td>
                    <strong>{formatPrice(row.market_snapshot?.price, row.market_snapshot?.currency)}</strong>
                    <span>{row.market_snapshot?.date ?? "date n/a"} | {row.market_snapshot?.provider ?? "provider n/a"}</span>
                  </td>
                  <td>{row.category}</td>
                  <td>{row.momentum_score}</td>
                  <td>{row.thematic_score}</td>
                  <td><strong className="score-number">{row.confirmation_score}</strong></td>
                  <td>{row.details?.classification ?? "ETF trend confirmation"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div> : <div className="empty-state">No ETF trend rows are available yet. Run the full pipeline from the dashboard.</div>}
      </section>
    </>
  );
}
