from __future__ import annotations

from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import json
import logging
import re
import threading
import time
from typing import Any, Iterable


PERFORMANCE_LOGGER = logging.getLogger("blum.performance")
MAX_EVENTS = 2500
MAX_QUERIES = 5000
MAX_STARTUP_PHASES = 200


@dataclass
class TimedBlock:
    recorder: "PerformanceRecorder"
    kind: str
    name: str
    metadata: dict[str, Any] | None = None

    def __enter__(self):
        self.started_at = time.perf_counter()
        self.wall_started_at = datetime.utcnow()
        return self

    def __exit__(self, exc_type, exc, traceback):
        duration_ms = (time.perf_counter() - self.started_at) * 1000
        metadata = dict(self.metadata or {})
        if exc is not None:
            metadata["status"] = "error"
            metadata["error"] = f"{exc_type.__name__}: {exc}" if exc_type else str(exc)
        if self.kind == "startup":
            self.recorder.record_startup_phase(self.name, duration_ms, metadata, self.wall_started_at)
        elif self.kind == "background":
            self.recorder.record_background_task(self.name, duration_ms, metadata, self.wall_started_at)
        elif self.kind == "dashboard_widget":
            self.recorder.record_dashboard_widget(self.name, duration_ms, metadata, self.wall_started_at)
        return False


