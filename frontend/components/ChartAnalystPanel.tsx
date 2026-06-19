"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { ChartReport, PricePoint } from "@/lib/types";
import { PlotPanel } from "./PlotPanel";

const TIMEFRAMES = ["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "5Y"];

export function ChartAnalystPanel({ ticker, prices = [] }: { ticker: string; prices?: PricePoint[] }) {
  const [timeframe, setTimeframe] = useState("6M");
  const [report, setReport] = useState<ChartReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const loadReport = async (tf = timeframe) => {
    setError("");
    try {
      setReport(await api.chartTechnicalReport(ticker, tf));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  useEffect(() => {
    loadReport(timeframe);
  }, [ticker, timeframe]);

  const analyze = async () => {
    setBusy(true);
    setError("");
    try {
      setReport(await api.chartAnalyzeTicker(ticker, timeframe, periodFor(timeframe), false));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const chartPrices = useMemo(() => trimPrices(report?.price_series?.length ? report.price_series : prices, timeframe), [report, prices, timeframe]);
  const hybrid = (report?.hybrid_analysis ?? {}) as ChartReport["hybrid_analysis"];
  const deterministic = (report?.deterministic_analysis ?? {}) as Record<string, any>;
  const levels = hybrid.key_levels ?? {};
  const visual = report?.visual_analysis ?? {};
  const plot = chartPlot(chartPrices, levels);

  return (
    <section className="chart-analyst-shell">
      <div className="page-header compact-header">
        <div>
          <div className="kicker">Chart Vision Technical Analyst</div>
          <h2>{ticker} technical chart intelligence.</h2>
        </div>
        <div className="header-actions">
          <select className="input" value={timeframe} onChange={(event) => setTimeframe(event.target.value)}>
            {TIMEFRAMES.map((item) => <option key={item}>{item}</option>)}
          </select>
          <button className="button primary" onClick={analyze} disabled={busy}>{busy ? "Analyzing..." : "Analyze chart"}</button>
        </div>
      </div>

      {error && <div className="empty-state" style={{ marginBottom: 12 }}>Chart API warning: {error}</div>}

      <section className="grid-2">
        <PlotPanel
          title="Price Structure With Key Levels"
          data={plot.data}
          layout={plot.layout}
          height={430}
          emptyMessage="Waiting for stored OHLCV data to render the chart."
        />
        <TechnicalSnapshot report={report} />
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <KeyLevels levels={levels} />
        <SignalEvidence hybrid={hybrid} />
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <AnalystReport hybrid={hybrid} visual={visual} deterministic={deterministic} />
        <HistoricalSimilarity similarity={hybrid.historical_similarity ?? {}} />
      </section>
    </section>
  );
}

function TechnicalSnapshot({ report }: { report: ChartReport | null }) {
  const d = report?.deterministic_analysis ?? {};
  const h = (report?.hybrid_analysis ?? {}) as ChartReport["hybrid_analysis"];
  const momentum = d.momentum ?? {};
  const volatility = d.volatility ?? {};
  const volume = d.volume ?? {};
  const pattern = d.patterns?.[0]?.pattern ?? "pending";
  return (
    <div className="panel chart-snapshot-panel">
      <div className="panel-head">
        <span>Technical Snapshot</span>
        <strong>{Number(h.confidence_score ?? report?.confidence ?? 0).toFixed(1)} confidence</strong>
      </div>
      <div className="brain-status-grid">
        <SnapshotMetric label="Trend" value={String(d.trend_direction ?? "pending").replaceAll("_", " ")} />
        <SnapshotMetric label="Momentum" value={String(momentum.state ?? "pending").replaceAll("_", " ")} />
        <SnapshotMetric label="Volatility" value={String(volatility.regime ?? "pending").replaceAll("_", " ")} />
        <SnapshotMetric label="Volume" value={String(volume.volume_state ?? "pending").replaceAll("_", " ")} />
        <SnapshotMetric label="Pattern" value={String(pattern).replaceAll("_", " ")} />
        <SnapshotMetric label="Breakout" value={`${Number(d.breakout_probability?.score ?? 0).toFixed(1)}/100`} />
      </div>
      <div className="brain-drift info">
        <strong>{String(h.timeframe_relevance ?? "timeframe pending").replaceAll("_", " ")}</strong>
        <span>{h.trend_summary ?? "Technical summary will appear when stored OHLCV evidence is sufficient for the autonomous chart analyst."}</span>
      </div>
      <p>{(report?.warnings ?? h.warnings)?.join(" ") ?? "Vision model status and deterministic analysis warnings will appear here."}</p>
    </div>
  );
}

function KeyLevels({ levels }: { levels: Record<string, any> }) {
  return (
    <div className="panel">
      <div className="panel-head"><span>Key Levels</span><strong>zones, not guarantees</strong></div>
      <div className="key-level-grid">
        <Level label="Support 1" value={levels.support_1} />
        <Level label="Support 2" value={levels.support_2} />
        <Level label="Resistance 1" value={levels.resistance_1} />
        <Level label="Resistance 2" value={levels.resistance_2} />
        <Level label="Breakout" value={levels.breakout_level} />
        <Level label="Breakdown" value={levels.breakdown_level} />
        <Level label="Invalidation" value={levels.invalidation_level} />
      </div>
    </div>
  );
}

function SignalEvidence({ hybrid }: { hybrid: any }) {
  return (
    <div className="panel">
      <div className="panel-head"><span>Signal Evidence</span><strong>{hybrid.technical_signals?.length ?? 0} signals</strong></div>
      <div className="evidence-columns">
        <EvidenceList title="Bullish Evidence" rows={hybrid.bullish_evidence ?? []} />
        <EvidenceList title="Bearish Evidence" rows={hybrid.bearish_evidence ?? []} />
        <EvidenceList title="Neutral / Uncertain" rows={hybrid.neutral_evidence ?? []} />
      </div>
    </div>
  );
}

function AnalystReport({ hybrid, visual, deterministic }: { hybrid: any; visual: Record<string, any>; deterministic: Record<string, any> }) {
  return (
    <div className="panel">
      <div className="panel-head">
        <span>Analyst Report</span>
        <strong>{String(visual.mode ?? "deterministic").replaceAll("_", " ")}</strong>
      </div>
      <p>{hybrid.analyst_report ?? deterministic.technical_summary ?? "The autonomous chart analyst is waiting for sufficient deterministic technical evidence."}</p>
      <div className="scenario-list">
        {(hybrid.possible_scenarios ?? []).map((scenario: any) => (
          <div key={scenario.name}>
            <strong>{scenario.name}</strong>
            <span>{scenario.condition}</span>
            <span>{scenario.impact}</span>
          </div>
        ))}
      </div>
      <div className="learning-event-list" style={{ marginTop: 10 }}>
        {(hybrid.what_to_watch_next ?? []).slice(0, 6).map((item: string) => <span key={item}>{item}</span>)}
      </div>
    </div>
  );
}

function HistoricalSimilarity({ similarity }: { similarity: Record<string, any> }) {
  return (
    <div className="panel">
      <div className="panel-head">
        <span>Historical Similarity</span>
        <strong>{similarity.reliability_score ? `${Number(similarity.reliability_score).toFixed(1)} reliability` : "maturing"}</strong>
      </div>
      <div className="brain-status-grid">
        <SnapshotMetric label="Similar Setups" value={similarity.similar_chart_setups ?? 0} />
        <SnapshotMetric label="Mature Cases" value={similarity.mature_cases ?? 0} />
        <SnapshotMetric label="7D Avg Return" value={formatPercent(similarity.average_forward_return_7d)} />
        <SnapshotMetric label="Success Rate" value={ratio(similarity.success_rate)} />
      </div>
      <p>{similarity.explanation ?? "Chart pattern memory will mature as future OHLCV outcomes are observed."}</p>
    </div>
  );
}

function SnapshotMetric({ label, value }: { label: string; value: string | number }) {
  return <div className="brain-metric"><span>{label}</span><strong>{value}</strong></div>;
}

function Level({ label, value }: { label: string; value: any }) {
  return <div><span>{label}</span><strong>{formatLevel(value)}</strong></div>;
}

function EvidenceList({ title, rows }: { title: string; rows: string[] }) {
  return (
    <div>
      <h3>{title}</h3>
      <div className="learning-event-list">
        {rows.length ? rows.slice(0, 6).map((item) => <span key={item}>{item}</span>) : <span>No confirmed evidence yet.</span>}
      </div>
    </div>
  );
}

function chartPlot(prices: PricePoint[], levels: Record<string, any>) {
  const x = prices.map((point) => point.date);
  const shapes = levelShapes(levels, x);
  return {
    data: [
      {
        type: "candlestick",
        x,
        open: prices.map((point) => point.open ?? point.close),
        high: prices.map((point) => point.high ?? point.close),
        low: prices.map((point) => point.low ?? point.close),
        close: prices.map((point) => point.close),
        increasing: { line: { color: "#20e070" } },
        decreasing: { line: { color: "#ff4d5e" } },
        name: "OHLC"
      },
      {
        type: "bar",
        x,
        y: prices.map((point) => point.volume ?? 0),
        yaxis: "y2",
        marker: { color: "rgba(77,216,255,.24)" },
        name: "Volume"
      }
    ],
    layout: {
      shapes,
      xaxis: { rangeslider: { visible: false }, gridcolor: "rgba(255,255,255,.06)" },
      yaxis: { domain: [0.24, 1], gridcolor: "rgba(255,255,255,.06)" },
      yaxis2: { domain: [0, 0.17], gridcolor: "rgba(255,255,255,.04)" },
      showlegend: false
    }
  };
}

function levelShapes(levels: Record<string, any>, x: string[]) {
  if (!x.length) return [];
  const x0 = x[0];
  const x1 = x[x.length - 1];
  const candidates = [
    { value: levels.support_1, color: "#20e070" },
    { value: levels.support_2, color: "#20e070" },
    { value: levels.resistance_1, color: "#ff4d5e" },
    { value: levels.resistance_2, color: "#ff4d5e" },
    { value: levels.invalidation_level, color: "#ffb000" }
  ];
  return candidates.filter((item) => item.value).map((item) => ({
    type: "line",
    xref: "x",
    yref: "y",
    x0,
    x1,
    y0: Number(item.value),
    y1: Number(item.value),
    line: { color: item.color, width: 1, dash: "dot" }
  }));
}

function trimPrices(prices: PricePoint[], timeframe: string) {
  const limits: Record<string, number> = { "1D": 96, "5D": 120, "1M": 42, "3M": 84, "6M": 150, "YTD": 260, "1Y": 260, "5Y": 1260 };
  return prices.slice(-(limits[timeframe] ?? 150));
}

function periodFor(timeframe: string) {
  const periods: Record<string, string> = { "1D": "5d", "5D": "1mo", "1M": "3mo", "3M": "6mo", "6M": "1y", "YTD": "1y", "1Y": "2y", "5Y": "5y" };
  return periods[timeframe] ?? "1y";
}

function formatLevel(value: any) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  return Number(value).toFixed(2);
}

function formatPercent(value: any) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "Pending";
  return `${Number(value).toFixed(2)}%`;
}

function ratio(value: any) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "Pending";
  return `${Math.round(Number(value) * 100)}%`;
}
