from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Query

from app.ai.orchestrator import AIOrchestrator
from app.core.database import get_db
from app.ingestion.news_ingestor import NewsIngestor
from app.models import AIInsight, Asset, NewsArticle, NewsAssetLink, PriceHistory, SentimentAnalysis, SignalSnapshot
from app.schemas import AssetOut, MarketUpdateRequest, NewsOut, NewsUpdateRequest, SemanticSearchRequest, SignalRunRequest
from app.services.dashboard import dashboard_overview, signal_payload
from app.services.etf import list_etf_trends, update_etf_trends
from app.services.market_data import MarketDataService
from app.services.semantic import SemanticService
from app.signals.backtest import run_simple_backtest
from app.signals.engine import SignalEngine


router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "blum-ai-financial-intelligence"}


@router.get("/assets", response_model=list[AssetOut])
def list_assets(
    asset_type: str | None = Query(default=None),
    country: str | None = Query(default=None),
    sector: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = select(Asset).where(Asset.is_active.is_(True)).order_by(Asset.asset_type, Asset.sector, Asset.ticker)
    if asset_type:
        query = query.where(Asset.asset_type.ilike(asset_type))
    if country:
        query = query.where(Asset.country.ilike(country))
    if sector:
        query = query.where(Asset.sector.ilike(f"%{sector}%"))
    return db.scalars(query).all()


@router.get("/assets/{ticker}")
def get_asset(ticker: str, db: Session = Depends(get_db)):
    asset = require_asset(db, ticker)
    prices = db.scalars(select(PriceHistory).where(PriceHistory.asset_id == asset.id).order_by(PriceHistory.date.desc()).limit(420)).all()
    signal = latest_signal(db, asset.id)
    linked = related_news_for_asset(db, asset.id, limit=12)
    return {
        "asset": AssetOut.model_validate(asset),
        "prices": [
            {"date": str(row.date), "open": row.open, "high": row.high, "low": row.low, "close": row.close, "volume": row.volume}
            for row in reversed(prices)
        ],
        "latest_signal": signal_payload(signal) if signal else None,
        "related_news": linked,
    }


@router.post("/market/update")
def market_update(payload: MarketUpdateRequest, db: Session = Depends(get_db)):
    return MarketDataService().update_prices(db, tickers=payload.tickers, period=payload.period, limit=payload.limit)


@router.post("/news/update")
def news_update(payload: NewsUpdateRequest, db: Session = Depends(get_db)):
    return NewsIngestor().update_news(db, lookback_hours=payload.lookback_hours, limit_per_feed=payload.limit_per_feed)


@router.post("/signals/run")
def signals_run(payload: SignalRunRequest, db: Session = Depends(get_db)):
    if payload.refresh_prices:
        MarketDataService().update_prices(db, tickers=payload.tickers, period="2y", limit=payload.limit)
    result = SignalEngine().run(db, tickers=payload.tickers, limit=payload.limit)
    result.update(update_etf_trends(db))
    return result


@router.get("/signals/top")
def signals_top(
    classification: str | None = Query(default=None),
    asset_type: str | None = Query(default=None),
    risk_level: str | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = select(SignalSnapshot, Asset).join(Asset, Asset.id == SignalSnapshot.asset_id).order_by(desc(SignalSnapshot.created_at), desc(SignalSnapshot.blum_score))
    if classification:
        query = query.where(SignalSnapshot.classification == classification)
    if asset_type:
        query = query.where(Asset.asset_type == asset_type)
    if risk_level:
        query = query.where(SignalSnapshot.risk_level == risk_level)
    rows = db.execute(query.limit(limit * 3)).all()
    seen = set()
    output = []
    for signal, asset in rows:
        if signal.ticker in seen:
            continue
        seen.add(signal.ticker)
        item = signal_payload(signal)
        item["asset"] = AssetOut.model_validate(asset)
        output.append(item)
        if len(output) >= limit:
            break
    return output


@router.get("/signals/{ticker}")
def signal_detail(ticker: str, db: Session = Depends(get_db)):
    asset = require_asset(db, ticker)
    signal = latest_signal(db, asset.id)
    if not signal:
        raise HTTPException(status_code=404, detail="No signal available. Run /signals/run first.")
    return signal_payload(signal)


@router.get("/sentiment/{ticker}")
def sentiment_for_ticker(ticker: str, db: Session = Depends(get_db)):
    asset = require_asset(db, ticker)
    linked_ids = [row[0] for row in db.execute(select(NewsAssetLink.article_id).where(NewsAssetLink.asset_id == asset.id)).all()]
    rows = []
    if linked_ids:
        rows = db.execute(
            select(SentimentAnalysis, NewsArticle)
            .join(NewsArticle, NewsArticle.id == SentimentAnalysis.article_id)
            .where(SentimentAnalysis.article_id.in_(linked_ids))
            .order_by(desc(SentimentAnalysis.created_at))
            .limit(80)
        ).all()
    return [
        {
            "title": article.title,
            "source": article.source,
            "published_at": article.published_at,
            "model_name": sentiment.model_name,
            "label": sentiment.label,
            "score": sentiment.score,
            "confidence": sentiment.confidence,
            "baseline_vader": sentiment.baseline_vader,
        }
        for sentiment, article in rows
    ]


@router.post("/semantic-search")
def semantic_search(payload: SemanticSearchRequest, db: Session = Depends(get_db)):
    return SemanticService().search(db, query=payload.query, limit=payload.limit)


@router.get("/related-news")
def related_news(ticker: str, limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db)):
    asset = require_asset(db, ticker)
    return related_news_for_asset(db, asset.id, limit=limit)


@router.get("/themes")
def themes(db: Session = Depends(get_db)):
    return SemanticService().themes(db)


@router.get("/etf-trends")
def etf_trends(db: Session = Depends(get_db)):
    return list_etf_trends(db)


@router.get("/dashboard/overview")
def overview(db: Session = Depends(get_db)):
    return dashboard_overview(db)


@router.get("/ai/explain/{ticker}")
def ai_explain(ticker: str, db: Session = Depends(get_db)):
    asset = require_asset(db, ticker)
    signal = latest_signal(db, asset.id)
    if not signal:
        raise HTTPException(status_code=404, detail="No signal available. Run /signals/run first.")
    news = related_news_for_asset(db, asset.id, limit=8)
    insight = AIOrchestrator().generate_asset_insight(
        ticker=asset.ticker,
        signal=signal_payload(signal),
        technical=signal.technical_summary,
        narrative=signal.narrative_summary,
        related_news=news,
    )
    db.add(AIInsight(asset_id=asset.id, model_name=insight["models_used"]["reasoning"], structured_output=insight, explanation=insight["reason"]))
    db.commit()
    return insight


@router.post("/backtest/{ticker}")
def backtest(ticker: str, db: Session = Depends(get_db)):
    asset = require_asset(db, ticker)
    return run_simple_backtest(db, asset.id, asset.ticker)


def require_asset(db: Session, ticker: str) -> Asset:
    asset = db.scalar(select(Asset).where(Asset.ticker == ticker.upper()))
    if not asset:
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {ticker}")
    return asset


def latest_signal(db: Session, asset_id: int) -> SignalSnapshot | None:
    return db.scalar(select(SignalSnapshot).where(SignalSnapshot.asset_id == asset_id).order_by(desc(SignalSnapshot.created_at)).limit(1))


def related_news_for_asset(db: Session, asset_id: int, limit: int = 20) -> list[dict]:
    rows = db.execute(
        select(NewsArticle, NewsAssetLink)
        .join(NewsAssetLink, NewsAssetLink.article_id == NewsArticle.id)
        .where(NewsAssetLink.asset_id == asset_id)
        .order_by(desc(NewsArticle.published_at), desc(NewsArticle.created_at))
        .limit(limit)
    ).all()
    return [
        {
            "id": article.id,
            "title": article.title,
            "summary": article.summary,
            "source": article.source,
            "published_at": article.published_at,
            "url": article.url,
            "quality_score": article.quality_score,
            "theme_tags": article.theme_tags,
            "relevance_score": link.relevance_score,
        }
        for article, link in rows
    ]

