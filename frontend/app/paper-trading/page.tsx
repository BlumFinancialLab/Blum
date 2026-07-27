"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  Clock,
  Copy,
  FileSearch,
  Lock,
  ShieldAlert,
  Target,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { api } from "@/lib/api";
import { BloombergPanel, MetricCard, ScoreBadge, TerminalHeader } from "@/components/FinancialTerminal";
import { LoadingState } from "@/components/LoadingState";
import { StatusBadge } from "@/components/StatusBadge";
import {
  CANDIDATE_PAPER_STATUSES,
  CLOSED_PAPER_STATUSES,
  filterPaperLifecycle,
  filterPaperMarket,
  mergePaperTrades,
  normalizePaperStatus,
  OPEN_PAPER_STATUSES,
  paperTradeKey,
} from "@/lib/paperTradingView.mjs";

type ReadinessState =
  | "READY"
  | "NO_DECISIONS"
  | "NO_ELIGIBLE_SETUPS"
  | "NO_SNAPSHOTS"
  | "DATA_BLOCKED"
  | "WORKER_DISABLED"
  | "INSUFFICIENT_EVIDENCE"
  | "ERROR";

type PaperForwardTrade = Record<string, any> & {
  trade_id?: string;
  source_trade_id?: number;
  source_engine?: string;
  market_group?: string;
  ticker?: string;
  status?: string;
};

type PaperMarketTab = "equities" | "forex";
type PaperLifecycleTab = "closed" | "open" | "candidates";

const PAPER_MARKET_TABS: Array<{ id: PaperMarketTab; label: string }> = [
  { id: "equities", label: "Azioni / ETF" },
  { id: "forex", label: "Forex" },
];

const PAPER_LIFECYCLE_TABS: Array<{ id: PaperLifecycleTab; label: string }> = [
  { id: "closed", label: "Storico chiusi / P&L" },
  { id: "open", label: "Posizioni aperte" },
  { id: "candidates", label: "Candidati / skipped" },
];

type DetailState = {
  trade: PaperForwardTrade | null;
  events: any[];
  loading: boolean;
  error: string;
};

const CANDIDATE_STATUSES = CANDIDATE_PAPER_STATUSES;
const OPEN_STATUSES = OPEN_PAPER_STATUSES;
const CLOSED_STATUSES = CLOSED_PAPER_STATUSES;

const EMPTY_STATES: Record<ReadinessState, { title: string; body: string; next: string }> = {
  READY: {
    title: "No rows in this section",
    body: "The paper-forward worker is alive, but this section has no matching trades yet.",
    next: "Use the blockers section to see whether BLUM is waiting for triggers, data, or closed outcomes.",
  },
  NO_DECISIONS: {
    title: "No paper decisions stored",
    body: "The journal is ready, but BLUM has not frozen any live-forward paper decisions yet.",
    next: "The autonomous worker must create timestamp-frozen candidates before this page can show trades.",
  },
  NO_ELIGIBLE_SETUPS: {
    title: "No eligible setups",
    body: "BLUM found no setup that passed actionability, trigger and risk filters.",
    next: "This is a valid no-trade state. The journal will populate when a setup becomes risk-defined.",
  },
  NO_SNAPSHOTS: {
    title: "No paper-forward snapshot",
    body: "No durable paper-forward snapshot exists yet, so the UI refuses to show invented decisions.",
    next: "The backend paper-forward worker must write the first snapshot.",
  },
  DATA_BLOCKED: {
    title: "Data blocked",
    body: "Required market or decision evidence is unavailable. BLUM cannot create a reliable paper journal.",
    next: "Resolve the upstream data blocker, then let the worker refresh snapshots.",
  },
  WORKER_DISABLED: {
    title: "Lifecycle disabled",
    body: "Paper-forward is present but the lifecycle worker is disabled or not configured for autonomous progression.",
    next: "Candidate freezing can remain read-only; lifecycle open/close requires backend enablement.",
  },
  INSUFFICIENT_EVIDENCE: {
    title: "Insufficient evidence",
    body: "There is not enough stored evidence to create or evaluate paper decisions without fabricating data.",
    next: "The Learning Loop needs more validated outcomes before copyability can improve.",
  },
  ERROR: {
    title: "Paper worker error",
    body: "The paper-forward API or one of its upstream services returned an error.",
    next: "Check runtime health before trusting paper trading output.",
  },
};

