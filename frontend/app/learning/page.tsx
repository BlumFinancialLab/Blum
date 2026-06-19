"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { AlertTriangle, Brain, Gauge, LineChart } from "lucide-react";
import { api } from "@/lib/api";
import { LoadingState } from "@/components/LoadingState";
import { PlotPanel } from "@/components/PlotPanel";
import { StatusBadge } from "@/components/StatusBadge";

export default function LearningPage() {
  const [dashboard, setDashboard] = useState<any | null>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const [predictions, setPredictions] = useState<any[]>([]);
  const [memory, setMemory] = useState<any | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    async function load() {
      setError("");
      const [dashResult, runsResult, predictionsResult, memoryResult] = await Promise.allSettled([
        api.learningDashboard(),
        api.learningRuns(20),
        api.learningPredictions(36),
        api.learningMemory(32)
      ] as const);
      if (!mounted) return;
      if (dashResult.status === "fulfilled") setDashboard(dashResult.value);
      if (runsResult.status === "fulfilled") setRuns(runsResult.value);
      if (predictionsResult.status === "fulfilled") setPredictions(predictionsResult.value);
      if (memoryResult.status === "fulfilled") setMemory(memoryResult.value);
      const failed = [dashResult, runsResult, predictionsResult, memoryResult].find(isRejected);
      if (failed) setError((failed.reason as Error).message);
    }
    load();
    const timer = window.setInterval(load, 45000);
    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, []);

  const metrics = dashboard?.metrics ?? {};
  const byTimeframe = metrics.by_timeframe ?? {};
  const reliabilityRows = memory?.signal_performance ?? dashboard?.signal_performance ?? [];
  const strategyRows = memory?.strategy_memory ?? dashboard?.strategy_memory ?? [];
  const mistakeRows = memory?.mistakes ?? dashboard?.mistakes ?? [];
  const latestRun = dashboard?.latest_run;

  const accuracyChart = useMemo(() => {
    const labels = ["short", "mid", "long"];
    return [{
      x: labels,
      y: labels.map((key) => percentToNumber(byTimeframe[key]?.accuracy)),
      type: "bar",
      marker: { color: ["#55aaff", "#20e070", "#ffb000"] }
    }];
  }, [byTimeframe]);

  if (error && !dashboard) return <div className="empty-state">API error: {error}</div>;
  if (!dashboard) return <LoadingState label="Loading BLUM Learning Loop" />;

  return (
    <>
      <header className="page-header">
        <div>
          <div className="kicker">BLUM Learning Loop</div>
          <h1>Point-in-time market simulation lab.</h1>
          <p>Autonomous historical sampling, prediction evaluation, mistake classification, signal reliability and strategy memory. Built to improve calibration and robustness, not to manufacture perfect win rates.</p>
        </div>
        <div className="header-actions">
          <StatusBadge label={dashboard.status === "active" ? "Learning active" : "Learning passive"} />
          <StatusBadge label={dashboard.configuration?.evaluation_mode ?? "walk_forward"} />
        </div>
      </header>

      <section className="grid-4">
        <LearningMetric icon={<Brain size={18} />} label="Simulations" value={metrics.simulations ?? 0} subvalue={`${metrics.outcomes ?? 0} evaluated horizons`} />
        <LearningMetric icon={<Gauge size={18} />} label="Short Accuracy" value={formatPct(byTimeframe.short?.accuracy)} subvalue="5-20 trading days" />
        <LearningMetric icon={<LineChart size={18} />} label="Mid Accuracy" value={formatPct(byTimeframe.mid?.accuracy)} subvalue="1-3 months" />
        <LearningMetric icon={<AlertTriangle size={18} />} label="Calibration Error" value={formatNumber(metrics.confidence_calibration?.mean_absolute_error)} subvalue={metrics.confidence_calibration?.status ?? "insufficient sample"} />
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <PlotPanel
          title="Walk-forward Accuracy by Horizon"
          data={accuracyChart as any}
          layout={{ yaxis: { range: [0, 100], title: "Accuracy %" }, xaxis: { title: "Prediction horizon" } }}
        />
        <div className="panel">
          <div className="panel-head">
            <span>Latest autonomous run</span>
            <strong>{latestRun?.status ?? "No run yet"}</strong>
          </div>
          {latestRun ? (
            <div className="brain-list dense">
              <div>
                <StatusBadge label={latestRun.trigger ?? "scheduled"} />
                <strong>{latestRun.run_id}</strong>
                <p>{formatTime(latestRun.started_at)} to {formatTime(latestRun.completed_at)}</p>
              </div>
              <div className="evidence-grid">
                <SmallDatum label="Predictions" value={latestRun.predictions_created} />
                <SmallDatum label="Outcomes" value={latestRun.outcomes_evaluated} />
                <SmallDatum label="Mistakes" value={latestRun.mistakes_found} />
                <SmallDatum label="Memory Updates" value={latestRun.memory_updates} />
              </div>
              <p>{latestRun.anti_overfitting_report?.policy ?? dashboard.policy}</p>
            </div>
          ) : (
            <div className="empty-state">The scheduler is active but no point-in-time learning run has been persisted yet.</div>
          )}
        </div>
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <div className="panel">
          <div className="panel-head"><span>Signal reliability memory</span><strong>{reliabilityRows.length}</strong></div>
          <div className="learning-table">
            <div className="learning-row head"><span>Factor</span><span>TF</span><span>Regime</span><span>Samples</span><span>Reliability</span><span>False +</span></div>
            {reliabilityRows.slice(0, 12).map((row: any) => (
              <div className="learning-row" key={`${row.signal_name}-${row.timeframe}-${row.market_regime}`}>
                <strong>{row.signal_name?.replaceAll("_", " ")}</strong>
                <span>{row.timeframe}</span>
                <span>{row.market_regime}</span>
                <span>{row.sample_count}</span>
                <span className={scoreTone(row.reliability_score)}>{formatNumber(row.reliability_score)}</span>
                <span>{row.false_positive_count}</span>
              </div>
            ))}
            {reliabilityRows.length === 0 && <div className="empty-state">No signal reliability rows yet. The first learning batches will populate this table.</div>}
          </div>
        </div>

        <div className="panel">
          <div className="panel-head"><span>Mistake taxonomy</span><strong>{mistakeRows.length}</strong></div>
          <div className="brain-list dense">
            {mistakeRows.slice(0, 12).map((item: any) => (
              <div key={item.error_type}>
                <div className="opportunity-line">
                  <strong>{String(item.error_type).replaceAll("_", " ")}</strong>
                  <span>{item.count}</span>
                </div>
                <p>Repeated error class used to reduce future overconfidence and improve factor weighting.</p>
              </div>
            ))}
            {mistakeRows.length === 0 && <div className="empty-state">No classified mistakes yet. This is expected before enough simulated outcomes mature.</div>}
          </div>
        </div>
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <div className="panel">
          <div className="panel-head"><span>Strategy memory</span><strong>{strategyRows.length}</strong></div>
          <div className="brain-list">
            {strategyRows.slice(0, 10).map((row: any) => (
              <div key={row.memory_key}>
                <StatusBadge label={row.category} />
                <strong>{row.lesson}</strong>
                <p>Reliability {formatNumber(row.reliability_score)}/100 | samples {row.sample_count} | positive {row.positive_count} | negative {row.negative_count}</p>
              </div>
            ))}
            {strategyRows.length === 0 && <div className="empty-state">No strategy memory has been learned yet.</div>}
          </div>
        </div>
        <div className="panel">
          <div className="panel-head"><span>Recent point-in-time predictions</span><strong>{predictions.length}</strong></div>
          <div className="learning-table predictions">
            <div className="learning-row head"><span>Ticker</span><span>Date</span><span>Regime</span><span>Direction</span><span>Confidence</span><span>Quality</span></div>
            {predictions.slice(0, 14).map((row) => (
              <div className="learning-row" key={row.id}>
                <strong>{row.ticker}</strong>
                <span>{row.analysis_date}</span>
                <span>{row.market_regime}</span>
                <span>{row.expected_direction}</span>
                <span>{formatNumber(row.confidence)}</span>
                <span>{formatNumber(row.data_quality_score)}</span>
              </div>
            ))}
            {predictions.length === 0 && <div className="empty-state">No historical predictions persisted yet.</div>}
          </div>
        </div>
      </section>

      <section className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><span>Governance and anti-overfitting</span><strong>Research only</strong></div>
        <div className="method-grid">
          <SmallDatum label="Asset Universe" value={dashboard.configuration?.asset_universe} />
          <SmallDatum label="Min History" value={`${dashboard.configuration?.min_history_years} years`} />
          <SmallDatum label="Daily Guard" value={dashboard.configuration?.max_daily_runs} />
          <SmallDatum label="Batch Size" value={dashboard.configuration?.batch_size} />
        </div>
        <p>{dashboard.policy}</p>
        <p>Every prediction stores the simulated date, hidden future policy, horizons, confidence, outcomes and mistake analysis. The loop updates parameters and memory only; it does not execute trades and does not self-modify source code.</p>
      </section>
    </>
  );
}

function LearningMetric({ icon, label, value, subvalue }: { icon: ReactNode; label: string; value: string | number; subvalue: string }) {
  return (
    <div className="metric-card">
      <span className="metric-label-icon">{icon}{label}</span>
      <strong>{value}</strong>
      <p>{subvalue}</p>
    </div>
  );
}

function SmallDatum({ label, value }: { label: string; value: any }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value ?? "n/a"}</strong>
    </div>
  );
}

function formatPct(value: any) {
  if (value === null || value === undefined) return "n/a";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function percentToNumber(value: any) {
  return value === null || value === undefined ? 0 : Number(value) * 100;
}

function formatNumber(value: any) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  return Number(value).toFixed(2);
}

function formatTime(value: string | null | undefined) {
  if (!value) return "n/a";
  return new Date(value).toLocaleString();
}

function scoreTone(value: any) {
  const numeric = Number(value);
  if (numeric >= 65) return "positive-text";
  if (numeric <= 42) return "negative-text";
  return "";
}

function isRejected(item: PromiseSettledResult<unknown>): item is PromiseRejectedResult {
  return item.status === "rejected";
}
