"use client";

import { useMemo, useState } from "react";

type MetricItem = {
  label: string;
  value: unknown;
  tone?: "positive" | "negative" | "warning" | "neutral";
  note?: string;
};

type DiagnosticColumn = {
  key: string;
  label: string;
  render?: (row: Record<string, unknown>) => string;
  tone?: (row: Record<string, unknown>) => string;
};

export function DiagnosticPanelRenderer({ panelId, title, data, onReload }: { panelId: string; title: string; data: unknown; onReload?: () => void }) {
  if (panelId === "reliability_by_regime") {
    return <ReliabilityByRegimeRenderer title={title} data={data} onReload={onReload} />;
  }
  if (panelId === "ensemble_status") {
    return <EnsembleStatusRenderer title={title} data={data} onReload={onReload} />;
  }
  return <GenericDiagnosticRenderer panelId={panelId} title={title} data={data} onReload={onReload} />;
}

export function MetricGrid({ items }: { items: MetricItem[] }) {
  return (
    <div className="diagnostic-metric-grid">
      {items.map((item) => (
        <div className={`diagnostic-metric ${item.tone ?? "neutral"}`} key={item.label}>
          <span>{item.label}</span>
          <strong>{formatUnknown(item.value)}</strong>
          {item.note && <p>{item.note}</p>}
        </div>
      ))}
    </div>
  );
}

export function EvidenceBadge({ label, tone = "neutral" }: { label: string; tone?: "positive" | "negative" | "warning" | "neutral" }) {
  return <span className={`evidence-badge ${tone}`}>{label}</span>;
}

export function ReliabilityBadge({ value }: { value: unknown }) {
  const numeric = numberOrNull(value);
  const tone = numeric == null ? "neutral" : numeric >= 75 ? "positive" : numeric < 50 ? "negative" : "warning";
  return <EvidenceBadge label={numeric == null ? "n/a" : `${numeric.toFixed(1)}/100`} tone={tone} />;
}

export function SampleSizeWarning({ sampleSize, threshold = 30 }: { sampleSize: unknown; threshold?: number }) {
  const value = numberOrNull(sampleSize);
  if (value == null) return <EvidenceBadge label="sample size unavailable" tone="warning" />;
  if (value < threshold) return <EvidenceBadge label={`weak evidence: ${value} samples`} tone="warning" />;
  return <EvidenceBadge label={`sample size: ${value}`} tone="positive" />;
}

