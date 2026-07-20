"use client";

import { AlertTriangle, CheckCircle2, LockKeyhole, TrendingDown, TrendingUp } from "lucide-react";
import { BloombergPanel } from "@/components/FinancialTerminal";

type NumberLike = number | null | undefined;
type SeriesRow = Record<string, unknown> & { timestamp?: string | null };

export function BrainEvidenceCharts({ data }: { data: any }) {
  const progress = data?.brain_progress ?? {};
  const learning = data?.learning_proof ?? {};
  const trading = data?.trading_proof ?? {};
  const readiness = data?.copy_readiness ?? {};
  const pilot = data?.institutional_pilot ?? {};

  return (
    <section className="brain-proof-grid" aria-label="BLUM learning and trading evidence">
      <BloombergPanel
        title="Brain Improvement"
        value={<TrendLabel value={progress.trend} />}
        subtitle="Stored Brain Score, Decision Quality and Learning Velocity. No synthetic points."
      >
        <LineEvidenceChart
          rows={progress.series ?? []}
          series={[
            { key: "brain_score", label: "Brain", color: "#ffb000" },
            { key: "decision_quality", label: "Decision", color: "#4dd8ff" },
            { key: "learning_velocity", label: "Velocity", color: "#20e070" },
          ]}
          valueSuffix=""
        />
        <EvidenceFooter warning={progress.evidence_warning} sample={progress.sample_size} />
      </BloombergPanel>

      <BloombergPanel
        title="P/L vs Benchmark"
        value={<MoneyValue value={trading.realized_pnl_eur} />}
        subtitle="Paper-forward net P/L against matched holding-period benchmark evidence."
      >
        <LineEvidenceChart
          rows={trading.equity_series ?? []}
          series={[
            { key: "blum_equity", label: "BLUM", color: "#20e070" },
            { key: "benchmark_equity", label: "Benchmark", color: "#4dd8ff" },
          ]}
          valueSuffix=" EUR"
        />
        <MetricStrip
          items={[
            ["W / L", `${trading.wins ?? 0} / ${trading.losses ?? 0}`],
            ["Expectancy", formatSigned(trading.expectancy_r, "R")],
            ["Drawdown", formatNumber(trading.max_drawdown_pct, "%")],
            ["Excess", formatSigned(trading.benchmark_excess_pct, "%")],
          ]}
        />
        <EvidenceFooter warning={trading.sample_warning || trading.benchmark_warning} sample={trading.closed_trades} />
      </BloombergPanel>

      <BloombergPanel
        title="Learning Throughput"
        value={<TrendLabel value={learning.trend} />}
        subtitle="Predictions converted into evaluated outcomes and persistent memory updates per cycle."
      >
        <ThroughputChart rows={learning.series ?? []} />
        <MetricStrip
          items={[
            ["Productive cycles", formatInteger(learning.productive_cycles)],
            ["Predictions", formatInteger(learning.predictions_created)],
            ["Outcomes", formatInteger(learning.outcomes_evaluated)],
            ["Memory", formatInteger(learning.memory_updates)],
          ]}
        />
        <EvidenceFooter warning={learning.sample_warning} sample={learning.productive_cycles} />
      </BloombergPanel>

      <BloombergPanel
        title="Pilot Capital Gate"
        value={<ReadinessLabel status={pilot.status ?? readiness.copy_readiness_status} />}
        subtitle="Controlled pilot eligibility requires mature forward evidence and active risk controls."
      >
        <div className="copy-gate-status">
          <div>
            <span>Kill switch</span>
            <strong>{pilot.kill_switch?.active ? "ACTIVE" : "CLEAR"}</strong>
          </div>
          <div>
            <span>Max pilot capital</span>
            <strong>{formatNumber(pilot.capital_envelope?.eligible_capital_percent, "%")}</strong>
          </div>
          <div>
            <span>Risk per trade</span>
            <strong>{formatNumber(pilot.capital_envelope?.max_risk_per_trade_percent, "%")}</strong>
          </div>
          <div>
            <span>Pilot readiness</span>
            <strong>{formatNumber(pilot.readiness_score, "/100")}</strong>
          </div>
        </div>
        <div className="copy-gate-progress">
          <ProgressRow
            label="Strategy forward sample"
            value={readiness.strategy_forward_trades}
            target={readiness.required_capital_strategy_forward_trades}
            progress={readiness.capital_strategy_forward_progress}
          />
          <ProgressRow
            label="Global forward sample"
            value={readiness.global_forward_trades}
            target={readiness.required_capital_global_forward_trades}
            progress={readiness.capital_global_forward_progress}
          />
          <ProgressRow
            label="Observation days"
            value={readiness.observation_days}
            target={readiness.required_capital_observation_days}
            progress={readiness.capital_observation_progress}
          />
        </div>
        {!!pilot.blockers?.length && (
          <div className="copy-gate-blockers">
            <AlertTriangle size={14} />
            <span>Blocked by: {pilot.blockers.slice(0, 3).map(humanize).join(", ")}</span>
          </div>
        )}
        <p className="copy-gate-next">Next milestone: {pilot.next_milestone ?? "Collect more verified forward evidence."}</p>
        <p className="copy-gate-next">Controlled external validation only. No guaranteed profit or automatic broker execution.</p>
      </BloombergPanel>
    </section>
  );
}

