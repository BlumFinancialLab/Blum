import { Asset, DashboardOverview, RelatedNews, Signal } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
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
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  assets: () => getJson<Asset[]>("/assets"),
  asset: (ticker: string) => getJson<{ asset: Asset; prices: any[]; latest_signal: Signal | null; related_news: RelatedNews[] }>(`/assets/${ticker}`),
  overview: () => getJson<DashboardOverview>("/dashboard/overview"),
  topSignals: (query = "") => getJson<Signal[]>(`/signals/top${query}`),
  signal: (ticker: string) => getJson<Signal>(`/signals/${ticker}`),
  sentiment: (ticker: string) => getJson<any[]>(`/sentiment/${ticker}`),
  explain: (ticker: string) => getJson<any>(`/ai/explain/${ticker}`),
  relatedNews: (ticker: string) => getJson<RelatedNews[]>(`/related-news?ticker=${ticker}`),
  themes: () => getJson<any[]>("/themes"),
  etfTrends: () => getJson<any[]>("/etf-trends"),
  semanticSearch: (query: string) => postJson<any[]>("/semantic-search", { query, limit: 12 }),
  marketUpdate: () => postJson("/market/update", { period: "2y", limit: 36 }),
  newsUpdate: () => postJson("/news/update", { lookback_hours: 72, limit_per_feed: 35 }),
  runSignals: () => postJson("/signals/run", { refresh_prices: false, limit: 36 }),
  backtest: (ticker: string) => postJson<any>(`/backtest/${ticker}`, {})
};

