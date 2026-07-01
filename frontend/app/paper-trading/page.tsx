"use client";

import { useEffect, useMemo, useState } from "react";
import { BookOpen, Clock, Copy, FileSearch, ShieldAlert, Target, TrendingDown, TrendingUp } from "lucide-react";
import { api } from "@/lib/api";
import { BloombergPanel, MetricCard, ScoreBadge, TerminalHeader } from "@/components/FinancialTerminal";
import { LoadingState } from "@/components/LoadingState";
import { StatusBadge } from "@/components/StatusBadge";

const EMPTY_STATES: Record<string, { title: string; body: string; next: string }> = {
  NO_DECISIONS: {
    title: "No paper decisions stored",
    body: "The journal is ready, but BLUM has not stored open or closed paper decisions yet.",
    next: "Wait for the autonomous paper worker to generate decisions, or inspect worker health if this persists.",
  },
  NO_ELIGIBLE_SETUPS: {
    title: "No eligible setups",
    body: "BLUM found candidates, but none passed the copyability, trigger and risk filters.",
    next: "This is a valid no-trade state. The journal will fill when a setup becomes risk-defined.",
  },
  NO_SNAPSHOTS: {
    title: "No PaperTradingSnapshot",
    body: "No durable paper trading snapshot exists yet, so the UI refuses to show fake trades.",
    next: "The backend snapshot producer must create the first paper snapshot.",
  },
  WORKER_FAILED: {
    title: "Paper worker failed",
    body: "The paper trading worker or one of its upstream evidence services reported a failure.",
    next: "Check runtime health before trusting paper trading output.",
  },
  DATA_BLOCKED: {
    title: "Data blocked",
    body: "Required market or trading evidence is unavailable. BLUM cannot build a reliable paper journal.",
    next: "Resolve the data source issue, then let the worker refresh snapshots.",
  },
  INSUFFICIENT_EVIDENCE: {
    title: "Insufficient evidence",
    body: "There is not enough stored evidence to create a paper decision without inventing data.",
    next: "The Learning Loop needs more evaluated setups before copyability can improve.",
  },
};

type Decision = Record<string, any>;

