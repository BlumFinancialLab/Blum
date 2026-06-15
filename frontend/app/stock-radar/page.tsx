"use client";

import type { CSSProperties } from "react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { StockRadar, StockRadarRow } from "@/lib/types";
import { assetPath } from "@/lib/routes";
import { LoadingState } from "@/components/LoadingState";
import { formatPercent, formatPrice, formatVolume, MarketSnapshotStrip } from "@/components/MarketSnapshotStrip";
import { PlotPanel } from "@/components/PlotPanel";
import { StatusBadge } from "@/components/StatusBadge";

const SECTIONS = [
  ["strongest_signals", "Strongest"],
  ["narrative_breakouts", "Narrative"],
  ["technical_breakouts", "Technical"],
  ["quality_momentum", "Quality Momentum"],
  ["quiet_accumulation", "Quiet Accumulation"],
  ["sentiment_divergence", "Divergence"],
  ["high_risk_momentum", "High Risk"],
  ["contrarian_setups", "Contrarian"],
] as const;

export default function StockRadarPage() {
  const [radar, setRadar] = useState<StockRadar | null>(null);
  const [selectedSection, setSelectedSection] = useState<string>("strongest_signals");
  const [sector, setSector] = useState("");
  const [priority, setPriority] = useState("");
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [updateResult, setUpdateResult] = useState<any>(null);

  const load = async () => {
    setError("");
    try {
      setRadar(await api.stockRadar(100));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  useEffect(() => { load(); }, []);

  const runUpdate = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await api.updateStockRadar(60);
      setUpdateResult(result);
      setRadar(result.radar);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const selectedRows = radar?.sections?.[selectedSection] ?? [];
  const sectionRows = selectedRows.length ? selectedRows : (radar?.summary.signal_count ? [] : radar?.data_gaps ?? radar?.rows ?? []);
  const rows = useMemo(() => {
    const query = search.trim().toLowerCase();
    return sectionRows.filter((row) =>
      (!sector || row.asset.sector === sector) &&
      (!priority || row.research_priority === priority) &&
      (!query || `${row.ticker} ${row.asset.name} ${row.asset.sector} ${row.asset.industry}`.toLowerCase().includes(query))
    );
  }, [sectionRows, sector, priority, search]);

  if (!radar) {
    if (error) return <div className="empty-state">API error: {error}</div>;
    return <LoadingState label="Loading Stock Radar" />;
  }

  const coverageRows = radar.rows.length ? radar.rows : radar.data_gaps;
  const sectors = Array.from(new Set(coverageRows.map((row) => row.asset.sector))).sort();
  const priorities = Array.from(new Set(coverageRows.map((row) => row.research_priority))).sort();
  const plotted = radar.rows.filter((row) => row.signal);

  return (
    <>
      <div className="page-header">
        <div>
          <div className="kicker">Stock Radar</div>
          <h1>Stock intelligence radar.</h1>
          <p>Equity coverage, live evidence readiness and signal triage from verified public data.</p>
        </div>
        <div className="header-actions">
          <Link className="button" href="/etf-radar">ETF Radar</Link>
          <Link className="button" href="/ipo-radar">IPO Radar</Link>
          <button className="button primary" onClick={runUpdate} disabled={busy}>{busy ? "Updating stock radar..." : "Run Stock Radar"}</button>
        </div>
      </div>

      {error && <div className="empty-state" style={{ marginBottom: 12 }}>API error: {error}</div>}

      <section className="grid-4">
        <Metric label="Stocks" value={radar.summary.stock_count} />
        <Metric label="Signals" value={radar.summary.signal_count} />
        <Metric label="Priced" value={radar.summary.priced_count} />
        <Metric label="Avg Score" value={radar.summary.average_score.toFixed(1)} />
      </section>

      {updateResult && (
        <section className="panel" style={{ marginTop: 12 }}>
          <div className="panel-head"><span>Stock radar update diagnostics</span><strong>{updateResult.radar?.status ?? radar.status}</strong></div>
          <div className="diagnostic-grid">
            <div>
              <span>Market data</span>
              <strong>{updateResult.market_update?.updated_assets ?? 0} assets updated</strong>
              <p>{updateResult.market_update?.price_rows ?? 0} OHLCV rows | {updateResult.market_update?.data_mode ?? "real data"}</p>
            </div>
            <div>
              <span>News and sentiment</span>
              <strong>{updateResult.news_update?.inserted_articles ?? 0} new articles</strong>
              <p>{updateResult.news_update?.sources_ok ?? 0}/{updateResult.news_update?.sources_requested ?? 0} public sources ok | {updateResult.news_update?.linked_assets ?? 0} asset links</p>
            </div>
          </div>
        </section>
      )}

      <section className="radar-tabs" style={{ marginTop: 12 }}>
        {SECTIONS.map(([key, label]) => (
          <button className={selectedSection === key ? "active" : ""} onClick={() => setSelectedSection(key)} key={key}>
            {label}<span>{radar.sections[key]?.length ?? 0}</span>
          </button>
        ))}
      </section>

      {radar.status !== "ready" && (
        <section className="panel readiness-panel" style={{ marginTop: 12 }}>
          <div className="panel-head"><span>Evidence readiness</span><strong>{radar.status.replaceAll("_", " ")}</strong></div>
          <p>
            No scored stock signals are available yet. The cards below show the real asset universe and latest stored market status while
            the backend hydrates prices, news, sentiment, embeddings and signal snapshots. No synthetic prices, headlines or scores are displayed.
          </p>
          <div className="mini-metrics">
            <div><span>Missing signals</span><strong>{radar.summary.missing_signal_count}</strong></div>
            <div><span>Priced names</span><strong>{radar.summary.priced_count}</strong></div>
            <div><span>Positive 1D</span><strong>{radar.summary.positive_1d_count}</strong></div>
            <div><span>Top score</span><strong>{radar.summary.top_score.toFixed(1)}</strong></div>
          </div>
        </section>
      )}

      <section className="grid-3" style={{ marginTop: 12 }}>
        {rows.slice(0, 6).map((row) => <StockRadarCard row={row} key={`card-${row.ticker}`} />)}
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <PlotPanel
          title="Sector Leadership"
          data={[{
            x: radar.sector_leaders.map((item) => item.average_score),
            y: radar.sector_leaders.map((item) => item.sector),
            type: "bar",
            orientation: "h",
            marker: { color: "#ffb000" },
          }]}
          layout={{ xaxis: { range: [0, 100] } }}
          emptyMessage="Sector leadership appears after real signal snapshots are created."
        />
        <PlotPanel
          title="Momentum vs Sentiment"
          data={[{
            x: plotted.map((row) => row.factor_scores?.momentum ?? 0),
            y: plotted.map((row) => row.factor_scores?.sentiment ?? 0),
            text: plotted.map((row) => row.ticker),
            type: "scatter",
            mode: "markers+text",
            marker: { size: plotted.map((row) => Math.max(9, (row.signal?.blum_score ?? 0) / 5)), color: "#4dd8ff" },
          }]}
          layout={{ xaxis: { range: [0, 100], title: "Momentum" }, yaxis: { range: [0, 100], title: "Sentiment" } }}
          emptyMessage="Momentum and sentiment scatter requires priced assets, linked news and signal snapshots."
        />
      </section>

      <section className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><span>Stock radar table</span><strong>{rows.length} names</strong></div>
        <div className="control-row">
          <input className="input" placeholder="Search ticker, company, sector" value={search} onChange={(event) => setSearch(event.target.value)} />
          <select className="input" value={sector} onChange={(event) => setSector(event.target.value)}>
            <option value="">All sectors</option>
            {sectors.map((item) => <option key={item}>{item}</option>)}
          </select>
          <select className="input" value={priority} onChange={(event) => setPriority(event.target.value)}>
            <option value="">All research priorities</option>
            {priorities.map((item) => <option key={item}>{item}</option>)}
          </select>
        </div>
        <StockRadarTable
          rows={rows}
          emptyMessage={radar.summary.signal_count ? "No stocks match the current radar filters or selected signal category." : "No scored stocks yet. Showing real coverage requires the pipeline to finish price, news and signal hydration."}
        />
      </section>
    </>
  );
}

function StockRadarCard({ row }: { row: StockRadarRow }) {
  const score = row.signal?.blum_score ?? 0;
  const scoreStyle = { "--score": score } as CSSProperties;
  return (
    <article className="score-card stock-radar-card">
      <div className="score-card-top">
        <div>
          <span>{row.asset.sector} | {row.research_priority}</span>
          <h3>{row.ticker}</h3>
          <p className="asset-subtitle">{row.asset.name}</p>
        </div>
        <div className="score-ring" style={scoreStyle}>
          <strong>{Math.round(score)}</strong>
        </div>
      </div>
      {row.signal ? <StatusBadge label={row.signal.classification} /> : <StatusBadge label="Insufficient Evidence" />}
      <MarketSnapshotStrip snapshot={row.market_snapshot} compact />
      <div className="tag-row">
        {row.radar_tags.slice(0, 5).map((tag) => <span key={tag}>{tag}</span>)}
      </div>
      <p>{row.why_watch}</p>
      <div className="mini-metrics">
        <div><span>Trend</span><strong>{factor(row, "trend")}</strong></div>
        <div><span>Momentum</span><strong>{factor(row, "momentum")}</strong></div>
        <div><span>Sentiment</span><strong>{factor(row, "sentiment")}</strong></div>
        <div><span>Confidence</span><strong>{row.signal?.confidence_score?.toFixed(0) ?? "n/a"}</strong></div>
      </div>
    </article>
  );
}

function StockRadarTable({ rows, emptyMessage }: { rows: StockRadarRow[]; emptyMessage: string }) {
  if (!rows.length) return <div className="empty-state">{emptyMessage}</div>;
  return (
    <div className="table-shell">
      <table className="intel-table">
        <thead>
          <tr>
            <th>Stock</th>
            <th>Market</th>
            <th>Priority</th>
            <th>Signal</th>
            <th>Factors</th>
            <th>Technical Context</th>
            <th>Narrative</th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`row-${row.ticker}`}>
              <td>
                <Link className="asset-link" href={assetPath(row.ticker)}>{row.ticker}</Link>
                <span>{row.asset.name}</span>
                <span>{row.asset.sector} | {row.asset.industry} | {row.asset.exchange}</span>
              </td>
              <td>
                <strong>{formatPrice(row.market_snapshot.price, row.market_snapshot.currency)}</strong>
                <span>{formatPercent(row.market_snapshot.perf_1d)} 1D | {formatPercent(row.market_snapshot.perf_5d)} 5D | {formatPercent(row.market_snapshot.perf_1m)} 1M</span>
                <span>{row.market_snapshot.provider ?? "provider n/a"} | vol {formatVolume(row.market_snapshot.volume)}</span>
              </td>
              <td><span className="metric-pill">{row.research_priority}</span></td>
              <td>
                {row.signal ? <StatusBadge label={row.signal.classification} /> : <StatusBadge label="Insufficient Evidence" />}
                <span>Score {row.signal?.blum_score?.toFixed(1) ?? "n/a"} | conf {row.signal?.confidence_score?.toFixed(0) ?? "n/a"} | {row.signal?.risk_level ?? "Not rated"}</span>
                <span>{row.signal?.lifecycle_state ?? "no lifecycle"} | {row.signal?.score_version ?? "no score version"}</span>
              </td>
              <td>
                <span>Mom {factor(row, "momentum")} | Trend {factor(row, "trend")}</span>
                <span>Sent {factor(row, "sentiment")} | Anom {factor(row, "anomaly")}</span>
              </td>
              <td>
                <span>RSI {display(row.technical_flags?.rsi)} | MACD hist {display(row.technical_flags?.macd_hist)}</span>
                <span>Support {display(row.technical_flags?.support)} | Resistance {display(row.technical_flags?.resistance)}</span>
              </td>
              <td>
                <span>7D news {display(row.narrative_flags?.news_count_7d)} | 30D news {display(row.narrative_flags?.news_count_30d)}</span>
                <span>7D sent {display(row.narrative_flags?.sentiment_7d)} | intensity {display(row.narrative_flags?.narrative_intensity)}</span>
              </td>
              <td className="why">{row.why_watch}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return <div className="metric-card"><span>{label}</span><strong>{value}</strong></div>;
}

function factor(row: StockRadarRow, key: string) {
  return Number(row.factor_scores?.[key] ?? 0).toFixed(0);
}

function display(value: unknown) {
  if (value === null || value === undefined || value === "") return "n/a";
  if (typeof value === "number") return Number(value).toFixed(Math.abs(value) >= 100 ? 0 : 2);
  return String(value);
}
