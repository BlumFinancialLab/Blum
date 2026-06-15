from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import mean

from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    AccuracySnapshot,
    Asset,
    CorporateActionEvent,
    ETFTrend,
    FundamentalSnapshot,
    MacroSnapshot,
    NewsArticle,
    NewsAssetLink,
    PriceHistory,
    PriceProviderCheck,
    SentimentAnalysis,
    SignalSnapshot,
)
from app.services.data_continuity import data_coverage_report


settings = get_settings()

EVENT_KEYWORDS = {
    "earnings": ["earnings", "eps", "revenue", "profit", "margin"],
    "guidance": ["guidance", "forecast", "outlook", "raised", "cut forecast"],
    "m_and_a": ["merger", "acquisition", "takeover", "buyout", "deal"],
    "regulation": ["regulator", "sec", "antitrust", "probe", "investigation", "ban"],
    "analyst_revision": ["upgrade", "downgrade", "price target", "analyst"],
    "product": ["launch", "product", "chip", "platform", "drug", "approval"],
    "supply_chain": ["supply chain", "shortage", "inventory", "shipping"],
    "capital_return": ["buyback", "repurchase", "dividend"],
}


def market_accuracy_overview(db: Session, persist: bool = False) -> dict:
    assets = db.scalars(select(Asset).where(Asset.is_active.is_(True)).order_by(Asset.asset_type, Asset.ticker)).all()
    profiles = [asset_accuracy_profile(db, asset, persist=False) for asset in assets]
    score = round(mean([item["blum_confidence_score"] for item in profiles]), 1) if profiles else 0.0
    issues = {}
    for profile in profiles:
        for issue in profile["issues"]:
            issues[issue["code"]] = issues.get(issue["code"], 0) + 1
    overview = {
        "scope": "market",
        "blum_confidence_score": score,
        "confidence_label": confidence_label(score),
        "asset_count": len(profiles),
        "top_quality_assets": sorted(profiles, key=lambda item: item["blum_confidence_score"], reverse=True)[:10],
        "lowest_quality_assets": sorted(profiles, key=lambda item: item["blum_confidence_score"])[:10],
        "issue_counts": issues,
        "coverage": data_coverage_report(db),
        "accuracy_contract": accuracy_contract(),
    }
    if persist:
        db.add(
            AccuracySnapshot(
                scope="market",
                score=score,
                confidence_label=overview["confidence_label"],
                components={"asset_profiles": len(profiles), "issue_counts": issues},
                issues={"items": issues},
            )
        )
        db.commit()
    return overview


def run_accuracy_audit(db: Session, limit: int = 80) -> dict:
    assets = db.scalars(select(Asset).where(Asset.is_active.is_(True)).order_by(Asset.asset_type, Asset.ticker).limit(limit)).all()
    profiles = [asset_accuracy_profile(db, asset, persist=True) for asset in assets]
    overview = market_accuracy_overview(db, persist=True)
    return {
        "status": "completed",
        "assets_audited": len(profiles),
        "market_confidence": overview["blum_confidence_score"],
        "profiles": profiles,
        "overview": overview,
    }


