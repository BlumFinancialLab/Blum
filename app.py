import html
import math
import re
from datetime import datetime, timedelta, timezone

import feedparser
import gradio as gr
import pandas as pd
import requests
import yfinance as yf
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer


APP_TITLE = "Blum Alpha Terminal"
AUTO_REFRESH_SECONDS = 300
MAX_NEWS_PER_FEED = 45

DEFAULT_FEEDS = [
    "https://finance.yahoo.com/news/rssindex",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "https://www.marketwatch.com/rss/topstories",
    "https://www.investing.com/rss/news.rss",
]

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

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

analyzer = SentimentIntensityAnalyzer()


def clamp(value, low=0.0, high=100.0):
    if value is None or pd.isna(value):
        return low
    return max(low, min(high, float(value)))


def scale(value, low, high):
    if value is None or pd.isna(value) or high == low:
        return 50.0
    return clamp((float(value) - low) / (high - low) * 100.0)


def safe_float(value, default=math.nan):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_text(value, limit=None):
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        return text[: limit - 1].rstrip() + "..."
    return text


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


def fetch_feed(url, lookback_hours):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=int(lookback_hours))
    try:
        response = requests.get(url, headers=HEADERS, timeout=9)
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
    except Exception as exc:
        return [], f"{url}: {clean_text(exc, 130)}"

    source = clean_text(parsed.feed.get("title", url), 80)
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
        rows.append(
            {
                "time": published.strftime("%Y-%m-%d %H:%M") if published else "latest",
                "source": source,
                "title": title,
                "summary": summary,
                "url": entry.get("link", ""),
                "sentiment": round(float(score), 3),
                "sentiment_label": sentiment_label(score),
                "themes": ", ".join(classify_themes(title, summary)),
            }
        )
    return rows, None


def fetch_news(feed_urls, lookback_hours):
    rows = []
    warnings = []
    for url in feed_urls:
        url = url.strip()
        if not url:
            continue
        items, warning = fetch_feed(url, lookback_hours)
        rows.extend(items)
        if warning:
            warnings.append(warning)

    if not rows:
        return pd.DataFrame(columns=["time", "source", "title", "summary", "url", "sentiment", "sentiment_label", "themes"]), warnings

    news = pd.DataFrame(rows)
    return news.drop_duplicates(subset=["title", "url"]).reset_index(drop=True), warnings


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
        return pd.DataFrame(columns=["symbol", "name", "relevance", "time", "source", "title", "sentiment", "sentiment_label", "themes", "url"])

    rows = []
    for asset in assets:
        for _, item in news.iterrows():
            relevance = relevance_score(asset, item["title"], item["summary"])
            if relevance > 0:
                rows.append(
                    {
                        "symbol": asset["symbol"],
                        "name": asset["name"],
                        "relevance": relevance,
                        "time": item["time"],
                        "source": item["source"],
                        "title": item["title"],
                        "sentiment": item["sentiment"],
                        "sentiment_label": item["sentiment_label"],
                        "themes": item["themes"],
                        "url": item["url"],
                    }
                )

    if not rows:
        return pd.DataFrame(columns=["symbol", "name", "relevance", "time", "source", "title", "sentiment", "sentiment_label", "themes", "url"])
    return pd.DataFrame(rows)


