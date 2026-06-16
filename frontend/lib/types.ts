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

export type OpportunityRow = {
  rank: number;
  module: string;
  ticker: string;
  name: string;
  sector: string;
  asset_type: string;
  last_price: number | null;
  currency?: string | null;
  change_percent: number | null;
  volume_relative: number;
  opportunity_score: number;
  trend_score: number;
  momentum_score: number;
  sentiment_score: number;
  news_score: number;
  risk_score: number;
  status_label: string;
  why_today: string;
  watch_points: string[];
  classification: string;
  risk_level: string;
  data_status: string;
};

export type OpportunityRadarPayload = {
  status: string;
  data_mode: string;
  rows: OpportunityRow[];
  sector_rotation: Array<{ sector: string; average_opportunity: number; average_risk: number; leaders: string[] }>;
  methodology: Record<string, any>;
  disclaimer: string;
};

export type MarketNarrativePayload = {
  dominant_theme: { theme: string; headline_count: number; avg_sentiment: number };
  emerging_subthemes: Array<{ theme: string; headline_count: number; avg_sentiment: number }>;
  beneficiary_sectors: string[];
  linked_assets: string[];
  macro_risks: string[];
  contrary_signals: string[];
  market_mood: string;
  operating_summary: string;
  synthesis: string;
  data_mode: string;
  disclaimer: string;
};

export type CommunitySentimentPayload = {
  data_mode: string;
  themes_rising: Array<{ theme: string; headline_count: number; avg_sentiment: number }>;
  themes_falling: Array<{ theme: string; headline_count: number; avg_sentiment: number }>;
  most_discussed_assets: Array<{ ticker: string; discussion_count: number; hype_bubble_risk: string }>;
  average_sentiment: number;
  possible_hype_bubbles: Array<{ ticker: string; discussion_count: number; hype_bubble_risk: string }>;
  rank_change_policy: string;
  disclaimer: string;
};

export type PortfolioScenarioPayload = {
  scenario_name: string;
  risk_profile: string;
  time_horizon: string;
  allocation: Array<{ bucket: string; weight: number; leaders: string[]; rationale: string }>;
  rationale: string[];
  monitor: string[];
  defensive_alternative: Array<{ bucket: string; weight: number; leaders: string[]; rationale: string }>;
  data_mode: string;
  disclaimer: string;
};

export type WatchlistPayload = {
  status: string;
  items: Array<Record<string, any>>;
  suggested_items?: OpportunityRow[];
  alerts: Array<{ ticker: string; message: string; severity?: string }>;
  disclaimer: string;
};

export type ExecutiveDashboardPayload = {
  title: string;
  generated_at: string;
  data_mode: string;
  market_mood: string;
  dominant_narrative: { theme: string; headline_count: number; avg_sentiment: number };
  risk_level: string;
  top_opportunities_today: OpportunityRow[];
  sector_rotation: Array<{ sector: string; average_opportunity: number; average_risk: number; leaders: string[] }>;
  watchlist_alerts: Array<{ ticker: string; message: string; severity?: string }>;
  best_ai_reports: Array<Record<string, any>>;
  last_backtests: Array<Record<string, any>>;
  narrative: MarketNarrativePayload;
  community_sentiment: CommunitySentimentPayload;
  portfolio_scenario: PortfolioScenarioPayload;
  disclaimer: string;
};

