from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

import requests
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import ExternalDatasetSource, LearningEvent


DATASETS_SERVER = "https://datasets-server.huggingface.co"
HF_DATASET_URL = "https://huggingface.co/datasets"


CURATED_HF_DATASETS = [
    {
        "dataset_id": "defeatbeta/yahoo-finance-data",
        "title": "Yahoo Finance data, stock news and earnings call transcripts",
        "primary_domain": "multi_source_finance",
        "data_domains": ["market_data", "stock_news", "earnings_transcripts", "treasury_data"],
        "license": "odc-by",
        "priority": 98,
        "ingestion_mode": "metadata_and_incremental_evidence",
        "usage_policy": "Public dataset metadata is cataloged automatically. Large table ingestion must remain incremental and evidence-tracked.",
    },
    {
        "dataset_id": "paperswithbacktest/Stocks-Daily-Price",
        "title": "Daily price data for 7000+ US stocks",
        "primary_domain": "historical_prices",
        "data_domains": ["daily_ohlcv", "us_equities", "backtest_history"],
        "license": "other",
        "priority": 94,
        "ingestion_mode": "metadata_first_price_backfill_candidate",
        "usage_policy": "Use as a candidate for historical OHLCV backfill after schema validation. No synthetic prices are created.",
    },
    {
        "dataset_id": "TeraflopAI/SEC-EDGAR",
        "title": "Large-scale SEC EDGAR filings corpus",
        "primary_domain": "filings",
        "data_domains": ["sec_filings", "10k", "10q", "risk_factors", "management_discussion"],
        "license": "apache-2.0",
        "priority": 92,
        "ingestion_mode": "catalog_and_targeted_retrieval",
        "usage_policy": "Very large corpus. The Space should retrieve targeted company evidence rather than materializing the full corpus.",
    },
    {
        "dataset_id": "kurry/sp500_earnings_transcripts",
        "title": "S&P 500 and US large-cap earnings transcripts from 2005 to 2025",
        "primary_domain": "earnings_transcripts",
        "data_domains": ["earnings_calls", "management_language", "guidance", "sentiment"],
        "license": "mit",
        "priority": 90,
        "ingestion_mode": "metadata_first_transcript_retrieval",
        "usage_policy": "Use for company narrative history and management tone. Respect dataset license and avoid fabricating missing transcripts.",
    },
    {
        "dataset_id": "glopardo/sp500-earnings-transcripts",
        "title": "S&P 500 earnings call transcripts and quarterly context",
        "primary_domain": "earnings_transcripts",
        "data_domains": ["earnings_calls", "question_answering", "summarization", "retrieval"],
        "license": "unknown",
        "priority": 82,
        "ingestion_mode": "metadata_first_transcript_retrieval",
        "usage_policy": "Secondary transcript source for cross-source validation.",
    },
    {
        "dataset_id": "paperswithbacktest/Stocks-Quarterly-Earnings",
        "title": "Quarterly earnings reports for 7000+ US stocks",
        "primary_domain": "fundamentals",
        "data_domains": ["quarterly_earnings", "fundamentals", "us_equities"],
        "license": "other",
        "priority": 78,
        "ingestion_mode": "gated_metadata_only",
        "usage_policy": "Gated source. Catalog only unless access is explicitly available.",
    },
    {
        "dataset_id": "c3po-ai/edgar-corpus",
        "title": "Annual SEC 10-K filing corpus from 1993 to 2020",
        "primary_domain": "filings",
        "data_domains": ["10k", "sec_filings", "long_document_understanding"],
        "license": "apache-2.0",
        "priority": 75,
        "ingestion_mode": "catalog_and_targeted_retrieval",
        "usage_policy": "Historical filing text source for long-term company memory.",
    },
    {
        "dataset_id": "PatronusAI/financebench",
        "title": "FinanceBench open-book financial QA benchmark",
        "primary_domain": "reasoning_benchmark",
        "data_domains": ["financial_qa", "reasoning_evaluation", "open_book_benchmark"],
        "license": "cc-by-nc-4.0",
        "priority": 68,
        "ingestion_mode": "evaluation_only",
        "usage_policy": "Use for evaluation ideas and benchmark structure, not for commercial training unless license allows it.",
    },
    {
        "dataset_id": "BUPT-Reasoning-Lab/FinanceReasoning",
        "title": "Finance reasoning dataset",
        "primary_domain": "reasoning_benchmark",
        "data_domains": ["financial_reasoning", "thesis_quality", "reasoning_evaluation"],
        "license": "cc-by-4.0",
        "priority": 66,
        "ingestion_mode": "evaluation_only",
        "usage_policy": "Use to benchmark reasoning style; Blum proprietary reasoning remains separate.",
    },
    {
        "dataset_id": "jlh-ibm/earnings_call",
        "title": "Earnings call transcripts with stock and sector price context",
        "primary_domain": "earnings_transcripts",
        "data_domains": ["earnings_calls", "stock_prices", "sector_index"],
        "license": "cc0-1.0",
        "priority": 64,
        "ingestion_mode": "metadata_first_small_reference",
        "usage_policy": "Useful as a small validation corpus for transcript and price-link logic.",
    },
    {
        "dataset_id": "younginpiniti/us-stocks-daily-all",
        "title": "US stocks daily historical dataset",
        "primary_domain": "historical_prices",
        "data_domains": ["daily_ohlcv", "us_equities"],
        "license": "unknown",
        "priority": 63,
        "ingestion_mode": "metadata_first_price_backfill_candidate",
        "usage_policy": "Candidate source for redundant daily OHLCV validation after schema inspection.",
    },
    {
        "dataset_id": "sfd-anonymous/edgar-forecast-benchmark",
        "title": "EDGAR grounded numerical forecasting benchmark",
        "primary_domain": "reasoning_benchmark",
        "data_domains": ["sec_filings", "forecasting_benchmark", "numerical_reasoning"],
        "license": "cc-by-4.0",
        "priority": 60,
        "ingestion_mode": "evaluation_only",
        "usage_policy": "Use to evaluate grounded reasoning, not as direct trading signal evidence.",
    },
]