def fetch_prices(symbols):
    if not symbols:
        return {}

    try:
        data = yf.download(
            tickers=" ".join(symbols),
            period="18mo",
            interval="1d",
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


def technicals(symbol, frame):
    if frame is None or frame.empty or len(frame) < 50:
        return {"symbol": symbol, "error": "Insufficient price history"}

    close = frame["Close"].dropna()
    volume = frame["Volume"].dropna() if "Volume" in frame else pd.Series(dtype=float)
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
    vol60 = safe_float(close.pct_change().tail(60).std() * math.sqrt(252) * 100)
    high_252 = safe_float(close.tail(min(252, len(close))).max())
    drawdown = ((latest / high_252) - 1) * 100 if high_252 and not pd.isna(high_252) else math.nan

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
        "vol60": round(vol60, 2) if not pd.isna(vol60) else None,
        "drawdown_1y": round(drawdown, 2) if not pd.isna(drawdown) else None,
        "volume_shock": round(volume_shock, 2),
        "sma20": round(sma20, 2),
        "sma50": round(sma50, 2),
        "sma200": round(sma200, 2) if not pd.isna(sma200) else None,
        "rsi14": round(rsi14, 1) if not pd.isna(rsi14) else None,
        "trend_score": trend_score,
        "technical_view": technical_view,
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
            "top_headline": "No direct headline match; using broad market pulse.",
            "top_source": "Market pulse",
            "top_url": "",
            "themes": "Macro & Index",
        }
    weighted = (subset["sentiment"] * subset["relevance"]).sum() / max(subset["relevance"].sum(), 1)
    top = subset.sort_values(["relevance", "sentiment"], ascending=[False, False]).iloc[0]
    themes = ", ".join(sorted(set(", ".join(subset["themes"].dropna()).split(", "))))[:120]
    return {
        "news_count": int(len(subset)),
        "avg_sentiment": round(float(weighted), 3),
        "relevance_total": int(subset["relevance"].sum()),
        "top_headline": top["title"],
        "top_source": top["source"],
        "top_url": top["url"],
        "themes": themes or "Macro & Index",
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
    short_momentum = (scale(tech.get("5d"), -5, 5) * 0.45) + (scale(tech.get("20d"), -10, 10) * 0.55)
    long_momentum = (scale(tech.get("63d"), -15, 18) * 0.25) + (scale(tech.get("126d"), -22, 28) * 0.30) + (scale(tech.get("252d"), -35, 45) * 0.45)
    trend_component = scale(tech.get("trend_score"), -3, 3)
    volume_component = scale(tech.get("volume_shock"), -35, 80)
    volatility_penalty = scale(tech.get("vol60"), 55, 12)
    drawdown_component = scale(tech.get("drawdown_1y"), -35, 0)
    rsi_value = tech.get("rsi14") or 50
    extension_penalty = 18 if rsi_value > 76 else 8 if rsi_value > 70 else 0
    oversold_bonus = 8 if rsi_value < 32 else 0
    regime_bonus = 5 if regime["label"] == "Risk-on" and asset["sector"] not in {"Utilities", "Staples", "Rates"} else 0
    defensive_bonus = 5 if regime["label"] == "Risk-off" and asset["sector"] in {"Staples", "Healthcare", "Utilities", "Rates", "Commodities"} else 0

    short_score = (
        sentiment_component * 0.30
        + short_momentum * 0.25
        + trend_component * 0.15
        + relevance_boost * 0.12
        + volume_component * 0.08
        + volatility_penalty * 0.05
        + regime_bonus
        + defensive_bonus
        + oversold_bonus
        - extension_penalty
    )

    long_score = (
        long_momentum * 0.30
        + trend_component * 0.22
        + sentiment_component * 0.15
        + drawdown_component * 0.10
        + volatility_penalty * 0.10
        + relevance_boost * 0.08
        + regime_bonus * 0.6
        + defensive_bonus * 0.7
    )

    short_score = round(clamp(short_score), 1)
    long_score = round(clamp(long_score), 1)
    alpha_score = round((short_score * 0.48) + (long_score * 0.52), 1)

    return {
        "short_score": short_score,
        "long_score": long_score,
        "alpha_score": alpha_score,
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
    if row.get("RSI 14") and row["RSI 14"] > 76:
        return "Technically extended; strong headline flow may already be priced."
    if row["technical_view"] == "Downtrend":
        return "Trend damage; require price repair before priority work."
    if row.get("vol60") and row["vol60"] > 48:
        return "High realized volatility may overwhelm the signal."
    if row["avg_sentiment"] < -0.2:
        return "Negative news tone conflicts with the setup."
    return "Need stronger evidence that the catalyst affects revenue, margins, flows or estimates."


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
                    "short_bucket": "Reject / wait",
                    "long_bucket": "Reject / wait",
                    "last": None,
                    "1d %": None,
                    "5d %": None,
                    "20d %": None,
                    "63d %": None,
                    "252d %": None,
                    "vol60": None,
                    "RSI 14": None,
                    "technical_view": "No data",
                    "news_count": news_stats["news_count"],
                    "avg_sentiment": news_stats["avg_sentiment"],
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
            "short_bucket": bucket(scores["short_score"]),
            "long_bucket": bucket(scores["long_score"]),
            "last": tech["last"],
            "1d %": tech["1d"],
            "5d %": tech["5d"],
            "20d %": tech["20d"],
            "63d %": tech["63d"],
            "252d %": tech["252d"],
            "vol60": tech["vol60"],
            "RSI 14": tech["rsi14"],
            "technical_view": tech["technical_view"],
            "news_count": news_stats["news_count"],
            "avg_sentiment": news_stats["avg_sentiment"],
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


def market_pulse(news):
    if news.empty:
        return {"headlines": 0, "positive": 0, "neutral": 0, "negative": 0, "avg": 0.0}
    counts = news["sentiment_label"].value_counts()
    return {
        "headlines": int(len(news)),
        "positive": int(counts.get("Positive", 0)),
        "neutral": int(counts.get("Neutral", 0)),
        "negative": int(counts.get("Negative", 0)),
        "avg": round(float(news["sentiment"].mean()), 3),
    }


def esc(value):
    return html.escape(str(value if value is not None else ""))


def signed(value):
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):+.2f}%"