export default function PaperTradingPage() {
  const [snapshotEnvelope, setSnapshotEnvelope] = useState<any | null>(null);
  const [error, setError] = useState("");
  const [slowLoad, setSlowLoad] = useState(false);
  const [marketTab, setMarketTab] = useState<PaperMarketTab>("equities");
  const [lifecycleTab, setLifecycleTab] = useState<PaperLifecycleTab>("closed");
  const [selectedTrade, setSelectedTrade] = useState<PaperForwardTrade | null>(null);
  const [detailState, setDetailState] = useState<DetailState>({ trade: null, events: [], loading: false, error: "" });

  useEffect(() => {
    let mounted = true;
    const slowTimer = window.setTimeout(() => mounted && setSlowLoad(true), 9000);

    withTimeout(api.traderPaperTrading(50), 12000, "unified paper-trading snapshot timeout")
      .then((payload) => {
        if (!mounted) return;
        window.clearTimeout(slowTimer);
        setSnapshotEnvelope(payload);
      })
      .catch((err) => mounted && setError(errorMessage(err)));

    return () => {
      mounted = false;
      window.clearTimeout(slowTimer);
    };
  }, []);

  const snapshot = useMemo(() => normalizeSnapshot(snapshotEnvelope), [snapshotEnvelope]);
  const trades = useMemo(() => mergePaperTrades(snapshot), [snapshot]);
  const visibleTrades = useMemo(
    () => filterPaperMarket(trades, marketTab),
    [trades, marketTab],
  );
  const candidates = useMemo(() => filterTrades(visibleTrades, CANDIDATE_STATUSES), [visibleTrades]);
  const openPositions = useMemo(() => filterTrades(visibleTrades, OPEN_STATUSES), [visibleTrades]);
  const closedTrades = useMemo(() => filterTrades(visibleTrades, CLOSED_STATUSES), [visibleTrades]);
  const readiness = useMemo(() => deriveReadiness(snapshotEnvelope, snapshot, visibleTrades, candidates, openPositions), [snapshotEnvelope, snapshot, visibleTrades, candidates, openPositions]);
  const blockers = useMemo(() => deriveBlockers(readiness, snapshot, candidates, openPositions, visibleTrades), [readiness, snapshot, candidates, openPositions, visibleTrades]);
  const latestLessons = useMemo(() => deriveLessons(snapshot, closedTrades), [snapshot, closedTrades]);
  const lifecycleRows = useMemo(
    () => filterPaperLifecycle(visibleTrades, lifecycleTab),
    [visibleTrades, lifecycleTab],
  );

  const openReplay = (trade: PaperForwardTrade) => {
    const tradeId = trade.source_trade_id;
    const sourceEngine = trade.source_engine;
    setSelectedTrade(trade);
    if (!tradeId || !sourceEngine) {
      setDetailState({ trade, events: [], loading: false, error: "Missing paper-forward trade id." });
      return;
    }
    setDetailState({ trade, events: [], loading: true, error: "" });
    api.unifiedPaperTradingDetail(sourceEngine, tradeId)
      .then((detail) => {
        const events = detail?.events ?? [];
        const detailTrade = detail?.trade ?? trade;
        setDetailState({
          trade: detailTrade,
          events,
          loading: false,
          error: detail?.status === "NOT_FOUND" ? "Trade detail not found." : "",
        });
      })
      .catch((err) => setDetailState({ trade, events: [], loading: false, error: errorMessage(err) }));
  };

  if (error) {
    return <ReadinessStateCard state="ERROR" explanation={`Paper-forward load failed: ${error}`} />;
  }

  if (!snapshotEnvelope) {
    return (
      <>
        <TerminalHeader
          eyebrow="BLUM Paper Trading"
          title="Live-Forward Paper Trading"
          subtitle="Loading the read-only paper-forward journal. No lifecycle or learning job is triggered from this page."
          statusItems={[
            { label: "Mode", value: "paper only", tone: "info" },
            { label: "Requests", value: "1 snapshot", tone: "info" },
          ]}
        />
        <LoadingState label={slowLoad ? "Still waiting for paper-forward snapshot" : "Loading paper-forward snapshot"} />
      </>
    );
  }

  const metrics = snapshot.metrics?.aggregate ?? snapshot.metrics ?? {};
  const counts = snapshot.counts?.aggregate ?? snapshot.counts ?? {};
  const marketMetrics = snapshot.metrics?.by_market ?? {};
  const game = snapshot.game ?? {};
  const statusLabel = snapshot.readiness_status ?? snapshot.readiness ?? readiness;
  const actionability = snapshot.actionability_summary ?? {};
  const topRejection = (actionability.top_rejection_reasons ?? [])[0];

  return (
    <>
      <TerminalHeader
        eyebrow="BLUM Paper Trading"
        title="Live-Forward Paper Trading"
        subtitle="Unified forward paper journal for equities, intraday and Forex. Read-only UI: no broker execution or worker run from page load."
        statusItems={[
          { label: "Readiness", value: String(statusLabel), tone: readinessTone(readiness) },
          { label: "Lifecycle", value: lifecycleLabel(readiness, snapshot), tone: readiness === "WORKER_DISABLED" ? "attention" : "info" },
          { label: "Snapshot", value: formatDateTime(snapshot.snapshot_created_at ?? snapshot.generated_at), tone: snapshot.is_stale ? "attention" : "info" },
          { label: "Broker", value: "disabled", tone: "positive" },
        ]}
      />

      <section className="terminal-command-grid">
        <MetricCard label="Candidates" value={numberLike(maxAvailableCount(counts.candidates, candidates.length, snapshot.candidate_count))} subvalue="Frozen or skipped decisions" icon={<Target size={15} />} tone={candidates.length ? "attention" : "neutral"} />
        <MetricCard label="Open" value={numberLike(snapshot.open_count ?? counts.open ?? openPositions.length)} subvalue="Forward paper positions" icon={<Clock size={15} />} tone={openPositions.length ? "positive" : "neutral"} />
        <MetricCard label="Closed" value={numberLike(maxAvailableCount(counts.closed, closedTrades.length, snapshot.closed_count))} subvalue="Evaluated outcomes" icon={<BookOpen size={15} />} tone={closedTrades.length ? "positive" : "neutral"} />
        <MetricCard label="No trade" value={numberLike(counts.decisions_rejected)} subvalue="Rejected without P/L" icon={<ShieldAlert size={15} />} tone={Number(counts.decisions_rejected) ? "attention" : "info"} />
        <MetricCard label="Realized P/L" value={formatCurrency(snapshot.realized_pnl ?? metrics.realized_pnl)} subvalue={`Unrealized ${formatCurrency(snapshot.unrealized_pnl ?? metrics.unrealized_pnl)}`} icon={<TrendingUp size={15} />} tone={moneyTone(snapshot.realized_pnl ?? metrics.realized_pnl)} />
        <MetricCard label="Win / Avg R" value={`${formatPercent01(snapshot.win_rate ?? metrics.win_rate)} / ${formatR(snapshot.average_r ?? metrics.average_r)}`} subvalue={`Benchmark excess ${formatPercent01(snapshot.benchmark_excess ?? metrics.benchmark_excess)}`} icon={<TrendingDown size={15} />} tone={moneyTone(snapshot.benchmark_excess ?? metrics.benchmark_excess)} />
      </section>

      <section className="terminal-command-grid" style={{ marginTop: 12 }}>
        <MarketEvidenceCard label="Standard" metrics={marketMetrics.standard} counts={snapshot.counts?.by_market?.standard} />
        <MarketEvidenceCard label="Intraday" metrics={marketMetrics.intraday} counts={snapshot.counts?.by_market?.intraday} />
        <MarketEvidenceCard label="Forex" metrics={marketMetrics.forex} counts={snapshot.counts?.by_market?.forex} />
      </section>

      <section className="radar-tabs" style={{ marginTop: 12 }} role="tablist" aria-label="Paper trading market">
        {PAPER_MARKET_TABS.map((tab) => {
          const count = trades.filter((row) => tab.id === "forex" ? row.market_group === "forex" : row.market_group !== "forex").length;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={marketTab === tab.id}
              className={marketTab === tab.id ? "active" : ""}
              onClick={() => setMarketTab(tab.id)}
            >
              {tab.label} <span>{count}</span>
            </button>
          );
        })}
      </section>

      <section className="radar-tabs" style={{ marginTop: 8 }} role="tablist" aria-label="Paper trading history">
        {PAPER_LIFECYCLE_TABS.map((tab) => {
          const count = filterPaperLifecycle(visibleTrades, tab.id).length;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={lifecycleTab === tab.id}
              className={lifecycleTab === tab.id ? "active" : ""}
              onClick={() => setLifecycleTab(tab.id)}
            >
              {tab.label} <span>{count}</span>
            </button>
          );
        })}
      </section>

      <section className="paper-forward-grid">
        <BloombergPanel title="Paper Forward Status" value={readiness} subtitle="A valid no-trade state is better than fabricated activity.">
          <ReadinessStateCard state={readiness} explanation={snapshot.explanation} compact />
          <div className="brain-list dense" style={{ marginTop: 10 }}>
            <div>
              <StatusBadge label="lifecycle" />
              <strong>{lifecycleLabel(readiness, snapshot)}</strong>
              <p>{snapshot.lifecycle_message ?? "Lifecycle state is read from the backend snapshot."}</p>
            </div>
            <div>
              <StatusBadge label="actionability" />
              <strong>{numberLike(actionability.actionable_count)} actionable / {numberLike(actionability.waiting_for_trigger_count)} waiting</strong>
              <p>{numberLike(actionability.skipped_count)} skipped, {numberLike(actionability.data_blocked_count)} data blocked, {numberLike(actionability.error_count)} real errors.</p>
            </div>
            <div>
              <StatusBadge label="main rejection" />
              <strong>{topRejection?.reason ? String(topRejection.reason).replaceAll("_", " ") : "none stored"}</strong>
              <p>{topRejection?.count ? `${topRejection.count} recent candidate(s).` : "No actionability rejection distribution is available yet."}</p>
            </div>
          </div>
        </BloombergPanel>

        <BloombergPanel title="Current Blockers" value={`${blockers.length} active`} subtitle="Why BLUM is not opening or closing more trades.">
          <BlockerList blockers={blockers} />
        </BloombergPanel>
      </section>

      <DecisionSection
        title={lifecycleTab === "closed"
          ? `${marketTab === "forex" ? "Forex" : "Azioni / ETF"} - Storico trade chiusi`
          : lifecycleTab === "open"
            ? "Posizioni aperte"
            : `${marketTab === "forex" ? "Forex" : "Azioni / ETF"} - Candidati / skipped`}
        value={`${lifecycleRows.length} ${lifecycleTab}`}
        subtitle={lifecycleTab === "closed"
          ? "Esiti chiusi con prezzi di entrata/uscita, P/L, R e benchmark. Gli skipped non compaiono in questa vista."
          : lifecycleTab === "open"
            ? "Posizioni paper-forward aperte con P/L non realizzato, stop e target."
            : "Decisioni non ancora aperte o scartate dai filtri di actionability."}
        rows={lifecycleRows.slice(0, 12)}
        emptyState={lifecycleTab === "candidates" ? candidateEmptyState(readiness, trades) : lifecycleRows.length ? "READY" : readiness}
        variant={lifecycleTab === "closed" ? "closed" : lifecycleTab === "open" ? "open" : "candidate"}
        onReplay={openReplay}
      />

      <section className="grid-2" style={{ marginTop: 12 }}>
        <BloombergPanel title={lifecycleTab === "closed" ? "Storico P/L" : "Trade Journal"} value={`${lifecycleRows.length} rows`} subtitle="Il journal segue il filtro selezionato. Il replay resta lazy e viene caricato solo aprendo una riga.">
          {lifecycleRows.length ? <TradeJournal rows={lifecycleRows.slice(0, 50)} onReplay={openReplay} selectedId={selectedTrade?.trade_id} /> : <ReadinessStateCard state={readiness} compact />}
        </BloombergPanel>

        <BloombergPanel title="Trade Detail" value={selectedTrade?.ticker ?? "lazy"} subtitle="Frozen decision, lifecycle and event log load only after opening a trade.">
          <TradeDetailPanel selected={selectedTrade} detailState={detailState} />
        </BloombergPanel>
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <BloombergPanel title="Latest Lessons" value={`${latestLessons.length} lessons`} subtitle="Closed-trade evidence only. Weak or missing evidence is shown as weak.">
          <LessonList lessons={latestLessons} readiness={readiness} />
        </BloombergPanel>

        <BloombergPanel title="Read-Only Policy" value="no POST on load" subtitle="The page observes paper-forward evidence and never starts lifecycle logic.">
          <div className="paper-state-card compact">
            <Lock size={18} />
            <div>
              <span>paper-only guardrail</span>
              <strong>No real-money execution, no broker integration</strong>
              <p>{snapshot.policy ?? "Frontend visualization reads snapshots and trades only. Lifecycle is a backend/manual concern."}</p>
              <em>Initial page load calls only `/api/paper-trading/snapshot`; detail is lazy and source-aware.</em>
            </div>
          </div>
        </BloombergPanel>
      </section>
    </>
  );
}

