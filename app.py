import html
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import feedparser
import gradio as gr
import pandas as pd
import plotly.graph_objects as go
import requests
import yfinance as yf
from plotly.subplots import make_subplots
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer


APP_TITLE = "Blum Alpha Terminal"
FRONTEND_POLL_SECONDS = 20
NEWS_REFRESH_SECONDS = 75
PRICE_REFRESH_SECONDS = 150
FULL_REFRESH_SECONDS = 300
HISTORY_PRICE_REFRESH_SECONDS = 1800
MAX_HISTORY_PERIOD = "max"
MAX_NEWS_PER_FEED = 35
MAX_SOURCE_WORKERS = 18
FEED_TIMEOUT_SECONDS = 7

SOURCE_CATALOG = [
    {"name": "Yahoo Finance", "url": "https://finance.yahoo.com/news/rssindex", "desk": "Markets", "tier": 1},
    {"name": "CNBC Top News", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "desk": "Markets", "tier": 1},
    {"name": "CNBC Markets", "url": "https://www.cnbc.com/id/15839135/device/rss/rss.html", "desk": "Markets", "tier": 1},
    {"name": "MarketWatch Top Stories", "url": "https://www.marketwatch.com/rss/topstories", "desk": "Markets", "tier": 1},
    {"name": "MarketWatch Real-Time", "url": "https://www.marketwatch.com/rss/realtimeheadlines", "desk": "Markets", "tier": 1},
    {"name": "WSJ Markets", "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml", "desk": "Markets", "tier": 1},
    {"name": "WSJ World", "url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml", "desk": "Macro", "tier": 1},
    {"name": "Investing.com News", "url": "https://www.investing.com/rss/news.rss", "desk": "Markets", "tier": 2},
    {"name": "Seeking Alpha Market Currents", "url": "https://seekingalpha.com/market_currents.xml", "desk": "Markets", "tier": 2},
    {"name": "Nasdaq Markets", "url": "https://www.nasdaq.com/feed/rssoutbound?category=Markets", "desk": "Markets", "tier": 2},
    {"name": "Nasdaq Stocks", "url": "https://www.nasdaq.com/feed/rssoutbound?category=Stocks", "desk": "Equities", "tier": 2},
    {"name": "Financial Times Home", "url": "https://www.ft.com/rss/home", "desk": "Macro", "tier": 1},
    {"name": "New York Times Business", "url": "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", "desk": "Business", "tier": 1},
    {"name": "New York Times Economy", "url": "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml", "desk": "Macro", "tier": 1},
    {"name": "BBC Business", "url": "https://feeds.bbci.co.uk/news/business/rss.xml", "desk": "Business", "tier": 1},
    {"name": "NPR Business", "url": "https://feeds.npr.org/1006/rss.xml", "desk": "Business", "tier": 2},
    {"name": "The Guardian Business", "url": "https://www.theguardian.com/uk/business/rss", "desk": "Business", "tier": 2},
    {"name": "AP Business", "url": "https://apnews.com/hub/business?output=rss", "desk": "Business", "tier": 1},
    {"name": "Federal Reserve Press", "url": "https://www.federalreserve.gov/feeds/press_all.xml", "desk": "Rates", "tier": 1},
    {"name": "Federal Reserve Speeches", "url": "https://www.federalreserve.gov/feeds/speeches.xml", "desk": "Rates", "tier": 1},
    {"name": "SEC Press Releases", "url": "https://www.sec.gov/news/pressreleases.rss", "desk": "Regulatory", "tier": 1},
    {"name": "SEC Speeches and Statements", "url": "https://www.sec.gov/news/speeches-statements.rss", "desk": "Regulatory", "tier": 1},
    {"name": "SEC Litigation Releases", "url": "https://www.sec.gov/enforcement-litigation/litigation-releases/rss", "desk": "Regulatory", "tier": 2},
    {"name": "IMF News", "url": "https://www.imf.org/en/news/rss", "desk": "Macro", "tier": 2},
    {"name": "ECB Press", "url": "https://www.ecb.europa.eu/rss/press.html", "desk": "Rates", "tier": 2},
    {"name": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "desk": "Crypto", "tier": 2},
    {"name": "Cointelegraph", "url": "https://cointelegraph.com/rss", "desk": "Crypto", "tier": 3},
    {"name": "Oilprice", "url": "https://oilprice.com/rss/main", "desk": "Commodities", "tier": 2},
    {"name": "PR Newswire Financial Services", "url": "https://www.prnewswire.com/rss/financial-services-latest-news/financial-services-latest-news-list.rss", "desk": "Company News", "tier": 3},
    {"name": "PR Newswire Earnings", "url": "https://www.prnewswire.com/rss/earnings-latest-news/earnings-latest-news-list.rss", "desk": "Earnings", "tier": 3},
    {"name": "Business Wire Finance", "url": "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeGVtQWA==", "desk": "Company News", "tier": 3},
    {"name": "TechCrunch Fintech", "url": "https://techcrunch.com/category/fintech/feed/", "desk": "Fintech", "tier": 3},
    {"name": "TechCrunch Enterprise", "url": "https://techcrunch.com/category/enterprise/feed/", "desk": "Technology", "tier": 3},
]

DEFAULT_FEEDS = [source["url"] for source in SOURCE_CATALOG]
CHART_SYMBOLS = ["SPY", "QQQ", "IWM", "SMH", "XLF", "XLE", "TLT", "GLD"]

ASSET_UNIVERSE = [
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "type": "ETF", "sector": "US Equity", "theme": "Broad US large cap", "aliases": ["s&p 500", "sp 500", "large cap", "wall street", "us stocks"]},
    {"symbol": "QQQ", "name": "Invesco QQQ Trust", "type": "ETF", "sector": "Technology", "theme": "Nasdaq growth", "aliases": ["nasdaq", "mega cap", "growth stocks", "technology stocks"]},
    {"symbol": "IWM", "name": "iShares Russell 2000 ETF", "type": "ETF", "sector": "Small Caps", "theme": "US small caps", "aliases": ["russell 2000", "small cap", "regional banks"]},
    {"symbol": "DIA", "name": "SPDR Dow Jones Industrial Average ETF", "type": "ETF", "sector": "US Equity", "theme": "Dow industrials", "aliases": ["dow jones", "industrials", "blue chips"]},
    {"symbol": "VTI", "name": "Vanguard Total Stock Market ETF", "type": "ETF", "sector": "US Equity", "theme": "Total US market", "aliases": ["total market", "us market", "equities"]},
    {"symbol": "SMH", "name": "VanEck Semiconductor ETF", "type": "ETF", "sector": "Semiconductors", "theme": "AI and chips", "aliases": ["semiconductor", "semiconductors", "chips", "ai chips", "gpu"]},
    {"symbol": "XLK", "name": "Technology Select Sector SPDR", "type": "ETF", "sector": "Technology", "theme": "Software and hardware", "aliases": ["technology", "software", "cloud", "chips"]},
    {"symbol": "XLC", "name": "Communication Services Select Sector SPDR", "type": "ETF", "sector": "Communication", "theme": "Media and internet", "aliases": ["media", "internet", "advertising", "streaming"]},
    {"symbol": "XLF", "name": "Financial Select Sector SPDR", "type": "ETF", "sector": "Financials", "theme": "Banks and brokers", "aliases": ["banks", "financials", "credit", "lending"]},
    {"symbol": "XLE", "name": "Energy Select Sector SPDR", "type": "ETF", "sector": "Energy", "theme": "Oil and gas", "aliases": ["oil", "energy", "crude", "gas", "opec"]},
    {"symbol": "XLV", "name": "Health Care Select Sector SPDR", "type": "ETF", "sector": "Healthcare", "theme": "Healthcare", "aliases": ["healthcare", "pharma", "biotech", "drug"]},
    {"symbol": "XLY", "name": "Consumer Discretionary Select Sector SPDR", "type": "ETF", "sector": "Consumer", "theme": "Consumer discretionary", "aliases": ["consumer", "retail", "spending", "autos"]},
    {"symbol": "XLP", "name": "Consumer Staples Select Sector SPDR", "type": "ETF", "sector": "Staples", "theme": "Defensive consumer", "aliases": ["staples", "groceries", "defensive"]},
    {"symbol": "XLI", "name": "Industrial Select Sector SPDR", "type": "ETF", "sector": "Industrials", "theme": "Industrial cycle", "aliases": ["industrial", "manufacturing", "aerospace"]},
    {"symbol": "XLU", "name": "Utilities Select Sector SPDR", "type": "ETF", "sector": "Utilities", "theme": "Defensive yield", "aliases": ["utilities", "power", "electricity", "grid"]},
    {"symbol": "XLB", "name": "Materials Select Sector SPDR", "type": "ETF", "sector": "Materials", "theme": "Materials cycle", "aliases": ["materials", "chemicals", "metals", "mining"]},
    {"symbol": "TLT", "name": "iShares 20+ Year Treasury Bond ETF", "type": "ETF", "sector": "Rates", "theme": "Long duration bonds", "aliases": ["treasury", "treasuries", "bonds", "yields", "rates", "duration"]},
    {"symbol": "HYG", "name": "iShares High Yield Corporate Bond ETF", "type": "ETF", "sector": "Credit", "theme": "High yield credit", "aliases": ["high yield", "junk bonds", "credit spreads", "credit"]},
    {"symbol": "LQD", "name": "iShares Investment Grade Corporate Bond ETF", "type": "ETF", "sector": "Credit", "theme": "Investment grade credit", "aliases": ["investment grade", "corporate bonds", "credit"]},
    {"symbol": "GLD", "name": "SPDR Gold Shares", "type": "ETF", "sector": "Commodities", "theme": "Gold", "aliases": ["gold", "precious metals", "safe haven"]},
    {"symbol": "USO", "name": "United States Oil Fund", "type": "ETF", "sector": "Commodities", "theme": "Crude oil", "aliases": ["oil", "crude", "wti", "brent", "opec"]},
    {"symbol": "VNQ", "name": "Vanguard Real Estate ETF", "type": "ETF", "sector": "Real Estate", "theme": "REITs", "aliases": ["reit", "real estate", "commercial property"]},
    {"symbol": "ARKK", "name": "ARK Innovation ETF", "type": "ETF", "sector": "Innovation", "theme": "High beta innovation", "aliases": ["innovation", "disruption", "growth", "high beta"]},
    {"symbol": "AAPL", "name": "Apple", "type": "Stock", "sector": "Technology", "theme": "Consumer devices and services", "aliases": ["apple", "iphone", "ios", "app store"]},
    {"symbol": "MSFT", "name": "Microsoft", "type": "Stock", "sector": "Technology", "theme": "Cloud and AI software", "aliases": ["microsoft", "azure", "copilot", "openai", "cloud"]},
    {"symbol": "NVDA", "name": "NVIDIA", "type": "Stock", "sector": "Semiconductors", "theme": "AI accelerators", "aliases": ["nvidia", "gpu", "ai chips", "blackwell", "cuda"]},
    {"symbol": "AMD", "name": "Advanced Micro Devices", "type": "Stock", "sector": "Semiconductors", "theme": "AI and CPUs", "aliases": ["amd", "advanced micro", "mi300", "cpu", "gpu"]},
    {"symbol": "AVGO", "name": "Broadcom", "type": "Stock", "sector": "Semiconductors", "theme": "Networking and custom silicon", "aliases": ["broadcom", "custom silicon", "networking chips", "vmware"]},
    {"symbol": "AMZN", "name": "Amazon", "type": "Stock", "sector": "Consumer", "theme": "E-commerce and cloud", "aliases": ["amazon", "aws", "e-commerce", "prime"]},
    {"symbol": "GOOGL", "name": "Alphabet", "type": "Stock", "sector": "Communication", "theme": "Search, ads and AI", "aliases": ["alphabet", "google", "youtube", "gemini", "search"]},
    {"symbol": "META", "name": "Meta Platforms", "type": "Stock", "sector": "Communication", "theme": "Social, ads and AI", "aliases": ["meta", "facebook", "instagram", "whatsapp", "reels"]},
    {"symbol": "TSLA", "name": "Tesla", "type": "Stock", "sector": "Consumer", "theme": "EVs and autonomy", "aliases": ["tesla", "ev", "electric vehicle", "autonomy", "robotaxi"]},
    {"symbol": "JPM", "name": "JPMorgan Chase", "type": "Stock", "sector": "Financials", "theme": "Money-center banking", "aliases": ["jpmorgan", "jpm", "bank", "credit"]},
    {"symbol": "BAC", "name": "Bank of America", "type": "Stock", "sector": "Financials", "theme": "Rate-sensitive banking", "aliases": ["bank of america", "bofa", "banks", "deposit"]},
    {"symbol": "GS", "name": "Goldman Sachs", "type": "Stock", "sector": "Financials", "theme": "Investment banking", "aliases": ["goldman", "investment banking", "trading revenue"]},
    {"symbol": "XOM", "name": "Exxon Mobil", "type": "Stock", "sector": "Energy", "theme": "Integrated oil", "aliases": ["exxon", "oil major", "energy"]},
    {"symbol": "CVX", "name": "Chevron", "type": "Stock", "sector": "Energy", "theme": "Integrated oil", "aliases": ["chevron", "oil major", "energy"]},
    {"symbol": "LLY", "name": "Eli Lilly", "type": "Stock", "sector": "Healthcare", "theme": "Obesity and diabetes drugs", "aliases": ["eli lilly", "lilly", "zepbound", "mounjaro", "glp-1"]},
    {"symbol": "UNH", "name": "UnitedHealth Group", "type": "Stock", "sector": "Healthcare", "theme": "Managed care", "aliases": ["unitedhealth", "optum", "managed care", "medicare"]},
    {"symbol": "COST", "name": "Costco", "type": "Stock", "sector": "Staples", "theme": "Membership retail", "aliases": ["costco", "membership", "warehouse retail"]},
    {"symbol": "WMT", "name": "Walmart", "type": "Stock", "sector": "Staples", "theme": "Value retail", "aliases": ["walmart", "retail", "groceries"]},
]

