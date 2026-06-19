from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import math
import re
from statistics import mean
from uuid import uuid4

import pandas as pd
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.ai.llm_provider import EvidenceBoundFallbackProvider
from app.models import Asset, ChatMessage, ChatSession, NewsArticle, NewsAssetLink, PriceHistory, SignalSnapshot
from app.services.blum_training_memory import BlumTrainingMemoryService
from app.services.fundamentals import fundamentals_for_asset
from app.services.live import market_sentiment
from app.services.market_data import market_snapshot_for_asset
from app.services.semantic import SemanticService
from app.services.strategic_intelligence import community_sentiment, market_narrative, opportunity_radar
from app.services.dashboard import signal_payload
from app.services.technical_analysis_engine import TechnicalAnalysisEngine


DISCLAIMER = "Analisi informativa, non consulenza finanziaria. I livelli sono tecnici e probabilistici, non garanzie."

MARKET_TERM_TICKERS = {
    "FTSE MIB": ["^FTSEMIB", "IMIB.MI", "ENEL.MI", "ENI.MI", "ISP.MI", "UCG.MI", "RACE.MI", "LDO.MI", "PRY.MI"],
    "FTSEMIB": ["^FTSEMIB", "IMIB.MI", "ENEL.MI", "ENI.MI", "ISP.MI", "UCG.MI", "RACE.MI", "LDO.MI", "PRY.MI"],
    "DAX": ["^GDAXI", "EXS1.DE", "SIE.DE", "SAP", "ALV.DE", "DTE.DE", "IFX.DE", "MBG.DE", "DBK.DE"],
    "S&P 500": ["SPY", "VOO", "IVV", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META"],
    "SP500": ["SPY", "VOO", "IVV", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META"],
    "NASDAQ": ["QQQ", "XLK", "NVDA", "MSFT", "AAPL", "AVGO", "AMD", "GOOGL", "META"],
    "GERMANY": ["^GDAXI", "EXS1.DE", "SIE.DE", "ALV.DE", "DTE.DE", "IFX.DE", "MBG.DE", "DBK.DE"],
    "GERMAN": ["^GDAXI", "EXS1.DE", "SIE.DE", "ALV.DE", "DTE.DE", "IFX.DE", "MBG.DE", "DBK.DE"],
    "ITALY": ["^FTSEMIB", "IMIB.MI", "ENEL.MI", "ENI.MI", "ISP.MI", "UCG.MI", "RACE.MI", "LDO.MI"],
    "ITALIAN": ["^FTSEMIB", "IMIB.MI", "ENEL.MI", "ENI.MI", "ISP.MI", "UCG.MI", "RACE.MI", "LDO.MI"],
    "EUROPE": ["^STOXX50E", "EXSA.DE", "^GDAXI", "^FTSEMIB", "^FCHI", "^FTSE", "SIE.DE", "ASML", "SAP", "MC.PA"],
    "EUROPEAN": ["^STOXX50E", "EXSA.DE", "^GDAXI", "^FTSEMIB", "^FCHI", "^FTSE", "SIE.DE", "ASML", "SAP", "MC.PA"],
}

LANGUAGE_HINTS = {
    "it": [" cosa ", " quali ", " analizza ", " trova ", " comprare", " ingresso", " rischio", " titolo", " azione", " uscita", " monitorare"],
    "en": [" what ", " which ", " analyze ", " find ", " entry", " risk", " stock", " watch", " compare", " setup"],
    "de": [" was ", " welche ", " analysiere ", " risiko", " aktie", " einstieg", " beobachten", " vergleich"],
    "fr": [" que ", " quels ", " analyse ", " risque", " action", " entree", " surveiller", " comparer"],
    "es": [" que ", " cuales ", " analiza ", " riesgo", " accion", " entrada", " vigilar", " comparar"],
}

LABELS = {
    "it": {
        "summary": "Sintesi",
        "observed": "Dati osservati",
        "technical": "Analisi tecnica",
        "fundamental": "Analisi fondamentale",
        "sentiment": "Sentiment / news / narrativa",
        "scenarios": "Scenario bull / base / bear",
        "levels": "Livelli tecnici rilevanti",
        "risks": "Rischi",
        "conclusion": "Conclusione operativa informativa",
        "disclaimer": DISCLAIMER,
        "missing": "Dati mancanti o incompleti",
    },
    "en": {
        "summary": "Summary",
        "observed": "Observed Data",
        "technical": "Technical Analysis",
        "fundamental": "Fundamental Analysis",
        "sentiment": "Sentiment / News / Narrative",
        "scenarios": "Bull / Base / Bear Scenario",
        "levels": "Relevant Technical Levels",
        "risks": "Risks",
        "conclusion": "Informational Operating View",
        "disclaimer": "Informational research only, not financial advice. Technical levels are probabilistic, not guarantees.",
        "missing": "Missing or Incomplete Data",
    },
    "de": {
        "summary": "Zusammenfassung",
        "observed": "Beobachtete Daten",
        "technical": "Technische Analyse",
        "fundamental": "Fundamentalanalyse",
        "sentiment": "Sentiment / News / Narrative",
        "scenarios": "Bull / Base / Bear Szenario",
        "levels": "Relevante technische Level",
        "risks": "Risiken",
        "conclusion": "Informative operative Sicht",
        "disclaimer": "Nur informative Analyse, keine Finanzberatung. Technische Level sind probabilistisch, keine Garantien.",
        "missing": "Fehlende oder unvollstaendige Daten",
    },
    "fr": {
        "summary": "Synthese",
        "observed": "Donnees observees",
        "technical": "Analyse technique",
        "fundamental": "Analyse fondamentale",
        "sentiment": "Sentiment / news / narrative",
        "scenarios": "Scenario bull / base / bear",
        "levels": "Niveaux techniques pertinents",
        "risks": "Risques",
        "conclusion": "Vue operationnelle informative",
        "disclaimer": "Analyse informative uniquement, pas un conseil financier. Les niveaux techniques sont probabilistes, pas des garanties.",
        "missing": "Donnees manquantes ou incompletes",
    },
    "es": {
        "summary": "Sintesis",
        "observed": "Datos observados",
        "technical": "Analisis tecnico",
        "fundamental": "Analisis fundamental",
        "sentiment": "Sentimiento / noticias / narrativa",
        "scenarios": "Escenario bull / base / bear",
        "levels": "Niveles tecnicos relevantes",
        "risks": "Riesgos",
        "conclusion": "Vision operativa informativa",
        "disclaimer": "Analisis informativo, no asesoramiento financiero. Los niveles tecnicos son probabilisticos, no garantias.",
        "missing": "Datos faltantes o incompletos",
    },
}


def financial_chat_response(
    db: Session,
    message: str,
    tickers: list[str] | None = None,
    horizon: str = "multi-horizon",
    risk_profile: str = "balanced",
    include_semantic_search: bool = True,
    language: str | None = None,
    session_id: str | None = None,
    mode: str | None = None,
) -> dict:
    detected_language = normalize_language(language) or detect_language(message)
    intent = infer_intent(message, mode)
    session = upsert_chat_session(db, session_id, message, detected_language, horizon, risk_profile)
    persist_chat_message(db, session, "user", message, detected_language)

    assets = relevant_assets(db, message, tickers)
    opportunities = opportunity_radar(db, limit=24)
    narrative = market_narrative(db)
    community = community_sentiment(db)
    sentiment = market_sentiment(db, hours=48)
    memory_hits = BlumTrainingMemoryService().semantic_memory(db, message, limit=6)
    semantic_hits = SemanticService().search(db, message, limit=8) if include_semantic_search else []
    asset_packets = [asset_context(db, asset) for asset in assets[:12]]
    candidates = rank_candidates(opportunities.get("rows", []), asset_packets)
    answer = build_answer(
        message=message,
        language=detected_language,
        intent=intent,
        candidates=candidates,
        asset_packets=asset_packets,
        narrative=narrative,
        community=community,
        sentiment=sentiment,
        memory_hits=memory_hits,
        horizon=horizon,
        risk_profile=risk_profile,
    )
    payload = {
        "generated_at": datetime.utcnow().isoformat(),
        "mode": "blum_multilingual_market_intelligence_chat",
        "session_id": session.session_key,
        "language": detected_language,
        "intent": intent,
        "question": message,
        "answer": answer,
        "candidate_opportunities": candidates[:10],
        "asset_context": asset_packets,
        "market_context": {
            "narrative": narrative,
            "community_sentiment": community,
            "market_sentiment": sentiment,
        },
        "semantic_evidence": semantic_hits,
        "training_memory": memory_hits,
        "rag_pipeline": rag_pipeline(detected_language, intent),
        "sources_used": sources_used(asset_packets, semantic_hits, memory_hits, narrative, sentiment),
        "context_coverage": context_coverage(asset_packets, semantic_hits, memory_hits),
        "suggested_followups": suggested_followups(candidates, assets, detected_language),
        "models_used": {
            "sentiment": "ProsusAI/finbert via stored sentiment rows, VADER baseline when available",
            "embeddings": "sentence-transformers semantic search over stored news and reasoning memory",
            "technical": "Deterministic OHLCV technical analysis engine",
            "fundamentals": "Stored SEC companyfacts snapshots when available",
            "reasoning": EvidenceBoundFallbackProvider().name,
            "future_llm_interfaces": "OpenAI-compatible API, local model, Hugging Face Inference, Ollama, vLLM, llama.cpp",
        },
        "governance": [
            "Observed data, inference and missing data are separated.",
            "No direct buy/sell instruction and no performance guarantee.",
            "Planning is hypothetical and evidence-bound.",
            "If evidence is missing, Blum lowers conviction instead of inventing data.",
        ],
        "disclaimer": LABELS[detected_language]["disclaimer"],
    }
    payload = json_safe(payload)
    persist_chat_message(db, session, "assistant", answer["composed_response"], detected_language, compact_chat_payload(payload))
    db.commit()
    return payload


def chat_context_overview(db: Session) -> dict:
    narrative = market_narrative(db)
    sentiment = market_sentiment(db, hours=48)
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "assets": int(db.scalar(select(func.count(Asset.id))) or 0),
        "signals": int(db.scalar(select(func.count(SignalSnapshot.id))) or 0),
        "news_articles": int(db.scalar(select(func.count(NewsArticle.id))) or 0),
        "dominant_narrative": narrative.get("dominant_theme", {}),
        "market_mood": narrative.get("market_mood"),
        "market_sentiment": sentiment,
        "starter_prompts": {
            "it": [
                "Analizza NVIDIA con approccio tecnico e fondamentale.",
                "Trova ETF AI interessanti con rischio definibile.",
                "Dove avrebbe senso monitorare un ingresso su Tesla?",
                "Quali narrative stanno accelerando?",
            ],
            "en": [
                "Find 5 stocks with strong momentum but not fully extended.",
                "Compare S&P 500 vs Nasdaq through Blum signals.",
                "Which setups have the best risk/reward evidence?",
                "What could the market be missing today?",
            ],
        },
        "disclaimer": DISCLAIMER,
    }


def chat_history(db: Session, limit: int = 80) -> list[dict]:
    rows = db.execute(
        select(ChatMessage, ChatSession)
        .join(ChatSession, ChatSession.id == ChatMessage.session_id)
        .order_by(desc(ChatMessage.created_at))
        .limit(limit)
    ).all()
    return [
        {
            "session_id": session.session_key,
            "role": message.role,
            "content": message.content,
            "language": message.language,
            "created_at": message.created_at.isoformat() if message.created_at else None,
        }
        for message, session in rows
    ]


def relevant_assets(db: Session, message: str, tickers: list[str] | None) -> list[Asset]:
    requested = {item.upper().strip() for item in tickers or [] if item.strip()}
    universe = db.scalars(select(Asset).where(Asset.is_active.is_(True))).all()
    text = f" {message.upper()} "
    requested.update(expand_market_terms(text))
    for asset in universe:
        ticker = asset.ticker.upper()
        if re.search(rf"(?<![A-Z0-9.]){re.escape(ticker)}(?![A-Z0-9.])", text):
            requested.add(ticker)
        elif asset.name and asset.name.upper() in text:
            requested.add(ticker)
    if requested:
        rows = db.scalars(select(Asset).where(Asset.ticker.in_(sorted(requested)))).all()
        return sorted(rows, key=lambda item: item.ticker)
    latest = db.execute(
        select(SignalSnapshot, Asset)
        .join(Asset, Asset.id == SignalSnapshot.asset_id)
        .order_by(desc(SignalSnapshot.blum_score), desc(SignalSnapshot.created_at))
        .limit(10)
    ).all()
    return [asset for _, asset in latest]


def asset_context(db: Session, asset: Asset) -> dict:
    latest_signal = db.scalar(
        select(SignalSnapshot)
        .where(SignalSnapshot.asset_id == asset.id)
        .order_by(desc(SignalSnapshot.created_at))
        .limit(1)
    )
    price_rows = db.scalars(
        select(PriceHistory)
        .where(PriceHistory.asset_id == asset.id)
        .order_by(desc(PriceHistory.date))
        .limit(320)
    ).all()
    frame = price_frame(price_rows)
    technical = TechnicalAnalysisEngine().analyze(frame, timeframe="6M") if not frame.empty else {"status": "missing_price_history"}
    fundamentals = fundamentals_for_asset(db, asset)
    latest_news = related_articles(db, asset.id, limit=8)
    memory = BlumTrainingMemoryService().asset_memory(db, asset)
    return {
        "ticker": asset.ticker,
        "name": asset.name,
        "asset_type": asset.asset_type,
        "sector": asset.sector,
        "industry": asset.industry,
        "country": asset.country,
        "exchange": asset.exchange,
        "currency": asset.currency,
        "market_snapshot": market_snapshot_for_asset(db, asset),
        "latest_signal": signal_payload(latest_signal, db) if latest_signal else None,
        "technical_analysis": technical,
        "fundamentals": fundamentals,
        "training_memory": memory,
        "history_depth": {
            "rows": len(price_rows),
            "latest_date": price_rows[0].date.isoformat() if price_rows else None,
            "oldest_sample_date": price_rows[-1].date.isoformat() if price_rows else None,
        },
        "recent_news": latest_news,
    }


def rank_candidates(rows: list[dict], asset_packets: list[dict]) -> list[dict]:
    by_ticker = {item["ticker"]: item for item in asset_packets}
    context_tickers = set(by_ticker)
    output = []
    for row in rows:
        ticker = row.get("ticker")
        if context_tickers and ticker not in context_tickers:
            continue
        packet = by_ticker.get(ticker, {})
        output.append(enrich_candidate(row, packet))
    if not output and asset_packets:
        for packet in asset_packets:
            signal = packet.get("latest_signal") or {}
            snapshot = packet.get("market_snapshot") or {}
            breakdown = signal.get("score_breakdown") or {}
            fallback = {
                "ticker": packet["ticker"],
                "name": packet["name"],
                "sector": packet["sector"],
                "asset_type": packet["asset_type"],
                "opportunity_score": signal.get("blum_score"),
                "risk_score": breakdown.get("risk_adjustment"),
                "momentum_score": breakdown.get("momentum_score"),
                "sentiment_score": breakdown.get("sentiment_score"),
                "news_score": breakdown.get("semantic_trend_score"),
                "classification": signal.get("classification", "Under observation"),
                "risk_level": signal.get("risk_level", "Unknown"),
                "why_today": signal.get("explanation", "Asset selected from the current evidence set."),
                "price": snapshot.get("price"),
                "data_status": snapshot.get("data_status"),
            }
            output.append(enrich_candidate(fallback, packet))
    return sorted(output, key=lambda item: safe_float(item.get("opportunity_score")), reverse=True)


def build_answer(
    *,
    message: str,
    language: str,
    intent: str,
    candidates: list[dict],
    asset_packets: list[dict],
    narrative: dict,
    community: dict,
    sentiment: dict,
    memory_hits: list[dict],
    horizon: str,
    risk_profile: str,
) -> dict:
    labels = LABELS[language]
    top = candidates[:5]
    dominant = narrative.get("dominant_theme", {}) if isinstance(narrative, dict) else {}
    market_mood = narrative.get("market_mood", "mixed") if isinstance(narrative, dict) else "mixed"
    thesis = executive_thesis(language, top, market_mood, dominant, intent)
    support = supporting_evidence(top, asset_packets, narrative, sentiment, memory_hits)
    contradictions = contradicting_evidence(top, asset_packets)
    missing = missing_data_points(asset_packets)
    scenarios = scenario_block(language, top)
    levels = levels_block(top)
    risks = risk_points(top, community, missing)
    technical = technical_block(top)
    fundamental = fundamental_block(top)
    sniper = market_sniper_mode(top, horizon, risk_profile, enabled=intent == "market_sniper")
    sections = [
        {"key": "summary", "title": labels["summary"], "bullets": [thesis]},
        {"key": "observed", "title": labels["observed"], "bullets": observed_data(top, narrative, sentiment)},
        {"key": "technical", "title": labels["technical"], "bullets": technical},
        {"key": "fundamental", "title": labels["fundamental"], "bullets": fundamental},
        {"key": "sentiment", "title": labels["sentiment"], "bullets": narrative_sentiment_points(narrative, sentiment, community)},
        {"key": "scenarios", "title": labels["scenarios"], "bullets": scenarios},
        {"key": "levels", "title": labels["levels"], "bullets": levels},
        {"key": "risks", "title": labels["risks"], "bullets": risks},
        {"key": "conclusion", "title": labels["conclusion"], "bullets": conclusion_points(language, top, risk_profile, horizon, intent)},
        {"key": "missing", "title": labels["missing"], "bullets": missing or [no_major_missing_data(language)]},
    ]
    composed = render_sections(sections, labels["disclaimer"])
    return {
        "composed_response": composed,
        "standard_sections": sections,
        "executive_view": thesis,
        "opportunity_lens": "Focus on statistically interesting setups, not deterministic predictions.",
        "supporting_evidence": support,
        "contradicting_evidence": contradictions,
        "bull_case": scenarios[0] if scenarios else "",
        "base_case": scenarios[1] if len(scenarios) > 1 else "",
        "bear_case": scenarios[2] if len(scenarios) > 2 else "",
        "risk_reward_view": risk_reward_view(top, risk_profile, horizon, language),
        "what_to_monitor": monitor_points(top, asset_packets, sentiment, community, language),
        "research_plan": planning_steps(top, risk_profile, horizon, language),
        "operation_plan": operation_planning_steps(top, horizon, language),
        "market_may_be_missing": market_may_be_missing(top, narrative, sentiment, language),
        "market_sniper_mode": sniper,
        "data_quality": data_quality(top, asset_packets, memory_hits),
        "answer_to_user": conclusion_points(language, top, risk_profile, horizon, intent)[0],
        "intellectual_honesty": intellectual_honesty(language),
    }


def upsert_chat_session(db: Session, session_id: str | None, message: str, language: str, horizon: str, risk_profile: str) -> ChatSession:
    session_key = session_id or uuid4().hex
    session = db.scalar(select(ChatSession).where(ChatSession.session_key == session_key).limit(1))
    if session is None:
        session = ChatSession(
            session_key=session_key,
            title=message[:180],
            language=language,
            horizon=horizon,
            risk_profile=risk_profile,
            metadata_payload={"created_by": "financial_chat"},
        )
        db.add(session)
        db.flush()
    else:
        session.language = language
        session.horizon = horizon
        session.risk_profile = risk_profile
        session.updated_at = datetime.utcnow()
    return session


def persist_chat_message(db: Session, session: ChatSession, role: str, content: str, language: str, response_payload: dict | None = None) -> None:
    db.add(ChatMessage(session_id=session.id, role=role, content=content, language=language, response_payload=json_safe(response_payload or {})))
    db.flush()


def compact_chat_payload(payload: dict) -> dict:
    answer = payload.get("answer") or {}
    return {
        "generated_at": payload.get("generated_at"),
        "mode": payload.get("mode"),
        "session_id": payload.get("session_id"),
        "language": payload.get("language"),
        "intent": payload.get("intent"),
        "question": payload.get("question"),
        "answer": {
            "executive_view": answer.get("executive_view"),
            "standard_sections": answer.get("standard_sections", []),
            "market_sniper_mode": answer.get("market_sniper_mode"),
            "data_quality": answer.get("data_quality"),
            "risk_reward_view": answer.get("risk_reward_view"),
            "what_to_monitor": answer.get("what_to_monitor", []),
        },
        "candidate_opportunities": payload.get("candidate_opportunities", [])[:10],
        "context_coverage": payload.get("context_coverage"),
        "sources_used": payload.get("sources_used"),
        "rag_pipeline": payload.get("rag_pipeline"),
        "models_used": payload.get("models_used"),
        "disclaimer": payload.get("disclaimer"),
    }


def json_safe(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def infer_intent(message: str, mode: str | None = None) -> str:
    if mode:
        return mode
    text = message.lower()
    if any(term in text for term in ["sniper", "ingresso", "entry", "risk/reward", "uscita", "target", "invalidazione", "breakout"]):
        return "market_sniper"
    if any(term in text for term in ["confronta", "compare", "vs", "versus"]):
        return "comparison"
    if any(term in text for term in ["trova", "find", "watchlist", "opportunit", "opportunity", "etf"]):
        return "opportunity_search"
    if any(term in text for term in ["narrative", "narrativa", "theme", "tema", "macro"]):
        return "narrative_analysis"
    return "asset_or_market_analysis"


def detect_language(message: str) -> str:
    text = f" {strip_accents(message.lower())} "
    scores = {code: sum(1 for hint in hints if hint in text) for code, hints in LANGUAGE_HINTS.items()}
    if any(char in message for char in "àèéìòù"):
        scores["it"] += 2
    if any(char in message for char in "äöüß"):
        scores["de"] += 2
    if any(char in message for char in "¿¡ñ"):
        scores["es"] += 2
    return max(scores, key=scores.get) if max(scores.values()) > 0 else "en"


def normalize_language(language: str | None) -> str | None:
    if not language or language == "auto":
        return None
    code = language.lower()[:2]
    return code if code in LABELS else None


def strip_accents(text: str) -> str:
    replacements = {"à": "a", "è": "e", "é": "e", "ì": "i", "ò": "o", "ù": "u", "á": "a", "í": "i", "ó": "o", "ú": "u"}
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def expand_market_terms(text: str) -> set[str]:
    tickers: set[str] = set()
    for term, mapped_tickers in MARKET_TERM_TICKERS.items():
        if term in text:
            tickers.update(mapped_tickers)
    return tickers


def related_articles(db: Session, asset_id: int, limit: int = 8) -> list[dict]:
    rows = db.execute(
        select(NewsArticle)
        .join(NewsAssetLink, NewsAssetLink.article_id == NewsArticle.id)
        .where(NewsAssetLink.asset_id == asset_id)
        .order_by(desc(NewsArticle.published_at), desc(NewsArticle.created_at))
        .limit(limit)
    ).scalars().all()
    return [
        {
            "id": row.id,
            "title": row.title,
            "source": row.source,
            "url": row.url,
            "published_at": row.published_at.isoformat() if row.published_at else None,
            "quality_score": row.quality_score,
            "themes": row.theme_tags.get("themes", []) if row.theme_tags else [],
        }
        for row in rows
    ]


def price_frame(rows: list[PriceHistory]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    records = [
        {"date": row.date, "open": row.open or row.close, "high": row.high or row.close, "low": row.low or row.close, "close": row.close, "volume": row.volume or 0}
        for row in rows
    ]
    return pd.DataFrame(records).sort_values("date")


def enrich_candidate(row: dict, packet: dict) -> dict:
    snapshot = packet.get("market_snapshot") or {}
    technical = packet.get("technical_analysis") or {}
    fundamentals = packet.get("fundamentals") or {}
    signal = packet.get("latest_signal") or {}
    memory = packet.get("training_memory") or {}
    technical_score = score_technical(technical)
    fundamental_score = score_fundamentals(fundamentals)
    sentiment_score = safe_float(row.get("sentiment_score") or (signal.get("score_breakdown") or {}).get("sentiment_score"))
    narrative_score = min(100, safe_float(row.get("news_score")) * 0.65 + len(packet.get("recent_news") or []) * 5)
    risk_score = safe_float(row.get("risk_score"))
    confidence = confidence_level(row, packet, technical_score, fundamental_score)
    enriched = {
        "ticker": row.get("ticker") or packet.get("ticker"),
        "name": row.get("name") or packet.get("name"),
        "sector": row.get("sector") or packet.get("sector"),
        "asset_type": row.get("asset_type") or packet.get("asset_type"),
        "price": snapshot.get("price") or row.get("last_price") or row.get("price"),
        "currency": snapshot.get("currency"),
        "price_date": snapshot.get("date"),
        "change_percent": snapshot.get("perf_1d") or row.get("change_percent"),
        "volume": snapshot.get("volume"),
        "opportunity_score": round(safe_float(row.get("opportunity_score")), 1),
        "technical_score": technical_score,
        "fundamental_score": fundamental_score,
        "sentiment_score": round(sentiment_score, 1),
        "narrative_score": round(narrative_score, 1),
        "momentum_score": round(safe_float(row.get("momentum_score")), 1),
        "risk_score": round(risk_score, 1),
        "risk_level": row.get("risk_level", "Unknown"),
        "confidence_level": confidence,
        "classification": row.get("classification", "Research Watch"),
        "why_today": row.get("why_today", "Asset selected from current Blum evidence."),
        "data_status": snapshot.get("data_status") or row.get("data_status"),
        "technical": technical,
        "fundamentals": fundamentals,
        "memory": memory,
        "recent_news": packet.get("recent_news", []),
    }
    enriched["sniper_setup"] = build_sniper_setup(enriched)
    return enriched


def score_technical(technical: dict) -> float:
    if technical.get("status") != "ready":
        return 0.0
    score = 45.0
    if technical.get("trend_direction") in {"uptrend", "uptrend_attempt"}:
        score += 18
    if (technical.get("moving_averages") or {}).get("alignment") in {"bullish_stack", "constructive"}:
        score += 12
    score += min(15, safe_float(technical.get("trend_strength_score")) * 0.15)
    score += min(10, safe_float(technical.get("breakout_probability")) * 0.10)
    if (technical.get("momentum") or {}).get("state") == "extended_positive":
        score -= 8
    return round(max(0, min(100, score)), 1)


def score_fundamentals(fundamentals: dict) -> float:
    if fundamentals.get("status") != "ready":
        return 0.0
    metrics = fundamentals.get("metrics") or {}
    score = safe_float(fundamentals.get("quality_score")) * 0.6
    if metrics.get("revenue"):
        score += 12
    if metrics.get("net_income"):
        score += 10
    if metrics.get("operating_cash_flow"):
        score += 8
    if metrics.get("liabilities") and metrics.get("assets"):
        try:
            debt_ratio = safe_float(metrics["liabilities"].get("value")) / max(1, safe_float(metrics["assets"].get("value")))
            if debt_ratio < 0.7:
                score += 8
        except Exception:
            pass
    return round(max(0, min(100, score)), 1)


def confidence_level(row: dict, packet: dict, technical_score: float, fundamental_score: float) -> str:
    points = 0
    if packet.get("market_snapshot", {}).get("data_status") == "ready":
        points += 1
    if technical_score >= 55:
        points += 1
    if fundamental_score >= 45:
        points += 1
    if packet.get("recent_news"):
        points += 1
    if packet.get("training_memory", {}).get("status") == "ready":
        points += 1
    if safe_float(row.get("opportunity_score")) >= 75:
        points += 1
    if points >= 5:
        return "High"
    if points >= 3:
        return "Medium"
    return "Low"


def build_sniper_setup(candidate: dict) -> dict:
    levels = (candidate.get("technical") or {}).get("levels") or {}
    last = candidate.get("price")
    breakout = levels.get("breakout_level")
    invalidation = levels.get("invalidation_level") or levels.get("breakdown_level")
    target = None
    if breakout and last:
        target = round(float(breakout) + max(0.01, float(breakout) - float(invalidation or last)), 2)
    return {
        "setup_type": candidate.get("classification", "Selective monitoring setup"),
        "entry_zone_informational": price_zone(last, breakout),
        "confirmation": "Close above relevant level with relative volume expansion and narrative confirmation.",
        "invalidation": invalidation,
        "target_zone_informational": target,
        "timeframe": "short/medium term",
        "momentum_condition": (candidate.get("technical") or {}).get("momentum", {}).get("state"),
        "volume_confirmation": (candidate.get("technical") or {}).get("volume", {}).get("relative_volume"),
        "risk_reward_estimated": (candidate.get("technical") or {}).get("risk_reward_estimate"),
        "confidence": candidate.get("confidence_level"),
        "why_now": candidate.get("why_today"),
        "what_could_go_wrong": "Failed breakout, weak volume confirmation, stale data, broader market risk-off or negative catalyst.",
    }


def price_zone(last, breakout) -> str:
    reference = safe_float(breakout or last)
    if reference <= 0:
        return "Not available because price evidence is missing."
    return f"{reference * 0.99:.2f}-{reference * 1.01:.2f}"


def executive_thesis(language: str, top: list[dict], market_mood: str, dominant: dict, intent: str) -> str:
    tickers = ", ".join(item.get("ticker", "") for item in top[:5] if item.get("ticker")) or "no high-quality candidate yet"
    theme = dominant.get("theme", "no dominant narrative")
    if language == "it":
        return f"BLUM inquadra la domanda in un regime {market_mood}: la narrativa dominante e {theme}. La coda da analizzare ora e {tickers}, ma la convinzione dipende da prezzo, volume, news, fondamentali e memoria storica."
    if language == "de":
        return f"BLUM betrachtet die Frage in einem {market_mood} Marktregime. Die dominante Narrative ist {theme}. Die aktuelle Research-Queue ist {tickers}, mit Fokus auf Preis, Volumen, News, Fundamentaldaten und historischer Memory."
    if language == "fr":
        return f"BLUM cadre la question dans un regime de marche {market_mood}. La narrative dominante est {theme}. La file de recherche est {tickers}, avec validation par prix, volumes, news, fondamentaux et memoire historique."
    if language == "es":
        return f"BLUM encuadra la pregunta en un regimen de mercado {market_mood}. La narrativa dominante es {theme}. La cola de investigacion es {tickers}, validada por precio, volumen, noticias, fundamentales y memoria historica."
    return f"BLUM frames this as a {market_mood} market research problem. The dominant narrative is {theme}. The current research queue is {tickers}, with conviction controlled by price, volume, news, fundamentals and historical memory."


def supporting_evidence(top: list[dict], asset_packets: list[dict], narrative: dict, sentiment: dict, memory_hits: list[dict]) -> list[str]:
    rows = []
    for item in top[:6]:
        rows.append(
            f"{item.get('ticker')}: Opportunity {item.get('opportunity_score')}/100, Technical {item.get('technical_score')}/100, Momentum {item.get('momentum_score')}/100, Sentiment {item.get('sentiment_score')}/100, Confidence {item.get('confidence_level')}."
        )
    if narrative.get("dominant_theme"):
        rows.append(f"Dominant narrative: {narrative['dominant_theme'].get('theme')} with {narrative['dominant_theme'].get('headline_count', 0)} linked headlines.")
    if sentiment.get("article_count", 0):
        rows.append(f"Market sentiment window contains {sentiment.get('article_count')} articles.")
    if memory_hits:
        rows.append(f"Reasoning memory retrieved {len(memory_hits)} historical Blum memory records relevant to the query.")
    return rows or ["No strong evidence stack is available yet."]


def contradicting_evidence(top: list[dict], asset_packets: list[dict]) -> list[str]:
    rows = []
    for item in top[:6]:
        if item.get("data_status") != "ready":
            rows.append(f"{item.get('ticker')}: price evidence status is {item.get('data_status')}; confidence must stay low.")
        if item.get("risk_level") in {"High", "Very High"} or safe_float(item.get("risk_score")) > 70:
            rows.append(f"{item.get('ticker')}: risk score is elevated and can invalidate an otherwise attractive setup.")
        if item.get("fundamental_score") == 0:
            rows.append(f"{item.get('ticker')}: no complete stored fundamental snapshot is available.")
        if item.get("technical_score") == 0:
            rows.append(f"{item.get('ticker')}: insufficient stored OHLCV for professional technical analysis.")
    return rows or ["No severe contradiction dominates the retrieved evidence, but that does not imply certainty."]


def observed_data(top: list[dict], narrative: dict, sentiment: dict) -> list[str]:
    rows = []
    for item in top[:5]:
        rows.append(f"{item.get('ticker')}: price {format_price(item.get('price'), item.get('currency'))}, 1D {item.get('change_percent')}, data {item.get('data_status')}, latest price date {item.get('price_date')}.")
    rows.append(f"Market mood: {narrative.get('market_mood', 'unknown')}; news count: {sentiment.get('article_count', 0)}.")
    return rows


def technical_block(top: list[dict]) -> list[str]:
    rows = []
    for item in top[:4]:
        tech = item.get("technical") or {}
        rows.append(
            f"{item.get('ticker')}: trend {tech.get('trend_direction', 'not available')}, RSI {(tech.get('technical_indicators') or {}).get('rsi')}, MACD hist {(tech.get('technical_indicators') or {}).get('macd_hist')}, breakout probability {tech.get('breakout_probability')}."
        )
    return rows or ["No technical evidence is available yet."]


def fundamental_block(top: list[dict]) -> list[str]:
    rows = []
    for item in top[:4]:
        fundamentals = item.get("fundamentals") or {}
        metrics = fundamentals.get("metrics") or {}
        rows.append(
            f"{item.get('ticker')}: fundamental status {fundamentals.get('status', 'missing')}, quality {fundamentals.get('quality_score', 0)}/100, revenue {'available' if metrics.get('revenue') else 'missing'}, net income {'available' if metrics.get('net_income') else 'missing'}, cash flow {'available' if metrics.get('operating_cash_flow') else 'missing'}."
        )
    return rows or ["No stored fundamental snapshot is available for the selected assets."]


def narrative_sentiment_points(narrative: dict, sentiment: dict, community: dict) -> list[str]:
    dominant = narrative.get("dominant_theme", {})
    rows = [
        f"Dominant narrative: {dominant.get('theme', 'not established')} | lifecycle {dominant.get('lifecycle', 'unknown')} | saturation {dominant.get('saturation', 'unknown')}.",
        f"Average market sentiment: {sentiment.get('average_sentiment', 0)} across {sentiment.get('article_count', 0)} articles.",
    ]
    for item in (community.get("most_discussed_assets") or [])[:3]:
        rows.append(f"{item.get('ticker')}: discussion count {item.get('discussion_count')}, hype-bubble risk {item.get('hype_bubble_risk')}.")
    return rows


def scenario_block(language: str, top: list[dict]) -> list[str]:
    tickers = ", ".join(item.get("ticker", "") for item in top[:3] if item.get("ticker")) or "the monitored set"
    if language == "it":
        return [
            f"Bull: {tickers} migliora se prezzo, volume relativo, narrativa e conferma settoriale restano allineati.",
            f"Base: {tickers} rimane una watchlist selettiva finche il quadro tecnico/news non diventa piu chiaro.",
            f"Bear: il setup si indebolisce se fallisce il breakout, cala la qualita delle news o aumenta la volatilita senza conferma.",
        ]
    return [
        f"Bull: {tickers} improves if price, relative volume, narrative and sector confirmation remain aligned.",
        f"Base: {tickers} stays a selective watchlist until technical/news evidence becomes clearer.",
        f"Bear: the setup weakens if breakout confirmation fails, news quality deteriorates or volatility expands without confirmation.",
    ]


def levels_block(top: list[dict]) -> list[str]:
    rows = []
    for item in top[:5]:
        levels = (item.get("technical") or {}).get("levels") or {}
        rows.append(
            f"{item.get('ticker')}: support {level_list(levels.get('support_levels'))}, resistance {level_list(levels.get('resistance_levels'))}, breakout {levels.get('breakout_level')}, invalidation {levels.get('invalidation_level')}."
        )
    return rows or ["No technical levels are available because price history is insufficient."]


def risk_points(top: list[dict], community: dict, missing: list[str]) -> list[str]:
    rows = [f"{item.get('ticker')}: risk {item.get('risk_level')} / score {item.get('risk_score')}; confidence {item.get('confidence_level')}." for item in top[:5]]
    if community.get("possible_hype_bubbles"):
        rows.append("Possible hype-bubble flags exist in community/news intensity and require extra skepticism.")
    rows.extend(missing[:4])
    return rows or ["Main risk: insufficient evidence to form a strong thesis."]


def conclusion_points(language: str, top: list[dict], risk_profile: str, horizon: str, intent: str) -> list[str]:
    fallback = "nessun candidato ad alta qualita" if language == "it" else "no high-quality candidate"
    tickers = ", ".join(item.get("ticker", "") for item in top[:3] if item.get("ticker")) or fallback
    if language == "it":
        return [f"Per profilo {risk_profile} e orizzonte {horizon}, BLUM tratterebbe {tickers} come coda di ricerca, non come ordine operativo. La priorita e confermare volume, livelli tecnici, narrativa e rischio prima di aumentare convinzione."]
    return [f"For a {risk_profile} profile and {horizon} horizon, BLUM treats {tickers} as a research queue, not an execution order. The priority is to confirm volume, technical levels, narrative and risk before increasing conviction."]


def planning_steps(top: list[dict], risk_profile: str, horizon: str, language: str) -> list[str]:
    if not top:
        return ["Wait for sufficient price, news and sentiment evidence before forming a high-conviction thesis."]
    tickers = ", ".join(item.get("ticker", "n/a") for item in top[:3])
    if language == "it":
        return [
            f"Costruire una watch queue su {tickers} per orizzonte {horizon}.",
            "Separare fatti osservati, ipotesi causali, contraddizioni e condizioni di invalidazione.",
            "Richiedere almeno due conferme indipendenti: prezzo/volume, ETF settoriale, sentiment/news o memoria storica.",
            f"Usare profilo {risk_profile}: ridurre convinzione quando volatilita, dati mancanti o narrativa affollata aumentano.",
        ]
    return [
        f"Build a watch queue around {tickers} for a {horizon} horizon.",
        "Separate observed facts, causal hypotheses, contradictions and invalidation conditions.",
        "Require at least two independent confirmations: price/volume, sector ETF, sentiment/news or historical memory.",
        f"Use a {risk_profile} risk frame and reduce conviction when volatility, missing data or narrative crowding rises.",
    ]


def operation_planning_steps(top: list[dict], horizon: str, language: str) -> list[str]:
    if not top:
        return ["No operation plan is generated because retrieved evidence is insufficient."]
    first = top[0]
    setup = first.get("sniper_setup") or {}
    if language == "it":
        return [
            f"Setup informativo: {first.get('ticker')} | zona da monitorare {setup.get('entry_zone_informational')}.",
            f"Conferma: {setup.get('confirmation')}",
            f"Invalidazione tecnica: {setup.get('invalidation')}",
            f"Target zone informativa: {setup.get('target_zone_informational')}",
            f"Review: rivalutare la tesi ogni giorno per orizzonte {horizon}.",
        ]
    return [
        f"Informational setup: {first.get('ticker')} | monitored zone {setup.get('entry_zone_informational')}.",
        f"Confirmation: {setup.get('confirmation')}",
        f"Technical invalidation: {setup.get('invalidation')}",
        f"Informational target zone: {setup.get('target_zone_informational')}",
        f"Review: re-check the thesis daily for {horizon}.",
    ]


def market_may_be_missing(top: list[dict], narrative: dict, sentiment: dict, language: str) -> list[str]:
    dominant = narrative.get("dominant_theme", {}) if isinstance(narrative, dict) else {}
    if language == "it":
        points = [
            f"Il mercato potrebbe sovrappesare il volume headline su {dominant.get('theme', 'narrativa dominante')} e sottopesare la qualita delle evidenze.",
            "Segnali deboli ma coerenti diventano interessanti quando prezzo, sentiment e conferma settoriale si allineano prima del consenso.",
        ]
    else:
        points = [
            f"The market may be overweighting headline volume around {dominant.get('theme', 'the dominant narrative')} while underweighting evidence quality.",
            "Weak but coherent signals matter when price, sentiment and sector confirmation align before broad consensus.",
        ]
    if any(item.get("data_status") != "ready" for item in top[:5]):
        points.append("Missing OHLCV evidence is itself a risk signal and should cap confidence.")
    if sentiment.get("article_count", 0) and abs(float(sentiment.get("average_sentiment", 0))) < 0.05:
        points.append("Market-wide sentiment is close to neutral, so dispersion between assets may be more useful than the headline mood.")
    return points


def market_sniper_mode(top: list[dict], horizon: str, risk_profile: str, enabled: bool) -> dict:
    candidate = top[0] if top else {}
    setup = candidate.get("sniper_setup") or {}
    return {
        "enabled": enabled,
        "selection_policy": "Extremely selective informational setup detection. It does not generate orders.",
        "asset": candidate.get("ticker"),
        "setup_type": setup.get("setup_type"),
        "entry_zone_informational": setup.get("entry_zone_informational"),
        "invalidation": setup.get("invalidation"),
        "target_zone_informational": setup.get("target_zone_informational"),
        "timeframe": horizon,
        "risk_profile": risk_profile,
        "momentum_condition": setup.get("momentum_condition"),
        "volume_confirmation": setup.get("volume_confirmation"),
        "risk_reward_estimated": setup.get("risk_reward_estimated"),
        "confidence": setup.get("confidence"),
        "why_now": setup.get("why_now"),
        "what_could_go_wrong": setup.get("what_could_go_wrong"),
    }


def risk_reward_view(top: list[dict], risk_profile: str, horizon: str, language: str) -> str:
    if not top:
        return "No candidate has enough evidence for a risk/reward view."
    high_risk = [item["ticker"] for item in top if safe_float(item.get("risk_score")) > 70]
    if language == "it":
        return f"Per profilo {risk_profile} e orizzonte {horizon}, dare priorita a score elevati con rischio definibile. Nomi da validare con cautela: {', '.join(high_risk[:5]) or 'nessuno nel set top'}."
    return f"For a {risk_profile} profile and {horizon} horizon, prioritize high scores with definable risk. Names requiring extra validation: {', '.join(high_risk[:5]) or 'none in the top set'}."


def monitor_points(top: list[dict], asset_packets: list[dict], sentiment: dict, community: dict, language: str) -> list[str]:
    points = [
        "Confirm that news intensity is rising with source quality, not only headline count.",
        "Check if sentiment confirms price action instead of only reacting to it.",
        "Require sector or ETF confirmation for single-name signals.",
        "Watch volatility expansion and drawdown risk after the signal.",
    ]
    if sentiment.get("article_count", 0) == 0:
        points.append("Market-wide sentiment evidence is currently thin.")
    for item in top[:3]:
        if item.get("data_status") != "ready":
            points.append(f"{item.get('ticker')}: wait for market data readiness before treating analysis as complete.")
    return points


def missing_data_points(asset_packets: list[dict]) -> list[str]:
    rows = []
    for packet in asset_packets[:8]:
        ticker = packet["ticker"]
        if packet.get("market_snapshot", {}).get("data_status") != "ready":
            rows.append(f"{ticker}: updated price/OHLCV evidence is missing or stale.")
        if packet.get("fundamentals", {}).get("status") != "ready":
            rows.append(f"{ticker}: complete stored fundamental evidence is not available.")
        if not packet.get("recent_news"):
            rows.append(f"{ticker}: no recent linked news is stored.")
        if packet.get("training_memory", {}).get("status") != "ready":
            rows.append(f"{ticker}: evaluated Blum memory sample is still limited.")
    return rows


def data_quality(top: list[dict], asset_packets: list[dict], memory_hits: list[dict]) -> dict:
    checks = []
    for packet in asset_packets:
        checks.extend(
            [
                packet.get("market_snapshot", {}).get("data_status") == "ready",
                packet.get("technical_analysis", {}).get("status") == "ready",
                packet.get("fundamentals", {}).get("status") == "ready",
                bool(packet.get("recent_news")),
                packet.get("training_memory", {}).get("status") == "ready",
            ]
        )
    score = round(sum(1 for item in checks if item) / max(1, len(checks)) * 100, 1)
    return {
        "score": score,
        "label": "High" if score >= 75 else "Medium" if score >= 45 else "Low",
        "asset_contexts": len(asset_packets),
        "memory_hits": len(memory_hits),
        "policy": "Missing data is surfaced and lowers conviction. No synthetic market data is created.",
    }


def rag_pipeline(language: str, intent: str) -> list[dict]:
    return [
        {"step": 1, "name": "language_detection", "result": language},
        {"step": 2, "name": "intent_detection", "result": intent},
        {"step": 3, "name": "entity_extraction", "result": "ticker, company, ETF, sector and market term detection"},
        {"step": 4, "name": "internal_context_retrieval", "result": "assets, signals, prices, technicals, fundamentals, news, narratives, memory"},
        {"step": 5, "name": "semantic_retrieval", "result": "news embeddings and Blum reasoning memory"},
        {"step": 6, "name": "anti_hallucination_validation", "result": "missing data marked explicitly"},
        {"step": 7, "name": "structured_answer", "result": "scenario, levels, risks, confidence and disclaimer"},
    ]


def sources_used(asset_packets: list[dict], semantic_hits: list[dict], memory_hits: list[dict], narrative: dict, sentiment: dict) -> list[dict]:
    sources = [
        {"name": "Blum asset universe", "type": "internal_db", "coverage": len(asset_packets)},
        {"name": "Stored OHLCV market snapshots", "type": "internal_db", "coverage": sum(1 for item in asset_packets if item.get("market_snapshot", {}).get("data_status") == "ready")},
        {"name": "Deterministic technical engine", "type": "calculated", "coverage": sum(1 for item in asset_packets if item.get("technical_analysis", {}).get("status") == "ready")},
        {"name": "SEC companyfacts fundamentals", "type": "public_filings", "coverage": sum(1 for item in asset_packets if item.get("fundamentals", {}).get("status") == "ready")},
        {"name": "FinBERT/VADER sentiment records", "type": "ai_sentiment", "coverage": sentiment.get("article_count", 0)},
        {"name": "Narrative intelligence", "type": "semantic_news", "coverage": len(narrative.get("emerging_subthemes", []) or [])},
        {"name": "Semantic news search", "type": "embeddings", "coverage": len(semantic_hits)},
        {"name": "Blum training memory", "type": "reasoning_memory", "coverage": len(memory_hits)},
    ]
    return sources


def context_coverage(asset_packets: list[dict], semantic_hits: list[dict], memory_hits: list[dict]) -> dict:
    return {
        "assets_detected": len(asset_packets),
        "assets_with_price": sum(1 for item in asset_packets if item.get("market_snapshot", {}).get("data_status") == "ready"),
        "assets_with_technical_analysis": sum(1 for item in asset_packets if item.get("technical_analysis", {}).get("status") == "ready"),
        "assets_with_fundamentals": sum(1 for item in asset_packets if item.get("fundamentals", {}).get("status") == "ready"),
        "assets_with_news": sum(1 for item in asset_packets if item.get("recent_news")),
        "semantic_hits": len(semantic_hits),
        "memory_hits": len(memory_hits),
    }


def suggested_followups(candidates: list[dict], assets: list[Asset], language: str) -> list[str]:
    tickers = [item.get("ticker") for item in candidates[:3] if item.get("ticker")]
    if language == "it":
        if tickers:
            return [
                f"Costruisci tesi bull/base/bear per {tickers[0]}.",
                f"Confronta rischio/rendimento tra {' e '.join(tickers[:2])}.",
                "Quale evidenza contraria invaliderebbe il setup migliore?",
                "Qual e il segnale europeo piu forte oggi?",
            ]
        return ["Cosa dovrei monitorare oggi?", "Dove il sentiment diverge dal prezzo?"]
    if tickers:
        return [
            f"Build a bull/base/bear thesis for {tickers[0]}.",
            f"Compare risk-adjusted opportunity between {' and '.join(tickers[:2])}.",
            "Which contradicting evidence would invalidate the top setup?",
            "What is the strongest European market signal today?",
        ]
    return ["What should I monitor today?", "Where is sentiment diverging from price?"]


def render_sections(sections: list[dict], disclaimer: str) -> str:
    lines = []
    for section in sections:
        lines.append(f"{section['title']}:")
        for bullet in section.get("bullets", []):
            lines.append(f"- {bullet}")
        lines.append("")
    lines.append(disclaimer)
    return "\n".join(lines).strip()


def no_major_missing_data(language: str) -> str:
    return "No major missing field in the retrieved context." if language == "en" else "Nessun dato essenziale mancante nel contesto recuperato."


def intellectual_honesty(language: str) -> str:
    if language == "it":
        return "Se dati, news o fondamentali sono incompleti, BLUM lo dichiara e riduce la convinzione invece di forzare una risposta."
    return "If data, news or fundamentals are incomplete, BLUM states it and reduces conviction instead of forcing a conclusion."


def format_price(price, currency) -> str:
    value = safe_float(price)
    if value <= 0:
        return "not available"
    return f"{value:.2f} {currency or ''}".strip()


def level_list(levels) -> str:
    if not levels:
        return "n/a"
    values = []
    for item in levels[:2]:
        values.append(str(item.get("level") if isinstance(item, dict) else item))
    return ", ".join(values)


def safe_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