def asset_accuracy_profile(db: Session, asset: Asset, persist: bool = False) -> dict:
    price = price_quality(db, asset)
    provider = provider_agreement_quality(db, asset)
    corporate = corporate_action_quality(db, asset)
    point_in_time = point_in_time_quality(db, asset)
    entity = entity_resolution_quality(db, asset)
    source = source_credibility_quality(db, asset)
    semantic = semantic_dedupe_quality(db, asset)
    events = event_extraction_quality(db, asset)
    reasoning = reasoning_confidence_quality(db, asset)
    contradictions = contradiction_quality(db, asset)
    fundamentals = fundamental_quality(db, asset)
    macro = macro_quality(db)
    etf = etf_confirmation_quality(db, asset)
    validation = historical_validation_quality(db, asset)

    components = {
        "price_coverage": price,
        "provider_agreement": provider,
        "corporate_actions": corporate,
        "point_in_time": point_in_time,
        "entity_resolution": entity,
        "source_credibility": source,
        "semantic_deduplication": semantic,
        "event_extraction": events,
        "reasoning_confidence": reasoning,
        "contradictions": contradictions,
        "fundamentals": fundamentals,
        "macro_context": macro,
        "etf_confirmation": etf,
        "historical_signal_validation": validation,
    }
    weights = {
        "price_coverage": 0.16,
        "provider_agreement": 0.08,
        "corporate_actions": 0.08,
        "point_in_time": 0.06,
        "entity_resolution": 0.07,
        "source_credibility": 0.07,
        "semantic_deduplication": 0.06,
        "event_extraction": 0.06,
        "reasoning_confidence": 0.06,
        "contradictions": 0.08,
        "fundamentals": 0.07,
        "macro_context": 0.05,
        "etf_confirmation": 0.06,
        "historical_signal_validation": 0.04,
    }
    score = round(sum(components[key]["score"] * weight for key, weight in weights.items()), 1)
    issues = [issue for component in components.values() for issue in component.get("issues", [])]
    profile = {
        "ticker": asset.ticker,
        "name": asset.name,
        "asset_type": asset.asset_type,
        "sector": asset.sector,
        "blum_confidence_score": score,
        "confidence_label": confidence_label(score),
        "components": components,
        "issues": issues,
        "generated_at": datetime.utcnow().isoformat(),
        "accuracy_contract": accuracy_contract(),
    }
    if persist:
        persist_corporate_action_suspects(db, asset, corporate.get("price_action_suspects", []))
        db.add(
            AccuracySnapshot(
                asset_id=asset.id,
                ticker=asset.ticker,
                scope="asset",
                score=score,
                confidence_label=profile["confidence_label"],
                components=components,
                issues={"items": issues},
            )
        )
        db.commit()
    return profile


def latest_accuracy_snapshot(db: Session, ticker: str | None = None, scope: str = "market") -> dict | None:
    query = select(AccuracySnapshot).where(AccuracySnapshot.scope == scope).order_by(desc(AccuracySnapshot.created_at))
    if ticker:
        query = query.where(AccuracySnapshot.ticker == ticker.upper())
    snapshot = db.scalar(query.limit(1))
    if not snapshot:
        return None
    return {
        "id": snapshot.id,
        "ticker": snapshot.ticker,
        "scope": snapshot.scope,
        "blum_confidence_score": snapshot.score,
        "confidence_label": snapshot.confidence_label,
        "components": snapshot.components,
        "issues": (snapshot.issues or {}).get("items", snapshot.issues),
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
    }


def price_quality(db: Session, asset: Asset) -> dict:
    row = db.execute(
        select(func.count(PriceHistory.id), func.min(PriceHistory.date), func.max(PriceHistory.date), func.count(func.distinct(PriceHistory.provider)))
        .where(PriceHistory.asset_id == asset.id)
    ).one()
    count, first_date, last_date, providers = int(row[0] or 0), row[1], row[2], int(row[3] or 0)
    issues = []
    if count == 0:
        issues.append(issue("missing_price_history", "No OHLCV history is stored for this asset.", "High"))
    elif count < settings.minimum_history_rows:
        issues.append(issue("short_price_history", f"Only {count} OHLCV rows are stored.", "Medium"))
    if last_date and (date.today() - last_date).days > settings.stale_price_max_age_days:
        issues.append(issue("stale_price_history", f"Latest OHLCV date is {last_date}.", "Medium"))
    history_score = min(100, count / max(1, settings.minimum_history_rows * 3) * 100)
    freshness_score = 100 if last_date and (date.today() - last_date).days <= settings.stale_price_max_age_days else 35 if last_date else 0
    provider_score = 100 if providers >= 2 else 68 if providers == 1 else 0
    score = round(history_score * 0.5 + freshness_score * 0.34 + provider_score * 0.16, 1)
    return {
        "score": score,
        "rows": count,
        "first_date": first_date.isoformat() if first_date else None,
        "last_date": last_date.isoformat() if last_date else None,
        "stored_provider_count": providers,
        "issues": issues,
    }