THEME_KEYWORDS = {
    "AI & Semiconductors": ["ai", "artificial intelligence", "chip", "chips", "semiconductor", "gpu", "data center", "datacenter", "nvidia", "broadcom", "amd"],
    "Rates & Bonds": ["fed", "federal reserve", "rate", "rates", "yield", "yields", "treasury", "inflation", "cpi", "pce", "bond"],
    "Credit & Banks": ["credit", "bank", "banks", "loan", "lending", "deposits", "default", "high yield", "spreads"],
    "Energy & Commodities": ["oil", "crude", "brent", "wti", "gas", "energy", "opec", "gold", "copper", "commodity"],
    "Consumer": ["consumer", "retail", "spending", "sales", "walmart", "costco", "amazon", "tesla", "autos"],
    "Healthcare": ["healthcare", "drug", "pharma", "biotech", "medicare", "glp-1", "obesity", "lilly"],
    "Macro & Index": ["stocks", "market", "wall street", "s&p", "nasdaq", "dow", "futures", "recession", "growth"],
    "Earnings & Guidance": ["earnings", "revenue", "profit", "guidance", "margin", "forecast", "estimates", "results"],
    "Geopolitics & Policy": ["tariff", "sanction", "war", "election", "policy", "regulation", "china", "russia", "middle east"],
}

FINANCIAL_RELEVANCE_TERMS = [
    "stock", "stocks", "shares", "equity", "market", "markets", "futures", "etf", "fund",
    "bond", "bonds", "treasury", "yield", "yields", "rate", "rates", "fed", "central bank",
    "inflation", "cpi", "pce", "gdp", "jobs", "payrolls", "recession", "growth",
    "earnings", "revenue", "profit", "margin", "guidance", "forecast", "estimate",
    "analyst", "upgrade", "downgrade", "valuation", "multiple", "cash flow",
    "oil", "gold", "commodity", "credit", "spread", "default", "bank", "loan",
    "merger", "acquisition", "ipo", "buyback", "dividend", "sec", "regulation",
]

NOISE_TERMS = [
    "celebrity", "movie", "recipe", "sports", "lottery", "crime", "weather",
    "royal", "fashion", "travel tips", "lifestyle", "dating",
]

CATALYST_KEYWORDS = {
    "Earnings / Guidance": ["earnings", "results", "revenue", "profit", "margin", "guidance", "forecast", "estimates"],
    "Rates / Macro": ["fed", "rate", "rates", "yield", "treasury", "inflation", "cpi", "pce", "payrolls", "gdp"],
    "Credit / Liquidity": ["credit", "spread", "spreads", "default", "liquidity", "deposit", "loan", "lending"],
    "Commodity Shock": ["oil", "crude", "brent", "wti", "gas", "gold", "copper", "opec"],
    "Policy / Regulation": ["sec", "regulator", "regulation", "tariff", "sanction", "policy", "antitrust"],
    "Corporate Action": ["merger", "acquisition", "takeover", "ipo", "buyback", "dividend", "spinoff"],
    "AI / Capex Cycle": ["ai", "artificial intelligence", "gpu", "chip", "semiconductor", "data center", "datacenter"],
    "Risk Event": ["lawsuit", "probe", "investigation", "warning", "cuts", "bankruptcy", "downgrade"],
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

analyzer = SentimentIntensityAnalyzer()
_PRICE_CACHE_LOCK = threading.RLock()
_PRICE_CACHE = {}


def clamp(value, low=0.0, high=100.0):
    if value is None or pd.isna(value):
        return low
    number = float(value)
    if not math.isfinite(number):
        return low
    return max(low, min(high, number))


def scale(value, low, high):
    if value is None or pd.isna(value) or high == low:
        return 50.0
    return clamp((float(value) - low) / (high - low) * 100.0)


def safe_float(value, default=math.nan):
    try:
        if pd.isna(value):
            return default
        number = float(value)
        if not math.isfinite(number):
            return default
        return number
    except (TypeError, ValueError):
        return default


def clean_text(value, limit=None):
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        return text[: limit - 1].rstrip() + "..."
    return text


def canonical_title(title):
    text = re.sub(r"[^a-z0-9]+", " ", str(title).lower()).strip()
    text = re.sub(r"\b(breaking|update|exclusive|analysis|morning bid)\b", "", text)
    return re.sub(r"\s+", " ", text)[:150]


def source_catalog_text():
    return "\n".join(source["url"] for source in SOURCE_CATALOG)


def source_meta(url):
    normalized = url.strip()
    for source in SOURCE_CATALOG:
        if source["url"] == normalized:
            return dict(source)
    return {"name": normalized, "url": normalized, "desk": "Custom", "tier": 3}


def parse_sources(rss_text):
    sources = []
    seen = set()
    for line in rss_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            url = line.split("|")[-1].strip()
        else:
            url = line
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        sources.append(source_meta(url))
    return sources


def now_label():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def normalize_symbols(symbols_text):
    parts = re.split(r"[\s,;]+", symbols_text.upper())
    output = []
    for part in parts:
        symbol = part.strip().replace("$", "")
        if symbol and symbol not in output and re.match(r"^[A-Z0-9.\-]{1,12}$", symbol):
            output.append(symbol)
    return output


def selected_universe(mode, custom_symbols):
    base = list(ASSET_UNIVERSE)
    custom = normalize_symbols(custom_symbols)

    if mode == "AI / Semis":
        base = [a for a in ASSET_UNIVERSE if a["sector"] in {"Semiconductors", "Technology"} or a["symbol"] in {"QQQ", "SMH", "ARKK"}]
    elif mode == "Macro ETFs":
        base = [a for a in ASSET_UNIVERSE if a["type"] == "ETF"]
    elif mode == "Mega-cap stocks":
        base = [a for a in ASSET_UNIVERSE if a["type"] == "Stock"]

    by_symbol = {asset["symbol"]: dict(asset) for asset in base}
    known = {asset["symbol"]: asset for asset in ASSET_UNIVERSE}
    for symbol in custom:
        if symbol in known:
            by_symbol[symbol] = dict(known[symbol])
        else:
            by_symbol[symbol] = {
                "symbol": symbol,
                "name": symbol,
                "type": "Stock/ETF",
                "sector": "Custom",
                "theme": "User-added instrument",
                "aliases": [symbol.lower()],
            }

    return list(by_symbol.values())[:70]


def sentiment_label(score):
    if score >= 0.22:
        return "Positive"
    if score <= -0.22:
        return "Negative"
    return "Neutral"


def classify_themes(title, summary):
    text = f"{title} {summary}".lower()
    themes = []
    for theme, keywords in THEME_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            themes.append(theme)
    return themes or ["Macro & Index"]


def catalyst_class(title, summary):
    text = f"{title} {summary}".lower()
    scored = []
    for catalyst, keywords in CATALYST_KEYWORDS.items():
        hits = sum(1 for keyword in keywords if keyword in text)
        if hits:
            scored.append((hits, catalyst))
    if not scored:
        return "General Market Signal"
    return sorted(scored, reverse=True)[0][1]


def news_quality_score(title, summary, themes, catalyst, source_tier):
    text = f"{title} {summary}".lower()
    score = 12
    score += max(0, 4 - int(source_tier)) * 7
    score += min(len(themes), 4) * 8
    score += 14 if catalyst != "General Market Signal" else 4
    score += min(sum(1 for term in FINANCIAL_RELEVANCE_TERMS if term in text), 8) * 5
    score -= sum(1 for term in NOISE_TERMS if term in text) * 12
    if len(title) < 28:
        score -= 8
    if len(summary) > 80:
        score += 5
    return round(clamp(score, 0, 100), 1)


def fetch_feed(source, lookback_hours):
    url = source["url"]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=int(lookback_hours))
    try:
        response = requests.get(url, headers=HEADERS, timeout=FEED_TIMEOUT_SECONDS)
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
    except Exception as exc:
        return [], f"{source['name']}: {clean_text(exc, 130)}"

    source_name = clean_text(parsed.feed.get("title", source["name"]), 80)
    rows = []
    for entry in parsed.entries[:MAX_NEWS_PER_FEED]:
        published = None
        if getattr(entry, "published_parsed", None):
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        elif getattr(entry, "updated_parsed", None):
            published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

        if published and published < cutoff:
            continue

        title = clean_text(entry.get("title", ""), 220)
        if not title:
            continue
        summary = clean_text(entry.get("summary", ""), 320)
        text = f"{title}. {summary}"
        score = analyzer.polarity_scores(text)["compound"]
        themes = classify_themes(title, summary)
        catalyst = catalyst_class(title, summary)
        quality = news_quality_score(title, summary, themes, catalyst, source["tier"])
        if quality < 28:
            continue
        rows.append(
            {
                "time": published.strftime("%Y-%m-%d %H:%M") if published else "latest",
                "source": source_name,
                "source_url": url,
                "source_desk": source["desk"],
                "source_tier": source["tier"],
                "title": title,
                "summary": summary,
                "url": entry.get("link", ""),
                "sentiment": round(float(score), 3),
                "sentiment_label": sentiment_label(score),
                "themes": ", ".join(themes),
                "catalyst_class": catalyst,
                "quality_score": quality,
                "canonical_key": canonical_title(title),
            }
        )
    return rows, None


def fetch_news(sources, lookback_hours):
    rows = []
    warnings = []
    source_report = []
    if not sources:
        empty_cols = ["time", "source", "source_url", "source_desk", "source_tier", "title", "summary", "url", "sentiment", "sentiment_label", "themes", "catalyst_class", "quality_score", "canonical_key"]
        return pd.DataFrame(columns=empty_cols), ["No RSS sources configured."], pd.DataFrame()

    with ThreadPoolExecutor(max_workers=min(MAX_SOURCE_WORKERS, len(sources))) as executor:
        futures = {executor.submit(fetch_feed, source, lookback_hours): source for source in sources}
        for future in as_completed(futures):
            source = futures[future]
            try:
                items, warning = future.result()
            except Exception as exc:
                items, warning = [], f"{source['name']}: {clean_text(exc, 130)}"
            rows.extend(items)
            if warning:
                warnings.append(warning)
            source_report.append(
                {
                    "source": source["name"],
                    "desk": source["desk"],
                    "tier": source["tier"],
                    "status": "active" if items else "empty/error",
                    "headlines": len(items),
                    "url": source["url"],
                    "warning": warning or "",
                }
            )

    report = pd.DataFrame(source_report).sort_values(["status", "headlines"], ascending=[True, False])
    if not rows:
        empty_cols = ["time", "source", "source_url", "source_desk", "source_tier", "title", "summary", "url", "sentiment", "sentiment_label", "themes", "catalyst_class", "quality_score", "canonical_key"]
        return pd.DataFrame(columns=empty_cols), warnings, report

    news = pd.DataFrame(rows)
    news = news.sort_values(["quality_score", "sentiment"], ascending=[False, False])
    news = news.drop_duplicates(subset=["canonical_key"]).drop_duplicates(subset=["title", "url"])
    return news.reset_index(drop=True), warnings, report


def relevance_score(asset, title, summary):
    text = f" {title} {summary} ".lower()
    symbol = asset["symbol"].lower()
    score = 0

    if re.search(rf"[^a-z0-9]{re.escape(symbol)}[^a-z0-9]", text):
        score += 5

    name_tokens = [token for token in re.split(r"[^a-z0-9]+", asset["name"].lower()) if len(token) > 3]
    if name_tokens and all(token in text for token in name_tokens[:2]):
        score += 4

    for alias in asset.get("aliases", []):
        if alias.lower() in text:
            score += 3 if len(alias) > 5 else 2

    sector = asset.get("sector", "").lower()
    theme = asset.get("theme", "").lower()
    if sector and sector in text:
        score += 1
    if any(word in text for word in theme.split() if len(word) > 4):
        score += 1

    return score


def map_news_to_assets(news, assets):
    if news.empty:
        return pd.DataFrame(columns=["symbol", "name", "relevance", "time", "source", "source_desk", "source_tier", "title", "sentiment", "sentiment_label", "themes", "catalyst_class", "quality_score", "url"])

    rows = []
    for asset in assets:
        for _, item in news.iterrows():
            relevance = relevance_score(asset, item["title"], item["summary"])
            if relevance > 0:
                conviction_relevance = int(relevance + max(1, item.get("quality_score", 50) / 18))
                rows.append(
                    {
                        "symbol": asset["symbol"],
                        "name": asset["name"],
                        "relevance": conviction_relevance,
                        "time": item["time"],
                        "source": item["source"],
                        "source_desk": item.get("source_desk", ""),
                        "source_tier": item.get("source_tier", ""),
                        "title": item["title"],
                        "sentiment": item["sentiment"],
                        "sentiment_label": item["sentiment_label"],
                        "themes": item["themes"],
                        "catalyst_class": item.get("catalyst_class", "General Market Signal"),
                        "quality_score": item.get("quality_score", 0),
                        "url": item["url"],
                    }
                )

    if not rows:
        return pd.DataFrame(columns=["symbol", "name", "relevance", "time", "source", "source_desk", "source_tier", "title", "sentiment", "sentiment_label", "themes", "catalyst_class", "quality_score", "url"])
    return pd.DataFrame(rows)


