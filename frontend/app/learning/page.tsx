"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { AlertTriangle, Brain, Gauge, LineChart } from "lucide-react";
import { api } from "@/lib/api";
import { AsyncPanel } from "@/components/AsyncPanel";
import { PlotPanel } from "@/components/PlotPanel";
import { StatusBadge } from "@/components/StatusBadge";

export default function LearningPage() {
  const [summary, setSummary] = useState<any | null>(null);
  const [dashboard, setDashboard] = useState<any | null>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const [predictions, setPredictions] = useState<any[]>([]);
  const [memory, setMemory] = useState<any | null>(null);
  const [trading, setTrading] = useState<any | null>(null);
  const [reasoning, setReasoning] = useState<any | null>(null);
  const [selectedTrade, setSelectedTrade] = useState<any | null>(null);
  const [tradeError, setTradeError] = useState("");
  const [error, setError] = useState("");
  const [summaryError, setSummaryError] = useState("");
  const [chartsLoading, setChartsLoading] = useState(false);
  const [tablesLoading, setTablesLoading] = useState(false);
  const [tablesLoaded, setTablesLoaded] = useState(false);
  const [tablesRequested, setTablesRequested] = useState(false);
  const [deepLoading, setDeepLoading] = useState(false);
  const [deepLoaded, setDeepLoaded] = useState(false);
  const tier3Ref = useRef<HTMLElement | null>(null);

  useEffect(() => {
    let mounted = true;

    async function loadCriticalSummary() {
      try {
        setSummaryError("");
        const [summaryResult, statusResult, currentCycleResult] = await Promise.allSettled([
          api.learningSummary(),
          api.tradingGameStatus(),
          api.tradingGameCurrentCycle()
        ] as const);
        if (!mounted) return;
        if (summaryResult.status === "fulfilled") setSummary(summaryResult.value);
        if (summaryResult.status === "rejected") setSummaryError((summaryResult.reason as Error).message);
        setTrading((previous: any) => ({
          ...(previous ?? {}),
          status: statusResult.status === "fulfilled" ? statusResult.value : previous?.status ?? null,
          currentCycle: currentCycleResult.status === "fulfilled" ? currentCycleResult.value : previous?.currentCycle ?? null
        }));
      } catch (err) {
        if (mounted) setSummaryError(err instanceof Error ? err.message : String(err));
      }
    }

    async function loadMainCharts() {
      setChartsLoading(true);
      const [dashResult, equityResult, annotatedEquityResult, intelligenceMetricsResult, rollingMetricsResult, historicalVsLiveResult, liveStatusResult, liveMetricsResult, learningIntelligenceResult] = await Promise.allSettled([
        api.learningDashboard(),
        api.tradingGameEquity(240),
        api.tradingGameAnnotatedEquity(240),
        api.tradingGameIntelligenceMetrics(),
        api.tradingGameIntelligenceRolling(),
        api.tradingGameHistoricalVsLive(),
        api.liveTradingGameStatus(),
        api.liveTradingGameMetrics(),
        api.learningIntelligenceDashboard()
      ] as const);
      if (!mounted) return;
      if (dashResult.status === "fulfilled") setDashboard(dashResult.value);
      setTrading((previous: any) => ({
        ...(previous ?? {}),
        equity: equityResult.status === "fulfilled" ? equityResult.value : previous?.equity ?? [],
        annotatedEquity: annotatedEquityResult.status === "fulfilled" ? annotatedEquityResult.value : previous?.annotatedEquity ?? null,
        intelligenceMetrics: intelligenceMetricsResult.status === "fulfilled" ? intelligenceMetricsResult.value : previous?.intelligenceMetrics ?? null,
        rollingMetrics: rollingMetricsResult.status === "fulfilled" ? rollingMetricsResult.value : previous?.rollingMetrics ?? null,
        historicalVsLive: historicalVsLiveResult.status === "fulfilled" ? historicalVsLiveResult.value : previous?.historicalVsLive ?? null,
        liveStatus: liveStatusResult.status === "fulfilled" ? liveStatusResult.value : previous?.liveStatus ?? null,
        liveMetrics: liveMetricsResult.status === "fulfilled" ? liveMetricsResult.value : previous?.liveMetrics ?? null,
        learningIntelligence: learningIntelligenceResult.status === "fulfilled" ? learningIntelligenceResult.value : previous?.learningIntelligence ?? null
      }));
      if (dashResult.status === "rejected") setError((dashResult.reason as Error).message);
      setChartsLoading(false);
    }

    loadCriticalSummary();
    const chartsTimer = window.setTimeout(loadMainCharts, 120);
    const summaryPoll = window.setInterval(loadCriticalSummary, 45000);
    return () => {
      mounted = false;
      window.clearTimeout(chartsTimer);
      window.clearInterval(summaryPoll);
    };
  }, []);

  useEffect(() => {
    const node = tier3Ref.current;
    if (!node || tablesRequested || tablesLoaded) return undefined;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setTablesRequested(true);
          observer.disconnect();
        }
      },
      { rootMargin: "320px 0px" }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [tablesRequested, tablesLoaded]);

  useEffect(() => {
    if (!tablesRequested || tablesLoaded || tablesLoading) return undefined;
    let mounted = true;

    async function loadVisibleTables() {
      setTablesLoading(true);
      const [runsResult, predictionsResult, memoryResult, tradesResult, ledgerResult, ledgerSummaryResult, cyclesResult, cycleStatsResult, metricsBySetupResult, metricsByRegimeResult, metricsBySectorResult, livePositionsResult, decisionIntelligenceResult, learningEvidenceResult, realityCheckResult, pnlBreakdownResult, failuresResult, lessonsResult, benchmarkResult, reproducibilityResult] = await Promise.allSettled([
        api.learningRuns(20),
        api.learningPredictions(24),
        api.learningMemory(24),
        api.tradingGameTrades(50),
        api.tradingGameLedger(50),
        api.tradingGameLedgerSummary(),
        api.tradingGameCycles(40),
        api.tradingGameCycleStats(),
        api.tradingGameIntelligenceBySetup(),
        api.tradingGameIntelligenceByRegime(),
        api.tradingGameIntelligenceBySector(),
        api.liveTradingGamePositions(),
        api.decisionIntelligenceDashboard(),
        api.tradingGameLearningEvidence(40),
        api.tradingGameRealityCheck(),
        api.tradingGamePnlBreakdown(),
        api.tradingGameFailures(16),
        api.tradingGameLessons(16),
        api.tradingGameBenchmark(),
        api.tradingGameReproducibility(80)
      ] as const);
      if (!mounted) return;
      if (runsResult.status === "fulfilled") setRuns(runsResult.value);
      if (predictionsResult.status === "fulfilled") setPredictions(predictionsResult.value);
      if (memoryResult.status === "fulfilled") setMemory(memoryResult.value);
      setTrading((previous: any) => ({
        ...(previous ?? {}),
        trades: tradesResult.status === "fulfilled" ? tradesResult.value : previous?.trades ?? [],
        ledger: ledgerResult.status === "fulfilled" ? ledgerResult.value : previous?.ledger ?? null,
        ledgerSummary: ledgerSummaryResult.status === "fulfilled" ? ledgerSummaryResult.value : previous?.ledgerSummary ?? null,
        cycles: cyclesResult.status === "fulfilled" ? cyclesResult.value : previous?.cycles ?? null,
        cycleStats: cycleStatsResult.status === "fulfilled" ? cycleStatsResult.value : previous?.cycleStats ?? null,
        metricsBySetup: metricsBySetupResult.status === "fulfilled" ? metricsBySetupResult.value : previous?.metricsBySetup ?? null,
        metricsByRegime: metricsByRegimeResult.status === "fulfilled" ? metricsByRegimeResult.value : previous?.metricsByRegime ?? null,
        metricsBySector: metricsBySectorResult.status === "fulfilled" ? metricsBySectorResult.value : previous?.metricsBySector ?? null,
        livePositions: livePositionsResult.status === "fulfilled" ? livePositionsResult.value : previous?.livePositions ?? null,
        decisionIntelligence: decisionIntelligenceResult.status === "fulfilled" ? decisionIntelligenceResult.value : previous?.decisionIntelligence ?? null,
        learningEvidence: learningEvidenceResult.status === "fulfilled" ? learningEvidenceResult.value : previous?.learningEvidence ?? null,
        realityCheck: realityCheckResult.status === "fulfilled" ? realityCheckResult.value : previous?.realityCheck ?? null,
        pnlBreakdown: pnlBreakdownResult.status === "fulfilled" ? pnlBreakdownResult.value : previous?.pnlBreakdown ?? null,
        failures: failuresResult.status === "fulfilled" ? failuresResult.value : previous?.failures ?? [],
        lessons: lessonsResult.status === "fulfilled" ? lessonsResult.value : previous?.lessons ?? [],
        benchmark: benchmarkResult.status === "fulfilled" ? benchmarkResult.value : previous?.benchmark ?? null,
        reproducibility: reproducibilityResult.status === "fulfilled" ? reproducibilityResult.value : previous?.reproducibility ?? null
      }));
      setTablesLoaded(true);
      setTablesLoading(false);
    }

    loadVisibleTables();
    return () => {
      mounted = false;
    };
  }, [tablesRequested, tablesLoaded, tablesLoading]);

  async function loadDeepReasoningPanels() {
    setDeepLoading(true);
    const [reasoningStatusResult, survivalResult, convictionResult, reliabilityResult, competitionResult, ensembleResult, benchmarkRelativeResult, trainingQualityResult] = await Promise.allSettled([
      api.reasoningCoreStatus(),
      api.thesisSurvival(16),
      api.convictionDecay(16),
      api.reliabilityByRegime(16),
      api.thesisCompetitions(12),
      api.ensembleStatus(),
      api.benchmarkRelative(16),
      api.trainingQuality(16)
    ] as const);
    setReasoning({
      status: reasoningStatusResult.status === "fulfilled" ? reasoningStatusResult.value : null,
      survival: survivalResult.status === "fulfilled" ? survivalResult.value : null,
      conviction: convictionResult.status === "fulfilled" ? convictionResult.value : null,
      reliability: reliabilityResult.status === "fulfilled" ? reliabilityResult.value : null,
      competitions: competitionResult.status === "fulfilled" ? competitionResult.value : null,
      ensemble: ensembleResult.status === "fulfilled" ? ensembleResult.value : null,
      benchmark: benchmarkRelativeResult.status === "fulfilled" ? benchmarkRelativeResult.value : null,
      trainingQuality: trainingQualityResult.status === "fulfilled" ? trainingQualityResult.value : null
    });
    setDeepLoaded(true);
    setDeepLoading(false);
  }

  const metrics = dashboard?.metrics ?? {};
  const byTimeframe = metrics.by_timeframe ?? {};
  const reliabilityRows = memory?.signal_performance ?? dashboard?.signal_performance ?? [];
  const strategyRows = memory?.strategy_memory ?? dashboard?.strategy_memory ?? [];
  const mistakeRows = memory?.mistakes ?? dashboard?.mistakes ?? [];
  const latestRun = dashboard?.latest_run;
  const game = trading?.status?.current_game ?? dashboard?.trading_game?.current_game ?? {
    current_capital: summary?.current_capital,
    target_capital: summary?.target_capital,
    target_cycles_completed: summary?.completed_target_cycles,
    bankrupt_cycles: summary?.bankrupt_cycles,
    status: summary?.status,
  };
  const equityRows = trading?.equity ?? [];
  const annotatedEquityRows = trading?.annotatedEquity?.equity_curve_points ?? equityRows;
  const equityAnnotations = trading?.annotatedEquity?.annotations ?? [];
  const gameTrades = trading?.trades ?? [];
  const ledgerRows = trading?.ledger?.rows ?? [];
  const advancedLedgerSummary = trading?.ledgerSummary?.summary ?? trading?.ledger?.summary ?? {};
  const cycleRows = trading?.cycles?.cycles ?? [];
  const currentCycle = trading?.currentCycle?.cycle ?? {};
  const cycleStats = trading?.cycleStats?.stats ?? trading?.cycles?.stats ?? {};
  const intelligenceMetrics = trading?.intelligenceMetrics?.metrics ?? {};
  const rollingMetrics = trading?.rollingMetrics?.windows ?? [];
  const setupMetrics = trading?.metricsBySetup?.rows ?? [];
  const regimeMetrics = trading?.metricsByRegime?.rows ?? [];
  const sectorMetrics = trading?.metricsBySector?.rows ?? [];
  const historicalVsLive = trading?.historicalVsLive ?? {};
  const liveStatus = trading?.liveStatus ?? {};
  const liveGame = liveStatus?.game ?? {};
  const livePositionRows = trading?.livePositions?.positions ?? liveStatus?.open_positions ?? [];
  const livePositions = Array.isArray(livePositionRows) ? livePositionRows : [];
  const liveMetrics = trading?.liveMetrics?.metrics ?? {};
  const learningIntelligence = trading?.learningIntelligence ?? {};
  const decisionIntelligence = trading?.decisionIntelligence ?? {};
  const decisionSuperiority = decisionIntelligence?.decision?.decision_superiority ?? {};
  const missedOpportunityRows = decisionIntelligence?.decision?.top_missed_opportunities ?? [];
  const businessQualityRows = decisionIntelligence?.business_quality?.highest_quality_companies ?? [];
  const portfolioQuality = decisionIntelligence?.portfolio?.portfolio_quality ?? {};
  const portfolioContributionRows = decisionIntelligence?.portfolio?.contributions ?? [];
  const portfolioCorrelationRows = decisionIntelligence?.portfolio?.correlations ?? [];
  const tradingPower = learningIntelligence?.trading_power ?? {
    score: summary?.trading_power_score,
    classification: summary?.trading_power_classification,
    truth_panel: summary?.truth_panel,
    warnings: summary?.warnings,
    explanation: summary?.suggested_next_step,
    statistical_confidence: summary?.benchmark_summary?.status,
  };
  const tradingPowerComponents = tradingPower?.components ?? {};
  const benchmarkArenaRows = learningIntelligence?.benchmarks?.rows ?? benchmarkRowsFromSummary(summary);
  const learningProgress = learningIntelligence?.progress ?? {};
  const weaknessRows = learningIntelligence?.weakness_map?.rows ?? [];
  const improvementActions = learningIntelligence?.self_improvement?.actions ?? [];
  const truthPanelRows = learningIntelligence?.truth_panel ?? tradingPower?.truth_panel ?? summary?.truth_panel ?? [];
  const learningEvidenceRows = trading?.learningEvidence?.rows ?? [];
  const realityCheck = trading?.realityCheck ?? {};
  const pnlBreakdown = trading?.pnlBreakdown ?? {};
  const tradingLessons = trading?.lessons ?? [];
  const tradingBenchmark = trading?.benchmark ?? {};
  const reproducibility = trading?.reproducibility ?? {};
  const precisionCounts = reasoning?.status?.precision_core?.counts ?? {};
  const survivalRows = reasoning?.survival?.rows ?? [];
  const convictionRows = reasoning?.conviction?.rows ?? [];
  const reliabilityByRegimeRows = reasoning?.reliability?.rows ?? [];
  const competitionRows = reasoning?.competitions?.rows ?? [];
  const trainingQualityRows = reasoning?.trainingQuality?.rows ?? [];

  const accuracyChart = useMemo(() => {
    const labels = ["short", "mid", "long"];
    return [{
      x: labels,
      y: labels.map((key) => percentToNumber(byTimeframe[key]?.accuracy)),
      type: "bar",
      marker: { color: ["#55aaff", "#20e070", "#ffb000"] }
    }];
  }, [byTimeframe]);

  const equityChart = useMemo(() => {
    const x = annotatedEquityRows.map((row: any) => row.timestamp || row.equity_date || row.created_at);
    const markerAnnotations = equityAnnotations.filter((item: any) => item.event_type !== "trade_entry");
    return [
      { x, y: annotatedEquityRows.map((row: any) => row.equity), type: "scatter", mode: "lines", name: "BLUM", line: { color: "#ffb000", width: 3 } },
      { x, y: annotatedEquityRows.map((row: any) => row.benchmark_equity), type: "scatter", mode: "lines", name: "Benchmark", line: { color: "#55aaff", width: 2 } },
      {
        x: markerAnnotations.map((item: any) => item.timestamp),
        y: markerAnnotations.map((item: any) => item.capital_after_event),
        type: "scatter",
        mode: "markers",
        name: "Events",
        marker: { color: markerAnnotations.map((item: any) => item.pnl_impact >= 0 ? "#20e070" : "#ff4d5e"), size: 9, symbol: "diamond" },
        text: markerAnnotations.map((item: any) => item.label),
        hovertemplate: "%{text}<extra></extra>"
      }
    ];
  }, [annotatedEquityRows, equityAnnotations]);

  async function openTrade(tradeId: number) {
    setTradeError("");
    try {
      const detail = await api.tradingGameTradeDetail(tradeId);
      setSelectedTrade(detail);
    } catch (err) {
      setTradeError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <>
      <header className="page-header">
        <div>
          <div className="kicker">BLUM Trading Intelligence Lab</div>
          <h1>Auditable paper trading intelligence.</h1>
          <p>Capital cycles, advanced trade ledger, live forward paper mode and intelligence-growth metrics. Built to measure whether BLUM is improving entries, exits, risk control and benchmark-relative decision quality.</p>
        </div>
        <div className="header-actions">
          <StatusBadge label={summary?.status === "ready" || dashboard?.status === "active" ? "Learning snapshot ready" : "Loading snapshot"} />
          <StatusBadge label={dashboard?.configuration?.evaluation_mode ?? "progressive"} />
          {chartsLoading && <StatusBadge label="charts loading" />}
          {tablesLoading && <StatusBadge label="tables loading" />}
        </div>
      </header>

      {summaryError && <div className="empty-state" style={{ marginBottom: 12 }}>Summary warning: {summaryError}</div>}
      {error && <div className="empty-state" style={{ marginBottom: 12 }}>Deferred widget warning: {error}</div>}

      <section className="grid-4">
        <LearningMetric icon={<Brain size={18} />} label="Simulations" value={metrics.simulations ?? "loading"} subvalue={`${metrics.outcomes ?? 0} evaluated horizons`} />
        <LearningMetric icon={<Gauge size={18} />} label="Short Accuracy" value={formatPct(byTimeframe.short?.accuracy)} subvalue="5-20 trading days" />
        <LearningMetric icon={<LineChart size={18} />} label="Mid Accuracy" value={formatPct(byTimeframe.mid?.accuracy)} subvalue="1-3 months" />
        <LearningMetric icon={<AlertTriangle size={18} />} label="Calibration Error" value={formatNumber(metrics.confidence_calibration?.mean_absolute_error)} subvalue={metrics.confidence_calibration?.status ?? "insufficient sample"} />
      </section>

      <section className="grid-3" style={{ marginTop: 12 }}>
        <AsyncPanel title="Tier 1 Critical Snapshot" loading={!summary && !summaryError} error={summaryError} updatedAt={summary?.generated_at} fallback="Loading lightweight summary">
          <div className="evidence-grid">
            <SmallDatum label="Capital" value={formatCurrency(summary?.current_capital)} />
            <SmallDatum label="Target Progress" value={summary?.target_progress === null || summary?.target_progress === undefined ? "n/a" : formatPct(summary.target_progress)} />
            <SmallDatum label="Power Score" value={summary?.trading_power_score === null || summary?.trading_power_score === undefined ? "n/a" : `${formatNumber(summary.trading_power_score)}/100`} />
            <SmallDatum label="Benchmarks" value={summary?.benchmark_summary?.status ?? "loading"} />
            <SmallDatum label="Latest Run" value={summary?.latest_learning_run_status ?? "loading"} />
            <SmallDatum label="Freshness" value={formatTime(summary?.generated_at)} />
          </div>
        </AsyncPanel>
        <AsyncPanel title="Tier 2 Main Charts" loading={chartsLoading} error="" updatedAt={summary?.generated_at} fallback="Loading charts without blocking the page">
          <p>Equity curve, benchmark comparison and rolling intelligence metrics load after the critical snapshot.</p>
        </AsyncPanel>
        <AsyncPanel title="Tier 3 Tables" loading={tablesLoading} error="" updatedAt={tablesLoaded ? summary?.generated_at : null} fallback="Loading ledgers and memory tables progressively">
          <p>Trade ledgers, cycles, predictions and learning evidence use safe default limits and load only when this section becomes visible or when requested.</p>
          {!tablesLoaded && (
            <button className="button compact" onClick={() => setTablesRequested(true)} disabled={tablesLoading}>
              {tablesLoading ? "Loading details..." : "Load detailed tables"}
            </button>
          )}
        </AsyncPanel>
      </section>

      <section className="grid-3" style={{ marginTop: 12 }}>
        <div className="panel lab-command-panel">
          <div className="panel-head"><span>BLUM Trading Power Score</span><strong>{formatNumber(tradingPower?.score)}/100</strong></div>
          <div className="cycle-progress-track"><span style={{ width: `${Math.max(0, Math.min(100, Number(tradingPower?.score ?? 0)))}%` }} /></div>
          <div className="evidence-grid">
            <SmallDatum label="Classification" value={tradingPower?.classification ?? "not calculated"} />
            <SmallDatum label="Evidence" value={tradingPower?.statistical_confidence ?? "n/a"} />
            <SmallDatum label="Sample" value={tradingPower?.sample_size ?? 0} />
            <SmallDatum label="Live sample" value={tradingPower?.live_sample_size ?? 0} />
            <SmallDatum label="Benchmark score" value={formatNumber(tradingPowerComponents?.benchmark_relative_score)} />
            <SmallDatum label="Live validation" value={formatNumber(tradingPowerComponents?.live_forward_validation_score)} />
          </div>
          <p>{tradingPower?.explanation ?? "The score appears after the Trading Intelligence ledger has evidence to evaluate."}</p>
          {(tradingPower?.warnings ?? []).length > 0 && <div className="tag-row">{tradingPower.warnings.slice(0, 5).map((item: string) => <span key={item}>{item}</span>)}</div>}
        </div>

        <div className="panel lab-command-panel">
          <div className="panel-head"><span>Truth Panel</span><strong>no hype</strong></div>
          <div className="brain-list dense">
            {(truthPanelRows.length ? truthPanelRows : ["Not enough evidence yet."]).slice(0, 6).map((item: string, index: number) => (
              <div key={`${index}-${item}`}>
                <StatusBadge label={index === 0 ? "current state" : "evidence"} />
                <strong>{item}</strong>
              </div>
            ))}
          </div>
        </div>

        <div className="panel lab-command-panel">
          <div className="panel-head"><span>Learning Progress</span><strong>{learningProgress?.trend_label ?? "inconclusive"}</strong></div>
          <div className="evidence-grid">
            <SmallDatum label="Growth Score" value={`${formatNumber(learningProgress?.intelligence_growth_score)}/100`} />
            <SmallDatum label="Current Trades" value={learningProgress?.current?.trades_count ?? 0} />
            <SmallDatum label="Win Rate" value={formatPct(learningProgress?.current?.win_rate)} />
            <SmallDatum label="Expectancy" value={`${formatNumber(learningProgress?.current?.expectancy_r)}R`} />
            <SmallDatum label="Missed Entry" value={formatPct(learningProgress?.current?.missed_entry_rate)} />
            <SmallDatum label="Benchmark Excess" value={formatPctRaw(learningProgress?.current?.benchmark_excess)} />
          </div>
          <p>{learningProgress?.summary ?? "BLUM cannot claim improvement until rolling windows and live validation are meaningful."}</p>
        </div>
      </section>

      <section className="grid-3" style={{ marginTop: 12 }}>
        <div className="panel lab-command-panel">
          <div className="panel-head"><span>Decision Superiority</span><strong>{formatNumber(decisionSuperiority?.score)}/100</strong></div>
          <div className="cycle-progress-track"><span style={{ width: `${Math.max(0, Math.min(100, Number(decisionSuperiority?.score ?? 0)))}%` }} /></div>
          <div className="evidence-grid">
            <SmallDatum label="Classification" value={decisionSuperiority?.classification ?? "insufficient evidence"} />
            <SmallDatum label="Recall" value={formatPct(decisionSuperiority?.metrics?.opportunity_recall)} />
            <SmallDatum label="Precision" value={formatPct(decisionSuperiority?.metrics?.opportunity_precision)} />
            <SmallDatum label="Alpha Capture" value={formatPct(decisionSuperiority?.metrics?.alpha_capture_rate)} />
            <SmallDatum label="Ranking" value={formatPct(decisionSuperiority?.metrics?.ranking_accuracy)} />
            <SmallDatum label="Comparable Decisions" value={decisionSuperiority?.sample_size ?? 0} />
          </div>
          <p>{decisionSuperiority?.explanation ?? "BLUM needs comparable decision snapshots before it can claim it selected superior opportunities."}</p>
          {missedOpportunityRows.length > 0 && <div className="tag-row">{missedOpportunityRows.slice(0, 4).map((row: any) => <span key={`${row.trade_id}-${row.best_available_ticker}`}>Missed {row.best_available_ticker} vs {row.ticker}</span>)}</div>}
        </div>

        <div className="panel lab-command-panel">
          <div className="panel-head"><span>Business Quality Lab</span><strong>{businessQualityRows.length}</strong></div>
          <div className="brain-list dense">
            {(businessQualityRows.length ? businessQualityRows : []).slice(0, 5).map((row: any) => (
              <div key={row.ticker}>
                <StatusBadge label={`${row.ticker} | ${row.status}`} />
                <div className="opportunity-line"><strong>{row.name}</strong><span>{formatNumber(row.business_quality_score)}/100</span></div>
                <p>Growth {formatNumber(row.growth_quality)} | FCF {formatNumber(row.cash_flow_quality)} | moat {formatNumber(row.moat_quality)} | data {formatNumber(row.data_quality_score)}</p>
              </div>
            ))}
            {businessQualityRows.length === 0 && <div className="empty-state compact">No business-quality evidence yet. Stored fundamental snapshots are required.</div>}
          </div>
        </div>

        <div className="panel lab-command-panel">
          <div className="panel-head"><span>Portfolio Intelligence</span><strong>{formatNumber(portfolioQuality?.score)}/100</strong></div>
          <div className="evidence-grid">
            <SmallDatum label="Diversification" value={formatNumber(portfolioQuality?.components?.diversification)} />
            <SmallDatum label="Concentration Risk" value={formatNumber(portfolioQuality?.components?.concentration_risk)} />
            <SmallDatum label="Drawdown Control" value={formatNumber(portfolioQuality?.components?.drawdown_control)} />
            <SmallDatum label="Alpha Generation" value={formatNumber(portfolioQuality?.components?.alpha_generation)} />
            <SmallDatum label="Contributors" value={portfolioContributionRows.length} />
            <SmallDatum label="Correlations" value={portfolioCorrelationRows.length} />
          </div>
          <p>{portfolioQuality?.explanation ?? "BLUM needs portfolio trade evidence before contribution, concentration and portfolio-alpha quality can be measured."}</p>
          {(portfolioQuality?.warnings ?? []).length > 0 && <div className="tag-row">{portfolioQuality.warnings.slice(0, 4).map((item: string) => <span key={item}>{item}</span>)}</div>}
        </div>
      </section>

      <section className="grid-3" style={{ marginTop: 12 }}>
        <div className="panel">
          <div className="panel-head"><span>Benchmark Arena</span><strong>{benchmarkArenaRows.length}</strong></div>
          <div className="learning-table">
            <div className="learning-row head"><span>Benchmark</span><span>Type</span><span>Result</span><span>Excess</span><span>Sample</span><span>Evidence</span></div>
            {benchmarkArenaRows.slice(0, 10).map((row: any) => (
              <div className="learning-row" key={`${row.benchmark_name}-${row.benchmark_type}`}>
                <strong>{row.benchmark_name}</strong>
                <span>{row.benchmark_type}</span>
                <span className={benchmarkTone(row.result_label)}>{String(row.result_label).replaceAll("_", " ")}</span>
                <span className={Number(row.excess_return) >= 0 ? "positive-text" : "negative-text"}>{formatPctRaw(row.excess_return)}</span>
                <span>{row.sample_size}</span>
                <span>{row.statistical_confidence}</span>
              </div>
            ))}
            {benchmarkArenaRows.length === 0 && <div className="empty-state">No benchmark comparison is available yet.</div>}
          </div>
        </div>

        <div className="panel">
          <div className="panel-head"><span>Strength / Weakness Map</span><strong>{weaknessRows.length}</strong></div>
          <div className="brain-list dense">
            {weaknessRows.slice(0, 6).map((row: any) => (
              <div key={`${row.dimension}-${row.entity}`}>
                <StatusBadge label={`${row.dimension}: ${String(row.entity).replaceAll("_", " ")}`} />
                <div className="opportunity-line"><strong>{row.main_problem}</strong><span>{formatNumber(row.weakness_score)}/100 weak</span></div>
                <p>{row.recommended_action}</p>
                <p>Samples {row.sample_size} | strength {formatNumber(row.strength_score)} | priority {row.priority}</p>
              </div>
            ))}
            {weaknessRows.length === 0 && <div className="empty-state compact">No weakness map yet. BLUM needs trade outcomes and attribution samples.</div>}
          </div>
        </div>

        <div className="panel">
          <div className="panel-head"><span>Self-Improvement Queue</span><strong>{improvementActions.length}</strong></div>
          <div className="brain-list dense">
            {improvementActions.slice(0, 6).map((row: any) => (
              <div key={row.id ?? `${row.source_dimension}-${row.affected_module}`}>
                <StatusBadge label={`${row.priority} | ${row.status}`} />
                <strong>{row.detected_problem}</strong>
                <p>{row.recommended_action}</p>
                <p>Module {row.affected_module} | impact: {row.expected_impact}</p>
              </div>
            ))}
            {improvementActions.length === 0 && <div className="empty-state compact">No self-improvement action has been proposed yet.</div>}
          </div>
        </div>
      </section>

      <section className="grid-3" style={{ marginTop: 12 }}>
        <div className="panel lab-command-panel">
          <div className="panel-head"><span>Capital Cycle</span><strong>{currentCycle?.status ?? "no cycle"}</strong></div>
          <div className="cycle-progress-track"><span style={{ width: `${cycleProgress(currentCycle)}%` }} /></div>
          <div className="evidence-grid">
            <SmallDatum label="Cycle Capital" value={formatCurrency(currentCycle?.final_capital ?? game?.current_capital)} />
            <SmallDatum label="Target" value={formatCurrency(currentCycle?.target_capital ?? game?.target_capital)} />
            <SmallDatum label="Progress" value={`${cycleProgress(currentCycle).toFixed(1)}%`} />
            <SmallDatum label="Cycle #" value={currentCycle?.cycle_number ?? "n/a"} />
            <SmallDatum label="Targets Hit" value={cycleStats?.target_cycles_completed ?? game?.target_cycles_completed ?? 0} />
            <SmallDatum label="Bankrupt Cycles" value={cycleStats?.bankrupt_cycles ?? game?.bankrupt_cycles ?? 0} />
          </div>
          <p>Capital growth is capped into 100 EUR to target cycles. When target or bankruptcy is reached, the cycle is recorded and the active bankroll restarts from 100 EUR.</p>
        </div>

        <div className="panel lab-command-panel">
          <div className="panel-head"><span>Trading Intelligence Metrics</span><strong>{formatNumber(intelligenceMetrics?.intelligence_growth_score)}/100</strong></div>
          <div className="evidence-grid">
            <SmallDatum label="Win Rate" value={formatPct(intelligenceMetrics?.win_rate)} />
            <SmallDatum label="Missed Entry" value={formatPct(intelligenceMetrics?.missed_entry_rate)} />
            <SmallDatum label="Target Hit" value={formatPct(intelligenceMetrics?.target_hit_rate)} />
            <SmallDatum label="Stop Hit" value={formatPct(intelligenceMetrics?.stop_hit_rate)} />
            <SmallDatum label="Expectancy" value={`${formatNumber(intelligenceMetrics?.expectancy_r)}R`} />
            <SmallDatum label="Benchmark Excess" value={formatPctRaw(intelligenceMetrics?.benchmark_excess)} />
          </div>
          <p>These metrics measure decision quality, not only P/L. High numbers still require sample-size and realism checks before they mean anything.</p>
        </div>

        <div className="panel lab-command-panel">
          <div className="panel-head"><span>Historical vs Live Forward</span><strong>{liveStatus?.status ?? "loading"}</strong></div>
          <div className="evidence-grid">
            <SmallDatum label="Live Capital" value={formatCurrency(liveGame?.current_capital)} />
            <SmallDatum label="Open Positions" value={livePositions.length ?? liveGame?.open_positions ?? 0} />
            <SmallDatum label="Live Trades" value={liveMetrics?.trades_count ?? historicalVsLive?.live?.trades_count ?? 0} />
            <SmallDatum label="Historical Trades" value={historicalVsLive?.historical?.trades_count ?? 0} />
            <SmallDatum label="Live Expectancy" value={`${formatNumber(liveMetrics?.expectancy_r ?? historicalVsLive?.live?.expectancy_r)}R`} />
            <SmallDatum label="Historical Expectancy" value={`${formatNumber(historicalVsLive?.historical?.expectancy_r)}R`} />
          </div>
          <p>{historicalVsLive?.sample_warning ?? "Live forward paper evidence starts weak and becomes meaningful only after enough timestamp-frozen trades close."}</p>
        </div>
      </section>

      {!deepLoaded ? (
        <section className="panel" style={{ marginTop: 12 }}>
          <div className="panel-head">
            <span>Tier 4 Deep Reasoning Panels</span>
            <button className="button compact" onClick={loadDeepReasoningPanels} disabled={deepLoading}>{deepLoading ? "Loading..." : "Load deep reasoning panels"}</button>
          </div>
          <p>Thesis survival, conviction decay, regime-aware reliability, thesis competitions, ensemble status and training quality are intentionally lazy-loaded. They no longer block the Learning dashboard first render.</p>
        </section>
      ) : (
        <section className="grid-2" style={{ marginTop: 12 }}>
          <div className="panel">
            <div className="panel-head">
              <span>Reasoning Precision Core</span>
              <strong>{reasoning?.status?.precision_core?.status ?? "Loading"}</strong>
            </div>
            <div className="evidence-grid">
              <SmallDatum label="Survival Metrics" value={precisionCounts.thesis_survival_metrics ?? 0} />
              <SmallDatum label="Conviction Rows" value={precisionCounts.conviction_history_rows ?? 0} />
              <SmallDatum label="Regime Reliability" value={precisionCounts.reliability_by_regime_rows ?? 0} />
              <SmallDatum label="Thesis Competitions" value={precisionCounts.thesis_competitions ?? 0} />
              <SmallDatum label="Engine Votes" value={precisionCounts.engine_votes ?? 0} />
              <SmallDatum label="Benchmark Outcomes" value={precisionCounts.benchmark_relative_outcomes ?? 0} />
            </div>
            <p>These panels measure thesis durability, confidence decay, benchmark-relative evidence and engine disagreement. They update database memory only; no source code is self-modified.</p>
          </div>

          <div className="panel">
            <div className="panel-head"><span>Thesis survival and decay</span><strong>{survivalRows.length} / {convictionRows.length}</strong></div>
            <div className="learning-table">
              <div className="learning-row head"><span>Ticker</span><span>Status</span><span>Age</span><span>Confidence</span><span>Excess</span><span>Quality</span></div>
              {survivalRows.slice(0, 8).map((row: any) => (
                <div className="learning-row" key={row.id}>
                  <strong>{row.ticker}</strong>
                  <span>{row.survival_status}</span>
                  <span>{formatNumber(row.survival_days)}d</span>
                  <span>{formatNumber(row.current_confidence)}</span>
                  <span className={Number(row.excess_return) >= 0 ? "positive-text" : "negative-text"}>{formatPctDecimal(row.excess_return)}</span>
                  <span>{formatNumber(row.survival_quality_score)}</span>
                </div>
              ))}
              {survivalRows.length === 0 && <div className="empty-state">No thesis survival rows yet. The autonomous model cycle will create them after stored theses exist.</div>}
            </div>
          </div>
        </section>
      )}

      <section className="panel" style={{ marginTop: 12 }} ref={tier3Ref}>
        <div className="panel-head">
          <span>Full Trade Ledger</span>
          <strong>{ledgerRows.length} visible / {trading?.ledger?.total ?? 0} total</strong>
        </div>
        {!tablesRequested && !tablesLoaded && (
          <div className="empty-state compact" style={{ marginBottom: 12 }}>
            Detailed ledgers are lazy-loaded. Scroll here or use the Tier 3 button to fetch paginated trade evidence.
          </div>
        )}
        <div className="evidence-grid" style={{ marginBottom: 12 }}>
          <SmallDatum label="Wins" value={advancedLedgerSummary?.wins ?? 0} />
          <SmallDatum label="Losses" value={advancedLedgerSummary?.losses ?? 0} />
          <SmallDatum label="Missed Entries" value={advancedLedgerSummary?.missed_entries ?? 0} />
          <SmallDatum label="Target Hits" value={advancedLedgerSummary?.target_hits ?? 0} />
          <SmallDatum label="Stop Hits" value={advancedLedgerSummary?.stop_hits ?? 0} />
          <SmallDatum label="No-Trade Correct" value={advancedLedgerSummary?.no_trade_correct ?? 0} />
        </div>
        <div className="learning-table trade-ledger-table">
          <div className="learning-row trade-ledger-row head"><span>Ticker</span><span>Setup</span><span>Mode</span><span>Cycle</span><span>Entry</span><span>Exit</span><span>P/L EUR</span><span>P/L/share</span><span>R</span><span>Outcome</span><span>Quality</span><span>Excess</span></div>
          {ledgerRows.slice(0, 18).map((row: any) => (
            <button className="learning-row trade-ledger-row clickable" key={row.trade_id} onClick={() => openTrade(row.trade_id)}>
              <strong>{row.ticker}</strong>
              <span>{String(row.setup_type).replaceAll("_", " ")}</span>
              <span>{String(row.mode ?? "historical").replaceAll("_", " ")}</span>
              <span>{row.capital_cycle_id ?? "n/a"}</span>
              <span>{row.entry_date}<br />{formatNumber(row.entry_price)}</span>
              <span>{row.exit_date ?? "open"}<br />{formatNumber(row.exit_price)}</span>
              <span className={Number(row.net_pnl_eur) >= 0 ? "positive-text" : "negative-text"}>{formatCurrency(row.net_pnl_eur)}</span>
              <span className={Number(row.pnl_per_share) >= 0 ? "positive-text" : "negative-text"}>{formatNumber(row.pnl_per_share)}</span>
              <span className={Number(row.r_multiple) >= 0 ? "positive-text" : "negative-text"}>{formatNumber(row.r_multiple)}</span>
              <span>{String(row.outcome_label ?? row.decision_state).replaceAll("_", " ")}</span>
              <span>{formatNumber(row.trade_quality_score)}</span>
              <span className={Number(row.excess_return_vs_benchmark) >= 0 ? "positive-text" : "negative-text"}>{formatPctRaw(row.excess_return_vs_benchmark)}</span>
            </button>
          ))}
          {ledgerRows.length === 0 && <div className="empty-state">No detailed trade ledger is available yet. The next Trading Game run will enrich persisted trades with entry, exit, attribution, P/L and learning evidence.</div>}
        </div>
      </section>

      {tradeError && <div className="empty-state" style={{ marginTop: 12 }}>Trade detail error: {tradeError}</div>}
      {selectedTrade && (
        <section className="panel trade-detail-panel" style={{ marginTop: 12 }}>
          <div className="panel-head">
            <span>Trade Replay</span>
            <button className="button compact" onClick={() => setSelectedTrade(null)}>Close</button>
          </div>
          <div className="grid-3">
            <div className="observed-model-panel">
              <span>Trade</span>
              <h3>{selectedTrade.trade?.ticker} / {String(selectedTrade.trade?.setup_type).replaceAll("_", " ")}</h3>
              <p>{selectedTrade.replay?.entry_decision?.why_considered}</p>
              <p>{selectedTrade.replay?.exit_decision?.reason}</p>
            </div>
            <div className="observed-model-panel">
              <span>P/L Breakdown</span>
              <div className="evidence-grid">
                <SmallDatum label="Net P/L" value={formatCurrency(selectedTrade.pnl_breakdown?.net_pnl_eur)} />
                <SmallDatum label="Per Share" value={formatNumber(selectedTrade.pnl_breakdown?.pnl_per_share)} />
                <SmallDatum label="R Multiple" value={formatNumber(selectedTrade.pnl_breakdown?.r_multiple)} />
                <SmallDatum label="Benchmark Excess" value={formatPctRaw(selectedTrade.pnl_breakdown?.benchmark_relative_pnl)} />
                <SmallDatum label="Fees" value={formatCurrency(selectedTrade.pnl_breakdown?.fees_estimate)} />
                <SmallDatum label="Slippage" value={formatCurrency(selectedTrade.pnl_breakdown?.slippage_estimate)} />
              </div>
            </div>
            <div className="observed-model-panel">
              <span>Risk Plan</span>
              <div className="evidence-grid">
                <SmallDatum label="Capital Before" value={formatCurrency(selectedTrade.replay?.risk_management?.capital_before)} />
                <SmallDatum label="Risk EUR" value={formatCurrency(selectedTrade.replay?.risk_management?.risk_amount_eur)} />
                <SmallDatum label="Risk %" value={formatPctRaw(selectedTrade.replay?.risk_management?.risk_percent)} />
                <SmallDatum label="Size" value={formatNumber(selectedTrade.replay?.risk_management?.position_size)} />
                <SmallDatum label="Invalidation" value={formatNumber(selectedTrade.replay?.risk_management?.invalidation_level)} />
                <SmallDatum label="Max Loss" value={formatCurrency(selectedTrade.replay?.risk_management?.max_expected_loss)} />
              </div>
            </div>
          </div>
          <section className="grid-3" style={{ marginTop: 12 }}>
            <div className="panel-inner">
              <span>Engine Attribution</span>
              <div className="brain-list dense">
                {(selectedTrade.attribution ?? []).slice(0, 6).map((row: any) => (
                  <div key={row.id ?? row.engine_name}>
                    <StatusBadge label={row.engine_name} />
                    <strong>{row.vote} | contribution {formatNumber(row.contribution_score)}</strong>
                    <p>{row.explanation}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="panel-inner">
              <span>Trade Quality</span>
              <p>{selectedTrade.quality?.explanation}</p>
              <div className="evidence-grid">
                <SmallDatum label="Final" value={formatNumber(selectedTrade.quality?.final_trade_quality_score)} />
                <SmallDatum label="Entry" value={formatNumber(selectedTrade.quality?.entry_quality)} />
                <SmallDatum label="Exit" value={formatNumber(selectedTrade.quality?.exit_quality)} />
                <SmallDatum label="Risk/Reward" value={formatNumber(selectedTrade.quality?.risk_reward_quality)} />
                <SmallDatum label="Rule" value={formatNumber(selectedTrade.quality?.rule_compliance)} />
                <SmallDatum label="Luck" value={formatNumber(selectedTrade.quality?.luck_factor)} />
              </div>
            </div>
            <div className="panel-inner">
              <span>Learning Outcome</span>
              <div className="brain-list dense">
                {(selectedTrade.learning_outcome ?? []).slice(0, 4).map((row: any) => (
                  <div key={row.id}>
                    <StatusBadge label={String(row.lesson_type).replaceAll("_", " ")} />
                    <strong>{row.affected_module}</strong>
                    <p>{row.observation}</p>
                  </div>
                ))}
                {(!selectedTrade.learning_outcome || selectedTrade.learning_outcome.length === 0) && <div className="empty-state compact">No learning evidence is linked to this trade yet.</div>}
              </div>
            </div>
          </section>
        </section>
      )}

      <section className="grid-3" style={{ marginTop: 12 }}>
        <div className="panel">
          <div className="panel-head"><span>Reality Check</span><strong>{realityCheck?.statistical_confidence ?? "n/a"}</strong></div>
          <div className="evidence-grid">
            <SmallDatum label="Trades" value={realityCheck?.trades_count ?? 0} />
            <SmallDatum label="Tickers" value={realityCheck?.unique_tickers ?? 0} />
            <SmallDatum label="Sectors" value={realityCheck?.unique_sectors ?? 0} />
            <SmallDatum label="Regimes" value={realityCheck?.unique_regimes ?? 0} />
            <SmallDatum label="Sample" value={`${formatNumber(realityCheck?.sample_quality_score)}/100`} />
            <SmallDatum label="Realism" value={`${formatNumber(realityCheck?.realism_score)}/100`} />
          </div>
          <p>{realityCheck?.explanation ?? "Reality check will appear after trade transparency runs."}</p>
          {(realityCheck?.warnings ?? []).length > 0 && <div className="tag-row">{realityCheck.warnings.slice(0, 8).map((item: string) => <span key={item}>{item.replaceAll("_", " ")}</span>)}</div>}
        </div>
        <div className="panel">
          <div className="panel-head"><span>P/L Breakdown</span><strong>{formatCurrency(pnlBreakdown?.total_realized_pnl)}</strong></div>
          <div className="brain-list dense">
            {Object.entries(pnlBreakdown?.pnl_by_setup ?? {}).slice(0, 5).map(([setup, value]: any) => (
              <div key={setup}>
                <div className="opportunity-line"><strong>{setup.replaceAll("_", " ")}</strong><span className={Number(value.pnl) >= 0 ? "positive-text" : "negative-text"}>{formatCurrency(value.pnl)}</span></div>
                <p>Count {value.count} | average {formatNumber(value.average_r)}R</p>
              </div>
            ))}
            {Object.keys(pnlBreakdown?.pnl_by_setup ?? {}).length === 0 && <div className="empty-state compact">No setup-level P/L breakdown yet.</div>}
          </div>
        </div>
        <div className="panel">
          <div className="panel-head"><span>Learning Evidence Log</span><strong>{learningEvidenceRows.length}</strong></div>
          <div className="brain-list dense">
            {learningEvidenceRows.slice(0, 6).map((row: any) => (
              <div key={row.id}>
                <StatusBadge label={String(row.lesson_type).replaceAll("_", " ")} />
                <strong>{row.ticker} | {String(row.setup_type).replaceAll("_", " ")}</strong>
                <p>{row.observation}</p>
              </div>
            ))}
            {learningEvidenceRows.length === 0 && <div className="empty-state compact">No trade learning evidence has been persisted yet.</div>}
          </div>
        </div>
      </section>

      <section className="grid-3" style={{ marginTop: 12 }}>
        <div className="panel">
          <div className="panel-head"><span>Capital Cycle History</span><strong>{cycleRows.length}</strong></div>
          <div className="brain-list dense">
            {cycleRows.slice(0, 6).map((row: any) => (
              <div key={row.id}>
                <StatusBadge label={`Cycle ${row.cycle_number}`} />
                <div className="opportunity-line"><strong>{String(row.status).replaceAll("_", " ")}</strong><span>{formatCurrency(row.final_capital)}</span></div>
                <p>Target {formatCurrency(row.target_capital)} | trades {row.trades_count} | return {formatPctRaw(row.return_percent)} | expectancy {formatNumber(row.expectancy_r)}R</p>
              </div>
            ))}
            {cycleRows.length === 0 && <div className="empty-state compact">No capital cycle has been recorded yet.</div>}
          </div>
        </div>
        <div className="panel">
          <div className="panel-head"><span>Setup Development</span><strong>{setupMetrics.length}</strong></div>
          <div className="brain-list dense">
            {setupMetrics.slice(0, 6).map((row: any) => (
              <div key={row.scope_id}>
                <StatusBadge label={String(row.scope_id).replaceAll("_", " ")} />
                <div className="opportunity-line"><strong>{formatNumber(row.intelligence_growth_score)}/100 growth</strong><span>{formatNumber(row.expectancy_r)}R</span></div>
                <p>Win {formatPct(row.win_rate)} | missed {formatPct(row.missed_entry_rate)} | quality {formatNumber(row.trade_quality_score)}</p>
              </div>
            ))}
            {setupMetrics.length === 0 && <div className="empty-state compact">No setup intelligence metrics yet.</div>}
          </div>
        </div>
        <div className="panel">
          <div className="panel-head"><span>Regime / Sector Learning</span><strong>{regimeMetrics.length + sectorMetrics.length}</strong></div>
          <div className="brain-list dense">
            {regimeMetrics.slice(0, 3).map((row: any) => (
              <div key={`regime-${row.scope_id}`}>
                <StatusBadge label={`Regime ${row.scope_id}`} />
                <strong>{formatNumber(row.intelligence_growth_score)}/100 | {formatNumber(row.expectancy_r)}R</strong>
                <p>Benchmark excess {formatPctRaw(row.benchmark_excess)} | trades {row.trades_count}</p>
              </div>
            ))}
            {sectorMetrics.slice(0, 3).map((row: any) => (
              <div key={`sector-${row.scope_id}`}>
                <StatusBadge label={`Sector ${row.scope_id}`} />
                <strong>{formatNumber(row.intelligence_growth_score)}/100 | {formatNumber(row.expectancy_r)}R</strong>
                <p>Benchmark excess {formatPctRaw(row.benchmark_excess)} | trades {row.trades_count}</p>
              </div>
            ))}
            {regimeMetrics.length + sectorMetrics.length === 0 && <div className="empty-state compact">No regime or sector learning metrics yet.</div>}
          </div>
        </div>
      </section>

      {deepLoaded && (
        <section className="grid-2" style={{ marginTop: 12 }}>
          <div className="panel">
            <div className="panel-head"><span>Regime-aware reliability</span><strong>{reliabilityByRegimeRows.length}</strong></div>
            <div className="learning-table">
              <div className="learning-row head"><span>Engine</span><span>Setup</span><span>Regime</span><span>Samples</span><span>Hit</span><span>Penalty</span></div>
              {reliabilityByRegimeRows.slice(0, 8).map((row: any) => (
                <div className="learning-row" key={row.id}>
                  <strong>{String(row.engine_name).replaceAll("_", " ")}</strong>
                  <span>{String(row.setup_type).replaceAll("_", " ")}</span>
                  <span>{row.market_regime}</span>
                  <span>{row.sample_size}</span>
                  <span>{formatPct(row.hit_rate)}</span>
                  <span>{formatNumber(row.confidence_penalty)}</span>
                </div>
              ))}
              {reliabilityByRegimeRows.length === 0 && <div className="empty-state">No regime-specific reliability rows yet. BLUM needs matured thesis outcomes first.</div>}
            </div>
          </div>

          <div className="panel">
            <div className="panel-head"><span>Thesis competition and training quality</span><strong>{competitionRows.length}</strong></div>
            <div className="brain-list dense">
              {competitionRows.slice(0, 5).map((row: any) => (
                <div key={row.id}>
                  <StatusBadge label={row.ticker} />
                  <strong>{row.judge_summary || "Competition pending"}</strong>
                  <p>Uncertainty {formatNumber(row.uncertainty_score)}/100 | theses {row.theses?.length ?? 0}</p>
                </div>
              ))}
              {competitionRows.length === 0 && <div className="empty-state">No bull/bear/neutral thesis competitions yet.</div>}
              {trainingQualityRows.slice(0, 3).map((row: any) => (
                <div key={`quality-${row.id}`}>
                  <StatusBadge label="Training gate" />
                  <strong>Training value {formatNumber(row.final_training_value_score)}/100</strong>
                  <p>SFT {String(row.include_in_sft)} | preference {String(row.include_in_preference_training)} | DPO {String(row.include_in_dpo)}</p>
                </div>
              ))}
            </div>
          </div>
        </section>
      )}

      <section className="grid-2" style={{ marginTop: 12 }}>
        <PlotPanel
          title="Trading Game Equity Curve"
          data={equityChart as any}
          layout={{ yaxis: { title: "Capital EUR" }, xaxis: { title: "Simulation date" } }}
        />
        <div className="panel">
          <div className="panel-head">
            <span>Paper P/L and capital discipline</span>
            <strong>{game?.status ?? "No game"}</strong>
          </div>
          {game ? (
            <div className="brain-list dense">
              <div className="evidence-grid">
                <SmallDatum label="Capital" value={formatCurrency(game.current_capital)} />
                <SmallDatum label="Realized P/L" value={formatCurrency(game.realized_pl)} />
                <SmallDatum label="Max Drawdown" value={`${formatNumber(game.max_drawdown)}%`} />
                <SmallDatum label="Expectancy" value={`${formatNumber(game.expectancy_r)}R`} />
                <SmallDatum label="Profit Factor" value={formatNumber(game.profit_factor)} />
                <SmallDatum label="Risk of Ruin" value={`${formatNumber(game.risk_of_ruin)}%`} />
                <SmallDatum label="Benchmark Alpha" value={`${formatNumber(tradingBenchmark?.alpha)}%`} />
                <SmallDatum label="Reproducibility" value={`${formatNumber(reproducibility?.average_reproducibility)}/100`} />
              </div>
              <p>BLUM starts each paper game at 100 EUR, risks fractionally, rejects non-reproducible setups and compares the equity curve against {tradingBenchmark?.benchmark ?? game.benchmark_ticker}. Small samples never qualify as proof of outperformance.</p>
            </div>
          ) : (
            <div className="empty-state">No trading game has been created yet. The autonomous engine will start it after Sniper simulations are available.</div>
          )}
        </div>
      </section>

      <section className="grid-2" style={{ marginTop: 12 }}>
        <div className="panel">
          <div className="panel-head"><span>Recent reproducible trade decisions</span><strong>{gameTrades.length}</strong></div>
          <div className="learning-table">
            <div className="learning-row head"><span>Ticker</span><span>Setup</span><span>Decision</span><span>R</span><span>P/L</span><span>Capital</span></div>
            {gameTrades.slice(0, 12).map((row: any) => (
              <div className="learning-row" key={row.id}>
                <strong>{row.ticker}</strong>
                <span>{String(row.setup_type).replaceAll("_", " ")}</span>
                <span>{String(row.decision_state).replaceAll("_", " ")}</span>
                <span className={Number(row.realized_r_multiple) >= 0 ? "positive-text" : "negative-text"}>{formatNumber(row.realized_r_multiple)}</span>
                <span className={Number(row.realized_pl) >= 0 ? "positive-text" : "negative-text"}>{formatCurrency(row.realized_pl)}</span>
                <span>{formatCurrency(row.capital_after)}</span>
              </div>
            ))}
            {gameTrades.length === 0 && <div className="empty-state">No P/L decisions yet. BLUM needs stored execution simulations before the game can score trades.</div>}
          </div>
        </div>
        <div className="panel">
          <div className="panel-head"><span>Capital management lessons</span><strong>{tradingLessons.length}</strong></div>
          <div className="brain-list dense">
            {tradingLessons.slice(0, 8).map((row: any) => (
              <div key={row.id}>
                <StatusBadge label={String(row.category).replaceAll("_", " ")} />
                <strong>{row.lesson}</strong>
                <p>Reliability {formatNumber(row.reliability_score)}/100 | samples {row.sample_count}</p>
              </div>
            ))}
            {tradingLessons.length === 0 && <div className="empty-state">No capital management lessons yet.</div>}
          </div>
        </div>
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
              <p>{latestRun.anti_overfitting_report?.policy ?? dashboard?.policy ?? "Learning Loop policy will appear after the dashboard snapshot loads."}</p>
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
          <SmallDatum label="Asset Universe" value={dashboard?.configuration?.asset_universe ?? "stocks,etfs"} />
          <SmallDatum label="Min History" value={`${dashboard?.configuration?.min_history_years ?? "n/a"} years`} />
          <SmallDatum label="Daily Guard" value={dashboard?.configuration?.max_daily_runs ?? "n/a"} />
          <SmallDatum label="Batch Size" value={dashboard?.configuration?.batch_size ?? "n/a"} />
        </div>
        <p>{dashboard?.policy ?? "Progressive loading is active. Deep learning details load after the lightweight summary and visible tables."}</p>
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

function formatPctDecimal(value: any) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  return `${(Number(value) * 100).toFixed(2)}%`;
}

function formatPctRaw(value: any) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  return `${Number(value).toFixed(2)}%`;
}

function cycleProgress(cycle: any) {
  const capital = Number(cycle?.final_capital ?? 0);
  const target = Number(cycle?.target_capital ?? 0);
  if (!Number.isFinite(capital) || !Number.isFinite(target) || target <= 0) return 0;
  return Math.max(0, Math.min(100, (capital / target) * 100));
}

function percentToNumber(value: any) {
  return value === null || value === undefined ? 0 : Number(value) * 100;
}

function formatNumber(value: any) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  return Number(value).toFixed(2);
}

function formatCurrency(value: any) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  return `${Number(value).toFixed(2)} EUR`;
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

function benchmarkTone(label: any) {
  const value = String(label ?? "");
  if (value === "outperforming") return "positive-text";
  if (value === "underperforming") return "negative-text";
  return "";
}

function benchmarkRowsFromSummary(summary: any) {
  const rows = summary?.benchmark_summary?.major_benchmarks ?? {};
  return Object.entries(rows).map(([benchmark_name, payload]: any) => ({
    benchmark_name,
    benchmark_type: "market",
    result_label: payload.result_label,
    excess_return: payload.excess_return,
    sample_size: payload.sample_size,
    statistical_confidence: payload.statistical_confidence,
  }));
}

function isRejected(item: PromiseSettledResult<unknown>): item is PromiseRejectedResult {
  return item.status === "rejected";
}
