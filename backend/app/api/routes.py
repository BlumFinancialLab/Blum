from __future__ import annotations

from datetime import datetime
import os

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Query

from app.ai.orchestrator import AIOrchestrator
from app.ai.financial_brain import FinancialBrainModel
from app.core.config import get_settings
from app.core.database import get_db
from app.ingestion.news_ingestor import NewsIngestor
from app.models import AIInsight, Asset, EmbeddingVector, NewsArticle, NewsAssetLink, PriceHistory, SentimentAnalysis, SignalSnapshot
from app.schemas import AssetOut, MarketUpdateRequest, NewsOut, NewsUpdateRequest, SemanticSearchRequest, SignalRunRequest
from app.services.dashboard import dashboard_overview, signal_payload
from app.services.etf import list_etf_trends, update_etf_trends
from app.services.ipo import ipo_radar, sec_company_submissions, update_ipo_radar
from app.services.live import live_news, market_sentiment
from app.services.market_brain import build_market_brain, latest_market_brain, market_brain_history
from app.services.market_data import MarketDataService, market_snapshot_for_asset
from app.services.pipeline import PipelineService
from app.services.realtime import realtime_status
from app.services.semantic import SemanticService
from app.services.stock import stock_radar, update_stock_radar
from app.signals.backtest import run_simple_backtest
from app.signals.engine import SignalEngine


router = APIRouter()
settings = get_settings()


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "blum-ai-financial-intelligence"}


@router.get("/system/status")
def system_status(db: Session = Depends(get_db)) -> dict:
    latest_brain = db.scalar(select(func.max(NewsArticle.created_at))) if db is not None else None
    return {
        "service": "blum-ai-financial-intelligence",
        "app_version": settings.app_version,
        "feature_set": "live-dashboard-navigation-dedupe-v0.5.2",
        "environment": settings.environment,
        "generated_at": datetime.utcnow().isoformat(),
        "hugging_face": {
            "space_id": os.getenv("SPACE_ID") or os.getenv("HF_SPACE_ID"),
            "space_author": os.getenv("SPACE_AUTHOR_NAME") or os.getenv("HF_SPACE_AUTHOR_NAME"),
            "space_repo": os.getenv("SPACE_REPO_NAME") or os.getenv("HF_SPACE_REPO_NAME"),
            "commit_sha": os.getenv("SPACE_COMMIT_SHA") or os.getenv("HF_SPACE_COMMIT_SHA") or os.getenv("GIT_COMMIT_SHA"),
        },
        "runtime_flags": {
            "model_loading_enabled": settings.enable_model_loading,
            "financial_brain_model_enabled": settings.enable_financial_brain_model,
            "live_startup_enabled": settings.enable_live_startup,
        },
        "active_models": {
            "finbert": settings.finbert_model,
            "embeddings": settings.embedding_model,
            "reasoning_llm": settings.llm_model,
            "financial_brain_configured": settings.financial_brain_model,
            "financial_brain_runtime": FinancialBrainModel().status(),
        },
        "feature_visibility": {
            "market_brain_page": True,
            "financial_brain_panel": True,
            "ipo_radar_page": True,
            "stock_radar_page": True,
            "theme_detail": True,
            "signal_lifecycle": True,
            "sec_submissions": True,
        },
        "database_counts": {
            "assets": int(db.scalar(select(func.count(Asset.id))) or 0),
            "news_articles": int(db.scalar(select(func.count(NewsArticle.id))) or 0),
            "signals": int(db.scalar(select(func.count(SignalSnapshot.id))) or 0),
            "embeddings": int(db.scalar(select(func.count(EmbeddingVector.id))) or 0),
        },
        "latest_news_created_at": latest_brain,
        "why_gui_can_look_unchanged": [
            "Hugging Face serves the previous image until the Docker build finishes successfully.",
            "The finance-domain 7B model is disabled by default unless BLUM_ENABLE_FINANCIAL_BRAIN_MODEL=true.",
            "Existing snapshots must be regenerated with Run brain or full pipeline after a new deployment.",
            "Browser cache can keep old static Next.js chunks; hard refresh if app_version is not 0.5.2.",
        ],
    }