def provider_agreement_quality(db: Session, asset: Asset) -> dict:
    latest_check = db.scalar(
        select(PriceProviderCheck)
        .where(PriceProviderCheck.asset_id == asset.id)
        .order_by(desc(PriceProviderCheck.date), desc(PriceProviderCheck.created_at))
        .limit(1)
    )
    providers = db.execute(
        select(PriceHistory.provider, func.count(PriceHistory.id), func.max(PriceHistory.date))
        .where(PriceHistory.asset_id == asset.id)
        .group_by(PriceHistory.provider)
        .order_by(func.count(PriceHistory.id).desc())
    ).all()
    if not providers:
        return {"score": 0, "status": "missing", "providers": [], "issues": [issue("provider_validation_missing", "No provider data to validate.", "High")]}
    if latest_check:
        divergence = float(latest_check.max_divergence_pct or 0)
        if latest_check.provider_count >= 2 and divergence < 0.75:
            score = 100
            issues = []
        elif latest_check.provider_count >= 2:
            score = 72 if divergence < 1.5 else 55
            issues = [issue("provider_price_divergence", f"Latest provider close divergence is {divergence:.2f}%.", "Medium")]
        else:
            score = 68
            issues = [issue("single_price_provider", "Only one public provider returned a recent validation close.", "Low")]
        return {
            "score": score,
            "status": latest_check.status,
            "latest_validation_date": latest_check.date.isoformat() if latest_check.date else None,
            "provider_count": latest_check.provider_count,
            "reference_close": latest_check.reference_close,
            "max_divergence_pct": latest_check.max_divergence_pct,
            "observations": latest_check.observations,
            "stored_history_providers": [{"provider": provider, "rows": int(count), "latest_date": latest.isoformat() if latest else None} for provider, count, latest in providers],
            "issues": issues,
        }
    score = 100 if len(providers) >= 2 else 72
    return {
        "score": score,
        "status": "multi_provider_ready" if len(providers) >= 2 else "single_provider_stored",
        "providers": [{"provider": provider, "rows": int(count), "latest_date": latest.isoformat() if latest else None} for provider, count, latest in providers],
        "validation_policy": "When multiple providers are stored, latest closes are checked for divergence. Single-provider assets are marked lower confidence.",
        "issues": [] if len(providers) >= 2 else [issue("single_price_provider", "Only one historical price provider is stored for this asset.", "Low")],
    }


def corporate_action_quality(db: Session, asset: Asset) -> dict:
    events = db.scalars(select(CorporateActionEvent).where(CorporateActionEvent.asset_id == asset.id).order_by(desc(CorporateActionEvent.effective_date)).limit(10)).all()
    suspects = detect_price_action_suspects(db, asset)
    issues = []
    if suspects and not events:
        issues.append(issue("corporate_action_review", "Large price-ratio events require corporate-action verification.", "Medium"))
    score = 100 if not suspects else 76 if events else 58
    return {
        "score": score,
        "stored_events": [
            {"type": event.action_type, "date": event.effective_date.isoformat(), "confidence": event.confidence, "source": event.source}
            for event in events
        ],
        "price_action_suspects": suspects[:8],
        "issues": issues,
    }


def persist_corporate_action_suspects(db: Session, asset: Asset, suspects: list[dict]) -> int:
    inserted = 0
    for suspect in suspects[:20]:
        try:
            effective_date = date.fromisoformat(str(suspect.get("date")))
        except Exception:
            continue
        exists = db.scalar(
            select(CorporateActionEvent.id)
            .where(
                CorporateActionEvent.asset_id == asset.id,
                CorporateActionEvent.action_type == "price_ratio_review",
                CorporateActionEvent.effective_date == effective_date,
                CorporateActionEvent.source == "price_anomaly_detector",
            )
            .limit(1)
        )
        if exists:
            continue
        try:
            with db.begin_nested():
                db.add(
                    CorporateActionEvent(
                        asset_id=asset.id,
                        ticker=asset.ticker,
                        action_type="price_ratio_review",
                        effective_date=effective_date,
                        source="price_anomaly_detector",
                        confidence=0.62,
                        details=suspect,
                    )
                )
                db.flush()
            inserted += 1
        except IntegrityError:
            continue
    return inserted