function DecisionSection({
  title,
  value,
  subtitle,
  rows,
  emptyState,
  variant,
  onReplay,
}: {
  title: string;
  value: string;
  subtitle: string;
  rows: PaperForwardTrade[];
  emptyState: ReadinessState;
  variant: "candidate" | "open" | "closed";
  onReplay: (row: PaperForwardTrade) => void;
}) {
  return (
    <section style={{ marginTop: 12 }}>
      <BloombergPanel title={title} value={value} subtitle={subtitle}>
        {rows.length ? (
          <div className="paper-forward-card-grid">
            {rows.map((row) => <DecisionCard key={tradeKey(row)} row={row} variant={variant} onReplay={onReplay} />)}
          </div>
        ) : (
          <ReadinessStateCard state={emptyState} compact />
        )}
      </BloombergPanel>
    </section>
  );
}

function DecisionCard({ row, variant, onReplay }: { row: PaperForwardTrade; variant: "candidate" | "open" | "closed"; onReplay: (row: PaperForwardTrade) => void }) {
  const status = normalizeStatus(row.status);
  const frozen = row.frozen_decision_payload ?? {};
  const plan = frozen.trade_plan ?? {};
  const confidenceComponents = row.confidence_components ?? {};
  const price = row.current_price ?? row.entry_price;
  return (
    <article className={`paper-forward-card ${statusToneClass(status)}`}>
      <div className="paper-forward-card-head">
        <div>
          <StatusBadge label={status.replaceAll("_", " ")} />
          <StatusBadge label={String(row.market_group ?? "paper").replaceAll("_", " ")} />
          <h3>{row.ticker ?? "UNKNOWN"}</h3>
          <p>{row.setup_type ?? "setup pending"}</p>
        </div>
        <ScoreBadge value={row.confidence ?? row.sniper_score} label={row.confidence !== undefined ? "conf" : "sniper"} />
      </div>

      <div className="copy-plan-grid">
        <Fact label={variant === "open" ? "Open / Latest" : variant === "closed" ? "Open / Close" : "Entry price"} value={variant === "closed" ? `${formatPrice(row.entry_price)} / ${formatPrice(row.exit_price)}` : `${formatPrice(row.entry_price)} / ${formatPrice(price)}`} />
        <Fact label="Stop / Invalidation" value={formatPrice(row.stop_loss ?? row.invalidation_level)} />
        <Fact label="Targets" value={`${formatPrice(row.target_1)} / ${formatPrice(row.target_2)}`} />
        <Fact label="Position size" value={formatNumber(row.position_size)} />
        <Fact label={variant === "closed" ? "P/L" : "Unrealized P/L"} value={formatCurrency(variant === "closed" ? row.net_pnl_eur : row.unrealized_pnl)} />
        <Fact label="R / RR" value={formatR(row.r_multiple ?? row.expected_r_multiple)} />
        <Fact label="Benchmark excess" value={formatPercent(row.excess_return_vs_benchmark)} />
        <Fact label="Model" value={row.model_version_used ?? "base-static"} />
      </div>

      {variant === "candidate" && (
        <div className="paper-forward-explain">
          <strong>{candidateOpeningSentence(row)}</strong>
          <span>Entry trigger: {row.entry_trigger ?? plan.entry_trigger ?? row.confirmation_condition ?? plan.confirmation_condition ?? "not exposed in compact row"}</span>
          <span>For: {displayCompact(reasonForTrade(row))}</span>
          <span>Against: {displayCompact(reasonAgainstTrade(row))}</span>
          {row.market_group === "forex" && (
            <span>
              Setup confidence {formatNumber(confidenceComponents.setup_confidence)} | Data confidence {formatNumber(confidenceComponents.data_confidence)} | Strategy confidence {formatNumber(confidenceComponents.strategy_confidence)}
            </span>
          )}
        </div>
      )}

      {variant === "open" && (
        <div className="paper-forward-explain">
          <strong>Position remains open until stop, target, invalidation, time stop or data blocker resolves it.</strong>
          <span>Opened: {formatDateTime(row.opened_at ?? row.decision_timestamp)}</span>
          <span>MFE / MAE: {formatNumber(row.max_favorable_excursion)} / {formatNumber(row.max_adverse_excursion)}</span>
          <span>Last checked: {formatDateTime(row.updated_at)}</span>
        </div>
      )}

      {variant === "closed" && (
        <div className="paper-forward-explain">
          <strong>Outcome: {outcomeLabel(row)}</strong>
          <span>Close reason: {row.close_reason ?? "not stored"}</span>
          <span>Lesson: {row.lesson_learned ?? "No lesson stored yet."}</span>
        </div>
      )}

      <button className="paper-replay-button" type="button" onClick={() => onReplay(row)}>
        <FileSearch size={14} />
        Open trade replay
      </button>
    </article>
  );
}

