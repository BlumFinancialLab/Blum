"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Activity, Brain, FlaskConical, History, SearchCheck, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import { BloombergPanel, MetricCard, TerminalHeader } from "@/components/FinancialTerminal";
import { LoadingState } from "@/components/LoadingState";
import { StatusBadge } from "@/components/StatusBadge";

export default function TrainingGroundPage() {
  const [data, setData] = useState<any | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    api.traderTrainingGround()
      .then((payload) => mounted && setData(payload))
      .catch((err) => mounted && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      mounted = false;
    };
  }, []);

  if (error) return <div className="terminal-empty">Training Ground error: {error}</div>;
  if (!data) return <LoadingState label="Loading Training Ground" />;

  const validation = data.current_validation ?? {};
  const evidenceTotal = validation.evidence_total ?? {};
  const evidence24h = validation.evidence_24h ?? {};
  const latestProductiveRun = validation.latest_productive_run ?? null;
  const analyzed = data.trades_being_analyzed ?? {};
  const displayStatus = validation.display_status ?? validation.status ?? "unknown";
  const readableStatus = humanStatus(displayStatus);

  return (
    <>
      <TerminalHeader
        eyebrow="BLUM Training Ground"
        title="Watch the brain train itself."
        subtitle="The Learning Loop should behave like a researcher: hypothesis, validation, contradiction, knowledge update, next experiment."
        statusItems={[
          { label: "Experiment", value: data.current_experiment?.name ?? "pending", tone: "attention" },
          { label: "Training", value: readableStatus, tone: displayStatus.includes("evidence") || displayStatus.includes("running") ? "positive" : "info" },
          { label: "Trades", value: String(analyzed.total_trades ?? 0), tone: analyzed.total_trades ? "positive" : "attention" },
          { label: "Policy", value: "observe only", tone: "info" },
        ]}
      />

      <section className="terminal-command-grid">
        <MetricCard label="Predictions" value={evidenceTotal.predictions_generated ?? validation.predictions_generated ?? 0} subvalue={`${evidence24h.predictions_generated ?? 0} generated in last 24h`} icon={<Brain size={15} />} tone="info" />
        <MetricCard label="Outcomes" value={evidenceTotal.outcomes_evaluated ?? validation.outcomes_evaluated ?? 0} subvalue={`${evidence24h.outcomes_evaluated ?? 0} evaluated in last 24h`} icon={<SearchCheck size={15} />} tone="positive" />
        <MetricCard label="Mistakes" value={evidenceTotal.mistakes_analyzed ?? validation.mistakes_analyzed ?? 0} subvalue={`${evidence24h.mistakes_analyzed ?? 0} classified in last 24h`} icon={<XCircle size={15} />} tone="attention" />
        <MetricCard label="Memory Updates" value={evidenceTotal.memory_updates ?? validation.memory_updates ?? 0} subvalue={`${evidence24h.memory_updates ?? 0} written in last 24h`} icon={<Activity size={15} />} tone="positive" />
      </section>

      <section className="grid-2">
        <BloombergPanel title="Current Experiment" value={readableStatus} subtitle="What BLUM is studying now">
          <div className="brain-list dense">
            <Fact label="Target" value={data.current_experiment?.target ?? "broad coverage"} />
            <Fact label="Hypothesis" value={data.current_hypothesis} />
            <Fact label="Training evidence" value={readableStatus} detail={validation.summary ?? "No training summary available."} />
            <Fact label="Expected learning value" value={formatNumber(data.current_experiment?.expected_learning_value)} />
          </div>
        </BloombergPanel>

        <BloombergPanel title="Trade Evidence Under Review" value={`${analyzed.total_trades ?? 0} trades`} subtitle="One trade should produce maximum knowledge">
          <div className="brain-list dense">
            <Fact label="Open trades" value={analyzed.open_trades ?? 0} />
            <Fact label="Latest trade" value={formatDate(analyzed.latest_trade_at)} />
            <Fact label="Latest productive run" value={latestProductiveRun ? formatDate(latestProductiveRun.started_at) : "not available"} detail={latestProductiveRun ? `predictions ${latestProductiveRun.predictions_generated ?? 0} | outcomes ${latestProductiveRun.outcomes_evaluated ?? 0} | memory ${latestProductiveRun.memory_updates ?? 0}` : undefined} />
            <Fact label="Latest paper outcome" value={data.latest_trade?.outcome_label ?? "not available"} detail={data.latest_trade?.lesson_generated ?? "No recent lesson stored"} />
          </div>
        </BloombergPanel>
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <PatternPanel title="Patterns Discovered" icon={<FlaskConical size={15} />} rows={data.patterns_discovered ?? []} empty="No validated positive pattern stored yet." />
        <PatternPanel title="Patterns Rejected" icon={<XCircle size={15} />} rows={data.patterns_rejected ?? []} empty="No rejected pattern stored yet." />
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <BloombergPanel title="Why The Model Changed" value={`${(data.why_model_changed ?? []).length} actions`} subtitle="Only data-level adjustments, never source-code self-modification">
          <div className="brain-list dense">
            {(data.why_model_changed ?? []).slice(0, 6).map((row: any, index: number) => (
              <Fact key={index} label={row.affected_module ?? row.status ?? "action"} value={row.recommended_action ?? row.detected_problem ?? "n/a"} detail={row.detected_problem} />
            ))}
            {!(data.why_model_changed ?? []).length && <Fact label="No model change" value="No validated improvement action is stored yet." />}
          </div>
        </BloombergPanel>

        <BloombergPanel title="Learning Timeline" value={<History size={16} />} subtitle="Latest autonomous cycles">
          <div className="brain-list dense">
            {(data.learning_timeline ?? []).slice(0, 6).map((row: any) => (
              <Fact key={row.id ?? row.started_at} label={row.status ?? "run"} value={formatDate(row.started_at)} detail={`predictions ${row.predictions_generated ?? 0} | outcomes ${row.outcomes_evaluated ?? 0} | memory ${row.memory_updates ?? 0}`} />
            ))}
            {!(data.learning_timeline ?? []).length && <Fact label="No timeline" value="No LearningRun rows are stored yet." />}
          </div>
        </BloombergPanel>
      </section>
    </>
  );
}

