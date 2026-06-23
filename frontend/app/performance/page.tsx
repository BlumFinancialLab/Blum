"use client";

import { useEffect, useMemo, useState } from "react";
import { Activity, Database, Gauge, Timer, Zap } from "lucide-react";
import { api } from "@/lib/api";
import { BloombergPanel, MetricCard, TerminalHeader } from "@/components/FinancialTerminal";
import { LoadingState } from "@/components/LoadingState";

const POLL_MS = 15000;

type Diagnostics = Record<string, any>;

export default function PerformanceDiagnosticsPage() {
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [clientStats, setClientStats] = useState<any | null>(null);
  const [probeStatus, setProbeStatus] = useState("idle");
  const [error, setError] = useState("");

  const loadDiagnostics = async () => {
    try {
      setError("");
      setDiagnostics(await api.performanceDiagnostics());
      setClientStats(api.clientRequestStats());
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const runDashboardProbe = async () => {
    setProbeStatus("probing");
    const probes: Array<[string, () => Promise<any>]> = [
      ["frontend.dashboard.overview", () => api.overview()],
      ["frontend.dashboard.live_news", () => api.liveNews(60)],
      ["frontend.dashboard.market_sentiment", () => api.marketSentiment(48)],
      ["frontend.dashboard.pipeline_status", () => api.pipelineStatus()],
      ["frontend.dashboard.system_status", () => api.systemStatus()],
      ["frontend.dashboard.executive", () => api.executiveDashboard()],
      ["frontend.dashboard.brain_status", () => api.brainStatus()]
    ];
    await Promise.all(
      probes.map(async ([name, fn]) => {
        const started = performance.now();
        try {
          await fn();
          await api.recordPerformanceWidget({ name, duration_ms: performance.now() - started, status: "ok", source: "browser_probe" });
        } catch (err) {
          await api.recordPerformanceWidget({
            name,
            duration_ms: performance.now() - started,
            status: "error",
            source: "browser_probe",
            detail: (err as Error).message.slice(0, 180)
          }).catch(() => undefined);
        }
      })
    );
    setProbeStatus("complete");
    await loadDiagnostics();
  };

  useEffect(() => {
    loadDiagnostics();
    runDashboardProbe();
    const interval = window.setInterval(loadDiagnostics, POLL_MS);
    return () => window.clearInterval(interval);
  }, []);

  const topBottlenecks = diagnostics?.top_10_bottlenecks ?? [];
  const startupPhases = diagnostics?.startup?.phases ?? [];
  const apiRows = diagnostics?.api?.slowest_endpoints ?? [];
  const queryRows = diagnostics?.database?.slowest_queries ?? [];
  const widgetRows = diagnostics?.dashboard_widgets?.slowest_widget_events ?? [];
  const backgroundRows = diagnostics?.background_tasks?.slowest_tasks ?? [];
  const cache = diagnostics?.cache ?? {};
  const initialLearning = diagnostics?.initial_learning_page_load ?? {};
  const snapshotRows = Object.values(diagnostics?.dashboard_snapshots?.latest_by_type ?? {}) as any[];
  const evidenceLabel = useMemo(() => evidenceFromCounts(diagnostics), [diagnostics]);

  if (error && !diagnostics) return <div className="terminal-empty">API error: {error}</div>;
  if (!diagnostics) return <LoadingState label="Loading performance diagnostics" />;

  return (
    <>
      <TerminalHeader
        eyebrow="Performance Diagnostics"
        title="Measure first. Optimize later."
        subtitle="Runtime timing for startup, API endpoints, SQLAlchemy queries, background workers and dashboard widgets. This page exposes bottlenecks without changing financial logic."
        statusItems={[
          { label: "Probe", value: probeStatus, tone: probeStatus === "complete" ? "positive" : "attention" },
          { label: "Evidence", value: evidenceLabel, tone: evidenceLabel.includes("low") ? "attention" : "positive" },
          { label: "Generated", value: formatTime(diagnostics.generated_at), tone: "info" },
          { label: "Policy", value: "measurement only", tone: "neutral" }
        ]}
        actions={<button className="terminal-button" onClick={runDashboardProbe}>Run dashboard probe</button>}
      />

      {error && <div className="terminal-empty" style={{ marginBottom: 12 }}>Refresh warning: {error}</div>}

      <section className="terminal-command-grid">
        <MetricCard label="Startup Duration" value={formatMs(diagnostics.startup?.total_duration_ms)} subvalue={`${startupPhases.length} measured phases`} icon={<Timer size={18} />} tone="attention" />
        <MetricCard label="API Avg" value={formatMs(diagnostics.api?.average_response_ms)} subvalue={`p95 ${formatMs(diagnostics.api?.p95_response_ms)} | ${diagnostics.api?.request_count ?? 0} requests`} icon={<Activity size={18} />} tone="info" />
        <MetricCard label="DB Avg" value={formatMs(diagnostics.database?.average_query_ms)} subvalue={`p95 ${formatMs(diagnostics.database?.p95_query_ms)} | ${diagnostics.database?.query_count ?? 0} queries`} icon={<Database size={18} />} tone="info" />
        <MetricCard label="Widget Avg" value={formatMs(diagnostics.dashboard_widgets?.average_widget_ms)} subvalue={`p95 ${formatMs(diagnostics.dashboard_widgets?.p95_widget_ms)}`} icon={<Gauge size={18} />} tone="neutral" />
        <MetricCard label="Cache Hit Rate" value={formatPct(cache.hit_rate)} subvalue={`${cache.hits ?? 0} hits / ${cache.misses ?? 0} misses`} icon={<Zap size={18} />} tone={cache.hit_rate === null || cache.hit_rate === undefined ? "attention" : "positive"} />
        <MetricCard label="Background Avg" value={formatMs(diagnostics.background_tasks?.average_duration_ms)} subvalue={`p95 ${formatMs(diagnostics.background_tasks?.p95_duration_ms)} | ${diagnostics.background_tasks?.event_count ?? 0} runs`} icon={<Activity size={18} />} tone="attention" />
      </section>

      <section className="professional-grid-2">
        <BloombergPanel title="Top 10 Bottlenecks" value={`${topBottlenecks.length} events`} subtitle="Slowest measured operations across API, DB, widgets and background tasks">
          <SimpleTable
            columns={["Kind", "Name", "Duration", "Rows"]}
            rows={topBottlenecks.map((row: any) => [
              row.kind,
              truncate(row.name, 92),
              formatMs(row.duration_ms),
              row.rows_scanned_estimate ?? "-"
            ])}
            empty="No bottleneck data has been recorded yet."
          />
        </BloombergPanel>

        <BloombergPanel title="Startup Breakdown" value={formatMs(diagnostics.startup?.total_duration_ms)} subtitle="Measured application startup phases">
          <SimpleTable
            columns={["Phase", "Duration", "Started"]}
            rows={startupPhases.map((row: any) => [row.name, formatMs(row.duration_ms), formatTime(row.started_at)])}
            empty="Startup phases will appear after the backend process starts."
          />
        </BloombergPanel>
      </section>

      <section className="professional-grid-2" style={{ marginTop: 12 }}>
        <BloombergPanel title="Initial Learning Page Load" value={`${clientStats?.initialLearningPage?.length ?? 0} requests`} subtitle="Browser-side request storm and dedupe visibility for the current route session">
          <div className="professional-grid-3" style={{ marginBottom: 10 }}>
            <MetricCard label="Total Requests" value={clientStats?.total ?? 0} />
            <MetricCard label="Duplicate Requests" value={clientStats?.duplicate ?? 0} />
            <MetricCard label="Cache Hits" value={clientStats?.cacheHits ?? 0} />
            <MetricCard label="Heavy POST During Load" value={initialLearning?.heavy_post_calls_during_page_load?.length ?? 0} />
            <MetricCard label="Server Frontend Events" value={initialLearning?.frontend_request_count ?? 0} />
            <MetricCard label="Server Cache Hits" value={initialLearning?.cache_hit_count ?? 0} />
          </div>
          <SimpleTable
            columns={["Method", "Endpoint", "Duration", "Status", "Dedupe"]}
            rows={(clientStats?.initialLearningPage ?? []).slice(-18).reverse().map((row: any) => [
              row.method,
              truncate(row.path, 86),
              formatMs(row.duration_ms),
              row.status,
              row.duplicate ? "yes" : row.cache_hit ? "cache" : "no"
            ])}
            empty="Open the Learning page in this session to collect initial-load request data."
          />
        </BloombergPanel>

        <BloombergPanel title="Recommended Next Optimization" value="from evidence" subtitle="Generated from currently visible bottleneck classes">
          <ul className="diagnostic-list">
            {recommendations(diagnostics, clientStats).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </BloombergPanel>
      </section>

      <section className="professional-grid-2" style={{ marginTop: 12 }}>
        <BloombergPanel title="Snapshot Freshness" value={`${diagnostics.dashboard_snapshots?.fresh_count ?? 0} fresh`} subtitle="Stale-but-usable dashboard payloads available to avoid blank loading states">
          <SimpleTable
            columns={["Snapshot", "Age", "Stale", "Compute", "Warnings"]}
            rows={snapshotRows.slice(0, 12).map((row: any) => [
              row.snapshot_type,
              formatSeconds(row.age_seconds),
              row.is_stale ? "yes" : "no",
              formatMs(row.computation_duration_ms),
              (row.warnings ?? []).length
            ])}
            empty="No dashboard snapshots have been written yet."
          />
        </BloombergPanel>

        <BloombergPanel title="Heavy POST Calls During Learning Load" value={`${initialLearning?.heavy_post_calls_during_page_load?.length ?? 0} events`} subtitle="These should stay at zero unless the user explicitly requests recalculation">
          <SimpleTable
            columns={["Method", "Path", "Duration", "Referer"]}
            rows={(initialLearning?.heavy_post_calls_during_page_load ?? []).slice(0, 10).map((row: any) => [
              row.method,
              truncate(row.path, 72),
              formatMs(row.duration_ms),
              truncate(row.referer, 72)
            ])}
            empty="No heavy recalculation POST was triggered during Learning page load."
          />
        </BloombergPanel>
      </section>

      <section className="professional-grid-2" style={{ marginTop: 12 }}>
        <BloombergPanel title="Slowest API Endpoints" value={`p95 ${formatMs(diagnostics.api?.p95_response_ms)}`} subtitle="Grouped by method and normalized path">
          <SimpleTable
            columns={["Endpoint", "Count", "Avg", "P95", "Max"]}
            rows={apiRows.slice(0, 14).map((row: any) => [
              `${row.method} ${row.path}`,
              row.count,
              formatMs(row.avg_ms),
              formatMs(row.p95_ms),
              formatMs(row.max_ms)
            ])}
            empty="No API requests recorded yet."
          />
        </BloombergPanel>

        <BloombergPanel title="Slowest Database Queries" value={`${diagnostics.database?.query_count ?? 0} queries`} subtitle="Exact query timing; scanned rows are rowcount when exposed by the driver">
          <SimpleTable
            columns={["Operation", "Duration", "Rows", "SQL"]}
            rows={queryRows.slice(0, 12).map((row: any) => [
              row.operation,
              formatMs(row.duration_ms),
              row.rows_scanned_estimate ?? "unknown",
              truncate(row.sql, 110)
            ])}
            empty="No SQL queries recorded yet."
          />
        </BloombergPanel>
      </section>

      <section className="professional-grid-2" style={{ marginTop: 12 }}>
        <BloombergPanel title="Slowest Dashboard Widgets" value={`${diagnostics.dashboard_widgets?.event_count ?? 0} events`} subtitle="Backend widget timings plus browser-side probe timings">
          <SimpleTable
            columns={["Widget", "Duration", "Source", "Status"]}
            rows={widgetRows.slice(0, 16).map((row: any) => [
              row.name,
              formatMs(row.duration_ms),
              row.event_type === "frontend_widget" ? "browser" : "backend",
              row.metadata?.status ?? "ok"
            ])}
            empty="Run the dashboard probe to collect widget timings."
          />
        </BloombergPanel>

        <BloombergPanel title="Background Task Durations" value={`${diagnostics.background_tasks?.event_count ?? 0} runs`} subtitle="Scheduler and startup worker timing">
          <SimpleTable
            columns={["Task", "Count", "Avg", "P95", "Max"]}
            rows={backgroundRows.slice(0, 12).map((row: any) => [
              row.name,
              row.count,
              formatMs(row.avg_ms),
              formatMs(row.p95_ms),
              formatMs(row.max_ms)
            ])}
            empty="No background jobs have completed in this process yet."
          />
        </BloombergPanel>
      </section>

      <section className="professional-grid-2" style={{ marginTop: 12 }}>
        <BloombergPanel title="Query Fingerprints" value="Grouped SQL" subtitle="Repeated query shapes ranked by p95 latency">
          <SimpleTable
            columns={["Count", "P95", "Max", "Rows", "Fingerprint"]}
            rows={(diagnostics.database?.slowest_query_fingerprints ?? []).slice(0, 12).map((row: any) => [
              row.count,
              formatMs(row.p95_ms),
              formatMs(row.max_ms),
              row.last_rows_scanned_estimate ?? "unknown",
              truncate(row.fingerprint, 120)
            ])}
            empty="No SQL fingerprints recorded yet."
          />
        </BloombergPanel>

        <BloombergPanel title="Observability Limits" value="Honest measurement" subtitle="Important boundaries before optimization decisions">
          <ul className="diagnostic-list">
            {(diagnostics.observability_limits ?? []).map((item: string) => <li key={item}>{item}</li>)}
            <li>{diagnostics.database?.rows_scanned_policy}</li>
            <li>{cache.note}</li>
          </ul>
        </BloombergPanel>
      </section>
    </>
  );
}

function SimpleTable({ columns, rows, empty }: { columns: string[]; rows: any[][]; empty: string }) {
  if (!rows.length) return <div className="terminal-empty">{empty}</div>;
  return (
    <div className="performance-table-wrap">
      <table className="asset-terminal-table performance-table">
        <thead>
          <tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${index}-${row.join("-")}`}>
              {row.map((cell, cellIndex) => <td key={`${cellIndex}-${String(cell).slice(0, 20)}`}>{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatMs(value: any) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "n/a";
  if (number >= 1000) return `${(number / 1000).toFixed(2)}s`;
  return `${number.toFixed(1)}ms`;
}

function formatPct(value: any) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "n/a";
  return `${(number * 100).toFixed(1)}%`;
}

function formatTime(value?: string | null) {
  if (!value) return "n/a";
  try {
    return new Date(value).toLocaleTimeString();
  } catch {
    return value;
  }
}

function formatSeconds(value: any) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "n/a";
  if (number < 60) return `${number.toFixed(0)}s`;
  if (number < 3600) return `${(number / 60).toFixed(1)}m`;
  return `${(number / 3600).toFixed(1)}h`;
}

function truncate(value: any, length: number) {
  const text = String(value ?? "");
  return text.length > length ? `${text.slice(0, length)}...` : text;
}

function evidenceFromCounts(diagnostics: Diagnostics | null) {
  if (!diagnostics) return "low evidence";
  const total = Number(diagnostics.api?.request_count ?? 0) + Number(diagnostics.database?.query_count ?? 0) + Number(diagnostics.dashboard_widgets?.event_count ?? 0);
  if (total > 500) return "strong evidence";
  if (total > 100) return "medium evidence";
  return "low evidence";
}

function recommendations(diagnostics: Diagnostics | null, clientStats: any | null) {
  const output: string[] = [];
  const slowApi = diagnostics?.api?.slowest_endpoints?.[0];
  const slowQuery = diagnostics?.database?.slowest_queries?.[0];
  const duplicates = Number(clientStats?.duplicate ?? 0);
  const heavyPosts = diagnostics?.initial_learning_page_load?.heavy_post_calls_during_page_load ?? [];
  const staleSnapshots = Number(diagnostics?.dashboard_snapshots?.stale_count ?? 0);
  if (duplicates > 0) output.push(`Request dedupe is catching ${duplicates} duplicate frontend calls in this session.`);
  if (heavyPosts.length > 0) output.push(`Remove or gate ${heavyPosts.length} heavy POST call(s) observed during Learning page load.`);
  if (staleSnapshots > 0) output.push(`${staleSnapshots} dashboard snapshot(s) are stale; verify background refresh cadence before adding live recomputation.`);
  if (slowApi) output.push(`Inspect ${slowApi.method} ${slowApi.path}: p95 ${formatMs(slowApi.p95_ms)} and max ${formatMs(slowApi.max_ms)}.`);
  if (slowQuery) output.push(`Inspect the slowest SQL operation ${slowQuery.operation}: ${formatMs(slowQuery.duration_ms)}.`);
  if ((diagnostics?.background_tasks?.slowest_tasks ?? []).length) output.push("Background worker timing is now available; compare startup pipeline versus scheduled refresh jobs before optimizing.");
  if (!output.length) output.push("Collect more requests first. Open Learning, Dashboard and Performance pages, then review the top bottlenecks.");
  return output;
}
