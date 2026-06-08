import math
import re
from datetime import datetime, timedelta, timezone

import feedparser
import gradio as gr
import pandas as pd
import requests
import yfinance as yf
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer


APP_TITLE = "Blum Market Intelligence"
DEFAULT_SYMBOLS = "SPY, QQQ, IWM, DIA, AAPL, MSFT, NVDA, TSLA, XLF, XLK, XLE, GLD, TLT"
DEFAULT_FEEDS = [
    "https://finance.yahoo.com/news/rssindex",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "https://www.marketwatch.com/rss/topstories",
    "https://www.investing.com/rss/news.rss",
]

ETF_KEYWORDS = {
    "SPY": ["s&p 500", "sp 500", "us stocks", "large cap", "wall street"],
    "QQQ": ["nasdaq", "technology", "mega cap", "growth stocks", "ai stocks"],
    "IWM": ["russell 2000", "small cap", "regional banks"],
    "DIA": ["dow jones", "industrials", "blue chips"],
    "TLT": ["treasury", "bond", "bonds", "yields", "rates", "duration"],
    "GLD": ["gold", "precious metals", "safe haven"],
    "XLF": ["banks", "financials", "credit", "lending"],
    "XLK": ["software", "semiconductors", "technology", "chips"],
    "XLE": ["oil", "energy", "gas", "crude", "opec"],
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

analyzer = SentimentIntensityAnalyzer()


def now_utc_label():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def normalize_symbols(symbols_text):
    parts = re.split(r"[\s,;]+", symbols_text.upper())
    symbols = []
    for part in parts:
        symbol = part.strip().replace("$", "")
        if symbol and symbol not in symbols and re.match(r"^[A-Z0-9.\-]{1,12}$", symbol):
            symbols.append(symbol)
    return symbols[:30]


def safe_float(value, default=math.nan):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def pct_label(value):
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value:+.2f}%"


def sentiment_label(score):
    if score >= 0.2:
        return "Positive"
    if score <= -0.2:
        return "Negative"
    return "Neutral"


def fetch_feed(url, lookback_hours, max_items):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    try:
        response = requests.get(url, headers=HEADERS, timeout=8)
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
    except Exception as exc:
        return [], f"{url}: {exc}"

    source = parsed.feed.get("title", url)
    items = []
    for entry in parsed.entries[:max_items]:
        published = None
        if getattr(entry, "published_parsed", None):
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        elif getattr(entry, "updated_parsed", None):
            published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

        if published and published < cutoff:
            continue

        title = entry.get("title", "").strip()
        if not title:
            continue

        summary = re.sub(r"<[^>]+>", " ", entry.get("summary", "")).strip()
        text = f"{title}. {summary}"
        sentiment = analyzer.polarity_scores(text)["compound"]
        items.append(
            {
                "time": published.strftime("%Y-%m-%d %H:%M") if published else "latest",
                "source": source,
                "title": title,
                "summary": summary[:280],
                "url": entry.get("link", ""),
                "sentiment": round(sentiment, 3),
                "sentiment_label": sentiment_label(sentiment),
            }
        )
    return items, None


def fetch_news(feed_urls, lookback_hours=48, max_items_per_feed=30):
    rows = []
    warnings = []
    for url in feed_urls:
        url = url.strip()
        if not url:
            continue
        items, warning = fetch_feed(url, lookback_hours, max_items_per_feed)
        rows.extend(items)
        if warning:
            warnings.append(warning)

    if not rows:
        return pd.DataFrame(), warnings

    news = pd.DataFrame(rows)
    return news.drop_duplicates(subset=["title", "url"]).reset_index(drop=True), warnings


def relevance_score(symbol, title, summary):
    text = f"{title} {summary}".lower()
    symbol_lower = symbol.lower()
    score = 0
    if re.search(rf"(^|[^a-z0-9]){re.escape(symbol_lower)}([^a-z0-9]|$)", text):
        score += 4
    for keyword in ETF_KEYWORDS.get(symbol, []):
        if keyword in text:
            score += 1
    return score