def detect_price_action_suspects(db: Session, asset: Asset) -> list[dict]:
    rows = db.execute(
        select(PriceHistory.date, PriceHistory.close)
        .where(PriceHistory.asset_id == asset.id)
        .order_by(PriceHistory.date)
    ).all()
    output = []
    previous = None
    for row_date, close in rows:
        if previous and previous[1] and close:
            ratio = float(close) / float(previous[1])
            if ratio <= 0.55 or ratio >= 1.8:
                output.append({"date": row_date.isoformat(), "ratio": round(ratio, 4), "previous_close": previous[1], "close": close})
        previous = (row_date, close)
    return output


def point_in_time_quality(db: Session, asset: Asset) -> dict:
    signal = latest_signal(db, asset)
    latest_price = db.scalar(select(func.max(PriceHistory.date)).where(PriceHistory.asset_id == asset.id))
    if not signal:
        return {"score": 55 if latest_price else 0, "status": "no_signal_snapshot", "issues": [issue("no_point_in_time_signal", "No signal snapshot has been created yet.", "Medium")]}
    signal_date = signal.created_at.date()
    future_leak = latest_price and latest_price > signal_date + timedelta(days=3)
    return {
        "score": 45 if future_leak else 92,
        "status": "future_data_review" if future_leak else "point_in_time_consistent",
        "signal_created_at": signal.created_at.isoformat(),
        "latest_price_date": latest_price.isoformat() if latest_price else None,
        "issues": [issue("possible_future_data_leak", "Signal should be reviewed for point-in-time consistency.", "High")] if future_leak else [],
    }


def entity_resolution_quality(db: Session, asset: Asset) -> dict:
    linked = db.scalar(select(func.count(NewsAssetLink.id)).where(NewsAssetLink.asset_id == asset.id)) or 0
    strong = db.scalar(select(func.count(NewsAssetLink.id)).where(NewsAssetLink.asset_id == asset.id, NewsAssetLink.relevance_score >= 3)) or 0
    aliases = asset_aliases(asset)
    score = min(100, 45 + strong * 10 + linked * 2)
    return {
        "score": round(score, 1),
        "linked_articles": int(linked),
        "strong_links": int(strong),
        "aliases": aliases,
        "issues": [] if linked else [issue("no_news_entity_links", "No news articles are linked to this asset yet.", "Low")],
    }


def source_credibility_quality(db: Session, asset: Asset) -> dict:
    rows = linked_articles(db, asset, limit=80)
    if not rows:
        return {"score": 45, "articles": 0, "issues": [issue("source_quality_missing", "No linked sources are available for source credibility scoring.", "Low")]}
    scores = [float(article.quality_score or 0) for article in rows]
    return {"score": round(mean(scores), 1), "articles": len(rows), "average_source_quality": round(mean(scores), 1), "issues": []}


def semantic_dedupe_quality(db: Session, asset: Asset) -> dict:
    rows = linked_articles(db, asset, limit=120)
    fingerprints = {}
    for article in rows:
        key = " ".join(sorted(set(article.title.lower().split()))[:10])
        fingerprints[key] = fingerprints.get(key, 0) + 1
    duplicates = sum(count - 1 for count in fingerprints.values() if count > 1)
    ratio = duplicates / max(1, len(rows))
    score = round(max(45, 100 - ratio * 100), 1)
    return {
        "score": score,
        "articles": len(rows),
        "estimated_duplicate_ratio": round(ratio, 4),
        "issues": [issue("semantic_news_duplicates", "Linked news contains repeated narrative clusters.", "Low")] if ratio > 0.28 else [],
    }


def event_extraction_quality(db: Session, asset: Asset) -> dict:
    rows = linked_articles(db, asset, limit=80)
    events = {}
    for article in rows:
        for event in extract_events(f"{article.title} {article.summary}"):
            events[event] = events.get(event, 0) + 1
    score = min(100, 48 + sum(events.values()) * 6)
    return {
        "score": round(score, 1),
        "events": events,
        "issues": [] if events else [issue("no_structured_news_events", "No structured event type has been extracted from linked news.", "Low")],
    }


def reasoning_confidence_quality(db: Session, asset: Asset) -> dict:
    signal = latest_signal(db, asset)
    if not signal:
        return {"score": 35, "status": "no_signal", "issues": [issue("reasoning_without_signal", "No signal exists for AI reasoning.", "Medium")]}
    data_score = float(signal.confidence_score or 0)
    watch_points = len((signal.watch_points or {}).get("items", []))
    score = round(min(100, data_score * 0.8 + watch_points * 4), 1)
    return {"score": score, "signal_confidence": data_score, "watch_points": watch_points, "issues": [] if score >= 50 else [issue("low_reasoning_confidence", "Signal explanation has low evidence confidence.", "Medium")]}


