from __future__ import annotations

from datetime import datetime
from statistics import mean
import uuid

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import MarketBrainSnapshot, SignalSnapshot
from app.services.dashboard import dashboard_overview
from app.services.etf import list_etf_trends
from app.services.ipo import ipo_radar
from app.services.live import live_news, market_sentiment
from app.services.stock import stock_radar


def build_market_brain(db: Session, persist: bool = True) -> dict:
    overview = dashboard_overview(db)
    sentiment = market_sentiment(db, hours=48)
    stocks = stock_radar(db, limit=100)
    etfs = list_etf_trends(db, limit=30)
    ipo = ipo_radar(db, limit=80)
    news = live_news(db, limit=50)
    latest_signals = latest_distinct_signals(db, limit=80)

    regime = infer_regime(latest_signals, sentiment, stocks, etfs)
    brain_score = compute_brain_score(latest_signals, sentiment, overview, ipo)
    opportunity_stack = build_opportunity_stack(stocks, etfs, ipo)
    scenarios = build_forward_scenarios(regime, latest_signals, sentiment, stocks, etfs, ipo, news)
    risks = build_risk_alerts(stocks, latest_signals, sentiment, ipo, overview)
    evidence = evidence_ledger(overview, sentiment, stocks, etfs, ipo, news, latest_signals)
    summary = brain_summary(regime, brain_score, opportunity_stack, risks)

    payload = {
        "run_id": f"brain-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}",
        "created_at": datetime.utcnow().isoformat(),
        "data_mode": "real_public_data_only",
        "brain_score": brain_score,
        "regime": regime,
        "horizon": "Intraday / 5D / 20D / 60D research horizons",
        "summary": summary,
        "market_now": {
            "average_sentiment": sentiment["average_sentiment"],
            "news_count_48h": sentiment["article_count"],
            "signal_count": overview["market_pulse"]["signal_count"],
            "asset_count": overview["market_pulse"]["asset_count"],
            "classification_mix": overview["market_pulse"]["classification_mix"],
            "top_themes": sentiment["themes"][:8],
            "top_live_news": news[:10],
        },
        "opportunity_stack": opportunity_stack,
        "forward_scenarios": scenarios,
        "risk_alerts": risks,
        "evidence_ledger": evidence,
        "model_stack": {
            "sentiment": "FinBERT-led sentiment records when model loading is available; VADER remains a baseline comparator.",
            "semantic": "Sentence-transformer embeddings and theme clusters where stored news embeddings exist.",
            "time_series": "Statistical anomaly, trend, volatility and regime factors from stored OHLCV history.",
            "reasoning": "Evidence-bound Market Brain orchestration, not a free-form trade recommender.",
            "rules": "Blum Intelligence Score, IPO readiness model and PM-style research-priority buckets.",
        },
        "disclaimer": "Educational research case study only. Not financial advice, not a recommendation and not an operational trading signal.",
    }

    if persist:
        db.add(
            MarketBrainSnapshot(
                run_id=payload["run_id"],
                brain_score=brain_score,
                regime=regime,
                horizon=payload["horizon"],
                summary=summary,
                structured_output=payload,
            )
        )
        db.commit()

    return payload


def latest_market_brain(db: Session) -> dict:
    snapshot = db.scalar(select(MarketBrainSnapshot).order_by(desc(MarketBrainSnapshot.created_at)).limit(1))
    if snapshot is None:
        return build_market_brain(db, persist=True)
    payload = dict(snapshot.structured_output or {})
    payload["last_snapshot"] = {
        "run_id": snapshot.run_id,
        "created_at": snapshot.created_at,
        "brain_score": snapshot.brain_score,
        "regime": snapshot.regime,
    }
    return payload


def latest_distinct_signals(db: Session, limit: int = 80) -> list[SignalSnapshot]:
    signals = db.scalars(select(SignalSnapshot).order_by(desc(SignalSnapshot.created_at), desc(SignalSnapshot.blum_score)).limit(limit * 3)).all()
    latest: dict[str, SignalSnapshot] = {}
    for signal in signals:
        latest.setdefault(signal.ticker, signal)
        if len(latest) >= limit:
            break
    return list(latest.values())