function LineEvidenceChart({
  rows,
  series,
  valueSuffix,
}: {
  rows: SeriesRow[];
  series: Array<{ key: string; label: string; color: string }>;
  valueSuffix: string;
}) {
  const boundedRows = rows.slice(-30);
  const allValues = boundedRows.flatMap((row) => series.map((item) => numeric(row[item.key])).filter(isNumber));
  if (boundedRows.length < 2 || allValues.length < 2) {
    return <EvidenceState message="Insufficient evidence: at least two timestamped observations are required." />;
  }
  const min = Math.min(...allValues);
  const max = Math.max(...allValues);
  const padding = Math.max((max - min) * 0.12, 1);
  const low = min - padding;
  const high = max + padding;
  const span = high - low || 1;
  const width = 640;
  const height = 210;
  const left = 42;
  const right = 16;
  const top = 14;
  const bottom = 28;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const pointFor = (value: number, index: number) => {
    const x = left + (index / Math.max(1, boundedRows.length - 1)) * plotWidth;
    const y = top + (1 - (value - low) / span) * plotHeight;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  };

  return (
    <div className="brain-evidence-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Evidence trend chart">
        {[0, 1, 2, 3].map((index) => {
          const y = top + (index / 3) * plotHeight;
          const value = high - (index / 3) * span;
          return (
            <g key={index}>
              <line x1={left} y1={y} x2={width - right} y2={y} className="brain-chart-gridline" />
              <text x={left - 6} y={y + 4} textAnchor="end" className="brain-chart-axis">{compact(value)}{valueSuffix}</text>
            </g>
          );
        })}
        {series.map((item) => {
          const points = boundedRows
            .map((row, index) => {
              const value = numeric(row[item.key]);
              return value === null ? null : pointFor(value, index);
            })
            .filter(Boolean)
            .join(" ");
          return points ? <polyline key={item.key} points={points} fill="none" stroke={item.color} strokeWidth="2.4" vectorEffect="non-scaling-stroke" /> : null;
        })}
      </svg>
      <div className="brain-chart-legend">
        {series.map((item) => <span key={item.key}><i style={{ background: item.color }} />{item.label}</span>)}
        <time>{shortDate(boundedRows[0]?.timestamp)} → {shortDate(boundedRows[boundedRows.length - 1]?.timestamp)}</time>
      </div>
    </div>
  );
}

function ThroughputChart({ rows }: { rows: SeriesRow[] }) {
  const boundedRows = rows.slice(-12);
  const keys = ["predictions", "outcomes", "memory_updates"];
  const values = boundedRows.flatMap((row) => keys.map((key) => numeric(row[key])).filter(isNumber));
  if (!boundedRows.length || !values.length) {
    return <EvidenceState message="Insufficient evidence: no productive learning cycle is stored yet." />;
  }
  const max = Math.max(...values, 1);
  const width = 640;
  const height = 210;
  const top = 16;
  const bottom = 24;
  const plotHeight = height - top - bottom;
  const groupWidth = width / boundedRows.length;
  const barWidth = Math.max(3, Math.min(12, groupWidth / 4));
  const colors = ["#ffb000", "#4dd8ff", "#20e070"];
  return (
    <div className="brain-evidence-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Learning throughput chart">
        {[0, 1, 2].map((index) => {
          const y = top + (index / 2) * plotHeight;
          return <line key={index} x1="0" y1={y} x2={width} y2={y} className="brain-chart-gridline" />;
        })}
        {boundedRows.map((row, index) => {
          const center = groupWidth * index + groupWidth / 2;
          return keys.map((key, keyIndex) => {
            const value = numeric(row[key]) ?? 0;
            const barHeight = (value / max) * plotHeight;
            const x = center + (keyIndex - 1) * (barWidth + 2) - barWidth / 2;
            return <rect key={`${index}-${key}`} x={x} y={top + plotHeight - barHeight} width={barWidth} height={barHeight} fill={colors[keyIndex]} rx="1" />;
          });
        })}
      </svg>
      <div className="brain-chart-legend">
        <span><i style={{ background: colors[0] }} />Predictions</span>
        <span><i style={{ background: colors[1] }} />Outcomes</span>
        <span><i style={{ background: colors[2] }} />Memory</span>
        <time>Last {boundedRows.length} cycles</time>
      </div>
    </div>
  );
}