function TradeJournal({ rows, onReplay, selectedId }: { rows: PaperForwardTrade[]; onReplay: (row: PaperForwardTrade) => void; selectedId?: string }) {
  return (
    <div className="paper-journal-table" role="table" aria-label="Trade Journal">
      <div className="paper-journal-row head" role="row">
        <span>Ticker</span>
        <span>Status</span>
        <span>Entry / Exit</span>
        <span>Stop / Targets</span>
        <span>Size</span>
        <span>P/L</span>
        <span>R / Alpha</span>
        <span>Model</span>
      </div>
      {rows.map((row) => (
        <button className={`paper-journal-row ${selectedId === row.trade_id ? "active" : ""}`} key={tradeKey(row)} onClick={() => onReplay(row)} role="row">
          <span>
            <strong>{row.ticker ?? "n/a"}</strong>
            <em>{row.market_group ?? "paper"} | {row.setup_type ?? "setup n/a"}</em>
          </span>
          <span>
            <b>{normalizeStatus(row.status).replaceAll("_", " ")}</b>
            <em>{formatDate(row.decision_date ?? row.decision_timestamp)}</em>
          </span>
          <span>
            <b>{formatPrice(row.entry_price)} / {formatPrice(row.exit_price)}</b>
            <em>{row.close_reason ?? row.actionability_state ?? "pending"}</em>
          </span>
          <span>
            <b>{formatPrice(row.stop_loss ?? row.invalidation_level)}</b>
            <em>{formatPrice(row.target_1)} / {formatPrice(row.target_2)}</em>
          </span>
          <span>
            <b>{formatNumber(row.position_size)}</b>
            <em>{formatCurrency(row.risk_amount)}</em>
          </span>
          <span>
            <b className={Number(row.net_pnl_eur ?? row.unrealized_pnl) >= 0 ? "positive-text" : "negative-text"}>{formatCurrency(row.net_pnl_eur ?? row.unrealized_pnl)}</b>
            <em>{formatPercent(row.pnl_percent)}</em>
          </span>
          <span>
            <b>{formatR(row.r_multiple ?? row.expected_r_multiple)}</b>
            <em>{formatPercent(row.excess_return_vs_benchmark)}</em>
          </span>
          <span>
            <b>{row.model_version_used ?? "base-static"}</b>
            <em>open replay</em>
          </span>
        </button>
      ))}
    </div>
  );
}

