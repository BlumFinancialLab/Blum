from datetime import datetime

from app.services.performance import PerformanceRecorder, percentile


def test_percentile_uses_interpolated_rank():
    assert round(percentile([10, 20, 30, 40], 95), 2) == 38.5


def test_performance_recorder_builds_diagnostics():
    recorder = PerformanceRecorder()
    now = datetime.utcnow()
    recorder.mark_startup_begin()
    recorder.record_startup_phase("bootstrap_database", 125.0, {}, now)
    recorder.mark_startup_complete()
    recorder.record_api_request(method="GET", path="/assets/NVDA", status_code=200, duration_ms=44.0, started_at=now)
    recorder.record_api_request(method="GET", path="/dashboard/overview", status_code=200, duration_ms=180.0, started_at=now)
    recorder.record_db_query(statement="SELECT * FROM price_history WHERE ticker = 'NVDA'", duration_ms=75.0, rowcount=240, started_at=now)
    recorder.record_dashboard_widget("dashboard.market_pulse_counts", 32.0, {}, now)
    recorder.record_background_task("market_refresh", 250.0, {"status": "ok"}, now)
    recorder.record_cache_event("market_snapshot", hit=True)
    recorder.record_cache_event("market_snapshot", hit=False)

    payload = recorder.diagnostics()

    assert payload["api"]["request_count"] == 2
    assert payload["api"]["slowest_endpoints"][0]["path"] == "/dashboard/overview"
    assert payload["database"]["slowest_queries"][0]["rows_scanned_estimate"] == 240
    assert payload["dashboard_widgets"]["backend_widgets"][0]["name"] == "dashboard.market_pulse_counts"
    assert payload["background_tasks"]["slowest_tasks"][0]["name"] == "market_refresh"
    assert payload["cache"]["hit_rate"] == 0.5
    assert payload["top_10_bottlenecks"][0]["kind"] == "background"


def test_performance_recorder_exposes_learning_page_load_diagnostics():
    recorder = PerformanceRecorder()
    now = datetime.utcnow()
    recorder.record_frontend_widget("frontend.api.GET./api/learning-intelligence/summary", 120.0, {"status": "ok", "source": "fetchBlum"})
    recorder.record_frontend_widget("frontend.api.GET./api/trading-game/status", 0.4, {"status": "cache_hit", "source": "fetchBlum"})
    recorder.record_frontend_widget("frontend.api.GET./api/trading-game/status", 0.2, {"status": "deduped", "source": "fetchBlum"})
    recorder.record_dashboard_widget(
        "performance.heavy_recalculation_triggered_during_page_load",
        3400.0,
        {"method": "POST", "path": "/api/business-quality/recalculate", "referer": "https://example.test/learning"},
        now,
    )

    payload = recorder.diagnostics()
    summary = payload["initial_learning_page_load"]

    assert summary["frontend_request_count"] == 3
    assert summary["cache_hit_count"] == 1
    assert summary["duplicate_request_count"] == 1
    assert summary["heavy_post_calls_during_page_load"][0]["path"] == "/api/business-quality/recalculate"