def score_ring(score):
    score = clamp(score)
    return f"""
    <div class="score-ring" style="--score:{score};">
      <span>{score:.0f}</span>
    </div>
    """


def build_shell_html(pulse, regime, df, warnings, theme_df):
    top_short = df.sort_values("short_score", ascending=False).head(1).iloc[0] if not df.empty else None
    top_long = df.sort_values("long_score", ascending=False).head(1).iloc[0] if not df.empty else None
    advance_short = int((df["short_score"] >= 78).sum()) if not df.empty else 0
    advance_long = int((df["long_score"] >= 78).sum()) if not df.empty else 0
    theme_leader = theme_df.head(1).iloc[0].to_dict() if not theme_df.empty else {"theme": "n/a", "avg_sentiment": 0, "headlines": 0}

    warning_html = ""
    if warnings:
        warning_html = "<div class='terminal-warning'>Source warnings: " + esc(" | ".join(warnings[:3])) + "</div>"

    return f"""
    <section class="terminal-hero">
      <div>
        <div class="terminal-kicker">PUBLIC MARKET INTELLIGENCE / LIVE RSS + PRICE HISTORY / {esc(now_label())}</div>
        <h1>{APP_TITLE}</h1>
        <p>Autonomous equity and ETF research queue. It screens the market, ranks short-term and long-term candidates, and explains why each instrument surfaced now.</p>
      </div>
      <div class="regime-card">
        <span>MARKET REGIME</span>
        <strong>{esc(regime["label"])}</strong>
        <p>{esc(regime["duration_signal"])} | {esc(regime["stance"])}</p>
      </div>
    </section>

    <section class="metric-grid">
      <div class="metric"><span>LIVE HEADLINES</span><strong>{pulse["headlines"]}</strong></div>
      <div class="metric positive"><span>POSITIVE</span><strong>{pulse["positive"]}</strong></div>
      <div class="metric neutral"><span>NEUTRAL</span><strong>{pulse["neutral"]}</strong></div>
      <div class="metric negative"><span>NEGATIVE</span><strong>{pulse["negative"]}</strong></div>
      <div class="metric"><span>AVG NEWS TONE</span><strong>{pulse["avg"]:+.2f}</strong></div>
      <div class="metric"><span>SHORT A-LIST</span><strong>{advance_short}</strong></div>
      <div class="metric"><span>LONG A-LIST</span><strong>{advance_long}</strong></div>
      <div class="metric"><span>HOT THEME</span><strong>{esc(theme_leader["theme"])}</strong><small>{theme_leader["headlines"]} headlines | {theme_leader["avg_sentiment"]:+.2f}</small></div>
    </section>

    <section class="split-leaders">
      <div class="leader-panel">
        <div class="panel-head"><span>TACTICAL LEADER</span>{score_ring(top_short["short_score"]) if top_short is not None else ""}</div>
        <h2>{esc(top_short["symbol"] if top_short is not None else "n/a")} <small>{esc(top_short["name"] if top_short is not None else "")}</small></h2>
        <p>{esc(top_short["tactical_setup"] if top_short is not None else "")}</p>
        <div class="leader-meta">{esc(top_short["short_bucket"] if top_short is not None else "")} | {signed(top_short["5d %"] if top_short is not None else None)} 5d | sentiment {top_short["avg_sentiment"]:+.2f}</div>
      </div>
      <div class="leader-panel">
        <div class="panel-head"><span>LONG-HORIZON LEADER</span>{score_ring(top_long["long_score"]) if top_long is not None else ""}</div>
        <h2>{esc(top_long["symbol"] if top_long is not None else "n/a")} <small>{esc(top_long["name"] if top_long is not None else "")}</small></h2>
        <p>{esc(top_long["theme"] if top_long is not None else "")}</p>
        <div class="leader-meta">{esc(top_long["long_bucket"] if top_long is not None else "")} | {signed(top_long["252d %"] if top_long is not None else None)} 1y | trend {esc(top_long["technical_view"] if top_long is not None else "")}</div>
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
        <div><span>Tone</span><strong>{row["avg_sentiment"]:+.2f}</strong></div>
      </div>
      <p class="thesis"><strong>Why now:</strong> {headline_html}</p>
      <p><strong>Forward lens:</strong> {esc(skew)}. {esc(base)}</p>
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
              <div><span>{esc(row["time"])}</span><span>{esc(row["source"])}</span><span>{esc(row["themes"])}</span><b>{row["sentiment"]:+.2f}</b></div>
              <h4>{link}</h4>
            </article>
            """
        )
    return "<div class='news-tape'>" + "".join(items) + "</div>"


