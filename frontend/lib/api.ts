import { AccuracyOverview, AccuracyProfile, Asset, BrainAccuracy, BrainAssetMemory, BrainEvaluation, BrainStatus, ChartReport, CommunitySentimentPayload, DashboardOverview, DataCoverage, ExecutiveDashboardPayload, FinancialChatResponse, IPORadar, LiveNewsArticle, MacroOverview, MarketBrain, MarketBrainHistoryRow, MarketNarrativePayload, MarketSentiment, OpportunityRadarPayload, PipelineStatus, PortfolioScenarioPayload, RelatedNews, Signal, SignalValidationReport, StockRadar, SystemStatus, WatchlistPayload } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await responseError(response));
  }
  return response.json() as Promise<T>;
}

async function postJson<T>(path: string, payload: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error(await responseError(response));
  }
  return response.json() as Promise<T>;
}

async function responseError(response: Response) {
  try {
    const payload = await response.json();
    const detail = typeof payload?.detail === "string" ? payload.detail : JSON.stringify(payload?.detail ?? payload);
    return `${response.status} ${response.statusText}: ${detail}`;
  } catch {
    return `${response.status} ${response.statusText}`;
  }
}

export const api = {
  systemStatus: () => getJson<SystemStatus>("/system/status"),
  brainStatus: () => getJson<BrainStatus>("/brain/status"),
  brainAccuracy: () => getJson<BrainAccuracy>("/brain/accuracy"),
  brainLearningEvents: (limit = 50) => getJson<any[]>(`/brain/learning-events?limit=${limit}`),
  brainSignalEvaluations: (limit = 120, ticker?: string) => getJson<BrainEvaluation[]>(`/brain/signal-evaluations?limit=${limit}${ticker ? `&ticker=${encodeURIComponent(ticker)}` : ""}`),
  brainAssetMemory: (ticker: string) => getJson<BrainAssetMemory>(`/brain/asset-memory/${encodeURIComponent(ticker)}`),
  brainConfidenceHistory: (ticker: string) => getJson<any>(`/brain/confidence-history/${encodeURIComponent(ticker)}`),
  evaluateBrainSignals: (limit = 240) => postJson<any>(`/brain/evaluate-signals?limit=${limit}`, {}),
  recalculateBrainWeights: () => postJson<any>("/brain/recalculate-weights", {}),
  runLearningCycle: (limit = 240) => postJson<any>(`/brain/run-learning-cycle?limit=${limit}`, {}),
  learningDashboard: () => getJson<any>("/learning/dashboard"),
  learningRuns: (limit = 50) => getJson<any[]>(`/learning/runs?limit=${limit}`),
  learningPredictions: (limit = 80, ticker?: string) => getJson<any[]>(`/learning/predictions?limit=${limit}${ticker ? `&ticker=${encodeURIComponent(ticker)}` : ""}`),
  learningMemory: (limit = 40) => getJson<any>(`/learning/memory?limit=${limit}`),
  runBlumLearningLoop: (batchSize = 25) => postJson<any>(`/learning/run-cycle?batch_size=${batchSize}`, {}),
  reasoningCoreStatus: () => getJson<any>("/model/reasoning-core/status"),
  reasoningCoreDiagnostics: () => getJson<any>("/model/reasoning-core/diagnostics"),
  thesisSurvival: (limit = 40) => getJson<any>(`/model/thesis-survival?limit=${limit}`),
  convictionDecay: (limit = 40) => getJson<any>(`/model/conviction-decay?limit=${limit}`),
  reliabilityByRegime: (limit = 40) => getJson<any>(`/model/reliability-by-regime?limit=${limit}`),
  thesisCompetitions: (limit = 30) => getJson<any>(`/model/thesis-competitions?limit=${limit}`),
  ensembleStatus: () => getJson<any>("/model/ensemble/status"),
  benchmarkRelative: (limit = 40) => getJson<any>(`/model/benchmark-relative?limit=${limit}`),
  trainingQuality: (limit = 40) => getJson<any>(`/model/training/quality?limit=${limit}`),
  sniperStatus: () => getJson<any>("/api/sniper/status"),
  sniperCandidates: (limit = 40, persist = false) => getJson<any>(`/api/sniper/candidates?limit=${limit}&persist=${persist ? "true" : "false"}`),
  sniperCandidate: (ticker: string, persist = false) => getJson<any>(`/api/sniper/candidates/${encodeURIComponent(ticker)}?persist=${persist ? "true" : "false"}`),
  sniperEvaluate: (limit = 40, tickers?: string) => postJson<any>(`/api/sniper/evaluate?limit=${limit}${tickers ? `&tickers=${encodeURIComponent(tickers)}` : ""}`, {}),
  sniperSimulate: (limit = 120, ticker?: string) => postJson<any>(`/api/sniper/simulate?limit=${limit}${ticker ? `&ticker=${encodeURIComponent(ticker)}` : ""}`, {}),
  sniperSetups: () => getJson<any[]>("/api/sniper/setups"),
  sniperRegimes: (limit = 80) => getJson<any[]>(`/api/sniper/regimes?limit=${limit}`),
  sniperMetrics: () => getJson<any>("/api/sniper/metrics"),
  sniperLessons: (limit = 40) => getJson<any[]>(`/api/sniper/lessons?limit=${limit}`),
  tradingGameStatus: () => getJson<any>("/api/trading-game/status"),
  tradingGameRun: (batchSize = 60) => postJson<any>(`/api/trading-game/run?batch_size=${batchSize}`, {}),
  tradingGameReset: () => postJson<any>("/api/trading-game/reset", {}),
  tradingGameEquity: (limit = 500, gameId?: number) => getJson<any[]>(`/api/trading-game/equity?limit=${limit}${gameId ? `&game_id=${gameId}` : ""}`),
  tradingGameAnnotatedEquity: (limit = 800, gameId?: number) => getJson<any>(`/api/trading-game/equity/annotated?limit=${limit}${gameId ? `&game_id=${gameId}` : ""}`),
  tradingGameTrades: (limit = 200, gameId?: number) => getJson<any[]>(`/api/trading-game/trades?limit=${limit}${gameId ? `&game_id=${gameId}` : ""}`),
  tradingGameLedger: (limit = 200, gameId?: number) => getJson<any>(`/api/trading-game/ledger?limit=${limit}${gameId ? `&game_id=${gameId}` : ""}`),
  tradingGameLedgerSummary: (gameId?: number) => getJson<any>(`/api/trading-game/ledger/summary${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGameLedgerByTicker: (ticker: string, limit = 200) => getJson<any>(`/api/trading-game/ledger/by-ticker/${encodeURIComponent(ticker)}?limit=${limit}`),
  tradingGameLedgerBySetup: (setupType: string, limit = 200) => getJson<any>(`/api/trading-game/ledger/by-setup/${encodeURIComponent(setupType)}?limit=${limit}`),
  tradingGameLedgerByOutcome: (outcomeLabel: string, limit = 200) => getJson<any>(`/api/trading-game/ledger/by-outcome/${encodeURIComponent(outcomeLabel)}?limit=${limit}`),
  tradingGameLedgerByCycle: (cycleId: number, limit = 500) => getJson<any>(`/api/trading-game/ledger/by-cycle/${cycleId}?limit=${limit}`),
  tradingGameTradeDetail: (tradeId: number) => getJson<any>(`/api/trading-game/trades/${tradeId}`),
  tradingGameTradeAttribution: (tradeId: number) => getJson<any[]>(`/api/trading-game/trades/${tradeId}/attribution`),
  tradingGameTradeQuality: (tradeId: number) => getJson<any>(`/api/trading-game/trades/${tradeId}/quality`),
  tradingGameTradePnlBreakdown: (tradeId: number) => getJson<any>(`/api/trading-game/trades/${tradeId}/pnl-breakdown`),
  tradingGameFailures: (limit = 80) => getJson<any[]>(`/api/trading-game/failures?limit=${limit}`),
  tradingGameLessons: (limit = 50) => getJson<any[]>(`/api/trading-game/lessons?limit=${limit}`),
  tradingGameBenchmark: (gameId?: number) => getJson<any>(`/api/trading-game/benchmark${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGameReproducibility: (limit = 120) => getJson<any>(`/api/trading-game/reproducibility?limit=${limit}`),
  tradingGameLearningEvidence: (limit = 120) => getJson<any>(`/api/trading-game/learning-evidence?limit=${limit}`),
  tradingGameRealityCheck: (gameId?: number) => getJson<any>(`/api/trading-game/reality-check${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGamePnlBreakdown: (gameId?: number) => getJson<any>(`/api/trading-game/pnl-breakdown${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGameCycles: (limit = 100, gameId?: number) => getJson<any>(`/api/trading-game/cycles?limit=${limit}${gameId ? `&game_id=${gameId}` : ""}`),
  tradingGameCurrentCycle: (gameId?: number) => getJson<any>(`/api/trading-game/cycles/current${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGameCycleStats: (gameId?: number) => getJson<any>(`/api/trading-game/cycles/stats${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGameCycleDetail: (cycleId: number) => getJson<any>(`/api/trading-game/cycles/${cycleId}`),
  tradingGameCycleReset: (gameId?: number) => postJson<any>(`/api/trading-game/cycles/reset${gameId ? `?game_id=${gameId}` : ""}`, {}),
  tradingGameIntelligenceMetrics: (gameId?: number) => getJson<any>(`/api/trading-game/intelligence-metrics${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGameIntelligenceRolling: (gameId?: number) => getJson<any>(`/api/trading-game/intelligence-metrics/rolling${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGameIntelligenceBySetup: (gameId?: number) => getJson<any>(`/api/trading-game/intelligence-metrics/by-setup${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGameIntelligenceByRegime: (gameId?: number) => getJson<any>(`/api/trading-game/intelligence-metrics/by-regime${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGameIntelligenceBySector: (gameId?: number) => getJson<any>(`/api/trading-game/intelligence-metrics/by-sector${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGameIntelligenceByCycle: (gameId?: number) => getJson<any>(`/api/trading-game/intelligence-metrics/by-cycle${gameId ? `?game_id=${gameId}` : ""}`),
  tradingGameHistoricalVsLive: () => getJson<any>("/api/trading-game/historical-vs-live"),
  liveTradingGameStatus: () => getJson<any>("/api/live-trading-game/status"),
  liveTradingGameRunCycle: () => postJson<any>("/api/live-trading-game/run-cycle", {}),
  liveTradingGamePositions: () => getJson<any>("/api/live-trading-game/positions"),
  liveTradingGameTrades: () => getJson<any>("/api/live-trading-game/trades"),
  liveTradingGameLedger: (limit = 200) => getJson<any>(`/api/live-trading-game/ledger?limit=${limit}`),
  liveTradingGameEquity: () => getJson<any>("/api/live-trading-game/equity"),
  liveTradingGameMetrics: () => getJson<any>("/api/live-trading-game/metrics"),
  liveTradingGameCompareHistorical: () => getJson<any>("/api/live-trading-game/compare-historical"),
  learningIntelligenceDashboard: () => getJson<any>("/api/learning-intelligence/dashboard"),
  learningTradingPower: () => getJson<any>("/api/learning-intelligence/trading-power"),
  recalculateLearningTradingPower: () => postJson<any>("/api/learning-intelligence/trading-power/recalculate", {}),
  learningBenchmarks: () => getJson<any>("/api/learning-intelligence/benchmarks"),
  learningBenchmark: (benchmarkName: string) => getJson<any>(`/api/learning-intelligence/benchmarks/${encodeURIComponent(benchmarkName)}`),
  recalculateLearningBenchmarks: () => postJson<any>("/api/learning-intelligence/benchmarks/recalculate", {}),
  learningProgress: () => getJson<any>("/api/learning-intelligence/progress"),
  learningProgressRolling: () => getJson<any>("/api/learning-intelligence/progress/rolling"),
  learningProgressBySetup: () => getJson<any>("/api/learning-intelligence/progress/by-setup"),
  learningProgressByRegime: () => getJson<any>("/api/learning-intelligence/progress/by-regime"),
  learningWeaknessMap: () => getJson<any>("/api/learning-intelligence/weakness-map"),
  learningWeaknessBySetup: () => getJson<any>("/api/learning-intelligence/weakness-map/by-setup"),
  learningWeaknessByRegime: () => getJson<any>("/api/learning-intelligence/weakness-map/by-regime"),
  learningWeaknessBySector: () => getJson<any>("/api/learning-intelligence/weakness-map/by-sector"),
  learningWeaknessByEngine: () => getJson<any>("/api/learning-intelligence/weakness-map/by-engine"),
  learningSelfImprovementActions: (limit = 80) => getJson<any>(`/api/learning-intelligence/self-improvement/actions?limit=${limit}`),
  generateLearningSelfImprovement: () => postJson<any>("/api/learning-intelligence/self-improvement/generate", {}),
  applyLearningSelfImprovement: (actionId: number) => postJson<any>(`/api/learning-intelligence/self-improvement/apply/${actionId}`, {}),
  evaluateLearningSelfImprovement: (actionId: number) => postJson<any>(`/api/learning-intelligence/self-improvement/evaluate/${actionId}`, {}),
  decisionIntelligenceDashboard: () => getJson<any>("/api/decision-intelligence/dashboard"),
  decisionSuperiority: () => getJson<any>("/api/decision-intelligence/superiority"),
  recalculateDecisionSuperiority: () => postJson<any>("/api/decision-intelligence/superiority/recalculate", {}),
  decisionUniverseSnapshots: () => getJson<any>("/api/decision-intelligence/universe-snapshots"),
  recalculateDecisionUniverseSnapshots: () => postJson<any>("/api/decision-intelligence/universe-snapshots/recalculate", {}),
  missedOpportunities: () => getJson<any>("/api/decision-intelligence/missed-opportunities"),
  businessQualityDashboard: () => getJson<any>("/api/business-quality/dashboard"),
  businessQualityScores: (limit = 80) => getJson<any>(`/api/business-quality/scores?limit=${limit}`),
  recalculateBusinessQuality: (limit = 80) => postJson<any>(`/api/business-quality/recalculate?limit=${limit}`, {}),
  portfolioIntelligenceDashboard: () => getJson<any>("/api/portfolio-intelligence/dashboard"),
  portfolioQuality: () => getJson<any>("/api/portfolio-intelligence/quality"),
  recalculatePortfolioIntelligence: () => postJson<any>("/api/portfolio-intelligence/recalculate", {}),
  chartAnalyzeTicker: (ticker: string, timeframe = "6M", period = "1y", includeVisual = false) => getPostChart<ChartReport>(`/chart/analyze-ticker?ticker=${encodeURIComponent(ticker)}&timeframe=${encodeURIComponent(timeframe)}&period=${encodeURIComponent(period)}&include_visual=${includeVisual ? "true" : "false"}`),
  chartTechnicalReport: (ticker: string, timeframe = "6M") => getJson<ChartReport>(`/chart/technical-report/${encodeURIComponent(ticker)}?timeframe=${encodeURIComponent(timeframe)}`),
  chartLevels: (ticker: string, timeframe = "6M") => getJson<any>(`/chart/levels/${encodeURIComponent(ticker)}?timeframe=${encodeURIComponent(timeframe)}`),
  chartSignals: (ticker: string, timeframe = "6M") => getJson<any[]>(`/chart/signals/${encodeURIComponent(ticker)}?timeframe=${encodeURIComponent(timeframe)}`),
  chartHistory: (ticker: string, limit = 30) => getJson<any[]>(`/chart/history/${encodeURIComponent(ticker)}?limit=${limit}`),
  assets: () => getJson<Asset[]>("/assets"),
  asset: (ticker: string) => getJson<{ asset: Asset; market_snapshot: Asset["market_snapshot"]; prices: any[]; latest_signal: Signal | null; related_news: RelatedNews[] }>(`/assets/${encodeURIComponent(ticker)}`),
  overview: () => getJson<DashboardOverview>("/dashboard/overview"),
  liveNews: (limit = 60) => getJson<LiveNewsArticle[]>(`/news/live?limit=${limit}`),
  marketSentiment: (hours = 48) => getJson<MarketSentiment>(`/sentiment/market?hours=${hours}`),
  dataCoverage: () => getJson<DataCoverage>("/data/coverage"),
  repairData: (limit = 36) => postJson<any>(`/data/repair?limit=${limit}`, {}),
  accuracyOverview: () => getJson<AccuracyOverview>("/accuracy/overview"),
  runAccuracy: (limit = 80) => postJson<any>(`/accuracy/run?limit=${limit}`, {}),
  assetAccuracy: (ticker: string) => getJson<AccuracyProfile>(`/accuracy/${encodeURIComponent(ticker)}`),
  signalValidation: (limit = 240) => getJson<SignalValidationReport>(`/validation/signals?limit=${limit}`),
  macroOverview: () => getJson<MacroOverview>("/macro/overview"),
  updateMacro: () => postJson<any>("/macro/update", {}),
  updateFundamentals: (limit = 24) => postJson<any>(`/fundamentals/update?limit=${limit}`, {}),
  fundamentals: (ticker: string) => getJson<any>(`/fundamentals/${encodeURIComponent(ticker)}`),
  executiveDashboard: () => getJson<ExecutiveDashboardPayload>("/intelligence/executive"),
  opportunityRadar: (limit = 30) => getJson<OpportunityRadarPayload>(`/intelligence/opportunities?limit=${limit}`),
  marketNarrative: () => getJson<MarketNarrativePayload>("/intelligence/narrative"),
  communitySentiment: () => getJson<CommunitySentimentPayload>("/intelligence/community"),
  watchlist: () => getJson<WatchlistPayload>("/intelligence/watchlist"),
  addWatchlist: (ticker: string, thesis = "") => postJson<WatchlistPayload>(`/intelligence/watchlist/${encodeURIComponent(ticker)}?thesis=${encodeURIComponent(thesis)}`, {}),
  portfolioScenario: (riskProfile = "balanced") => getJson<PortfolioScenarioPayload>(`/intelligence/portfolio-scenario?risk_profile=${encodeURIComponent(riskProfile)}`),
  intelligenceReport: (ticker: string) => getJson<any>(`/intelligence/reports/${encodeURIComponent(ticker)}`),
  similarBacktest: (ticker: string) => getJson<any>(`/intelligence/backtest/${encodeURIComponent(ticker)}`),
  pipelineStatus: () => getJson<PipelineStatus>("/pipeline/status"),
  topSignals: (query = "") => getJson<Signal[]>(`/signals/top${query}`),
  signal: (ticker: string) => getJson<Signal>(`/signals/${ticker}`),
  sentiment: (ticker: string) => getJson<any[]>(`/sentiment/${ticker}`),
  explain: (ticker: string) => getJson<any>(`/ai/explain/${ticker}`),
  relatedNews: (ticker: string) => getJson<RelatedNews[]>(`/related-news?ticker=${ticker}`),
  themes: () => getJson<any[]>("/themes"),
  themeDetail: (label: string) => getJson<any>(`/themes/${encodeURIComponent(label)}`),
  etfTrends: () => getJson<any[]>("/etf-trends"),
  stockRadar: (limit = 80) => getJson<StockRadar>(`/stock-radar?limit=${limit}`),
  updateStockRadar: (limit = 36) => postJson<any>(`/stock-radar/update?limit=${limit}`, {}),
  ipoRadar: (limit = 80) => getJson<IPORadar>(`/ipo-radar?limit=${limit}`),
  updateIpoRadar: (limitPerForm = 50) => postJson<any>(`/ipo-radar/update?limit_per_form=${limitPerForm}`, {}),
  secSubmissions: (cik: string, persist = false) => getJson<any>(`/ipo-radar/sec-submissions/${cik}?persist=${persist ? "true" : "false"}`),
  marketBrain: () => getJson<MarketBrain>("/market-brain"),
  marketBrainHistory: (limit = 20) => getJson<MarketBrainHistoryRow[]>(`/market-brain/history?limit=${limit}`),
  runMarketBrain: (refreshPipeline = false) => postJson<MarketBrain>(`/market-brain/run?refresh_pipeline=${refreshPipeline ? "true" : "false"}&refresh_sec=true`, {}),
  modelStatus: () => getJson<any>("/ai/models/status"),
  semanticSearch: (query: string) => postJson<any[]>("/semantic-search", { query, limit: 12 }),
  financialChat: (payload: { message: string; tickers?: string[]; horizon?: string; risk_profile?: string; include_semantic_search?: boolean; language?: string; session_id?: string; mode?: string }) =>
    postJson<FinancialChatResponse>("/api/chat", payload),
  financialChatContext: () => getJson<any>("/api/chat/context"),
  financialChatHistory: (limit = 80) => getJson<any[]>(`/api/chat/history?limit=${limit}`),
  marketUpdate: () => postJson("/market/update", { period: "max", limit: 36 }),
  newsUpdate: () => postJson("/news/update", { lookback_hours: 72, limit_per_feed: 35 }),
  runSignals: () => postJson("/signals/run", { refresh_prices: false, limit: 36 }),
  runPipeline: () => postJson<any>("/pipeline/run", { refresh_prices: false, limit: 36 }),
  backtest: (ticker: string) => postJson<any>(`/backtest/${ticker}`, {})
};

function getPostChart<T>(path: string): Promise<T> {
  return postJson<T>(path, {});
}