export function DiagnosticTable({ columns, rows, limit = 10 }: { columns: DiagnosticColumn[]; rows: Record<string, unknown>[]; limit?: number }) {
  const [visible, setVisible] = useState(limit);
  const visibleRows = rows.slice(0, visible);
  if (!rows.length) return <EmptyState message="No rows available for this diagnostic panel yet." />;
  return (
    <div className="diagnostic-table-shell">
      <table className="diagnostic-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column.key}>{column.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {visibleRows.map((row, index) => (
            <tr key={`${index}-${columns.map((column) => String(row[column.key] ?? "")).join("-")}`}>
              {columns.map((column) => (
                <td key={column.key} className={column.tone?.(row) ?? ""}>
                  {column.render ? column.render(row) : formatUnknown(row[column.key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {visible < rows.length && (
        <button className="button compact" onClick={() => setVisible((current) => Math.min(rows.length, current + limit))}>
          Load more rows
        </button>
      )}
    </div>
  );
}

export function WeightDistributionTable({ weights }: { weights: Array<{ engine: string; weight: number; role: string; interpretation: string }> }) {
  return (
    <DiagnosticTable
      columns={[
        { key: "engine", label: "Engine" },
        { key: "weight", label: "Weight", render: (row) => formatPercentLike(row.weight) },
        { key: "role", label: "Role" },
        { key: "interpretation", label: "Interpretation" },
      ]}
      rows={weights}
      limit={12}
    />
  );
}

export function EmptyState({ message }: { message: string }) {
  return <div className="empty-state compact">{message}</div>;
}

export function JsonDebugToggle({ data }: { data: unknown }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="json-debug-toggle">
      <button className="button compact" onClick={() => setOpen((current) => !current)}>
        {open ? "Hide raw JSON" : "Show raw JSON"}
      </button>
      {open && <pre className="json-preview">{JSON.stringify(data, null, 2)}</pre>}
    </div>
  );
}

function ReliabilityByRegimeRenderer({ title, data, onReload }: { title: string; data: unknown; onReload?: () => void }) {
  const rows = normalizeRows(data);
  const totalRows = numberOrNull(getFirst(data, ["count", "total", "total_rows"])) ?? rows.length;
  const avgReliability = average(rows.map((row) => numberOrNull(getFirst(row, ["reliability_score", "reliability"]))).filter(isNumber));
  const strongest = maxBy(rows, (row) => numberOrNull(getFirst(row, ["reliability_score", "reliability"])));
  const weakest = minBy(rows, (row) => numberOrNull(getFirst(row, ["reliability_score", "reliability"])));
  const lowestSample = minValue(rows.map((row) => numberOrNull(getFirst(row, ["sample_size", "sample", "samples"]))).filter(isNumber));
  const strongestRegime = regimeByReliability(rows, "max");
  const weakestRegime = regimeByReliability(rows, "min");
  const warning = reliabilityWarning(rows, avgReliability, lowestSample);

  return (
    <div className="diagnostic-renderer">
      <PanelHeader title={title} status={`${totalRows} rows`} onReload={onReload} />
      <MetricGrid
        items={[
          { label: "Total Rows", value: totalRows },
          { label: "Strongest Engine", value: labelForEngine(strongest), tone: "positive" },
          { label: "Weakest Engine", value: labelForEngine(weakest), tone: "warning" },
          { label: "Avg Reliability", value: avgReliability == null ? "n/a" : `${avgReliability.toFixed(1)}/100`, tone: reliabilityTone(avgReliability) },
          { label: "Lowest Sample", value: lowestSample ?? "n/a", tone: lowestSample != null && lowestSample < 30 ? "warning" : "neutral" },
          { label: "Strongest Regime", value: strongestRegime ?? "n/a", tone: "positive" },
          { label: "Weakest Regime", value: weakestRegime ?? "n/a", tone: "warning" },
        ]}
      />
      <TruthSummary
        meaning="This matrix shows which BLUM engines or signal families have historically worked in specific regimes, sectors and horizons."
        evidence={lowestSample != null && lowestSample < 30 ? "Evidence is weak where sample size is below 30." : "Sample size is acceptable for a first read, but still needs regime coverage."}
        improving={avgReliability != null && avgReliability >= 60 ? "Reliability is constructive in the current sample." : "No durable reliability edge is visible yet."}
        warning={warning}
        next="Check whether high reliability also has benchmark-relative excess return and enough samples before trusting it."
      />
      <div className="diagnostic-badge-row">
        <SampleSizeWarning sampleSize={lowestSample} />
        <ReliabilityBadge value={avgReliability} />
        <EvidenceBadge label="negative return + positive excess needs review" tone="warning" />
      </div>
      <DiagnosticTable
        columns={[
          { key: "engine_name", label: "Engine", render: (row) => formatUnknown(getFirst(row, ["engine_name", "engine"])) },
          { key: "signal_type", label: "Signal", render: (row) => formatUnknown(getFirst(row, ["signal_type", "signal"])) },
          { key: "setup_type", label: "Setup", render: (row) => cleanLabel(getFirst(row, ["setup_type", "setup"])) },
          { key: "sector", label: "Sector" },
          { key: "horizon", label: "Horizon" },
          { key: "sample_size", label: "Sample", render: (row) => formatUnknown(getFirst(row, ["sample_size", "sample", "samples"])) },
          { key: "hit_rate", label: "Hit Rate", render: (row) => formatPercentLike(getFirst(row, ["hit_rate", "win_rate"])) },
          { key: "average_return", label: "Avg Return", render: (row) => formatSignedPercent(getFirst(row, ["average_return", "avg_return"])) },
          { key: "excess_return_vs_benchmark", label: "Excess vs Benchmark", render: (row) => formatSignedPercent(getFirst(row, ["excess_return_vs_benchmark", "excess_return"])) },
          { key: "max_drawdown", label: "Drawdown", render: (row) => formatSignedPercent(getFirst(row, ["max_drawdown", "average_drawdown"])) },
          { key: "reliability_score", label: "Reliability", render: (row) => formatScore(getFirst(row, ["reliability_score", "reliability"])) },
          { key: "confidence_penalty", label: "Confidence Penalty", render: (row) => formatUnknown(getFirst(row, ["confidence_penalty", "penalty"])) },
          { key: "last_updated", label: "Updated", render: (row) => formatDateTime(getFirst(row, ["last_updated", "updated_at", "calculated_at"])) },
        ]}
        rows={rows}
        limit={10}
      />
      <JsonDebugToggle data={data} />
    </div>
  );
}

function EnsembleStatusRenderer({ title, data, onReload }: { title: string; data: unknown; onReload?: () => void }) {
  const weights = normalizeWeights(data);
  const totalVotes = numberOrNull(getFirst(data, ["total_votes", "vote_count", "votes"])) ?? normalizeRows(getFirst(data, ["votes", "engine_votes", "rows"])).length;
  const activeEngines = weights.length || numberOrNull(getFirst(data, ["active_engines", "engine_count"])) || 0;
  const highest = maxBy(weights, (row) => row.weight);
  const lowest = minBy(weights, (row) => row.weight);
  const disagreements = normalizeRows(getFirst(data, ["disagreements", "recent_disagreements", "disagreement_cases"]));
  const sampleSize = numberOrNull(getFirst(data, ["sample_size", "validation_sample_size", "votes_sample_size"])) ?? totalVotes;

  return (
    <div className="diagnostic-renderer">
      <PanelHeader title={title} status={`${activeEngines} engines`} onReload={onReload} />
      <MetricGrid
        items={[
          { label: "Total Votes", value: totalVotes },
          { label: "Active Engines", value: activeEngines },
          { label: "Highest Weighted", value: highest ? highest.engine : "n/a", tone: "positive", note: highest ? formatPercentLike(highest.weight) : undefined },
          { label: "Lowest Weighted", value: lowest ? lowest.engine : "n/a", tone: "warning", note: lowest ? formatPercentLike(lowest.weight) : undefined },
        ]}
      />
      <TruthSummary
        meaning="This panel shows which BLUM engines currently influence the ensemble and whether their weights are explainable."
        evidence={sampleSize && sampleSize < 50 ? "Weights are not backed by enough samples yet." : "Weights have at least basic sample support, but need regime-aware validation."}
        improving={weights.length ? "Ensemble weights are visible and auditable." : "No active weight distribution is available yet."}
        warning={disagreements.length ? "Engine disagreement exists and should reduce confidence when material." : "No disagreements are stored; this can mean either alignment or missing disagreement tracking."}
        next="Check whether high-weight engines have recent benchmark-relative reliability in the current regime."
      />
      <div className="diagnostic-badge-row">
        <SampleSizeWarning sampleSize={sampleSize} threshold={50} />
        {!disagreements.length && <EvidenceBadge label="no disagreements stored" tone="warning" />}
        {!weights.length && <EvidenceBadge label="weights unavailable" tone="warning" />}
      </div>
      <WeightDistributionTable weights={weights} />
      <section className="diagnostic-section">
        <h3>Disagreements</h3>
        {disagreements.length ? (
          <DiagnosticTable
            columns={[
              { key: "ticker", label: "Ticker" },
              { key: "engine_name", label: "Engine", render: (row) => formatUnknown(getFirst(row, ["engine_name", "engine"])) },
              { key: "vote", label: "Vote" },
              { key: "confidence", label: "Confidence", render: (row) => formatScore(getFirst(row, ["confidence", "score"])) },
              { key: "created_at", label: "Created", render: (row) => formatDateTime(getFirst(row, ["created_at", "timestamp"])) },
            ]}
            rows={disagreements}
            limit={6}
          />
        ) : (
          <EmptyState message="No ensemble disagreements are stored yet. Treat consensus confidence cautiously until disagreement tracking is populated." />
        )}
      </section>
      <JsonDebugToggle data={data} />
    </div>
  );
}

function GenericDiagnosticRenderer({ panelId, title, data, onReload }: { panelId: string; title: string; data: unknown; onReload?: () => void }) {
  const rows = normalizeRows(data);
  const metrics = topLevelMetrics(data);
  const warning = genericWarning(data, rows);
  const status = String(getFirst(data, ["status", "snapshot_status", "health", "classification"]) ?? `${metrics.length} metrics`);
  return (
    <div className="diagnostic-renderer">
      <PanelHeader title={title} status={status} onReload={onReload} />
      <MetricGrid items={metrics.slice(0, 8)} />
      <TruthSummary
        meaning={genericMeaning(panelId)}
        evidence={rows.length ? `${rows.length} evidence rows are loaded in this panel.` : "No row-level evidence is available in this payload."}
        improving={genericImprovement(data)}
        warning={warning}
        next={genericNextStep(panelId)}
      />
      <div className="diagnostic-badge-row">
        <EvidenceBadge label="loaded on demand" tone="positive" />
        {rows.length > 0 && <SampleSizeWarning sampleSize={inferSampleSize(data, rows)} />}
        {warning !== "No major warning detected in the summary payload." && <EvidenceBadge label="review warning" tone="warning" />}
      </div>
      {rows.length ? (
        <DiagnosticTable columns={inferColumns(rows)} rows={rows} limit={10} />
      ) : (
        <KeyValueSummary data={data} />
      )}
      <JsonDebugToggle data={data} />
    </div>
  );
}

function PanelHeader({ title, status, onReload }: { title: string; status: string; onReload?: () => void }) {
  return (
    <div className="diagnostic-panel-head">
      <div>
        <EvidenceBadge label="loaded on demand" tone="positive" />
        <h3>{title}</h3>
      </div>
      <div className="diagnostic-panel-actions">
        <EvidenceBadge label={status} tone={statusTone(status)} />
        {onReload && <button className="button compact" onClick={onReload}>Reload panel</button>}
      </div>
    </div>
  );
}

function TruthSummary({ meaning, evidence, improving, warning, next }: { meaning: string; evidence: string; improving: string; warning: string; next: string }) {
  return (
    <div className="truth-summary-grid">
      <div><span>What this means</span><strong>{meaning}</strong></div>
      <div><span>Evidence strength</span><strong>{evidence}</strong></div>
      <div><span>Improving?</span><strong>{improving}</strong></div>
      <div><span>Main warning</span><strong>{warning}</strong></div>
      <div><span>Check next</span><strong>{next}</strong></div>
    </div>
  );
}

function KeyValueSummary({ data }: { data: unknown }) {
  const entries = Object.entries(flattenObject(data).slice(0, 12).reduce<Record<string, unknown>>((acc, [key, value]) => ({ ...acc, [key]: value }), {}));
  if (!entries.length) return <EmptyState message="No summary fields available yet." />;
  return (
    <div className="diagnostic-key-values">
      {entries.map(([key, value]) => (
        <div key={key}>
          <span>{cleanLabel(key)}</span>
          <strong>{formatUnknown(value)}</strong>
        </div>
      ))}
    </div>
  );
}

function normalizeRows(data: unknown): Record<string, unknown>[] {
  if (Array.isArray(data)) return data.filter(isRecord);
  if (!isRecord(data)) return [];
  const candidates = [
    data.rows,
    data.items,
    data.results,
    data.records,
    data.events,
    data.actions,
    data.benchmarks,
    data.weights,
    getFirst(data, ["payload.rows", "snapshot.payload.rows"]),
  ];
  for (const candidate of candidates) {
    if (Array.isArray(candidate)) return candidate.filter(isRecord);
  }
  return [];
}

function normalizeWeights(data: unknown): Array<{ engine: string; weight: number; role: string; interpretation: string }> {
  const raw = getFirst(data, ["weights_json", "weights", "active_weights", "current_weights", "payload.weights", "snapshot.payload.weights"]);
  const rows = Array.isArray(raw) ? raw : isRecord(raw) ? Object.entries(raw).map(([engine, weight]) => ({ engine, weight })) : [];
  return rows
    .filter(isRecord)
    .map((row) => {
      const engine = String(getFirst(row, ["engine", "engine_name", "name"]) ?? "unknown_engine");
      const weight = numberOrNull(getFirst(row, ["weight", "value", "score"])) ?? 0;
      return {
        engine,
        weight,
        role: weight >= 0.25 ? "primary" : weight >= 0.1 ? "supporting" : "low influence",
        interpretation: interpretWeight(engine, weight),
      };
    })
    .sort((a, b) => b.weight - a.weight);
}

function topLevelMetrics(data: unknown): MetricItem[] {
  const entries = flattenObject(data)
    .filter(([, value]) => ["string", "number", "boolean"].includes(typeof value) || value == null)
    .slice(0, 12);
  if (!entries.length) return [{ label: "Status", value: "No metrics available", tone: "warning" }];
  return entries.map(([key, value]) => ({
    label: cleanLabel(key),
    value,
    tone: metricTone(key, value),
  }));
}

function flattenObject(data: unknown, prefix = "", depth = 0): Array<[string, unknown]> {
  if (!isRecord(data) || depth > 2) return [];
  const output: Array<[string, unknown]> = [];
  Object.entries(data).forEach(([key, value]) => {
    const nextKey = prefix ? `${prefix}.${key}` : key;
    if (Array.isArray(value)) {
      output.push([`${nextKey}.count`, value.length]);
    } else if (isRecord(value)) {
      output.push(...flattenObject(value, nextKey, depth + 1));
    } else {
      output.push([nextKey, value]);
    }
  });
  return output;
}

function inferColumns(rows: Record<string, unknown>[]): DiagnosticColumn[] {
  const preferred = [
    "ticker",
    "engine_name",
    "setup_type",
    "sector",
    "status",
    "sample_size",
    "score",
    "confidence",
    "reliability_score",
    "excess_return",
    "created_at",
    "updated_at",
  ];
  const keys = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  const ordered = [...preferred.filter((key) => keys.includes(key)), ...keys.filter((key) => !preferred.includes(key))].slice(0, 8);
  return ordered.map((key) => ({
    key,
    label: cleanLabel(key),
    render: (row) => formatCell(key, row[key]),
  }));
}

function formatCell(key: string, value: unknown) {
  if (key.includes("date") || key.endsWith("_at") || key.includes("timestamp")) return formatDateTime(value);
  if (key.includes("rate") || key.includes("return") || key.includes("drawdown") || key.includes("excess")) return formatSignedPercent(value);
  if (key.includes("score") || key.includes("confidence") || key.includes("reliability")) return formatScore(value);
  return formatUnknown(value);
}

function getFirst(data: unknown, paths: string[]): unknown {
  for (const path of paths) {
    const value = getPath(data, path);
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return undefined;
}

function getPath(data: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((current, key) => (isRecord(current) ? current[key] : undefined), data);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function numberOrNull(value: unknown): number | null {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function average(values: number[]) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
}

function minValue(values: number[]) {
  return values.length ? Math.min(...values) : null;
}

function maxBy<T>(rows: T[], getter: (row: T) => number | null): T | null {
  return rows.reduce<T | null>((best, row) => {
    const value = getter(row);
    if (value == null) return best;
    const bestValue = best == null ? null : getter(best);
    return best == null || bestValue == null || value > bestValue ? row : best;
  }, null);
}

function minBy<T>(rows: T[], getter: (row: T) => number | null): T | null {
  return rows.reduce<T | null>((best, row) => {
    const value = getter(row);
    if (value == null) return best;
    const bestValue = best == null ? null : getter(best);
    return best == null || bestValue == null || value < bestValue ? row : best;
  }, null);
}

function regimeByReliability(rows: Record<string, unknown>[], direction: "max" | "min") {
  const grouped = new Map<string, number[]>();
  rows.forEach((row) => {
    const regime = String(getFirst(row, ["market_regime", "regime", "volatility_regime", "breadth_regime"]) ?? "");
    const reliability = numberOrNull(getFirst(row, ["reliability_score", "reliability"]));
    if (!regime || reliability == null) return;
    grouped.set(regime, [...(grouped.get(regime) ?? []), reliability]);
  });
  const aggregates = Array.from(grouped.entries()).map(([regime, values]) => ({ regime, value: average(values) ?? 0 }));
  const selected = direction === "max" ? maxBy(aggregates, (row) => row.value) : minBy(aggregates, (row) => row.value);
  return selected?.regime;
}

function labelForEngine(row: Record<string, unknown> | null) {
  if (!row) return "n/a";
  return formatUnknown(getFirst(row, ["engine_name", "engine", "module_name"]));
}

function reliabilityWarning(rows: Record<string, unknown>[], avgReliability: number | null, lowestSample: number | null) {
  const contradiction = rows.find((row) => {
    const avgReturn = numberOrNull(getFirst(row, ["average_return", "avg_return"]));
    const excess = numberOrNull(getFirst(row, ["excess_return_vs_benchmark", "excess_return"]));
    return avgReturn != null && excess != null && avgReturn < 0 && excess > 0;
  });
  if (lowestSample != null && lowestSample < 30) return "Small sample size: treat as weak evidence.";
  if (contradiction) return "Negative average return with positive excess return needs review.";
  if (avgReliability != null && avgReliability > 75) return "Reliability is promising but not durable without more samples.";
  return "No major warning detected in the summary payload.";
}

function genericMeaning(panelId: string) {
  const copy: Record<string, string> = {
    thesis_survival: "Shows whether BLUM theses remain valid, weaken, expire or get invalidated over time.",
    conviction_decay: "Shows whether thesis confidence is fresh, stable, decaying or stale as new evidence arrives.",
    training_quality: "Shows which examples are strong enough to teach the future BLUM reasoning model.",
    benchmark_relative: "Shows whether BLUM evidence is beating relevant benchmarks or only moving with beta.",
    decision_superiority: "Shows whether BLUM selected the best available opportunity at decision time.",
    business_quality: "Shows whether company quality supports or contradicts market setups.",
    portfolio_intelligence: "Shows whether individual opportunities improve portfolio quality and risk.",
    capital_allocation: "Shows whether sizing and capital allocation are disciplined.",
    alpha_recovery: "Shows why alpha was lost or gained and which recovery actions are proposed.",
    meta_cognition: "Shows what BLUM is learning about its own reasoning process.",
    runtime_state: "Shows runtime health, failed modules, stale snapshots and current bottlenecks.",
    snapshot_health: "Shows whether UI snapshots are present, stale or missing.",
    learning_health: "Shows whether backend learning workers are alive and current.",
    performance_diagnostics: "Shows measured endpoint, database, widget and background task timing.",
  };
  return copy[panelId] ?? "Shows stored diagnostic evidence for this BLUM subsystem.";
}

function genericImprovement(data: unknown) {
  const trend = String(getFirst(data, ["trend_label", "status", "classification", "system_readiness.status"]) ?? "").toLowerCase();
  if (trend.includes("improving") || trend.includes("ready") || trend.includes("healthy")) return "Current summary is constructive.";
  if (trend.includes("deteriorating") || trend.includes("failed") || trend.includes("underperform")) return "Current summary is negative or degraded.";
  return "Improvement cannot be inferred from this payload alone.";
}

function genericWarning(data: unknown, rows: Record<string, unknown>[]) {
  const warnings = getFirst(data, ["warnings", "warnings_json", "snapshot_warnings", "observability_limits"]);
  if (Array.isArray(warnings) && warnings.length) return String(warnings[0]);
  const sample = inferSampleSize(data, rows);
  if (sample != null && sample < 30) return "Small sample size: treat this diagnostic as weak evidence.";
  return "No major warning detected in the summary payload.";
}

function genericNextStep(panelId: string) {
  if (panelId === "performance_diagnostics") return "Open the slowest endpoints and confirm whether snapshot reads stay under budget.";
  if (panelId === "snapshot_health") return "Refresh missing snapshots from background jobs, not from page render.";
  if (panelId === "runtime_state") return "Investigate failed or stale modules before trusting higher-level conclusions.";
  return "Check sample size, benchmark-relative result and the main contradiction before trusting the signal.";
}

function inferSampleSize(data: unknown, rows: Record<string, unknown>[]) {
  return numberOrNull(getFirst(data, ["sample_size", "trades_count", "total_votes", "count", "total"])) ?? rows.length;
}

function interpretWeight(engine: string, weight: number) {
  if (weight >= 0.25) return `${engine} is a primary driver; require strong evidence and regime fit.`;
  if (weight >= 0.1) return `${engine} supports consensus but should not dominate alone.`;
  return `${engine} has low influence or needs more validation.`;
}

function statusTone(status: string): "positive" | "negative" | "warning" | "neutral" {
  const value = status.toLowerCase();
  if (value.includes("ready") || value.includes("healthy") || value.includes("ok")) return "positive";
  if (value.includes("fail") || value.includes("underperform") || value.includes("error")) return "negative";
  if (value.includes("stale") || value.includes("missing") || value.includes("weak") || value.includes("warning")) return "warning";
  return "neutral";
}

function reliabilityTone(value: number | null): "positive" | "negative" | "warning" | "neutral" {
  if (value == null) return "neutral";
  if (value >= 70) return "positive";
  if (value < 45) return "negative";
  return "warning";
}

function metricTone(key: string, value: unknown): "positive" | "negative" | "warning" | "neutral" {
  const text = `${key} ${String(value)}`.toLowerCase();
  if (text.includes("underperform") || text.includes("failed") || text.includes("negative")) return "negative";
  if (text.includes("warning") || text.includes("stale") || text.includes("missing") || text.includes("weak")) return "warning";
  if (text.includes("ready") || text.includes("healthy") || text.includes("outperform")) return "positive";
  return "neutral";
}

function formatUnknown(value: unknown) {
  if (value === null || value === undefined || value === "") return "n/a";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3);
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return `${value.length} items`;
  if (isRecord(value)) return `${Object.keys(value).length} fields`;
  return cleanLabel(value);
}

function formatScore(value: unknown) {
  const numeric = numberOrNull(value);
  return numeric == null ? "n/a" : `${numeric.toFixed(1)}/100`;
}

function formatPercentLike(value: unknown) {
  const numeric = numberOrNull(value);
  if (numeric == null) return "n/a";
  const percent = Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
  return `${percent.toFixed(2)}%`;
}

function formatSignedPercent(value: unknown) {
  const numeric = numberOrNull(value);
  if (numeric == null) return "n/a";
  const percent = Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
  const sign = percent > 0 ? "+" : "";
  return `${sign}${percent.toFixed(2)}%`;
}

function formatDateTime(value: unknown) {
  if (!value) return "n/a";
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return formatUnknown(value);
  return date.toLocaleString();
}

function cleanLabel(value: unknown) {
  return String(value ?? "n/a").replaceAll("_", " ");
}
