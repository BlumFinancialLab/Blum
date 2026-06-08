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
};

export type DashboardOverview = {
  market_pulse: {
    asset_count: number;
    article_count: number;
    average_sentiment: number;
    signal_count: number;
    classification_mix: Record<string, number>;
  };
  todays_strongest_signals: Signal[];
  narrative_breakouts: Signal[];
  technical_breakouts: Signal[];
  sentiment_divergence: Signal[];
  watchlist_candidates: Signal[];
  etf_rotation_leaders: Array<{
    ticker: string;
    category: string;
    momentum_score: number;
    thematic_score: number;
    confirmation_score: number;
  }>;
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