function TradeDetailPanel({ selected, detailState }: { selected: PaperForwardTrade | null; detailState: DetailState }) {
  if (!selected) {
    return (
      <div className="paper-state-card compact">
        <Copy size={18} />
        <div>
          <span>lazy replay</span>
          <strong>Select a trade</strong>
          <p>Frozen decision payload and lifecycle events are loaded only after you open a trade.</p>
        </div>
      </div>
    );
  }
  if (detailState.loading) return <LoadingState label={`Loading ${selected.ticker ?? "trade"} replay`} />;
  if (detailState.error) return <ReadinessStateCard state="ERROR" explanation={detailState.error} compact />;

  const trade = detailState.trade ?? selected;
  const frozen = trade.frozen_decision_payload ?? {};
  const plan = frozen.trade_plan ?? {};
  const setup = frozen.setup ?? {};
  const priceContext = frozen.price_context ?? {};
  const feedback = frozen.feedback_loop ?? {};
  const events = detailState.events ?? [];

  return (
    <div className="trade-replay-card">
      <div className="trade-replay-head">
        <div>
          <StatusBadge label={normalizeStatus(trade.status).replaceAll("_", " ")} />
          <h2>{trade.ticker ?? "UNKNOWN"} {trade.actionability_state ?? "paper"}</h2>
          <p>{candidateOpeningSentence(trade)}</p>
        </div>
        <ScoreBadge value={trade.confidence ?? trade.sniper_score} label="decision" />
      </div>

      <div className="copy-plan-grid">
        <Fact label="Frozen timestamp" value={formatDateTime(frozen.decision_timestamp ?? trade.decision_timestamp)} />
        <Fact label="Model version" value={trade.model_version_used ?? feedback.model_version_used ?? "base-static"} />
        <Fact label="Confidence adjustment" value={formatNumber(trade.confidence_adjustment ?? feedback.confidence_adjustment)} />
        <Fact label="Entry logic" value={trade.entry_trigger ?? plan.entry_trigger ?? trade.confirmation_condition ?? plan.confirmation_condition ?? "not stored"} />
        <Fact label="Stop logic" value={formatPrice(trade.stop_loss ?? trade.invalidation_level ?? plan.stop_price ?? plan.invalidation_level)} />
        <Fact label="Target logic" value={`${formatPrice(trade.target_1 ?? plan.target_1)} / ${formatPrice(trade.target_2 ?? plan.target_2)}`} />
        <Fact label="Technical context" value={displayCompact(priceContext)} />
        <Fact label="Market regime" value={frozen.market_regime ?? "not stored"} />
      </div>

      <ReplayBlock title="Original thesis / setup" value={setup.thesis ?? setup.description ?? setup.setup_type ?? trade.setup_type} />
      <ReplayBlock title="Why trade" value={reasonForTrade(trade)} />
      <ReplayBlock title="Why not / risk" value={reasonAgainstTrade(trade)} />
      <ReplayBlock title="Weights used" value={trade.weights_used ?? feedback.weights_used} />
      <ReplayBlock title="Learning memory used" value={trade.learning_memory_used ?? feedback.learning_memory_used} />
      <ReplayBlock title="Strategy memory used" value={trade.strategy_memory_used ?? feedback.strategy_memory_used} />
      <ReplayBlock title="Research priority used" value={trade.research_priority_used ?? feedback.research_priority_used} />
      <ReplayBlock title="Lesson" value={trade.lesson_learned} />

      <div className="paper-event-log">
        <strong>Lifecycle event log</strong>
        {events.length ? (
          events.map((event) => (
            <div key={event.id ?? `${event.event_type}-${event.timestamp}`}>
              <StatusBadge label={String(event.event_type ?? "event").replaceAll("_", " ")} />
              <span>{formatDateTime(event.timestamp)}</span>
              <p>{event.reason ?? "No event reason stored."}</p>
            </div>
          ))
        ) : (
          <p>No lifecycle events are stored for this trade yet.</p>
        )}
      </div>

      <details className="developer-payload">
        <summary>Developer payload</summary>
        <pre>{JSON.stringify({ trade, events }, null, 2)}</pre>
      </details>
    </div>
  );
}

