"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { AlertTriangle, Brain, Gauge, LineChart } from "lucide-react";
import { api } from "@/lib/api";
import { AsyncPanel } from "@/components/AsyncPanel";
import { PlotPanel } from "@/components/PlotPanel";
import { StatusBadge } from "@/components/StatusBadge";

type LearningTab = "overview" | "trading" | "diagnostics";
type PanelState = { loading: boolean; error: string; data: any | null };

export default function LearningPage() {
  const [activeTab, setActiveTab] = useState<LearningTab>("overview");
  const [summary, setSummary] = useState<any | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [summaryError, setSummaryError] = useState("");
  const [trading, setTrading] = useState<any | null>(null);
  const [tradingLoading, setTradingLoading] = useState(false);
  const [tradingError, setTradingError] = useState("");
  const [diagnostics, setDiagnostics] = useState<Record<string, PanelState>>({});

  async function loadSummary() {
    setSummaryLoading(true);
    setSummaryError("");
    try {
      setSummary(await api.learningSummary());
    } catch (error) {
      setSummaryError(error instanceof Error ? error.message : String(error));
    } finally {
      setSummaryLoading(false);
    }
  }

  useEffect(() => {
    let mounted = true;
    setSummaryLoading(true);
    api.learningSummary()
      .then((payload) => {
        if (mounted) setSummary(payload);
      })
      .catch((error) => {
        if (mounted) setSummaryError(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        if (mounted) setSummaryLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (activeTab !== "trading" || trading || tradingLoading) return undefined;
    let mounted = true;

    async function loadTradingGame() {
      setTradingLoading(true);
      setTradingError("");
      const [equityResult, ledgerResult, ledgerSummaryResult, realityCheckResult, benchmarkResult] = await Promise.allSettled([
        api.tradingGameAnnotatedEquity(240),
        api.tradingGameLedger(25),
        api.tradingGameLedgerSummary(),
        api.tradingGameRealityCheck(),
        api.tradingGameBenchmark(),
      ] as const);
      if (!mounted) return;
      setTrading({
        equity: equityResult.status === "fulfilled" ? equityResult.value : null,
        ledger: ledgerResult.status === "fulfilled" ? ledgerResult.value : null,
        ledgerSummary: ledgerSummaryResult.status === "fulfilled" ? ledgerSummaryResult.value : null,
        realityCheck: realityCheckResult.status === "fulfilled" ? realityCheckResult.value : null,
        benchmark: benchmarkResult.status === "fulfilled" ? benchmarkResult.value : null,
      });
      const rejected = [equityResult, ledgerResult, ledgerSummaryResult, realityCheckResult, benchmarkResult].find(isRejected);
      if (rejected) setTradingError((rejected.reason as Error).message);
      setTradingLoading(false);
    }

    loadTradingGame();
    return () => {
      mounted = false;
    };
  }, [activeTab, trading, tradingLoading]);

  async function loadMoreLedger() {
    setTradingLoading(true);
    try {
      const ledger = await api.tradingGameLedger(100);
      setTrading((previous: any) => ({ ...(previous ?? {}), ledger }));
    } catch (error) {
      setTradingError(error instanceof Error ? error.message : String(error));
    } finally {
      setTradingLoading(false);
    }
  }

  async function loadDiagnosticPanel(panelId: string, loader: () => Promise<any>) {
    setDiagnostics((previous) => ({ ...previous, [panelId]: { loading: true, error: "", data: previous[panelId]?.data ?? null } }));
    try {
      const data = await loader();
      setDiagnostics((previous) => ({ ...previous, [panelId]: { loading: false, error: "", data } }));
    } catch (error) {
      setDiagnostics((previous) => ({
        ...previous,
        [panelId]: { loading: false, error: error instanceof Error ? error.message : String(error), data: previous[panelId]?.data ?? null },
      }));
    }
  }

  const equityChart = useMemo(() => {
    const points = trading?.equity?.equity_curve_points ?? trading?.equity ?? [];
    if (!Array.isArray(points)) return [];
    return [
      {
        x: points.map((row: any) => row.timestamp || row.equity_date || row.created_at),
        y: points.map((row: any) => row.equity),
        type: "scatter",
        mode: "lines",
        name: "BLUM",
        line: { color: "#ffb000", width: 3 },
      },
      {
        x: points.map((row: any) => row.timestamp || row.equity_date || row.created_at),
        y: points.map((row: any) => row.benchmark_equity),
        type: "scatter",
        mode: "lines",
        name: "Benchmark",
        line: { color: "#55aaff", width: 2 },
      },
    ];
  }, [trading]);

  const cycle = summary?.current_capital_cycle ?? {};
  const ledgerRows = trading?.ledger?.rows ?? [];
  const ledgerSummary = trading?.ledgerSummary?.summary ?? trading?.ledger?.summary ?? {};
  const realityCheck = trading?.realityCheck ?? {};
  const benchmark = trading?.benchmark ?? summary?.benchmark_summary ?? {};
  const truthPanel = summary?.truth_panel ?? [];

  return (
    <>
      <header className="page-header">
        <div>
          <div className="kicker">BLUM Learning Control Room</div>
          <h1>Fast truth, background learning.</h1>
          <p>The Learning Loop continues independently in the backend. This page observes lightweight snapshots first and loads trading evidence or diagnostics only when requested.</p>
        </div>
        <div className="header-actions">
          <StatusBadge label={summary?.backend_training_status?.mode ?? "snapshot observer"} />
          <StatusBadge label={summary?.is_recalculation_running ? "background recalculation running" : "read-only frontend"} />
          {summaryLoading && <StatusBadge label="summary loading" />}
        </div>
      </header>

      <nav className="tab-row" style={{ marginBottom: 12 }}>
        {[
          ["overview", "Overview"],
          ["trading", "Trading Game"],
          ["diagnostics", "Deep Diagnostics"],
        ].map(([id, label]) => (
          <button key={id} className={`button compact ${activeTab === id ? "primary" : ""}`} onClick={() => setActiveTab(id as LearningTab)}>
            {label}
          </button>
        ))}
      </nav>

      {activeTab === "overview" && (
        <OverviewTab
          summary={summary}
          loading={summaryLoading}
          error={summaryError}
          truthPanel={truthPanel}
          onRefresh={loadSummary}
        />
      )}

      {activeTab === "trading" && (
        <TradingGameTab
          summary={summary}
          cycle={cycle}
          loading={tradingLoading}
          error={tradingError}
          equityChart={equityChart as any}
          ledgerRows={ledgerRows}
          ledgerSummary={ledgerSummary}
          realityCheck={realityCheck}
          benchmark={benchmark}
          onRetry={() => setTrading(null)}
          onLoadMore={loadMoreLedger}
        />
      )}

      {activeTab === "diagnostics" && (
        <DeepDiagnosticsTab
          diagnostics={diagnostics}
          loadPanel={loadDiagnosticPanel}
        />
      )}
    </>
  );
}

function OverviewTab({ summary, loading, error, truthPanel, onRefresh }: { summary: any; loading: boolean; error: string; truthPanel: string[]; onRefresh: () => void }) {
  const topWeakness = summary?.top_weakness;
  const latestLesson = summary?.latest_lesson_learned;
  const warnings = summary?.warnings ?? [];

  return (
    <>
      <AsyncPanel
        title="Overview Snapshot"
        loading={loading}
        error={error}
        stale={hasStaleSnapshots(summary)}
        updatedAt={summary?.last_snapshot_timestamp ?? summary?.generated_at}
        onRetry={onRefresh}
        fallback="Loading one lightweight summary endpoint"
      >
        <div className="grid-4">
          <LearningMetric icon={<Brain size={18} />} label="Learning Status" value={summary?.learning_loop_status ?? "not started"} subvalue={`Latest run: ${formatTime(summary?.latest_learning_run_at)}`} />
          <LearningMetric icon={<Gauge size={18} />} label="Trading Power" value={summary?.trading_power_score == null ? "n/a" : `${formatNumber(summary.trading_power_score)}/100`} subvalue={summary?.trading_power_classification ?? "initializing"} />
          <LearningMetric icon={<LineChart size={18} />} label="Game Capital" value={formatCurrency(summary?.current_capital)} subvalue={`Target progress: ${formatPct(summary?.target_progress)}`} />
          <LearningMetric icon={<AlertTriangle size={18} />} label="Backend Training" value={summary?.backend_training_status?.status ?? "unknown"} subvalue={summary?.backend_training_status?.frontend_policy ?? "read only"} />
        </div>
      </AsyncPanel>

      {summary?.is_recalculation_running && (
        <div className="empty-state" style={{ marginTop: 12 }}>
          Recalculation running in background. Showing last snapshot from {formatTime(summary?.last_snapshot_timestamp)}.
        </div>
      )}

      {warnings.length > 0 && (
        <div className="empty-state" style={{ marginTop: 12 }}>
          {warnings.slice(0, 3).join(" ")}
        </div>
      )}

      <section className="grid-3" style={{ marginTop: 12 }}>
        <div className="panel">
          <div className="panel-head"><span>Win Rate / Expectancy</span><strong>snapshot</strong></div>
          <div className="evidence-grid">
            <SmallDatum label="Win Rate" value={formatPct(summary?.win_rate)} />
            <SmallDatum label="Expectancy R" value={formatR(summary?.expectancy_r)} />
            <SmallDatum label="Completed Cycles" value={summary?.completed_target_cycles ?? 0} />
            <SmallDatum label="Bankrupt Cycles" value={summary?.bankrupt_cycles ?? 0} />
          </div>
        </div>

        <div className="panel">
          <div className="panel-head"><span>Benchmark Result</span><strong>{summary?.benchmark_summary?.status ?? "initializing"}</strong></div>
          <div className="learning-table compact">
            <div className="learning-row head"><span>Benchmark</span><span>Result</span><span>Excess</span></div>
            {Object.entries(summary?.benchmark_summary?.major_benchmarks ?? {}).map(([name, payload]: any) => (
              <div className="learning-row" key={name}>
                <strong>{name}</strong>
                <span className={benchmarkTone(payload.result_label)}>{String(payload.result_label).replaceAll("_", " ")}</span>
                <span>{formatPctRaw(payload.excess_return)}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="panel">
          <div className="panel-head"><span>Live Evidence</span><strong>{summary?.live_vs_historical_status ?? "missing"}</strong></div>
          <div className="evidence-grid">
            <SmallDatum label="Last Snapshot" value={formatTime(summary?.last_snapshot_timestamp)} />
            <SmallDatum label="Summary Runtime" value={`${formatNumber(summary?.summary_duration_ms)} ms`} />
            <SmallDatum label="Missing Sections" value={(summary?.missing_sections ?? []).length} />
            <SmallDatum label="Source" value={summary?.performance?.source ?? "snapshot"} />
          </div>
        </div>
      </section>

      <section className="grid-3" style={{ marginTop: 12 }}>
        <div className="panel">
          <div className="panel-head"><span>Top Weakness</span><strong>{topWeakness?.priority ?? "n/a"}</strong></div>
          {topWeakness ? (
            <div className="brain-list dense">
              <div>
                <StatusBadge label={`${topWeakness.dimension}: ${topWeakness.entity}`} />
                <strong>{topWeakness.main_problem}</strong>
                <p>{topWeakness.recommended_action}</p>
                <p>Weakness {formatNumber(topWeakness.weakness_score)}/100 | samples {topWeakness.sample_size}</p>
              </div>
            </div>
          ) : <div className="empty-state compact">No weakness snapshot available yet.</div>}
        </div>

        <div className="panel">
          <div className="panel-head"><span>Latest Lesson</span><strong>{latestLesson?.lesson_type ?? "none"}</strong></div>
          {latestLesson ? (
            <div className="brain-list dense">
              <div>
                <StatusBadge label={`${latestLesson.ticker} | ${latestLesson.setup_type}`} />
                <strong>{latestLesson.observation}</strong>
                <p>Module {latestLesson.affected_module} | confidence {formatNumber(latestLesson.confidence)}/100</p>
              </div>
            </div>
          ) : <div className="empty-state compact">No stored lesson available yet.</div>}
        </div>

        <div className="panel">
          <div className="panel-head"><span>Truth Panel</span><strong>read first</strong></div>
          <div className="brain-list dense">
            {(truthPanel.length ? truthPanel : ["Not enough evidence yet."]).slice(0, 6).map((item, index) => (
              <div key={`${index}-${item}`}>
                <StatusBadge label={index === 0 ? "current state" : "evidence"} />
                <strong>{item}</strong>
              </div>
            ))}
          </div>
        </div>
      </section>
    </>
  );
}

function TradingGameTab({ summary, cycle, loading, error, equityChart, ledgerRows, ledgerSummary, realityCheck, benchmark, onRetry, onLoadMore }: any) {
  return (
    <>
      <AsyncPanel title="Trading Game Evidence" loading={loading && !ledgerRows.length} error={error} updatedAt={summary?.data_freshness?.game_updated_at} onRetry={onRetry} fallback="Loading focused trading evidence">
        <section className="grid-3">
          <div className="panel">
            <div className="panel-head"><span>Capital Cycle Progress</span><strong>{cycle?.status ?? "snapshot"}</strong></div>
            <div className="cycle-progress-track"><span style={{ width: `${cycleProgress(cycle, summary)}%` }} /></div>
            <div className="evidence-grid">
              <SmallDatum label="Capital" value={formatCurrency(cycle?.final_capital ?? summary?.current_capital)} />
              <SmallDatum label="Target" value={formatCurrency(cycle?.target_capital ?? summary?.target_capital)} />
              <SmallDatum label="Progress" value={`${cycleProgress(cycle, summary).toFixed(1)}%`} />
              <SmallDatum label="Trades" value={cycle?.trades_count ?? ledgerSummary?.total_trades ?? "n/a"} />
            </div>
          </div>
          <div className="panel">
            <div className="panel-head"><span>Win / Loss / Missed</span><strong>latest</strong></div>
            <div className="evidence-grid">
              <SmallDatum label="Wins" value={ledgerSummary?.wins ?? cycle?.wins ?? 0} />
              <SmallDatum label="Losses" value={ledgerSummary?.losses ?? cycle?.losses ?? 0} />
              <SmallDatum label="Missed Entries" value={ledgerSummary?.missed_entries ?? cycle?.missed_entries ?? 0} />
              <SmallDatum label="Average R" value={formatR(ledgerSummary?.average_r ?? cycle?.expectancy_r)} />
            </div>
          </div>
          <div className="panel">
            <div className="panel-head"><span>Reality Check</span><strong>{realityCheck?.statistical_confidence ?? "pending"}</strong></div>
            <p>{realityCheck?.explanation ?? "Reality-check evidence appears after the trading game has enough samples."}</p>
            {(realityCheck?.warnings ?? realityCheck?.warnings_json ?? []).slice?.(0, 4)?.map((warning: string) => <StatusBadge key={warning} label={warning} />)}
          </div>
        </section>
      </AsyncPanel>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <PlotPanel title="Equity Curve" data={equityChart} height={320} emptyMessage="Open the Trading Game tab after backend snapshots exist to show the equity curve." />
        <div className="panel">
          <div className="panel-head"><span>Benchmark Summary</span><strong>{benchmark?.result_label ?? benchmark?.status ?? "snapshot"}</strong></div>
          <div className="evidence-grid">
            <SmallDatum label="Benchmark" value={benchmark?.benchmark_ticker ?? benchmark?.benchmark_name ?? "SPY"} />
            <SmallDatum label="BLUM Return" value={formatPctRaw(benchmark?.blum_return)} />
            <SmallDatum label="Benchmark Return" value={formatPctRaw(benchmark?.benchmark_return)} />
            <SmallDatum label="Excess" value={formatPctRaw(benchmark?.excess_return)} />
          </div>
        </div>
      </section>

      <section className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head">
          <span>Latest 25 Trades</span>
          <button className="button compact" onClick={onLoadMore} disabled={loading}>{loading ? "Loading..." : "Load 100 rows"}</button>
        </div>
        <div className="learning-table">
          <div className="learning-row head"><span>Ticker</span><span>Setup</span><span>Entry</span><span>Exit</span><span>P/L</span><span>R</span><span>Outcome</span></div>
          {ledgerRows.slice(0, 100).map((row: any) => (
            <div className="learning-row" key={row.trade_id ?? row.id}>
              <strong>{row.ticker}</strong>
              <span>{String(row.setup_type ?? "").replaceAll("_", " ")}</span>
              <span>{formatDate(row.entry_date)}</span>
              <span>{formatDate(row.exit_date)}</span>
              <span className={Number(row.net_pnl_eur ?? row.gross_pnl_eur) >= 0 ? "positive-text" : "negative-text"}>{formatCurrency(row.net_pnl_eur ?? row.gross_pnl_eur)}</span>
              <span>{formatR(row.r_multiple ?? row.realized_r_multiple)}</span>
              <span>{String(row.outcome_label ?? "open").replaceAll("_", " ")}</span>
            </div>
          ))}
          {ledgerRows.length === 0 && <div className="empty-state">No trade ledger rows loaded yet.</div>}
        </div>
      </section>
    </>
  );
}

function DeepDiagnosticsTab({ diagnostics, loadPanel }: { diagnostics: Record<string, PanelState>; loadPanel: (panelId: string, loader: () => Promise<any>) => void }) {
  const panels = [
    { id: "thesis_survival", title: "Thesis Survival", loader: () => api.thesisSurvival(16), summary: rowsSummary },
    { id: "conviction_decay", title: "Conviction Decay", loader: () => api.convictionDecay(16), summary: rowsSummary },
    { id: "reliability_by_regime", title: "Reliability by Regime", loader: () => api.reliabilityByRegime(16), summary: rowsSummary },
    { id: "ensemble_status", title: "Ensemble Status", loader: () => api.ensembleStatus(), summary: objectSummary },
    { id: "training_quality", title: "Training Quality", loader: () => api.trainingQuality(16), summary: rowsSummary },
    { id: "benchmark_relative", title: "Benchmark Relative Detail", loader: () => api.benchmarkRelative(16), summary: rowsSummary },
    { id: "decision_superiority", title: "Decision Superiority", loader: () => api.decisionIntelligenceDashboard(), summary: objectSummary },
    { id: "business_quality", title: "Business Quality", loader: () => api.businessQualityDashboard(), summary: objectSummary },
    { id: "portfolio_intelligence", title: "Portfolio Intelligence", loader: () => api.portfolioIntelligenceDashboard(), summary: objectSummary },
    { id: "capital_allocation", title: "Capital Allocation", loader: () => api.capitalAllocationDashboard(), summary: objectSummary },
    { id: "performance_diagnostics", title: "Performance Diagnostics", loader: () => api.performanceDiagnostics(), summary: performanceSummary },
  ];

  return (
    <section className="grid-2">
      {panels.map((panel) => {
        const state = diagnostics[panel.id] ?? { loading: false, error: "", data: null };
        return (
          <AsyncPanel key={panel.id} title={panel.title} loading={state.loading} error={state.error} fallback={`Loading ${panel.title}`}>
            {!state.data ? (
              <div className="empty-state compact">
                <p>This diagnostic panel is intentionally lazy-loaded. It will not run during page render.</p>
                <button className="button compact" onClick={() => loadPanel(panel.id, panel.loader)}>Load panel</button>
              </div>
            ) : (
              <div className="brain-list dense">
                <div>
                  <StatusBadge label="loaded on demand" />
                  <strong>{panel.summary(state.data)}</strong>
                  <pre className="json-preview">{JSON.stringify(compactPreview(state.data), null, 2)}</pre>
                  <button className="button compact" onClick={() => loadPanel(panel.id, panel.loader)}>Reload panel</button>
                </div>
              </div>
            )}
          </AsyncPanel>
        );
      })}
    </section>
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

function hasStaleSnapshots(summary: any) {
  return Object.values(summary?.snapshots ?? {}).some((snapshot: any) => snapshot?.is_stale || snapshot?.status === "stale");
}

function formatPct(value: any) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function formatPctRaw(value: any) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  return `${Number(value).toFixed(2)}%`;
}

function formatNumber(value: any) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  return Number(value).toFixed(2);
}

function formatR(value: any) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  return `${Number(value).toFixed(2)}R`;
}

function formatCurrency(value: any) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  return `${Number(value).toFixed(2)} EUR`;
}

function formatTime(value: string | null | undefined) {
  if (!value) return "n/a";
  return new Date(value).toLocaleString();
}

function formatDate(value: string | null | undefined) {
  if (!value) return "open";
  return new Date(value).toLocaleDateString();
}

function cycleProgress(cycle: any, summary: any) {
  const capital = Number(cycle?.final_capital ?? summary?.current_capital ?? 0);
  const target = Number(cycle?.target_capital ?? summary?.target_capital ?? 0);
  if (!Number.isFinite(capital) || !Number.isFinite(target) || target <= 0) return 0;
  return Math.max(0, Math.min(100, (capital / target) * 100));
}

function benchmarkTone(label: any) {
  const value = String(label ?? "");
  if (value === "outperforming") return "positive-text";
  if (value === "underperforming") return "negative-text";
  return "";
}

function rowsSummary(data: any) {
  const rows = Array.isArray(data?.rows) ? data.rows : Array.isArray(data) ? data : [];
  return `${rows.length} rows loaded`;
}

function objectSummary(data: any) {
  if (data?.status) return `Status: ${data.status}`;
  if (data?.generated_at) return `Generated ${formatTime(data.generated_at)}`;
  return `${Object.keys(data ?? {}).length} fields loaded`;
}

function performanceSummary(data: any) {
  return `${data?.api?.request_count ?? 0} API events, ${data?.database?.query_count ?? 0} DB events`;
}

function compactPreview(data: any) {
  if (Array.isArray(data)) return data.slice(0, 3);
  if (Array.isArray(data?.rows)) return { ...data, rows: data.rows.slice(0, 3) };
  const entries = Object.entries(data ?? {}).slice(0, 8);
  return Object.fromEntries(entries);
}

function isRejected(item: PromiseSettledResult<unknown>): item is PromiseRejectedResult {
  return item.status === "rejected";
}
