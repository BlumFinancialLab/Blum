"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { BrainAccuracy, BrainEvaluation, Signal } from "@/lib/types";
import { LoadingState } from "@/components/LoadingState";
import { SignalTable } from "@/components/SignalTable";

export default function SignalLabPage() {
  const [signals, setSignals] = useState<Signal[] | null>(null);
  const [evaluations, setEvaluations] = useState<BrainEvaluation[]>([]);
  const [brainAccuracy, setBrainAccuracy] = useState<BrainAccuracy | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [assetType, setAssetType] = useState("");
  const [risk, setRisk] = useState("");
  const [classification, setClassification] = useState("");
  const load = () => {
    Promise.allSettled([api.topSignals("?limit=80"), api.brainSignalEvaluations(160), api.brainAccuracy()] as const)
      .then(([signalsResult, evaluationsResult, accuracyResult]) => {
        if (signalsResult.status === "fulfilled") setSignals(signalsResult.value);
        if (evaluationsResult.status === "fulfilled") setEvaluations(evaluationsResult.value);
        if (accuracyResult.status === "fulfilled") setBrainAccuracy(accuracyResult.value);
      });
  };
  useEffect(() => { load(); }, []);
  const filtered = useMemo(() => {
    return (signals ?? []).filter((signal) =>
      (!assetType || signal.asset?.asset_type === assetType) &&
      (!risk || signal.risk_level === risk) &&
      (!classification || signal.classification === classification)
    );
  }, [signals, assetType, risk, classification]);
  const runLearning = async () => {
    setBusy(true);
    try {
      setResult(await api.runLearningCycle(240));
      load();
    } finally {
      setBusy(false);
    }
  };
  if (!signals) return <LoadingState label="Loading signal lab" />;
  return (
    <>
      <div className="page-header">
        <div><div className="kicker">Signal Lab</div><h1>Filter, compare and audit signal logic.</h1></div>
        <button className="button primary" onClick={runLearning} disabled={busy}>{busy ? "Running learning cycle..." : "Evaluate signals"}</button>
      </div>
      <LearningAuditSummary accuracy={brainAccuracy} result={result} />
      <div className="control-row">
        <select className="input" value={assetType} onChange={(e) => setAssetType(e.target.value)}>
          <option value="">All asset types</option><option value="Stock">Stock</option><option value="ETF">ETF</option>
        </select>
        <select className="input" value={risk} onChange={(e) => setRisk(e.target.value)}>
          <option value="">All risks</option><option>Low</option><option>Medium</option><option>High</option>
        </select>
        <select className="input" value={classification} onChange={(e) => setClassification(e.target.value)}>
          <option value="">All classifications</option>
          {Array.from(new Set(signals.map((s) => s.classification))).map((item) => <option key={item}>{item}</option>)}
        </select>
      </div>
      <SignalTable signals={filtered} />
      <SignalEvaluationTable evaluations={evaluations} />
    </>
  );
}

function LearningAuditSummary({ accuracy, result }: { accuracy: BrainAccuracy | null; result: any }) {
  const calibration = accuracy?.confidence_calibration ?? {};
  return (
    <section className="panel" style={{ marginBottom: 12 }}>
      <div className="panel-head">
        <span>Financial Brain Learning Audit</span>
        <strong>{calibration.status ?? "pending"}</strong>
      </div>
      <div className="brain-status-grid">
        <AuditMetric label="Historical Accuracy" value={ratio(accuracy?.historical_accuracy)} />
        <AuditMetric label="7D Success" value={ratio(accuracy?.success_rate_7d)} />
        <AuditMetric label="30D Success" value={ratio(accuracy?.success_rate_30d)} />
        <AuditMetric label="Calibration" value={calibration.score === undefined || calibration.score === null ? "Pending" : `${Number(calibration.score).toFixed(1)}/100`} />
      </div>
      <div className="brain-two-col">
        <div>
          <h3>Best signal types</h3>
          <AuditList rows={accuracy?.by_signal_type?.slice(0, 5) ?? []} />
        </div>
        <div>
          <h3>Source reliability</h3>
          <div className="brain-performance-list">
            {(accuracy?.source_reliability ?? []).slice(0, 5).map((item) => (
              <div key={item.source}>
                <strong>{item.source}</strong>
                <span>{Number(item.reliability_score ?? 0).toFixed(1)} reliability | {item.article_count ?? 0} articles</span>
              </div>
            ))}
            {!accuracy?.source_reliability?.length && <div className="empty-state compact">Waiting for linked source outcomes.</div>}
          </div>
        </div>
      </div>
      {result && <p>Last learning cycle: {result.status} | mature {result.evaluation?.mature_evaluations ?? 0} | pending {result.evaluation?.inconclusive_evaluations ?? 0} | weights {result.weights?.status ?? "n/a"}</p>}
    </section>
  );
}

function SignalEvaluationTable({ evaluations }: { evaluations: BrainEvaluation[] }) {
  return (
    <section className="panel" style={{ marginTop: 12 }}>
      <div className="panel-head">
        <span>Signal Outcome Memory</span>
        <strong>{evaluations.length} horizons</strong>
      </div>
      <div className="evaluation-table">
        <div className="evaluation-row header">
          <span>Ticker</span>
          <span>Signal</span>
          <span>Horizon</span>
          <span>Pre-signal confidence</span>
          <span>Post result</span>
          <span>Learning impact</span>
          <span>Invalidating conditions</span>
        </div>
        {evaluations.map((row) => (
          <div className="evaluation-row" key={row.id}>
            <strong>{row.ticker}</strong>
            <span>{row.signal_type}</span>
            <span>{row.horizon_days}D</span>
            <span>{row.initial_confidence.toFixed(1)}</span>
            <span className={`outcome ${row.outcome}`}>{row.outcome}</span>
            <span>{learningImpact(row)}</span>
            <span>{invalidatingConditions(row)}</span>
          </div>
        ))}
        {!evaluations.length && <div className="empty-state">No learning evaluations are stored yet. Run the learning cycle after signal snapshots exist.</div>}
      </div>
    </section>
  );
}

function AuditMetric({ label, value }: { label: string; value: number | string }) {
  return <div className="brain-metric"><span>{label}</span><strong>{value}</strong></div>;
}

function AuditList({ rows }: { rows: Array<{ key: string; mature_count: number; success_rate: number | null; accuracy_score: number }> }) {
  if (!rows.length) return <div className="empty-state compact">Waiting for matured signal families.</div>;
  return (
    <div className="brain-performance-list">
      {rows.map((row) => (
        <div key={row.key}>
          <strong>{row.key}</strong>
          <span>{ratio(row.success_rate)} success | {row.mature_count} matured | score {row.accuracy_score.toFixed(1)}</span>
        </div>
      ))}
    </div>
  );
}

function learningImpact(row: BrainEvaluation) {
  if (row.outcome === "correct") return "Supports future confidence in similar setups";
  if (row.outcome === "wrong") return "Reduces future confidence for similar evidence";
  if (row.outcome === "neutral") return "Keeps confidence stable; follow-through was inconclusive";
  return "Pending future price observations";
}

function invalidatingConditions(row: BrainEvaluation) {
  const payload = row.evaluation_payload ?? {};
  if (row.outcome === "wrong") return payload.reason ?? "Price action contradicted the initial thesis.";
  if (row.outcome === "inconclusive") return "Horizon has not matured or future OHLCV is missing.";
  return "Monitor sentiment reversal, volume decay and support/resistance failure.";
}

function ratio(value: number | null | undefined) {
  if (value === null || value === undefined) return "Pending";
  return `${Math.round(Number(value) * 100)}%`;
}