function LessonList({ lessons, readiness }: { lessons: any[]; readiness: ReadinessState }) {
  if (!lessons.length) {
    return <ReadinessStateCard state={readiness === "READY" ? "NO_DECISIONS" : readiness} compact explanation="No closed paper-forward lesson is available yet." />;
  }
  return (
    <div className="brain-list dense">
      {lessons.slice(0, 6).map((lesson, index) => (
        <div key={lesson.id ?? `${lesson.ticker}-${index}`}>
          <StatusBadge label={lesson.outcome ?? lesson.lesson_type ?? "lesson"} />
          <strong>{lesson.ticker ?? "Portfolio"} {lesson.setup_type ?? ""}</strong>
          <p>{lesson.observation ?? lesson.lesson_learned ?? "No lesson text stored."}</p>
          <span>Confidence {formatNumber(lesson.confidence)} | R {formatR(lesson.r_multiple)} | Benchmark {formatPercent(lesson.benchmark_excess)}</span>
        </div>
      ))}
    </div>
  );
}

function BlockerList({ blockers }: { blockers: string[] }) {
  if (!blockers.length) {
    return (
      <div className="paper-state-card compact">
        <CheckCircle2 size={18} />
        <div>
          <span>no active blocker</span>
          <strong>Paper-forward journal is ready</strong>
          <p>BLUM can show candidates, opens and closes as soon as the backend worker stores them.</p>
        </div>
      </div>
    );
  }
  return (
    <div className="paper-blocker-list">
      {blockers.map((blocker) => (
        <div key={blocker}>
          <AlertTriangle size={15} />
          <strong>{String(blocker).replaceAll("_", " ")}</strong>
        </div>
      ))}
    </div>
  );
}