def fetch_prices(symbols, period=MAX_HISTORY_PERIOD, interval="1d"):
    if not symbols:
        return {}

    key = (tuple(sorted(set(symbols))), period, interval)
    ttl = HISTORY_PRICE_REFRESH_SECONDS if period == MAX_HISTORY_PERIOD and interval == "1d" else PRICE_REFRESH_SECONDS
    with _PRICE_CACHE_LOCK:
        cached = _PRICE_CACHE.get(key)
        if cached and time.time() - cached["timestamp"] < ttl:
            return {symbol: frame.copy() for symbol, frame in cached["frames"].items() if symbol in symbols}

    try:
        data = yf.download(
            tickers=" ".join(symbols),
            period=period,
            interval=interval,
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception:
        data = pd.DataFrame()

    frames = {}
    if data is None or data.empty:
        return frames

    for symbol in symbols:
        try:
            if isinstance(data.columns, pd.MultiIndex):
                if symbol in data.columns.get_level_values(0):
                    frame = data[symbol].copy()
                elif symbol in data.columns.get_level_values(-1):
                    frame = data.xs(symbol, axis=1, level=-1).copy()
                else:
                    continue
            else:
                frame = data.copy()

            if "Close" not in frame:
                continue
            frame = frame[["Open", "High", "Low", "Close", "Volume"]].apply(pd.to_numeric, errors="coerce")
            frame = frame.dropna(subset=["Close"])
            if not frame.empty:
                frames[symbol] = frame
        except Exception:
            continue

    with _PRICE_CACHE_LOCK:
        _PRICE_CACHE[key] = {
            "timestamp": time.time(),
            "frames": {symbol: frame.copy() for symbol, frame in frames.items()},
        }

    return frames


def fetch_yahoo_intraday_symbol(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": "5d", "interval": "5m", "includePrePost": "false"}
    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=7)
        response.raise_for_status()
        payload = response.json()
        result = payload.get("chart", {}).get("result", [])
        if not result:
            return symbol, pd.DataFrame()
        data = result[0]
        timestamps = data.get("timestamp", [])
        quote = data.get("indicators", {}).get("quote", [{}])[0]
        if not timestamps or not quote:
            return symbol, pd.DataFrame()
        frame = pd.DataFrame(
            {
                "Open": quote.get("open", []),
                "High": quote.get("high", []),
                "Low": quote.get("low", []),
                "Close": quote.get("close", []),
                "Volume": quote.get("volume", []),
            },
            index=pd.to_datetime(timestamps, unit="s", utc=True),
        )
        frame = frame.apply(pd.to_numeric, errors="coerce").dropna(subset=["Close"])
        return symbol, frame
    except Exception:
        return symbol, pd.DataFrame()


def fetch_intraday_prices(symbols):
    frames = {}
    if not symbols:
        return frames
    with ThreadPoolExecutor(max_workers=min(8, len(symbols))) as executor:
        futures = [executor.submit(fetch_yahoo_intraday_symbol, symbol) for symbol in symbols]
        for future in as_completed(futures):
            symbol, frame = future.result()
            if frame is not None and not frame.empty:
                frames[symbol] = frame
    return frames


def rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, math.nan)
    return 100 - (100 / (1 + rs))


def return_pct(close, periods):
    if len(close) <= periods:
        return math.nan
    base = safe_float(close.iloc[-periods - 1])
    latest = safe_float(close.iloc[-1])
    if base == 0 or pd.isna(base) or pd.isna(latest):
        return math.nan
    return (latest / base - 1) * 100


def rounded(value, digits=2):
    number = safe_float(value)
    if pd.isna(number):
        return None
    return round(number, digits)


def percent_from_ratio(value):
    number = safe_float(value)
    if pd.isna(number):
        return math.nan
    return number * 100


def history_years(close):
    if close is None or len(close) < 2:
        return math.nan
    try:
        days = (pd.Timestamp(close.index[-1]) - pd.Timestamp(close.index[0])).days
    except Exception:
        days = 0
    if days and days > 0:
        return days / 365.25
    return len(close) / 252


def inception_label(close):
    if close is None or close.empty:
        return "n/a"
    try:
        return pd.Timestamp(close.index[0]).strftime("%Y-%m-%d")
    except Exception:
        return "n/a"


def all_time_cagr(close):
    if close is None or len(close) < 2:
        return math.nan
    first = safe_float(close.iloc[0])
    latest = safe_float(close.iloc[-1])
    years = history_years(close)
    if first <= 0 or latest <= 0 or pd.isna(years) or years <= 0:
        return math.nan
    return ((latest / first) ** (1 / years) - 1) * 100


def max_drawdown_pct(close):
    if close is None or close.empty:
        return math.nan
    running_high = close.cummax()
    drawdowns = (close / running_high - 1) * 100
    return safe_float(drawdowns.min())


def ulcer_index(close):
    if close is None or close.empty:
        return math.nan
    drawdowns = (close / close.cummax() - 1) * 100
    return safe_float(math.sqrt(float((drawdowns.pow(2)).mean())))


def annualized_sharpe(returns):
    if returns is None or len(returns) < 30:
        return math.nan
    std = safe_float(returns.std())
    if std <= 0:
        return math.nan
    return safe_float((returns.mean() / std) * math.sqrt(252))


def annualized_sortino(returns):
    if returns is None or len(returns) < 30:
        return math.nan
    downside = returns[returns < 0]
    downside_std = safe_float(downside.std())
    if downside.empty or downside_std <= 0:
        return math.nan
    return safe_float((returns.mean() / downside_std) * math.sqrt(252))


def benchmark_profile(close, benchmark_close):
    blank = {
        "beta_spy": None,
        "corr_spy": None,
        "relative_strength_1y": None,
        "information_ratio_1y": None,
        "up_capture_spy": None,
        "down_capture_spy": None,
    }
    if benchmark_close is None or close is None or benchmark_close.empty or close.empty:
        return blank

    paired = pd.concat(
        [
            close.pct_change().rename("asset"),
            benchmark_close.pct_change().rename("benchmark"),
        ],
        axis=1,
        join="inner",
    ).replace([math.inf, -math.inf], math.nan).dropna()

    if len(paired) < 60:
        return blank

    recent = paired.tail(min(252, len(paired)))
    bench_var = safe_float(recent["benchmark"].var())
    beta = safe_float(recent["asset"].cov(recent["benchmark"]) / bench_var) if bench_var > 0 else math.nan
    corr = safe_float(recent["asset"].corr(recent["benchmark"]))
    active = recent["asset"] - recent["benchmark"]
    active_std = safe_float(active.std())
    information_ratio = safe_float((active.mean() / active_std) * math.sqrt(252)) if active_std > 0 else math.nan
    asset_window_return = ((1 + recent["asset"]).prod() - 1) * 100
    benchmark_window_return = ((1 + recent["benchmark"]).prod() - 1) * 100
    relative_strength = safe_float(asset_window_return - benchmark_window_return)

    up = recent[recent["benchmark"] > 0]
    down = recent[recent["benchmark"] < 0]
    up_capture = math.nan
    down_capture = math.nan
    up_bench = safe_float(up["benchmark"].mean()) if not up.empty else math.nan
    down_bench = safe_float(down["benchmark"].mean()) if not down.empty else math.nan
    if not pd.isna(up_bench) and up_bench != 0:
        up_capture = safe_float(up["asset"].mean() / up_bench * 100)
    if not pd.isna(down_bench) and down_bench != 0:
        down_capture = safe_float(down["asset"].mean() / down_bench * 100)

    return {
        "beta_spy": rounded(beta, 2),
        "corr_spy": rounded(corr, 2),
        "relative_strength_1y": rounded(relative_strength, 2),
        "information_ratio_1y": rounded(information_ratio, 2),
        "up_capture_spy": rounded(up_capture, 1),
        "down_capture_spy": rounded(down_capture, 1),
    }


def technicals(symbol, frame, benchmark_close=None):
    if frame is None or frame.empty or len(frame) < 50:
        return {"symbol": symbol, "error": "Insufficient price history"}

    close = frame["Close"].dropna()
    volume = frame["Volume"].dropna() if "Volume" in frame else pd.Series(dtype=float)
    returns = close.pct_change().replace([math.inf, -math.inf], math.nan).dropna()
    latest = safe_float(close.iloc[-1])
    sma20 = safe_float(close.rolling(20).mean().iloc[-1])
    sma50 = safe_float(close.rolling(50).mean().iloc[-1])
    sma200 = safe_float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else math.nan
    rsi14 = safe_float(rsi(close).iloc[-1])
    ret1 = return_pct(close, 1)
    ret5 = return_pct(close, 5)
    ret20 = return_pct(close, 20)
    ret63 = return_pct(close, 63)
    ret126 = return_pct(close, 126)
    ret252 = return_pct(close, 252)
    ret504 = return_pct(close, 504)
    ret756 = return_pct(close, 756)
    vol60 = safe_float(close.pct_change().tail(60).std() * math.sqrt(252) * 100)
    vol252 = safe_float(returns.tail(min(252, len(returns))).std() * math.sqrt(252) * 100) if len(returns) >= 30 else math.nan
    high_252 = safe_float(close.tail(min(252, len(close))).max())
    drawdown = ((latest / high_252) - 1) * 100 if high_252 and not pd.isna(high_252) else math.nan
    high_all_time = safe_float(close.max())
    ath_distance = ((latest / high_all_time) - 1) * 100 if high_all_time and not pd.isna(high_all_time) else math.nan
    hist_years = history_years(close)
    cagr = all_time_cagr(close)
    max_drawdown = max_drawdown_pct(close)
    sharpe = annualized_sharpe(returns)
    sortino = annualized_sortino(returns)
    calmar = safe_float((cagr / abs(max_drawdown))) if not pd.isna(cagr) and not pd.isna(max_drawdown) and max_drawdown < 0 else math.nan
    var95_daily = percent_from_ratio(returns.quantile(0.05)) if not returns.empty else math.nan
    tail = returns[returns <= returns.quantile(0.05)] if not returns.empty else pd.Series(dtype=float)
    cvar95_daily = percent_from_ratio(tail.mean()) if not tail.empty else math.nan
    hit_rate = percent_from_ratio((returns > 0).mean()) if not returns.empty else math.nan
    best_day = percent_from_ratio(returns.max()) if not returns.empty else math.nan
    worst_day = percent_from_ratio(returns.min()) if not returns.empty else math.nan
    skew = safe_float(returns.skew()) if len(returns) >= 30 else math.nan
    kurtosis = safe_float(returns.kurtosis()) if len(returns) >= 30 else math.nan
    ulcer = ulcer_index(close)
    benchmark = benchmark_profile(close, benchmark_close)

    if not volume.empty and len(volume) > 20:
        avg_volume = safe_float(volume.tail(21).iloc[:-1].mean())
        volume_shock = safe_float((volume.iloc[-1] / avg_volume - 1) * 100) if avg_volume else 0
    else:
        volume_shock = 0

    trend_score = 0
    trend_score += 1 if latest > sma20 else -1
    trend_score += 1 if latest > sma50 else -1
    if not pd.isna(sma200):
        trend_score += 1 if latest > sma200 else -1

    if rsi14 >= 76:
        technical_view = "Extended"
    elif rsi14 <= 31:
        technical_view = "Oversold"
    elif trend_score >= 2:
        technical_view = "Uptrend"
    elif trend_score <= -2:
        technical_view = "Downtrend"
    else:
        technical_view = "Mixed"

    return {
        "symbol": symbol,
        "last": round(latest, 2),
        "1d": round(ret1, 2) if not pd.isna(ret1) else None,
        "5d": round(ret5, 2) if not pd.isna(ret5) else None,
        "20d": round(ret20, 2) if not pd.isna(ret20) else None,
        "63d": round(ret63, 2) if not pd.isna(ret63) else None,
        "126d": round(ret126, 2) if not pd.isna(ret126) else None,
        "252d": round(ret252, 2) if not pd.isna(ret252) else None,
        "504d": round(ret504, 2) if not pd.isna(ret504) else None,
        "756d": round(ret756, 2) if not pd.isna(ret756) else None,
        "vol60": round(vol60, 2) if not pd.isna(vol60) else None,
        "vol252": rounded(vol252, 2),
        "drawdown_1y": round(drawdown, 2) if not pd.isna(drawdown) else None,
        "history_years": rounded(hist_years, 1),
        "inception_date": inception_label(close),
        "all_time_return": rounded((latest / safe_float(close.iloc[0]) - 1) * 100 if safe_float(close.iloc[0]) > 0 else math.nan, 2),
        "cagr": rounded(cagr, 2),
        "max_drawdown": rounded(max_drawdown, 2),
        "ath_distance": rounded(ath_distance, 2),
        "sharpe": rounded(sharpe, 2),
        "sortino": rounded(sortino, 2),
        "calmar": rounded(calmar, 2),
        "var95_daily": rounded(var95_daily, 2),
        "cvar95_daily": rounded(cvar95_daily, 2),
        "hit_rate": rounded(hit_rate, 1),
        "best_day": rounded(best_day, 2),
        "worst_day": rounded(worst_day, 2),
        "skew": rounded(skew, 2),
        "kurtosis": rounded(kurtosis, 2),
        "ulcer_index": rounded(ulcer, 2),
        "volume_shock": round(volume_shock, 2),
        "sma20": round(sma20, 2),
        "sma50": round(sma50, 2),
        "sma200": round(sma200, 2) if not pd.isna(sma200) else None,
        "rsi14": round(rsi14, 1) if not pd.isna(rsi14) else None,
        "trend_score": trend_score,
        "technical_view": technical_view,
        **benchmark,
        "error": "",
    }


