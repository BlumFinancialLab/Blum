"use client";

import { BrainStatus } from "@/lib/types";

export function FinancialBrainStatus({ status, busy, onRunCycle }: { status: BrainStatus | null; busy?: boolean; onRunCycle?: () => void }) {
  if (!status) {
    return (
      <section className="panel financial-brain-panel">
        <div className="panel-head">
          <span>Blum Financial Brain</span>
          <strong>Loading</strong>
        </div>
        <div className="empty-state">Learning status is loading from the backend memory layer.</div>
      </section>
    );
  }
  const calibration = status.confidence_calibration ?? {};
  const weights = status.active_weight_version?.weights ?? {};
  return (
    <section className="panel financial-brain-panel">
      <div className="panel-head">
        <span>Blum Financial Brain Status</span>
        <strong>{status.learning_state}</strong>
      </div>
      <div className="brain-status-grid">
        <BrainMetric label="Signals Evaluated" value={status.signals_evaluated} />
        <BrainMetric label="Historical Accuracy" value={percent(status.historical_accuracy)} />
        <BrainMetric label="7D Success Rate" value={percent(status.success_rate_7d)} />
        <BrainMetric label="30D Success Rate" value={percent(status.success_rate_30d)} />
        <BrainMetric label="Confidence Calibration" value={calibration.score === null || calibration.score === undefined ? calibration.status ?? "Pending" : `${Number(calibration.score).toFixed(1)}/100`} />
        <BrainMetric label="Data Quality Score" value={`${Number(status.data_quality_score ?? 0).toFixed(1)}/100`} />
        <BrainMetric label="Pending Horizons" value={status.pending_evaluations} />
        <BrainMetric label="Learning Cadence" value={`${status.learning_interval_minutes}m`} />
      </div>
      <div className="brain-two-col">
        <div>
          <h3>Best Performing Signal Types</h3>
          <PerformanceList rows={status.best_performing_signal_types} empty="Waiting for matured outcomes." />
        </div>
        <div>
          <h3>Weakest Signal Types</h3>
          <PerformanceList rows={status.weakest_signal_types} empty="No weak pattern confirmed yet." />
        </div>
      </div>
      <div className={`brain-drift ${status.model_drift_warning?.severity?.toLowerCase() ?? "info"}`}>
        <strong>{status.model_drift_warning?.status?.replaceAll("_", " ") ?? "drift pending"}</strong>
        <span>{status.model_drift_warning?.message ?? "The model needs more matured signals before drift can be measured."}</span>
      </div>
      <div className="weight-strip">
        {Object.entries(weights).slice(0, 9).map(([key, value]) => (
          <span key={key}>{key.replaceAll("_", " ")} <strong>{Number(value).toFixed(2)}</strong></span>
        ))}
      </div>
      <div className="governance-list">
        {status.governance.slice(0, 4).map((item) => <span key={item}>{item}</span>)}
      </div>
      {onRunCycle && (
        <div className="control-row" style={{ marginTop: 12, marginBottom: 0 }}>
          <button className="button primary" onClick={onRunCycle} disabled={busy}>{busy ? "Running learning cycle..." : "Run learning cycle"}</button>
        </div>
      )}
      <p>{status.disclaimer}</p>
    </section>
  );
}

function BrainMetric({ label, value }: { label: string; value: number | string }) {
  return <div className="brain-metric"><span>{label}</span><strong>{value}</strong></div>;
}

function PerformanceList({ rows, empty }: { rows: BrainStatus["best_performing_signal_types"]; empty: string }) {
  if (!rows?.length) return <div className="empty-state compact">{empty}</div>;
  return (
    <div className="brain-performance-list">
      {rows.slice(0, 5).map((row) => (
        <div key={row.key}>
          <strong>{row.key}</strong>
          <span>{percent(row.success_rate)} success | {row.mature_count} matured | score {row.accuracy_score.toFixed(1)}</span>
        </div>
      ))}
    </div>
  );
}

function percent(value: number | null | undefined) {
  if (value === null || value === undefined) return "Pending";
  return `${Math.round(Number(value) * 100)}%`;
}
