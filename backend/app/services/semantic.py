from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session
from sklearn.cluster import KMeans

from app.ai.orchestrator import AIOrchestrator
from app.models import Asset, EmbeddingVector, NewsArticle, NewsAssetLink, SentimentAnalysis, ThemeCluster


class SemanticService:
    def __init__(self, ai: AIOrchestrator | None = None):
        self.ai = ai or AIOrchestrator()

    def search(self, db: Session, query: str, limit: int = 10) -> list[dict]:
        rows = db.execute(
            select(EmbeddingVector, NewsArticle)
            .join(NewsArticle, NewsArticle.id == EmbeddingVector.article_id)
            .order_by(EmbeddingVector.created_at.desc())
            .limit(500)
        ).all()
        vectors = [row.EmbeddingVector.vector.get("values", []) for row in rows]
        scores = self.ai.embeddings.similarity(query, vectors)
        ranked = sorted(zip(rows, scores), key=lambda item: item[1], reverse=True)[:limit]
        return [
            {
                "score": round(float(score), 4),
                "article": {
                    "id": row.NewsArticle.id,
                    "title": row.NewsArticle.title,
                    "summary": row.NewsArticle.summary,
                    "source": row.NewsArticle.source,
                    "url": row.NewsArticle.url,
                    "published_at": row.NewsArticle.published_at,
                    "theme_tags": row.NewsArticle.theme_tags,
                },
            }
            for row, score in ranked
        ]

    def themes(self, db: Session) -> list[dict]:
        stored = db.scalars(select(ThemeCluster).order_by(desc(ThemeCluster.created_at)).limit(30)).all()
        if stored:
            return [
                {
                    "label": item.label,
                    "keywords": item.keywords,
                    "asset_tickers": item.asset_tickers,
                    "sentiment_score": item.sentiment_score,
                    "created_at": item.created_at,
                }
                for item in stored
            ]
        embedded = db.execute(
            select(EmbeddingVector, NewsArticle)
            .join(NewsArticle, NewsArticle.id == EmbeddingVector.article_id)
            .order_by(desc(EmbeddingVector.created_at))
            .limit(400)
        ).all()
        vectors = [row.EmbeddingVector.vector.get("values", []) for row in embedded if row.EmbeddingVector.vector.get("values")]
        if len(vectors) >= 6:
            return semantic_clusters(embedded, vectors)
        articles = db.scalars(select(NewsArticle).order_by(desc(NewsArticle.created_at)).limit(200)).all()
        clusters: dict[str, dict] = {}
        for article in articles:
            for theme in article.theme_tags.get("themes", ["Market Structure"]):
                entry = clusters.setdefault(theme, {"label": theme, "articles": 0, "asset_tickers": [], "keywords": set()})
                entry["articles"] += 1
                entry["keywords"].update(theme.lower().split())
        return [
            {
                "label": label,
                "article_count": value["articles"],
                "asset_tickers": value["asset_tickers"],
                "keywords": sorted(value["keywords"]),
                "sentiment_score": 0,
            }
            for label, value in sorted(clusters.items(), key=lambda item: item[1]["articles"], reverse=True)
        ]

    def theme_detail(self, db: Session, label: str, limit: int = 60) -> dict:
        normalized = label.strip().lower()
        articles = db.scalars(select(NewsArticle).order_by(desc(NewsArticle.published_at), desc(NewsArticle.created_at)).limit(700)).all()
        matched = [
            article for article in articles
            if normalized in [str(theme).lower() for theme in article.theme_tags.get("themes", [])]
            or normalized in article.title.lower()
            or normalized in article.summary.lower()
        ][:limit]
        article_ids = [article.id for article in matched]
        sentiments = []
        links_by_article: dict[int, list[dict]] = {}
        if article_ids:
            sentiments = db.scalars(
                select(SentimentAnalysis)
                .where(SentimentAnalysis.article_id.in_(article_ids))
                .order_by(desc(SentimentAnalysis.created_at))
            ).all()
            link_rows = db.execute(
                select(NewsAssetLink.article_id, Asset.ticker, Asset.name, Asset.sector, NewsAssetLink.relevance_score)
                .join(Asset, Asset.id == NewsAssetLink.asset_id)
                .where(NewsAssetLink.article_id.in_(article_ids))
            ).all()
            for article_id, ticker, name, sector, relevance in link_rows:
                links_by_article.setdefault(article_id, []).append(
                    {"ticker": ticker, "name": name, "sector": sector, "relevance_score": relevance}
                )
        sentiment_by_article = {}
        for sentiment in sentiments:
            sentiment_by_article.setdefault(sentiment.article_id, sentiment)
        scores = [float(sentiment.score) for sentiment in sentiments]
        source_counts: dict[str, int] = {}
        asset_counts: dict[str, dict] = {}
        for article in matched:
            source_counts[article.source] = source_counts.get(article.source, 0) + 1
            for asset in links_by_article.get(article.id, []):
                item = asset_counts.setdefault(asset["ticker"], {"ticker": asset["ticker"], "name": asset["name"], "sector": asset["sector"], "mentions": 0})
                item["mentions"] += 1
        return {
            "label": label,
            "article_count": len(matched),
            "average_sentiment": round(sum(scores) / len(scores), 4) if scores else 0,
            "source_mix": sorted([{"source": source, "count": count} for source, count in source_counts.items()], key=lambda item: item["count"], reverse=True),
            "linked_assets": sorted(asset_counts.values(), key=lambda item: item["mentions"], reverse=True)[:20],
            "articles": [
                {
                    "id": article.id,
                    "title": article.title,
                    "summary": article.summary,
                    "source": article.source,
                    "url": article.url,
                    "published_at": article.published_at,
                    "quality_score": article.quality_score,
                    "theme_tags": article.theme_tags,
                    "sentiment": sentiment_payload(sentiment_by_article.get(article.id)),
                    "linked_assets": links_by_article.get(article.id, [])[:8],
                }
                for article in matched
            ],
        }


def semantic_clusters(rows, vectors: list[list[float]]) -> list[dict]:
    import numpy as np

    matrix = np.array(vectors, dtype=float)
    n_clusters = max(2, min(8, int(len(matrix) ** 0.5)))
    labels = KMeans(n_clusters=n_clusters, n_init=10, random_state=42).fit_predict(matrix)
    clusters: dict[int, dict] = {}
    vector_index = 0
    for row in rows:
        values = row.EmbeddingVector.vector.get("values", [])
        if not values:
            continue
        label_id = int(labels[vector_index])
        vector_index += 1
        article = row.NewsArticle
        entry = clusters.setdefault(label_id, {"articles": [], "themes": {}, "sources": set()})
        entry["articles"].append(article)
        entry["sources"].add(article.source)
        for theme in article.theme_tags.get("themes", ["Market Structure"]):
            entry["themes"][theme] = entry["themes"].get(theme, 0) + 1
    output = []
    for label_id, data in clusters.items():
        ranked_themes = sorted(data["themes"].items(), key=lambda item: item[1], reverse=True)
        label = ranked_themes[0][0] if ranked_themes else f"Semantic Cluster {label_id + 1}"
        output.append(
            {
                "label": label,
                "article_count": len(data["articles"]),
                "source_count": len(data["sources"]),
                "keywords": [theme for theme, _ in ranked_themes[:5]],
                "asset_tickers": [],
                "sentiment_score": 0,
                "cluster_method": "sentence-transformers + kmeans",
                "sample_titles": [article.title for article in data["articles"][:4]],
            }
        )
    return sorted(output, key=lambda item: item["article_count"], reverse=True)


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