def theme_sentiment(news):
    rows = []
    for theme in THEME_KEYWORDS:
        mask = news["themes"].str.contains(re.escape(theme), na=False) if not news.empty else pd.Series(dtype=bool)
        subset = news[mask] if not news.empty else pd.DataFrame()
        rows.append(
            {
                "theme": theme,
                "headlines": int(len(subset)),
                "avg_sentiment": round(float(subset["sentiment"].mean()), 3) if not subset.empty else 0.0,
            }
        )
    return pd.DataFrame(rows).sort_values(["headlines", "avg_sentiment"], ascending=[False, False])


def asset_news_stats(symbol, matched_news, broad_sentiment):
    subset = matched_news[matched_news["symbol"] == symbol] if not matched_news.empty else pd.DataFrame()
    if subset.empty:
        return {
            "news_count": 0,
            "avg_sentiment": round(broad_sentiment * 0.35, 3),
            "relevance_total": 0,
            "quality_total": 0,
            "source_diversity": 0,
            "top_headline": "No direct headline match; using broad market pulse.",
            "top_source": "Market pulse",
            "top_url": "",
            "themes": "Macro & Index",
            "catalyst_class": "General Market Signal",
        }
    weights = subset["relevance"] * (subset["quality_score"].fillna(50) / 50)
    weighted = (subset["sentiment"] * weights).sum() / max(weights.sum(), 1)
    top = subset.sort_values(["relevance", "quality_score", "sentiment"], ascending=[False, False, False]).iloc[0]
    themes = ", ".join(sorted(set(", ".join(subset["themes"].dropna()).split(", "))))[:120]
    catalyst = subset["catalyst_class"].mode().iloc[0] if "catalyst_class" in subset and not subset["catalyst_class"].empty else "General Market Signal"
    return {
        "news_count": int(len(subset)),
        "avg_sentiment": round(float(weighted), 3),
        "relevance_total": int(subset["relevance"].sum()),
        "quality_total": int(subset["quality_score"].fillna(0).sum()),
        "source_diversity": int(subset["source"].nunique()),
        "top_headline": top["title"],
        "top_source": top["source"],
        "top_url": top["url"],
        "themes": themes or "Macro & Index",
        "catalyst_class": catalyst,
    }


def infer_regime(metrics, broad_sentiment):
    spy = metrics.get("SPY", {})
    qqq = metrics.get("QQQ", {})
    iwm = metrics.get("IWM", {})
    hyg = metrics.get("HYG", {})
    tlt = metrics.get("TLT", {})

    risk_score = 0
    for item in [spy, qqq, iwm, hyg]:
        risk_score += 1 if item.get("trend_score", 0) > 0 else -1
    risk_score += 1 if broad_sentiment > 0.12 else -1 if broad_sentiment < -0.12 else 0
    duration_signal = "duration bid" if tlt.get("trend_score", 0) > 0 else "rates pressure"

    if risk_score >= 3:
        label = "Risk-on"
        stance = "Momentum and cyclicality can be rewarded, but overextension still matters."
    elif risk_score <= -2:
        label = "Risk-off"
        stance = "Favor defensive quality, cash-flow durability and downside controls."
    else:
        label = "Mixed / selective"
        stance = "Selection matters more than beta; require cleaner catalyst and technical confirmation."

    return {
        "label": label,
        "risk_score": risk_score,
        "duration_signal": duration_signal,
        "stance": stance,
    }


def score_asset(asset, tech, news_stats, regime):
    if tech.get("error"):
        return None

    sentiment_component = scale(news_stats["avg_sentiment"], -0.45, 0.45)
    relevance_boost = scale(news_stats["relevance_total"], 0, 18)
    quality_boost = scale(news_stats.get("quality_total", 0), 0, 420)
    diversity_boost = scale(news_stats.get("source_diversity", 0), 0, 6)
    catalyst_boost = 8 if news_stats.get("catalyst_class") != "General Market Signal" else 0
    short_momentum = (scale(tech.get("5d"), -5, 5) * 0.45) + (scale(tech.get("20d"), -10, 10) * 0.55)
    long_momentum = (scale(tech.get("63d"), -15, 18) * 0.25) + (scale(tech.get("126d"), -22, 28) * 0.30) + (scale(tech.get("252d"), -35, 45) * 0.45)
    trend_component = scale(tech.get("trend_score"), -3, 3)
    volume_component = scale(tech.get("volume_shock"), -35, 80)
    volatility_penalty = scale(tech.get("vol60"), 55, 12)
    drawdown_component = scale(tech.get("drawdown_1y"), -35, 0)
    history_depth = scale(tech.get("history_years"), 0.5, 15)
    cagr_component = scale(tech.get("cagr"), -8, 22)
    sharpe_component = scale(tech.get("sharpe"), -0.6, 2.2)
    sortino_component = scale(tech.get("sortino"), -0.8, 3.0)
    calmar_component = scale(tech.get("calmar"), -0.25, 1.6)
    max_drawdown_component = scale(tech.get("max_drawdown"), -72, -8)
    ath_component = scale(tech.get("ath_distance"), -55, 0)
    relative_strength = scale(tech.get("relative_strength_1y"), -25, 25)
    information_component = scale(tech.get("information_ratio_1y"), -1.1, 1.4)
    beta_control = scale(tech.get("beta_spy"), 2.2, 0.55)
    tail_risk = scale(tech.get("var95_daily"), -5.5, -0.8)
    up_capture = scale(tech.get("up_capture_spy"), 45, 130)
    down_capture = scale(tech.get("down_capture_spy"), 155, 55)
    institutional_quality = (
        history_depth * 0.07
        + cagr_component * 0.16
        + sharpe_component * 0.16
        + sortino_component * 0.12
        + calmar_component * 0.12
        + max_drawdown_component * 0.12
        + beta_control * 0.08
        + tail_risk * 0.07
        + up_capture * 0.05
        + down_capture * 0.05
    )
    rsi_value = tech.get("rsi14") or 50
    extension_penalty = 18 if rsi_value > 76 else 8 if rsi_value > 70 else 0
    oversold_bonus = 8 if rsi_value < 32 else 0
    regime_bonus = 5 if regime["label"] == "Risk-on" and asset["sector"] not in {"Utilities", "Staples", "Rates"} else 0
    defensive_bonus = 5 if regime["label"] == "Risk-off" and asset["sector"] in {"Staples", "Healthcare", "Utilities", "Rates", "Commodities"} else 0

    short_score = (
        sentiment_component * 0.25
        + short_momentum * 0.22
        + trend_component * 0.12
        + relative_strength * 0.08
        + information_component * 0.04
        + relevance_boost * 0.08
        + quality_boost * 0.07
        + diversity_boost * 0.05
        + volume_component * 0.07
        + volatility_penalty * 0.05
        + ath_component * 0.04
        + tail_risk * 0.03
        + regime_bonus
        + defensive_bonus
        + catalyst_boost
        + oversold_bonus
        - extension_penalty
    )

    long_score = (
        institutional_quality * 0.28
        + long_momentum * 0.18
        + cagr_component * 0.10
        + sharpe_component * 0.08
        + max_drawdown_component * 0.08
        + relative_strength * 0.07
        + information_component * 0.05
        + trend_component * 0.08
        + sentiment_component * 0.07
        + drawdown_component * 0.04
        + volatility_penalty * 0.04
        + relevance_boost * 0.03
        + quality_boost * 0.04
        + diversity_boost * 0.04
        + regime_bonus * 0.6
        + defensive_bonus * 0.7
        + catalyst_boost * 0.5
    )

    short_score = round(clamp(short_score), 1)
    long_score = round(clamp(long_score), 1)
    alpha_score = round((short_score * 0.48) + (long_score * 0.52), 1)
    catalyst_stack = (
        sentiment_component * 0.34
        + quality_boost * 0.28
        + diversity_boost * 0.18
        + relevance_boost * 0.20
    )
    institutional_edge = round(
        clamp(
            (
                short_score * 0.26
                + long_score * 0.34
                + institutional_quality * 0.25
                + catalyst_stack * 0.10
                + relative_strength * 0.05
            )
            * 1.10,
            0,
            110,
        ),
        1,
    )

    return {
        "short_score": short_score,
        "long_score": long_score,
        "alpha_score": alpha_score,
        "institutional_edge": institutional_edge,
        "institutional_quality": round(clamp(institutional_quality), 1),
    }


def bucket(score):
    if score >= 78:
        return "A - Advance to deep research"
    if score >= 64:
        return "B - High-priority watchlist"
    if score >= 52:
        return "C - Screen flag"
    return "Reject / wait"


def tactical_setup(row):
    if row["technical_view"] == "Extended":
        return "Momentum strong but entry-gated"
    if row["technical_view"] == "Oversold" and row["avg_sentiment"] > 0:
        return "Contrarian rebound watch"
    if row["technical_view"] == "Uptrend" and row["avg_sentiment"] >= 0:
        return "Momentum continuation"
    if row["technical_view"] == "Downtrend":
        return "Avoid until trend repair"
    return "Selective confirmation needed"


def forward_lens(row, horizon):
    score = row["short_score"] if horizon == "short" else row["long_score"]
    if score >= 78:
        skew = "Positive skew"
        base = "If news flow remains supportive and price holds trend support, this stays at the front of the research queue."
    elif score >= 64:
        skew = "Constructive but gated"
        base = "Needs either cleaner follow-through, better source proof or a valuation/risk check before deeper work."
    elif score >= 52:
        skew = "Unproven signal"
        base = "Interesting enough to monitor, not strong enough to prioritize without a new catalyst."
    else:
        skew = "Low-confidence"
        base = "Current evidence does not justify priority research."
    return skew, base


def first_rejection(row):
    if row["news_count"] == 0:
        return "No direct source proof yet; signal relies on broad market sentiment."
    if row.get("history_years") and row["history_years"] < 1:
        return "Public trading history is too short for institutional long-horizon confidence."
    if row.get("max_drawdown") and row["max_drawdown"] < -70:
        return "Full-history drawdown profile shows severe structural downside risk."
    if row.get("sharpe") is not None and not pd.isna(row["sharpe"]) and row["sharpe"] < 0:
        return "Negative full-history risk-adjusted return profile."
    if row.get("source_diversity", 0) < 2 and row.get("source_quality", 0) < 120:
        return "Catalyst is not yet independently confirmed across enough sources."
    if row.get("RSI 14") and row["RSI 14"] > 76:
        return "Technically extended; strong headline flow may already be priced."
    if row["technical_view"] == "Downtrend":
        return "Trend damage; require price repair before priority work."
    if row.get("vol60") and row["vol60"] > 48:
        return "High realized volatility may overwhelm the signal."
    if row.get("beta_spy") and row["beta_spy"] > 1.8:
        return "High beta versus SPY requires tighter sizing and cleaner catalyst proof."
    if row["avg_sentiment"] < -0.2:
        return "Negative news tone conflicts with the setup."
    return "Need stronger evidence that the catalyst affects revenue, margins, flows or estimates."


def actionability(row, horizon):
    score = row["short_score"] if horizon == "short" else row["long_score"]
    if score >= 78:
        return "High. Promote to deeper research immediately; validate valuation, source trail and risk sizing."
    if score >= 64:
        return "Medium. Keep on desk; require one more catalyst, technical confirmation or estimate linkage."
    if score >= 52:
        return "Low-medium. Monitor only; signal is visible but not yet research-grade."
    return "Low. Do not prioritize until evidence changes."


def variant_wedge(row):
    if row["avg_sentiment"] > 0.22 and row["technical_view"] in {"Mixed", "Downtrend"}:
        return "Positive news flow is not fully confirmed by price structure yet."
    if row["avg_sentiment"] < -0.22 and row["technical_view"] == "Uptrend":
        return "Price trend is resisting negative headlines; watch for squeeze or delayed break."
    if row["news_count"] >= 4 and row["source_diversity"] >= 3:
        return "Multiple independent sources are converging on the same market theme."
    return "Evidence is still forming; the wedge is catalyst clarity versus market confirmation."


def investable_trigger(row):
    if row.get("history_years") and row["history_years"] < 1:
        return "More public trading history plus direct source proof from filings, issuer data or tier-one coverage."
    if row.get("sharpe") is not None and not pd.isna(row["sharpe"]) and row["sharpe"] < 0:
        return "Risk-adjusted profile repair: positive trend, improved downside capture and cleaner catalyst evidence."
    if row["technical_view"] == "Extended":
        return "Pullback toward trend support without deterioration in news tone."
    if row["technical_view"] == "Downtrend":
        return "Close back above 50-day trend with improving catalyst quality."
    if row["news_count"] == 0:
        return "Direct source proof from issuer, macro data, filings or multiple tier-one headlines."
    return "Sustained sentiment, better source diversity and evidence of impact on flows, estimates or margins."


def kill_trigger(row):
    if row["avg_sentiment"] > 0:
        return "Sentiment reversal, failed breakout, or catalyst exposed as already priced."
    return "Further negative news, broken support, worsening liquidity or missing source confirmation."


