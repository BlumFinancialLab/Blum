from datetime import date, datetime
from pydantic import BaseModel, Field


class AssetOut(BaseModel):
    ticker: str
    name: str
    category: str
    sector: str
    industry: str
    country: str
    asset_type: str
    currency: str
    exchange: str
    description: str

    class Config:
        from_attributes = True


class PricePoint(BaseModel):
    date: date
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float
    volume: float | None = None


class NewsOut(BaseModel):
    id: int
    source: str
    published_at: datetime | None
    title: str
    summary: str
    url: str
    quality_score: float
    theme_tags: dict

    class Config:
        from_attributes = True


class SignalOut(BaseModel):
    ticker: str
    classification: str
    blum_score: float
    risk_level: str
    time_horizon: str
    score_breakdown: dict
    technical_summary: dict
    narrative_summary: dict
    explanation: str
    watch_points: dict
    created_at: datetime

    class Config:
        from_attributes = True


class SemanticSearchRequest(BaseModel):
    query: str = Field(min_length=2)
    limit: int = Field(default=10, ge=1, le=50)


class SignalRunRequest(BaseModel):
    tickers: list[str] | None = None
    refresh_prices: bool = False
    limit: int = Field(default=30, ge=1, le=100)


class MarketUpdateRequest(BaseModel):
    tickers: list[str] | None = None
    period: str = "max"
    limit: int = Field(default=36, ge=1, le=120)


class NewsUpdateRequest(BaseModel):
    lookback_hours: int = Field(default=72, ge=1, le=720)
    limit_per_feed: int = Field(default=35, ge=1, le=100)
