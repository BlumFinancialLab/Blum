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


def attach_news_to_symbols(news_df, symbols):
    if news_df.empty:
        return pd.DataFrame()

    rows = []
    for symbol in symbols:
        for _, item in news_df.iterrows():
            text = f"{item['title']} {item['summary']}"
            relevance = keyword_match_score(symbol, text)
            if relevance > 0:
                rows.append(
                    {
                        "symbol": symbol,
                        "relevance": relevance,
                        "sentiment": item["sentiment"],
                        "title": item["title"],
                        "source": item["source"],
                        "published": item["published"],
                        "url": item["url"],
                    }
                )

    return pd.DataFrame(rows)


def rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()
    rs = gain / loss.replace(0, math.nan)
    return 100 - (100 / (1 + rs))


def technical_snapshot(symbol, horizon_days):
    period = "2y" if horizon_days > 180 else "1y"
    data = yf.download(symbol, period=period, progress=False, auto_adjust=True)

    if data.empty or "Close" not in data:
        return None

    close = data["Close"].dropna()
    latest = float(close.iloc[-1])
    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1])
    sma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else math.nan
    latest_rsi = float(rsi(close).iloc[-1])

    window = min(max(horizon_days, 20), len(close) - 1)
    horizon_return = float((latest / close.iloc[-window] - 1) * 100)
    volatility = float(close.pct_change().tail(60).std() * math.sqrt(252) * 100)

    trend_score = 0
    trend_score += 1 if latest > sma20 else -1
    trend_score += 1 if latest > sma50 else -1
    if not math.isnan(sma200):
        trend_score += 1 if latest > sma200 else -1

    if latest_rsi > 70:
        momentum_label = "overbought / risk of pullback"
    elif latest_rsi < 30:
        momentum_label = "oversold / possible rebound setup"
    elif trend_score >= 2:
        momentum_label = "positive trend"
    elif trend_score <= -2:
        momentum_label = "negative trend"
    else:
        momentum_label = "mixed trend"

    return {
        "symbol": symbol,
        "last_price": round(latest, 2),
        "return_over_horizon_%": round(horizon_return, 2),
        "annualized_volatility_%": round(volatility, 2),
        "sma20": round(sma20, 2),
        "sma50": round(sma50, 2),
        "sma200": round(sma200, 2) if not math.isnan(sma200) else "",
        "rsi14": round(latest_rsi, 1),
        "technical_view": momentum_label,
        "trend_score": trend_score,
    }


def classify_candidate(technical, sentiment_score, news_count, horizon):
    score = technical["trend_score"]
    score += 1 if sentiment_score > 0.15 else 0
    score -= 1 if sentiment_score < -0.15 else 0
    score += 1 if news_count >= 3 else 0

    if horizon == "Breve termine":
        if technical["rsi14"] > 75:
            score -= 1
        if technical["rsi14"] < 30:
            score += 1
    else:
        if technical["last_price"] > technical["sma50"]:
            score += 1

    if score >= 4:
        return "A - da approfondire subito"
    if score >= 2:
        return "B - watchlist / serve conferma"
    if score >= 0:
        return "C - segnale debole"
    return "Reject / rischio o dati insufficienti"


def run_screen(symbols_text, horizon, horizon_days, rss_text, lookback_hours):
    symbols = normalize_symbols(symbols_text)
    feeds = [line.strip() for line in rss_text.splitlines() if line.strip()]

    if not symbols:
        return "Inserisci almeno un ticker.", pd.DataFrame(), pd.DataFrame()

    news_df = fetch_rss_items(feeds, lookback_hours)
    matched_news = attach_news_to_symbols(news_df, symbols)

    output_rows = []
    for symbol in symbols:
        technical = technical_snapshot(symbol, horizon_days)
        if technical is None:
            output_rows.append(
                {
                    "symbol": symbol,
                    "status": "Dati prezzo non disponibili",
                    "candidate_bucket": "Reject / dati insufficienti",
                }
            )
            continue

        symbol_news = matched_news[matched_news["symbol"] == symbol] if not matched_news.empty else pd.DataFrame()
        sentiment_score = float(symbol_news["sentiment"].mean()) if not symbol_news.empty else 0.0
        news_count = len(symbol_news)

        technical["news_count"] = news_count
        technical["avg_news_sentiment"] = round(sentiment_score, 3)
        technical["candidate_bucket"] = classify_candidate(
            technical, sentiment_score, news_count, horizon
        )
        technical["status"] = "Research candidate, non raccomandazione operativa"
        output_rows.append(technical)

    ranking = pd.DataFrame(output_rows)
    if "candidate_bucket" in ranking:
        ranking = ranking.sort_values(
            by=["candidate_bucket", "trend_score", "avg_news_sentiment"],
            ascending=[True, False, False],
        )

    summary = build_summary(ranking, matched_news, horizon, horizon_days)
    news_view = matched_news.sort_values(
        by=["symbol", "relevance", "sentiment"], ascending=[True, False, False]
    ) if not matched_news.empty else pd.DataFrame()

    return summary, ranking, news_view.head(100)