def make_rows(assets, metrics, matched_news, broad_sentiment, regime):
    rows = []
    for asset in assets:
        symbol = asset["symbol"]
        tech = metrics.get(symbol, {"symbol": symbol, "error": "No price data"})
        news_stats = asset_news_stats(symbol, matched_news, broad_sentiment)

        if tech.get("error"):
            rows.append(
                {
                    "symbol": symbol,
                    "name": asset["name"],
                    "type": asset["type"],
                    "sector": asset["sector"],
                    "theme": asset["theme"],
                    "short_score": 0.0,
                    "long_score": 0.0,
                    "alpha_score": 0.0,
                    "institutional_edge": 0.0,
                    "institutional_quality": 0.0,
                    "short_bucket": "Reject / wait",
                    "long_bucket": "Reject / wait",
                    "last": None,
                    "1d %": None,
                    "5d %": None,
                    "20d %": None,
                    "63d %": None,
                    "252d %": None,
                    "vol60": None,
                    "vol252": None,
                    "history_years": None,
                    "inception_date": "n/a",
                    "all_time_return": None,
                    "cagr": None,
                    "max_drawdown": None,
                    "ath_distance": None,
                    "sharpe": None,
                    "sortino": None,
                    "calmar": None,
                    "var95_daily": None,
                    "cvar95_daily": None,
                    "hit_rate": None,
                    "beta_spy": None,
                    "corr_spy": None,
                    "relative_strength_1y": None,
                    "information_ratio_1y": None,
                    "up_capture_spy": None,
                    "down_capture_spy": None,
                    "RSI 14": None,
                    "technical_view": "No data",
                    "news_count": news_stats["news_count"],
                    "avg_sentiment": news_stats["avg_sentiment"],
                    "source_diversity": news_stats["source_diversity"],
                    "source_quality": news_stats["quality_total"],
                    "catalyst_class": news_stats["catalyst_class"],
                    "top_headline": news_stats["top_headline"],
                    "source": news_stats["top_source"],
                    "themes_detected": news_stats["themes"],
                    "tactical_setup": "No data",
                    "first_rejection": tech.get("error", "No price data"),
                    "next_workflow": "Source repair",
                    "url": news_stats["top_url"],
                }
            )
            continue

        scores = score_asset(asset, tech, news_stats, regime)
        combined = {
            "symbol": symbol,
            "name": asset["name"],
            "type": asset["type"],
            "sector": asset["sector"],
            "theme": asset["theme"],
            "short_score": scores["short_score"],
            "long_score": scores["long_score"],
            "alpha_score": scores["alpha_score"],
            "institutional_edge": scores["institutional_edge"],
            "institutional_quality": scores["institutional_quality"],
            "short_bucket": bucket(scores["short_score"]),
            "long_bucket": bucket(scores["long_score"]),
            "last": tech["last"],
            "1d %": tech["1d"],
            "5d %": tech["5d"],
            "20d %": tech["20d"],
            "63d %": tech["63d"],
            "252d %": tech["252d"],
            "vol60": tech["vol60"],
            "vol252": tech["vol252"],
            "history_years": tech["history_years"],
            "inception_date": tech["inception_date"],
            "all_time_return": tech["all_time_return"],
            "cagr": tech["cagr"],
            "max_drawdown": tech["max_drawdown"],
            "ath_distance": tech["ath_distance"],
            "sharpe": tech["sharpe"],
            "sortino": tech["sortino"],
            "calmar": tech["calmar"],
            "var95_daily": tech["var95_daily"],
            "cvar95_daily": tech["cvar95_daily"],
            "hit_rate": tech["hit_rate"],
            "beta_spy": tech["beta_spy"],
            "corr_spy": tech["corr_spy"],
            "relative_strength_1y": tech["relative_strength_1y"],
            "information_ratio_1y": tech["information_ratio_1y"],
            "up_capture_spy": tech["up_capture_spy"],
            "down_capture_spy": tech["down_capture_spy"],
            "RSI 14": tech["rsi14"],
            "technical_view": tech["technical_view"],
            "news_count": news_stats["news_count"],
            "avg_sentiment": news_stats["avg_sentiment"],
            "source_diversity": news_stats["source_diversity"],
            "source_quality": news_stats["quality_total"],
            "catalyst_class": news_stats["catalyst_class"],
            "top_headline": news_stats["top_headline"],
            "source": news_stats["top_source"],
            "themes_detected": news_stats["themes"],
            "tactical_setup": "",
            "first_rejection": "",
            "next_workflow": "",
            "url": news_stats["top_url"],
        }
        combined["tactical_setup"] = tactical_setup(combined)
        combined["first_rejection"] = first_rejection(combined)
        combined["next_workflow"] = "Model update / earnings check" if combined["type"] == "Stock" else "ETF flow and factor check"
        rows.append(combined)

    return pd.DataFrame(rows)


def market_pulse(news, source_report):
    active_sources = int((source_report["status"] == "active").sum()) if source_report is not None and not source_report.empty else 0
    total_sources = int(len(source_report)) if source_report is not None and not source_report.empty else 0
    if news.empty:
        return {"headlines": 0, "positive": 0, "neutral": 0, "negative": 0, "avg": 0.0, "quality": 0.0, "active_sources": active_sources, "total_sources": total_sources}
    counts = news["sentiment_label"].value_counts()
    return {
        "headlines": int(len(news)),
        "positive": int(counts.get("Positive", 0)),
        "neutral": int(counts.get("Neutral", 0)),
        "negative": int(counts.get("Negative", 0)),
        "avg": round(float(news["sentiment"].mean()), 3),
        "quality": round(float(news["quality_score"].mean()), 1),
        "active_sources": active_sources,
        "total_sources": total_sources,
    }


def esc(value):
    return html.escape(str(value if value is not None else ""))


def signed(value):
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):+.2f}%"


def score_ring(score, max_score=100):
    score = clamp(score, 0, max_score)
    ring_pct = (score / max_score) * 100 if max_score else score
    return f"""
    <div class="score-ring" style="--score:{ring_pct};">
      <span>{score:.0f}</span>
    </div>
    """


def sparkline_svg(frame, width=240, height=78):
    if frame is None or frame.empty or "Close" not in frame:
        return "<div class='spark-empty'>no chart</div>"
    close = frame["Close"].dropna().tail(90)
    if len(close) < 5:
        return "<div class='spark-empty'>no chart</div>"
    low = safe_float(close.min())
    high = safe_float(close.max())
    if high == low:
        high = low + 1
    points = []
    for idx, value in enumerate(close):
        x = idx / max(len(close) - 1, 1) * width
        y = height - ((safe_float(value) - low) / (high - low) * (height - 8)) - 4
        points.append(f"{x:.1f},{y:.1f}")
    last = safe_float(close.iloc[-1])
    first = safe_float(close.iloc[0])
    color = "#00e676" if last >= first else "#ff4d5e"
    return f"""
    <svg class="sparkline" viewBox="0 0 {width} {height}" preserveAspectRatio="none">
      <defs>
        <linearGradient id="sparkFill{abs(hash(tuple(points))) % 100000}" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stop-color="{color}" stop-opacity=".22"/>
          <stop offset="100%" stop-color="{color}" stop-opacity="0"/>
        </linearGradient>
      </defs>
      <polyline points="0,{height} {' '.join(points)} {width},{height}" fill="rgba(255,255,255,.03)" stroke="none"/>
      <polyline points="{' '.join(points)}" fill="none" stroke="{color}" stroke-width="2.2" vector-effect="non-scaling-stroke"/>
    </svg>
    """


def plotly_template(fig, title, height=360):
    fig.update_layout(
        title={"text": title, "font": {"size": 15, "color": "#ffd46a"}, "x": 0.02},
        paper_bgcolor="#050608",
        plot_bgcolor="#070a0f",
        font={"color": "#f4f7fb", "family": "Inter, Arial, sans-serif"},
        height=height,
        margin={"l": 42, "r": 18, "t": 52, "b": 38},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1,
            "font": {"size": 10},
        },
        hovermode="x unified",
    )
    fig.update_xaxes(
        gridcolor="rgba(255,255,255,.06)",
        zeroline=False,
        showline=True,
        linecolor="rgba(255,255,255,.14)",
    )
    fig.update_yaxes(
        gridcolor="rgba(255,255,255,.06)",
        zeroline=False,
        showline=True,
        linecolor="rgba(255,255,255,.14)",
    )
    return fig


def empty_figure(title, message="Waiting for live data"):
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font={"color": "#9aa2ad", "size": 14},
    )
    return plotly_template(fig, title, height=320)


def build_market_plot(intraday_frames, df):
    if not intraday_frames:
        return empty_figure("Live Market Board", "Intraday chart data is warming up")

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.72, 0.28],
        specs=[[{"secondary_y": False}], [{"secondary_y": False}]],
    )
    palette = {
        "SPY": "#ffd46a",
        "QQQ": "#4dd8ff",
        "IWM": "#a78bfa",
        "SMH": "#20e070",
        "XLF": "#58a6ff",
        "XLE": "#ff8f3d",
        "TLT": "#c7d2fe",
        "GLD": "#facc15",
    }

    for symbol in CHART_SYMBOLS:
        frame = intraday_frames.get(symbol)
        if frame is None or frame.empty or "Close" not in frame:
            continue
        close = frame["Close"].dropna().tail(160)
        if len(close) < 3:
            continue
        normalized = close / close.iloc[0] * 100
        fig.add_trace(
            go.Scatter(
                x=normalized.index,
                y=normalized,
                mode="lines",
                name=symbol,
                line={"width": 2, "color": palette.get(symbol, "#f4f7fb")},
            ),
            row=1,
            col=1,
        )

    if not df.empty:
        movers = df[df["symbol"].isin(CHART_SYMBOLS)].copy()
        if not movers.empty:
            movers = movers.sort_values("1d %", ascending=True)
            colors = ["#20e070" if (v is not None and not pd.isna(v) and v >= 0) else "#ff4b5c" for v in movers["1d %"]]
            fig.add_trace(
                go.Bar(
                    x=movers["1d %"],
                    y=movers["symbol"],
                    orientation="h",
                    marker={"color": colors},
                    name="1D %",
                    hovertemplate="%{y}: %{x:.2f}%<extra></extra>",
                ),
                row=2,
                col=1,
            )

    fig.update_yaxes(title_text="Indexed 100", row=1, col=1)
    fig.update_yaxes(title_text="1D", row=2, col=1)
    fig.update_xaxes(title_text="Intraday", row=2, col=1)
    return plotly_template(fig, "Live Market Board - 5m Intraday + 1D Movers", height=430)


def build_sector_plot(df):
    if df.empty:
        return empty_figure("Sector Command Map", "Waiting for ranked instruments")
    grouped = (
        df.groupby("sector")
        .agg(
            short_score=("short_score", "mean"),
            long_score=("long_score", "mean"),
            institutional_edge=("institutional_edge", "mean"),
            tone=("avg_sentiment", "mean"),
            count=("symbol", "count"),
        )
        .reset_index()
    )
    grouped["composite"] = grouped["institutional_edge"]
    grouped = grouped.sort_values("composite", ascending=True)
    colors = ["#20e070" if tone > 0.08 else "#ff4b5c" if tone < -0.08 else "#ffb000" for tone in grouped["tone"]]
    fig = go.Figure(
        go.Bar(
            x=grouped["composite"],
            y=grouped["sector"],
            orientation="h",
            marker={"color": colors, "line": {"color": "rgba(255,255,255,.16)", "width": 1}},
            customdata=grouped[["tone", "count", "short_score", "long_score", "institutional_edge"]],
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Institutional Edge: %{x:.1f}/110<br>"
                "Tone: %{customdata[0]:+.2f}<br>"
                "Instruments: %{customdata[1]}<br>"
                "Short: %{customdata[2]:.1f}<br>"
                "Long: %{customdata[3]:.1f}<br>"
                "Edge: %{customdata[4]:.1f}<extra></extra>"
            ),
        )
    )
    fig.update_xaxes(range=[0, 110])
    return plotly_template(fig, "Sector Command Map - Institutional Edge / 110", height=360)


def build_theme_plot(theme_df):
    if theme_df is None or theme_df.empty:
        return empty_figure("Theme Sentiment Radar", "Waiting for theme classification")
    data = theme_df.sort_values("headlines", ascending=True).tail(10)
    colors = ["#20e070" if tone > 0.08 else "#ff4b5c" if tone < -0.08 else "#ffb000" for tone in data["avg_sentiment"]]
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=data["headlines"],
            y=data["theme"],
            orientation="h",
            marker={"color": colors},
            text=[f"{tone:+.2f}" for tone in data["avg_sentiment"]],
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>Headlines: %{x}<br>Tone: %{text}<extra></extra>",
        )
    )
    return plotly_template(fig, "Theme Sentiment Radar", height=360)


def build_chart_wall(df, price_frames):
    symbols = ["SPY", "QQQ", "IWM", "SMH", "XLF", "XLE", "TLT", "GLD"]
    cards = []
    for symbol in symbols:
        row = df[df["symbol"] == symbol].head(1)
        if row.empty:
            continue
        item = row.iloc[0]
        cards.append(
            f"""
            <div class="chart-card">
              <div class="chart-head"><strong>{esc(symbol)}</strong><span>5M LIVE / {esc(item["technical_view"])}</span></div>
              {sparkline_svg(price_frames.get(symbol))}
              <div class="chart-foot"><span>1D {signed(item["1d %"])}</span><span>20D {signed(item["20d %"])}</span><span>RSI {esc(item["RSI 14"])}</span></div>
            </div>
            """
        )
    if not cards:
        return "<div class='empty-state'>Market charts unavailable until price data loads.</div>"
    return "<div class='chart-wall'>" + "".join(cards) + "</div>"


def build_sector_heatmap(df):
    if df.empty:
        return "<div class='empty-state'>No sector heatmap yet.</div>"
    grouped = (
        df.groupby("sector")
        .agg(short_score=("short_score", "mean"), long_score=("long_score", "mean"), institutional_edge=("institutional_edge", "mean"), tone=("avg_sentiment", "mean"), count=("symbol", "count"))
        .reset_index()
        .sort_values("institutional_edge", ascending=False)
    )
    cells = []
    for _, row in grouped.iterrows():
        score = round(float(row["institutional_edge"]), 1)
        tone = float(row["tone"])
        tone_class = "pos" if tone > 0.08 else "neg" if tone < -0.08 else "neu"
        cells.append(
            f"""
            <div class="heat-cell {tone_class}" style="--heat:{score};">
              <span>{esc(row["sector"])}</span>
              <strong>{score:.0f}</strong>
              <small>{int(row["count"])} instruments | edge /110 | tone {tone:+.2f}</small>
            </div>
            """
        )
    return "<div class='heatmap'>" + "".join(cells) + "</div>"