def contradiction_quality(db: Session, asset: Asset) -> dict:
    signal = latest_signal(db, asset)
    issues = []
    if not signal:
        return {"score": 55, "status": "no_signal", "issues": []}
    narrative = signal.narrative_summary or {}
    technical = signal.technical_summary or {}
    if numeric(technical.get("perf_5d")) > 4 and numeric(narrative.get("sentiment_7d")) < -0.15:
        issues.append(issue("price_up_sentiment_down", "Price strength conflicts with negative 7D sentiment.", "Medium"))
    if signal.risk_level == "High" and signal.blum_score >= 75:
        issues.append(issue("high_score_high_risk", "High opportunity score is paired with high risk.", "Medium"))
    if numeric(technical.get("rsi")) > 72 and signal.classification in {"Strong Watch", "Narrative Breakout", "Technical Breakout"}:
        issues.append(issue("overbought_signal", "Signal is strong while RSI is elevated.", "Low"))
    return {"score": max(35, 100 - len(issues) * 22), "issues": issues}


def fundamental_quality(db: Session, asset: Asset) -> dict:
    snapshot = db.scalar(select(FundamentalSnapshot).where(FundamentalSnapshot.asset_id == asset.id).order_by(desc(FundamentalSnapshot.period_end), desc(FundamentalSnapshot.created_at)).limit(1))
    if asset.asset_type != "Stock":
        return {"score": 85, "status": "not_required_for_etf", "issues": []}
    if not snapshot:
        return {"score": 38, "status": "missing", "issues": [issue("fundamentals_missing", "No verified fundamental snapshot is stored.", "Medium")]}
    return {"score": snapshot.quality_score, "status": "ready", "period_end": snapshot.period_end.isoformat() if snapshot.period_end else None, "provider": snapshot.provider, "issues": []}


def macro_quality(db: Session) -> dict:
    count = int(db.scalar(select(func.count(func.distinct(MacroSnapshot.indicator)))) or 0)
    score = round(min(100, count / 7 * 100), 1)
    return {"score": score, "series_available": count, "issues": [] if count >= 5 else [issue("macro_context_incomplete", "Macro context has fewer than five stored public series.", "Low")]}


def etf_confirmation_quality(db: Session, asset: Asset) -> dict:
    if asset.asset_type == "ETF":
        trend = db.scalar(select(ETFTrend).where(ETFTrend.asset_id == asset.id).order_by(desc(ETFTrend.created_at)).limit(1))
        score = float(trend.confirmation_score) if trend else 55
        return {"score": round(score, 1), "status": "etf_self_confirmation", "issues": [] if trend else [issue("etf_trend_missing", "ETF trend row is not stored yet.", "Low")]}
    trends = db.scalars(select(ETFTrend).order_by(desc(ETFTrend.created_at), desc(ETFTrend.confirmation_score)).limit(80)).all()
    sector_hits = [trend for trend in trends if asset.sector.lower() in f"{trend.category} {trend.details}".lower()]
    if not sector_hits:
        return {"score": 55, "status": "no_sector_etf_match", "issues": [issue("etf_confirmation_missing", "No sector/thematic ETF confirmation is linked yet.", "Low")]}
    best = max(sector_hits, key=lambda item: item.confirmation_score)
    return {"score": round(float(best.confirmation_score), 1), "status": "confirmed_by_etf", "etf": best.ticker, "issues": []}


def historical_validation_quality(db: Session, asset: Asset) -> dict:
    signals = db.scalars(select(SignalSnapshot).where(SignalSnapshot.asset_id == asset.id).order_by(desc(SignalSnapshot.created_at)).limit(20)).all()
    if len(signals) < 2:
        return {"score": 50, "validated_signals": len(signals), "issues": [issue("signal_validation_sparse", "Not enough historical signal snapshots to validate lifecycle reliability.", "Low")]}
    confirmed = len([signal for signal in signals if signal.lifecycle_state in {"confirmed", "strengthening"}])
    score = round(55 + confirmed / len(signals) * 45, 1)
    return {"score": score, "validated_signals": len(signals), "confirmed_or_strengthening": confirmed, "issues": []}