def infer_regime(signals: list[SignalSnapshot], sentiment: dict, stocks: dict, etfs: list[dict]) -> str:
    if not signals:
        return "Evidence Formation"
    scores = [float(signal.blum_score) for signal in signals]
    avg_score = mean(scores)
    sentiment_score = float(sentiment.get("average_sentiment") or 0)
    high_risk = len([signal for signal in signals if signal.risk_level == "High"]) / max(1, len(signals))
    etf_confirmation = mean([float(item.get("confirmation_score") or 0) for item in etfs[:8]]) if etfs else 0
    quality_count = len(stocks.get("sections", {}).get("quality_momentum", []))
    divergence_count = len(stocks.get("sections", {}).get("sentiment_divergence", []))

    if sentiment_score <= -0.16 and avg_score < 56:
        return "Defensive / Risk-Off"
    if high_risk >= 0.36 and avg_score >= 62:
        return "High-Beta Momentum With Fragile Risk"
    if divergence_count >= 3:
        return "Price Narrative Divergence"
    if sentiment_score >= 0.14 and avg_score >= 68 and etf_confirmation >= 58:
        return "Risk-On Narrative Momentum"
    if quality_count >= 4 or etf_confirmation >= 62:
        return "Selective Rotation"
    return "Mixed Cross-Currents"


def compute_brain_score(signals: list[SignalSnapshot], sentiment: dict, overview: dict, ipo: dict) -> float:
    signal_component = mean([float(signal.blum_score) for signal in signals[:20]]) if signals else 0
    sentiment_component = clamp((float(sentiment.get("average_sentiment") or 0) + 1) * 50)
    readiness = overview.get("readiness", {})
    asset_count = max(1, int(overview.get("market_pulse", {}).get("asset_count") or 1))
    coverage_component = clamp((float(readiness.get("signal_count") or 0) / asset_count) * 100)
    news_component = clamp(float(sentiment.get("article_count") or 0) * 2.5)
    ipo_component = float(ipo.get("summary", {}).get("top_opportunity_score") or 0)
    return round(
        signal_component * 0.34
        + sentiment_component * 0.18
        + coverage_component * 0.16
        + news_component * 0.14
        + ipo_component * 0.18,
        2,
    )


def build_opportunity_stack(stocks: dict, etfs: list[dict], ipo: dict) -> dict:
    sections = stocks.get("sections", {})
    return {
        "stock_research_priorities": [
            compact_stock(row) for row in (
                sections.get("strongest_signals", [])[:8]
                + sections.get("quality_momentum", [])[:5]
                + sections.get("quiet_accumulation", [])[:5]
            )
        ][:14],
        "etf_rotation_leaders": [compact_etf(item) for item in etfs[:10]],
        "ipo_watch": [compact_ipo(row) for row in ipo.get("sections", {}).get("highest_opportunity", [])[:10]],
        "narrative_breakouts": [compact_stock(row) for row in sections.get("narrative_breakouts", [])[:8]],
        "technical_breakouts": [compact_stock(row) for row in sections.get("technical_breakouts", [])[:8]],
        "sentiment_divergence": [compact_stock(row) for row in sections.get("sentiment_divergence", [])[:8]],
    }