@router.get("/assets")
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
    assets = db.scalars(query).all()
    return [asset_payload(db, asset) for asset in assets]


@router.get("/assets/{ticker}")
def get_asset(ticker: str, db: Session = Depends(get_db)):
    asset = require_asset(db, ticker)
    prices = db.scalars(select(PriceHistory).where(PriceHistory.asset_id == asset.id).order_by(PriceHistory.date.desc()).limit(420)).all()
    signal = latest_signal(db, asset.id)
    linked = related_news_for_asset(db, asset.id, limit=12)
    return {
        "asset": AssetOut.model_validate(asset),
        "market_snapshot": market_snapshot_for_asset(db, asset),
        "prices": [
            {"date": str(row.date), "open": row.open, "high": row.high, "low": row.low, "close": row.close, "volume": row.volume}
            for row in reversed(prices)
        ],
        "latest_signal": signal_payload(signal, db) if signal else None,
        "related_news": linked,
    }


@router.post("/market/update")
def market_update(payload: MarketUpdateRequest, db: Session = Depends(get_db)):
    return MarketDataService().update_prices(db, tickers=payload.tickers, period=payload.period, limit=payload.limit)


@router.post("/news/update")
def news_update(payload: NewsUpdateRequest, db: Session = Depends(get_db)):
    return NewsIngestor().update_news(db, lookback_hours=payload.lookback_hours, limit_per_feed=payload.limit_per_feed)


@router.get("/news/live")
def news_live(limit: int = Query(default=60, ge=1, le=200), db: Session = Depends(get_db)):
    return live_news(db, limit=limit)


@router.get("/sentiment/market")
def sentiment_market(hours: int = Query(default=48, ge=1, le=720), db: Session = Depends(get_db)):
    return market_sentiment(db, hours=hours)


@router.post("/signals/run")
def signals_run(payload: SignalRunRequest, db: Session = Depends(get_db)):
    if payload.refresh_prices:
        MarketDataService().update_prices(db, tickers=payload.tickers, period=settings.historical_price_period, limit=payload.limit)
    result = SignalEngine().run(db, tickers=payload.tickers, limit=payload.limit)
    result.update(update_etf_trends(db))
    return result


@router.post("/pipeline/run")
def pipeline_run(payload: SignalRunRequest, db: Session = Depends(get_db)):
    return PipelineService().run(db, tickers=payload.tickers, limit=payload.limit, period=settings.historical_price_period)


@router.get("/pipeline/status")
def pipeline_status():
    return realtime_status()


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
        item = signal_payload(signal, db)
        item["asset"] = AssetOut.model_validate(asset)
        item["market_snapshot"] = market_snapshot_for_asset(db, asset)
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
    return signal_payload(signal, db)


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


@router.get("/themes/{label}")
def theme_detail(label: str, limit: int = Query(default=60, ge=1, le=160), db: Session = Depends(get_db)):
    return SemanticService().theme_detail(db, label=label, limit=limit)


@router.get("/etf-trends")
def etf_trends(db: Session = Depends(get_db)):
    return list_etf_trends(db)


@router.get("/stock-radar")
def stock_radar_endpoint(limit: int = Query(default=80, ge=1, le=120), db: Session = Depends(get_db)):
    return stock_radar(db, limit=limit)


@router.post("/stock-radar/update")
def stock_radar_update(limit: int = Query(default=36, ge=1, le=80), db: Session = Depends(get_db)):
    return update_stock_radar(db, limit=limit)


@router.get("/ipo-radar")
def ipo_radar_endpoint(limit: int = Query(default=80, ge=1, le=160), db: Session = Depends(get_db)):
    return ipo_radar(db, limit=limit)


@router.post("/ipo-radar/update")
def ipo_radar_update(limit_per_form: int = Query(default=50, ge=10, le=120), db: Session = Depends(get_db)):
    return update_ipo_radar(db, limit_per_form=limit_per_form)


