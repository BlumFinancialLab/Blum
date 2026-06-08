import math
from datetime import datetime, timedelta, timezone

import feedparser
import gradio as gr
import pandas as pd
import requests
import yfinance as yf
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer


DEFAULT_RSS_FEEDS = [
    "https://www.investing.com/rss/news.rss",
    "https://www.marketwatch.com/rss/topstories",
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://finance.yahoo.com/news/rssindex",
]

ETF_KEYWORDS = {
    "SPY": ["s&p 500", "sp 500", "large cap", "us stocks"],
    "QQQ": ["nasdaq", "technology", "mega cap", "growth stocks"],
    "IWM": ["russell 2000", "small cap"],
    "DIA": ["dow jones", "industrials"],
    "TLT": ["treasury", "bonds", "rates", "duration"],
    "GLD": ["gold", "precious metals"],
    "XLF": ["banks", "financials", "credit"],
    "XLK": ["software", "semiconductors", "technology"],
    "XLE": ["oil", "energy", "gas"],
}


analyzer = SentimentIntensityAnalyzer()


def normalize_symbols(symbols_text):
    raw = symbols_text.replace("\n", ",").replace(";", ",").split(",")
    symbols = []
    for item in raw:
        symbol = item.strip().upper()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols[:25]


def fetch_rss_items(feed_urls, lookback_hours):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    rows = []

    for url in feed_urls:
        url = url.strip()
        if not url:
            continue

        parsed = feedparser.parse(url)
        source = parsed.feed.get("title", url)

        for entry in parsed.entries[:80]:
            published = None
            if getattr(entry, "published_parsed", None):
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            elif getattr(entry, "updated_parsed", None):
                published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

            if published and published < cutoff:
                continue

            title = entry.get("title", "").strip()
            summary = entry.get("summary", "").strip()
            link = entry.get("link", "").strip()
            text = f"{title}. {summary}"
            score = analyzer.polarity_scores(text)["compound"]

            rows.append(
                {
                    "source": source,
                    "published": published.isoformat() if published else "",
                    "title": title,
                    "summary": summary[:400],
                    "url": link,
                    "sentiment": score,
                }
            )

    return pd.DataFrame(rows).drop_duplicates(subset=["title", "url"])


def keyword_match_score(symbol, text):
    symbol = symbol.upper()
    lowered = text.lower()
    score = 0

    if symbol.lower() in lowered:
        score += 3

    for keyword in ETF_KEYWORDS.get(symbol, []):
        if keyword in lowered:
            score += 1

    return score