def build_forward_scenarios(regime: str, signals: list[SignalSnapshot], sentiment: dict, stocks: dict, etfs: list[dict], ipo: dict, news: list[dict]) -> list[dict]:
    top_signal = signals[0] if signals else None
    top_etf = etfs[0] if etfs else None
    top_ipo = (ipo.get("sections", {}).get("highest_opportunity") or [None])[0]
    sentiment_score = float(sentiment.get("average_sentiment") or 0)
    scenarios = [
        {
            "name": "Base Case: Selective Confirmation",
            "probability_proxy": probability_from_regime(regime, "base"),
            "time_horizon": "5D to 20D",
            "drivers": [
                f"Current regime classified as {regime}.",
                f"48h news sentiment is {sentiment_score:.2f} across {sentiment.get('article_count', 0)} articles.",
                f"Top ETF confirmation is {top_etf['ticker']} at {top_etf['confirmation_score']:.1f}." if top_etf else "ETF confirmation evidence is not available yet.",
            ],
            "watch_points": [
                "Confirm whether top signals keep price above short moving averages.",
                "Watch for sentiment deterioration while price momentum remains elevated.",
                "Prioritize names with ETF confirmation and moderate risk classification.",
            ],
            "evidence": evidence_refs(top_signal, top_etf, top_ipo, news),
        },
        {
            "name": "Upside Scenario: Narrative Breakout Broadens",
            "probability_proxy": probability_from_regime(regime, "upside"),
            "time_horizon": "1D to 20D",
            "drivers": [
                "Narrative strength improves when sentiment, news intensity and technical confirmation align.",
                f"Top signal: {top_signal.ticker} / {top_signal.classification} / score {top_signal.blum_score:.1f}." if top_signal else "No scored top signal is stored yet.",
                f"Primary-market heat proxy top score {ipo.get('summary', {}).get('top_opportunity_score', 0):.1f}.",
            ],
            "watch_points": [
                "Look for volume confirmation and reduced downside volatility.",
                "Require source-backed news drivers rather than price-only momentum.",
                "Check whether sector ETFs confirm the same narrative.",
            ],
            "evidence": evidence_refs(top_signal, top_etf, top_ipo, news),
        },
        {
            "name": "Downside Scenario: Sentiment Or Liquidity Shock",
            "probability_proxy": probability_from_regime(regime, "downside"),
            "time_horizon": "1D to 60D",
            "drivers": [
                "High-risk momentum can fail quickly when news sentiment reverses or volume gaps appear.",
                f"High-risk stock radar count: {len(stocks.get('sections', {}).get('high_risk_momentum', []))}.",
                f"Negative sentiment headlines: {sentiment.get('label_counts', {}).get('negative', 0)}.",
            ],
            "watch_points": [
                "Monitor gap-down moves, failed breakouts and sudden negative news clusters.",
                "Downgrade candidates with price strength but falling sentiment.",
                "Treat unpriced assets and missing provider data as evidence gaps, not signals.",
            ],
            "evidence": evidence_refs(top_signal, top_etf, top_ipo, news),
        },
    ]
    return scenarios


def build_risk_alerts(stocks: dict, signals: list[SignalSnapshot], sentiment: dict, ipo: dict, overview: dict) -> list[dict]:
    alerts: list[dict] = []
    high_risk = stocks.get("sections", {}).get("high_risk_momentum", [])
    divergence = stocks.get("sections", {}).get("sentiment_divergence", [])
    data_gaps = stocks.get("data_gaps", [])
    if high_risk:
        alerts.append({"severity": "High", "title": "High-risk momentum cluster", "detail": f"{len(high_risk)} stocks have momentum but high risk classification.", "tickers": [row["ticker"] for row in high_risk[:8]]})
    if divergence:
        alerts.append({"severity": "Medium", "title": "Price/sentiment divergence", "detail": f"{len(divergence)} stocks show narrative contradiction.", "tickers": [row["ticker"] for row in divergence[:8]]})
    if float(sentiment.get("average_sentiment") or 0) < -0.12:
        alerts.append({"severity": "Medium", "title": "Negative market narrative", "detail": "Market-wide sentiment is below the defensive threshold.", "tickers": []})
    if data_gaps:
        alerts.append({"severity": "Evidence", "title": "Incomplete public data coverage", "detail": f"{len(data_gaps)} stock rows still lack full signal snapshots.", "tickers": [row["ticker"] for row in data_gaps[:10]]})
    ipo_high_risk = [
        row for row in ipo.get("rows", [])
        if float(row.get("score", {}).get("valuation_risk_score") or 0) >= 45
    ]
    if ipo_high_risk:
        alerts.append({"severity": "Medium", "title": "IPO filing risk language", "detail": f"{len(ipo_high_risk)} IPO candidates include elevated filing-risk terms.", "tickers": [row["company"]["name"] for row in ipo_high_risk[:5]]})
    if not signals and overview.get("market_pulse", {}).get("price_row_count", 0) == 0:
        alerts.append({"severity": "Evidence", "title": "No market history stored", "detail": "Public price providers have not yet populated OHLCV rows.", "tickers": []})
    return alerts


def evidence_ledger(overview: dict, sentiment: dict, stocks: dict, etfs: list[dict], ipo: dict, news: list[dict], signals: list[SignalSnapshot]) -> dict:
    return {
        "stored_assets": overview["market_pulse"]["asset_count"],
        "stored_price_rows": overview["market_pulse"]["price_row_count"],
        "stored_news_articles": overview["market_pulse"]["article_count"],
        "sentiment_articles_48h": sentiment["article_count"],
        "distinct_signals": len(signals),
        "stock_radar_rows": len(stocks.get("rows", [])),
        "stock_data_gaps": len(stocks.get("data_gaps", [])),
        "etf_rotation_rows": len(etfs),
        "ipo_companies_observed": ipo.get("summary", {}).get("companies_observed", 0),
        "ipo_filings_observed": ipo.get("summary", {}).get("filings_observed", 0),
        "live_news_rows": len(news),
        "data_policy": "All outputs are derived from stored public data. Missing evidence remains visible as a gap.",
    }