class PerformanceRecorder:
    def __init__(self) -> None:
        self.process_started_at = datetime.utcnow()
        self.startup_started_at: datetime | None = None
        self.startup_completed_at: datetime | None = None
        self._lock = threading.RLock()
        self._api_events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
        self._db_events: deque[dict[str, Any]] = deque(maxlen=MAX_QUERIES)
        self._background_events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
        self._widget_events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
        self._startup_phases: deque[dict[str, Any]] = deque(maxlen=MAX_STARTUP_PHASES)
        self._cache_hits = 0
        self._cache_misses = 0
        self._frontend_widget_events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)

    def mark_startup_begin(self) -> None:
        with self._lock:
            self.startup_started_at = datetime.utcnow()
            self.startup_completed_at = None
        self._structured_log("startup_begin", {"started_at": self.startup_started_at.isoformat()})

    def mark_startup_complete(self) -> None:
        with self._lock:
            self.startup_completed_at = datetime.utcnow()
            started = self.startup_started_at or self.process_started_at
            duration_ms = (self.startup_completed_at - started).total_seconds() * 1000
        self._structured_log("startup_complete", {"duration_ms": round(duration_ms, 3)})

    def startup_phase(self, name: str, **metadata: Any) -> TimedBlock:
        return TimedBlock(self, "startup", name, metadata)

    def background_task(self, name: str, **metadata: Any) -> TimedBlock:
        return TimedBlock(self, "background", name, metadata)

    def dashboard_widget(self, name: str, **metadata: Any) -> TimedBlock:
        return TimedBlock(self, "dashboard_widget", name, metadata)

    def record_api_request(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        started_at: datetime,
        query_string: str = "",
        client: str = "",
    ) -> None:
        event = {
            "event_type": "api_request",
            "method": method,
            "path": normalize_path(path),
            "raw_path": path,
            "query_string": query_string[:250],
            "status_code": status_code,
            "duration_ms": round(duration_ms, 3),
            "started_at": started_at.isoformat(),
            "client": client,
        }
        with self._lock:
            self._api_events.append(event)
        self._structured_log("api_request", event)

    def record_db_query(
        self,
        *,
        statement: str,
        duration_ms: float,
        rowcount: int | None,
        started_at: datetime,
        parameters: Any = None,
        error: str | None = None,
    ) -> None:
        sql = compact_sql(statement)
        event = {
            "event_type": "db_query",
            "sql": sql,
            "operation": sql.split(" ", 1)[0].upper() if sql else "UNKNOWN",
            "duration_ms": round(duration_ms, 3),
            "started_at": started_at.isoformat(),
            "rowcount": rowcount if rowcount is not None and rowcount >= 0 else None,
            "rows_scanned_estimate": rowcount if rowcount is not None and rowcount >= 0 else None,
            "rows_scanned_note": (
                "Exact scanned rows require EXPLAIN/ANALYZE and are not available from the DBAPI cursor. "
                "This field uses returned/affected rowcount when the driver exposes it."
            ),
            "parameter_shape": summarize_parameters(parameters),
        }
        if error:
            event["error"] = error
        with self._lock:
            self._db_events.append(event)
        self._structured_log("db_query", event)

    def record_startup_phase(self, name: str, duration_ms: float, metadata: dict[str, Any] | None = None, started_at: datetime | None = None) -> None:
        event = {
            "event_type": "startup_phase",
            "name": name,
            "duration_ms": round(duration_ms, 3),
            "started_at": (started_at or datetime.utcnow()).isoformat(),
            "metadata": metadata or {},
        }
        with self._lock:
            self._startup_phases.append(event)
        self._structured_log("startup_phase", event)

    def record_background_task(self, name: str, duration_ms: float, metadata: dict[str, Any] | None = None, started_at: datetime | None = None) -> None:
        event = {
            "event_type": "background_task",
            "name": name,
            "duration_ms": round(duration_ms, 3),
            "started_at": (started_at or datetime.utcnow()).isoformat(),
            "metadata": metadata or {},
        }
        with self._lock:
            self._background_events.append(event)
        self._structured_log("background_task", event)

    def record_dashboard_widget(self, name: str, duration_ms: float, metadata: dict[str, Any] | None = None, started_at: datetime | None = None) -> None:
        event = {
            "event_type": "dashboard_widget",
            "name": name,
            "duration_ms": round(duration_ms, 3),
            "started_at": (started_at or datetime.utcnow()).isoformat(),
            "metadata": metadata or {},
        }
        with self._lock:
            self._widget_events.append(event)
        self._structured_log("dashboard_widget", event)

    def record_frontend_widget(self, name: str, duration_ms: float, metadata: dict[str, Any] | None = None) -> None:
        event = {
            "event_type": "frontend_widget",
            "name": name,
            "duration_ms": round(duration_ms, 3),
            "started_at": datetime.utcnow().isoformat(),
            "metadata": metadata or {},
        }
        with self._lock:
            self._frontend_widget_events.append(event)
        self._structured_log("frontend_widget", event)

    def record_cache_event(self, name: str, hit: bool, metadata: dict[str, Any] | None = None) -> None:
        with self._lock:
            if hit:
                self._cache_hits += 1
            else:
                self._cache_misses += 1
        self._structured_log("cache_event", {"name": name, "hit": hit, "metadata": metadata or {}})

    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            api_events = list(self._api_events)
            db_events = list(self._db_events)
            background_events = list(self._background_events)
            widget_events = list(self._widget_events)
            frontend_widget_events = list(self._frontend_widget_events)
            startup_phases = list(self._startup_phases)
            cache_hits = self._cache_hits
            cache_misses = self._cache_misses
            startup_started_at = self.startup_started_at
            startup_completed_at = self.startup_completed_at

        api_durations = [event["duration_ms"] for event in api_events]
        db_durations = [event["duration_ms"] for event in db_events]
        background_durations = [event["duration_ms"] for event in background_events]
        widget_durations = [event["duration_ms"] for event in widget_events + frontend_widget_events]
        cache_total = cache_hits + cache_misses

        return {
            "generated_at": datetime.utcnow().isoformat(),
            "policy": "Performance Diagnostics measures timing only. No optimization is applied by this layer.",
            "process_started_at": self.process_started_at.isoformat(),
            "startup": {
                "started_at": startup_started_at.isoformat() if startup_started_at else None,
                "completed_at": startup_completed_at.isoformat() if startup_completed_at else None,
                "total_duration_ms": round((startup_completed_at - startup_started_at).total_seconds() * 1000, 3) if startup_started_at and startup_completed_at else None,
                "phases": sorted(startup_phases, key=lambda item: item["duration_ms"], reverse=True),
            },
            "api": {
                "request_count": len(api_events),
                "average_response_ms": round(mean(api_durations), 3),
                "p95_response_ms": round(percentile(api_durations, 95), 3),
                "slowest_endpoints": aggregate_events(api_events, keys=("method", "path"))[:20],
                "slowest_endpoint_events": sorted(api_events, key=lambda item: item["duration_ms"], reverse=True)[:20],
            },
            "database": {
                "query_count": len(db_events),
                "average_query_ms": round(mean(db_durations), 3),
                "p95_query_ms": round(percentile(db_durations, 95), 3),
                "slowest_queries": sorted(db_events, key=lambda item: item["duration_ms"], reverse=True)[:30],
                "slowest_query_fingerprints": aggregate_sql(db_events)[:20],
                "rows_scanned_policy": (
                    "DBAPI timing is exact, but rows scanned are not exact without running EXPLAIN. "
                    "The diagnostics expose cursor rowcount when available and mark unknown scans as null."
                ),
            },
            "dashboard_widgets": {
                "event_count": len(widget_events) + len(frontend_widget_events),
                "average_widget_ms": round(mean(widget_durations), 3),
                "p95_widget_ms": round(percentile(widget_durations, 95), 3),
                "backend_widgets": aggregate_events(widget_events, keys=("name",))[:20],
                "frontend_widgets": aggregate_events(frontend_widget_events, keys=("name",))[:20],
                "slowest_widget_events": sorted(widget_events + frontend_widget_events, key=lambda item: item["duration_ms"], reverse=True)[:20],
            },
            "cache": {
                "hits": cache_hits,
                "misses": cache_misses,
                "total_events": cache_total,
                "hit_rate": round(cache_hits / cache_total, 4) if cache_total else None,
                "note": "No cache events have been observed yet." if cache_total == 0 else "Hit rate is based on explicitly instrumented cache events.",
            },
            "background_tasks": {
                "event_count": len(background_events),
                "average_duration_ms": round(mean(background_durations), 3),
                "p95_duration_ms": round(percentile(background_durations, 95), 3),
                "slowest_tasks": aggregate_events(background_events, keys=("name",))[:20],
                "slowest_task_events": sorted(background_events, key=lambda item: item["duration_ms"], reverse=True)[:20],
            },
            "initial_learning_page_load": learning_page_load_summary(api_events, widget_events, frontend_widget_events),
            "top_10_bottlenecks": top_bottlenecks(api_events, db_events, background_events, widget_events + frontend_widget_events),
            "observability_limits": [
                "Exact database rows scanned are not available without issuing EXPLAIN/ANALYZE, which this diagnostics layer avoids to prevent side effects.",
                "Frontend widget timings are visible after the Performance Diagnostics page runs its browser-side probes.",
                "Metrics are in-memory for the current process and reset when the Space container restarts.",
            ],
        }

    def startup_status(self) -> dict[str, Any]:
        with self._lock:
            phases = list(self._startup_phases)
            started_at = self.startup_started_at
            completed_at = self.startup_completed_at
        current_stage = phases[-1]["name"] if phases else "process_started"
        return {
            "started_at": started_at.isoformat() if started_at else self.process_started_at.isoformat(),
            "current_stage": "ready" if completed_at else current_stage,
            "database_restore_status": "not_instrumented",
            "alembic_status": "applied_by_start_script",
            "background_jobs_status": "starting" if not completed_at else "scheduled",
            "api_ready": True,
            "ui_ready": True,
            "startup_completed_at": completed_at.isoformat() if completed_at else None,
            "startup_duration_ms": round((completed_at - started_at).total_seconds() * 1000, 3) if started_at and completed_at else None,
            "phases": phases,
            "last_error": "",
        }

    def _structured_log(self, event_name: str, payload: dict[str, Any]) -> None:
        try:
            PERFORMANCE_LOGGER.info(json.dumps({"event": event_name, **json_safe(payload)}, ensure_ascii=True, sort_keys=True))
        except Exception:
            PERFORMANCE_LOGGER.info("performance_event=%s", event_name)