def build_source_panel(source_report):
    if source_report is None or source_report.empty:
        return "<div class='empty-state'>No source status yet.</div>"
    active = int((source_report["status"] == "active").sum())
    total = int(len(source_report))
    headlines = int(source_report["headlines"].sum())
    desks = source_report.groupby("desk")["headlines"].sum().sort_values(ascending=False).head(8)
    desk_rows = "".join(
        f"<div><span>{esc(desk)}</span><strong>{int(count)}</strong></div>"
        for desk, count in desks.items()
    )
    return f"""
    <div class="source-panel">
      <div class="source-score"><span>RSS NETWORK</span><strong>{active}/{total}</strong><small>{headlines} high-quality headlines</small></div>
      <div class="desk-grid">{desk_rows}</div>
    </div>
    """


def build_headline_radar(news):
    if news.empty:
        return "<div class='empty-state'>No live headlines available.</div>"
    rows = []
    for _, item in news.head(10).iterrows():
        tone_class = item["sentiment_label"].lower()
        title = esc(item["title"])
        link = f"<a href='{esc(item['url'])}' target='_blank'>{title}</a>" if item.get("url") else title
        rows.append(
            f"""
            <div class="radar-line {tone_class}">
              <span>{esc(item["source"])}</span>
              <strong>{link}</strong>
              <small>{esc(item["catalyst_class"])} | Q {item["quality_score"]:.0f} | {item["sentiment"]:+.2f}</small>
            </div>
            """
        )
    return "<div class='headline-radar'>" + "".join(rows) + "</div>"


def build_market_ticker(df):
    if df.empty:
        return "<div class='market-ticker'><span>Waiting for market data...</span></div>"
    symbols = ["SPY", "QQQ", "IWM", "SMH", "XLF", "XLE", "TLT", "GLD", "AAPL", "MSFT", "NVDA", "TSLA"]
    items = []
    for symbol in symbols:
        row = df[df["symbol"] == symbol].head(1)
        if row.empty:
            continue
        item = row.iloc[0]
        move = item["1d %"]
        direction = "up" if move is not None and not pd.isna(move) and float(move) >= 0 else "down"
        items.append(
            f"<span class='{direction}'><b>{esc(symbol)}</b> {signed(move)} <em>{esc(item['technical_view'])}</em></span>"
        )
    return "<div class='market-ticker'>" + "".join(items) + "</div>"


def build_shell_html(pulse, regime, df, warnings, theme_df, news, source_report):
    top_short = df.sort_values("short_score", ascending=False).head(1).iloc[0] if not df.empty else None
    top_long = df.sort_values("long_score", ascending=False).head(1).iloc[0] if not df.empty else None
    top_edge = df.sort_values("institutional_edge", ascending=False).head(1).iloc[0] if not df.empty else None
    advance_short = int((df["short_score"] >= 78).sum()) if not df.empty else 0
    advance_long = int((df["long_score"] >= 78).sum()) if not df.empty else 0
    edge_count = int((df["institutional_edge"] >= 90).sum()) if not df.empty else 0
    max_history = round(float(df["history_years"].fillna(0).max()), 1) if not df.empty and "history_years" in df else 0.0
    theme_leader = theme_df.head(1).iloc[0].to_dict() if not theme_df.empty else {"theme": "n/a", "avg_sentiment": 0, "headlines": 0}

    warning_html = ""
    if warnings:
        warning_html = "<div class='terminal-warning'>Source warnings: " + esc(" | ".join(warnings[:3])) + "</div>"

    source_panel = build_source_panel(source_report)
    headline_radar = build_headline_radar(news)
    market_ticker = build_market_ticker(df)

    return f"""
    <section class="terminal-hero">
      <div>
        <div class="terminal-kicker">REALTIME PUBLIC MARKET INTELLIGENCE / CACHE UPDATED {esc(now_label())}</div>
        <h1>{APP_TITLE}</h1>
        <p>Live RSS refinery, full-history price engine and autonomous equity/ETF research queues. Backend refreshes continuously; the interface reads a clean market snapshot.</p>
      </div>
      <div class="regime-card">
        <span>MARKET REGIME</span>
        <strong>{esc(regime["label"])}</strong>
        <p>{esc(regime["duration_signal"])} | {esc(regime["stance"])}</p>
      </div>
    </section>

    {market_ticker}

    <section class="metric-grid">
      <div class="metric"><span>LIVE HEADLINES</span><strong>{pulse["headlines"]}</strong></div>
      <div class="metric"><span>ACTIVE SOURCES</span><strong>{pulse["active_sources"]}/{pulse["total_sources"]}</strong></div>
      <div class="metric"><span>SENTIMENT MIX</span><strong>{pulse["positive"]}/{pulse["neutral"]}/{pulse["negative"]}</strong><small>positive / neutral / negative</small></div>
      <div class="metric"><span>AVG NEWS TONE</span><strong>{pulse["avg"]:+.2f}</strong></div>
      <div class="metric"><span>AVG QUALITY</span><strong>{pulse["quality"]:.0f}</strong></div>
      <div class="metric"><span>SHORT A-LIST</span><strong>{advance_short}</strong></div>
      <div class="metric"><span>LONG A-LIST</span><strong>{advance_long}</strong></div>
      <div class="metric"><span>EDGE 110</span><strong>{edge_count}</strong><small>{esc(top_edge["symbol"] if top_edge is not None else "n/a")} leads at {(top_edge["institutional_edge"] if top_edge is not None else 0):.0f}/110</small></div>
      <div class="metric"><span>MAX HISTORY</span><strong>{max_history:.1f}y</strong><small>daily data, max available</small></div>
      <div class="metric"><span>HOT THEME</span><strong>{esc(theme_leader["theme"])}</strong><small>{theme_leader["headlines"]} headlines | {theme_leader["avg_sentiment"]:+.2f}</small></div>
    </section>

    <section class="cockpit-grid">
      <div class="cockpit-panel">
        <div class="panel-label">RSS SOURCE NETWORK</div>
        {source_panel}
      </div>
      <div class="cockpit-panel">
        <div class="panel-label">LIVE HEADLINE RADAR</div>
        {headline_radar}
      </div>
    </section>

    <section class="split-leaders">
      <div class="leader-panel">
        <div class="panel-head"><span>TACTICAL LEADER</span>{score_ring(top_short["short_score"]) if top_short is not None else ""}</div>
        <h2>{esc(top_short["symbol"] if top_short is not None else "n/a")} <small>{esc(top_short["name"] if top_short is not None else "")}</small></h2>
        <p>{esc(top_short["tactical_setup"] if top_short is not None else "")}</p>
        <div class="leader-meta">{esc(top_short["short_bucket"] if top_short is not None else "")} | {signed(top_short["5d %"] if top_short is not None else None)} 5d | Edge {(top_short["institutional_edge"] if top_short is not None else 0):.0f}/110 | sentiment {(top_short["avg_sentiment"] if top_short is not None else 0):+.2f}</div>
      </div>
      <div class="leader-panel">
        <div class="panel-head"><span>LONG-HORIZON LEADER</span>{score_ring(top_long["long_score"]) if top_long is not None else ""}</div>
        <h2>{esc(top_long["symbol"] if top_long is not None else "n/a")} <small>{esc(top_long["name"] if top_long is not None else "")}</small></h2>
        <p>{esc(top_long["theme"] if top_long is not None else "")}</p>
        <div class="leader-meta">{esc(top_long["long_bucket"] if top_long is not None else "")} | {signed(top_long["252d %"] if top_long is not None else None)} 1y | CAGR {signed(top_long["cagr"] if top_long is not None else None)} | history {(top_long["history_years"] if top_long is not None and top_long["history_years"] is not None else 0):.1f}y</div>
      </div>
    </section>
    {warning_html}
    """


def card(row, horizon):
    score_key = "short_score" if horizon == "short" else "long_score"
    bucket_key = "short_bucket" if horizon == "short" else "long_bucket"
    skew, base = forward_lens(row, horizon)
    headline = esc(row["top_headline"])
    url = row.get("url", "")
    headline_html = f"<a href='{esc(url)}' target='_blank'>{headline}</a>" if url else headline
    horizon_metric = signed(row["5d %"]) if horizon == "short" else signed(row["252d %"])
    horizon_label = "5d move" if horizon == "short" else "1y move"

    return f"""
    <article class="idea-card">
      <div class="idea-top">
        <div>
          <span class="asset-type">{esc(row["type"])} / {esc(row["sector"])}</span>
          <h3>{esc(row["symbol"])} <small>{esc(row["name"])}</small></h3>
        </div>
        {score_ring(row[score_key])}
      </div>
      <div class="bucket">{esc(row[bucket_key])}</div>
      <div class="mini-grid">
        <div><span>{horizon_label}</span><strong>{horizon_metric}</strong></div>
        <div><span>RSI</span><strong>{esc(row["RSI 14"])}</strong></div>
        <div><span>News</span><strong>{int(row["news_count"])}</strong></div>
        <div><span>Sources</span><strong>{int(row["source_diversity"])}</strong></div>
        <div><span>Edge</span><strong>{(row.get("institutional_edge", 0) or 0):.0f}/110</strong></div>
        <div><span>CAGR</span><strong>{signed(row.get("cagr"))}</strong></div>
        <div><span>Sharpe</span><strong>{esc(row.get("sharpe"))}</strong></div>
        <div><span>MDD</span><strong>{signed(row.get("max_drawdown"))}</strong></div>
      </div>
      <div class="catalyst-chip">{esc(row["catalyst_class"])} | tone {row["avg_sentiment"]:+.2f}</div>
      <p class="thesis"><strong>Why now:</strong> {headline_html}</p>
      <p><strong>Actionability:</strong> {esc(actionability(row, horizon))}</p>
      <p><strong>Variant wedge:</strong> {esc(variant_wedge(row))}</p>
      <p><strong>Forward lens:</strong> {esc(skew)}. {esc(base)}</p>
      <p><strong>What makes it investable:</strong> {esc(investable_trigger(row))}</p>
      <p><strong>What kills it:</strong> {esc(kill_trigger(row))}</p>
      <p><strong>First rejection:</strong> {esc(row["first_rejection"])}</p>
      <p><strong>Next workflow:</strong> {esc(row["next_workflow"])}</p>
    </article>
    """


def build_cards_html(df, horizon):
    if df.empty:
        return "<div class='empty-state'>No candidates available.</div>"
    score_key = "short_score" if horizon == "short" else "long_score"
    top = df.sort_values(score_key, ascending=False).head(6)
    return "<div class='cards-grid'>" + "".join(card(row, horizon) for _, row in top.iterrows()) + "</div>"


def queue_html(df, horizon):
    title = "Short-Term Tactical Queue" if horizon == "short" else "Long-Term Investment Queue"
    subtitle = "Fresh catalyst + near-term momentum + institutional risk filter" if horizon == "short" else "Full-history durability + trend structure"
    if df.empty:
        return f"""
        <section class="queue-panel">
          <div class="section-head"><span>{title}</span><strong>{subtitle}</strong></div>
          <div class="empty-state">No candidates available yet.</div>
        </section>
        """

    score_key = "short_score" if horizon == "short" else "long_score"
    bucket_key = "short_bucket" if horizon == "short" else "long_bucket"
    move_key = "5d %" if horizon == "short" else "252d %"
    rows = []
    for rank, (_, row) in enumerate(df.sort_values(score_key, ascending=False).head(10).iterrows(), start=1):
        score = float(row[score_key])
        score_class = "score-hot" if score >= 78 else "score-watch" if score >= 64 else "score-cold"
        edge = float(row.get("institutional_edge", 0) or 0)
        edge_class = "score-hot" if edge >= 90 else "score-watch" if edge >= 72 else "score-cold"
        rows.append(
            f"""
            <tr>
              <td class="rank-cell">{rank}</td>
              <td class="asset-cell"><strong>{esc(row["symbol"])}</strong><span>{esc(row["sector"])}</span></td>
              <td><span class="score-pill {score_class}">{score:.0f}</span><span class="edge-mini {edge_class}">Edge {edge:.0f}/110</span></td>
              <td><strong>{esc(row[bucket_key])}</strong><span>{esc(row["tactical_setup"])}</span></td>
              <td><strong>{esc(row["catalyst_class"])}</strong><span>{int(row["news_count"])} news / {int(row["source_diversity"])} sources / tone {row["avg_sentiment"]:+.2f}</span></td>
              <td><strong>{signed(row[move_key])}</strong><span>RSI {esc(row["RSI 14"])} / {esc(row["technical_view"])}</span></td>
              <td><strong>{(row["history_years"] if row["history_years"] is not None and not pd.isna(row["history_years"]) else 0):.1f}y history</strong><span>CAGR {signed(row["cagr"])} / Sharpe {esc(row["sharpe"])} / MDD {signed(row["max_drawdown"])}</span><span>Beta {esc(row["beta_spy"])} / RS {signed(row["relative_strength_1y"])}</span></td>
              <td class="why-cell">{esc(clean_text(row["top_headline"], 150))}<span>{esc(clean_text(row["first_rejection"], 120))}</span></td>
            </tr>
            """
        )
    return f"""
    <section class="queue-panel">
      <div class="section-head"><span>{title}</span><strong>{subtitle}</strong></div>
      <div class="queue-shell">
        <table class="terminal-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Asset</th>
              <th>Score</th>
              <th>Research Status</th>
              <th>Catalyst</th>
              <th>Market State</th>
              <th>Full-History Risk</th>
              <th>Why Now / First Rejection</th>
            </tr>
          </thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
    </section>
    """


