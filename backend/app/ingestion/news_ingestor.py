from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import re

import feedparser
import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.orchestrator import AIOrchestrator
from app.ingestion.rss_sources import RSS_SOURCES
from app.models import Asset, EmbeddingVector, NewsArticle, NewsAssetLink, SentimentAnalysis


HEADERS = {
    "User-Agent": "Blum-AI-Financial-Intelligence/0.2 public research demo"
}

THEME_KEYWORDS = {
    "AI": ["ai", "artificial intelligence", "gpu", "data center", "accelerator", "llm"],
    "Rates": ["fed", "rate", "rates", "yield", "treasury", "inflation", "cpi", "pce"],
    "Earnings": ["earnings", "revenue", "profit", "guidance", "margin", "eps"],
    "Geopolitics": ["war", "sanction", "tariff", "china", "russia", "middle east"],
    "M&A": ["merger", "acquisition", "takeover", "deal", "buyout"],
    "Regulation": ["sec", "regulator", "antitrust", "probe", "investigation"],
    "Supply Chain": ["supply chain", "shortage", "inventory", "shipping", "logistics"],
    "Innovation": ["innovation", "robotics", "automation", "cloud", "cyber"],
    "Energy": ["oil", "gas", "opec", "crude", "renewable", "clean energy"],
}


class NewsIngestor:
    def __init__(self, ai: AIOrchestrator | None = None):
        self.ai = ai or AIOrchestrator()

    def update_news(self, db: Session, lookback_hours: int = 72, limit_per_feed: int = 35) -> dict:
        assets = db.scalars(select(Asset).where(Asset.is_active.is_(True))).all()
        inserted = 0
        linked = 0
        analyzed = 0
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        for source in RSS_SOURCES:
            for item in self._fetch_source(source, cutoff, limit_per_feed):
                canonical_key = item["canonical_key"]
                existing = db.scalar(select(NewsArticle).where(NewsArticle.canonical_key == canonical_key))
                if existing:
                    continue
                article = NewsArticle(**item)
                db.add(article)
                db.flush()
                sentiment = self.ai.sentiment.analyze(f"{article.title}. {article.summary}")
                db.add(
                    SentimentAnalysis(
                        article_id=article.id,
                        model_name=sentiment["model_name"],
                        label=sentiment["label"],
                        score=sentiment["score"],
                        confidence=sentiment["confidence"],
                        baseline_vader=sentiment["baseline_vader"],
                        raw_payload=sentiment,
                    )
                )
                analyzed += 1
                vector = self.ai.embeddings.embed_text(f"{article.title}. {article.summary}")
                if vector:
                    db.add(EmbeddingVector(article_id=article.id, model_name=self.ai.embeddings.model_name, vector={"values": vector}))
                for asset, relevance in self._match_assets(article, assets):
                    db.add(NewsAssetLink(article_id=article.id, asset_id=asset.id, relevance_score=relevance))
                    linked += 1
                inserted += 1
        db.commit()
        return {"inserted_articles": inserted, "linked_assets": linked, "sentiment_rows": analyzed}

    def _fetch_source(self, source: dict, cutoff: datetime, limit: int) -> list[dict]:
        try:
            response = requests.get(source["url"], headers=HEADERS, timeout=8)
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
        except Exception:
            return []
        rows: list[dict] = []
        for entry in parsed.entries[:limit]:
            title = clean_text(entry.get("title", ""), 260)
            if not title:
                continue
            summary = clean_text(entry.get("summary", ""), 600)
            published = parse_entry_time(entry)
            if published and published < cutoff:
                continue
            url = entry.get("link", "") or stable_url(source["url"], title)
            rows.append(
                {
                    "source": clean_text(parsed.feed.get("title", source["name"]), 160),
                    "source_url": source["url"],
                    "published_at": published,
                    "title": title,
                    "summary": summary,
                    "body": "",
                    "url": url,
                    "canonical_key": canonical_key(title, url),
                    "quality_score": quality_score(title, summary, source["tier"]),
                    "theme_tags": {"themes": classify_themes(title, summary), "desk": source["desk"], "tier": source["tier"]},
                }
            )
        return rows

    def _match_assets(self, article: NewsArticle, assets: list[Asset]) -> list[tuple[Asset, float]]:
        text = f" {article.title} {article.summary} ".lower()
        matches: list[tuple[Asset, float]] = []
        for asset in assets:
            score = 0.0
            ticker = asset.ticker.lower()
            if re.search(rf"[^a-z0-9]{re.escape(ticker)}[^a-z0-9]", text):
                score += 5
            for token in asset.name.lower().replace(".", "").split():
                if len(token) > 4 and token in text:
                    score += 1.5
            if asset.sector.lower() in text:
                score += 1.0
            if asset.industry.lower() and asset.industry.lower() in text:
                score += 1.0
            if score > 0:
                matches.append((asset, score))
        return sorted(matches, key=lambda item: item[1], reverse=True)[:8]


def clean_text(value: str, limit: int) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rstrip()


def parse_entry_time(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
    return None


def canonical_key(title: str, url: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    digest = hashlib.sha256(f"{normalized}|{url}".encode("utf-8")).hexdigest()[:20]
    return f"{normalized[:180]}:{digest}"


def stable_url(feed_url: str, title: str) -> str:
    return f"{feed_url}#{hashlib.sha1(title.encode('utf-8')).hexdigest()[:12]}"


def classify_themes(title: str, summary: str) -> list[str]:
    text = f"{title} {summary}".lower()
    themes = [theme for theme, terms in THEME_KEYWORDS.items() if any(term in text for term in terms)]
    return themes or ["Market Structure"]


def quality_score(title: str, summary: str, tier: int) -> float:
    score = 35 + max(0, 4 - int(tier)) * 10
    score += min(len(summary) / 80, 10)
    score += 8 if any(word in f"{title} {summary}".lower() for word in ["earnings", "guidance", "fed", "revenue", "margins", "forecast"]) else 0
    return round(max(0, min(100, score)), 1)

