"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { MarketBrain, MarketBrainHistoryRow } from "@/lib/types";
import { LoadingState } from "@/components/LoadingState";
import { PlotPanel } from "@/components/PlotPanel";
import { StatusBadge } from "@/components/StatusBadge";

export default function MarketBrainPage() {
  const [brain, setBrain] = useState<MarketBrain | null>(null);
  const [history, setHistory] = useState<MarketBrainHistoryRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    setError("");
    try {
      const [brainResult, historyResult] = await Promise.allSettled([api.marketBrain(), api.marketBrainHistory(12)] as const);
      if (brainResult.status === "fulfilled") setBrain(brainResult.value);
      if (historyResult.status === "fulfilled") setHistory(historyResult.value);
      if (brainResult.status === "rejected") throw brainResult.reason;
    } catch (err) {
      setError((err as Error).message);
    }
  };

  useEffect(() => { load(); }, []);

  const runBrain = async (refreshPipeline: boolean) => {
    setBusy(true);
    setError("");
    try {
      const result = await api.runMarketBrain(refreshPipeline);
      setBrain(result);
      setHistory(await api.marketBrainHistory(12));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (error) return <div className="empty-state">API error: {error}</div>;
  if (!brain) return <LoadingState label="Loading Market Brain" />;

  const stack = brain.opportunity_stack;
  const scenarioNames = brain.forward_scenarios.map((scenario) => scenario.name.replace(/^.*?:\s*/, ""));
  const scenarioValues = brain.forward_scenarios.map((scenario) => scenario.probability_proxy);

  return (
    <>
      <div className="page-header">
        <div>
          <div className="kicker">Market Brain</div>
          <h1>Evidence-bound AI market reasoning engine.</h1>
        </div>
        <div className="control-row" style={{ marginBottom: 0 }}>
          <button className="button" disabled={busy} onClick={() => runBrain(false)}>{busy ? "Running..." : "Run brain"}</button>
          <button className="button primary" disabled={busy} onClick={() => runBrain(true)}>{busy ? "Refreshing..." : "Full data refresh"}</button>
        </div>
      </div>

      <section className="brain-hero">
        <div>
          <span>Current regime</span>
          <h2>{brain.regime}</h2>
          <p>{brain.summary}</p>
          <div className="tag-row">
            <span>{brain.data_mode}</span>
            <span>{brain.horizon}</span>
            <span>{formatTime(brain.created_at)}</span>
          </div>
        </div>
        <div className="brain-score">
          <span>Blum Market Brain Score</span>
          <strong>{brain.brain_score.toFixed(1)}</strong>
          <p>Composite evidence score derived from signals, sentiment, coverage, news intensity and IPO/pre-listing evidence.</p>
        </div>
      </section>

      <section className="grid-4" style={{ marginTop: 12 }}>
        <Metric label="Assets" value={brain.market_now.asset_count} />
        <Metric label="Signals" value={brain.market_now.signal_count} />
        <Metric label="48h News" value={brain.market_now.news_count_48h} />
        <Metric label="Sentiment" value={brain.market_now.average_sentiment.toFixed(2)} />
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <PlotPanel
          title="Forward Scenario Weights"
          data={[{
            x: scenarioValues,
            y: scenarioNames,
            type: "bar",
            orientation: "h",
            marker: { color: ["#55aaff", "#20e070", "#ff4d5e"] },
          }]}
          layout={{ xaxis: { range: [0, 100], title: "Probability proxy" } }}
        />
        <PlotPanel
          title="Theme Sentiment Map"
          data={[{
            x: brain.market_now.top_themes.map((theme) => theme.headline_count),
            y: brain.market_now.top_themes.map((theme) => theme.avg_sentiment),
            text: brain.market_now.top_themes.map((theme) => theme.theme),
            type: "scatter",
            mode: "markers+text",
            marker: { size: brain.market_now.top_themes.map((theme) => Math.max(10, theme.headline_count * 3)), color: "#ffb000" },
          }]}
          layout={{ xaxis: { title: "Headline count" }, yaxis: { title: "Avg sentiment" } }}
        />
      </section>

      <section className="scenario-grid" style={{ marginTop: 12 }}>
        {brain.forward_scenarios.map((scenario) => (
          <article className="panel scenario-card" key={scenario.name}>
            <div className="panel-head">
              <span>{scenario.time_horizon}</span>
              <strong>{scenario.probability_proxy}%</strong>
            </div>
            <h3>{scenario.name}</h3>
            <div className="scenario-list">
              {scenario.drivers.map((driver) => <p key={driver}>{driver}</p>)}
            </div>
            <div className="tag-row">
              {scenario.watch_points.slice(0, 3).map((item) => <span key={item}>{item}</span>)}
            </div>
          </article>
        ))}
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <div className="panel">
          <div className="panel-head"><span>Brain changelog</span><strong>{brain.change_log.length}</strong></div>
          <div className="brain-list">
            {brain.change_log.map((item) => (
              <div key={`${item.type}-${item.message}`}>
                <StatusBadge label={item.severity} />
                <strong>{item.type.replaceAll("_", " ")}</strong>
                <p>{item.message}</p>
              </div>
            ))}
          </div>
        </div>
        <div className="panel">
          <div className="panel-head"><span>Contradiction engine</span><strong>{brain.contradictions.length}</strong></div>
          <div className="brain-list">
            {brain.contradictions.length === 0 && <div className="empty-state">No material price, sentiment or risk contradictions detected.</div>}
            {brain.contradictions.slice(0, 8).map((item) => (
              <div key={`${item.type}-${item.ticker}-${item.title}`}>
                <StatusBadge label={item.severity} />
                <strong>{item.title}</strong>
                <span>{Object.entries(item.evidence).map(([key, value]) => `${key} ${value}`).join(" | ")}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="grid-3" style={{ marginTop: 12 }}>
        <OpportunityPanel title="Stock research priorities" rows={stack.stock_research_priorities} kind="stock" />
        <OpportunityPanel title="ETF rotation leaders" rows={stack.etf_rotation_leaders} kind="etf" />
        <OpportunityPanel title="IPO / pre-listing watch" rows={stack.ipo_watch} kind="ipo" />
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <div className="panel">
          <div className="panel-head"><span>Event graph</span><strong>{brain.event_graph.nodes.length} nodes</strong></div>
          <div className="event-graph">
            {brain.event_graph.nodes.slice(0, 28).map((node) => (
              <div className={`event-node ${node.type}`} key={node.id}>
                <span>{node.type}</span>
                <strong>{node.label}</strong>
                {node.score !== undefined && node.score !== null && <em>{Number(node.score).toFixed(1)}</em>}
              </div>
            ))}
          </div>
        </div>
        <div className="panel">
          <div className="panel-head"><span>Snapshot history</span><strong>{history.length}</strong></div>
          <div className="brain-list dense">
            {history.length === 0 && <div className="empty-state">No persisted Market Brain snapshots yet. Run brain to create the first snapshot.</div>}
            {history.map((item) => (
              <div key={item.run_id}>
                <div className="opportunity-line">
                  <strong>{item.regime}</strong>
                  <span>{Number(item.brain_score).toFixed(1)}</span>
                </div>
                <p>{formatTime(item.created_at)} | risk {item.risk_alert_count} | contradictions {item.contradiction_count}</p>
                <span>Top: {item.top_stock ?? "n/a"} | ETF {item.top_etf ?? "n/a"} | IPO {item.top_ipo ?? "n/a"}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <div className="panel">
          <div className="panel-head"><span>Risk alerts</span><strong>{brain.risk_alerts.length}</strong></div>
          <div className="brain-list">
            {brain.risk_alerts.length === 0 && <div className="empty-state">No active risk alerts from the stored evidence set.</div>}
            {brain.risk_alerts.map((alert) => (
              <div key={`${alert.title}-${alert.severity}`}>
                <StatusBadge label={alert.severity} />
                <strong>{alert.title}</strong>
                <p>{alert.detail}</p>
                {!!alert.tickers.length && <span>{alert.tickers.join(" | ")}</span>}
              </div>
            ))}
          </div>
        </div>
        <div className="panel">
          <div className="panel-head"><span>Evidence ledger</span><strong>Audit trail</strong></div>
          <div className="evidence-grid">
            {Object.entries(brain.evidence_ledger).map(([key, value]) => (
              <div key={key}>
                <span>{key.replaceAll("_", " ")}</span>
                <strong>{String(value)}</strong>
              </div>
            ))}
          </div>
          <p>{brain.disclaimer}</p>
        </div>
      </section>

      <section className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><span>Model stack</span><strong>Task-routed AI</strong></div>
        <div className="method-grid">
          {Object.entries(brain.model_stack).map(([key, value]) => (
            <div key={key}>
              <span>{key}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return <div className="metric-card"><span>{label}</span><strong>{value}</strong></div>;
}

function OpportunityPanel({ title, rows, kind }: { title: string; rows: any[]; kind: "stock" | "etf" | "ipo" }) {
  return (
    <div className="panel opportunity-panel">
      <div className="panel-head"><span>{title}</span><strong>{rows.length}</strong></div>
      <div className="brain-list dense">
        {rows.length === 0 && <div className="empty-state">No evidence-backed rows are available yet.</div>}
        {rows.slice(0, 8).map((row, index) => (
          <div key={`${title}-${row.ticker ?? row.name}-${index}`}>
            <div className="opportunity-line">
              {kind === "stock" && row.ticker ? <Link href={`/assets/${row.ticker}`}>{row.ticker}</Link> : <strong>{row.ticker ?? row.name}</strong>}
              <span>{displayScore(row.score ?? row.confirmation_score ?? row.opportunity_score)}</span>
            </div>
            <p>{row.name ?? row.category ?? row.classification}</p>
            <div className="tag-row">
              {row.classification && <span>{row.classification}</span>}
              {row.research_priority && <span>{row.research_priority}</span>}
              {row.risk_level && <span>{row.risk_level}</span>}
              {row.latest_form && <span>{row.latest_form}</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function displayScore(value: number | undefined | null) {
  if (value === undefined || value === null) return "n/a";
  return Number(value).toFixed(1);
}

function formatTime(value: string | null) {
  if (!value) return "Pending";
  return new Intl.DateTimeFormat("en", { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}
