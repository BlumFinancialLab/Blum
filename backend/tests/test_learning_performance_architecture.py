from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    BlumTradingPowerScore,
    DashboardSnapshot,
    LearningBenchmarkComparison,
    LearningRun,
    TradingCapitalCycle,
    TradingGame,
)
from app.services.dashboard_snapshots import DashboardSnapshotService
from app.services.learning_summary import LearningSummaryService, build_truth_panel, safe_progress, summarize_benchmarks


def test_safe_progress_handles_partial_data():
    assert safe_progress(None, 10000) is None
    assert safe_progress(50, 100) == 0.5
    assert safe_progress(200, 100) == 1


def test_summarize_benchmarks_returns_partial_status():
    payload = summarize_benchmarks([])
    assert payload["status"] == "initializing"
    assert payload["major_benchmarks"]["SPY"]["result_label"] == "insufficient_sample"


def test_truth_panel_is_honest_when_power_missing():
    rows = build_truth_panel(None, summarize_benchmarks([]), ["No benchmark summary."], [])
    assert rows[0].startswith("Not enough precomputed evidence")
    assert any("No benchmark summary" in row for row in rows)


def test_learning_summary_returns_partial_payload_without_precomputed_rows():
    engine = create_engine("sqlite:///:memory:", future=True)
    for model in [
        BlumTradingPowerScore,
        DashboardSnapshot,
        LearningBenchmarkComparison,
        LearningRun,
        TradingCapitalCycle,
        TradingGame,
    ]:
        model.__table__.create(bind=engine)

    with Session(engine) as db:
        payload = LearningSummaryService().summary(db)

    assert payload["status"] == "initializing"
    assert "trading_power_score" in payload["missing_sections"]
    assert payload["truth_panel"][0].startswith("Not enough precomputed evidence")


def test_dashboard_snapshot_round_trip_and_stale_flag():
    engine = create_engine("sqlite:///:memory:", future=True)
    DashboardSnapshot.__table__.create(bind=engine)
    service = DashboardSnapshotService()
    with Session(engine) as db:
        written = service.write(db, "learning_summary", {"status": "ready"}, ttl_seconds=1)
        assert written["status"] == "ready"
        latest = service.latest(db, "learning_summary")
        assert latest["payload"]["status"] == "ready"
        row = db.get(DashboardSnapshot, 1)
        row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
        stale = service.latest(db, "learning_summary")
        assert stale["status"] == "stale"