def build_method_html():
    return """
    <section class="method">
      <h3>Engine prompt executed by this MVP</h3>
      <p>Act as an autonomous public-market research terminal. Ingest public RSS news, classify themes, map catalysts to a liquid equity/ETF universe, retrieve historical price behavior, calculate technical state, infer market regime and produce two ranked research queues: short-term tactical opportunities and long-term investment candidates. Never output final trade instructions; output research priority, evidence, first rejection risk and next workflow.</p>
      <h3>Scoring model</h3>
      <p>Short-term score emphasizes fresh news sentiment, 5d/20d momentum, trend state, relevance, volume shock and regime alignment. Long-term score emphasizes 63d/126d/252d trend, 200-day structure, volatility, drawdown control, sentiment persistence and thematic relevance.</p>
      <h3>Data caveat</h3>
      <p>This uses public RSS and Yahoo Finance. It is not licensed terminal data, not financial advice and not a replacement for regulated research, filings, earnings transcripts, valuation work or risk review.</p>
    </section>
    """


def run_terminal(universe_mode, custom_symbols, lookback_hours, rss_text):
    assets = selected_universe(universe_mode, custom_symbols)
    feeds = [line.strip() for line in rss_text.splitlines() if line.strip()]
    symbols = [asset["symbol"] for asset in assets]

    news, warnings = fetch_news(feeds, int(lookback_hours))
    pulse = market_pulse(news)
    matched = map_news_to_assets(news, assets)
    price_frames = fetch_prices(symbols)
    metrics = {symbol: technicals(symbol, price_frames.get(symbol)) for symbol in symbols}
    regime = infer_regime(metrics, pulse["avg"])
    rows = make_rows(assets, metrics, matched, pulse["avg"], regime)
    theme_df = theme_sentiment(news)

    if not rows.empty:
        rows = rows.sort_values(["alpha_score", "short_score", "long_score"], ascending=False).reset_index(drop=True)

    display_cols = [
        "symbol", "name", "type", "sector", "short_score", "short_bucket", "long_score", "long_bucket",
        "last", "1d %", "5d %", "20d %", "63d %", "252d %", "vol60", "RSI 14", "technical_view",
        "news_count", "avg_sentiment", "tactical_setup", "first_rejection",
    ]
    ranking = rows[display_cols] if not rows.empty else pd.DataFrame(columns=display_cols)
    news_table = matched.sort_values(["relevance", "sentiment"], ascending=False).head(150) if not matched.empty else matched

    shell = build_shell_html(pulse, regime, rows, warnings, theme_df)
    short_cards = build_cards_html(rows, "short")
    long_cards = build_cards_html(rows, "long")
    news_html = build_news_html(news)
    method = build_method_html()

    return shell, short_cards, long_cards, ranking, news_table, theme_df, news_html, method


