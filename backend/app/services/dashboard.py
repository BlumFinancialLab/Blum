from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import Asset, ETFTrend, NewsArticle, PriceHistory, SentimentAnalysis, SignalSnapshot
from app.services.accuracy import latest_accuracy_snapshot, market_accuracy_overview, signal_validation_report
from app.services.data_continuity import data_coverage_report
from app.services.dashboard_snapshots import DashboardSnapshotService
from app.services.macro import macro_overview
from app.services.market_data import market_snapshot_for_asset
from app.services.performance import performance_recorder
from app.services.pipeline import pipeline_readiness
from app.services.realtime import realtime_status


def dashboard_overview(db: Session) -> dict:
    with performance_recorder.dashboard_widget("dashboard.snapshot_lookup", snapshot_type="dashboard_overview_summary"):
        snapshot = DashboardSnapshotService().latest(db, "dashboard_overview_summary")
    if snapshot["payload"]:
        payload = dict(snapshot["payload"])
        payload["snapshot_status"] = snapshot["status"]
        payload["snapshot_created_at"] = snapshot.get("created_at")
        payload["snapshot_warnings"] = snapshot.get("warnings", [])
        payload["runtime_policy"] = "snapshot_first_no_live_recalculation"
        return payload
    return empty_dashboard_overview(snapshot)


def build_dashboard_overview_live(db: Session) -> dict:
    with performance_recorder.dashboard_widget("dashboard.load_signal_candidates"):
        signals = db.scalars(select(SignalSnapshot).order_by(desc(SignalSnapshot.created_at), desc(SignalSnapshot.blum_score)).limit(80)).all()
    with performance_recorder.dashboard_widget("dashboard.rank_latest_signals", signal_count=len(signals)):
        latest_by_ticker = {}
        for signal in signals:
            latest_by_ticker.setdefault(signal.ticker, signal)
        top = sorted(latest_by_ticker.values(), key=lambda item: item.blum_score, reverse=True)[:12]
        classifications = {}
        for signal in latest_by_ticker.values():
            classifications[signal.classification] = classifications.get(signal.classification, 0) + 1
    with performance_recorder.dashboard_widget("dashboard.market_pulse_counts"):
        sentiment_avg = db.scalar(select(func.avg(SentimentAnalysis.score))) or 0
        article_count = db.scalar(select(func.count(NewsArticle.id))) or 0
        asset_count = db.scalar(select(func.count(Asset.id))) or 0
        price_row_count = int(db.scalar(select(func.count(PriceHistory.id))) or 0)
    with performance_recorder.dashboard_widget("dashboard.etf_rotation_query"):
        etf_trends = db.execute(
            select(ETFTrend, Asset)
            .join(Asset, Asset.id == ETFTrend.asset_id)
            .order_by(desc(ETFTrend.created_at), desc(ETFTrend.confirmation_score))
            .limit(10)
        ).all()
    with performance_recorder.dashboard_widget("dashboard.data_coverage"):
        data_coverage = data_coverage_report(db)
    with performance_recorder.dashboard_widget("dashboard.accuracy"):
        accuracy = market_accuracy_overview(db, persist=False)
    with performance_recorder.dashboard_widget("dashboard.macro"):
        macro = macro_overview(db)
    with performance_recorder.dashboard_widget("dashboard.validation"):
        validation = signal_validation_report(db)
    with performance_recorder.dashboard_widget("dashboard.readiness"):
        readiness = pipeline_readiness(db)
    with performance_recorder.dashboard_widget("dashboard.realtime_status"):
        realtime = realtime_status()
    with performance_recorder.dashboard_widget("dashboard.signal_payloads", signal_count=len(top)):
        strongest = [signal_payload(item, db) for item in top]
        narrative_breakouts = [signal_payload(item, db) for item in top if item.classification == "Narrative Breakout"]
        technical_breakouts = [signal_payload(item, db) for item in top if item.classification == "Technical Breakout"]
        sentiment_divergence = [signal_payload(item, db) for item in top if item.classification == "Sentiment Divergence"]
        watchlist_candidates = [signal_payload(item, db) for item in top if item.classification in {"Strong Watch", "Watch"}]
    with performance_recorder.dashboard_widget("dashboard.etf_payloads", etf_count=len(etf_trends)):
        etf_rotation_leaders = [etf_payload(item, asset, db) for item, asset in etf_trends]
    return {
        "market_pulse": {
            "asset_count": asset_count,
            "article_count": article_count,
            "average_sentiment": round(float(sentiment_avg), 4),
            "signal_count": len(latest_by_ticker),
            "classification_mix": classifications,
            "price_row_count": price_row_count,
        },
        "data_coverage": data_coverage,
        "accuracy": accuracy,
        "macro": macro,
        "validation": validation,
        "readiness": readiness,
        "realtime": realtime,
        "todays_strongest_signals": strongest,
        "narrative_breakouts": narrative_breakouts,
        "technical_breakouts": technical_breakouts,
        "sentiment_divergence": sentiment_divergence,
        "watchlist_candidates": watchlist_candidates,
        "etf_rotation_leaders": etf_rotation_leaders,
    }