export type SystemStatus = {
  service: string;
  app_version: string;
  feature_set: string;
  environment: string;
  generated_at: string;
  hugging_face: {
    space_id?: string | null;
    space_author?: string | null;
    space_repo?: string | null;
    commit_sha?: string | null;
  };
  runtime_flags: {
    model_loading_enabled: boolean;
    financial_brain_model_enabled: boolean;
    live_startup_enabled: boolean;
    yfinance_fallback_enabled?: boolean;
    historical_price_seed_enabled?: boolean;
    startup_signal_seed_enabled?: boolean;
    startup_accuracy_seed_enabled?: boolean;
    data_gap_repair_minutes?: number;
    accuracy_audit_minutes?: number;
    fundamentals_refresh_minutes?: number;
    macro_refresh_minutes?: number;
  };
  active_models: {
    finbert: string;
    embeddings: string;
    reasoning_llm: string;
    financial_brain_configured: string;
    financial_brain_runtime: {
      configured_model: string;
      enabled: boolean;
      load_policy: string;
      purpose: string;
    };
  };
  feature_visibility: Record<string, boolean>;
  database_counts: Record<string, number>;
  why_gui_can_look_unchanged: string[];
};

export type BrainPerformanceRow = {
  key: string;
  mature_count: number;
  success_rate: number | null;
  neutral_rate: number | null;
  average_return: number | null;
  average_drawdown: number | null;
  accuracy_score: number;
};

export type BrainStatus = {
  name: string;
  generated_at: string;
  learning_state: string;
  scheduler_enabled: boolean;
  learning_interval_minutes: number;
  signals_evaluated: number;
  mature_evaluations: number;
  pending_evaluations: number;
  historical_accuracy: number | null;
  success_rate_7d: number | null;
  success_rate_30d: number | null;
  confidence_calibration: Record<string, any>;
  best_performing_signal_types: BrainPerformanceRow[];
  weakest_signal_types: BrainPerformanceRow[];
  data_quality_score: number;
  model_drift_warning: { status: string; severity: string; message: string };
  active_weight_version: Record<string, any> | null;
  governance: string[];
  disclaimer: string;
};

export type BrainEvaluation = {
  id: number;
  signal_id?: number | null;
  ticker: string;
  sector: string;
  signal_type: string;
  expected_direction: string;
  time_horizon: string;
  horizon_days: number;
  signal_created_at: string;
  initial_confidence: number;
  initial_sentiment: number;
  initial_momentum: number;
  news_evidence: Record<string, any>;
  price_at_signal: number | null;
  price_after_horizon: number | null;
  max_drawdown: number | null;
  max_upside: number | null;
  realized_return: number | null;
  volatility_after_signal: number | null;
  outcome: string;
  explanation_quality_score: number;
  data_quality_score: number;
  evaluation_payload: Record<string, any>;
  created_at: string;
  updated_at: string;
};

export type BrainAssetMemory = {
  ticker: string;
  generated_at: string;
  learning_state: string;
  latest_signal: Record<string, any> | null;
  blum_memory_summary: string;
  historical_similarity: {
    similar_cases_found: number;
    average_return: number | null;
    success_rate: number | null;
    average_drawdown: number | null;
    confidence_adjustment: number;
    explanation: string;
  };
  similar_historical_setups: Array<Record<string, any>>;
  confidence_evolution: Array<Record<string, any>>;
  signal_outcome_history: BrainEvaluation[];
  why_confidence_changed: string[];
  what_blum_learned: string[];
  governance_note: string;
  disclaimer: string;
};

export type BrainAccuracy = {
  generated_at: string;
  historical_accuracy: number | null;
  success_rate_7d: number | null;
  success_rate_30d: number | null;
  confidence_calibration: Record<string, any>;
  by_signal_type: BrainPerformanceRow[];
  by_sector: BrainPerformanceRow[];
  ticker_profiles: Array<Record<string, any>>;
  sector_profiles: Array<Record<string, any>>;
  source_reliability: Array<Record<string, any>>;
  disclaimer: string;
};

