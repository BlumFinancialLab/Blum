from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import re
from statistics import mean

import feedparser
import requests
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import IPOCompany, IPOFiling, IPOScore, NewsArticle


settings = get_settings()

SEC_CURRENT_FORMS = ["S-1", "S-1/A", "F-1", "F-1/A", "424B1", "424B4"]
SEC_CURRENT_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
SEC_SOURCE = "SEC EDGAR current filings"
IPO_NEWS_KEYWORDS = [
    "ipo",
    "initial public offering",
    "files to go public",
    "go public",
    "direct listing",
    "listing",
    "prospectus",
    "market debut",
    "spac",
]

THEME_KEYWORDS = {
    "AI": ["ai", "artificial intelligence", "machine learning", "accelerator", "data center"],
    "Space": ["space", "satellite", "launch", "orbital", "aerospace"],
    "Cybersecurity": ["cyber", "security", "identity", "threat", "zero trust"],
    "Semiconductors": ["semiconductor", "chip", "silicon", "foundry", "gpu"],
    "Healthcare": ["biotech", "pharma", "clinical", "therapeutics", "medical"],
    "Energy Transition": ["clean energy", "solar", "battery", "hydrogen", "grid"],
    "Defense": ["defense", "missile", "drone", "weapons", "military"],
    "Fintech": ["payments", "banking", "fintech", "credit", "lending"],
    "Robotics": ["robot", "automation", "industrial automation", "autonomous"],
    "Crypto": ["bitcoin", "crypto", "blockchain", "digital asset"],
}

RISK_KEYWORDS = [
    "going concern",
    "material weakness",
    "no revenue",
    "substantial doubt",
    "litigation",
    "restatement",
    "volatile",
]


def update_ipo_radar(db: Session, limit_per_form: int = 60, forms: list[str] | None = None) -> dict:
    requested_forms = forms or SEC_CURRENT_FORMS
    inserted = 0
    duplicates = 0
    source_errors: list[dict] = []
    touched_company_ids: set[int] = set()

    for form_type in requested_forms:
        try:
            entries = fetch_sec_current_filings(form_type=form_type, count=limit_per_form)
        except Exception as exc:
            source_errors.append({"source": SEC_SOURCE, "form_type": form_type, "status": f"{type(exc).__name__}: {str(exc)}"})
            continue

        for entry in entries:
            parsed = parse_sec_entry(entry, form_type=form_type)
            if not parsed["accession_number"]:
                source_errors.append({"source": SEC_SOURCE, "form_type": form_type, "status": "missing_accession", "title": parsed["title"][:140]})
                continue

            company = upsert_ipo_company(db, parsed)
            touched_company_ids.add(company.id)
            existing = db.scalar(select(IPOFiling).where(IPOFiling.accession_number == parsed["accession_number"]))
            if existing:
                duplicates += 1
                continue

            filing = IPOFiling(
                company_id=company.id,
                cik=company.cik,
                company_name=company.name,
                form_type=parsed["form_type"],
                filing_date=parsed["filing_date"],
                title=parsed["title"],
                url=parsed["url"],
                accession_number=parsed["accession_number"],
                source=SEC_SOURCE,
                raw_payload=parsed["raw_payload"],
            )
            db.add(filing)
            db.flush()
            inserted += 1

    db.commit()

    scored = 0
    for company_id in touched_company_ids:
        company = db.get(IPOCompany, company_id)
        if company is None:
            continue
        score = score_ipo_company(db, company)
        if score:
            db.add(score)
            scored += 1
    db.commit()

    radar = ipo_radar(db, limit=max(80, limit_per_form))
    return {
        "status": "ready" if radar["summary"]["scored_companies"] else "waiting_for_sec_data",
        "data_mode": "real_public_sec_and_news_only",
        "source": SEC_SOURCE,
        "forms_requested": requested_forms,
        "inserted_filings": inserted,
        "duplicate_filings": duplicates,
        "companies_touched": len(touched_company_ids),
        "scores_created": scored,
        "source_errors": source_errors,
        "radar": radar,
    }


