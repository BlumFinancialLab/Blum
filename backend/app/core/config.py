from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Blum AI Financial Intelligence"
    app_version: str = "0.2.0"
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
    default_benchmark: str = Field(default="SPY", alias="BLUM_DEFAULT_BENCHMARK")
    max_update_assets: int = Field(default=36, alias="BLUM_MAX_UPDATE_ASSETS")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        populate_by_name = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