def source_health_html(source_report):
    if source_report is None or source_report.empty:
        return "<div class='empty-state'>No source health available yet.</div>"
    rows = []
    for _, row in source_report.sort_values(["status", "headlines"], ascending=[True, False]).head(18).iterrows():
        status_class = "source-active" if row["status"] == "active" else "source-muted"
        rows.append(
            f"""
            <tr>
              <td><span class="source-dot {status_class}"></span>{esc(row["source"])}</td>
              <td>{esc(row["desk"])}</td>
              <td>{esc(row["tier"])}</td>
              <td>{int(row["headlines"])}</td>
              <td>{esc(row["status"])}</td>
            </tr>
            """
        )
    return f"""
    <section class="source-health-card">
      <div class="section-head"><span>Source Health</span><strong>RSS network diagnostics</strong></div>
      <table class="source-table">
        <thead><tr><th>Source</th><th>Desk</th><th>Tier</th><th>News</th><th>Status</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </section>
    """


def build_news_html(news):
    if news.empty:
        return "<div class='empty-state'>No live public headlines were retrieved. Widen the lookback or change RSS feeds.</div>"
    items = []
    for _, row in news.head(28).iterrows():
        tone_class = row["sentiment_label"].lower()
        title = esc(row["title"])
        link = f"<a href='{esc(row['url'])}' target='_blank'>{title}</a>" if row.get("url") else title
        items.append(
            f"""
            <article class="news-line {tone_class}">
              <div><span>{esc(row["time"])}</span><span>{esc(row["source"])}</span><span>{esc(row.get("source_desk", ""))}</span><span>{esc(row["catalyst_class"])}</span><b>Q {row["quality_score"]:.0f} / {row["sentiment"]:+.2f}</b></div>
              <h4>{link}</h4>
            </article>
            """
        )
    return "<div class='news-tape'>" + "".join(items) + "</div>"


def build_method_html():
    return """
    <section class="method">
      <h3>Engine prompt executed by this MVP</h3>
      <p>Act as an autonomous public-market research terminal. Ingest a large public RSS network, classify themes, score source quality, remove low-signal headlines, map catalysts to a liquid equity/ETF universe, retrieve maximum available public price history, calculate technical and institutional risk state, infer market regime and produce two ranked research queues: short-term tactical opportunities and long-term investment candidates. The backend maintains a realtime cache; the frontend reads the latest snapshot every few seconds without refetching every source on each render.</p>
      <h3>Scoring model</h3>
      <p>Short-term score emphasizes fresh news sentiment, 5d/20d momentum, trend state, relevance, source quality, source diversity, catalyst class, volume shock, relative strength and regime alignment. Long-term score emphasizes full-history CAGR, Sharpe, Sortino, Calmar, maximum drawdown, daily VaR/CVaR, all-time-high distance, 63d/126d/252d trend, SPY beta/correlation/capture, information ratio, source diversity, sentiment persistence and thematic relevance. Institutional Edge is a 0-110 research-conviction scale, not a guaranteed success probability.</p>
      <h3>News refinery</h3>
      <p>Every headline receives theme tags, catalyst class, source tier, desk, quality score and canonical key for deduplication. Weak non-market headlines are filtered before they can influence any security ranking.</p>
      <h3>Realtime architecture</h3>
      <p>RSS and market-data pulls run in backend worker threads. Full-history daily data powers institutional scoring and is cached separately; a lightweight Yahoo chart API adapter powers 5-minute intraday chart panels. Manual refresh forces a new snapshot; passive UI polling reads cache only.</p>
      <h3>Data caveat</h3>
      <p>This uses public RSS and Yahoo Finance. It is not licensed terminal data, not financial advice and not a replacement for regulated research, filings, earnings transcripts, valuation work or risk review.</p>
    </section>
    """


def compute_terminal_outputs(universe_mode, custom_symbols, lookback_hours, rss_text):
    assets = selected_universe(universe_mode, custom_symbols)
    sources = parse_sources(rss_text)
    symbols = [asset["symbol"] for asset in assets]
    price_symbols = list(dict.fromkeys(symbols + ["SPY"]))

    news, warnings, source_report = fetch_news(sources, int(lookback_hours))
    pulse = market_pulse(news, source_report)
    matched = map_news_to_assets(news, assets)
    price_frames = fetch_prices(price_symbols, period=MAX_HISTORY_PERIOD, interval="1d")
    intraday_frames = fetch_intraday_prices([symbol for symbol in CHART_SYMBOLS if symbol in symbols])
    benchmark_close = price_frames.get("SPY", pd.DataFrame()).get("Close") if "SPY" in price_frames else None
    metrics = {symbol: technicals(symbol, price_frames.get(symbol), benchmark_close) for symbol in symbols}
    regime = infer_regime(metrics, pulse["avg"])
    rows = make_rows(assets, metrics, matched, pulse["avg"], regime)
    theme_df = theme_sentiment(news)

    if not rows.empty:
        rows = rows.sort_values(["institutional_edge", "alpha_score", "short_score", "long_score"], ascending=False).reset_index(drop=True)

    shell = build_shell_html(pulse, regime, rows, warnings, theme_df, news, source_report)
    market_plot = build_market_plot(intraday_frames or price_frames, rows)
    sector_plot = build_sector_plot(rows)
    theme_plot = build_theme_plot(theme_df)
    short_queue = queue_html(rows, "short")
    long_queue = queue_html(rows, "long")
    news_html = build_news_html(news)
    source_html = source_health_html(source_report)
    method = build_method_html()

    return shell, market_plot, sector_plot, theme_plot, short_queue, long_queue, news_html, source_html, method


def loading_outputs(message="Building the first market snapshot. Live feeds and price history are warming up."):
    shell = f"""
    <section class="terminal-hero loading-hero">
      <div>
        <div class="terminal-kicker">REALTIME BACKEND / MARKET DATA CACHE / STARTING</div>
        <h1>{APP_TITLE}</h1>
        <p>{esc(message)}</p>
      </div>
      <div class="regime-card">
        <span>ENGINE STATUS</span>
        <strong>WARMING</strong>
        <p>Backend refresh threads are initializing the RSS network and chart cache.</p>
      </div>
    </section>
    """
    return (
        shell,
        empty_figure("Live Market Board"),
        empty_figure("Sector Command Map"),
        empty_figure("Theme Sentiment Radar"),
        queue_html(pd.DataFrame(), "short"),
        queue_html(pd.DataFrame(), "long"),
        "<div class='empty-state'>Waiting for the first live news tape.</div>",
        "<div class='empty-state'>Waiting for source health.</div>",
        build_method_html(),
    )


class RealtimeMarketEngine:
    def __init__(self):
        self.lock = threading.RLock()
        self.snapshot = None
        self.config = None
        self.last_full_refresh = 0.0
        self.last_requested_at = 0.0
        self.is_refreshing = False
        self.started = False
        self.stop_event = threading.Event()
        self.worker = None
        self.last_error = ""

    def start(self):
        with self.lock:
            if self.started:
                return
            self.started = True
            self.worker = threading.Thread(target=self._loop, daemon=True)
            self.worker.start()

    def configure(self, universe_mode, custom_symbols, lookback_hours, rss_text):
        next_config = (
            universe_mode,
            custom_symbols or "",
            int(lookback_hours),
            rss_text or source_catalog_text(),
        )
        with self.lock:
            changed = next_config != self.config
            self.config = next_config
            if changed:
                self.last_requested_at = 0.0
            return changed

    def _loop(self):
        while not self.stop_event.is_set():
            should_refresh = False
            with self.lock:
                has_config = self.config is not None
                stale = time.time() - self.last_full_refresh > FULL_REFRESH_SECONDS
                should_refresh = has_config and stale and not self.is_refreshing
            if should_refresh:
                self.refresh_async()
            self.stop_event.wait(5)

    def refresh_async(self):
        with self.lock:
            if self.is_refreshing or self.config is None:
                return
            self.is_refreshing = True
            config = self.config

        def job():
            try:
                result = compute_terminal_outputs(*config)
                with self.lock:
                    self.snapshot = result
                    self.last_full_refresh = time.time()
                    self.last_error = ""
            except Exception as exc:
                with self.lock:
                    self.last_error = clean_text(exc, 180)
                    if self.snapshot is None:
                        self.snapshot = loading_outputs(f"Market engine error: {self.last_error}")
            finally:
                with self.lock:
                    self.is_refreshing = False

        threading.Thread(target=job, daemon=True).start()

    def refresh_now(self, universe_mode, custom_symbols, lookback_hours, rss_text):
        self.start()
        self.configure(universe_mode, custom_symbols, lookback_hours, rss_text)
        with self.lock:
            if self.is_refreshing:
                return self.read()
            self.is_refreshing = True
            config = self.config
        try:
            result = compute_terminal_outputs(*config)
            with self.lock:
                self.snapshot = result
                self.last_full_refresh = time.time()
                self.last_error = ""
                return self.snapshot
        except Exception as exc:
            with self.lock:
                self.last_error = clean_text(exc, 180)
                if self.snapshot is None:
                    self.snapshot = loading_outputs(f"Market engine error: {self.last_error}")
                return self.snapshot
        finally:
            with self.lock:
                self.is_refreshing = False

    def read(self):
        with self.lock:
            if self.snapshot is None:
                return loading_outputs()
            return self.snapshot

    def read_or_start(self, universe_mode, custom_symbols, lookback_hours, rss_text):
        self.start()
        changed = self.configure(universe_mode, custom_symbols, lookback_hours, rss_text)
        with self.lock:
            empty = self.snapshot is None
            stale_initial = time.time() - self.last_requested_at > min(NEWS_REFRESH_SECONDS, PRICE_REFRESH_SECONDS)
            if empty or changed or stale_initial:
                self.last_requested_at = time.time()
                self.refresh_async()
        return self.read()


ENGINE = RealtimeMarketEngine()


def run_terminal(universe_mode, custom_symbols, lookback_hours, rss_text):
    return ENGINE.refresh_now(universe_mode, custom_symbols, lookback_hours, rss_text)


def read_terminal(universe_mode, custom_symbols, lookback_hours, rss_text):
    return ENGINE.read_or_start(universe_mode, custom_symbols, lookback_hours, rss_text)


