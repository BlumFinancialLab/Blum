from __future__ import annotations

from urllib.parse import urlencode


RSS_SOURCES = [
    {"name": "Yahoo Finance", "url": "https://finance.yahoo.com/news/rssindex", "desk": "Markets", "tier": 1},
    {"name": "CNBC Markets", "url": "https://www.cnbc.com/id/15839135/device/rss/rss.html", "desk": "Markets", "tier": 1},
    {"name": "CNBC Top News", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "desk": "Markets", "tier": 1},
    {"name": "MarketWatch Top Stories", "url": "https://www.marketwatch.com/rss/topstories", "desk": "Markets", "tier": 1},
    {"name": "MarketWatch Real-Time", "url": "https://www.marketwatch.com/rss/realtimeheadlines", "desk": "Markets", "tier": 1},
    {"name": "WSJ Markets", "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml", "desk": "Markets", "tier": 1},
    {"name": "WSJ World", "url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml", "desk": "Macro", "tier": 1},
    {"name": "Financial Times", "url": "https://www.ft.com/rss/home", "desk": "Macro", "tier": 1},
    {"name": "NYT Business", "url": "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", "desk": "Business", "tier": 1},
    {"name": "BBC Business", "url": "https://feeds.bbci.co.uk/news/business/rss.xml", "desk": "Business", "tier": 1},
    {"name": "AP Business", "url": "https://apnews.com/hub/business?output=rss", "desk": "Business", "tier": 1},
    {"name": "Federal Reserve Press", "url": "https://www.federalreserve.gov/feeds/press_all.xml", "desk": "Rates", "tier": 1},
    {"name": "SEC Press Releases", "url": "https://www.sec.gov/news/pressreleases.rss", "desk": "Regulatory", "tier": 1},
    {"name": "ECB Press", "url": "https://www.ecb.europa.eu/rss/press.html", "desk": "Rates", "tier": 2},
    {"name": "Investing.com News", "url": "https://www.investing.com/rss/news.rss", "desk": "Markets", "tier": 2},
    {"name": "Nasdaq Markets", "url": "https://www.nasdaq.com/feed/rssoutbound?category=Markets", "desk": "Markets", "tier": 2},
    {"name": "PR Newswire Earnings", "url": "https://www.prnewswire.com/rss/earnings-latest-news/earnings-latest-news-list.rss", "desk": "Earnings", "tier": 3},
    {"name": "Business Wire Finance", "url": "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeGVtQWA==", "desk": "Company News", "tier": 3},
    {"name": "Oilprice", "url": "https://oilprice.com/rss/main", "desk": "Commodities", "tier": 2},
]


PUBLIC_WEB_NEWS_QUERIES = [
    {"name": "Global Equity Markets", "query": "global stock markets OR S&P 500 OR Nasdaq OR Dow Jones when:7d", "desk": "Markets", "tier": 2},
    {"name": "AI Infrastructure", "query": "AI chips OR data center capex OR GPU demand OR artificial intelligence stocks when:7d", "desk": "AI", "tier": 2},
    {"name": "Semiconductor Cycle", "query": "semiconductor earnings OR chip guidance OR ASML OR Nvidia OR AMD when:7d", "desk": "Semiconductors", "tier": 2},
    {"name": "Rates And Inflation", "query": "Federal Reserve rates inflation Treasury yields CPI PCE markets when:7d", "desk": "Rates", "tier": 2},
    {"name": "Earnings Guidance", "query": "earnings guidance revenue margins Wall Street stocks when:7d", "desk": "Earnings", "tier": 2},
    {"name": "Energy Markets", "query": "oil prices OPEC crude energy stocks Exxon Chevron when:7d", "desk": "Energy", "tier": 2},
    {"name": "Healthcare GLP-1", "query": "Eli Lilly Novo Nordisk GLP-1 obesity drug market when:7d", "desk": "Healthcare", "tier": 2},
    {"name": "Defense Aerospace", "query": "defense stocks aerospace NATO Rheinmetall Airbus when:7d", "desk": "Defense", "tier": 2},
    {"name": "Cyber Security", "query": "cybersecurity stocks breach spending ETF when:7d", "desk": "Cyber Security", "tier": 2},
    {"name": "Clean Energy", "query": "clean energy stocks grid infrastructure renewables ETF when:7d", "desk": "Clean Energy", "tier": 2},
    {"name": "Luxury Consumer", "query": "luxury demand China consumer LVMH European stocks when:7d", "desk": "Consumer", "tier": 2},
    {"name": "ETF Rotation", "query": "ETF flows sector rotation technology financials energy healthcare when:7d", "desk": "ETF", "tier": 2},
]


def google_news_source(name: str, query: str, desk: str, tier: int = 2) -> dict:
    params = urlencode({"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    return {
        "name": f"Google News: {name}",
        "url": f"https://news.google.com/rss/search?{params}",
        "desk": desk,
        "tier": tier,
        "kind": "public_web_search",
    }


def thematic_web_sources() -> list[dict]:
    return [google_news_source(item["name"], item["query"], item["desk"], item["tier"]) for item in PUBLIC_WEB_NEWS_QUERIES]


def asset_web_sources(assets, max_assets: int = 36) -> list[dict]:
    sources = []
    for asset in assets[:max_assets]:
        company = asset.name.replace("&", "and")
        query = f'"{asset.ticker}" OR "{company}" stock earnings guidance market when:7d'
        sources.append(google_news_source(asset.ticker, query, asset.sector, 2))
    return sources
