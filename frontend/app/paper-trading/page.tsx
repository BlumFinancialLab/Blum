"use client";

import { useEffect, useState } from "react";
import { Copy, ShieldAlert, Target, TrendingUp } from "lucide-react";
import { api } from "@/lib/api";
import { BloombergPanel, ConfidenceMeter, MetricCard, ScoreBadge, TerminalHeader } from "@/components/FinancialTerminal";
import { LoadingState } from "@/components/LoadingState";
import { StatusBadge } from "@/components/StatusBadge";

export default function PaperTradingPage() {
  const [data, setData] = useState<any | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    api.traderPaperTrading(24)
      .then((payload) => mounted && setData(payload))
      .catch((err) => mounted && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      mounted = false;
    };
  }, []);

  if (error) return <div className="terminal-empty">Paper Trading error: {error}</div>;
  if (!data) return <LoadingState label="Loading Paper Trading" />;

  const decisions = data.decisions ?? [];
  const completed = data.completed_decisions ?? [];
  const open = data.open_decisions ?? [];

  return (
    <>
      <TerminalHeader
        eyebrow="BLUM Paper Trading"
        title="Future copy trading starts here, on paper only."
        subtitle="Every scenario must be conditional, risk-defined, auditable and later tied to an outcome and a lesson."
        statusItems={[
          { label: "Mode", value: data.mode ?? "paper_only", tone: "info" },
          { label: "Broker", value: data.no_broker_execution ? "disabled" : "blocked", tone: data.no_broker_execution ? "positive" : "negative" },
          { label: "Readiness", value: data.copy_readiness?.status ?? "pending", tone: "attention" },
          { label: "Decisions", value: String(decisions.length), tone: decisions.length ? "positive" : "attention" },
        ]}
      />

      <section className="terminal-command-grid">
        <MetricCard label="Paper Candidates" value={decisions.length} subvalue="Conditional scenarios only" icon={<Copy size={15} />} tone="info" />
        <MetricCard label="Open Paper Decisions" value={open.length} subvalue="No real capital" icon={<Target size={15} />} tone="attention" />
        <MetricCard label="Completed Outcomes" value={completed.length} subvalue="Used for learning" icon={<TrendingUp size={15} />} tone="positive" />
        <MetricCard label="Guardrail" value="No broker" subvalue="Research and paper simulation only" icon={<ShieldAlert size={15} />} tone="positive" />
      </section>

      <BloombergPanel title="Paper Decisions" value="latest copyable evidence" subtitle="BUY/SELL is a paper scenario label, not an instruction or financial advice.">
        <div className="copy-candidate-grid">
          {decisions.map((row: any, index: number) => (
            <PaperDecisionCard key={`${row.ticker}-${index}`} row={row} />
          ))}
          {!decisions.length && <div className="terminal-empty">No paper-copyable decision is ready. BLUM is waiting for cleaner setup evidence.</div>}
        </div>
      </BloombergPanel>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <BloombergPanel title="Completed Paper Outcomes" value={`${completed.length} latest`} subtitle="Outcome -> lesson -> confidence recalibration">
          <div className="brain-list dense">
            {completed.slice(0, 8).map((row: any) => (
              <div key={row.trade_id}>
                <StatusBadge label={row.outcome ?? "outcome"} />
                <strong>{row.ticker} {row.setup_type}</strong>
                <p>P/L {formatCurrency(row.pnl)} | R {formatNumber(row.r_multiple)} | exit {formatPrice(row.exit)}</p>
                <span>{row.lesson_learned ?? "No lesson stored"}</span>
              </div>
            ))}
            {!completed.length && <Fact label="No completed trades" value="Paper decisions need outcomes before they can improve the brain." />}
          </div>
        </BloombergPanel>

        <BloombergPanel title="Truth Layer" value="paper only" subtitle="Copyability must be earned by evidence">
          <div className="brain-list dense">
            {(data.truth_layer ?? []).slice(0, 6).map((line: string, index: number) => (
              <div key={`${index}-${line}`}>
                <StatusBadge label={index === 0 ? "truth" : "guardrail"} />
                <strong>{line}</strong>
              </div>
            ))}
          </div>
        </BloombergPanel>
      </section>
    </>
  );
}

function PaperDecisionCard({ row }: { row: any }) {
  return (
    <article className="copy-candidate-card">
      <div className="copy-card-head">
        <div>
          <span>{row.side ?? "PAPER"}</span>
          <strong>{row.ticker ?? "n/a"}</strong>
          <p>{row.why ?? "No paper thesis stored"}</p>
        </div>
        <ScoreBadge value={row.decision_quality} label="decision" />
      </div>
      <div className="copy-card-meta">
        <StatusBadge label={String(row.copyability ?? "watch").replaceAll("_", " ")} />
        <StatusBadge label={`confidence ${formatNumber(row.confidence)}`} />
      </div>
      <ConfidenceMeter value={row.confidence} label="Confidence" />
      <div className="copy-plan-grid">
        <Fact label="Entry" value={displayValue(row.entry)} />
        <Fact label="Stop" value={formatPrice(row.stop)} />
        <Fact label="Targets" value={(row.targets ?? []).map(formatPrice).join(" / ") || "n/a"} />
        <Fact label="Holding" value={row.holding_estimate ?? "n/a"} />
        <Fact label="Expected Risk" value={displayValue(row.expected_risk)} />
        <Fact label="Expected Reward" value={displayValue(row.expected_reward)} />
      </div>
      <div className="copy-learning-note">
        <strong>Bull thesis</strong>
        <span>{row.bull_thesis ?? "No bull thesis stored"}</span>
      </div>
      <div className="copy-learning-note">
        <strong>Bear thesis / risk</strong>
        <span>{Array.isArray(row.risk) ? row.risk.join(", ") : row.bear_thesis ?? row.risk ?? "No risk note stored"}</span>
      </div>
      {!!row.missing_data?.length && <div className="copy-warning">Missing: {row.missing_data.join(", ")}</div>}
    </article>
  );
}

function Fact({ label, value }: { label: string; value: any }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value ?? "n/a"}</strong>
    </div>
  );
}

function formatNumber(value: any) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(1) : "n/a";
}

function formatPrice(value: any) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(2) : "n/a";
}

function formatCurrency(value: any) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(2)} EUR` : "n/a";
}

function displayValue(value: any) {
  if (value === null || value === undefined) return "n/a";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