def compact_sql(statement: str) -> str:
    return re.sub(r"\s+", " ", statement or "").strip()[:900]


def normalize_path(path: str) -> str:
    if path.startswith("/assets/") and path.count("/") >= 2:
        return "/assets/{ticker}"
    if path.startswith("/signals/") and path.count("/") >= 2:
        return "/signals/{ticker}"
    if path.startswith("/sentiment/") and path.count("/") >= 2:
        return "/sentiment/{ticker}"
    if path.startswith("/fundamentals/") and path.count("/") >= 2:
        return "/fundamentals/{ticker}"
    if path.startswith("/chart/technical-report/"):
        return "/chart/technical-report/{ticker}"
    if path.startswith("/chart/levels/"):
        return "/chart/levels/{ticker}"
    if path.startswith("/chart/signals/"):
        return "/chart/signals/{ticker}"
    if path.startswith("/chart/history/"):
        return "/chart/history/{ticker}"
    if path.startswith("/api/trading-game/trades/") and "/attribution" in path:
        return "/api/trading-game/trades/{trade_id}/attribution"
    if path.startswith("/api/trading-game/trades/") and "/quality" in path:
        return "/api/trading-game/trades/{trade_id}/quality"
    if path.startswith("/api/trading-game/trades/") and "/pnl-breakdown" in path:
        return "/api/trading-game/trades/{trade_id}/pnl-breakdown"
    if path.startswith("/api/trading-game/trades/"):
        return "/api/trading-game/trades/{trade_id}"
    return re.sub(r"/[A-Z]{1,6}(?:\.[A-Z]{2})?(?=/|$)", "/{ticker}", path)