CSS = """
:root {
  --bg: #030405;
  --panel: #0b0d10;
  --panel2: #11151b;
  --panel3: #171d25;
  --line: #2a3038;
  --text: #f4f7fb;
  --muted: #9aa2ad;
  --amber: #ffb000;
  --amber2: #ffd46a;
  --green: #20e070;
  --red: #ff4b5c;
  --blue: #58a6ff;
  --cyan: #4dd8ff;
  --violet: #a78bfa;
  --soft: rgba(255,255,255,.055);
}
body, .gradio-container {
  background: var(--bg) !important;
  color: var(--text) !important;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
}
.gradio-container {
  max-width: 1720px !important;
}
.main {
  background: var(--bg) !important;
}
label, .block-title, .wrap, .prose {
  color: var(--text) !important;
}
.gradio-container h3 {
  color: var(--amber2) !important;
  font-size: 14px !important;
  text-transform: uppercase;
  letter-spacing: .08em;
  margin: 18px 0 8px !important;
}
.plot-container, .js-plotly-plot {
  border-radius: 10px !important;
}
button {
  border-radius: 4px !important;
  border: 1px solid var(--amber) !important;
  background: linear-gradient(180deg, #ffc247, #b97700) !important;
  color: #050608 !important;
  font-weight: 800 !important;
}
textarea, input, select {
  background: #090d13 !important;
  color: var(--text) !important;
  border-color: var(--line) !important;
}
.terminal-hero {
  min-height: 170px;
  display: grid;
  grid-template-columns: 1fr 360px;
  gap: 12px;
  align-items: stretch;
  padding: 22px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background:
    linear-gradient(120deg, rgba(255,176,0,.16), transparent 34%),
    linear-gradient(180deg, rgba(255,255,255,.06), transparent),
    repeating-linear-gradient(90deg, rgba(255,255,255,.026) 0 1px, transparent 1px 88px),
    #06080b;
  box-shadow: 0 24px 80px rgba(0,0,0,.42), inset 0 1px rgba(255,255,255,.08);
}
.terminal-kicker {
  color: var(--amber2);
  font-size: 12px;
  letter-spacing: .08em;
  font-weight: 800;
  text-transform: uppercase;
}
.terminal-hero h1 {
  margin: 12px 0 8px;
  color: var(--text);
  font-size: 44px;
  line-height: .95;
  letter-spacing: 0;
}
.terminal-hero p {
  max-width: 900px;
  color: var(--muted);
  font-size: 15px;
  line-height: 1.5;
}
.regime-card {
  background: rgba(5,6,8,.76);
  border: 1px solid rgba(255,176,0,.38);
  border-radius: 10px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
}
.regime-card span, .metric span, .panel-head span, .asset-type {
  color: var(--muted);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: .08em;
  font-weight: 800;
}
.regime-card strong {
  display: block;
  color: var(--amber);
  font-size: 32px;
  margin: 8px 0;
}
.market-ticker {
  display: flex;
  gap: 8px;
  overflow: auto;
  padding: 8px 0 2px;
  scrollbar-width: thin;
}
.market-ticker span {
  flex: 0 0 auto;
  color: var(--text);
  background: #080b0f;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 7px 10px;
  font-size: 12px;
  white-space: nowrap;
}
.market-ticker b {
  margin-right: 6px;
}
.market-ticker em {
  color: var(--muted);
  font-style: normal;
  margin-left: 6px;
}
.market-ticker .up { border-color: rgba(32,224,112,.38); }
.market-ticker .down { border-color: rgba(255,75,92,.42); }
.metric-grid {
  display: grid;
  grid-template-columns: repeat(8, minmax(118px, 1fr));
  gap: 8px;
  margin: 10px 0;
}
.metric {
  min-height: 84px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
}
.metric strong {
  display: block;
  margin-top: 8px;
  color: var(--text);
  font-size: 25px;
  line-height: 1;
}
.metric small {
  display: block;
  color: var(--muted);
  margin-top: 7px;
  font-size: 11px;
}
.metric.positive strong { color: var(--green); }
.metric.negative strong { color: var(--red); }
.metric.neutral strong { color: var(--amber); }
.cockpit-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(320px, .65fr);
  gap: 10px;
  margin-bottom: 10px;
}
.cockpit-panel {
  background:
    linear-gradient(180deg, rgba(255,255,255,.025), transparent),
    var(--panel);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 12px;
  min-height: 220px;
}
.cockpit-panel.wide {
  min-width: 0;
}
.panel-label {
  color: var(--amber2);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: .08em;
  font-weight: 900;
  margin-bottom: 10px;
}
.chart-wall {
  display: grid;
  grid-template-columns: repeat(4, minmax(140px, 1fr));
  gap: 8px;
}
.chart-card {
  background: #070a0f;
  border: 1px solid #202b3a;
  border-radius: 8px;
  padding: 9px;
  min-height: 128px;
}
.chart-head, .chart-foot {
  display: flex;
  justify-content: space-between;
  gap: 6px;
  align-items: center;
}
.chart-head strong {
  color: var(--text);
  font-size: 17px;
}
.chart-head span, .chart-foot span {
  color: var(--muted);
  font-size: 10px;
  white-space: nowrap;
}
.sparkline {
  width: 100%;
  height: 78px;
  margin: 6px 0;
  background:
    linear-gradient(rgba(255,255,255,.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.04) 1px, transparent 1px);
  background-size: 100% 26px, 48px 100%;
}
.spark-empty {
  min-height: 78px;
  display: grid;
  place-items: center;
  color: var(--muted);
  font-size: 11px;
}
.heatmap {
  display: grid;
  grid-template-columns: repeat(4, minmax(120px, 1fr));
  gap: 8px;
}
.heat-cell {
  min-height: 82px;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px;
  background:
    linear-gradient(135deg, rgba(255,176,0,.18), transparent),
    #070a0f;
}
.heat-cell.pos { border-color: rgba(0,230,118,.45); }
.heat-cell.neg { border-color: rgba(255,77,94,.45); }
.heat-cell.neu { border-color: rgba(255,176,0,.35); }
.heat-cell span, .heat-cell small {
  display: block;
  color: var(--muted);
  font-size: 11px;
}
.heat-cell strong {
  display: block;
  color: var(--text);
  font-size: 26px;
  margin: 5px 0;
}
.source-panel {
  display: grid;
  gap: 10px;
}
.source-score {
  background: #070a0f;
  border: 1px solid rgba(77,216,255,.35);
  border-radius: 8px;
  padding: 12px;
}
.source-score span, .source-score small {
  display: block;
  color: var(--muted);
  font-size: 11px;
}
.source-score strong {
  display: block;
  color: var(--cyan);
  font-size: 34px;
  margin: 4px 0;
}
.desk-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(100px, 1fr));
  gap: 6px;
}
.desk-grid div {
  background: #070a0f;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 8px;
}
.desk-grid span {
  display: block;
  color: var(--muted);
  font-size: 10px;
}
.desk-grid strong {
  color: var(--text);
  font-size: 18px;
}
.headline-radar {
  display: grid;
  gap: 7px;
  max-height: 340px;
  overflow: auto;
}
.radar-line {
  background: #070a0f;
  border: 1px solid var(--line);
  border-left: 3px solid var(--amber);
  border-radius: 8px;
  padding: 8px;
}
.radar-line.positive { border-left-color: var(--green); }
.radar-line.negative { border-left-color: var(--red); }
.radar-line span, .radar-line small {
  display: block;
  color: var(--muted);
  font-size: 10px;
}
.radar-line strong {
  display: block;
  color: var(--text);
  font-size: 12px;
  line-height: 1.28;
  margin: 3px 0;
}
.radar-line a {
  color: var(--text);
  text-decoration: none;
}
.radar-line a:hover {
  color: var(--amber);
}
.split-leaders {
  display: grid;
  grid-template-columns: repeat(2, minmax(300px, 1fr));
  gap: 10px;
  margin-bottom: 10px;
}
.leader-panel, .idea-card, .method, .queue-panel, .source-health-card {
  background: linear-gradient(180deg, var(--panel2), var(--panel));
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 18px;
}
.panel-head, .idea-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.leader-panel h2, .idea-card h3 {
  margin: 10px 0 8px;
  color: var(--text);
  font-size: 28px;
  letter-spacing: 0;
}
.idea-card h3 {
  font-size: 22px;
}
.leader-panel small, .idea-card small {
  display: block;
  color: var(--muted);
  font-size: 13px;
  font-weight: 500;
  margin-top: 4px;
}
.leader-panel p, .idea-card p, .method p {
  color: var(--muted);
  line-height: 1.45;
}
.leader-meta, .bucket {
  color: var(--amber2);
  border-top: 1px solid var(--line);
  padding-top: 10px;
  margin-top: 12px;
  font-size: 13px;
  font-weight: 700;
}
.section-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 14px;
  margin-bottom: 12px;
}
.section-head span {
  color: var(--amber2);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: .08em;
  font-weight: 900;
}
.section-head strong {
  color: var(--muted);
  font-size: 13px;
  font-weight: 600;
}
.queue-panel {
  margin-bottom: 12px;
  padding: 14px;
}
.queue-shell {
  overflow-x: auto;
}
.terminal-table, .source-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}
.terminal-table th, .source-table th {
  color: var(--muted);
  background: #070a0f;
  border-bottom: 1px solid var(--line);
  font-size: 10px;
  text-align: left;
  text-transform: uppercase;
  letter-spacing: .06em;
  padding: 9px 8px;
}
.terminal-table td, .source-table td {
  color: var(--text);
  border-bottom: 1px solid rgba(255,255,255,.055);
  padding: 11px 8px;
  vertical-align: top;
  font-size: 12px;
  overflow-wrap: anywhere;
}
.terminal-table tr:hover, .source-table tr:hover {
  background: rgba(255,176,0,.055);
}
.terminal-table td span, .source-table td span {
  display: block;
  color: var(--muted);
  margin-top: 3px;
  line-height: 1.25;
}
.rank-cell {
  color: var(--amber) !important;
  font-weight: 900;
  width: 34px;
}
.asset-cell strong {
  display: block;
  color: var(--text);
  font-size: 15px;
}
.terminal-table th:nth-child(1), .terminal-table td:nth-child(1) { width: 42px; }
.terminal-table th:nth-child(2), .terminal-table td:nth-child(2) { width: 12%; }
.terminal-table th:nth-child(3), .terminal-table td:nth-child(3) { width: 86px; }
.terminal-table th:nth-child(4), .terminal-table td:nth-child(4) { width: 16%; }
.terminal-table th:nth-child(5), .terminal-table td:nth-child(5) { width: 15%; }
.terminal-table th:nth-child(6), .terminal-table td:nth-child(6) { width: 12%; }
.terminal-table th:nth-child(7), .terminal-table td:nth-child(7) { width: 19%; }
.terminal-table th:nth-child(8), .terminal-table td:nth-child(8) { width: auto; }
.score-pill {
  display: inline-grid !important;
  place-items: center;
  min-width: 42px;
  height: 28px;
  border-radius: 999px;
  color: #050608 !important;
  font-weight: 900;
  margin: 0 !important;
}
.edge-mini {
  display: inline-flex !important;
  align-items: center;
  justify-content: center;
  width: fit-content;
  margin: 6px 0 0 !important;
  border-radius: 4px;
  padding: 4px 7px;
  color: #050608 !important;
  font-size: 10px;
  font-weight: 900;
  text-transform: uppercase;
  letter-spacing: .03em;
}
.score-hot { background: var(--green); }
.score-watch { background: var(--amber); }
.score-cold { background: #5f6b7a; color: var(--text) !important; }
.edge-mini.score-cold { color: var(--text) !important; }
.why-cell {
  color: #dbe5f1 !important;
  line-height: 1.35;
}
.source-health-card {
  min-height: 100%;
}
.source-table th:nth-child(1), .source-table td:nth-child(1) {
  width: 36%;
}
.source-dot {
  display: inline-block !important;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin: 0 7px 0 0 !important;
}
.source-active { background: var(--green); }
.source-muted { background: var(--red); }
.score-ring {
  width: 58px;
  height: 58px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background:
    radial-gradient(circle at center, var(--panel) 58%, transparent 60%),
    conic-gradient(var(--amber) calc(var(--score) * 1%), #233044 0);
  flex: 0 0 auto;
}
.score-ring span {
  color: var(--text);
  font-weight: 900;
  font-size: 18px;
}
.cards-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(280px, 1fr));
  gap: 10px;
}
.idea-card {
  min-height: 560px;
}
.mini-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
  margin: 12px 0;
}
.mini-grid div {
  background: #080c12;
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 9px;
}
.mini-grid span {
  display: block;
  color: var(--muted);
  font-size: 10px;
  text-transform: uppercase;
}
.mini-grid strong {
  color: var(--text);
  font-size: 15px;
}
.catalyst-chip {
  color: #050608;
  background: linear-gradient(90deg, var(--amber), var(--cyan));
  border-radius: 4px;
  padding: 8px 10px;
  font-size: 12px;
  font-weight: 900;
  margin: 10px 0;
}
.thesis a, .news-line a {
  color: var(--text);
  text-decoration: none;
}
.thesis a:hover, .news-line a:hover {
  color: var(--amber);
}
.news-tape {
  display: grid;
  grid-template-columns: repeat(2, minmax(320px, 1fr));
  gap: 8px;
}
.news-line {
  background: var(--panel);
  border: 1px solid var(--line);
  border-left: 4px solid var(--amber);
  border-radius: 4px;
  padding: 12px;
}
.news-line.positive { border-left-color: var(--green); }
.news-line.negative { border-left-color: var(--red); }
.news-line div {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  color: var(--muted);
  font-size: 11px;
}
.news-line b {
  color: var(--amber);
}
.news-line h4 {
  margin: 8px 0 0;
  color: var(--text);
  font-size: 14px;
  line-height: 1.35;
}
.terminal-warning, .empty-state {
  border: 1px solid rgba(255,176,0,.5);
  background: rgba(255,176,0,.08);
  color: var(--amber2);
  border-radius: 4px;
  padding: 12px;
  margin: 10px 0;
}
#control-stack {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 14px;
}
.queue-table {
  border: 1px solid var(--line) !important;
  border-radius: 6px !important;
  overflow: hidden;
}
@media (max-width: 1100px) {
  .terminal-hero, .split-leaders, .cockpit-grid { grid-template-columns: 1fr; }
  .metric-grid { grid-template-columns: repeat(2, minmax(130px, 1fr)); }
  .cards-grid, .news-tape, .chart-wall, .heatmap { grid-template-columns: 1fr; }
  .terminal-hero h1 { font-size: 40px; }
}
"""


with gr.Blocks(title=APP_TITLE, css=CSS, theme=gr.themes.Base()) as demo:
    with gr.Row():
        with gr.Column(scale=9):
            shell_output = gr.HTML()
        with gr.Column(scale=3, elem_id="control-stack"):
            gr.Markdown("### Control Deck")
            universe_mode = gr.Dropdown(
                ["Auto: Liquid US + ETF universe", "AI / Semis", "Macro ETFs", "Mega-cap stocks"],
                value="Auto: Liquid US + ETF universe",
                label="Universe",
            )
            custom_symbols = gr.Textbox(
                label="Optional extra tickers",
                placeholder="Example: PLTR, ARM, SOFI",
                lines=2,
            )
            lookback_hours = gr.Slider(6, 168, value=48, step=6, label="News lookback, hours")
            refresh = gr.Button("Refresh Now", variant="primary")

            with gr.Accordion("RSS source configuration", open=False):
                rss_text = gr.Textbox(
                    label="Public RSS feeds",
                    value=source_catalog_text(),
                    lines=12,
                )

    gr.Markdown("### Market Graphs")
    market_plot_output = gr.Plot(label="Live Market Board")
    with gr.Row():
        sector_plot_output = gr.Plot(label="Sector Command Map")
        theme_plot_output = gr.Plot(label="Theme Sentiment Radar")

    gr.Markdown("### Research Queues")
    short_queue_output = gr.HTML()
    long_queue_output = gr.HTML()

    gr.Markdown("### Live News And Source Health")
    with gr.Row():
        with gr.Column(scale=7):
            news_output = gr.HTML()
        with gr.Column(scale=5):
            source_output = gr.HTML()

    with gr.Accordion("Engine notes and data caveats", open=False):
        method_output = gr.HTML()

    inputs = [universe_mode, custom_symbols, lookback_hours, rss_text]
    outputs = [
        shell_output,
        market_plot_output,
        sector_plot_output,
        theme_plot_output,
        short_queue_output,
        long_queue_output,
        news_output,
        source_output,
        method_output,
    ]

    refresh.click(run_terminal, inputs=inputs, outputs=outputs)
    try:
        demo.load(read_terminal, inputs=inputs, outputs=outputs, every=FRONTEND_POLL_SECONDS)
    except TypeError:
        demo.load(read_terminal, inputs=inputs, outputs=outputs)


demo.launch()