def signal_validation_report(db: Session, limit: int = 240) -> dict:
    signals = db.scalars(select(SignalSnapshot).order_by(desc(SignalSnapshot.created_at)).limit(limit)).all()
    if not signals:
        return {
            "status": "empty",
            "validated_signals": 0,
            "message": "No signal snapshots are available for historical validation yet.",
            "by_classification": {},
            "by_lifecycle": {},
        }
    by_classification: dict[str, dict] = {}
    by_lifecycle: dict[str, int] = {}
    for signal in signals:
        bucket = by_classification.setdefault(signal.classification, {"count": 0, "avg_score": 0.0, "avg_confidence": 0.0})
        bucket["count"] += 1
        bucket["avg_score"] += float(signal.blum_score or 0)
        bucket["avg_confidence"] += float(signal.confidence_score or 0)
        by_lifecycle[signal.lifecycle_state] = by_lifecycle.get(signal.lifecycle_state, 0) + 1
    for bucket in by_classification.values():
        count = max(1, bucket["count"])
        bucket["avg_score"] = round(bucket["avg_score"] / count, 1)
        bucket["avg_confidence"] = round(bucket["avg_confidence"] / count, 1)
    confirmed = sum(by_lifecycle.get(item, 0) for item in ("confirmed", "strengthening"))
    degraded = sum(by_lifecycle.get(item, 0) for item in ("weakening", "failed"))
    validation_score = round((confirmed + 0.35 * (len(signals) - confirmed - degraded)) / max(1, len(signals)) * 100, 1)
    return {
        "status": "ready",
        "validated_signals": len(signals),
        "validation_score": validation_score,
        "confirmed_or_strengthening": confirmed,
        "weakening_or_failed": degraded,
        "by_classification": by_classification,
        "by_lifecycle": by_lifecycle,
        "methodology": (
            "This validates historical signal lifecycle consistency from stored snapshots. "
            "It does not claim future performance and does not generate investment recommendations."
        ),
    }


def latest_signal(db: Session, asset: Asset) -> SignalSnapshot | None:
    return db.scalar(select(SignalSnapshot).where(SignalSnapshot.asset_id == asset.id).order_by(desc(SignalSnapshot.created_at)).limit(1))


def linked_articles(db: Session, asset: Asset, limit: int) -> list[NewsArticle]:
    return db.scalars(
        select(NewsArticle)
        .join(NewsAssetLink, NewsAssetLink.article_id == NewsArticle.id)
        .where(NewsAssetLink.asset_id == asset.id)
        .order_by(desc(NewsArticle.published_at), desc(NewsArticle.created_at))
        .limit(limit)
    ).all()


def extract_events(text: str) -> list[str]:
    lowered = text.lower()
    return [event for event, keywords in EVENT_KEYWORDS.items() if any(keyword in lowered for keyword in keywords)]


def asset_aliases(asset: Asset) -> list[str]:
    words = [asset.ticker, asset.name, asset.name.replace(" Inc.", ""), asset.name.replace(" Corporation", ""), asset.sector, asset.industry]
    return list(dict.fromkeys([item.strip() for item in words if item and len(item.strip()) > 1]))


def confidence_label(score: float) -> str:
    if score >= 82:
        return "Very High"
    if score >= 68:
        return "High"
    if score >= 52:
        return "Medium"
    if score >= 35:
        return "Low"
    return "Insufficient"


def issue(code: str, message: str, severity: str) -> dict:
    return {"code": code, "message": message, "severity": severity}


def numeric(value) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def accuracy_contract() -> list[str]:
    return [
        "1 multi-provider price validation",
        "2 corporate-action review",
        "3 point-in-time consistency",
        "4 per-asset data quality score",
        "5 entity resolution",
        "6 source credibility",
        "7 semantic news deduplication",
        "8 structured event extraction",
        "9 confidence-aware AI reasoning",
        "10 contradiction engine",
        "11 fundamentals layer",
        "12 macro layer",
        "13 sector/ETF confirmation",
        "14 historical signal validation",
        "15 Blum Confidence Score",
    ]