def summarize_parameters(parameters: Any) -> str:
    if parameters is None:
        return "none"
    if isinstance(parameters, dict):
        return f"dict:{len(parameters)}"
    if isinstance(parameters, (list, tuple)):
        return f"sequence:{len(parameters)}"
    return type(parameters).__name__


def mean(values: Iterable[float]) -> float:
    data = list(values)
    return sum(data) / len(data) if data else 0.0


def percentile(values: Iterable[float], pct: int) -> float:
    data = sorted(values)
    if not data:
        return 0.0
    index = (len(data) - 1) * pct / 100
    lower = int(index)
    upper = min(lower + 1, len(data) - 1)
    if lower == upper:
        return data[lower]
    weight = index - lower
    return data[lower] * (1 - weight) + data[upper] * weight


def aggregate_events(events: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        grouped[tuple(event.get(key) for key in keys)].append(event)
    rows = []
    for group_key, group_events in grouped.items():
        durations = [event["duration_ms"] for event in group_events]
        row = {key: group_key[index] for index, key in enumerate(keys)}
        row.update(
            {
                "count": len(group_events),
                "avg_ms": round(mean(durations), 3),
                "p95_ms": round(percentile(durations, 95), 3),
                "max_ms": round(max(durations), 3),
                "last_seen_at": group_events[-1].get("started_at"),
            }
        )
        rows.append(row)
    return sorted(rows, key=lambda item: (item["p95_ms"], item["max_ms"], item["count"]), reverse=True)


def aggregate_sql(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        grouped[sql_fingerprint(event["sql"])].append(event)
    rows = []
    for fingerprint, group_events in grouped.items():
        durations = [event["duration_ms"] for event in group_events]
        rows.append(
            {
                "fingerprint": fingerprint,
                "operation": group_events[-1].get("operation"),
                "count": len(group_events),
                "avg_ms": round(mean(durations), 3),
                "p95_ms": round(percentile(durations, 95), 3),
                "max_ms": round(max(durations), 3),
                "last_sql": group_events[-1].get("sql"),
                "last_rowcount": group_events[-1].get("rowcount"),
                "last_rows_scanned_estimate": group_events[-1].get("rows_scanned_estimate"),
            }
        )
    return sorted(rows, key=lambda item: (item["p95_ms"], item["max_ms"], item["count"]), reverse=True)


def sql_fingerprint(sql: str) -> str:
    compact = re.sub(r"\b\d+\b", "?", sql)
    compact = re.sub(r"'[^']*'", "?", compact)
    return compact[:300]


def top_bottlenecks(api_events: list[dict[str, Any]], db_events: list[dict[str, Any]], background_events: list[dict[str, Any]], widget_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in api_events:
        rows.append({"kind": "api", "name": f"{event['method']} {event['path']}", "duration_ms": event["duration_ms"], "started_at": event["started_at"]})
    for event in db_events:
        rows.append({"kind": "database", "name": event["sql"][:140], "duration_ms": event["duration_ms"], "started_at": event["started_at"], "rows_scanned_estimate": event.get("rows_scanned_estimate")})
    for event in background_events:
        rows.append({"kind": "background", "name": event["name"], "duration_ms": event["duration_ms"], "started_at": event["started_at"]})
    for event in widget_events:
        rows.append({"kind": event.get("event_type", "dashboard_widget"), "name": event["name"], "duration_ms": event["duration_ms"], "started_at": event["started_at"]})
    return sorted(rows, key=lambda item: item["duration_ms"], reverse=True)[:10]


def learning_page_load_summary(api_events: list[dict[str, Any]], widget_events: list[dict[str, Any]], frontend_widget_events: list[dict[str, Any]]) -> dict[str, Any]:
    frontend_api_events = [event for event in frontend_widget_events if str(event.get("name", "")).startswith("frontend.api.")]
    status_counts: dict[str, int] = defaultdict(int)
    for event in frontend_api_events:
        status_counts[str((event.get("metadata") or {}).get("status") or "unknown")] += 1
    heavy_events = [
        event for event in widget_events
        if event.get("name") == "performance.heavy_recalculation_triggered_during_page_load"
    ]
    endpoint_rows = []
    for event in frontend_api_events[-80:]:
        name = str(event.get("name") or "")
        endpoint_rows.append(
            {
                "name": name.replace("frontend.api.", ""),
                "duration_ms": event.get("duration_ms"),
                "status": (event.get("metadata") or {}).get("status"),
                "source": (event.get("metadata") or {}).get("source"),
                "started_at": event.get("started_at"),
            }
        )
    blocking_candidates = [
        event for event in frontend_api_events
        if event.get("duration_ms", 0) >= 1000
    ]
    return {
        "frontend_request_count": len(frontend_api_events),
        "duplicate_request_count": status_counts.get("deduped", 0),
        "cache_hit_count": status_counts.get("cache_hit", 0) + status_counts.get("cache", 0),
        "status_counts": dict(status_counts),
        "heavy_post_calls_during_page_load": [
            {
                "method": (event.get("metadata") or {}).get("method"),
                "path": (event.get("metadata") or {}).get("path"),
                "duration_ms": event.get("duration_ms"),
                "referer": (event.get("metadata") or {}).get("referer"),
                "started_at": event.get("started_at"),
            }
            for event in heavy_events[-20:]
        ],
        "endpoints_called_during_initial_page_load": endpoint_rows,
        "potential_first_render_blockers": sorted(blocking_candidates, key=lambda item: item.get("duration_ms", 0), reverse=True)[:12],
        "server_learning_endpoint_events": [
            event for event in api_events
            if event.get("path") == "/api/learning-intelligence/summary"
            or str(event.get("path", "")).startswith("/learning/")
        ][-20:],
    }


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


performance_recorder = PerformanceRecorder()
