from __future__ import annotations

from dataclasses import dataclass
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
from app.services.learning_loop import LearningDashboardService
from app.services.market_data import market_snapshot_for_asset
from app.services.semantic import SemanticService
from app.services.strategic_intelligence import community_sentiment, market_narrative, opportunity_radar
from app.services.dashboard import signal_payload
from app.services.technical_analysis_engine import TechnicalAnalysisEngine


DISCLAIMER = "Analisi informativa, non consulenza finanziaria. I livelli sono tecnici e probabilistici, non garanzie."
EN_DISCLAIMER = "Informational research only, not financial advice. Technical levels are probabilistic, not guarantees."

PRIVATE_COMPANIES = {
    "SPACEX": {
        "name": "SpaceX",
        "theme": "Space Economy",
        "proxies": ["RKLB", "ASTS", "IRDM", "ARKX", "UFO"],
        "note": "private launch, satellite and space infrastructure company",
    },
    "OPENAI": {
        "name": "OpenAI",
        "theme": "Artificial Intelligence",
        "proxies": ["MSFT", "NVDA", "GOOGL", "META", "AIQ", "BOTZ"],
        "note": "private AI company with no listed common equity",
    },
    "ANTHROPIC": {
        "name": "Anthropic",
        "theme": "Artificial Intelligence",
        "proxies": ["AMZN", "GOOGL", "NVDA", "AIQ", "BOTZ"],
        "note": "private AI company with no listed common equity",
    },
    "XAI": {
        "name": "xAI",
        "theme": "Artificial Intelligence",
        "proxies": ["TSLA", "NVDA", "AIQ", "BOTZ"],
        "note": "private AI company with no listed common equity",
    },
    "BYTEDANCE": {
        "name": "ByteDance",
        "theme": "Social Media / AI",
        "proxies": ["META", "GOOGL", "TCEHY"],
        "note": "private company with no direct public ticker in the BLUM universe",
    },
    "STRIPE": {
        "name": "Stripe",
        "theme": "Fintech",
        "proxies": ["ADYEN.AS", "PYPL", "SQ"],
        "note": "private fintech company with no direct public ticker",
    },
    "REVOLUT": {
        "name": "Revolut",
        "theme": "Fintech",
        "proxies": ["NU", "PYPL", "SQ"],
        "note": "private fintech company with no direct public ticker",
    },
    "SHEIN": {
        "name": "Shein",
        "theme": "E-commerce / Fashion",
        "proxies": ["AMZN", "BABA", "ZAL.DE"],
        "note": "private company with no direct public ticker",
    },
}

AMBIGUOUS_ENTITIES = {
    "SHELL": ["SHEL", "Shell plc can refer to different listings or legacy symbols."],
    "TOTAL": ["TTE", "TotalEnergies is usually TTE, but the word total is ambiguous in natural language."],
    "ARM": ["ARM", "ARM can be a ticker or a common word; BLUM needs confirmation when the query is unclear."],
}

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

COMPANY_TERM_TICKERS = {
    "NVIDIA": ["NVDA"],
    "TESLA": ["TSLA"],
    "MICROSOFT": ["MSFT"],
    "APPLE": ["AAPL"],
    "AMAZON": ["AMZN"],
    "ALPHABET": ["GOOGL"],
    "GOOGLE": ["GOOGL"],
    "META": ["META"],
    "FACEBOOK": ["META"],
    "BROADCOM": ["AVGO"],
    "ADVANCED MICRO DEVICES": ["AMD"],
    "AMD": ["AMD"],
    "APPLIED MATERIALS": ["AMAT"],
    "LAM RESEARCH": ["LRCX"],
    "ASML": ["ASML"],
    "INTEL": ["INTC"],
    "NETFLIX": ["NFLX"],
    "PALANTIR": ["PLTR"],
    "ORACLE": ["ORCL"],
    "SALESFORCE": ["CRM"],
    "ADOBE": ["ADBE"],
    "JPMORGAN": ["JPM"],
    "JP MORGAN": ["JPM"],
    "GOLDMAN": ["GS"],
    "ELI LILLY": ["LLY"],
    "NOVO NORDISK": ["NVO"],
    "EXXON": ["XOM"],
    "CHEVRON": ["CVX"],
    "CATERPILLAR": ["CAT"],
    "SIEMENS": ["SIE.DE"],
    "SAP": ["SAP"],
    "RHEINMETALL": ["RHM.DE"],
    "AIRBUS": ["AIR.PA"],
    "LVMH": ["MC.PA"],
    "LOUIS VUITTON": ["MC.PA"],
    "ENEL": ["ENEL.MI"],
    "ENI": ["ENI.MI"],
    "UNICREDIT": ["UCG.MI"],
    "INTESA": ["ISP.MI"],
    "FERRARI": ["RACE.MI"],
    "LEONARDO": ["LDO.MI"],
}

