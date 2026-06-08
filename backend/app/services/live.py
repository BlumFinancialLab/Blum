from __future__ import annotations

from datetime import datetime, timedelta
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Asset, NewsArticle, NewsAssetLink, SentimentAnalysis


def live_news(db: Session, limit: int = 60) -> list[dict]:
    articles = db.scalars(
        select(NewsArticle)
        .order_by(desc(NewsArticle.published_at), desc(NewsArticle.created_at))
        .limit(limit)
    ).all()
    if not articles:
        return []
    article_ids = [article.id for article in articles]
    sentiment_rows = db.execute(
        select(SentimentAnalysis)
        .where(SentimentAnalysis.article_id.in_(article_ids))
        .order_by(desc(SentimentAnalysis.created_at))
    ).scalars().all()
    sentiment_by_article = {}
    for row in sentiment_rows:
        sentiment_by_article.setdefault(row.article_id, row)
    link_rows = db.execute(
        select(NewsAssetLink.article_id, Asset.ticker, Asset.name, Asset.sector, NewsAssetLink.relevance_score)
        .join(Asset, Asset.id == NewsAssetLink.asset_id)
        .where(NewsAssetLink.article_id.in_(article_ids))
        .order_by(NewsAssetLink.relevance_score.desc())
    ).all()
    links_by_article: dict[int, list[dict]] = {}
    for article_id, ticker, name, sector, relevance_score in link_rows:
        links_by_article.setdefault(article_id, []).append(
            {"ticker": ticker, "name": name, "sector": sector, "relevance_score": relevance_score}
        )
    return [
        {
            "id": article.id,
            "source": article.source,
            "published_at": article.published_at,
            "title": article.title,
            "summary": article.summary,
            "url": article.url,
            "quality_score": article.quality_score,
            "theme_tags": article.theme_tags,
            "sentiment": sentiment_payload(sentiment_by_article.get(article.id)),
            "linked_assets": links_by_article.get(article.id, [])[:8],
        }
        for article in articles
    ]


def market_sentiment(db: Session, hours: int = 48) -> dict:
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    rows = db.execute(
        select(NewsArticle, SentimentAnalysis)
        .join(SentimentAnalysis, SentimentAnalysis.article_id == NewsArticle.id)
        .where(NewsArticle.created_at >= cutoff)
        .order_by(desc(NewsArticle.created_at))
        .limit(600)
    ).all()
    scores = [float(sentiment.score) for _, sentiment in rows]
    labels = {"positive": 0, "neutral": 0, "negative": 0}
    themes: dict[str, dict] = {}
    models: dict[str, int] = {}
    for article, sentiment in rows:
        labels[sentiment.label] = labels.get(sentiment.label, 0) + 1
        models[sentiment.model_name] = models.get(sentiment.model_name, 0) + 1
        for theme in article.theme_tags.get("themes", ["Market Structure"]):
            item = themes.setdefault(theme, {"headline_count": 0, "sentiment_sum": 0.0})
            item["headline_count"] += 1
            item["sentiment_sum"] += float(sentiment.score)
    ranked_themes = [
        {
            "theme": theme,
            "headline_count": values["headline_count"],
            "avg_sentiment": round(values["sentiment_sum"] / max(values["headline_count"], 1), 4),
        }
        for theme, values in sorted(themes.items(), key=lambda item: item[1]["headline_count"], reverse=True)
    ]
    return {
        "window_hours": hours,
        "article_count": len(rows),
        "average_sentiment": round(sum(scores) / len(scores), 4) if scores else 0.0,
        "label_counts": labels,
        "models": models,
        "themes": ranked_themes[:12],
    }


def sentiment_payload(row: SentimentAnalysis | None) -> dict | None:
    if row is None:
        return None
    return {
        "model_name": row.model_name,
        "label": row.label,
        "score": row.score,
        "confidence": row.confidence,
        "baseline_vader": row.baseline_vader,
    }
