export type Asset = {
  ticker: string;
  name: string;
  category: string;
  sector: string;
  industry: string;
  country: string;
  asset_type: string;
  currency: string;
  exchange: string;
  description: string;
  market_snapshot?: MarketSnapshot;
};

export type MarketSnapshot = {
  ticker: string;
  currency: string;
  data_status: string;
  price: number | null;
  date: string | null;
  volume: number | null;
  provider: string | null;
  perf_1d: number | null;
  perf_5d: number | null;
  perf_1m: number | null;
};

export type Signal = {
  ticker: string;
  classification: string;
  blum_score: number;
  risk_level: string;
  time_horizon: string;
  score_breakdown: Record<string, number>;
  technical_summary?: Record<string, number | string | boolean | null>;
  narrative_summary?: Record<string, number | string | boolean | null>;
  explanation: string;
  watch_points: { items?: string[] };
  created_at: string;
  asset?: Asset;
  market_snapshot?: MarketSnapshot;
};

export type DashboardOverview = {
  market_pulse: {
    asset_count: number;
    article_count: number;
    average_sentiment: number;
    signal_count: number;
    price_row_count: number;
    classification_mix: Record<string, number>;
  };
  readiness: {
    price_row_count: number;
    news_article_count: number;
    signal_count: number;
    price_providers: Array<{ provider: string; rows: number }>;
  };
  realtime: PipelineStatus;
  todays_strongest_signals: Signal[];
  narrative_breakouts: Signal[];
  technical_breakouts: Signal[];
  sentiment_divergence: Signal[];
  watchlist_candidates: Signal[];
  etf_rotation_leaders: Array<{
    ticker: string;
    category: string;
    asset?: Asset;
    market_snapshot?: MarketSnapshot;
    momentum_score: number;
    thematic_score: number;
    confirmation_score: number;
  }>;
};

export type PipelineStatus = {
  started: boolean;
  running: boolean;
  last_started_at: string | null;
  last_completed_at: string | null;
  last_job: string | null;
  last_status: string;
  last_error: string;
  last_result: Record<string, any>;
};

export type SentimentPayload = {
  model_name: string;
  label: string;
  score: number;
  confidence: number;
  baseline_vader?: number | null;
};

export type LiveNewsArticle = {
  id: number;
  title: string;
  summary: string;
  source: string;
  published_at: string | null;
  url: string;
  quality_score: number;
  theme_tags: { themes?: string[]; desk?: string; tier?: number };
  sentiment: SentimentPayload | null;
  linked_assets: Array<{ ticker: string; name: string; sector: string; relevance_score: number }>;
};

export type MarketSentiment = {
  window_hours: number;
  article_count: number;
  average_sentiment: number;
  label_counts: Record<string, number>;
  models: Record<string, number>;
  themes: Array<{ theme: string; headline_count: number; avg_sentiment: number }>;
};

export type PricePoint = {
  date: string;
  open?: number;
  high?: number;
  low?: number;
  close: number;
  volume?: number;
};

export type RelatedNews = {
  id: number;
  title: string;
  summary: string;
  source: string;
  published_at: string | null;
  url: string;
  quality_score: number;
  theme_tags: { themes?: string[] };
  relevance_score?: number;
};