def empty_dashboard_overview(snapshot: dict) -> dict:
    return {
        "snapshot_status": snapshot.get("status", "missing"),
        "snapshot_created_at": snapshot.get("created_at"),
        "snapshot_warnings": [snapshot.get("warning") or "dashboard_overview_summary snapshot is not ready"],
        "runtime_policy": "snapshot_first_no_live_recalculation",
        "market_pulse": {
            "asset_count": 0,
            "article_count": 0,
            "average_sentiment": 0,
            "signal_count": 0,
            "classification_mix": {},
            "price_row_count": 0,
        },
        "data_coverage": {"status": "missing_snapshot"},
        "accuracy": {"status": "missing_snapshot"},
        "macro": {"status": "missing_snapshot"},
        "validation": {"status": "missing_snapshot"},
        "readiness": {"status": "missing_snapshot"},
        "realtime": {"status": "unknown"},
        "todays_strongest_signals": [],
        "narrative_breakouts": [],
        "technical_breakouts": [],
        "sentiment_divergence": [],
        "watchlist_candidates": [],
        "etf_rotation_leaders": [],
    }


def signal_payload(signal: SignalSnapshot, db: Session | None = None) -> dict:
    with performance_recorder.dashboard_widget("dashboard.signal_payload", ticker=signal.ticker):
        payload = {
            "ticker": signal.ticker,
            "classification": signal.classification,
            "blum_score": signal.blum_score,
            "risk_level": signal.risk_level,
            "time_horizon": signal.time_horizon,
            "score_version": signal.score_version,
            "confidence_score": signal.confidence_score,
            "lifecycle_state": signal.lifecycle_state,
            "score_breakdown": signal.score_breakdown,
            "explanation": signal.explanation,
            "watch_points": signal.watch_points,
            "created_at": signal.created_at,
        }
        if db is not None and signal.asset is not None:
            payload["accuracy"] = latest_accuracy_snapshot(db, ticker=signal.asset.ticker, scope="asset")
            payload["asset"] = {
                "ticker": signal.asset.ticker,
                "name": signal.asset.name,
                "category": signal.asset.category,
                "sector": signal.asset.sector,
                "industry": signal.asset.industry,
                "country": signal.asset.country,
                "asset_type": signal.asset.asset_type,
                "currency": signal.asset.currency,
                "exchange": signal.asset.exchange,
                "description": signal.asset.description,
            }
            payload["market_snapshot"] = market_snapshot_for_asset(db, signal.asset)
        return payload


def etf_payload(item: ETFTrend, asset: Asset, db: Session) -> dict:
    with performance_recorder.dashboard_widget("dashboard.etf_payload", ticker=item.ticker):
        return {
            "ticker": item.ticker,
            "category": item.category,
            "asset": {
                "ticker": asset.ticker,
                "name": asset.name,
                "category": asset.category,
                "sector": asset.sector,
                "industry": asset.industry,
                "country": asset.country,
                "asset_type": asset.asset_type,
                "currency": asset.currency,
                "exchange": asset.exchange,
                "description": asset.description,
            },
            "market_snapshot": market_snapshot_for_asset(db, asset),
            "momentum_score": item.momentum_score,
            "thematic_score": item.thematic_score,
            "confirmation_score": item.confirmation_score,
        }
