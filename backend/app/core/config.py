from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Blum AI Financial Intelligence"
    app_version: str = "0.5.0"
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
    default_benchmark: str = Field(default="SPY", alias="BLUM_DEFAULT_BENCHMARK")
    max_update_assets: int = Field(default=36, alias="BLUM_MAX_UPDATE_ASSETS")
    enable_live_startup: bool = Field(default=True, alias="BLUM_ENABLE_LIVE_STARTUP")
    startup_pipeline_limit: int = Field(default=36, alias="BLUM_STARTUP_PIPELINE_LIMIT")
    news_refresh_minutes: int = Field(default=10, alias="BLUM_NEWS_REFRESH_MINUTES")
    market_refresh_minutes: int = Field(default=45, alias="BLUM_MARKET_REFRESH_MINUTES")
    ipo_refresh_minutes: int = Field(default=120, alias="BLUM_IPO_REFRESH_MINUTES")
    news_fetch_workers: int = Field(default=10, alias="BLUM_NEWS_FETCH_WORKERS")
    max_dynamic_asset_news_feeds: int = Field(default=36, alias="BLUM_MAX_DYNAMIC_ASSET_NEWS_FEEDS")
    historical_price_period: str = Field(default="max", alias="BLUM_HISTORICAL_PRICE_PERIOD")
    refresh_price_period: str = Field(default="6mo", alias="BLUM_REFRESH_PRICE_PERIOD")
    sec_user_agent: str = Field(default="Blum-AI-Financial-Intelligence research demo", alias="BLUM_SEC_USER_AGENT")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        populate_by_name = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