def brain_summary(regime: str, brain_score: float, opportunity_stack: dict, risks: list[dict]) -> str:
    stocks = len(opportunity_stack.get("stock_research_priorities", []))
    etfs = len(opportunity_stack.get("etf_rotation_leaders", []))
    ipos = len(opportunity_stack.get("ipo_watch", []))
    return (
        f"Market Brain classified the current state as {regime} with a {brain_score:.1f}/100 evidence score. "
        f"It surfaced {stocks} stock research priorities, {etfs} ETF rotation leaders and {ipos} IPO/pre-listing watch items. "
        f"{len(risks)} risk alerts are active. Outputs are research triage, not recommendations."
    )


def compact_stock(row: dict) -> dict:
    signal = row.get("signal") or {}
    snapshot = row.get("market_snapshot") or {}
    return {
        "ticker": row.get("ticker"),
        "name": row.get("asset", {}).get("name"),
        "sector": row.get("asset", {}).get("sector"),
        "research_priority": row.get("research_priority"),
        "classification": signal.get("classification"),
        "score": signal.get("blum_score"),
        "risk_level": signal.get("risk_level"),
        "price": snapshot.get("price"),
        "currency": snapshot.get("currency"),
        "perf_1d": snapshot.get("perf_1d"),
        "perf_5d": snapshot.get("perf_5d"),
        "why": row.get("why_watch"),
        "tags": row.get("radar_tags", [])[:6],
    }


def compact_etf(item: dict) -> dict:
    snapshot = item.get("market_snapshot") or {}
    return {
        "ticker": item.get("ticker"),
        "name": item.get("asset", {}).get("name"),
        "category": item.get("category"),
        "confirmation_score": item.get("confirmation_score"),
        "momentum_score": item.get("momentum_score"),
        "thematic_score": item.get("thematic_score"),
        "price": snapshot.get("price"),
        "currency": snapshot.get("currency"),
        "perf_1d": snapshot.get("perf_1d"),
        "perf_1m": snapshot.get("perf_1m"),
    }


def compact_ipo(row: dict) -> dict:
    company = row.get("company", {})
    latest = row.get("latest_filing") or {}
    score = row.get("score", {})
    return {
        "name": company.get("name"),
        "cik": company.get("cik"),
        "sector": company.get("sector"),
        "latest_form": latest.get("form_type"),
        "filing_date": latest.get("filing_date"),
        "filing_url": latest.get("url"),
        "classification": score.get("classification"),
        "opportunity_score": score.get("opportunity_score"),
        "readiness_score": score.get("readiness_score"),
        "narrative_heat_score": score.get("narrative_heat_score"),
        "time_horizon": score.get("time_horizon"),
        "why": score.get("explanation"),
    }


def evidence_refs(top_signal: SignalSnapshot | None, top_etf: dict | None, top_ipo: dict | None, news: list[dict]) -> dict:
    return {
        "top_signal": {
            "ticker": top_signal.ticker,
            "classification": top_signal.classification,
            "score": top_signal.blum_score,
        } if top_signal else None,
        "top_etf": compact_etf(top_etf) if top_etf else None,
        "top_ipo": compact_ipo(top_ipo) if top_ipo else None,
        "news": [
            {
                "title": article.get("title"),
                "source": article.get("source"),
                "url": article.get("url"),
                "published_at": article.get("published_at"),
            }
            for article in news[:5]
        ],
    }


def probability_from_regime(regime: str, scenario: str) -> int:
    matrix = {
        "Risk-On Narrative Momentum": {"base": 54, "upside": 34, "downside": 12},
        "Selective Rotation": {"base": 60, "upside": 24, "downside": 16},
        "High-Beta Momentum With Fragile Risk": {"base": 42, "upside": 24, "downside": 34},
        "Price Narrative Divergence": {"base": 38, "upside": 18, "downside": 44},
        "Defensive / Risk-Off": {"base": 46, "upside": 14, "downside": 40},
        "Evidence Formation": {"base": 70, "upside": 10, "downside": 20},
        "Mixed Cross-Currents": {"base": 56, "upside": 22, "downside": 22},
    }
    return matrix.get(regime, matrix["Mixed Cross-Currents"])[scenario]


def clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, float(value)))