@router.get("/ipo-radar/sec-submissions/{cik}")
def ipo_sec_submissions(cik: str, persist: bool = Query(default=False), db: Session = Depends(get_db)):
    return sec_company_submissions(db, cik=cik, persist=persist)


@router.get("/market-brain")
def market_brain_endpoint(db: Session = Depends(get_db)):
    return build_market_brain(db, persist=False)


@router.get("/market-brain/latest")
def market_brain_latest_endpoint(db: Session = Depends(get_db)):
    return latest_market_brain(db)


@router.get("/market-brain/history")
def market_brain_history_endpoint(limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db)):
    return market_brain_history(db, limit=limit)


@router.post("/market-brain/run")
def market_brain_run(
    refresh_pipeline: bool = Query(default=False),
    refresh_sec: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    updates = {}
    if refresh_pipeline:
        updates["pipeline"] = PipelineService().run(db, limit=settings.startup_pipeline_limit, period=settings.historical_price_period)
    elif refresh_sec:
        updates["ipo_update"] = update_ipo_radar(db, limit_per_form=50)
    brain = build_market_brain(db, persist=True)
    brain["update_diagnostics"] = updates
    return brain


@router.get("/ai/models/status")
def ai_model_status(db: Session = Depends(get_db)):
    sentiment_models = db.execute(
        select(SentimentAnalysis.model_name, func.count(SentimentAnalysis.id))
        .group_by(SentimentAnalysis.model_name)
        .order_by(func.count(SentimentAnalysis.id).desc())
    ).all()
    insight_models = db.execute(
        select(AIInsight.model_name, func.count(AIInsight.id))
        .group_by(AIInsight.model_name)
        .order_by(func.count(AIInsight.id).desc())
    ).all()
    embedding_models = db.execute(
        select(EmbeddingVector.model_name, func.count(EmbeddingVector.id))
        .group_by(EmbeddingVector.model_name)
        .order_by(func.count(EmbeddingVector.id).desc())
    ).all()
    return {
        "model_loading_enabled": settings.enable_model_loading,
        "configured_models": {
            "financial_sentiment": settings.finbert_model,
            "embeddings": settings.embedding_model,
            "reasoning_llm": settings.llm_model,
            "financial_brain": settings.financial_brain_model,
            "time_series": "statistical-fallback with adapter-ready interface",
        },
        "financial_brain": FinancialBrainModel().status(),
        "observed_models": {
            "sentiment": [{"model_name": model, "records": int(count)} for model, count in sentiment_models],
            "embeddings": [{"model_name": model, "records": int(count)} for model, count in embedding_models],
            "insights": [{"model_name": model, "records": int(count)} for model, count in insight_models],
        },
        "fallback_policy": {
            "sentiment": "FinBERT primary when loadable; VADER baseline/fallback is labeled in stored records.",
            "embeddings": "sentence-transformers primary when loadable; deterministic embedding fallback is explicit in code path.",
            "reasoning": "Configured LLM when loadable; deterministic evidence reasoner fallback never invents data.",
            "time_series": "Transparent statistical fallback until Chronos, TimesFM or PatchTST adapter is enabled.",
        },
    }


@router.get("/dashboard/overview")
def overview(db: Session = Depends(get_db)):
    return dashboard_overview(db)


@router.get("/ai/explain/{ticker}")
def ai_explain(ticker: str, db: Session = Depends(get_db)):
    asset = require_asset(db, ticker)
    signal = latest_signal(db, asset.id)
    hydration = {}
    if not signal:
        hydration = hydrate_asset_evidence(db, asset)
        signal = latest_signal(db, asset.id)
    news = related_news_for_asset(db, asset.id, limit=8)
    if not signal:
        insight = insufficient_evidence_insight(db, asset, news, hydration)
        db.add(
            AIInsight(
                asset_id=asset.id,
                model_name=insight["models_used"]["reasoning"],
                insight_type="asset_explanation_incomplete",
                structured_output=insight,
                explanation=insight["reason"],
            )
        )
        db.commit()
        return insight
    insight = AIOrchestrator().generate_asset_insight(
        ticker=asset.ticker,
        signal=signal_payload(signal, db),
        technical=signal.technical_summary,
        narrative=signal.narrative_summary,
        related_news=news,
    )
    insight["evidence_status"] = "ready"
    insight["auto_hydration"] = hydration
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


def asset_payload(db: Session, asset: Asset) -> dict:
    payload = AssetOut.model_validate(asset).model_dump()
    payload["market_snapshot"] = market_snapshot_for_asset(db, asset)
    return payload


def latest_signal(db: Session, asset_id: int) -> SignalSnapshot | None:
    return db.scalar(select(SignalSnapshot).where(SignalSnapshot.asset_id == asset_id).order_by(desc(SignalSnapshot.created_at)).limit(1))


def hydrate_asset_evidence(db: Session, asset: Asset) -> dict:
    tickers = [asset.ticker]
    benchmark = settings.default_benchmark.upper()
    if benchmark != asset.ticker:
        tickers.append(benchmark)
    market = MarketDataService().update_prices(db, tickers=tickers, period=settings.historical_price_period, limit=len(tickers))
    news = NewsIngestor().update_news(db, lookback_hours=168, limit_per_feed=20, tickers=[asset.ticker])
    signals = SignalEngine().run(db, tickers=[asset.ticker], limit=1)
    etf = update_etf_trends(db)
    return {
        "mode": "on_demand_real_data_hydration",
        "market_update": market,
        "news_update": news,
        "signal_run": signals,
        "etf_update": etf,
    }


def insufficient_evidence_insight(db: Session, asset: Asset, news: list[dict], hydration: dict) -> dict:
    price_rows = int(db.scalar(select(func.count(PriceHistory.id)).where(PriceHistory.asset_id == asset.id)) or 0)
    market = hydration.get("market_update", {})
    news_update = hydration.get("news_update", {})
    missing_assets = market.get("missing_assets", [])
    provider_report = market.get("provider_report", [])
    reason = (
        f"{asset.ticker} does not have enough verified public market data to create a full Blum Intelligence Score yet. "
        f"The backend attempted on-demand real-data hydration, stored {price_rows} OHLCV rows and found {len(news)} linked news items. "
        "No synthetic prices, headlines, sentiment or signal evidence were generated."
    )
    if missing_assets:
        reason += f" Public price providers did not return usable data for: {', '.join(missing_assets[:6])}."
    return {
        "ticker": asset.ticker,
        "classification": "Insufficient Evidence",
        "blum_score": 0,
        "reason": reason,
        "watch_points": [
            "Keep the live worker running until public OHLCV providers return sufficient historical rows.",
            "Review source diagnostics to identify blocked, empty or rate-limited public feeds.",
            "Use the live news tape as narrative evidence while the quantitative signal waits for price history.",
        ],
        "risk_level": "Not Rated",
        "time_horizon": "Not Rated",
        "monitor_next": ["public OHLCV availability", "linked news count", "source diagnostics", "signal snapshot creation"],
        "evidence_status": "insufficient_real_data",
        "data_diagnostics": {
            "price_rows": price_rows,
            "linked_news": len(news),
            "market_update": {
                "data_mode": market.get("data_mode"),
                "updated_assets": market.get("updated_assets", 0),
                "price_rows": market.get("price_rows", 0),
                "missing_assets": missing_assets,
                "provider_report": provider_report,
            },
            "news_update": {
                "mode": news_update.get("mode"),
                "sources_requested": news_update.get("sources_requested", 0),
                "sources_ok": news_update.get("sources_ok", 0),
                "inserted_articles": news_update.get("inserted_articles", 0),
                "linked_assets": news_update.get("linked_assets", 0),
                "source_errors": news_update.get("source_errors", [])[:8],
            },
        },
        "models_used": {
            "sentiment": settings.finbert_model,
            "embeddings": settings.embedding_model,
            "reasoning": "evidence-readiness-engine",
            "time_series": "statistical-regime-engine",
        },
    }


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
