import { AccuracyOverview, AccuracyProfile, Asset, CommunitySentimentPayload, DashboardOverview, DataCoverage, ExecutiveDashboardPayload, IPORadar, LiveNewsArticle, MacroOverview, MarketBrain, MarketBrainHistoryRow, MarketNarrativePayload, MarketSentiment, OpportunityRadarPayload, PipelineStatus, PortfolioScenarioPayload, RelatedNews, Signal, SignalValidationReport, StockRadar, SystemStatus, WatchlistPayload } from "./types";

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
  marketUpdate: () => postJson("/market/update", { period: "max", limit: 36 }),
  newsUpdate: () => postJson("/news/update", { lookback_hours: 72, limit_per_feed: 35 }),
  runSignals: () => postJson("/signals/run", { refresh_prices: false, limit: 36 }),
  runPipeline: () => postJson<any>("/pipeline/run", { refresh_prices: false, limit: 36 }),
  backtest: (ticker: string) => postJson<any>(`/backtest/${ticker}`, {})
};