function ProgressRow({ label, value, target, progress }: { label: string; value: NumberLike; target: NumberLike; progress: NumberLike }) {
  const percentage = Math.max(0, Math.min(100, (numeric(progress) ?? 0) * 100));
  return (
    <div className="copy-progress-row">
      <div><span>{label}</span><strong>{value ?? "n/a"} / {target ?? "n/a"}</strong></div>
      <i><b style={{ width: `${percentage}%` }} /></i>
    </div>
  );
}

function MetricStrip({ items }: { items: Array<[string, string]> }) {
  return <div className="brain-proof-metrics">{items.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>;
}

function EvidenceFooter({ warning, sample }: { warning?: string | null; sample?: NumberLike }) {
  return (
    <div className={`brain-evidence-footer ${warning ? "is-warning" : "is-valid"}`}>
      {warning ? <AlertTriangle size={13} /> : <CheckCircle2 size={13} />}
      <span>{warning || "Evidence threshold met for this view."}</span>
      <b>n={sample ?? 0}</b>
    </div>
  );
}

function EvidenceState({ message }: { message: string }) {
  return <div className="brain-evidence-empty"><AlertTriangle size={16} /><strong>Insufficient evidence</strong><span>{message}</span></div>;
}

function TrendLabel({ value }: { value?: string | null }) {
  const trend = String(value ?? "insufficient_evidence");
  const Icon = trend === "improving" ? TrendingUp : trend === "deteriorating" ? TrendingDown : AlertTriangle;
  return <span className={`brain-trend trend-${trend}`}><Icon size={13} />{humanize(trend)}</span>;
}

function ReadinessLabel({ status }: { status?: string | null }) {
  const ready = status === "COPY_READY_PAPER_ONLY" || status === "COPY_READY_HIGH_CONFIDENCE";
  return <span className={`brain-trend ${ready ? "trend-improving" : "trend-insufficient_evidence"}`}>{ready ? <CheckCircle2 size={13} /> : <LockKeyhole size={13} />}{humanize(status ?? "NOT_READY")}</span>;
}

function MoneyValue({ value }: { value: NumberLike }) {
  const number = numeric(value);
  if (number === null) return <span>n/a</span>;
  return <span className={number >= 0 ? "value-positive" : "value-negative"}>{number >= 0 ? "+" : ""}{number.toFixed(2)} EUR</span>;
}

function numeric(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function isNumber(value: number | null): value is number {
  return value !== null;
}

function formatNumber(value: NumberLike, suffix = "") {
  const number = numeric(value);
  return number === null ? "n/a" : `${number.toFixed(1)}${suffix}`;
}

function formatSigned(value: NumberLike, suffix = "") {
  const number = numeric(value);
  return number === null ? "n/a" : `${number >= 0 ? "+" : ""}${number.toFixed(2)}${suffix}`;
}

function formatInteger(value: NumberLike) {
  const number = numeric(value);
  return number === null ? "n/a" : Math.round(number).toString();
}

function compact(value: number) {
  return Math.abs(value) >= 1000 ? `${(value / 1000).toFixed(1)}k` : value.toFixed(Math.abs(value) < 10 ? 1 : 0);
}

function humanize(value: unknown) {
  return String(value ?? "unknown").replaceAll("_", " ").toLowerCase();
}

function shortDate(value?: string | null) {
  if (!value) return "n/a";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString(undefined, { day: "2-digit", month: "short" });
}
