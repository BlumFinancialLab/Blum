"use client";

import { useEffect, useMemo, useState } from "react";
import { Copy, ShieldAlert, Target, Zap } from "lucide-react";
import { api } from "@/lib/api";
import { BloombergPanel, ConfidenceMeter, MetricCard, ScoreBadge, TerminalHeader } from "@/components/FinancialTerminal";
import { LoadingState } from "@/components/LoadingState";
import { StatusBadge } from "@/components/StatusBadge";

export default function CopyTradingPage() {
  const [data, setData] = useState<any | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    api.copyTradingDashboard(25)
      .then((payload) => {
        if (mounted) setData(payload);
      })
      .catch((err) => {
        if (mounted) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const rows = data?.rows ?? [];
  const summary = data?.summary ?? {};
  const grouped = useMemo(() => groupByReadiness(rows), [rows]);

  if (loading && !data) return <LoadingState label="Loading Copy Trading Intelligence" />;
  if (error) return <div className="terminal-empty">Copy Trading Intelligence error: {error}</div>;

  return (
    <>
      <TerminalHeader
        eyebrow="BLUM Copy Trading Intelligence"
        title="Paper mirror desk for conditional setups."
        subtitle="BLUM turns stored Sniper and TradePlan evidence into auditable paper mirror plans. No broker connection, no automatic execution, no financial advice."
        statusItems={[
          { label: "Mode", value: data?.mode ?? "paper_copy_intelligence", tone: "info" },
          { label: "Guardrail", value: data?.paper_only ? "paper only" : "blocked", tone: data?.paper_only ? "positive" : "negative" },
          { label: "Candidates", value: String(summary?.candidate_count ?? rows.length), tone: rows.length ? "positive" : "attention" },
          { label: "Execution", value: data?.no_broker_execution ? "disabled" : "unknown", tone: "attention" },
        ]}
      />

      <section className="terminal-command-grid">
        <MetricCard label="Copy Readiness" value={`${formatNumber(summary?.average_readiness_score)}/100`} subvalue="Evidence-weighted paper readiness" icon={<Copy size={15} />} tone="attention" />
        <MetricCard label="Trigger-ready" value={summary?.actionable_if_triggered ?? 0} subvalue="Still conditional, never direct orders" icon={<Zap size={15} />} tone="positive" />
        <MetricCard label="Wait for Trigger" value={summary?.wait_for_trigger ?? 0} subvalue="Setup not active yet" icon={<Target size={15} />} tone="info" />
        <MetricCard label="Blocked" value={summary?.blocked ?? 0} subvalue="Avoid/reduce/insufficient risk plan" icon={<ShieldAlert size={15} />} tone="negative" />
      </section>

      <section className="grid-2" style={{ marginBottom: 12 }}>
        <BloombergPanel title="Truth Layer" value="research only" subtitle="What BLUM is allowed to say">
          <div className="brain-list dense">
            {(data?.truth_layer ?? ["Insufficient copy trading evidence yet."]).map((line: string, index: number) => (
              <div key={`${index}-${line}`}>
                <StatusBadge label={index === 0 ? "state" : "guardrail"} />
                <strong>{line}</strong>
              </div>
            ))}
          </div>
        </BloombergPanel>

        <BloombergPanel title="Readiness Mix" value={`${rows.length} plans`} subtitle="Copyability is downgraded when risk-plan fields are missing">
          <div className="copy-readiness-bars">
            {Object.entries(grouped).map(([label, count]) => (
              <div key={label}>
                <span>{label.replaceAll("_", " ")}</span>
                <i><b style={{ width: `${rows.length ? Math.max(4, (Number(count) / rows.length) * 100) : 0}%` }} /></i>
                <strong>{String(count)}</strong>
              </div>
            ))}
          </div>
        </BloombergPanel>
      </section>

      <BloombergPanel title="Paper Mirror Candidates" value="latest evidence" subtitle="Each row is a conditional scenario, not an instruction to trade">
        <div className="copy-candidate-grid">
          {rows.map((row: any) => (
            <CopyCandidateCard key={`${row.ticker}-${row.trade_plan_id ?? row.sniper_score_id}`} row={row} />
          ))}
          {!rows.length && <div className="terminal-empty">No stored TradePlan or Sniper candidates are available yet. Background workers must produce evidence first.</div>}
        </div>
      </BloombergPanel>
    </>
  );
}

function CopyCandidateCard({ row }: { row: any }) {
  return (
    <article className="copy-candidate-card">
      <div className="copy-card-head">
        <div>
          <span>{row.asset_type ?? row.source}</span>
          <strong>{row.ticker}</strong>
          <p>{row.asset_name ?? row.sector ?? "Stored BLUM evidence"}</p>
        </div>
        <ScoreBadge value={row.copy_readiness_score} label="copy readiness" />
      </div>
      <div className="copy-card-meta">
        <StatusBadge label={String(row.copy_readiness ?? "watch").replaceAll("_", " ")} />
        <StatusBadge label={String(row.setup_type ?? "setup").replaceAll("_", " ")} />
        <StatusBadge label={String(row.actionability ?? "watch").replaceAll("_", " ")} />
      </div>
      <ConfidenceMeter value={row.confidence} label="Plan confidence" />
      <div className="copy-plan-grid">
        <SmallFact label="Entry trigger" value={row.entry_trigger || "Missing - watch only"} />
        <SmallFact label="Confirmation" value={row.confirmation_condition || "No confirmation stored"} />
        <SmallFact label="Invalidation" value={formatPrice(row.invalidation_level)} />
        <SmallFact label="Target zone" value={[formatPrice(row.target_1), formatPrice(row.target_2)].filter((item) => item !== "n/a").join(" / ") || "n/a"} />
      </div>
      <p className="copy-instruction">{row.paper_instruction}</p>
      <div className="copy-learning-note">
        <strong>Learning evidence</strong>
        <span>{row.learning_evidence?.lesson ?? row.learning_evidence?.status ?? "No recent trade evidence"}</span>
      </div>
      {!!row.missing_data?.length && (
        <div className="copy-warning">Missing: {row.missing_data.join(", ")}</div>
      )}
    </article>
  );
}

function SmallFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function groupByReadiness(rows: any[]) {
  return rows.reduce((acc: Record<string, number>, row) => {
    const key = row.copy_readiness ?? "unknown";
    acc[key] = (acc[key] ?? 0) + 1;
    return acc;
  }, {});
}

function formatNumber(value: any) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  return Number(value).toFixed(1);
}

function formatPrice(value: any) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  return Number(value).toFixed(2);
}