def build_summary(ranking, matched_news, horizon, horizon_days):
    if ranking.empty:
        return "Nessun dato sufficiente per costruire lo screen."

    top = ranking.head(5)
    lines = [
        "# Blum Market Intelligence - fase 1",
        "",
        f"Orizzonte: **{horizon}**, finestra analitica: **{horizon_days} giorni**.",
        "",
        "Questo output è uno screening di ricerca: segnala cosa visionare e perché, non genera raccomandazioni di acquisto o vendita.",
        "",
        "## Candidati prioritari",
    ]

    for _, row in top.iterrows():
        lines.append(
            f"- **{row['symbol']}**: {row.get('candidate_bucket', '')}; "
            f"tecnica: {row.get('technical_view', '')}; "
            f"sentiment medio news: {row.get('avg_news_sentiment', 0)}; "
            f"news rilevanti: {row.get('news_count', 0)}."
        )

    lines.extend(
        [
            "",
            "## Metodo fase 1",
            "- Prezzi storici e indicatori tecnici via Yahoo Finance.",
            "- News da feed RSS pubblici configurabili.",
            "- Sentiment headline/summary con VADER, utile per triage rapido ma non sufficiente per una tesi finale.",
            "- Ranking qualitativo per priorita di ricerca, separato da decisioni operative.",
            "",
            "## Limiti importanti",
            "- Feed RSS pubblici non equivalgono a Bloomberg Terminal, FactSet o Refinitiv.",
            "- Alcune fonti possono bloccare richieste automatiche o pubblicare solo headline parziali.",
            "- La fase successiva dovrebbe aggiungere fonti premium/API, deduplicazione semantica, memoria storica e backtest.",
        ]
    )

    return "\n".join(lines)


with gr.Blocks(title="Blum Market Intelligence") as demo:
    gr.Markdown("# Blum Market Intelligence")
    gr.Markdown(
        "Screening di ricerca per azioni ed ETF basato su news RSS pubbliche, sentiment, dati storici e analisi tecnica."
    )

    with gr.Row():
        with gr.Column(scale=1):
            symbols_input = gr.Textbox(
                label="Azioni / ETF da analizzare",
                value="SPY, QQQ, AAPL, MSFT, NVDA, TSLA, GLD, TLT",
                lines=4,
            )
            horizon_input = gr.Radio(
                ["Breve termine", "Lungo termine"],
                value="Breve termine",
                label="Visione",
            )
            horizon_days_input = gr.Slider(
                minimum=20,
                maximum=730,
                value=90,
                step=10,
                label="Arco temporale analisi prezzi, in giorni",
            )
            lookback_input = gr.Slider(
                minimum=6,
                maximum=168,
                value=48,
                step=6,
                label="Lookback news RSS, in ore",
            )
            rss_input = gr.Textbox(
                label="Feed RSS, uno per riga",
                value="\n".join(DEFAULT_RSS_FEEDS),
                lines=8,
            )
            run_button = gr.Button("Analizza", variant="primary")

        with gr.Column(scale=2):
            summary_output = gr.Markdown()
            ranking_output = gr.Dataframe(label="Ranking ricerca")
            news_output = gr.Dataframe(label="News rilevanti")

    run_button.click(
        fn=run_screen,
        inputs=[
            symbols_input,
            horizon_input,
            horizon_days_input,
            rss_input,
            lookback_input,
        ],
        outputs=[summary_output, ranking_output, news_output],
    )


if __name__ == "__main__":
    demo.launch()