LANGUAGE_HINTS = {
    "it": [" cosa ", " quali ", " analizza ", " analisi ", " trova ", " comprare", " ingresso", " rischio", " titolo", " azione", " uscita", " monitorare", " tecnica", " fondamentale", " confronto", " spiegami"],
    "en": [" what ", " which ", " analyze ", " analysis ", " find ", " entry", " risk", " stock", " watch", " compare", " setup", " technical", " fundamental"],
    "de": [" was ", " welche ", " analysiere ", " analyse ", " risiko", " aktie", " einstieg", " beobachten", " vergleich"],
    "fr": [" que ", " quels ", " analyse ", " risque", " action", " entree", " surveiller", " comparer"],
    "es": [" que ", " cuales ", " analiza ", " analisis ", " riesgo", " accion", " entrada", " vigilar", " comparar"],
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


@dataclass
class ChatEntity:
    raw: str
    normalized: str
    entity_type: str
    resolved_ticker: str | None = None
    confidence: float = 0.0
    reason: str = ""
    proxies: list[str] | None = None

    def to_dict(self) -> dict:
        return {
            "raw": self.raw,
            "normalized": self.normalized,
            "entity_type": self.entity_type,
            "resolved_ticker": self.resolved_ticker,
            "confidence": self.confidence,
            "reason": self.reason,
            "proxies": self.proxies or [],
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

    entities = resolve_entities(db, message, tickers)
    intent = refine_intent_with_entities(intent, entities)
    blocked_answer = blocked_entity_response(message, detected_language, intent, entities, mode)
    if blocked_answer:
        payload = minimal_chat_payload(
            session=session,
            message=message,
            language=detected_language,
            intent=intent,
            answer=blocked_answer,
            entities=entities,
            mode=mode,
        )
        persist_chat_message(db, session, "assistant", blocked_answer["composed_response"], detected_language, compact_chat_payload(payload))
        db.commit()
        return payload

    assets = relevant_assets(db, message, tickers, entities=entities, intent=intent)
    opportunities = opportunity_radar(db, limit=24)
    narrative = market_narrative(db)
    community = community_sentiment(db)
    sentiment = market_sentiment(db, hours=48)
    memory_hits = BlumTrainingMemoryService().semantic_memory(db, message, limit=6)
    learning_loop_context = LearningDashboardService().chat_memory(db, message, assets[:5], limit=8)
    semantic_hits = SemanticService().search(db, message, limit=8) if include_semantic_search else []
    asset_packets = dedupe_context_blocks([asset_context(db, asset) for asset in assets[:12]])
    validation = validate_asset_contexts(intent, entities, asset_packets, detected_language)
    if validation.get("blocked"):
        answer = build_error_response(detected_language, validation["message"], validation.get("suggestions", []))
        payload = minimal_chat_payload(
            session=session,
            message=message,
            language=detected_language,
            intent=intent,
            answer=answer,
            entities=entities,
            mode=mode,
            validation=validation,
        )
        persist_chat_message(db, session, "assistant", answer["composed_response"], detected_language, compact_chat_payload(payload))
        db.commit()
        return payload

    candidates = dedupe_context_blocks(rank_candidates(opportunities.get("rows", []), asset_packets))
    answer = build_answer(
        message=message,
        language=detected_language,
        intent=intent,
        entities=entities,
        validation=validation,
        candidates=candidates,
        asset_packets=asset_packets,
        narrative=narrative,
        community=community,
        sentiment=sentiment,
        memory_hits=memory_hits,
        learning_loop_context=learning_loop_context,
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
        "entity_resolution": [entity.to_dict() for entity in entities],
        "candidate_opportunities": candidates[:10],
        "asset_context": asset_packets,
        "market_context": {
            "narrative": narrative,
            "community_sentiment": community,
            "market_sentiment": sentiment,
        },
        "semantic_evidence": semantic_hits,
        "training_memory": memory_hits,
        "learning_loop_context": learning_loop_context,
        "rag_pipeline": rag_pipeline(detected_language, intent),
        "sources_used": sources_used(asset_packets, semantic_hits, memory_hits, narrative, sentiment, learning_loop_context),
        "context_coverage": context_coverage(asset_packets, semantic_hits, memory_hits, learning_loop_context),
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
    quality = quality_gate(payload, entities, validation)
    if mode in {"debug", "developer", "chatbot_debug_feedback"}:
        payload["diagnostics"] = quality
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


def resolve_entities(db: Session, message: str, tickers: list[str] | None = None) -> list[ChatEntity]:
    text = f" {strip_accents(message.upper())} "
    universe = db.scalars(select(Asset).where(Asset.is_active.is_(True))).all()
    by_ticker = {asset.ticker.upper(): asset for asset in universe}
    entities: list[ChatEntity] = []

    for raw_ticker in tickers or []:
        ticker = raw_ticker.upper().strip()
        if not ticker:
            continue
        asset = by_ticker.get(ticker)
        if asset:
            entities.append(
                ChatEntity(
                    raw=raw_ticker,
                    normalized=asset.name,
                    entity_type=asset_kind(asset),
                    resolved_ticker=asset.ticker,
                    confidence=0.99,
                    reason="explicit ticker supplied by the client and found in BLUM universe",
                )
            )
        else:
            entities.append(ChatEntity(raw=raw_ticker, normalized=ticker, entity_type="unknown_asset", confidence=0.35, reason="explicit ticker was not found in BLUM universe"))

    for term, payload in PRIVATE_COMPANIES.items():
        if re.search(rf"(?<![A-Z0-9]){re.escape(term)}(?![A-Z0-9])", text):
            entities.append(
                ChatEntity(
                    raw=payload["name"],
                    normalized=payload["name"],
                    entity_type="private_company",
                    confidence=0.99,
                    reason=payload["note"],
                    proxies=payload.get("proxies", []),
                )
            )

    for term, detail in AMBIGUOUS_ENTITIES.items():
        if re.search(rf"(?<![A-Z0-9]){re.escape(term)}(?![A-Z0-9])", text):
            # If the exact ticker was already resolved, keep the public asset instead of asking again.
            if not any(entity.resolved_ticker == detail[0] for entity in entities):
                entities.append(ChatEntity(raw=term.title(), normalized=term.title(), entity_type="ambiguous_company", confidence=0.55, reason=detail[1], proxies=[detail[0]]))

    for term, mapped_tickers in COMPANY_TERM_TICKERS.items():
        if re.search(rf"(?<![A-Z0-9]){re.escape(term)}(?![A-Z0-9])", text):
            for ticker in mapped_tickers:
                asset = by_ticker.get(ticker.upper())
                if asset:
                    entities.append(
                        ChatEntity(
                            raw=term.title(),
                            normalized=asset.name,
                            entity_type=asset_kind(asset),
                            resolved_ticker=asset.ticker,
                            confidence=0.94,
                            reason="company name matched a known public asset in BLUM universe",
                        )
                    )

    for term, mapped_tickers in MARKET_TERM_TICKERS.items():
        if term in text:
            entities.append(ChatEntity(raw=term, normalized=term, entity_type="index" if term.startswith("^") else "general_market_topic", confidence=0.8, reason="market term matched", proxies=mapped_tickers))

    # Exact ticker recognition is useful, but we avoid one-letter symbols unless they were explicit.
    for ticker, asset in sorted(by_ticker.items(), key=lambda item: len(item[0]), reverse=True):
        if len(ticker.replace(".", "").replace("^", "")) < 2:
            continue
        pattern = rf"(?<![A-Z0-9.]){re.escape(ticker)}(?![A-Z0-9.])"
        if re.search(pattern, text):
            entities.append(
                ChatEntity(
                    raw=ticker,
                    normalized=asset.name,
                    entity_type=asset_kind(asset),
                    resolved_ticker=asset.ticker,
                    confidence=0.96,
                    reason="exact public ticker matched BLUM universe",
                )
            )

    for asset in universe:
        name = strip_accents((asset.name or "").upper())
        if len(name) >= 5 and name in text:
            entities.append(
                ChatEntity(
                    raw=asset.name,
                    normalized=asset.name,
                    entity_type=asset_kind(asset),
                    resolved_ticker=asset.ticker,
                    confidence=0.9,
                    reason="asset name matched BLUM universe",
                )
            )

    entities = dedupe_entities(entities)
    if not entities and looks_like_asset_request(message):
        candidate = extract_requested_asset_phrase(message)
        if candidate:
            entities.append(ChatEntity(raw=candidate, normalized=candidate, entity_type="unknown_asset", confidence=0.4, reason="asset-like request could not be matched to a public BLUM asset"))
    return entities


def asset_kind(asset: Asset) -> str:
    kind = (asset.asset_type or "").lower()
    if "etf" in kind:
        return "ETF"
    if "crypto" in kind:
        return "crypto"
    if asset.ticker.startswith("^"):
        return "index"
    return "public_stock"


def dedupe_entities(entities: list[ChatEntity]) -> list[ChatEntity]:
    result: list[ChatEntity] = []
    seen: set[tuple[str, str | None]] = set()
    for entity in entities:
        key = (entity.entity_type, entity.resolved_ticker or entity.normalized.upper())
        if key in seen:
            continue
        seen.add(key)
        result.append(entity)
    return result


def looks_like_asset_request(message: str) -> bool:
    text = strip_accents(message.lower())
    return any(
        term in text
        for term in [
            "analisi tecnica",
            "analisi fondamentale",
            "analizza",
            "analyze",
            "technical analysis",
            "fundamental analysis",
            "titolo",
            "stock",
            "azione",
            "ticker",
        ]
    )


def extract_requested_asset_phrase(message: str) -> str | None:
    cleaned = re.sub(r"[?!.]+$", "", message.strip())
    patterns = [
        r"(?:analisi tecnica|analisi fondamentale|analizza|analyze|technical analysis of|fundamental analysis of)\s+(?:di|of|for|su|on)?\s*([A-Za-z0-9 .&'-]{2,80})",
        r"(?:di|of|for|su|on)\s+([A-Za-z0-9 .&'-]{2,80})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def refine_intent_with_entities(intent: str, entities: list[ChatEntity]) -> str:
    if any(entity.entity_type == "private_company" for entity in entities):
        return "private_company_request"
    if any(entity.entity_type == "unknown_asset" for entity in entities):
        return "unknown_asset_request"
    if any(entity.entity_type == "ambiguous_company" for entity in entities):
        return "ambiguous_company_request"
    return intent


def blocked_entity_response(message: str, language: str, intent: str, entities: list[ChatEntity], mode: str | None = None) -> dict | None:
    private_entities = [entity for entity in entities if entity.entity_type == "private_company"]
    if private_entities:
        return build_private_company_response(language, private_entities[0], technical_requested=is_technical_request(message), fundamental_requested=is_fundamental_request(message))
    ambiguous = [entity for entity in entities if entity.entity_type == "ambiguous_company"]
    if ambiguous:
        return build_ambiguous_company_response(language, ambiguous[0])
    unknown = [entity for entity in entities if entity.entity_type == "unknown_asset"]
    if unknown:
        return build_unknown_asset_response(language, unknown[0])
    return None


def relevant_assets(db: Session, message: str, tickers: list[str] | None, entities: list[ChatEntity] | None = None, intent: str | None = None) -> list[Asset]:
    entities = entities or resolve_entities(db, message, tickers)
    requested = {item.upper().strip() for item in tickers or [] if item.strip()}
    requested.update(entity.resolved_ticker for entity in entities if entity.resolved_ticker)
    for entity in entities:
        if entity.entity_type in {"index", "general_market_topic"}:
            requested.update((entity.proxies or [])[:12])
    universe = db.scalars(select(Asset).where(Asset.is_active.is_(True))).all()
    text = f" {message.upper()} "
    if not requested and intent in {"market_summary", "opportunity_search", "narrative_analysis"}:
        requested.update(expand_market_terms(text))
        requested.update(expand_company_terms(text))
    if requested:
        rows = db.scalars(select(Asset).where(Asset.ticker.in_(sorted(requested)))).all()
        return dedupe_assets(sorted(rows, key=lambda item: item.ticker))
    if looks_like_asset_request(message):
        return []
    latest = db.execute(
        select(SignalSnapshot, Asset)
        .join(Asset, Asset.id == SignalSnapshot.asset_id)
        .order_by(desc(SignalSnapshot.blum_score), desc(SignalSnapshot.created_at))
        .limit(10)
    ).all()
    return dedupe_assets([asset for _, asset in latest])


def dedupe_assets(assets: list[Asset]) -> list[Asset]:
    output: list[Asset] = []
    seen: set[str] = set()
    for asset in assets:
        ticker = asset.ticker.upper()
        if ticker in seen:
            continue
        seen.add(ticker)
        output.append(asset)
    return output


def dedupe_context_blocks(blocks: list[dict]) -> list[dict]:
    output: list[dict] = []
    seen: set[str] = set()
    for block in blocks:
        ticker = str(block.get("ticker") or "").upper()
        key = ticker or str(block)
        if key in seen:
            continue
        seen.add(key)
        output.append(block)
    return output


def dedupe_response_sections(sections: list[dict]) -> list[dict]:
    output: list[dict] = []
    seen_sections: set[str] = set()
    for section in sections:
        key = str(section.get("key") or section.get("title") or "").lower()
        if key in seen_sections:
            continue
        seen_sections.add(key)
        bullets = dedupe_warnings([str(item) for item in section.get("bullets", []) if item])
        output.append({**section, "bullets": bullets})
    return output


def dedupe_warnings(rows: list[str | None]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not row:
            continue
        text = str(row).strip()
        if not text:
            continue
        key = re.sub(r"\s+", " ", text.lower())
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def validate_asset_contexts(intent: str, entities: list[ChatEntity], asset_packets: list[dict], language: str = "en") -> dict:
    tickers = {packet.get("ticker") for packet in asset_packets if packet.get("ticker")}
    requested_public = [entity for entity in entities if entity.resolved_ticker]
    mismatches = [entity for entity in requested_public if entity.resolved_ticker not in tickers]
    if mismatches:
        names = ", ".join(entity.raw for entity in mismatches)
        return {
            "blocked": True,
            "reason": "asset_mismatch",
            "message": (
                f"Validazione asset fallita per {names}: BLUM non ha recuperato lo stesso ticker pubblico richiesto."
                if language == "it"
                else f"Asset validation failed for {names}: BLUM did not retrieve the same public ticker that was requested."
            ),
            "suggestions": ["Usa il ticker esatto e riprova." if language == "it" else "Use the exact ticker and retry."],
        }
    if intent == "technical_analysis":
        missing = []
        for packet in asset_packets:
            tech = packet.get("technical_analysis") or {}
            snapshot = packet.get("market_snapshot") or {}
            if snapshot.get("data_status") != "ready" or tech.get("status") != "ready":
                missing.append(packet.get("ticker"))
        if missing:
            return {
                "blocked": True,
                "reason": "missing_ohlcv",
                "message": (
                    f"Non riesco a fare analisi tecnica affidabile per {', '.join(missing)}: manca una serie pubblica OHLCV validata."
                    if language == "it"
                    else f"I cannot run reliable technical analysis for {', '.join(missing)} because validated public OHLCV data is missing."
                ),
                "suggestions": [
                    "Posso provare prima ad aggiornare i dati pubblici o analizzare un proxy con storico disponibile."
                    if language == "it"
                    else "I can first try to refresh public data or analyze a proxy with available history."
                ],
            }
    if not asset_packets and any(entity.entity_type in {"public_stock", "ETF", "index", "crypto"} for entity in entities):
        return {
            "blocked": True,
            "reason": "no_context",
            "message": (
                "Non riesco a recuperare dati affidabili per l'asset richiesto in questo momento."
                if language == "it"
                else "I cannot retrieve reliable data for the requested asset right now."
            ),
            "suggestions": [
                "Posso spiegare quali dati servirebbero o provare con un proxy valido."
                if language == "it"
                else "I can explain which data is needed or try a valid proxy."
            ],
        }
    return {
        "blocked": False,
        "requested_tickers": sorted(ticker for ticker in tickers if ticker),
        "data_freshness": {packet.get("ticker"): (packet.get("history_depth") or {}).get("latest_date") for packet in asset_packets},
    }


def quality_gate(payload: dict, entities: list[ChatEntity], validation: dict) -> dict:
    answer = payload.get("answer") or {}
    sections = answer.get("standard_sections") or []
    tickers = [item.get("ticker") for item in payload.get("candidate_opportunities", []) if item.get("ticker")]
    duplicate_count = len(tickers) - len(set(tickers))
    checks = {
        "language_matches": bool(payload.get("language")),
        "entity_count": len(entities),
        "validation_blocked": bool(validation.get("blocked")),
        "duplicate_tickers": duplicate_count,
        "has_disclaimer": bool(payload.get("disclaimer")),
        "section_count": len(sections),
        "raw_json_exposed": answer.get("composed_response", "").strip().startswith("{"),
        "response_template_used": answer.get("response_style"),
    }
    return checks


def is_technical_request(message: str) -> bool:
    text = strip_accents(message.lower())
    return any(term in text for term in ["analisi tecnica", "technical analysis", "rsi", "macd", "support", "resisten", "breakout", "livelli"])


def is_fundamental_request(message: str) -> bool:
    text = strip_accents(message.lower())
    return any(term in text for term in ["analisi fondamentale", "fundamental analysis", "fondamental", "bilancio", "revenue", "eps", "cash flow"])


def private_theme(entity: ChatEntity) -> str:
    payload = PRIVATE_COMPANIES.get(entity.normalized.upper()) or PRIVATE_COMPANIES.get(entity.raw.upper()) or {}
    return payload.get("theme", "the related market theme")


def safe_followups_for_entities(language: str, entities: list[ChatEntity]) -> list[str]:
    private = next((entity for entity in entities if entity.entity_type == "private_company"), None)
    if language == "it":
        if private:
            return [f"Costruisci una watchlist di proxy quotati per {private.normalized}.", "Quali societa quotate sono esposte a questo tema?"]
        return ["Mandami il ticker esatto.", "Vuoi che cerchi proxy quotati?"]
    if private:
        return [f"Build a listed-proxy watchlist for {private.normalized}.", "Which public companies are exposed to this theme?"]
    return ["Send the exact ticker.", "Do you want listed proxies?"]


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
    seen: set[str] = set()
    for row in rows:
        ticker = row.get("ticker")
        if context_tickers and ticker not in context_tickers:
            continue
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
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
    entities: list[ChatEntity],
    validation: dict,
    candidates: list[dict],
    asset_packets: list[dict],
    narrative: dict,
    community: dict,
    sentiment: dict,
    memory_hits: list[dict],
    learning_loop_context: dict,
    horizon: str,
    risk_profile: str,
) -> dict:
    if intent == "technical_analysis" and len(candidates) == 1:
        return build_technical_analysis_response(language, candidates[0], validation)
    if intent == "fundamental_analysis" and len(candidates) == 1:
        return build_fundamental_analysis_response(language, candidates[0], validation)
    if intent == "full_analysis" and len(candidates) == 1:
        return build_full_analysis_response(language, candidates[0], narrative, sentiment, learning_loop_context, validation)
    if intent == "compare_assets":
        return build_comparison_response(language, candidates[:6], validation)
    if intent == "opportunity_search":
        return build_opportunity_search_response(language, candidates[:8], narrative, learning_loop_context, risk_profile, horizon)

    labels = LABELS[language]
    top = candidates[:5]
    dominant = narrative.get("dominant_theme", {}) if isinstance(narrative, dict) else {}
    market_mood = narrative.get("market_mood", "mixed") if isinstance(narrative, dict) else "mixed"
    thesis = executive_thesis(language, top, market_mood, dominant, intent)
    support = supporting_evidence(top, asset_packets, narrative, sentiment, memory_hits, learning_loop_context)
    contradictions = contradicting_evidence(top, asset_packets)
    missing = missing_data_points(asset_packets)
    scenarios = scenario_block(language, top)
    levels = levels_block(top)
    risks = risk_points(top, community, missing)
    technical = technical_block(top)
    fundamental = fundamental_block(top)
    learning_points = learning_loop_points(learning_loop_context, language)
    sniper = market_sniper_mode(top, horizon, risk_profile, enabled=intent == "market_sniper")
    sections = dedupe_response_sections([
        {"key": "summary", "title": labels["summary"], "bullets": [thesis]},
        {"key": "observed", "title": labels["observed"], "bullets": observed_data(top, narrative, sentiment)},
        {"key": "technical", "title": labels["technical"], "bullets": technical},
        {"key": "fundamental", "title": labels["fundamental"], "bullets": fundamental},
        {"key": "sentiment", "title": labels["sentiment"], "bullets": narrative_sentiment_points(narrative, sentiment, community)},
        {"key": "learning", "title": "BLUM Learning Loop", "bullets": learning_points},
        {"key": "scenarios", "title": labels["scenarios"], "bullets": scenarios},
        {"key": "levels", "title": labels["levels"], "bullets": levels},
        {"key": "risks", "title": labels["risks"], "bullets": risks},
        {"key": "conclusion", "title": labels["conclusion"], "bullets": conclusion_points(language, top, risk_profile, horizon, intent)},
        {"key": "missing", "title": labels["missing"], "bullets": missing or [no_major_missing_data(language)]},
    ])
    composed = render_sections(sections, labels["disclaimer"])
    return {
        "response_style": "structured",
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
        "learning_loop_view": learning_points,
        "research_plan": planning_steps(top, risk_profile, horizon, language),
        "operation_plan": operation_planning_steps(top, horizon, language),
        "market_may_be_missing": market_may_be_missing(top, narrative, sentiment, language),
        "market_sniper_mode": sniper,
        "data_quality": data_quality(top, asset_packets, memory_hits, learning_loop_context),
        "learning_loop_memory": learning_loop_context,
        "answer_to_user": conclusion_points(language, top, risk_profile, horizon, intent)[0],
        "intellectual_honesty": intellectual_honesty(language),
    }


def build_private_company_response(language: str, entity: ChatEntity, technical_requested: bool = False, fundamental_requested: bool = False) -> dict:
    labels = LABELS[language]
    proxies = ", ".join(entity.proxies or [])
    if language == "it":
        if technical_requested:
            summary = f"Qui c'e un problema: {entity.normalized} non e quotata in borsa e non ha un ticker pubblico."
            data = "Non posso fare una vera analisi tecnica diretta: mancano prezzo pubblico, volumi, RSI, MACD, supporti e resistenze."
        elif fundamental_requested:
            summary = f"{entity.normalized} e una societa privata: non esiste un ticker pubblico diretto da analizzare come azione quotata."
            data = "Posso discutere il business e il tema competitivo solo come analisi qualitativa, ma non posso usare multipli di mercato diretti o bilanci completi da società quotata."
        else:
            summary = f"{entity.normalized} e una societa privata, quindi BLUM non puo trattarla come un titolo quotato."
            data = "Il punto chiave e che non esiste una serie pubblica OHLCV validabile per costruire indicatori o segnali tecnici."
        alternatives = f"Posso pero analizzare il tema {private_theme(entity)} tramite proxy quotati: {proxies}." if proxies else "Posso cercare proxy quotati se mi indichi il mercato o il settore preferito."
        ask = "Se vuoi, costruisco una mini-watchlist di proxy quotati e confronto momentum, rischio e narrativa."
        sections = [
            {"key": "summary", "title": "Sintesi", "bullets": [summary]},
            {"key": "missing", "title": "Cosa manca", "bullets": [data]},
            {"key": "alternatives", "title": "Alternative utili", "bullets": [alternatives, ask]},
        ]
        composed = render_sections(sections, labels["disclaimer"])
        return response_contract(
            composed,
            sections,
            summary,
            supporting=[],
            contradictions=[data],
            conclusion=ask,
            style="concise_safe",
        )

    summary = f"Here is the issue: {entity.normalized} is private and has no public common-stock ticker."
    data = "I cannot run direct technical analysis because there is no public OHLCV series, volume, RSI, MACD, support or resistance data for the company itself."
    alternatives = f"I can analyze the {private_theme(entity)} theme through listed proxies such as {proxies}." if proxies else "I can look for listed proxies if you specify the market or sector."
    ask = "If useful, I can build a small public-proxy watchlist and compare momentum, risk and narrative strength."
    sections = [
        {"key": "summary", "title": "Summary", "bullets": [summary]},
        {"key": "missing", "title": "What is missing", "bullets": [data]},
        {"key": "alternatives", "title": "Useful alternatives", "bullets": [alternatives, ask]},
    ]
    composed = render_sections(sections, labels["disclaimer"])
    return response_contract(composed, sections, summary, supporting=[], contradictions=[data], conclusion=ask, style="concise_safe")


def build_ambiguous_company_response(language: str, entity: ChatEntity) -> dict:
    labels = LABELS[language]
    likely = ", ".join(entity.proxies or [])
    if language == "it":
        summary = f"'{entity.raw}' e ambiguo. Potrei intendere {likely}, ma non voglio sostituire l'asset senza conferma."
        ask = "Dimmi il ticker preciso o il mercato di quotazione e procedo con l'analisi."
        sections = [
            {"key": "summary", "title": "Serve chiarimento", "bullets": [summary]},
            {"key": "next", "title": "Prossimo passo", "bullets": [ask]},
        ]
    else:
        summary = f"'{entity.raw}' is ambiguous. I may mean {likely}, but I will not substitute the asset without confirmation."
        ask = "Send the exact ticker or listing market and I will analyze it."
        sections = [
            {"key": "summary", "title": "Clarification needed", "bullets": [summary]},
            {"key": "next", "title": "Next step", "bullets": [ask]},
        ]
    return response_contract(render_sections(sections, labels["disclaimer"]), sections, summary, contradictions=[entity.reason], conclusion=ask, style="clarification")


def build_unknown_asset_response(language: str, entity: ChatEntity) -> dict:
    labels = LABELS[language]
    if language == "it":
        summary = f"Non riesco a collegare '{entity.raw}' a un asset pubblico presente nell'universo BLUM."
        ask = "Mandami il ticker esatto, oppure dimmi se si tratta di azienda privata, ETF, indice o crypto."
        sections = [
            {"key": "summary", "title": "Asset non validato", "bullets": [summary]},
            {"key": "next", "title": "Cosa serve", "bullets": [ask]},
        ]
    else:
        summary = f"I cannot connect '{entity.raw}' to a public asset in the BLUM universe."
        ask = "Send the exact ticker, or tell me whether it is a private company, ETF, index or crypto."
        sections = [
            {"key": "summary", "title": "Asset not validated", "bullets": [summary]},
            {"key": "next", "title": "What I need", "bullets": [ask]},
        ]
    return response_contract(render_sections(sections, labels["disclaimer"]), sections, summary, contradictions=["Asset validation failed."], conclusion=ask, style="clarification")


def build_error_response(language: str, message: str, suggestions: list[str] | None = None) -> dict:
    labels = LABELS[language]
    suggestions = dedupe_warnings(suggestions or [])
    if language == "it":
        sections = [
            {"key": "summary", "title": "Non posso completare l'analisi", "bullets": [message]},
            {"key": "next", "title": "Alternativa", "bullets": suggestions or ["Posso spiegare quali dati servirebbero o provare con un proxy valido."]},
        ]
    else:
        sections = [
            {"key": "summary", "title": "I cannot complete the analysis", "bullets": [message]},
            {"key": "next", "title": "Alternative", "bullets": suggestions or ["I can explain which data is needed or try a valid proxy."]},
        ]
    return response_contract(render_sections(sections, labels["disclaimer"]), sections, message, contradictions=[message], conclusion=sections[-1]["bullets"][0], style="error")


def build_technical_analysis_response(language: str, candidate: dict, validation: dict) -> dict:
    labels = LABELS[language]
    ticker = candidate.get("ticker")
    tech = candidate.get("technical") or {}
    levels = tech.get("levels") or {}
    indicators = tech.get("technical_indicators") or {}
    latest = candidate.get("price_date")
    stale = freshness_warning(language, latest)
    trend = tech.get("trend_direction", "not available")
    momentum = tech.get("momentum") or {}
    volume = tech.get("volume") or {}
    risk = tech.get("risk_reward_estimate") or {}
    summary = (
        f"{ticker}: trend {trend}, RSI {indicators.get('rsi')}, volume relativo {volume.get('relative_volume')}."
        if language == "it"
        else f"{ticker}: {trend} trend, RSI {indicators.get('rsi')}, relative volume {volume.get('relative_volume')}."
    )
    if stale:
        summary = f"{summary} {stale}"
    if language == "it":
        sections = [
            {"key": "summary", "title": "Sintesi", "bullets": [summary]},
            {"key": "trend", "title": "Trend", "bullets": [f"Struttura: {trend}. Forza trend: {tech.get('trend_strength_score', 'n/a')}/100. Ultimo dato disponibile: {latest or 'n/a'}."]},
            {"key": "momentum", "title": "Momentum", "bullets": [f"RSI {indicators.get('rsi')}; MACD hist {indicators.get('macd_hist')}; stato momentum {momentum.get('state', 'n/a')}."]},
            {"key": "levels", "title": "Livelli tecnici", "bullets": [f"Supporti: {level_list(levels.get('support_levels'))}. Resistenze: {level_list(levels.get('resistance_levels'))}. Breakout: {levels.get('breakout_level')}. Invalidazione: {levels.get('invalidation_level')}."]},
            {"key": "scenario", "title": "Scenario", "bullets": [technical_scenario_it(ticker, tech, risk)]},
            {"key": "risks", "title": "Rischi", "bullets": dedupe_warnings([f"Rischio: {candidate.get('risk_level')} / score {candidate.get('risk_score')}.", tech.get("technical_summary"), stale])},
        ]
    else:
        sections = [
            {"key": "summary", "title": "Summary", "bullets": [summary]},
            {"key": "trend", "title": "Trend", "bullets": [f"Structure: {trend}. Trend strength: {tech.get('trend_strength_score', 'n/a')}/100. Latest available data: {latest or 'n/a'}."]},
            {"key": "momentum", "title": "Momentum", "bullets": [f"RSI {indicators.get('rsi')}; MACD hist {indicators.get('macd_hist')}; momentum state {momentum.get('state', 'n/a')}."]},
            {"key": "levels", "title": "Technical Levels", "bullets": [f"Support: {level_list(levels.get('support_levels'))}. Resistance: {level_list(levels.get('resistance_levels'))}. Breakout: {levels.get('breakout_level')}. Invalidation: {levels.get('invalidation_level')}."]},
            {"key": "scenario", "title": "Scenario", "bullets": [technical_scenario_en(ticker, tech, risk)]},
            {"key": "risks", "title": "Risks", "bullets": dedupe_warnings([f"Risk: {candidate.get('risk_level')} / score {candidate.get('risk_score')}.", tech.get("technical_summary"), stale])},
        ]
    sections = dedupe_response_sections(sections)
    composed = render_sections(sections, labels["disclaimer"])
    return response_contract(
        composed,
        sections,
        summary,
        supporting=[bullet for section in sections[:4] for bullet in section.get("bullets", [])],
        contradictions=sections[-1]["bullets"],
        conclusion=sections[-2]["bullets"][0],
        style="technical",
    )


def build_fundamental_analysis_response(language: str, candidate: dict, validation: dict) -> dict:
    labels = LABELS[language]
    ticker = candidate.get("ticker")
    fundamentals = candidate.get("fundamentals") or {}
    metrics = fundamentals.get("metrics") or {}
    status = fundamentals.get("status", "missing")
    quality = fundamentals.get("quality_score", 0)
    latest_period = metrics.get("revenue", {}).get("end") if isinstance(metrics.get("revenue"), dict) else None
    if language == "it":
        summary = f"{ticker}: fondamentali {status}, quality score {quality}/100."
        sections = [
            {"key": "summary", "title": "Sintesi", "bullets": [summary]},
            {"key": "data", "title": "Dati disponibili", "bullets": [f"Revenue: {metric_state(metrics.get('revenue'))}; net income: {metric_state(metrics.get('net_income'))}; cash flow operativo: {metric_state(metrics.get('operating_cash_flow'))}; periodo: {latest_period or 'n/a'}."]},
            {"key": "view", "title": "Lettura BLUM", "bullets": [fundamental_read_it(ticker, fundamentals, candidate)]},
            {"key": "risks", "title": "Rischi", "bullets": missing_fundamental_warnings_it(ticker, fundamentals)},
        ]
    else:
        summary = f"{ticker}: fundamentals {status}, quality score {quality}/100."
        sections = [
            {"key": "summary", "title": "Summary", "bullets": [summary]},
            {"key": "data", "title": "Available Data", "bullets": [f"Revenue: {metric_state(metrics.get('revenue'))}; net income: {metric_state(metrics.get('net_income'))}; operating cash flow: {metric_state(metrics.get('operating_cash_flow'))}; period: {latest_period or 'n/a'}."]},
            {"key": "view", "title": "BLUM Read", "bullets": [fundamental_read_en(ticker, fundamentals, candidate)]},
            {"key": "risks", "title": "Risks", "bullets": missing_fundamental_warnings_en(ticker, fundamentals)},
        ]
    sections = dedupe_response_sections(sections)
    return response_contract(render_sections(sections, labels["disclaimer"]), sections, summary, supporting=sections[1]["bullets"], contradictions=sections[-1]["bullets"], conclusion=sections[2]["bullets"][0], style="fundamental")


def build_full_analysis_response(language: str, candidate: dict, narrative: dict, sentiment: dict, learning_loop_context: dict, validation: dict) -> dict:
    technical = build_technical_analysis_response(language, candidate, validation)
    fundamental = build_fundamental_analysis_response(language, candidate, validation)
    labels = LABELS[language]
    ticker = candidate.get("ticker")
    learning = learning_loop_points(learning_loop_context, language)[:2]
    narrative_point = narrative_sentiment_points(narrative, sentiment, {"most_discussed_assets": []})[:2]
    if language == "it":
        sections = [
            {"key": "summary", "title": "Sintesi", "bullets": [f"{ticker} ha score BLUM {candidate.get('opportunity_score')}/100, confidence {candidate.get('confidence_level')} e rischio {candidate.get('risk_level')}. Ultimo dato: {candidate.get('price_date') or 'n/a'}."]},
            *technical["standard_sections"][1:4],
            *fundamental["standard_sections"][1:3],
            {"key": "sentiment", "title": "Sentiment e narrativa", "bullets": narrative_point},
            {"key": "learning", "title": "Memoria BLUM", "bullets": learning},
            {"key": "risks", "title": "Rischi", "bullets": risk_points([candidate], {"possible_hype_bubbles": []}, [])},
            {"key": "conclusion", "title": "Vista finale", "bullets": [f"{ticker} e interessante solo se il prezzo conferma i livelli tecnici con volume e senza peggioramento del rischio. Se manca conferma, resta watchlist."]},
        ]
    else:
        sections = [
            {"key": "summary", "title": "Summary", "bullets": [f"{ticker} has BLUM score {candidate.get('opportunity_score')}/100, confidence {candidate.get('confidence_level')} and risk {candidate.get('risk_level')}. Latest data: {candidate.get('price_date') or 'n/a'}."]},
            *technical["standard_sections"][1:4],
            *fundamental["standard_sections"][1:3],
            {"key": "sentiment", "title": "Sentiment and Narrative", "bullets": narrative_point},
            {"key": "learning", "title": "BLUM Memory", "bullets": learning},
            {"key": "risks", "title": "Risks", "bullets": risk_points([candidate], {"possible_hype_bubbles": []}, [])},
            {"key": "conclusion", "title": "Final View", "bullets": [f"{ticker} is interesting only if price confirms key levels with volume and no deterioration in risk. Without confirmation, it stays watchlist only."]},
        ]
    sections = dedupe_response_sections(sections)
    return response_contract(render_sections(sections, labels["disclaimer"]), sections, sections[0]["bullets"][0], supporting=technical["supporting_evidence"], contradictions=fundamental["contradicting_evidence"], conclusion=sections[-1]["bullets"][0], style="full_analysis")


def build_comparison_response(language: str, candidates: list[dict], validation: dict) -> dict:
    labels = LABELS[language]
    if not candidates:
        return build_error_response(language, "No validated public assets were found for comparison." if language == "en" else "Non ho trovato asset pubblici validati da confrontare.")
    lines = []
    for item in candidates:
        lines.append(f"{item.get('ticker')}: BLUM {item.get('opportunity_score')}/100 | technical {item.get('technical_score')}/100 | fundamental {item.get('fundamental_score')}/100 | risk {item.get('risk_level')}")
    if language == "it":
        best = max(candidates, key=lambda item: safe_float(item.get("opportunity_score")))
        sections = [
            {"key": "summary", "title": "Sintesi comparativa", "bullets": [f"Nel set validato, {best.get('ticker')} ha il profilo BLUM piu forte, ma il rischio resta da verificare sui livelli tecnici."]},
            {"key": "scores", "title": "Score", "bullets": lines},
            {"key": "risk", "title": "Rischi", "bullets": [f"Non considero questo confronto una classifica operativa: serve conferma su prezzo, volume e contesto di mercato."]},
        ]
    else:
        best = max(candidates, key=lambda item: safe_float(item.get("opportunity_score")))
        sections = [
            {"key": "summary", "title": "Comparative Summary", "bullets": [f"In the validated set, {best.get('ticker')} has the strongest BLUM profile, but risk must still be checked against technical levels."]},
            {"key": "scores", "title": "Scores", "bullets": lines},
            {"key": "risk", "title": "Risks", "bullets": ["This is not an execution ranking: price, volume and market context still need confirmation."]},
        ]
    return response_contract(render_sections(sections, labels["disclaimer"]), dedupe_response_sections(sections), sections[0]["bullets"][0], supporting=lines, contradictions=sections[-1]["bullets"], conclusion=sections[0]["bullets"][0], style="comparison")


def build_opportunity_search_response(language: str, candidates: list[dict], narrative: dict, learning_loop_context: dict, risk_profile: str, horizon: str) -> dict:
    labels = LABELS[language]
    top = candidates[:5]
    if not top:
        return build_error_response(language, "BLUM does not have enough validated evidence to rank opportunities right now." if language == "en" else "BLUM non ha abbastanza evidenza validata per classificare opportunita in questo momento.")
    rows = [f"{item.get('ticker')}: {item.get('classification')} | score {item.get('opportunity_score')}/100 | risk {item.get('risk_level')} | {item.get('why_today')}" for item in top]
    learning = learning_loop_points(learning_loop_context, language)[:2]
    if language == "it":
        sections = [
            {"key": "summary", "title": "Cosa guardare ora", "bullets": [f"Con profilo {risk_profile} e orizzonte {horizon}, questi sono candidati da monitorare, non ordini operativi."]},
            {"key": "candidates", "title": "Top candidati", "bullets": rows},
            {"key": "learning", "title": "Filtro memoria BLUM", "bullets": learning},
            {"key": "risk", "title": "Rischio", "bullets": ["Scarto o riduco convinzione se mancano prezzo aggiornato, volume, conferma settoriale o news di qualita."]},
        ]
    else:
        sections = [
            {"key": "summary", "title": "What to watch now", "bullets": [f"For a {risk_profile} profile and {horizon} horizon, these are monitoring candidates, not execution orders."]},
            {"key": "candidates", "title": "Top Candidates", "bullets": rows},
            {"key": "learning", "title": "BLUM Memory Filter", "bullets": learning},
            {"key": "risk", "title": "Risk", "bullets": ["Conviction is reduced or rejected when updated price, volume, sector confirmation or high-quality news are missing."]},
        ]
    return response_contract(render_sections(sections, labels["disclaimer"]), dedupe_response_sections(sections), sections[0]["bullets"][0], supporting=rows, contradictions=sections[-1]["bullets"], conclusion=sections[0]["bullets"][0], style="opportunity_search")


def response_contract(
    composed: str,
    sections: list[dict],
    executive: str,
    supporting: list[str] | None = None,
    contradictions: list[str] | None = None,
    conclusion: str = "",
    style: str = "structured",
) -> dict:
    supporting = dedupe_warnings(supporting or [])
    contradictions = dedupe_warnings(contradictions or [])
    sections = dedupe_response_sections(sections)
    return {
        "response_style": style,
        "composed_response": composed,
        "standard_sections": sections,
        "executive_view": executive,
        "opportunity_lens": "Explain BLUM evidence naturally; do not force a trade thesis.",
        "supporting_evidence": supporting,
        "contradicting_evidence": contradictions,
        "bull_case": "",
        "base_case": "",
        "bear_case": "",
        "risk_reward_view": conclusion,
        "what_to_monitor": [],
        "learning_loop_view": [],
        "research_plan": [],
        "operation_plan": [],
        "market_may_be_missing": [],
        "market_sniper_mode": {},
        "data_quality": {"policy": "No synthetic market data is created. Missing data blocks unsupported analysis."},
        "learning_loop_memory": {},
        "answer_to_user": conclusion or executive,
        "intellectual_honesty": "If data is missing, BLUM says so instead of inventing analysis.",
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
            "learning_loop_memory": answer.get("learning_loop_memory"),
            "risk_reward_view": answer.get("risk_reward_view"),
            "what_to_monitor": answer.get("what_to_monitor", []),
            "learning_loop_view": answer.get("learning_loop_view", []),
        },
        "candidate_opportunities": payload.get("candidate_opportunities", [])[:10],
        "context_coverage": payload.get("context_coverage"),
        "sources_used": payload.get("sources_used"),
        "rag_pipeline": payload.get("rag_pipeline"),
        "models_used": payload.get("models_used"),
        "disclaimer": payload.get("disclaimer"),
    }


def minimal_chat_payload(
    *,
    session: ChatSession,
    message: str,
    language: str,
    intent: str,
    answer: dict,
    entities: list[ChatEntity],
    mode: str | None = None,
    validation: dict | None = None,
) -> dict:
    payload = {
        "generated_at": datetime.utcnow().isoformat(),
        "mode": "blum_multilingual_market_intelligence_chat",
        "session_id": session.session_key,
        "language": language,
        "intent": intent,
        "question": message,
        "answer": answer,
        "entity_resolution": [entity.to_dict() for entity in entities],
        "candidate_opportunities": [],
        "asset_context": [],
        "market_context": {},
        "semantic_evidence": [],
        "training_memory": [],
        "learning_loop_context": {},
        "rag_pipeline": rag_pipeline(language, intent),
        "sources_used": [],
        "context_coverage": {
            "assets_detected": 0,
            "assets_with_price": 0,
            "assets_with_technical_analysis": 0,
            "assets_with_fundamentals": 0,
            "assets_with_news": 0,
            "semantic_hits": 0,
            "memory_hits": 0,
            "learning_loop_memory_hits": 0,
            "learning_loop_signal_reliability": 0,
        },
        "suggested_followups": safe_followups_for_entities(language, entities),
        "models_used": {
            "reasoning": "deterministic_entity_validation_and_response_builder",
            "policy": "No market analysis is generated when asset validation fails.",
        },
        "governance": [
            "Entity validation runs before market-data retrieval.",
            "Unknown or private assets are never replaced with random tickers.",
            "Technical analysis is blocked when OHLCV data is unavailable.",
        ],
        "disclaimer": LABELS[language]["disclaimer"],
    }
    if mode in {"debug", "developer", "chatbot_debug_feedback"}:
        payload["diagnostics"] = {
            "detected_language": language,
            "detected_intent": intent,
            "entities": [entity.to_dict() for entity in entities],
            "validation": validation or {},
            "response_template_used": answer.get("response_style"),
        }
    return json_safe(payload)


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
    normalized = strip_accents(text)
    if any(term in normalized for term in ["debug", "risposta sbagliata", "bad answer", "non funziona", "hai sbagliato"]):
        return "chatbot_debug_feedback"
    if any(term in normalized for term in ["analisi completa", "full analysis", "tecnica e fondamentale", "tecnico e fondamentale", "technical and fundamental"]):
        return "full_analysis"
    if any(term in normalized for term in ["analisi tecnica", "technical analysis", "rsi", "macd", "support", "resisten", "supporti", "breakout", "breakdown"]):
        return "technical_analysis"
    if any(term in normalized for term in ["analisi fondamentale", "fundamental analysis", "fondamentali", "bilancio", "revenue", "eps", "cash flow", "valuation", "multipli"]):
        return "fundamental_analysis"
    if any(term in normalized for term in ["sniper", "ingresso", "entry", "risk/reward", "uscita", "target", "invalidazione"]):
        return "technical_analysis"
    if any(term in text for term in ["confronta", "compare", "vs", "versus"]):
        return "compare_assets"
    if any(term in normalized for term in ["trova", "find", "watchlist", "opportunit", "opportunity", "etf", "candidati", "titoli interessanti"]):
        return "opportunity_search"
    if any(term in normalized for term in ["narrative", "narrativa", "theme", "tema", "macro"]):
        return "narrative_analysis"
    if any(term in normalized for term in ["portfolio", "portafoglio", "allocazione", "allocation"]):
        return "portfolio_question"
    if any(term in normalized for term in ["come funziona", "what is", "spiegami", "explain"]):
        return "educational_question"
    return "full_analysis" if looks_like_asset_request(message) else "market_summary"


def detect_language(message: str) -> str:
    text = f" {strip_accents(message.lower())} "
    scores = {code: sum(1 for hint in hints if hint in text) for code, hints in LANGUAGE_HINTS.items()}
    italian_words = {"analisi", "tecnica", "fondamentale", "azione", "titolo", "quotata", "borsa", "rischio", "livelli", "supporti", "resistenze"}
    english_words = {"analysis", "technical", "fundamental", "stock", "risk", "levels", "support", "resistance"}
    tokens = set(re.findall(r"[a-zA-Zàèéìòùáíóúñäöüß]+", message.lower()))
    scores["it"] += len(tokens & italian_words)
    scores["en"] += len(tokens & english_words)
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


def expand_company_terms(text: str) -> set[str]:
    tickers: set[str] = set()
    for term, mapped_tickers in COMPANY_TERM_TICKERS.items():
        if re.search(rf"(?<![A-Z0-9]){re.escape(term)}(?![A-Z0-9])", text):
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


def freshness_warning(language: str, latest_date: str | None) -> str:
    if not latest_date:
        return "Attenzione: timestamp prezzo non disponibile." if language == "it" else "Warning: price timestamp is not available."
    try:
        point = datetime.fromisoformat(str(latest_date)).date()
    except ValueError:
        return ""
    age = (datetime.utcnow().date() - point).days
    if age > 5:
        return f"Attenzione: ultimo dato disponibile {latest_date}, quindi non e real-time." if language == "it" else f"Warning: latest available data is {latest_date}, so this is not real-time."
    return f"Ultimo dato disponibile: {latest_date}." if language == "it" else f"Latest available data: {latest_date}."


def technical_scenario_it(ticker: str, tech: dict, risk: dict) -> str:
    levels = tech.get("levels") or {}
    breakout = levels.get("breakout_level")
    invalidation = levels.get("invalidation_level")
    volume = (tech.get("volume") or {}).get("relative_volume")
    rr = risk.get("label", "non definito")
    return (
        f"Scenario informativo: {ticker} migliora solo con conferma sopra {breakout} e volume relativo in espansione "
        f"(ora {volume}). L'invalidazione tecnica e {invalidation}. Rapporto rischio/rendimento: {rr}."
    )


def technical_scenario_en(ticker: str, tech: dict, risk: dict) -> str:
    levels = tech.get("levels") or {}
    breakout = levels.get("breakout_level")
    invalidation = levels.get("invalidation_level")
    volume = (tech.get("volume") or {}).get("relative_volume")
    rr = risk.get("label", "undefined")
    return (
        f"Informational scenario: {ticker} improves only with confirmation above {breakout} and expanding relative volume "
        f"(now {volume}). Technical invalidation is {invalidation}. Risk/reward: {rr}."
    )


def metric_state(metric) -> str:
    if not metric:
        return "missing"
    if isinstance(metric, dict):
        value = metric.get("value")
        unit = metric.get("unit", "")
        return f"available ({value} {unit})".strip()
    return "available"


def fundamental_read_it(ticker: str, fundamentals: dict, candidate: dict) -> str:
    if fundamentals.get("status") != "ready":
        return f"Per {ticker} i fondamentali non sono completi nel database BLUM; quindi la tesi deve pesare di piu su prezzo, rischio e narrativa."
    quality = fundamentals.get("quality_score", 0)
    return f"I fondamentali disponibili sono utilizzabili con quality score {quality}/100. Non bastano da soli: vanno confrontati con momentum, valutazione e rischio di delusione sugli utili."


def fundamental_read_en(ticker: str, fundamentals: dict, candidate: dict) -> str:
    if fundamentals.get("status") != "ready":
        return f"For {ticker}, fundamentals are incomplete in BLUM's database; the thesis must lean more on price, risk and narrative evidence."
    quality = fundamentals.get("quality_score", 0)
    return f"Available fundamentals are usable with quality score {quality}/100. They are not sufficient alone and must be compared with momentum, valuation and earnings-disappointment risk."


def missing_fundamental_warnings_it(ticker: str, fundamentals: dict) -> list[str]:
    metrics = fundamentals.get("metrics") or {}
    rows = []
    if fundamentals.get("status") != "ready":
        rows.append(f"{ticker}: fondamentali incompleti o non disponibili.")
    for label, key in [("revenue", "revenue"), ("net income", "net_income"), ("cash flow operativo", "operating_cash_flow")]:
        if not metrics.get(key):
            rows.append(f"{ticker}: {label} non presente nel contesto recuperato.")
    return rows or ["Il rischio principale e che la narrativa di mercato corra piu dei numeri fondamentali."]


def missing_fundamental_warnings_en(ticker: str, fundamentals: dict) -> list[str]:
    metrics = fundamentals.get("metrics") or {}
    rows = []
    if fundamentals.get("status") != "ready":
        rows.append(f"{ticker}: fundamentals are incomplete or unavailable.")
    for label, key in [("revenue", "revenue"), ("net income", "net_income"), ("operating cash flow", "operating_cash_flow")]:
        if not metrics.get(key):
            rows.append(f"{ticker}: {label} is missing from retrieved context.")
    return rows or ["The main risk is that market narrative runs ahead of the fundamental numbers."]


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


def supporting_evidence(top: list[dict], asset_packets: list[dict], narrative: dict, sentiment: dict, memory_hits: list[dict], learning_loop_context: dict) -> list[str]:
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
    strategy_memory = learning_loop_context.get("strategy_memory", []) if isinstance(learning_loop_context, dict) else []
    signal_reliability = learning_loop_context.get("signal_reliability", []) if isinstance(learning_loop_context, dict) else []
    if strategy_memory:
        top_memory = strategy_memory[0]
        rows.append(f"Learning Loop memory: {top_memory.get('lesson')} | reliability {top_memory.get('reliability_score')}/100 over {top_memory.get('sample_count')} samples.")
    if signal_reliability:
        top_signal = signal_reliability[0]
        rows.append(f"Most reliable simulated signal factor: {top_signal.get('signal_name')} / {top_signal.get('timeframe')} with reliability {top_signal.get('reliability_score')}/100.")
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


def learning_loop_points(learning_loop_context: dict, language: str) -> list[str]:
    if not isinstance(learning_loop_context, dict):
        return ["BLUM Learning Loop memory is not available in this response context."]
    memory = learning_loop_context.get("strategy_memory", [])
    reliability = learning_loop_context.get("signal_reliability", [])
    predictions = learning_loop_context.get("ticker_recent_predictions", [])
    rows = []
    if memory:
        for item in memory[:3]:
            if language == "it":
                rows.append(f"Lezione storica: {item.get('lesson')} | affidabilita {item.get('reliability_score')}/100 su {item.get('sample_count')} campioni.")
            else:
                rows.append(f"Historical lesson: {item.get('lesson')} | reliability {item.get('reliability_score')}/100 across {item.get('sample_count')} samples.")
    if reliability:
        for item in reliability[:2]:
            if language == "it":
                rows.append(f"Fattore simulato: {item.get('signal_name')} ({item.get('timeframe')}) | reliability {item.get('reliability_score')}/100 | false positive {item.get('false_positive_count')}.")
            else:
                rows.append(f"Simulated factor: {item.get('signal_name')} ({item.get('timeframe')}) | reliability {item.get('reliability_score')}/100 | false positives {item.get('false_positive_count')}.")
    if predictions:
        rows.append(f"Ticker-specific historical predictions retrieved: {len(predictions)}.")
    return rows or [
        "BLUM has not accumulated enough point-in-time simulation memory for this query yet; confidence should remain conservative."
        if language == "en"
        else "BLUM non ha ancora abbastanza memoria point-in-time per questa domanda; la confidence deve restare prudente."
    ]


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


def data_quality(top: list[dict], asset_packets: list[dict], memory_hits: list[dict], learning_loop_context: dict) -> dict:
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
        "learning_memory_hits": len((learning_loop_context or {}).get("strategy_memory", [])),
        "signal_reliability_rows": len((learning_loop_context or {}).get("signal_reliability", [])),
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


def sources_used(asset_packets: list[dict], semantic_hits: list[dict], memory_hits: list[dict], narrative: dict, sentiment: dict, learning_loop_context: dict) -> list[dict]:
    sources = [
        {"name": "Blum asset universe", "type": "internal_db", "coverage": len(asset_packets)},
        {"name": "Stored OHLCV market snapshots", "type": "internal_db", "coverage": sum(1 for item in asset_packets if item.get("market_snapshot", {}).get("data_status") == "ready")},
        {"name": "Deterministic technical engine", "type": "calculated", "coverage": sum(1 for item in asset_packets if item.get("technical_analysis", {}).get("status") == "ready")},
        {"name": "SEC companyfacts fundamentals", "type": "public_filings", "coverage": sum(1 for item in asset_packets if item.get("fundamentals", {}).get("status") == "ready")},
        {"name": "FinBERT/VADER sentiment records", "type": "ai_sentiment", "coverage": sentiment.get("article_count", 0)},
        {"name": "Narrative intelligence", "type": "semantic_news", "coverage": len(narrative.get("emerging_subthemes", []) or [])},
        {"name": "Semantic news search", "type": "embeddings", "coverage": len(semantic_hits)},
        {"name": "Blum training memory", "type": "reasoning_memory", "coverage": len(memory_hits)},
        {"name": "BLUM Learning Loop strategy memory", "type": "point_in_time_simulation_memory", "coverage": len((learning_loop_context or {}).get("strategy_memory", []))},
        {"name": "BLUM Learning Loop signal reliability", "type": "walk_forward_outcome_memory", "coverage": len((learning_loop_context or {}).get("signal_reliability", []))},
    ]
    return sources


def context_coverage(asset_packets: list[dict], semantic_hits: list[dict], memory_hits: list[dict], learning_loop_context: dict) -> dict:
    return {
        "assets_detected": len(asset_packets),
        "assets_with_price": sum(1 for item in asset_packets if item.get("market_snapshot", {}).get("data_status") == "ready"),
        "assets_with_technical_analysis": sum(1 for item in asset_packets if item.get("technical_analysis", {}).get("status") == "ready"),
        "assets_with_fundamentals": sum(1 for item in asset_packets if item.get("fundamentals", {}).get("status") == "ready"),
        "assets_with_news": sum(1 for item in asset_packets if item.get("recent_news")),
        "semantic_hits": len(semantic_hits),
        "memory_hits": len(memory_hits),
        "learning_loop_memory_hits": len((learning_loop_context or {}).get("strategy_memory", [])),
        "learning_loop_signal_reliability": len((learning_loop_context or {}).get("signal_reliability", [])),
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
