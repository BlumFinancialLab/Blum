from functools import lru_cache
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Blum AI Financial Intelligence"
    app_version: str = "2.1.0"
    environment: str = Field(default="demo", alias="ENVIRONMENT")
    database_url: str = Field(
        default="postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/blum",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://127.0.0.1:6379/0", alias="REDIS_URL")
    cors_origins: str = Field(default="*", alias="CORS_ORIGINS")
    enable_model_loading: bool = Field(default=True, alias="BLUM_ENABLE_MODEL_LOADING")
    finbert_model: str = Field(default="ProsusAI/finbert", alias="BLUM_FINBERT_MODEL")
    embedding_model: str = Field(default="sentence-transformers/all-MiniLM-L6-v2", alias="BLUM_EMBEDDING_MODEL")
    llm_model: str = Field(default="Qwen/Qwen2.5-0.5B-Instruct", alias="BLUM_LLM_MODEL")
    enable_financial_brain_model: bool = Field(default=False, alias="BLUM_ENABLE_FINANCIAL_BRAIN_MODEL")
    financial_brain_model: str = Field(default="AdaptLLM/finance-chat", alias="BLUM_FINANCIAL_BRAIN_MODEL")
    financial_brain_max_new_tokens: int = Field(default=420, alias="BLUM_FINANCIAL_BRAIN_MAX_NEW_TOKENS")
    chart_vision_model: str = Field(default="Qwen/Qwen3-VL", alias="CHART_VISION_MODEL")
    chart_vision_fallback_model: str = Field(default="OpenGVLab/InternVL3", alias="CHART_VISION_FALLBACK_MODEL")
    chart_vision_mode: str = Field(default="disabled", alias="CHART_VISION_MODE")
    chart_vision_remote_url: str = Field(default="", alias="CHART_VISION_REMOTE_URL")
    chart_vision_remote_token: str = Field(default="", alias="CHART_VISION_REMOTE_TOKEN")
    chart_vision_min_confidence: float = Field(default=0.70, alias="CHART_VISION_MIN_CONFIDENCE")
    default_benchmark: str = Field(default="SPY", alias="BLUM_DEFAULT_BENCHMARK")
    enable_yfinance_fallback: bool = Field(default=False, alias="BLUM_ENABLE_YFINANCE_FALLBACK")
    max_update_assets: int = Field(default=160, alias="BLUM_MAX_UPDATE_ASSETS")
    enable_live_startup: bool = Field(default=True, alias="BLUM_ENABLE_LIVE_STARTUP")
    enable_autonomous_engine: bool = Field(default=True, alias="BLUM_ENABLE_AUTONOMOUS_ENGINE")
    startup_run_full_autonomous: bool = Field(default=False, alias="BLUM_STARTUP_RUN_FULL_AUTONOMOUS")
    blum_autonomous_max_seconds_per_job: int = Field(default=120, alias="BLUM_AUTONOMOUS_MAX_SECONDS_PER_JOB")
    blum_autonomous_max_items_per_job: int = Field(default=50, alias="BLUM_AUTONOMOUS_MAX_ITEMS_PER_JOB")
    autonomous_cycle_minutes: int = Field(default=20, alias="BLUM_AUTONOMOUS_CYCLE_MINUTES")
    autonomous_repair_limit: int = Field(default=80, alias="BLUM_AUTONOMOUS_REPAIR_LIMIT")
    seed_historical_prices_on_startup: bool = Field(default=True, alias="BLUM_SEED_HISTORICAL_PRICES_ON_STARTUP")
    seed_signals_on_startup: bool = Field(default=True, alias="BLUM_SEED_SIGNALS_ON_STARTUP")
    seed_accuracy_on_startup: bool = Field(default=True, alias="BLUM_SEED_ACCURACY_ON_STARTUP")
    startup_pipeline_limit: int = Field(default=160, alias="BLUM_STARTUP_PIPELINE_LIMIT")
    news_refresh_minutes: int = Field(default=10, alias="BLUM_NEWS_REFRESH_MINUTES")
    market_refresh_minutes: int = Field(default=45, alias="BLUM_MARKET_REFRESH_MINUTES")
    data_gap_repair_minutes: int = Field(default=180, alias="BLUM_DATA_GAP_REPAIR_MINUTES")
    accuracy_audit_minutes: int = Field(default=240, alias="BLUM_ACCURACY_AUDIT_MINUTES")
    enable_learning_loop: bool = Field(default=True, validation_alias=AliasChoices("LEARNING_LOOP_ENABLED", "BLUM_ENABLE_LEARNING_LOOP"))
    learning_loop_minutes: int = Field(default=360, validation_alias=AliasChoices("LEARNING_LOOP_MINUTES", "BLUM_LEARNING_LOOP_MINUTES"))
    learning_batch_size: int = Field(default=100, alias="LEARNING_BATCH_SIZE")
    learning_max_daily_runs: int = Field(default=5000, alias="LEARNING_MAX_DAILY_RUNS")
    learning_random_seed: str = Field(default="", alias="LEARNING_RANDOM_SEED")
    learning_min_history_years: int = Field(default=3, alias="LEARNING_MIN_HISTORY_YEARS")
    learning_asset_universe: str = Field(default="stocks,etfs", alias="LEARNING_ASSET_UNIVERSE")
    learning_evaluation_mode: str = Field(default="walk_forward", alias="LEARNING_EVALUATION_MODE")
    learning_random_sample_ratio: float = Field(default=0.40, alias="LEARNING_RANDOM_SAMPLE_RATIO")
    learning_alpha_loss_sample_ratio: float = Field(default=0.30, alias="LEARNING_ALPHA_LOSS_SAMPLE_RATIO")
    learning_factor_focus_sample_ratio: float = Field(default=0.20, alias="LEARNING_FACTOR_FOCUS_SAMPLE_RATIO")
    learning_capital_preservation_sample_ratio: float = Field(default=0.10, alias="LEARNING_CAPITAL_PRESERVATION_SAMPLE_RATIO")
    professional_learning_enabled: bool = Field(default=True, alias="BLUM_PROFESSIONAL_LEARNING_ENABLED")
    professional_learning_minutes: int = Field(default=30, alias="BLUM_PROFESSIONAL_LEARNING_MINUTES")
    professional_learning_batch_size: int = Field(default=20, alias="BLUM_PROFESSIONAL_LEARNING_BATCH_SIZE")
    blum_model_cycle_minutes: int = Field(default=5, alias="BLUM_MODEL_CYCLE_MINUTES")
    blum_model_cycle_limit: int = Field(default=160, alias="BLUM_MODEL_CYCLE_LIMIT")
    fundamentals_refresh_minutes: int = Field(default=720, alias="BLUM_FUNDAMENTALS_REFRESH_MINUTES")
    macro_refresh_minutes: int = Field(default=240, alias="BLUM_MACRO_REFRESH_MINUTES")
    stale_price_max_age_days: int = Field(default=7, alias="BLUM_STALE_PRICE_MAX_AGE_DAYS")
    minimum_history_rows: int = Field(default=220, alias="BLUM_MINIMUM_HISTORY_ROWS")
    ipo_refresh_minutes: int = Field(default=120, alias="BLUM_IPO_REFRESH_MINUTES")
    news_fetch_workers: int = Field(default=10, alias="BLUM_NEWS_FETCH_WORKERS")
    max_dynamic_asset_news_feeds: int = Field(default=60, alias="BLUM_MAX_DYNAMIC_ASSET_NEWS_FEEDS")
    historical_price_period: str = Field(default="max", alias="BLUM_HISTORICAL_PRICE_PERIOD")
    refresh_price_period: str = Field(default="6mo", alias="BLUM_REFRESH_PRICE_PERIOD")
    sec_user_agent: str = Field(default="Blum-AI-Financial-Intelligence research demo", alias="BLUM_SEC_USER_AGENT")
    blum_model_repository: str = Field(default="Italianhype/Blum", alias="BLUM_MODEL_REPOSITORY")
    blum_analyst_repository: str = Field(default="Italianhype/Blum-Analyst", alias="BLUM_ANALYST_REPOSITORY")
    training_export_dir: str = Field(default="/tmp/blum_training_exports", alias="BLUM_TRAINING_EXPORT_DIR")
    enable_hf_dataset_catalog: bool = Field(default=True, alias="BLUM_ENABLE_HF_DATASET_CATALOG")
    hf_dataset_refresh_hours: int = Field(default=24, alias="BLUM_HF_DATASET_REFRESH_HOURS")
    hf_dataset_max_sources: int = Field(default=40, alias="BLUM_HF_DATASET_MAX_SOURCES")
    trading_min_timeframe: str = Field(default="4h", alias="TRADING_MIN_TIMEFRAME")
    trading_default_timeframe: str = Field(default="daily", alias="TRADING_DEFAULT_TIMEFRAME")
    trading_allow_microscalping: bool = Field(default=False, alias="TRADING_ALLOW_MICROSCALPING")
    trading_require_reproducible_setup: bool = Field(default=True, alias="TRADING_REQUIRE_REPRODUCIBLE_SETUP")
    trading_game_enabled: bool = Field(default=True, alias="TRADING_GAME_ENABLED")
    trading_game_initial_capital: float = Field(default=100.0, alias="TRADING_GAME_INITIAL_CAPITAL")
    trading_game_target_capital: float = Field(default=10000.0, alias="TRADING_GAME_TARGET_CAPITAL")
    trading_game_reset_on_target: bool = Field(default=True, alias="TRADING_GAME_RESET_ON_TARGET")
    trading_game_reset_on_bankruptcy: bool = Field(default=True, alias="TRADING_GAME_RESET_ON_BANKRUPTCY")
    trading_game_max_cycle_days: int = Field(default=365, alias="TRADING_GAME_MAX_CYCLE_DAYS")
    trading_game_batch_size: int = Field(default=60, alias="TRADING_GAME_BATCH_SIZE")
    trading_game_max_risk_percent: float = Field(default=2.0, alias="TRADING_GAME_MAX_RISK_PERCENT")
    trading_game_default_risk_percent: float = Field(default=1.0, alias="TRADING_GAME_DEFAULT_RISK_PERCENT")
    trading_game_benchmark: str = Field(default="SPY", alias="TRADING_GAME_BENCHMARK")
    live_trading_game_enabled: bool = Field(default=True, alias="LIVE_TRADING_GAME_ENABLED")
    live_trading_game_initial_capital: float = Field(default=100.0, alias="LIVE_TRADING_GAME_INITIAL_CAPITAL")
    live_trading_game_target_capital: float = Field(default=10000.0, alias="LIVE_TRADING_GAME_TARGET_CAPITAL")
    live_trading_game_max_open_positions: int = Field(default=5, alias="LIVE_TRADING_GAME_MAX_OPEN_POSITIONS")
    live_trading_game_max_risk_per_trade: float = Field(default=1.0, alias="LIVE_TRADING_GAME_MAX_RISK_PER_TRADE")
    live_trading_game_require_actionable_setup: bool = Field(default=True, alias="LIVE_TRADING_GAME_REQUIRE_ACTIONABLE_SETUP")
    live_trading_game_allow_fractional_shares: bool = Field(default=True, alias="LIVE_TRADING_GAME_ALLOW_FRACTIONAL_SHARES")
    live_trading_game_benchmark: str = Field(default="SPY", alias="LIVE_TRADING_GAME_BENCHMARK")
    paper_forward_lifecycle_enabled: bool = Field(default=False, alias="PAPER_FORWARD_LIFECYCLE_ENABLED")
    paper_forward_min_confidence: float = Field(default=50.0, alias="PAPER_FORWARD_MIN_CONFIDENCE")
    paper_forward_min_risk_reward: float = Field(default=1.0, alias="PAPER_FORWARD_MIN_RISK_REWARD")
    paper_forward_min_data_quality: float = Field(default=50.0, alias="PAPER_FORWARD_MIN_DATA_QUALITY")
    paper_forward_max_candidates_per_run: int = Field(default=30, alias="PAPER_FORWARD_MAX_CANDIDATES_PER_RUN")
    paper_forward_allow_watchlist_candidates: bool = Field(default=True, alias="PAPER_FORWARD_ALLOW_WATCHLIST_CANDIDATES")
    paper_forward_allow_trade_candidates: bool = Field(default=True, alias="PAPER_FORWARD_ALLOW_TRADE_CANDIDATES")
    paper_forward_enabled_markets: str = Field(
        default="us_equities,european_equities,global_equities,etfs,indexes,commodities,forex,crypto,bonds,volatility",
        alias="PAPER_FORWARD_ENABLED_MARKETS",
    )
    paper_forward_enabled_asset_classes: str = Field(
        default="equities,etfs,indexes,commodities,forex,crypto,bonds,volatility",
        alias="PAPER_FORWARD_ENABLED_ASSET_CLASSES",
    )
    paper_forward_require_benchmark: bool = Field(default=False, alias="PAPER_FORWARD_REQUIRE_BENCHMARK")
    paper_forward_min_liquidity_score: float = Field(default=0.0, alias="PAPER_FORWARD_MIN_LIQUIDITY_SCORE")
    paper_forward_max_assets_per_market: int = Field(default=25, alias="PAPER_FORWARD_MAX_ASSETS_PER_MARKET")
    paper_forward_scan_stale_data_max_age_hours: float = Field(default=72.0, alias="PAPER_FORWARD_SCAN_STALE_DATA_MAX_AGE_HOURS")
    paper_forward_cross_market_ranking_enabled: bool = Field(default=True, alias="PAPER_FORWARD_CROSS_MARKET_RANKING_ENABLED")
    blum_enabled_market_desk_agents: str = Field(
        default=(
            "FTSEMIBAgent,DAXAgent,CAC40Agent,IBEX35Agent,SMIAgent,EuroStoxx50Agent,"
            "WallStreetAgent,SP500Agent,NasdaqAgent,DowJonesAgent,Russell2000Agent,"
            "NikkeiAgent,HangSengAgent,IndiaNiftyAgent,ChinaAAgent,EmergingMarketsAgent,"
            "ETFDeskAgent,CryptoDeskAgent,ForexDeskAgent,CommodityDeskAgent,"
            "RatesBondProxyAgent,VolatilityDeskAgent"
        ),
        alias="BLUM_ENABLED_MARKET_DESK_AGENTS",
    )
    blum_max_candidates_per_agent: int = Field(default=5, alias="BLUM_MAX_CANDIDATES_PER_AGENT")
    blum_max_candidates_per_market: int = Field(default=8, alias="BLUM_MAX_CANDIDATES_PER_MARKET")
    blum_max_candidates_per_asset_class: int = Field(default=12, alias="BLUM_MAX_CANDIDATES_PER_ASSET_CLASS")
    blum_max_candidates_per_ticker: int = Field(default=1, alias="BLUM_MAX_CANDIDATES_PER_TICKER")
    blum_cross_market_orchestrator_enabled: bool = Field(default=True, alias="BLUM_CROSS_MARKET_ORCHESTRATOR_ENABLED")
    blum_quant_edge_min_score: float = Field(default=60.0, alias="BLUM_QUANT_EDGE_MIN_SCORE")
    blum_quant_edge_min_sample_size: int = Field(default=20, alias="BLUM_QUANT_EDGE_MIN_SAMPLE_SIZE")
    blum_reject_high_overfitting_risk: bool = Field(default=True, alias="BLUM_REJECT_HIGH_OVERFITTING_RISK")
    blum_learning_acceleration_enabled: bool = Field(default=True, alias="BLUM_LEARNING_ACCELERATION_ENABLED")
    blum_learning_acceleration_max_batches_per_run: int = Field(default=3, alias="BLUM_LEARNING_ACCELERATION_MAX_BATCHES_PER_RUN")
    blum_learning_acceleration_max_assets_per_run: int = Field(default=30, alias="BLUM_LEARNING_ACCELERATION_MAX_ASSETS_PER_RUN")
    blum_learning_acceleration_min_samples: int = Field(default=20, alias="BLUM_LEARNING_ACCELERATION_MIN_SAMPLES")
    blum_learning_acceleration_max_runtime_seconds: int = Field(default=20, alias="BLUM_LEARNING_ACCELERATION_MAX_RUNTIME_SECONDS")
    blum_learning_acceleration_budget_guard_enabled: bool = Field(default=True, alias="BLUM_LEARNING_ACCELERATION_BUDGET_GUARD_ENABLED")
    blum_learning_acceleration_prioritize_uncertainty: bool = Field(default=True, alias="BLUM_LEARNING_ACCELERATION_PRIORITIZE_UNCERTAINTY")
    blum_learning_acceleration_prioritize_missed_winners: bool = Field(default=True, alias="BLUM_LEARNING_ACCELERATION_PRIORITIZE_MISSED_WINNERS")
    blum_learning_acceleration_prioritize_repeated_blockers: bool = Field(default=True, alias="BLUM_LEARNING_ACCELERATION_PRIORITIZE_REPEATED_BLOCKERS")
    blum_experiment_manager_enabled: bool = Field(default=True, alias="BLUM_EXPERIMENT_MANAGER_ENABLED")
    blum_experiment_max_active_experiments: int = Field(default=5, alias="BLUM_EXPERIMENT_MAX_ACTIVE_EXPERIMENTS")
    self_improvement_enabled: bool = Field(default=True, alias="SELF_IMPROVEMENT_ENABLED")
    self_improvement_auto_apply: bool = Field(default=False, alias="SELF_IMPROVEMENT_AUTO_APPLY")
    self_improvement_auto_apply_low_risk: bool = Field(default=True, alias="SELF_IMPROVEMENT_AUTO_APPLY_LOW_RISK")
    self_improvement_min_sample_size: int = Field(default=50, alias="SELF_IMPROVEMENT_MIN_SAMPLE_SIZE")
    self_improvement_require_benchmark_check: bool = Field(default=True, alias="SELF_IMPROVEMENT_REQUIRE_BENCHMARK_CHECK")
    self_improvement_require_live_confirmation: bool = Field(default=False, alias="SELF_IMPROVEMENT_REQUIRE_LIVE_CONFIRMATION")
    self_improvement_rollback_enabled: bool = Field(default=True, alias="SELF_IMPROVEMENT_ROLLBACK_ENABLED")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        populate_by_name = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
