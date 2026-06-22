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
  const [trading, setTrading] = useState<any | null>(null);
  const [reasoning, setReasoning] = useState<any | null>(null);
  const [selectedTrade, setSelectedTrade] = useState<any | null>(null);
  const [tradeError, setTradeError] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    async function load() {
      setError("");
      const [dashResult, runsResult, predictionsResult, memoryResult, tradingStatusResult, equityResult, annotatedEquityResult, tradesResult, ledgerResult, learningEvidenceResult, realityCheckResult, pnlBreakdownResult, failuresResult, lessonsResult, benchmarkResult, reproducibilityResult, reasoningStatusResult, survivalResult, convictionResult, reliabilityResult, competitionResult, ensembleResult, benchmarkRelativeResult, trainingQualityResult] = await Promise.allSettled([
        api.learningDashboard(),
        api.learningRuns(20),
        api.learningPredictions(36),
        api.learningMemory(32),
        api.tradingGameStatus(),
        api.tradingGameEquity(240),
        api.tradingGameAnnotatedEquity(360),
        api.tradingGameTrades(80),
        api.tradingGameLedger(120),
        api.tradingGameLearningEvidence(60),
        api.tradingGameRealityCheck(),
        api.tradingGamePnlBreakdown(),
        api.tradingGameFailures(24),
        api.tradingGameLessons(24),
        api.tradingGameBenchmark(),
        api.tradingGameReproducibility(160),
        api.reasoningCoreStatus(),
        api.thesisSurvival(24),
        api.convictionDecay(24),
        api.reliabilityByRegime(24),
        api.thesisCompetitions(16),
        api.ensembleStatus(),
        api.benchmarkRelative(24),
        api.trainingQuality(24)
      ] as const);
      if (!mounted) return;
      if (dashResult.status === "fulfilled") setDashboard(dashResult.value);
      if (runsResult.status === "fulfilled") setRuns(runsResult.value);
      if (predictionsResult.status === "fulfilled") setPredictions(predictionsResult.value);
      if (memoryResult.status === "fulfilled") setMemory(memoryResult.value);
      setTrading({
        status: tradingStatusResult.status === "fulfilled" ? tradingStatusResult.value : null,
        equity: equityResult.status === "fulfilled" ? equityResult.value : [],
        annotatedEquity: annotatedEquityResult.status === "fulfilled" ? annotatedEquityResult.value : null,
        trades: tradesResult.status === "fulfilled" ? tradesResult.value : [],
        ledger: ledgerResult.status === "fulfilled" ? ledgerResult.value : null,
        learningEvidence: learningEvidenceResult.status === "fulfilled" ? learningEvidenceResult.value : null,
        realityCheck: realityCheckResult.status === "fulfilled" ? realityCheckResult.value : null,
        pnlBreakdown: pnlBreakdownResult.status === "fulfilled" ? pnlBreakdownResult.value : null,
        failures: failuresResult.status === "fulfilled" ? failuresResult.value : [],
        lessons: lessonsResult.status === "fulfilled" ? lessonsResult.value : [],
        benchmark: benchmarkResult.status === "fulfilled" ? benchmarkResult.value : null,
        reproducibility: reproducibilityResult.status === "fulfilled" ? reproducibilityResult.value : null
      });
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
      const failed = [dashResult, runsResult, predictionsResult, memoryResult, tradingStatusResult].find(isRejected);
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
  const game = trading?.status?.current_game ?? dashboard?.trading_game?.current_game;
  const equityRows = trading?.equity ?? [];
  const annotatedEquityRows = trading?.annotatedEquity?.equity_curve_points ?? equityRows;
  const equityAnnotations = trading?.annotatedEquity?.annotations ?? [];
  const gameTrades = trading?.trades ?? [];
  const ledgerRows = trading?.ledger?.rows ?? [];
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

      <section className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head">
          <span>Full Trade Ledger</span>
          <strong>{ledgerRows.length} visible / {trading?.ledger?.total ?? 0} total</strong>
        </div>
        <div className="learning-table trade-ledger-table">
          <div className="learning-row trade-ledger-row head"><span>Ticker</span><span>Setup</span><span>Entry</span><span>Exit</span><span>P/L EUR</span><span>P/L %</span><span>R</span><span>Outcome</span><span>Quality</span><span>Excess</span></div>
          {ledgerRows.slice(0, 18).map((row: any) => (
            <button className="learning-row trade-ledger-row clickable" key={row.trade_id} onClick={() => openTrade(row.trade_id)}>
              <strong>{row.ticker}</strong>
              <span>{String(row.setup_type).replaceAll("_", " ")}</span>
              <span>{row.entry_date}<br />{formatNumber(row.entry_price)}</span>
              <span>{row.exit_date ?? "open"}<br />{formatNumber(row.exit_price)}</span>
              <span className={Number(row.net_pnl_eur) >= 0 ? "positive-text" : "negative-text"}>{formatCurrency(row.net_pnl_eur)}</span>
              <span className={Number(row.pnl_percent) >= 0 ? "positive-text" : "negative-text"}>{formatPctRaw(row.pnl_percent)}</span>
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

function formatPctDecimal(value: any) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  return `${(Number(value) * 100).toFixed(2)}%`;
}

function formatPctRaw(value: any) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  return `${Number(value).toFixed(2)}%`;
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

function isRejected(item: PromiseSettledResult<unknown>): item is PromiseRejectedResult {
  return item.status === "rejected";
}