def map_news_to_symbols(news, symbols):
    if news.empty:
        return pd.DataFrame(
            columns=["symbol", "relevance", "time", "source", "title", "sentiment", "sentiment_label", "url"]
        )

    rows = []
    for symbol in symbols:
        for _, item in news.iterrows():
            relevance = relevance_score(symbol, item["title"], item["summary"])
            if relevance:
                rows.append(
                    {
                        "symbol": symbol,
                        "relevance": relevance,
                        "time": item["time"],
                        "source": item["source"],
                        "title": item["title"],
                        "sentiment": item["sentiment"],
                        "sentiment_label": item["sentiment_label"],
                        "url": item["url"],
                    }
                )

    if not rows:
        return pd.DataFrame(
            columns=["symbol", "relevance", "time", "source", "title", "sentiment", "sentiment_label", "url"]
        )
    return pd.DataFrame(rows)


def rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, math.nan)
    return 100 - (100 / (1 + rs))


def get_close_series(symbol, horizon_days):
    period = "3y" if horizon_days > 365 else "2y"
    data = yf.download(
        symbol,
        period=period,
        interval="1d",
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if data is None or data.empty or "Close" not in data:
        return pd.Series(dtype=float)

    close = data["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = pd.to_numeric(close, errors="coerce").dropna()
    return close


def technical_snapshot(symbol, horizon_days):
    try:
        close = get_close_series(symbol, horizon_days)
        if len(close) < 50:
            return {"symbol": symbol, "error": "Insufficient price history"}

        latest = safe_float(close.iloc[-1])
        sma20 = safe_float(close.rolling(20).mean().iloc[-1])
        sma50 = safe_float(close.rolling(50).mean().iloc[-1])
        sma200 = safe_float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else math.nan
        latest_rsi = safe_float(rsi(close).iloc[-1])

        window = min(max(int(horizon_days), 20), len(close) - 1)
        horizon_return = safe_float((latest / close.iloc[-window] - 1) * 100)
        one_day_return = safe_float((latest / close.iloc[-2] - 1) * 100)
        vol = safe_float(close.pct_change().tail(60).std() * math.sqrt(252) * 100)

        trend_score = 0
        trend_score += 1 if latest > sma20 else -1
        trend_score += 1 if latest > sma50 else -1
        if not pd.isna(sma200):
            trend_score += 1 if latest > sma200 else -1

        if latest_rsi >= 72:
            technical_view = "Extended"
        elif latest_rsi <= 32:
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
            "1d": round(one_day_return, 2),
            "horizon_return": round(horizon_return, 2),
            "volatility": round(vol, 2),
            "sma20": round(sma20, 2),
            "sma50": round(sma50, 2),
            "sma200": round(sma200, 2) if not pd.isna(sma200) else None,
            "rsi14": round(latest_rsi, 1) if not pd.isna(latest_rsi) else None,
            "technical_view": technical_view,
            "trend_score": trend_score,
            "error": "",
        }
    except Exception as exc:
        return {"symbol": symbol, "error": str(exc)[:160]}


def bucket_candidate(row):
    score = row.get("trend_score", 0)
    score += 1 if row.get("news_count", 0) >= 3 else 0
    score += 1 if row.get("avg_sentiment", 0) >= 0.18 else 0
    score -= 1 if row.get("avg_sentiment", 0) <= -0.18 else 0
    score += 1 if row.get("horizon_return", 0) > 0 else 0

    rsi_value = row.get("rsi14")
    if rsi_value and rsi_value > 76:
        score -= 1

    if score >= 5:
        return "A - Research now"
    if score >= 3:
        return "B - Watchlist"
    if score >= 1:
        return "C - Weak signal"
    return "Risk / insufficient evidence"


def build_market_pulse(news):
    if news.empty:
        return {
            "headline_count": 0,
            "positive": 0,
            "neutral": 0,
            "negative": 0,
            "avg_sentiment": 0,
        }

    labels = news["sentiment_label"].value_counts()
    return {
        "headline_count": int(len(news)),
        "positive": int(labels.get("Positive", 0)),
        "neutral": int(labels.get("Neutral", 0)),
        "negative": int(labels.get("Negative", 0)),
        "avg_sentiment": round(float(news["sentiment"].mean()), 3),
    }


def make_summary_html(pulse, ranking, warnings, horizon_days):
    updated = now_utc_label()
    if ranking.empty:
        leaders = "No ranked instruments yet."
    else:
        leaders = "".join(
            f"""
            <div class="leader">
              <div><strong>{row['symbol']}</strong><span>{row['bucket']}</span></div>
              <p>{row['technical_view']} | news sentiment {row['avg_sentiment']:+.2f} | {row['news_count']} matched headlines</p>
            </div>
            """
            for _, row in ranking.head(4).iterrows()
        )

    warning_html = ""
    if warnings:
        warning_html = (
            "<div class='warning'><strong>Source warnings:</strong> "
            + " | ".join(warnings[:3])
            + "</div>"
        )

    return f"""
    <section class="hero">
      <div>
        <p class="eyebrow">Live public-market intelligence</p>
        <h1>{APP_TITLE}</h1>
        <p class="subtitle">Real-time public RSS monitoring, equity/ETF sentiment triage and technical screening.</p>
      </div>
      <div class="stamp">Updated<br><strong>{updated}</strong></div>
    </section>
    <section class="tiles">
      <div class="tile"><span>Headlines</span><strong>{pulse['headline_count']}</strong></div>
      <div class="tile positive"><span>Positive</span><strong>{pulse['positive']}</strong></div>
      <div class="tile neutral"><span>Neutral</span><strong>{pulse['neutral']}</strong></div>
      <div class="tile negative"><span>Negative</span><strong>{pulse['negative']}</strong></div>
      <div class="tile"><span>Avg sentiment</span><strong>{pulse['avg_sentiment']:+.2f}</strong></div>
      <div class="tile"><span>Price horizon</span><strong>{horizon_days}d</strong></div>
    </section>
    <section class="panel">
      <div class="panel-title">Priority research queue</div>
      <div class="leaders">{leaders}</div>
    </section>
    {warning_html}
    """


def build_tape_html(news):
    if news.empty:
        return "<div class='tape empty'>No live headlines were retrieved. Try a wider lookback or different RSS feeds.</div>"

    items = []
    for _, row in news.head(18).iterrows():
        sentiment_class = row["sentiment_label"].lower()
        title = row["title"].replace("<", "&lt;").replace(">", "&gt;")
        url = row.get("url", "")
        link = f"<a href='{url}' target='_blank'>{title}</a>" if url else title
        items.append(
            f"""
            <article class="headline {sentiment_class}">
              <div class="headline-meta"><span>{row['time']}</span><span>{row['source']}</span><span>{row['sentiment_label']} {row['sentiment']:+.2f}</span></div>
              <h3>{link}</h3>
            </article>
            """
        )
    return "<div class='tape'>" + "".join(items) + "</div>"


def run_dashboard(symbols_text, horizon_mode, horizon_days, rss_text, lookback_hours):
    symbols = normalize_symbols(symbols_text)
    feeds = [line.strip() for line in rss_text.splitlines() if line.strip()]
    if not symbols:
        return "<div class='warning'>Add at least one ticker or ETF.</div>", pd.DataFrame(), pd.DataFrame(), ""

    news, warnings = fetch_news(feeds, int(lookback_hours), max_items_per_feed=35)
    matched_news = map_news_to_symbols(news, symbols)

    rows = []
    for symbol in symbols:
        tech = technical_snapshot(symbol, int(horizon_days))
        symbol_news = matched_news[matched_news["symbol"] == symbol] if not matched_news.empty else pd.DataFrame()
        avg_sentiment = round(float(symbol_news["sentiment"].mean()), 3) if not symbol_news.empty else 0.0

        row = {
            "symbol": symbol,
            "bucket": "Risk / insufficient evidence",
            "last": None,
            "1d %": None,
            f"{int(horizon_days)}d %": None,
            "vol %": None,
            "RSI 14": None,
            "technical_view": "n/a",
            "news_count": int(len(symbol_news)),
            "avg_sentiment": avg_sentiment,
            "status": tech.get("error", ""),
        }

        if not tech.get("error"):
            row.update(
                {
                    "last": tech["last"],
                    "1d %": tech["1d"],
                    f"{int(horizon_days)}d %": tech["horizon_return"],
                    "vol %": tech["volatility"],
                    "RSI 14": tech["rsi14"],
                    "technical_view": tech["technical_view"],
                    "trend_score": tech["trend_score"],
                    "status": "Research signal, not a trade recommendation",
                }
            )
            row["bucket"] = bucket_candidate(
                {
                    **tech,
                    "news_count": row["news_count"],
                    "avg_sentiment": row["avg_sentiment"],
                }
            )
        else:
            row["trend_score"] = -99

        rows.append(row)

    ranking = pd.DataFrame(rows)
    bucket_order = {
        "A - Research now": 0,
        "B - Watchlist": 1,
        "C - Weak signal": 2,
        "Risk / insufficient evidence": 3,
    }
    ranking["_order"] = ranking["bucket"].map(bucket_order).fillna(9)
    ranking = ranking.sort_values(
        by=["_order", "trend_score", "avg_sentiment", "news_count"],
        ascending=[True, False, False, False],
    ).drop(columns=["_order", "trend_score"])

    news_table = matched_news.sort_values(
        by=["relevance", "sentiment"], ascending=[False, False]
    ).head(120)

    pulse = build_market_pulse(news)
    summary = make_summary_html(pulse, ranking, warnings, int(horizon_days))
    tape = build_tape_html(news)

    return summary, ranking, news_table, tape


CSS = """
:root {
  --bg: #080b10;
  --panel: #111722;
  --panel-2: #151d2b;
  --line: #263244;
  --text: #eef3f8;
  --muted: #9aa7b7;
  --green: #33d17a;
  --red: #ff5f62;
  --amber: #f7c948;
  --blue: #6ea8fe;
}
body, .gradio-container {
  background: var(--bg) !important;
  color: var(--text) !important;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
}
.gradio-container {
  max-width: 1440px !important;
}
#settings-panel {
  background: var(--panel) !important;
  border: 1px solid var(--line) !important;
  border-radius: 8px !important;
  padding: 14px !important;
}
.hero {
  min-height: 180px;
  display: flex;
  justify-content: space-between;
  gap: 24px;
  align-items: flex-end;
  padding: 28px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background:
    linear-gradient(135deg, rgba(110,168,254,.20), transparent 42%),
    linear-gradient(90deg, #101826, #0b111a);
}
.eyebrow {
  color: var(--blue);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: .08em;
  margin: 0 0 10px;
}
.hero h1 {
  color: var(--text);
  font-size: 42px;
  line-height: 1;
  margin: 0;
  letter-spacing: 0;
}
.subtitle {
  max-width: 720px;
  color: var(--muted);
  margin: 14px 0 0;
  font-size: 16px;
}
.stamp {
  color: var(--muted);
  text-align: right;
  font-size: 12px;
}
.stamp strong {
  color: var(--text);
  font-size: 14px;
}
.tiles {
  display: grid;
  grid-template-columns: repeat(6, minmax(120px, 1fr));
  gap: 10px;
  margin: 12px 0;
}
.tile {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px;
}
.tile span {
  display: block;
  color: var(--muted);
  font-size: 12px;
}
.tile strong {
  display: block;
  color: var(--text);
  font-size: 26px;
  margin-top: 4px;
}
.tile.positive strong { color: var(--green); }
.tile.negative strong { color: var(--red); }
.tile.neutral strong { color: var(--amber); }
.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 12px;
}
.panel-title {
  color: var(--muted);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: .08em;
  margin-bottom: 12px;
}
.leaders {
  display: grid;
  grid-template-columns: repeat(2, minmax(240px, 1fr));
  gap: 10px;
}
.leader {
  background: var(--panel-2);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
}
.leader div {
  display: flex;
  justify-content: space-between;
  gap: 10px;
}
.leader strong {
  color: var(--text);
  font-size: 18px;
}
.leader span {
  color: var(--blue);
  font-size: 13px;
}
.leader p {
  color: var(--muted);
  margin: 8px 0 0;
  font-size: 13px;
}
.warning {
  border: 1px solid rgba(247,201,72,.45);
  background: rgba(247,201,72,.09);
  color: #ffe08a;
  border-radius: 8px;
  padding: 12px;
  margin: 12px 0;
}
.tape {
  display: grid;
  grid-template-columns: repeat(2, minmax(280px, 1fr));
  gap: 10px;
}
.headline {
  background: var(--panel);
  border: 1px solid var(--line);
  border-left: 3px solid var(--amber);
  border-radius: 8px;
  padding: 12px;
}
.headline.positive { border-left-color: var(--green); }
.headline.negative { border-left-color: var(--red); }
.headline-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  color: var(--muted);
  font-size: 11px;
}
.headline h3 {
  margin: 8px 0 0;
  font-size: 14px;
  line-height: 1.35;
}
.headline a {
  color: var(--text);
  text-decoration: none;
}
.headline a:hover {
  color: var(--blue);
}
.empty {
  color: var(--muted);
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: 8px;
}
label, .block-title, .wrap {
  color: var(--text) !important;
}
button {
  border-radius: 6px !important;
}
@media (max-width: 900px) {
  .hero { align-items: flex-start; flex-direction: column; }
  .hero h1 { font-size: 32px; }
  .stamp { text-align: left; }
  .tiles { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
  .leaders, .tape { grid-template-columns: 1fr; }
}
"""


with gr.Blocks(title=APP_TITLE, css=CSS, theme=gr.themes.Base()) as demo:
    with gr.Row():
        with gr.Column(scale=7):
            summary_output = gr.HTML()
        with gr.Column(scale=3, elem_id="settings-panel"):
            gr.Markdown("### Controls")
            symbols_input = gr.Textbox(
                label="Stocks and ETFs",
                value=DEFAULT_SYMBOLS,
                lines=4,
            )
            horizon_mode = gr.Radio(
                ["Short-term", "Long-term"],
                value="Short-term",
                label="Investment lens",
            )
            horizon_days = gr.Slider(
                minimum=20,
                maximum=730,
                value=90,
                step=10,
                label="Historical price horizon, days",
            )
            lookback_hours = gr.Slider(
                minimum=6,
                maximum=168,
                value=48,
                step=6,
                label="News lookback, hours",
            )
            refresh_button = gr.Button("Refresh live intelligence", variant="primary")

    with gr.Tabs():
        with gr.Tab("Research Queue"):
            ranking_output = gr.Dataframe(
                label="Equity / ETF research ranking",
                interactive=False,
                wrap=True,
            )
        with gr.Tab("Live News Tape"):
            tape_output = gr.HTML()
        with gr.Tab("Matched Headlines"):
            news_output = gr.Dataframe(
                label="Headlines mapped to tickers",
                interactive=False,
                wrap=True,
            )
        with gr.Tab("Sources"):
            rss_input = gr.Textbox(
                label="RSS feeds, one per line",
                value="\n".join(DEFAULT_FEEDS),
                lines=8,
            )
            gr.Markdown(
                "Public RSS feeds can be delayed, rate-limited or partially blocked. "
                "This Space is a research triage tool, not a licensed Bloomberg replacement and not financial advice."
            )

    inputs = [symbols_input, horizon_mode, horizon_days, rss_input, lookback_hours]
    outputs = [summary_output, ranking_output, news_output, tape_output]
    refresh_button.click(run_dashboard, inputs=inputs, outputs=outputs)
    demo.load(run_dashboard, inputs=inputs, outputs=outputs)


demo.launch()