export default function PaperTradingPage() {
  const [data, setData] = useState<any | null>(null);
  const [error, setError] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    api.traderPaperTrading(40)
      .then((payload) => mounted && setData(payload))
      .catch((err) => mounted && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      mounted = false;
    };
  }, []);

  const openDecisions = useMemo(() => dedupeDecisions(data?.open_decisions ?? data?.pending_decisions ?? []), [data]);
  const closedDecisions = useMemo(() => dedupeDecisions(data?.closed_decisions ?? data?.completed_decisions ?? []), [data]);
  const selectedDecision = useMemo(
    () => [...openDecisions, ...closedDecisions].find((row) => decisionId(row) === selectedId) ?? null,
    [closedDecisions, openDecisions, selectedId]
  );

  useEffect(() => {
    if (!selectedId && openDecisions.length) setSelectedId(decisionId(openDecisions[0]));
  }, [openDecisions, selectedId]);

  if (error) {
    return <ReadinessState state="WORKER_FAILED" explanation={`Paper Trading error: ${error}`} />;
  }
  if (!data) return <LoadingState label="Loading PaperTradingSnapshot" />;

  const summary = data.journal_summary ?? {};
  const readinessState = data.readiness_state ?? (openDecisions.length || closedDecisions.length ? "READY" : "NO_DECISIONS");
  const hasJournalEvidence = openDecisions.length > 0 || closedDecisions.length > 0;

  return (
    <>
      <TerminalHeader
        eyebrow="BLUM Paper Trading"
        title="Paper Trading Journal"
        subtitle="One snapshot, no broker execution, every decision tied to risk, outcome and learning evidence."
        statusItems={[
          { label: "Snapshot", value: data.snapshot_type ?? "PaperTradingSnapshot", tone: "info" },
          { label: "Mode", value: data.mode ?? "paper_only", tone: "info" },
          { label: "Readiness", value: readinessState, tone: readinessState === "READY" ? "positive" : "attention" },
          { label: "Broker", value: data.no_broker_execution ? "disabled" : "blocked", tone: data.no_broker_execution ? "positive" : "negative" },
        ]}
      />

      <section className="terminal-command-grid">
        <MetricCard label="Open Decisions" value={openDecisions.length} subvalue="Open trades and pending triggers" icon={<Clock size={15} />} tone={openDecisions.length ? "attention" : "neutral"} />
        <MetricCard label="Closed Decisions" value={closedDecisions.length} subvalue="Evaluated paper outcomes" icon={<BookOpen size={15} />} tone={closedDecisions.length ? "positive" : "neutral"} />
        <MetricCard label="Total P/L" value={formatCurrency(summary.total_pnl)} subvalue="Closed paper decisions" icon={<TrendingUp size={15} />} tone={Number(summary.total_pnl) >= 0 ? "positive" : "negative"} />
        <MetricCard label="Average R" value={formatR(summary.average_r)} subvalue={`${summary.wins ?? 0} wins / ${summary.losses ?? 0} losses`} icon={<Target size={15} />} tone={Number(summary.average_r) >= 0 ? "positive" : "attention"} />
      </section>

      {!hasJournalEvidence && (
        <ReadinessState
          state={readinessState}
          explanation={data.readiness_explanation}
          warnings={data.warnings}
          truth={data.truth_layer}
        />
      )}

      {hasJournalEvidence && (
        <section className="paper-journal-layout">
          <div className="paper-journal-main">
            <JournalSection
              title="Open Decisions"
              subtitle="Active paper trades and candidate triggers. These are not real orders."
              rows={openDecisions}
              emptyState={readinessState}
              selectedId={selectedId}
              onSelect={setSelectedId}
              open
            />
            <JournalSection
              title="Closed Decisions"
              subtitle="Completed outcomes used for learning, calibration and copyability evidence."
              rows={closedDecisions}
              emptyState="NO_DECISIONS"
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          </div>

          <BloombergPanel title="Trade Replay" value={selectedDecision ? selectedDecision.ticker : "select a decision"} subtitle="Lazy-rendered from the same PaperTradingSnapshot. No extra backend call.">
            {selectedDecision ? <TradeReplay row={selectedDecision} /> : <ReplayPlaceholder />}
          </BloombergPanel>
        </section>
      )}

      <section className="grid-2" style={{ marginTop: 12 }}>
        <BloombergPanel title="Truth Layer" value="paper only" subtitle="The journal observes evidence; it does not execute trades.">
          <div className="brain-list dense">
            {(data.truth_layer ?? ["Paper trading is informational only."]).slice(0, 6).map((line: string, index: number) => (
              <div key={`${index}-${line}`}>
                <StatusBadge label={index === 0 ? "truth" : "guardrail"} />
                <strong>{line}</strong>
              </div>
            ))}
          </div>
        </BloombergPanel>
        <BloombergPanel title="Snapshot Policy" value="read-only" subtitle="Frontend visualization never starts training or recalculation.">
          <div className="paper-state-card compact">
            <FileSearch size={18} />
            <div>
              <strong>Loaded from one PaperTradingSnapshot</strong>
              <p>{data.policy ?? "No brokers, no live execution, no financial advice."}</p>
              <span>Generated: {formatDateTime(data.generated_at)}</span>
            </div>
          </div>
        </BloombergPanel>
      </section>
    </>
  );
}

