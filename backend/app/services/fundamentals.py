from __future__ import annotations

from datetime import date, datetime

import requests
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Asset, FundamentalSnapshot


settings = get_settings()

CIK_MAP = {
    "AAPL": "0000320193",
    "MSFT": "0000789019",
    "NVDA": "0001045810",
    "AMD": "0000002488",
    "AVGO": "0001730168",
    "AMZN": "0001018724",
    "GOOGL": "0001652044",
    "META": "0001326801",
    "TSLA": "0001318605",
    "JPM": "0000019617",
    "XOM": "0000034088",
    "LLY": "0000059478",
    "NVO": "0000353278",
    "ASML": "0000937966",
    "SAP": "0001000184",
    "ORCL": "0001341439",
    "CRM": "0001108524",
    "NOW": "0001373715",
    "PLTR": "0001321655",
    "NFLX": "0001065280",
    "SMCI": "0001375365",
    "MU": "0000723125",
    "QCOM": "0000804328",
    "AMAT": "0000006951",
    "LRCX": "0000707549",
    "KLAC": "0000319201",
    "INTC": "0000050863",
    "IBM": "0000051143",
    "PANW": "0001327567",
    "CRWD": "0001535527",
    "UBER": "0001543151",
    "COST": "0000909832",
    "WMT": "0000104169",
    "HD": "0000354950",
    "BA": "0000012927",
    "CAT": "0000018230",
    "RTX": "0000101829",
    "LMT": "0000936468",
    "NOC": "0001133421",
    "UNH": "0000731766",
    "MRK": "0000310158",
    "ISRG": "0001035267",
    "V": "0001403161",
    "MA": "0001141391",
    "BAC": "0000070858",
    "GS": "0000886982",
}

SEC_METRICS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "net_income": ["NetIncomeLoss"],
    "operating_income": ["OperatingIncomeLoss"],
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "equity": ["StockholdersEquity"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "eps_diluted": ["EarningsPerShareDiluted"],
}


def update_fundamentals(db: Session, tickers: list[str] | None = None, limit: int = 20) -> dict:
    query = select(Asset).where(Asset.is_active.is_(True), Asset.asset_type == "Stock").order_by(Asset.ticker)
    if tickers:
        query = query.where(Asset.ticker.in_([ticker.upper() for ticker in tickers]))
    assets = db.scalars(query.limit(limit)).all()
    inserted = 0
    diagnostics = []
    for asset in assets:
        cik = CIK_MAP.get(asset.ticker)
        if not cik:
            diagnostics.append({"ticker": asset.ticker, "status": "missing_cik", "provider": "sec_companyfacts"})
            continue
        payload = fetch_companyfacts(cik)
        if not payload:
            diagnostics.append({"ticker": asset.ticker, "status": "source_unavailable", "provider": "sec_companyfacts"})
            continue
        metrics = extract_metrics(payload)
        if not metrics:
            diagnostics.append({"ticker": asset.ticker, "status": "no_metrics", "provider": "sec_companyfacts"})
            continue
        period_end = latest_period_end(metrics)
        existing = db.scalar(
            select(FundamentalSnapshot)
            .where(FundamentalSnapshot.asset_id == asset.id, FundamentalSnapshot.provider == "sec_companyfacts", FundamentalSnapshot.period_end == period_end)
            .limit(1)
        )
        quality = fundamental_quality(metrics)
        if existing:
            existing.metrics = metrics
            existing.quality_score = quality
            existing.created_at = datetime.utcnow()
        else:
            db.add(
                FundamentalSnapshot(
                    asset_id=asset.id,
                    ticker=asset.ticker,
                    provider="sec_companyfacts",
                    period_end=period_end,
                    fiscal_period=metrics.get("_latest_form", ""),
                    metrics=metrics,
                    quality_score=quality,
                )
            )
            inserted += 1
        diagnostics.append({"ticker": asset.ticker, "status": "ok", "quality_score": quality, "period_end": str(period_end)})
    db.commit()
    return {"inserted_or_updated": inserted, "assets_checked": len(assets), "diagnostics": diagnostics}


def fundamentals_for_asset(db: Session, asset: Asset) -> dict:
    snapshot = db.scalar(
        select(FundamentalSnapshot)
        .where(FundamentalSnapshot.asset_id == asset.id)
        .order_by(desc(FundamentalSnapshot.period_end), desc(FundamentalSnapshot.created_at))
        .limit(1)
    )
    if not snapshot:
        return {
            "status": "missing",
            "ticker": asset.ticker,
            "quality_score": 0,
            "provider": "sec_companyfacts",
            "latest_snapshot": None,
            "message": "No verified fundamental snapshot is stored for this asset yet.",
        }
    latest_snapshot = {
        "ticker": asset.ticker,
        "provider": snapshot.provider,
        "period_end": snapshot.period_end.isoformat() if snapshot.period_end else None,
        "quality_score": snapshot.quality_score,
        "metrics": snapshot.metrics,
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
    }
    return {
        "status": "ready",
        "ticker": asset.ticker,
        "provider": snapshot.provider,
        "period_end": snapshot.period_end.isoformat() if snapshot.period_end else None,
        "quality_score": snapshot.quality_score,
        "metrics": snapshot.metrics,
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "latest_snapshot": latest_snapshot,
    }


def fetch_companyfacts(cik: str) -> dict | None:
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik.zfill(10)}.json"
    headers = {"User-Agent": settings.sec_user_agent, "Accept": "application/json"}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def extract_metrics(payload: dict) -> dict:
    facts = payload.get("facts", {}).get("us-gaap", {})
    output = {"entity_name": payload.get("entityName"), "cik": payload.get("cik")}
    latest_form = ""
    latest_end = None
    for label, candidates in SEC_METRICS.items():
        point = latest_fact(facts, candidates)
        if not point:
            continue
        output[label] = {
            "value": point.get("val"),
            "unit": point.get("unit"),
            "fy": point.get("fy"),
            "fp": point.get("fp"),
            "form": point.get("form"),
            "filed": point.get("filed"),
            "end": point.get("end"),
        }
        if point.get("end") and (latest_end is None or point["end"] > latest_end):
            latest_end = point["end"]
            latest_form = point.get("form", "")
    output["_latest_period_end"] = latest_end
    output["_latest_form"] = latest_form
    output["_data_policy"] = "SEC companyfacts XBRL facts only. Missing metrics are not estimated."
    return output


def latest_fact(facts: dict, candidates: list[str]) -> dict | None:
    rows = []
    for concept in candidates:
        concept_payload = facts.get(concept)
        if not concept_payload:
            continue
        for unit, values in concept_payload.get("units", {}).items():
            for value in values:
                if value.get("val") is None or not value.get("end"):
                    continue
                item = dict(value)
                item["unit"] = unit
                item["concept"] = concept
                rows.append(item)
    if not rows:
        return None
    rows.sort(key=lambda item: (item.get("end") or "", item.get("filed") or ""), reverse=True)
    return rows[0]


def latest_period_end(metrics: dict) -> date | None:
    value = metrics.get("_latest_period_end")
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except Exception:
        return None


def fundamental_quality(metrics: dict) -> float:
    available = [key for key in SEC_METRICS if key in metrics]
    score = min(100, len(available) / max(1, len(SEC_METRICS)) * 100)
    if metrics.get("revenue") and metrics.get("net_income") and metrics.get("assets"):
        score = max(score, 72)
    return round(score, 1)
