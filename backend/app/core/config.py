from functools import lru_cache
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Blum AI Financial Intelligence"
    app_version: str = "0.9.0"
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
    learning_max_daily_runs: int = Field(default=1000, alias="LEARNING_MAX_DAILY_RUNS")
    learning_random_seed: str = Field(default="", alias="LEARNING_RANDOM_SEED")
    learning_min_history_years: int = Field(default=3, alias="LEARNING_MIN_HISTORY_YEARS")
    learning_asset_universe: str = Field(default="stocks,etfs", alias="LEARNING_ASSET_UNIVERSE")
    learning_evaluation_mode: str = Field(default="walk_forward", alias="LEARNING_EVALUATION_MODE")
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
    training_export_dir: str = Field(default="/tmp/blum_training_exports", alias="BLUM_TRAINING_EXPORT_DIR")
    enable_hf_dataset_catalog: bool = Field(default=True, alias="BLUM_ENABLE_HF_DATASET_CATALOG")
    hf_dataset_refresh_hours: int = Field(default=24, alias="BLUM_HF_DATASET_REFRESH_HOURS")
    hf_dataset_max_sources: int = Field(default=40, alias="BLUM_HF_DATASET_MAX_SOURCES")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        populate_by_name = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