function ReadinessStateCard({ state, explanation, compact = false }: { state: ReadinessState; explanation?: string; compact?: boolean }) {
  const fallback = EMPTY_STATES[state] ?? EMPTY_STATES.NO_DECISIONS;
  const Icon = state === "ERROR" || state === "WORKER_DISABLED" || state === "DATA_BLOCKED" ? ShieldAlert : state === "NO_ELIGIBLE_SETUPS" ? TrendingDown : FileSearch;
  return (
    <div className={`paper-state-card ${compact ? "compact" : ""}`}>
      <Icon size={20} />
      <div>
        <span>{state}</span>
        <strong>{fallback.title}</strong>
        <p>{explanation ?? fallback.body}</p>
        <em>{fallback.next}</em>
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
  const display = displayCompact(value);
  if (display === "n/a") return null;
  return (
    <div className="copy-learning-note">
      <strong>{title}</strong>
      <span>{display}</span>
    </div>
  );
}

function normalizeSnapshot(envelope: any): any {
  if (!envelope) return null;
  return envelope.payload ?? envelope;
}

function filterTrades(rows: PaperForwardTrade[], statuses: Set<string>) {
  return rows.filter((row) => statuses.has(normalizePaperStatus(row.status)));
}

function MarketEvidenceCard({ label, metrics, counts }: { label: string; metrics?: any; counts?: any }) {
  return (
    <MetricCard
      label={`${label} evidence`}
      value={`${numberLike(counts?.open)} open / ${numberLike(counts?.closed)} closed`}
      subvalue={`P/L ${formatCurrency(metrics?.realized_pnl)} | Avg R ${formatR(metrics?.average_r)}`}
      icon={<BookOpen size={15} />}
      tone={moneyTone(metrics?.realized_pnl)}
    />
  );
}

function deriveReadiness(envelope: any, snapshot: any, rows: PaperForwardTrade[], candidates: PaperForwardTrade[], openRows: PaperForwardTrade[]): ReadinessState {
  if (!snapshot || envelope?.status === "missing") return "NO_SNAPSHOTS";
  const raw = String(snapshot.readiness_status ?? snapshot.readiness ?? snapshot.status ?? envelope?.status ?? "").toUpperCase();
  if (raw.includes("DISABLED")) return "WORKER_DISABLED";
  if (raw.includes("ERROR") || rows.some((row) => normalizeStatus(row.status) === "ERROR")) return "ERROR";
  if (raw.includes("DATA_BLOCKED") || rows.some((row) => normalizeStatus(row.status) === "DATA_BLOCKED")) return "DATA_BLOCKED";
  if (!rows.length) return "NO_DECISIONS";
  if (!openRows.length && candidates.length && candidates.every((row) => normalizeStatus(row.status) === "SKIPPED")) return "NO_ELIGIBLE_SETUPS";
  if (raw.includes("INSUFFICIENT")) return "INSUFFICIENT_EVIDENCE";
  return "READY";
}

function deriveBlockers(readiness: ReadinessState, snapshot: any, candidates: PaperForwardTrade[], openRows: PaperForwardTrade[], rows: PaperForwardTrade[]) {
  const blockers = new Set<string>(snapshot?.current_blockers ?? snapshot?.blockers ?? []);
  if (readiness !== "READY") blockers.add(readiness.toLowerCase());
  if (!rows.length) blockers.add("no_live_forward_paper_decisions");
  if (!candidates.length) blockers.add("no_candidate_decisions");
  if (!openRows.length) blockers.add("no_open_paper_forward_positions");
  if (candidates.some((row) => normalizeStatus(row.status) === "SKIPPED")) blockers.add("some_candidates_failed_actionability_filters");
  if (candidates.some((row) => normalizeStatus(row.status) === "DATA_BLOCKED")) blockers.add("some_candidates_blocked_by_missing_market_data");
  return Array.from(blockers).filter(Boolean).slice(0, 10);
}

function deriveLessons(snapshot: any, closedRows: PaperForwardTrade[]) {
  const lessons = [];
  if (snapshot?.latest_lesson ?? snapshot?.last_lesson) lessons.push(snapshot.latest_lesson ?? snapshot.last_lesson);
  for (const row of closedRows) {
    if (row.lesson_learned) {
      lessons.push({
        ticker: row.ticker,
        setup_type: row.setup_type,
        lesson_type: "paper_forward_outcome",
        outcome: outcomeLabel(row),
        observation: row.lesson_learned,
        confidence: row.confidence,
        r_multiple: row.r_multiple,
        benchmark_excess: row.excess_return_vs_benchmark,
      });
    }
  }
  const seen = new Set<string>();
  return lessons.filter((lesson) => {
    const key = `${lesson.ticker ?? ""}-${lesson.observation ?? lesson.id ?? ""}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function candidateEmptyState(readiness: ReadinessState, rows: PaperForwardTrade[]): ReadinessState {
  if (readiness !== "READY") return readiness;
  if (!rows.length) return "NO_DECISIONS";
  return "NO_ELIGIBLE_SETUPS";
}

function candidateOpeningSentence(row: PaperForwardTrade) {
  const status = normalizeStatus(row.status);
  if (status === "OPEN") return "BLUM opened this paper trade because the frozen entry condition was met on later data.";
  if (status === "CLOSED") return "BLUM closed this paper trade and stored the outcome for learning.";
  if (status === "DATA_BLOCKED") return "BLUM has not opened this trade because required market data is blocked.";
  if (status === "SKIPPED") return "BLUM has not opened this trade because the setup did not pass actionability filters.";
  if (status === "ERROR") return "BLUM has not opened this trade because the candidate produced an error state.";
  return "BLUM has not opened this trade yet because the entry condition has not been confirmed.";
}

function reasonForTrade(row: PaperForwardTrade) {
  const frozen = row.frozen_decision_payload ?? {};
  const setup = frozen.setup ?? {};
  return setup.why_now ?? setup.reason ?? setup.description ?? row.actionability_state ?? "No positive thesis stored in compact row; open replay for full frozen context.";
}

function reasonAgainstTrade(row: PaperForwardTrade) {
  const status = normalizeStatus(row.status);
  const frozen = row.frozen_decision_payload ?? {};
  const plan = frozen.trade_plan ?? {};
  if (status === "SKIPPED") return row.blockers?.length ? row.blockers : "Candidate failed BLUM actionability or risk filters.";
  if (status === "DATA_BLOCKED") return "Market data required for the paper-forward decision is missing.";
  if (status === "ERROR") return "Worker stored an error state for this candidate.";
  return plan.no_trade_conditions ?? plan.risk_notes ?? "No explicit contradiction stored in compact row; open replay for full frozen context.";
}

function outcomeLabel(row: PaperForwardTrade) {
  const status = normalizeStatus(row.status);
  const label = String(row.outcome_label ?? "").toUpperCase();
  if (label) return label;
  if (status === "DATA_BLOCKED") return "DATA_INVALID";
  const pnl = Number(row.net_pnl_eur);
  if (!Number.isFinite(pnl)) return status === "CLOSED" ? "INCONCLUSIVE" : status;
  if (Math.abs(pnl) < 0.0001) return "BREAKEVEN";
  return pnl > 0 ? "WIN" : "LOSS";
}

function normalizeStatus(value: any) {
  return normalizePaperStatus(value);
}

function tradeKey(row: PaperForwardTrade) {
  return paperTradeKey(row);
}

function readinessTone(value: ReadinessState): "positive" | "attention" | "negative" | "info" {
  if (value === "READY") return "positive";
  if (value === "ERROR" || value === "DATA_BLOCKED" || value === "WORKER_DISABLED") return "negative";
  if (value === "NO_DECISIONS" || value === "NO_ELIGIBLE_SETUPS") return "attention";
  return "info";
}

function lifecycleLabel(readiness: ReadinessState, snapshot: any) {
  if (snapshot?.paper_forward_lifecycle_mode) return String(snapshot.paper_forward_lifecycle_mode).replaceAll("_", " ").toLowerCase();
  if (readiness === "WORKER_DISABLED") return "disabled";
  if (snapshot?.status === "ready" || snapshot?.readiness === "READY") return "observing";
  return "read-only";
}

function statusToneClass(status: string) {
  if (status === "OPEN" || status === "CLOSED") return "tone-positive";
  if (status === "DATA_BLOCKED" || status === "ERROR") return "tone-negative";
  if (status === "SKIPPED") return "tone-attention";
  return "tone-info";
}

function moneyTone(value: any): "positive" | "attention" | "negative" | "info" {
  const number = Number(value);
  if (!Number.isFinite(number)) return "info";
  if (number > 0) return "positive";
  if (number < 0) return "negative";
  return "attention";
}

function numberLike(value: any) {
  const number = Number(value);
  return Number.isFinite(number) ? String(number) : "0";
}

function maxAvailableCount(...values: any[]) {
  const counts = values.map(Number).filter((value) => Number.isFinite(value) && value >= 0);
  return counts.length ? Math.max(...counts) : 0;
}

function formatNumber(value: any, digits = 2) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : "n/a";
}

function formatPrice(value: any) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "n/a";
  return number > 0 && Math.abs(number) < 10 ? number.toFixed(5) : number.toFixed(2);
}

function formatCurrency(value: any) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(2)} EUR` : "n/a";
}

function formatPercent(value: any) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(2)}%` : "n/a";
}

function formatPercent01(value: any) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "n/a";
  return `${(Math.abs(number) <= 1 ? number * 100 : number).toFixed(2)}%`;
}

function formatR(value: any) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(2)}R` : "n/a";
}

function formatDate(value: any) {
  if (!value) return "n/a";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleDateString();
}

function formatDateTime(value: any) {
  if (!value) return "n/a";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function displayCompact(value: any): string {
  if (value === null || value === undefined || value === "") return "n/a";
  if (Array.isArray(value)) return value.length ? value.map(displayCompact).join(", ") : "n/a";
  if (typeof value === "object") {
    const entries = Object.entries(value)
      .filter(([, item]) => item !== null && item !== undefined && item !== "")
      .slice(0, 8)
      .map(([key, item]) => `${key}: ${typeof item === "object" ? JSON.stringify(item) : String(item)}`);
    return entries.length ? entries.join(" | ") : "n/a";
  }
  return String(value);
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

function withTimeout<T>(promise: Promise<T>, ms: number, message: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error(message)), ms);
    promise.then(resolve).catch(reject).finally(() => window.clearTimeout(timer));
  });
}