def refresh_huggingface_dataset_catalog(db: Session, validate: bool = True) -> dict:
    upserted = 0
    validation = []
    for item in CURATED_HF_DATASETS:
        dataset_id = item["dataset_id"]
        status_payload = validate_dataset(dataset_id) if validate else {"status": "not_checked"}
        source = db.scalar(select(ExternalDatasetSource).where(ExternalDatasetSource.dataset_id == dataset_id))
        payload = {
            "provider": "hugging_face",
            "title": item["title"],
            "primary_domain": item["primary_domain"],
            "data_domains": {"items": item["data_domains"]},
            "license": item["license"],
            "priority": item["priority"],
            "ingestion_mode": item["ingestion_mode"],
            "status": source_status(status_payload),
            "dataset_url": f"{HF_DATASET_URL}/{dataset_id}",
            "viewer_status": status_payload,
            "parquet_files": status_payload.get("parquet_files", {}),
            "size_summary": status_payload.get("size", {}),
            "usage_policy": {"policy": item["usage_policy"], "no_synthetic_data": True},
            "last_checked_at": datetime.utcnow(),
        }
        if source is None:
            source = ExternalDatasetSource(dataset_id=dataset_id, **payload)
            db.add(source)
        else:
            for key, value in payload.items():
                setattr(source, key, value)
        upserted += 1
        validation.append({"dataset_id": dataset_id, "status": payload["status"], "priority": item["priority"]})
    db.add(
        LearningEvent(
            event_type="huggingface_dataset_catalog_refresh",
            severity="Info",
            title="Hugging Face financial dataset catalog refreshed",
            description="Blum refreshed its catalog of real public datasets for market data, filings, earnings and reasoning benchmarks.",
            payload={"sources_seen": len(CURATED_HF_DATASETS), "validation": validation},
        )
    )
    db.commit()
    return {"status": "ok", "sources_upserted": upserted, "validation": validation}


def dataset_catalog_status(db: Session, limit: int = 80) -> dict:
    rows = db.scalars(select(ExternalDatasetSource).order_by(ExternalDatasetSource.priority.desc(), desc(ExternalDatasetSource.updated_at)).limit(limit)).all()
    ready = [row for row in rows if row.status in {"viewer_ready", "metadata_ready"}]
    by_domain: dict[str, int] = {}
    for row in rows:
        by_domain[row.primary_domain] = by_domain.get(row.primary_domain, 0) + 1
    return {
        "status": "ready" if rows else "not_initialized",
        "source_count": len(rows),
        "ready_count": len(ready),
        "domains": by_domain,
        "sources": [serialize_source(row) for row in rows],
        "policy": "Cataloged Hugging Face datasets are real public sources. Large datasets are validated and ingested incrementally, not copied blindly.",
    }


def validate_dataset(dataset_id: str) -> dict:
    encoded = quote(dataset_id, safe="")
    payload = {"dataset_id": dataset_id}
    payload["is_valid"] = get_json(f"{DATASETS_SERVER}/is-valid?dataset={encoded}")
    payload["splits"] = get_json(f"{DATASETS_SERVER}/splits?dataset={encoded}")
    payload["parquet_files"] = slim_parquet(get_json(f"{DATASETS_SERVER}/parquet?dataset={encoded}"))
    payload["size"] = get_json(f"{DATASETS_SERVER}/size?dataset={encoded}")
    return payload


def get_json(url: str) -> dict:
    try:
        response = requests.get(url, timeout=4)
        if response.status_code >= 400:
            return {"status": "error", "status_code": response.status_code, "detail": response.text[:240]}
        return response.json()
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


def slim_parquet(payload: dict) -> dict:
    files = payload.get("parquet_files") if isinstance(payload, dict) else None
    if not isinstance(files, list):
        return payload
    return {
        "status": "ok",
        "file_count": len(files),
        "sample_files": files[:8],
    }


def source_status(payload: dict) -> str:
    valid = payload.get("is_valid", {})
    splits = payload.get("splits", {})
    parquet = payload.get("parquet_files", {})
    if isinstance(valid, dict) and valid.get("valid") is False:
        return "unavailable"
    if isinstance(parquet, dict) and parquet.get("file_count", 0) > 0:
        return "viewer_ready"
    if isinstance(splits, dict) and splits.get("splits"):
        return "metadata_ready"
    if any(isinstance(payload.get(key), dict) and payload[key].get("status") == "error" for key in ["is_valid", "splits", "parquet_files", "size"]):
        return "metadata_partial"
    return "discovered"


def serialize_source(row: ExternalDatasetSource) -> dict:
    return {
        "dataset_id": row.dataset_id,
        "title": row.title,
        "primary_domain": row.primary_domain,
        "data_domains": row.data_domains,
        "license": row.license,
        "priority": row.priority,
        "ingestion_mode": row.ingestion_mode,
        "status": row.status,
        "dataset_url": row.dataset_url,
        "viewer_status": row.viewer_status,
        "parquet_files": row.parquet_files,
        "size_summary": row.size_summary,
        "usage_policy": row.usage_policy,
        "last_checked_at": row.last_checked_at.isoformat() if row.last_checked_at else None,
    }
