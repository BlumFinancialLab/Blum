from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
import json
import time
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import (
    EquityCurveAnnotation,
    EquityCurveSnapshot,
    HistoricalPrediction,
    TradeEngineAttribution,
    TradeLearningEvidence,
    TradeQualityScore,
    TradingGame,
    TradingGameEquityCurve,
    TradingGameLedgerSnapshot,
    TradingGameTrade,
)
from app.services.dashboard_snapshots import DashboardSnapshotService
from app.services.performance import performance_recorder


LEDGER_SNAPSHOT_LIMIT = 200
EQUITY_SNAPSHOT_LIMIT = 600
SNAPSHOT_TTL_SECONDS = 600


class RuntimeTrace:
    """Small endpoint-level phase timer for Trading Game runtime diagnostics."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.started_at = time.perf_counter()
        self.phases: dict[str, float] = {}
        self.metadata: dict[str, Any] = {}

    @contextmanager
    def phase(self, name: str):
        started = time.perf_counter()
        try:
            yield
        finally:
            self.phases[name] = round((time.perf_counter() - started) * 1000, 3)

    def add(self, **metadata: Any) -> None:
        self.metadata.update(metadata)

    def payload(self) -> dict:
        total_ms = round((time.perf_counter() - self.started_at) * 1000, 3)
        return {
            "name": self.name,
            "total_ms": total_ms,
            "phases_ms": self.phases,
            "metadata": self.metadata,
        }


class TradingGameRuntimeSnapshotService:
    """Snapshot producer/reader for heavy Trading Game surfaces.

    The service isolates expensive ledger/equity assembly from GET page loads.
    Snapshot production is allowed to do bounded batch reads. Endpoint reads use
    the latest persisted payload and only fall back to live bounded reads when
    the requested view cannot be satisfied from a snapshot.
    """

    def produce_ledger_snapshot(self, db: Session, game_id: int | None = None, limit: int = LEDGER_SNAPSHOT_LIMIT) -> dict:
        from app.services.trade_transparency import TradeLedgerService, TRANSPARENCY_POLICY, serialize_game_header

        trace = RuntimeTrace("trading_game_ledger_snapshot_produce")
        ledger_service = TradeLedgerService()
        with trace.phase("base_trade_query"):
            game = ledger_service.game(db, game_id)
            if not game:
                return self._missing_snapshot_payload("trading_game_ledger_snapshot", "no_game")
            total = int(db.scalar(select(func.count(TradingGameTrade.id)).where(TradingGameTrade.game_id == game.id)) or 0)
            rows = db.scalars(
                select(TradingGameTrade)
                .where(TradingGameTrade.game_id == game.id)
                .order_by(desc(TradingGameTrade.created_at))
                .limit(limit)
            ).all()
        trade_ids = [row.id for row in rows]
        with trace.phase("attribution_loading"):
            attributions = self._attribution_summary(db, trade_ids)
        with trace.phase("evidence_loading"):
            evidence = self._evidence_summary(db, trade_ids)
        with trace.phase("quality_loading"):
            quality = self._quality_summary(db, trade_ids)
        with trace.phase("prediction_loading"):
            prediction = self._prediction_summary(db, rows)
        with trace.phase("benchmark_loading"):
            benchmark = self._benchmark_summary(rows)
        with trace.phase("serialization"):
            serialized_rows = [ledger_service.serialize_trade(db, row) for row in rows]
            summary = ledger_service.summary_for_game(db, game)
        payload = {
            "status": "ok",
            "snapshot_status": "ready",
            "game": serialize_game_header(game),
            "summary": summary,
            "rows": serialized_rows,
            "total": total,
            "limit": limit,
            "offset": 0,
            "filters": {"snapshot_default": True, "game_id": game_id, "sort_by": "created_at_desc"},
            "attribution_summary": attributions,
            "trade_quality_summary": quality,
            "benchmark_summary": benchmark,
            "evidence_summary": evidence,
            "prediction_summary": prediction,
            "policy": TRANSPARENCY_POLICY,
        }
        with trace.phase("json_generation"):
            size = payload_size_bytes(payload)
        trace.add(
            base_trade_query_count=2,
            attribution_loading_queries=1 if trade_ids else 0,
            evidence_loading_queries=1 if trade_ids else 0,
            quality_loading_queries=1 if trade_ids else 0,
            prediction_loading_queries=1 if prediction["linked_prediction_count"] else 0,
            row_count=len(rows),
            total_trades=total,
            response_size_bytes=size,
            object_counts={"rows": len(rows), "attributions": attributions["rows"], "evidence": evidence["rows"], "quality_rows": quality["rows"]},
        )
        trace_payload = trace.payload()
        payload["runtime_trace"] = trace_payload
        expires_at = datetime.utcnow() + timedelta(seconds=SNAPSHOT_TTL_SECONDS)
        row = TradingGameLedgerSnapshot(
            game_id=game.id,
            expires_at=expires_at,
            limit=limit,
            total_trades=total,
            row_count=len(rows),
            payload_json=payload,
            summary_json=summary,
            trace_json=trace_payload,
            payload_size_bytes=size,
            is_stale=False,
        )
        db.add(row)
        db.commit()
        self._write_dashboard_pointer(
            db,
            "trading_game_ledger_snapshot",
            row.id,
            game.id,
            trace_payload,
            size,
            warnings=[],
        )
        performance_recorder.record_cache_event("trading_game.ledger_snapshot.write", hit=True, metadata={"game_id": game.id, "rows": len(rows)})
        return {"status": "ready", "snapshot_id": row.id, "game_id": game.id, "row_count": len(rows), "total": total, "payload_size_bytes": size, "runtime_trace": trace_payload}

    def ledger_from_snapshot(self, db: Session, game_id: int | None = None, limit: int = 50, offset: int = 0) -> dict | None:
        trace = RuntimeTrace("trading_game_ledger_snapshot_read")
        with trace.phase("snapshot_lookup"):
            row = self._latest_ledger_snapshot(db, game_id)
        if row is None:
            performance_recorder.record_cache_event("trading_game.ledger_snapshot", hit=False, metadata={"game_id": game_id})
            return None
        payload = dict(row.payload_json or {})
        rows = list(payload.get("rows") or [])
        with trace.phase("payload_slice"):
            payload["rows"] = rows[offset : offset + limit]
            payload["limit"] = limit
            payload["offset"] = offset
            payload["snapshot_id"] = row.id
            payload["snapshot_created_at"] = row.created_at.isoformat() if row.created_at else None
            payload["snapshot_expires_at"] = row.expires_at.isoformat() if row.expires_at else None
            payload["snapshot_status"] = "stale" if self._is_stale(row) else "ready"
            payload.setdefault("warnings", [])
            if self._is_stale(row):
                payload["warnings"] = list(payload.get("warnings") or []) + ["ledger_snapshot_stale"]
        with trace.phase("json_generation"):
            size = payload_size_bytes(payload)
        trace.add(
            source_snapshot_payload_size_bytes=row.payload_size_bytes,
            response_size_bytes=size,
            source_row_count=row.row_count,
            returned_rows=len(payload["rows"]),
            query_count=1,
        )
        payload["runtime_trace"] = trace.payload()
        performance_recorder.record_cache_event("trading_game.ledger_snapshot", hit=not self._is_stale(row), metadata={"game_id": row.game_id})
        return payload

    def produce_equity_snapshot(self, db: Session, game_id: int | None = None, limit: int = EQUITY_SNAPSHOT_LIMIT) -> dict:
        from app.services.trade_transparency import TradeLedgerService, serialize_annotation, serialize_equity_point, serialize_game_header

        trace = RuntimeTrace("equity_curve_snapshot_produce")
        with trace.phase("base_trade_query"):
            game = TradeLedgerService().game(db, game_id)
            if not game:
                return self._missing_snapshot_payload("equity_curve_snapshot", "no_game")
        with trace.phase("equity_points_loading"):
            points = db.scalars(
                select(TradingGameEquityCurve)
                .where(TradingGameEquityCurve.game_id == game.id)
                .order_by(TradingGameEquityCurve.created_at)
                .limit(limit)
            ).all()
        with trace.phase("annotations_loading"):
            annotations = db.scalars(
                select(EquityCurveAnnotation)
                .where(EquityCurveAnnotation.game_id == game.id)
                .order_by(EquityCurveAnnotation.timestamp)
                .limit(limit)
            ).all()
        with trace.phase("benchmark_loading"):
            benchmark_points = [{"timestamp": iso_value(row.equity_date or row.created_at), "value": row.benchmark_equity, "return": row.benchmark_return} for row in points]
        with trace.phase("serialization"):
            payload = {
                "status": "ok",
                "snapshot_status": "ready",
                "game": serialize_game_header(game),
                "equity_curve_points": [serialize_equity_point(row) for row in points],
                "benchmark_curve_points": benchmark_points,
                "annotations": [serialize_annotation(row) for row in annotations],
                "summary": {
                    "point_count": len(points),
                    "annotation_count": len(annotations),
                    "latest_equity": points[-1].equity if points else None,
                    "latest_benchmark_equity": points[-1].benchmark_equity if points else None,
                },
                "policy": "Markers connect equity movement to trade entries, exits, drawdowns, rule events and benchmark divergence when those events exist.",
            }
        with trace.phase("json_generation"):
            size = payload_size_bytes(payload)
        trace.add(
            base_trade_query_count=1,
            equity_points_queries=1,
            annotations_queries=1,
            benchmark_loading_queries=0,
            point_count=len(points),
            annotation_count=len(annotations),
            response_size_bytes=size,
            object_counts={"points": len(points), "benchmark_points": len(benchmark_points), "annotations": len(annotations)},
        )
        trace_payload = trace.payload()
        payload["runtime_trace"] = trace_payload
        row = EquityCurveSnapshot(
            game_id=game.id,
            expires_at=datetime.utcnow() + timedelta(seconds=SNAPSHOT_TTL_SECONDS),
            limit=limit,
            point_count=len(points),
            annotation_count=len(annotations),
            payload_json=payload,
            summary_json=payload["summary"],
            trace_json=trace_payload,
            payload_size_bytes=size,
            is_stale=False,
        )
        db.add(row)
        db.commit()
        self._write_dashboard_pointer(db, "equity_curve_snapshot", row.id, game.id, trace_payload, size, warnings=[])
        performance_recorder.record_cache_event("trading_game.equity_snapshot.write", hit=True, metadata={"game_id": game.id, "points": len(points)})
        return {"status": "ready", "snapshot_id": row.id, "game_id": game.id, "point_count": len(points), "annotation_count": len(annotations), "payload_size_bytes": size, "runtime_trace": trace_payload}

    def equity_from_snapshot(self, db: Session, game_id: int | None = None, limit: int = 240) -> dict | None:
        trace = RuntimeTrace("equity_curve_snapshot_read")
        with trace.phase("snapshot_lookup"):
            row = self._latest_equity_snapshot(db, game_id)
        if row is None:
            performance_recorder.record_cache_event("trading_game.equity_snapshot", hit=False, metadata={"game_id": game_id})
            return None
        payload = dict(row.payload_json or {})
        points = list(payload.get("equity_curve_points") or [])
        benchmark = list(payload.get("benchmark_curve_points") or [])
        annotations = list(payload.get("annotations") or [])
        with trace.phase("payload_slice"):
            payload["equity_curve_points"] = points[:limit]
            payload["benchmark_curve_points"] = benchmark[:limit]
            payload["annotations"] = annotations[:limit]
            payload["snapshot_id"] = row.id
            payload["snapshot_created_at"] = row.created_at.isoformat() if row.created_at else None
            payload["snapshot_expires_at"] = row.expires_at.isoformat() if row.expires_at else None
            payload["snapshot_status"] = "stale" if self._is_stale(row) else "ready"
            payload.setdefault("warnings", [])
            if self._is_stale(row):
                payload["warnings"] = list(payload.get("warnings") or []) + ["equity_curve_snapshot_stale"]
        with trace.phase("json_generation"):
            size = payload_size_bytes(payload)
        trace.add(
            source_snapshot_payload_size_bytes=row.payload_size_bytes,
            response_size_bytes=size,
            point_count=len(payload["equity_curve_points"]),
            annotation_count=len(payload["annotations"]),
            query_count=1,
        )
        payload["runtime_trace"] = trace.payload()
        performance_recorder.record_cache_event("trading_game.equity_snapshot", hit=not self._is_stale(row), metadata={"game_id": row.game_id})
        return payload

    def _latest_ledger_snapshot(self, db: Session, game_id: int | None) -> TradingGameLedgerSnapshot | None:
        query = select(TradingGameLedgerSnapshot)
        if game_id:
            query = query.where(TradingGameLedgerSnapshot.game_id == game_id)
        return db.scalar(query.order_by(desc(TradingGameLedgerSnapshot.created_at)).limit(1))

    def _latest_equity_snapshot(self, db: Session, game_id: int | None) -> EquityCurveSnapshot | None:
        query = select(EquityCurveSnapshot)
        if game_id:
            query = query.where(EquityCurveSnapshot.game_id == game_id)
        return db.scalar(query.order_by(desc(EquityCurveSnapshot.created_at)).limit(1))

    def _is_stale(self, row: TradingGameLedgerSnapshot | EquityCurveSnapshot) -> bool:
        return bool(row.is_stale or (row.expires_at is not None and row.expires_at < datetime.utcnow()))

    def _attribution_summary(self, db: Session, trade_ids: list[int]) -> dict:
        if not trade_ids:
            return {"rows": 0, "by_engine": {}}
        rows = db.scalars(select(TradeEngineAttribution).where(TradeEngineAttribution.trade_id.in_(trade_ids))).all()
        by_engine: dict[str, dict] = {}
        for row in rows:
            item = by_engine.setdefault(row.engine_name, {"count": 0, "average_contribution": 0.0, "correct": 0})
            item["count"] += 1
            item["average_contribution"] += row.contribution_score or 0.0
            item["correct"] += 1 if row.was_correct else 0
        for item in by_engine.values():
            item["average_contribution"] = round(item["average_contribution"] / max(1, item["count"]), 4)
        return {"rows": len(rows), "by_engine": by_engine}

    def _evidence_summary(self, db: Session, trade_ids: list[int]) -> dict:
        if not trade_ids:
            return {"rows": 0, "lesson_types": {}}
        rows = db.scalars(select(TradeLearningEvidence).where(TradeLearningEvidence.trade_id.in_(trade_ids))).all()
        lesson_types: dict[str, int] = {}
        for row in rows:
            lesson_types[row.lesson_type] = lesson_types.get(row.lesson_type, 0) + 1
        return {"rows": len(rows), "lesson_types": lesson_types}

    def _quality_summary(self, db: Session, trade_ids: list[int]) -> dict:
        if not trade_ids:
            return {"rows": 0, "average_trade_quality": None}
        rows = db.scalars(select(TradeQualityScore).where(TradeQualityScore.trade_id.in_(trade_ids))).all()
        values = [row.final_trade_quality_score for row in rows if row.final_trade_quality_score is not None]
        return {"rows": len(rows), "average_trade_quality": round(sum(values) / len(values), 4) if values else None}

    def _prediction_summary(self, db: Session, trades: list[TradingGameTrade]) -> dict:
        ids = sorted({row.thesis_id for row in trades if row.thesis_id})
        if not ids:
            return {"linked_prediction_count": 0, "rows_loaded": 0}
        rows = db.scalars(select(HistoricalPrediction.id).where(HistoricalPrediction.id.in_(ids))).all()
        return {"linked_prediction_count": len(ids), "rows_loaded": len(rows)}

    def _benchmark_summary(self, trades: list[TradingGameTrade]) -> dict:
        values = [row.excess_return_vs_benchmark for row in trades if row.excess_return_vs_benchmark is not None]
        return {
            "benchmark_tickers": sorted({row.benchmark_ticker for row in trades if row.benchmark_ticker}),
            "average_excess_return": round(sum(values) / len(values), 4) if values else None,
            "positive_excess_count": sum(1 for value in values if value and value > 0),
            "sample_size": len(values),
        }

    def _write_dashboard_pointer(self, db: Session, snapshot_type: str, snapshot_id: int, game_id: int, trace: dict, size: int, warnings: list[str]) -> None:
        DashboardSnapshotService().write(
            db,
            snapshot_type,
            {
                "status": "ready",
                "snapshot_id": snapshot_id,
                "game_id": game_id,
                "runtime_trace": trace,
                "payload_size_bytes": size,
            },
            source_modules={"producer": "TradingGameRuntimeSnapshotService", "runtime_policy": "dedicated_snapshot_table"},
            ttl_seconds=SNAPSHOT_TTL_SECONDS,
            warnings=warnings,
            missing_sections=[],
            computation_duration_ms=trace.get("total_ms"),
        )

    def _missing_snapshot_payload(self, snapshot_type: str, reason: str) -> dict:
        return {"status": "missing", "snapshot_type": snapshot_type, "reason": reason}


def payload_size_bytes(payload: dict) -> int:
    try:
        return len(json.dumps(json_safe(payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except Exception:
        return 0


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    return value


def iso_value(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
