"use client";

import { useEffect, useState } from "react";
import { Brain, Gauge, ShieldAlert, Target, TrendingUp, Zap } from "lucide-react";
import { api } from "@/lib/api";
import { BloombergPanel, MetricCard, MiniSparkline, ScoreBadge, TerminalHeader } from "@/components/FinancialTerminal";
import { BrainEvidenceCharts } from "@/components/BrainEvidenceCharts";
import { LoadingState } from "@/components/LoadingState";
import { StatusBadge } from "@/components/StatusBadge";

export default function BrainPage() {
  const [data, setData] = useState<any | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    api.traderBrain()
      .then((payload) => mounted && setData(payload))
      .catch((err) => mounted && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      mounted = false;
    };
  }, []);

  if (error) return <div className="terminal-empty">Trader Brain error: {error}</div>;
  if (!data) return <LoadingState label="Loading Trader Brain" />;

  const evidenceTone = evidenceToneFor(data?.readiness?.evidence_grade);
  const chartValues = (data?.brain_progress?.series ?? [])
    .map((row: any) => Number(row.brain_score))
    .filter((value: number) => Number.isFinite(value));

  return (
    <>
      <TerminalHeader
        eyebrow="BLUM Trader Brain"
        title="Is BLUM becoming a better trader?"
        subtitle="One control room for decision quality, alpha readiness, learning velocity and evidence quality. No market noise, no vanity dashboard."
        statusItems={[
          { label: "Version", value: `v${data.version ?? "2.1.0"}`, tone: "info" },
          { label: "Brain", value: data.brain_classification ?? "evaluating", tone: toneForScore(data.brain_score) },
          { label: "Alpha", value: data.readiness?.alpha ?? "pending", tone: data.readiness?.alpha === "READY" ? "positive" : "attention" },
          { label: "Evidence", value: data.readiness?.evidence_grade ?? "unknown", tone: evidenceTone },
        ]}
      />

      <section className="terminal-command-grid">
        <MetricCard label="Brain Score" value={`${formatNumber(data.brain_score)}/100`} subvalue={data.brain_classification} icon={<Brain size={15} />} tone={toneForScore(data.brain_score)} />
        <MetricCard label="Decision Quality" value={`${formatNumber(data.decision_quality)}/100`} subvalue="Process quality, not just outcome" icon={<Target size={15} />} tone={toneForScore(data.decision_quality)} />
        <MetricCard label="Alpha Readiness" value={`${formatNumber(data.alpha_readiness)}/100`} subvalue={data.readiness?.alpha ?? "benchmark evidence pending"} icon={<TrendingUp size={15} />} tone={toneForScore(data.alpha_readiness)} />
        <MetricCard label="Learning Velocity" value={`${formatNumber(data.learning_velocity)}/100`} subvalue="Knowledge gained per cycle" icon={<Zap size={15} />} tone={toneForScore(data.learning_velocity)} />
        <MetricCard label="Evidence Quality" value={`${formatNumber(data.evidence_quality)}/100`} subvalue={data.readiness?.evidence_grade ?? "unknown"} icon={<ShieldAlert size={15} />} tone={evidenceTone} />
        <MetricCard label="Knowledge Quality" value={`${formatNumber(data.knowledge_quality)}/100`} subvalue="Validated lessons, not raw volume" icon={<Gauge size={15} />} tone={toneForScore(data.knowledge_quality)} />
      </section>

      <BrainEvidenceCharts data={data} />

      <section className="grid-2">
        <BloombergPanel title="Brain Status" value={<ScoreBadge value={data.brain_score} label="brain" />} subtitle="The master KPI combines decision quality, evidence, calibration, risk, reproducibility and explainability.">
          <div className="brain-level-layout">
            <div className="brain-level-score">
              <div className="brain-level-ring" style={{ "--score": `${Math.max(0, Math.min(100, safeNumber(data.brain_score))) * 3.6}deg` } as any}>
                <strong>{formatNumber(data.brain_score, 0)}</strong>
                <span>{data.brain_classification}</span>
              </div>
              {chartValues.length > 1 ? (
                <MiniSparkline values={chartValues as number[]} tone={toneForScore(data.brain_score)} />
              ) : (
                <div className="brain-sparkline-empty">Waiting for a second validated Brain snapshot.</div>
              )}
            </div>
            <div className="brain-list dense">
              <LearningFact label="Current learning objective" value={data.current_learning_objective?.target ?? "No focused objective stored yet"} detail={data.current_learning_objective?.reason ?? "Broad autonomous coverage continues."} />
              <LearningFact label="Current phase" value={data.current_learning_phase ?? "unknown"} detail={data.brain_status ?? "No status line available"} />
              <LearningFact label="Last learning cycle" value={data.last_learning_cycle?.status ?? "not started"} detail={formatDate(data.last_learning_cycle?.started_at)} />
            </div>
          </div>
        </BloombergPanel>

        <BloombergPanel title="Truth Panel" value={data.status} subtitle="BLUM must say when evidence is weak. That is part of the brain.">
          <div className="brain-list dense">
            {(data.truth ?? []).slice(0, 6).map((line: string, index: number) => (
              <div key={`${index}-${line}`}>
                <StatusBadge label={index === 0 ? "truth" : "evidence"} />
                <strong>{line}</strong>
              </div>
            ))}
          </div>
        </BloombergPanel>
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <BloombergPanel title="Strength / Weakness" value="learning target" subtitle="The next experiment should attack the weakest decision process, not add another chart.">
          <div className="brain-list dense">
            <LearningFact label="Current strength" value={entityLabel(data.current_strength)} detail={data.current_strength?.recommended_action ?? "No validated strength stored yet"} />
            <LearningFact label="Current weakness" value={entityLabel(data.current_weakness)} detail={data.current_weakness?.main_problem ?? "No validated weakness stored yet"} />
            <LearningFact label="Latest regression" value={data.latest_regression?.factor_name ?? "none stored"} detail={data.latest_regression?.explanation ?? "No active regression flag."} />
          </div>
        </BloombergPanel>

        <BloombergPanel title="Next Planned Experiment" value={data.next_planned_experiment?.priority_type ?? "pending"} subtitle="Autonomous research must decide what to test next.">
          <div className="brain-list dense">
            <LearningFact label="Target" value={data.next_planned_experiment?.target ?? "not selected"} detail={data.next_planned_experiment?.reason ?? "No focused experiment is stored yet."} />
            <LearningFact label="Expected learning value" value={formatNumber(data.next_planned_experiment?.expected_learning_value)} detail={`urgency ${data.next_planned_experiment?.urgency ?? "n/a"} | sample gap ${data.next_planned_experiment?.sample_gap ?? "n/a"}`} />
            <LearningFact label="Latest lesson" value={data.latest_lesson?.lesson_type ?? "not available"} detail={data.latest_lesson?.observation ?? "The Learning Loop has not produced a recent lesson."} />
          </div>
        </BloombergPanel>
      </section>
    </>
  );
}

function LearningFact({ label, value, detail }: { label: string; value: any; detail?: any }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value ?? "n/a"}</strong>
      {detail && <p>{detail}</p>}
    </div>
  );
}

function formatNumber(value: any, digits = 1) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : "n/a";
}

function safeNumber(value: any) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function toneForScore(value: any): "positive" | "attention" | "negative" | "info" {
  const number = safeNumber(value);
  if (number >= 70) return "positive";
  if (number >= 45) return "attention";
  if (number > 0) return "negative";
  return "info";
}

function evidenceToneFor(value: any): "positive" | "attention" | "negative" | "info" {
  const label = String(value ?? "").toLowerCase();
  if (label.includes("strong")) return "positive";
  if (label.includes("medium")) return "attention";
  if (label.includes("low") || label.includes("weak") || label.includes("insufficient")) return "negative";
  return "info";
}

function entityLabel(value: any) {
  if (!value) return "not enough evidence";
  return [value.dimension, value.entity].filter(Boolean).join(" / ");
}

function formatDate(value: any) {
  if (!value) return "not available";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return String(value);
  }
}