export type Signal = {
  ticker: string;
  classification: string;
  blum_score: number;
  risk_level: string;
  time_horizon: string;
  score_version?: string;
  confidence_score?: number;
  lifecycle_state?: string;
  score_breakdown: Record<string, number>;
  technical_summary?: Record<string, number | string | boolean | null>;
  narrative_summary?: Record<string, number | string | boolean | null>;
  explanation: string;
  watch_points: { items?: string[] };
  created_at: string;
  asset?: Asset;
  market_snapshot?: MarketSnapshot;
  accuracy?: AccuracySnapshot | null;
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
  data_coverage?: DataCoverage;
  accuracy?: AccuracyOverview;
  macro?: MacroOverview;
  validation?: SignalValidationReport;
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

export type AccuracyIssue = {
  code: string;
  message: string;
  severity: string;
};

export type AccuracySnapshot = {
  id?: number;
  ticker?: string | null;
  scope?: string;
  blum_confidence_score: number;
  confidence_label: string;
  components?: Record<string, any>;
  issues?: AccuracyIssue[] | Record<string, number>;
  created_at?: string | null;
};

export type AccuracyProfile = {
  ticker: string;
  name: string;
  asset_type: string;
  sector: string;
  blum_confidence_score: number;
  confidence_label: string;
  components: Record<string, any>;
  issues: AccuracyIssue[];
  generated_at: string;
  accuracy_contract: string[];
  latest_persisted_snapshot?: AccuracySnapshot | null;
};

export type AccuracyOverview = {
  scope: string;
  blum_confidence_score: number;
  confidence_label: string;
  asset_count: number;
  top_quality_assets: AccuracyProfile[];
  lowest_quality_assets: AccuracyProfile[];
  issue_counts: Record<string, number>;
  coverage: DataCoverage;
  accuracy_contract: string[];
};

export type MacroOverview = {
  provider: string;
  series_count: number;
  indicators: Array<{
    indicator: string;
    latest_date: string | null;
    latest_value: number | null;
    observations: number;
    description?: string;
  }>;
};

export type SignalValidationReport = {
  status: string;
  validated_signals: number;
  validation_score?: number;
  confirmed_or_strengthening?: number;
  weakening_or_failed?: number;
  by_classification: Record<string, { count: number; avg_score: number; avg_confidence: number }>;
  by_lifecycle: Record<string, number>;
  message?: string;
  methodology?: string;
};

export type DataCoverage = {
  data_policy: string;
  learning_mode: string;
  minimum_history_rows: number;
  stale_price_max_age_days: number;
  asset_count: number;
  ready_assets: number;
  stale_assets: number;
  missing_assets: number;
  short_history_assets: number;
  coverage_ratio: number;
  repair_candidates: string[];
  assets: Array<{
    ticker: string;
    name: string;
    asset_type: string;
    sector: string;
    country: string;
    rows: number;
    first_date: string | null;
    last_date: string | null;
    age_days: number | null;
    status: string;
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
  theme_tags: { themes?: string[]; events?: string[]; desk?: string; tier?: number; source_reliability?: string };
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

export type StockRadarSignal = {
  classification: string;
  blum_score: number;
  risk_level: string;
  time_horizon: string;
  score_version?: string;
  confidence_score?: number;
  lifecycle_state?: string;
  score_breakdown: Record<string, number>;
  created_at: string;
};

export type StockRadarRow = {
  ticker: string;
  asset: Asset;
  market_snapshot: MarketSnapshot;
  signal: StockRadarSignal | null;
  factor_scores?: Record<string, number>;
  technical_flags?: Record<string, number | string | boolean | null>;
  narrative_flags?: Record<string, number | string | boolean | null>;
  research_priority: string;
  radar_tags: string[];
  why_watch: string;
};

export type StockRadar = {
  status: string;
  summary: {
    stock_count: number;
    signal_count: number;
    missing_signal_count: number;
    priced_count: number;
    average_score: number;
    top_score: number;
    high_risk_count: number;
    positive_1d_count: number;
  };
  sections: Record<string, StockRadarRow[]>;
  sector_leaders: Array<{
    sector: string;
    asset_count: number;
    average_score: number;
    leader: string;
    leader_score: number;
    leader_price: MarketSnapshot;
  }>;
  rows: StockRadarRow[];
  data_gaps: StockRadarRow[];
};

export type IPORadarRow = {
  company: {
    id: number;
    name: string;
    cik?: string | null;
    ticker?: string | null;
    exchange?: string | null;
    country: string;
    sector: string;
    industry: string;
    status: string;
    metadata: Record<string, any>;
    first_seen_at: string;
    last_seen_at: string;
  };
  latest_filing: {
    form_type: string;
    filing_date: string | null;
    title: string;
    url: string;
    accession_number: string;
    source: string;
  } | null;
  score: {
    readiness_score: number;
    listing_probability_score: number;
    narrative_heat_score: number;
    valuation_risk_score: number;
    quality_score: number;
    opportunity_score: number;
    classification: string;
    time_horizon: string;
    evidence: Record<string, any>;
    explanation: string;
    created_at: string;
  };
};

export type IPORadar = {
  status: string;
  data_mode: string;
  summary: {
    companies_observed: number;
    filings_observed: number;
    scored_companies: number;
    avg_opportunity_score: number;
    top_opportunity_score: number;
    final_prospectus_count: number;
    advanced_filing_count: number;
    narrative_watch_count: number;
    latest_filing_at: string | null;
  };
  sections: Record<string, IPORadarRow[]>;
  rows: IPORadarRow[];
  prelisting_narratives: RelatedNews[];
  source_diagnostics: Record<string, any>;
};

export type MarketBrain = {
  run_id: string;
  created_at: string;
  data_mode: string;
  brain_score: number;
  regime: string;
  horizon: string;
  summary: string;
  market_now: {
    average_sentiment: number;
    news_count_48h: number;
    signal_count: number;
    asset_count: number;
    classification_mix: Record<string, number>;
    top_themes: Array<{ theme: string; headline_count: number; avg_sentiment: number }>;
    top_live_news: LiveNewsArticle[];
  };
  opportunity_stack: {
    stock_research_priorities: any[];
    etf_rotation_leaders: any[];
    ipo_watch: any[];
    narrative_breakouts: any[];
    technical_breakouts: any[];
    sentiment_divergence: any[];
  };
  forward_scenarios: Array<{
    name: string;
    probability_proxy: number;
    time_horizon: string;
    drivers: string[];
    watch_points: string[];
    evidence: Record<string, any>;
  }>;
  risk_alerts: Array<{ severity: string; title: string; detail: string; tickers: string[] }>;
  contradictions: Array<{ type: string; severity: string; ticker: string; title: string; evidence: Record<string, any> }>;
  event_graph: {
    nodes: Array<{ id: string; label: string; type: string; score?: number | null }>;
    edges: Array<{ source: string; target: string; relationship: string; weight: number }>;
  };
  evidence_ledger: Record<string, number | string>;
  change_log: Array<{ type: string; severity: string; message: string; previous?: any; current?: any }>;
  financial_brain: {
    model_name?: string;
    configured_model?: string;
    model_status?: string;
    thesis?: string;
    regime_interpretation?: Record<string, any>;
    opportunity_hypotheses?: Array<Record<string, any>>;
    risk_hypotheses?: Array<Record<string, any>>;
    contradictions_to_resolve?: Array<Record<string, any>>;
    monitoring_plan?: Array<Record<string, any>>;
    confidence?: Record<string, any>;
    limitations?: string[];
    evidence_policy?: string;
  };
  model_stack: Record<string, string>;
  disclaimer: string;
  update_diagnostics?: Record<string, any>;
};

export type MarketBrainHistoryRow = {
  run_id: string;
  created_at: string;
  brain_score: number;
  regime: string;
  summary: string;
  risk_alert_count: number;
  contradiction_count: number;
  top_stock?: string | null;
  top_etf?: string | null;
  top_ipo?: string | null;
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
  theme_tags: { themes?: string[]; events?: string[]; desk?: string; tier?: number; source_reliability?: string };
  relevance_score?: number;
};