def ipo_radar(db: Session, limit: int = 80) -> dict:
    latest_scores = latest_scores_by_company(db, limit=limit)
    rows = [ipo_row(db, score) for score in latest_scores]
    rows = sorted(rows, key=lambda item: item["score"]["opportunity_score"], reverse=True)
    final_watch = [row for row in rows if row["score"]["classification"] == "Final Prospectus Watch"]
    advanced = [row for row in rows if row["score"]["readiness_score"] >= 62]
    narrative = [row for row in rows if row["score"]["narrative_heat_score"] >= 45]
    early = [row for row in rows if row["score"]["classification"] in {"Early Filing Watch", "Pre-Listing Evidence Watch"}]
    filings_count = int(db.scalar(select(func.count(IPOFiling.id))) or 0)
    company_count = int(db.scalar(select(func.count(IPOCompany.id))) or 0)
    latest_filing_at = db.scalar(select(func.max(IPOFiling.filing_date)))
    scores = [row["score"]["opportunity_score"] for row in rows]

    return {
        "status": "ready" if rows else "waiting_for_sec_data",
        "data_mode": "real_public_sec_and_news_only",
        "summary": {
            "companies_observed": company_count,
            "filings_observed": filings_count,
            "scored_companies": len(rows),
            "avg_opportunity_score": round(mean(scores), 2) if scores else 0,
            "top_opportunity_score": round(max(scores), 2) if scores else 0,
            "final_prospectus_count": len(final_watch),
            "advanced_filing_count": len(advanced),
            "narrative_watch_count": len(narrative),
            "latest_filing_at": latest_filing_at,
        },
        "sections": {
            "highest_opportunity": rows[:16],
            "final_prospectus_watch": final_watch[:16],
            "advanced_filing_watch": advanced[:16],
            "narrative_watch": narrative[:16],
            "early_filing_watch": early[:16],
        },
        "rows": rows,
        "prelisting_narratives": prelisting_narratives(db),
        "source_diagnostics": {
            "primary_source": SEC_SOURCE,
            "forms_tracked": SEC_CURRENT_FORMS,
            "news_keywords": IPO_NEWS_KEYWORDS,
            "data_policy": "No synthetic IPO candidates are generated. Empty sections mean no current public evidence was stored.",
        },
    }


def fetch_sec_current_filings(form_type: str, count: int) -> list[dict]:
    response = requests.get(
        SEC_CURRENT_URL,
        params={"action": "getcurrent", "type": form_type, "count": count, "output": "atom"},
        headers={"User-Agent": settings.sec_user_agent, "Accept-Encoding": "gzip, deflate", "Host": "www.sec.gov"},
        timeout=24,
    )
    response.raise_for_status()
    parsed = feedparser.parse(response.text)
    if getattr(parsed, "bozo", False) and not parsed.entries:
        raise ValueError(str(getattr(parsed, "bozo_exception", "invalid SEC Atom feed")))
    return list(parsed.entries)


def parse_sec_entry(entry: dict, form_type: str) -> dict:
    title = clean_text(getattr(entry, "title", "") or entry.get("title", ""))
    summary = clean_text(getattr(entry, "summary", "") or entry.get("summary", ""))
    url = entry_link(entry)
    filing_date = parse_datetime(
        getattr(entry, "updated", None)
        or getattr(entry, "published", None)
        or entry.get("updated")
        or entry.get("published")
    )
    company_name, cik = parse_company_identity(title, summary)
    accession = parse_accession(url) or stable_accession(form_type, title, url, filing_date)
    return {
        "company_name": company_name,
        "cik": cik,
        "form_type": form_type,
        "filing_date": filing_date,
        "title": title or f"{form_type} filing",
        "summary": summary,
        "url": url,
        "accession_number": accession,
        "raw_payload": {
            "title": title,
            "summary": summary,
            "url": url,
            "published": getattr(entry, "published", None) or entry.get("published"),
            "updated": getattr(entry, "updated", None) or entry.get("updated"),
            "source": SEC_SOURCE,
        },
    }