function PatternPanel({ title, rows, empty, icon }: { title: string; rows: any[]; empty: string; icon: ReactNode }) {
  return (
    <BloombergPanel title={title} value={icon} subtitle="Validated learning, not raw logs">
      <div className="brain-list dense">
        {rows.slice(0, 6).map((row, index) => (
          <div key={`${index}-${row.ticker}-${row.lesson_type}`}>
            <StatusBadge label={row.lesson_type ?? "lesson"} />
            <strong>{row.ticker ?? row.setup_type ?? "pattern"} {row.setup_type ? `- ${row.setup_type}` : ""}</strong>
            <p>{row.observation ?? "No observation stored"}</p>
            <span>samples {row.sample_size ?? "n/a"} | confidence {formatNumber(row.confidence)}</span>
          </div>
        ))}
        {!rows.length && <Fact label="Empty" value={empty} />}
      </div>
    </BloombergPanel>
  );
}

function Fact({ label, value, detail }: { label: string; value: any; detail?: any }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value ?? "n/a"}</strong>
      {detail && <p>{detail}</p>}
    </div>
  );
}

function formatNumber(value: any) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(1) : "n/a";
}

function formatDate(value: any) {
  if (!value) return "not available";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return String(value);
  }
}

function humanStatus(value: string) {
  const labels: Record<string, string> = {
    waiting_budget_using_latest_evidence: "Waiting, showing latest evidence",
    training_running: "Training running",
    evidence_available: "Evidence available",
    no_training_data: "No training data",
    budget_wait: "Budget wait",
    skipped: "Skipped",
    completed: "Completed",
    running: "Running"
  };
  return labels[value] ?? value.replaceAll("_", " ");
}