CSS = """
:root {
  --bg: #050608;
  --panel: #0c1016;
  --panel2: #111822;
  --panel3: #151f2b;
  --line: #2a3647;
  --text: #f4f7fb;
  --muted: #95a3b7;
  --amber: #ffb000;
  --amber2: #ffd166;
  --green: #00e676;
  --red: #ff4d5e;
  --blue: #3ea6ff;
}
body, .gradio-container {
  background: var(--bg) !important;
  color: var(--text) !important;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
}
.gradio-container {
  max-width: 1680px !important;
}
.main {
  background: var(--bg) !important;
}
label, .block-title, .wrap, .prose {
  color: var(--text) !important;
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
  min-height: 250px;
  display: grid;
  grid-template-columns: 1fr 360px;
  gap: 18px;
  align-items: stretch;
  padding: 28px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background:
    linear-gradient(120deg, rgba(255,176,0,.18), transparent 36%),
    repeating-linear-gradient(90deg, rgba(255,255,255,.035) 0 1px, transparent 1px 80px),
    linear-gradient(135deg, #0c1118, #050608);
  box-shadow: 0 0 0 1px rgba(255,176,0,.12), 0 20px 80px rgba(0,0,0,.35);
}
.terminal-kicker {
  color: var(--amber2);
  font-size: 12px;
  letter-spacing: .08em;
  font-weight: 800;
  text-transform: uppercase;
}
.terminal-hero h1 {
  margin: 18px 0 10px;
  color: var(--text);
  font-size: 56px;
  line-height: .95;
  letter-spacing: 0;
}
.terminal-hero p {
  max-width: 900px;
  color: var(--muted);
  font-size: 17px;
  line-height: 1.5;
}
.regime-card {
  background: rgba(5,6,8,.72);
  border: 1px solid rgba(255,176,0,.38);
  border-radius: 6px;
  padding: 22px;
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
  font-size: 38px;
  margin: 8px 0;
}
.metric-grid {
  display: grid;
  grid-template-columns: repeat(8, minmax(120px, 1fr));
  gap: 8px;
  margin: 10px 0;
}
.metric {
  min-height: 98px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 14px;
}
.metric strong {
  display: block;
  margin-top: 8px;
  color: var(--text);
  font-size: 29px;
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
.split-leaders {
  display: grid;
  grid-template-columns: repeat(2, minmax(300px, 1fr));
  gap: 10px;
  margin-bottom: 10px;
}
.leader-panel, .idea-card, .method {
  background: linear-gradient(180deg, var(--panel2), var(--panel));
  border: 1px solid var(--line);
  border-radius: 6px;
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
  min-height: 410px;
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
@media (max-width: 1100px) {
  .terminal-hero, .split-leaders { grid-template-columns: 1fr; }
  .metric-grid { grid-template-columns: repeat(2, minmax(130px, 1fr)); }
  .cards-grid, .news-tape { grid-template-columns: 1fr; }
  .terminal-hero h1 { font-size: 40px; }
}
"""


with gr.Blocks(title=APP_TITLE, css=CSS, theme=gr.themes.Base()) as demo:
    with gr.Row():
        with gr.Column(scale=8):
            shell_output = gr.HTML()
        with gr.Column(scale=2, elem_id="control-stack"):
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
            refresh = gr.Button("Run Live Market Scan", variant="primary")

    with gr.Tabs():
        with gr.Tab("Short-Term Alpha Queue"):
            short_cards_output = gr.HTML()
        with gr.Tab("Long-Term Investment Queue"):
            long_cards_output = gr.HTML()
        with gr.Tab("Full Ranking Matrix"):
            ranking_output = gr.Dataframe(interactive=False, wrap=True, label="Autonomous stock / ETF ranking")
        with gr.Tab("Matched Catalyst Map"):
            matched_output = gr.Dataframe(interactive=False, wrap=True, label="News mapped to instruments")
        with gr.Tab("Theme Radar"):
            theme_output = gr.Dataframe(interactive=False, wrap=True, label="Market theme sentiment")
        with gr.Tab("Live News Tape"):
            news_output = gr.HTML()
        with gr.Tab("Engine"):
            method_output = gr.HTML()
            rss_text = gr.Textbox(
                label="Public RSS feeds",
                value="\n".join(DEFAULT_FEEDS),
                lines=7,
            )

    inputs = [universe_mode, custom_symbols, lookback_hours, rss_text]
    outputs = [
        shell_output,
        short_cards_output,
        long_cards_output,
        ranking_output,
        matched_output,
        theme_output,
        news_output,
        method_output,
    ]

    refresh.click(run_terminal, inputs=inputs, outputs=outputs)
    try:
        demo.load(run_terminal, inputs=inputs, outputs=outputs, every=AUTO_REFRESH_SECONDS)
    except TypeError:
        demo.load(run_terminal, inputs=inputs, outputs=outputs)


demo.launch()