function JournalSection({
  title,
  subtitle,
  rows,
  emptyState,
  selectedId,
  onSelect,
  open = false,
}: {
  title: string;
  subtitle: string;
  rows: Decision[];
  emptyState: string;
  selectedId: string | null;
  onSelect: (id: string) => void;
  open?: boolean;
}) {
  return (
    <BloombergPanel title={title} value={`${rows.length} decisions`} subtitle={subtitle}>
      {rows.length ? (
        <div className="paper-journal-table" role="table" aria-label={title}>
          <div className="paper-journal-row head" role="row">
            <span>Ticker</span>
            <span>Entry / Exit</span>
            <span>Stop / Targets</span>
            <span>Size</span>
            <span>Risk / Reward</span>
            <span>P/L</span>
            <span>R / Alpha</span>
            <span>Quality</span>
          </div>
          {rows.map((row) => {
            const id = decisionId(row);
            return (
              <button className={`paper-journal-row ${selectedId === id ? "active" : ""}`} key={id} onClick={() => onSelect(id)} role="row">
                <span>
                  <strong>{row.ticker ?? "n/a"}</strong>
                  <em>{row.setup_type ?? row.status ?? "paper decision"}</em>
                </span>
                <span>
                  <b>{formatPrice(row.entry)}</b>
                  <em>{open ? formatDate(row.entry_date) || "waiting" : `${formatPrice(row.exit)} ${formatDate(row.exit_date) ? `- ${formatDate(row.exit_date)}` : ""}`}</em>
                </span>
                <span>
                  <b>{formatPrice(row.stop)}</b>
                  <em>{formatTargets(row.targets)}</em>
                </span>
                <span>
                  <b>{formatNumber(row.position_size)}</b>
                  <em>{row.holding_period ?? row.holding_estimate ?? "n/a"}</em>
                </span>
                <span>
                  <b>{formatRisk(row.risk ?? row.expected_risk)}</b>
                  <em>{formatReward(row.reward ?? row.expected_reward)}</em>
                </span>
                <span>
                  <b className={Number(row.pnl) >= 0 ? "positive-text" : "negative-text"}>{formatCurrency(row.pnl)}</b>
                  <em>{formatPercent(row.pnl_percent)}</em>
                </span>
                <span>
                  <b>{formatR(row.r_multiple)}</b>
                  <em>{formatPercent(row.benchmark_excess)}</em>
                </span>
                <span>
                  <ScoreBadge value={row.decision_quality} label="process" />
                  <em>{String(row.copyability ?? "pending").replaceAll("_", " ")}</em>
                </span>
              </button>
            );
          })}
        </div>
      ) : (
        <ReadinessState state={emptyState} compact />
      )}
    </BloombergPanel>
  );
}

function TradeReplay({ row }: { row: Decision }) {
  const replay = row.trade_replay ?? {};
  return (
    <div className="trade-replay-card">
      <div className="trade-replay-head">
        <div>
          <StatusBadge label={String(row.outcome ?? row.status ?? "paper").replaceAll("_", " ")} />
          <h2>{row.ticker ?? "n/a"} {row.side ?? "PAPER"}</h2>
          <p>{row.why ?? replay.entry_decision ?? "No entry thesis stored."}</p>
        </div>
        <ScoreBadge value={row.decision_quality} label="quality" />
      </div>

      <div className="copy-plan-grid">
        <Fact label="Entry" value={formatPrice(row.entry)} />
        <Fact label="Exit" value={formatPrice(row.exit)} />
        <Fact label="Stop" value={formatPrice(row.stop)} />
        <Fact label="Targets" value={formatTargets(row.targets)} />
        <Fact label="Position Size" value={formatNumber(row.position_size)} />
        <Fact label="Holding Period" value={row.holding_period ?? row.holding_estimate ?? "n/a"} />
        <Fact label="P/L" value={formatCurrency(row.pnl)} />
        <Fact label="R Multiple" value={formatR(row.r_multiple)} />
        <Fact label="Benchmark Excess" value={formatPercent(row.benchmark_excess)} />
        <Fact label="Copyability" value={String(row.copyability ?? "pending").replaceAll("_", " ")} />
      </div>

      <ReplayBlock title="Entry decision" value={replay.entry_decision ?? row.why} />
      <ReplayBlock title="Exit decision" value={replay.exit_decision ?? "No exit decision stored yet."} />
      <ReplayBlock title="Bull thesis" value={row.bull_thesis} />
      <ReplayBlock title="Bear thesis / risk" value={row.bear_thesis ?? row.risk_notes} />
      <ReplayBlock title="Lesson learned" value={row.lesson_learned ?? replay.lesson} />
      {!!row.confidence_recalibration && <ReplayBlock title="Confidence recalibration" value={row.confidence_recalibration} />}
    </div>
  );
}