def upsert_ipo_company(db: Session, parsed: dict) -> IPOCompany:
    now = datetime.utcnow()
    company = None
    if parsed.get("cik"):
        company = db.scalar(select(IPOCompany).where(IPOCompany.cik == parsed["cik"], IPOCompany.name == parsed["company_name"]))
    if company is None:
        company = db.scalar(select(IPOCompany).where(IPOCompany.name == parsed["company_name"]))
    if company is None:
        company = IPOCompany(
            cik=parsed.get("cik"),
            name=parsed["company_name"],
            status="filing_observed",
            country="Unknown",
            sector=infer_sector(parsed["title"]),
            industry="Unknown",
            company_metadata={"themes": infer_themes(parsed["title"]), "first_observed_form": parsed["form_type"]},
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(company)
        db.flush()
    else:
        company.last_seen_at = now
        if not company.cik and parsed.get("cik"):
            company.cik = parsed["cik"]
        metadata = dict(company.company_metadata or {})
        themes = list(dict.fromkeys((metadata.get("themes") or []) + infer_themes(parsed["title"])))
        metadata["themes"] = themes
        metadata["last_observed_form"] = parsed["form_type"]
        company.company_metadata = metadata
        if company.sector == "Unknown":
            company.sector = infer_sector(parsed["title"])
    return company


def score_ipo_company(db: Session, company: IPOCompany) -> IPOScore | None:
    filings = db.scalars(
        select(IPOFiling)
        .where(IPOFiling.company_id == company.id)
        .order_by(desc(IPOFiling.filing_date).nullslast(), desc(IPOFiling.created_at))
    ).all()
    if not filings:
        return None

    latest = filings[0]
    forms = [filing.form_type.upper() for filing in filings]
    latest_form = latest.form_type.upper()
    amendments = len([form for form in forms if form.endswith("/A")])
    final_forms = len([form for form in forms if form in {"424B1", "424B4"}])
    days_since_latest = days_since(latest.filing_date)
    text = " ".join([company.name, latest.title, latest.raw_payload.get("summary", "")]).lower()
    themes = infer_themes(text)
    risk_terms = [term for term in RISK_KEYWORDS if term in text]

    readiness = 36
    if latest_form in {"S-1/A", "F-1/A"}:
        readiness = 56
    if latest_form == "424B1":
        readiness = 76
    if latest_form == "424B4":
        readiness = 90
    readiness += min(12, len(filings) * 2.4) + min(10, amendments * 2.6)
    readiness += recency_bonus(days_since_latest)
    readiness = clamp(readiness)

    listing_probability = 38 + min(18, len(filings) * 3.0) + min(16, amendments * 3.2) + recency_bonus(days_since_latest)
    if final_forms:
        listing_probability += 28
    if latest_form == "424B4":
        listing_probability += 10
    listing_probability = clamp(listing_probability)

    narrative_heat = min(100, len(themes) * 14 + headline_intensity(company.name) + (8 if "IPO" in latest.title.upper() else 0))
    valuation_risk = min(100, len(risk_terms) * 18)
    quality = 0
    quality += 28 if company.cik else 0
    quality += 18 if latest.url else 0
    quality += 18 if latest.filing_date else 0
    quality += 16 if latest.form_type else 0
    quality += min(20, len(filings) * 4)
    quality = clamp(quality)
    opportunity = clamp(
        readiness * 0.32
        + listing_probability * 0.28
        + narrative_heat * 0.18
        + quality * 0.12
        + (100 - valuation_risk) * 0.10
    )

    classification = classify_ipo(latest_form, readiness, narrative_heat, opportunity)
    explanation = (
        f"{company.name} surfaced from verified SEC filing evidence. Latest observed form is {latest_form}; "
        f"{len(filings)} tracked filings, {amendments} amendments and {final_forms} final prospectus filings are stored. "
        f"Readiness {readiness:.1f}, listing probability proxy {listing_probability:.1f}, narrative heat {narrative_heat:.1f}. "
        "The score is a research-priority signal, not an investment recommendation."
    )
    return IPOScore(
        company_id=company.id,
        filing_id=latest.id,
        readiness_score=round(readiness, 2),
        listing_probability_score=round(listing_probability, 2),
        narrative_heat_score=round(narrative_heat, 2),
        valuation_risk_score=round(valuation_risk, 2),
        quality_score=round(quality, 2),
        opportunity_score=round(opportunity, 2),
        classification=classification,
        time_horizon=ipo_horizon(latest_form),
        explanation=explanation,
        evidence={
            "latest_form": latest_form,
            "latest_filing_url": latest.url,
            "latest_filing_date": latest.filing_date.isoformat() if latest.filing_date else None,
            "filing_count": len(filings),
            "forms_observed": sorted(set(forms)),
            "amendment_count": amendments,
            "final_prospectus_count": final_forms,
            "themes": themes,
            "risk_terms_observed": risk_terms,
            "source": SEC_SOURCE,
            "data_policy": "The model only scores stored SEC/news evidence and does not invent listing dates, valuations or tickers.",
        },
    )


def latest_scores_by_company(db: Session, limit: int) -> list[IPOScore]:
    scores = db.scalars(select(IPOScore).order_by(desc(IPOScore.created_at), desc(IPOScore.opportunity_score)).limit(limit * 3)).all()
    latest: dict[int, IPOScore] = {}
    for score in scores:
        latest.setdefault(score.company_id, score)
        if len(latest) >= limit:
            break
    return list(latest.values())


def ipo_row(db: Session, score: IPOScore) -> dict:
    company = score.company
    filing = score.filing or db.scalar(
        select(IPOFiling)
        .where(IPOFiling.company_id == company.id)
        .order_by(desc(IPOFiling.filing_date).nullslast(), desc(IPOFiling.created_at))
        .limit(1)
    )
    return {
        "company": {
            "id": company.id,
            "name": company.name,
            "cik": company.cik,
            "ticker": company.ticker,
            "exchange": company.exchange,
            "country": company.country,
            "sector": company.sector,
            "industry": company.industry,
            "status": company.status,
            "metadata": company.company_metadata,
            "first_seen_at": company.first_seen_at,
            "last_seen_at": company.last_seen_at,
        },
        "latest_filing": filing_payload(filing),
        "score": score_payload(score),
    }


def filing_payload(filing: IPOFiling | None) -> dict | None:
    if filing is None:
        return None
    return {
        "form_type": filing.form_type,
        "filing_date": filing.filing_date,
        "title": filing.title,
        "url": filing.url,
        "accession_number": filing.accession_number,
        "source": filing.source,
    }


def score_payload(score: IPOScore) -> dict:
    return {
        "readiness_score": score.readiness_score,
        "listing_probability_score": score.listing_probability_score,
        "narrative_heat_score": score.narrative_heat_score,
        "valuation_risk_score": score.valuation_risk_score,
        "quality_score": score.quality_score,
        "opportunity_score": score.opportunity_score,
        "classification": score.classification,
        "time_horizon": score.time_horizon,
        "evidence": score.evidence,
        "explanation": score.explanation,
        "created_at": score.created_at,
    }


def prelisting_narratives(db: Session, limit: int = 20) -> list[dict]:
    filters = []
    for keyword in IPO_NEWS_KEYWORDS:
        pattern = f"%{keyword}%"
        filters.append(NewsArticle.title.ilike(pattern))
        filters.append(NewsArticle.summary.ilike(pattern))
    rows = db.scalars(
        select(NewsArticle)
        .where(or_(*filters))
        .order_by(desc(NewsArticle.published_at), desc(NewsArticle.created_at))
        .limit(limit)
    ).all()
    return [
        {
            "id": article.id,
            "source": article.source,
            "published_at": article.published_at,
            "title": article.title,
            "summary": article.summary,
            "url": article.url,
            "quality_score": article.quality_score,
            "theme_tags": article.theme_tags,
        }
        for article in rows
    ]


def parse_company_identity(title: str, summary: str) -> tuple[str, str | None]:
    text = title or summary
    match = re.search(r"^[A-Z0-9/-]+\s+-\s+(.+?)\s+\((\d{6,10})\)", text)
    if match:
        return clean_company_name(match.group(1)), match.group(2).zfill(10)
    cik_match = re.search(r"\((\d{6,10})\)", text)
    cik = cik_match.group(1).zfill(10) if cik_match else None
    without_form = re.sub(r"^[A-Z0-9/-]+\s+-\s+", "", text)
    without_cik = re.sub(r"\(\d{6,10}\).*", "", without_form)
    return clean_company_name(without_cik or "Unknown filer"), cik


def clean_company_name(value: str) -> str:
    value = clean_text(value)
    value = re.sub(r"\s+\((Filer|Subject|Filed by).*$", "", value, flags=re.IGNORECASE)
    return value[:260] or "Unknown filer"


def parse_accession(url: str) -> str | None:
    match = re.search(r"accession_number=([0-9-]+)", url)
    if match:
        return match.group(1)
    match = re.search(r"/([0-9]{10}-[0-9]{2}-[0-9]{6})", url)
    if match:
        return match.group(1)
    return None


def stable_accession(form_type: str, title: str, url: str, filing_date: datetime | None) -> str:
    raw = "|".join([form_type, title, url, filing_date.isoformat() if filing_date else ""])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def entry_link(entry: dict) -> str:
    links = getattr(entry, "links", None) or entry.get("links", [])
    for link in links:
        href = getattr(link, "href", None) or link.get("href")
        if href:
            return href
    return getattr(entry, "link", None) or entry.get("link", "")


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except Exception:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def infer_themes(text: str) -> list[str]:
    lower = (text or "").lower()
    themes = []
    for theme, keywords in THEME_KEYWORDS.items():
        if any(keyword in lower for keyword in keywords):
            themes.append(theme)
    return themes


def infer_sector(text: str) -> str:
    themes = infer_themes(text)
    if "Healthcare" in themes:
        return "Healthcare"
    if "Semiconductors" in themes or "AI" in themes:
        return "Technology"
    if "Energy Transition" in themes:
        return "Energy"
    if "Defense" in themes or "Space" in themes:
        return "Industrials"
    if "Fintech" in themes or "Crypto" in themes:
        return "Financials"
    return "Unknown"


def classify_ipo(latest_form: str, readiness: float, narrative_heat: float, opportunity: float) -> str:
    if latest_form == "424B4":
        return "Final Prospectus Watch"
    if latest_form == "424B1":
        return "Final Prospectus Watch"
    if opportunity >= 78 and narrative_heat >= 45:
        return "Narrative IPO Watch"
    if readiness >= 68:
        return "Advanced Filing Watch"
    if latest_form in {"S-1/A", "F-1/A"}:
        return "Amendment Velocity Watch"
    if latest_form in {"S-1", "F-1"}:
        return "Early Filing Watch"
    return "Pre-Listing Evidence Watch"


def ipo_horizon(latest_form: str) -> str:
    if latest_form in {"424B1", "424B4"}:
        return "Near-term IPO watch"
    if latest_form in {"S-1/A", "F-1/A"}:
        return "Short/medium-term IPO watch"
    return "Early-stage IPO research watch"


def days_since(value: datetime | None) -> int | None:
    if value is None:
        return None
    return max(0, (datetime.utcnow() - value).days)


def recency_bonus(days: int | None) -> float:
    if days is None:
        return 0
    if days <= 3:
        return 10
    if days <= 14:
        return 7
    if days <= 45:
        return 4
    return 0


def headline_intensity(company_name: str) -> float:
    tokens = [token for token in re.split(r"\W+", company_name.lower()) if len(token) >= 4]
    if not tokens:
        return 0
    return min(16, len(tokens) * 3)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, float(value)))