function ReplayPlaceholder() {
  return (
    <div className="paper-state-card">
      <Copy size={18} />
      <div>
        <strong>Select a decision</strong>
        <p>Trade Replay is intentionally lazy-rendered and uses only the loaded snapshot.</p>
      </div>
    </div>
  );
}

function ReadinessState({ state, explanation, warnings, truth, compact = false }: { state: string; explanation?: string; warnings?: string[]; truth?: string[]; compact?: boolean }) {
  const fallback = EMPTY_STATES[state] ?? EMPTY_STATES.NO_DECISIONS;
  const Icon = state === "WORKER_FAILED" || state === "DATA_BLOCKED" ? ShieldAlert : state === "NO_ELIGIBLE_SETUPS" ? TrendingDown : FileSearch;
  return (
    <div className={`paper-state-card ${compact ? "compact" : ""}`}>
      <Icon size={20} />
      <div>
        <span>{state}</span>
        <strong>{fallback.title}</strong>
        <p>{explanation ?? fallback.body}</p>
        <em>{fallback.next}</em>
        {!!warnings?.length && <small>Warnings: {warnings.slice(0, 3).join(", ")}</small>}
        {!!truth?.length && <small>{truth[0]}</small>}
      </div>
    </div>
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

function ReplayBlock({ title, value }: { title: string; value: any }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="copy-learning-note">
      <strong>{title}</strong>
      <span>{displayValue(value)}</span>
    </div>
  );
}

function decisionId(row: Decision) {
  return String(row.decision_id ?? row.trade_id ?? `${row.ticker}-${row.setup_type}-${row.entry ?? "pending"}`);
}

function dedupeDecisions(rows: Decision[]) {
  const seen = new Set<string>();
  return rows.filter((row) => {
    const id = decisionId(row);
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  });
}

function formatNumber(value: any) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(2) : "n/a";
}

function formatPrice(value: any) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(2) : "n/a";
}

function formatCurrency(value: any) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(2)} EUR` : "n/a";
}

function formatPercent(value: any) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(2)}%` : "n/a";
}

function formatR(value: any) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(2)}R` : "n/a";
}

function formatDate(value: any) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleDateString();
}

function formatDateTime(value: any) {
  if (!value) return "n/a";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function formatTargets(targets: any) {
  if (!Array.isArray(targets) || !targets.length) return "n/a";
  return targets.map(formatPrice).join(" / ");
}

function formatRisk(value: any) {
  if (value && typeof value === "object") {
    const parts = [
      value.risk_amount !== undefined ? `${formatCurrency(value.risk_amount)}` : null,
      value.risk_percent !== undefined ? `${formatPercent(value.risk_percent)}` : null,
    ].filter(Boolean);
    return parts.join(" / ") || displayValue(value);
  }
  return displayValue(value);
}

function formatReward(value: any) {
  if (value && typeof value === "object") {
    const parts = [
      value.target_1 !== undefined ? `T1 ${formatPrice(value.target_1)}` : null,
      value.target_2 !== undefined ? `T2 ${formatPrice(value.target_2)}` : null,
    ].filter(Boolean);
    return parts.join(" / ") || displayValue(value);
  }
  return displayValue(value);
}

function displayValue(value: any) {
  if (value === null || value === undefined || value === "") return "n/a";
  if (Array.isArray(value)) return value.filter(Boolean).join(", ") || "n/a";
  if (typeof value === "object") return Object.entries(value).map(([key, item]) => `${key}: ${item}`).join(" | ");
  return String(value);
}
