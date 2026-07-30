"""Bounded background orchestration for trading ML research."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
import time
from typing import Iterable
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import BackgroundJobState, TradingMLModelVersion, TradingMLTrainingRun
from app.services.central_brain_runtime import BrainEventBus
from app.services.dashboard_snapshots import DashboardSnapshotService

from .contracts import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    InsufficientTrainingEvidenceError,
    TradingMLExample,
)
from .feature_store import TradingMLFeatureStoreProjector
from .finrlx import FinRLXQuantEngine
from .registry import TradingMLModelRegistry, TradingMLPromotionService
from .training import BoundedOptunaChallengerSearch, OnlineShadowTrainer, SklearnTradingModelTrainer


class TradingMLLearningWorker:
    job_name = "trading_ml_learning"

    def __init__(
        self,
        *,
        artifact_root: str | Path | None = None,
        max_runtime_seconds: int | None = None,
        max_rows: int | None = None,
    ) -> None:
        settings = get_settings()
        self.root = Path(artifact_root or settings.trading_ml_artifact_root)
        self.max_runtime_seconds = int(max_runtime_seconds or settings.trading_ml_max_runtime_seconds)
        self.max_rows = int(max_rows or settings.trading_ml_max_rows_per_slice)
        self.settings = settings
        self.projector = TradingMLFeatureStoreProjector(
            root=self.root / "feature_store",
            max_rows_per_projection=self.max_rows,
        )
        self.registry = TradingMLModelRegistry(self.root)
        self.promotion = TradingMLPromotionService(self.root)
        self.finrlx = FinRLXQuantEngine()

    def run_once(self, db: Session, trigger: str = "scheduled") -> dict:
        started = time.perf_counter()
        state = self._state(db)
        state.status = "running"
        state.last_started_at = datetime.utcnow()
        state.max_items = self.max_rows * 2
        db.commit()
        # Give the optional shadow challenger a bounded initialization slice
        # before the heavier core lanes can consume the entire worker budget.
        finrlx = self._run_finrlx(started)
        markets: dict[str, dict] = {}
        total_processed = 0
        for market_family in ("equity", "forex"):
            if time.perf_counter() - started >= self.max_runtime_seconds:
                markets[market_family] = {"status": "BUDGET_EXHAUSTED"}
                continue
            try:
                market_result = self._run_market(db, market_family, trigger, started)
                markets[market_family] = market_result
                total_processed += int(market_result.get("rows_considered") or 0)
            except Exception as exc:
                db.rollback()
                markets[market_family] = {
                    "status": "FAILED",
                    "error": f"{type(exc).__name__}: {exc}",
                }

        duration = time.perf_counter() - started
        payload = {
            "status": "COMPLETED" if any(item.get("status") != "FAILED" for item in markets.values()) else "FAILED",
            "trigger": trigger,
            "markets": markets,
            "finrlx": finrlx,
            "duration_seconds": round(duration, 4),
            "bounded": True,
            "decision_policy": "shadow/challenger models have no authority; only evidence-gated ACTIVE models advise within guardrails",
            "last_run_at": datetime.utcnow().isoformat(),
        }
        state = self._state(db)
        state.status = "completed" if payload["status"] == "COMPLETED" else "failed"
        state.items_processed = total_processed
        state.duration_ms = duration * 1000
        state.last_completed_at = datetime.utcnow()
        state.next_run_after = datetime.utcnow() + timedelta(minutes=self.settings.trading_ml_worker_minutes)
        state.cursor_json = self.projector.manifest().get("source_cursors") or {}
        state.error_message = "" if payload["status"] == "COMPLETED" else "All market-family lanes failed"
        db.commit()
        DashboardSnapshotService().write(
            db,
            "trading_ml_status",
            payload,
            source_modules={"producer": self.job_name},
            ttl_seconds=max(300, self.settings.trading_ml_worker_minutes * 120),
            warnings=[
                item["error"]
                for item in markets.values()
                if item.get("status") == "FAILED" and item.get("error")
            ],
        )
        BrainEventBus().publish(
            db,
            "learning_cycle_completed" if payload["status"] == "COMPLETED" else "module_failed",
            self.job_name,
            status=payload["status"].lower(),
            duration_ms=duration * 1000,
            payload={"markets": markets, "items_processed": total_processed},
        )
        return payload

    def _run_finrlx(self, started: float) -> dict:
        """Run optional external research without affecting core worker success."""
        markets: dict[str, dict] = {}
        for market_family in ("forex", "equity"):
            remaining_seconds = self.max_runtime_seconds - (time.perf_counter() - started)
            if remaining_seconds < 1:
                markets[market_family] = {
                    "status": "BUDGET_EXHAUSTED",
                    "reason": "The FinRL-X initialization slice consumed its bounded budget.",
                    "paper_only": True,
                }
                continue
            try:
                status = self.finrlx.status(market_family=market_family)
                if status.get("status") != "NO_VALIDATED_ARTIFACT":
                    markets[market_family] = status
                    continue
                per_market_budget = max(
                    1,
                    min(
                        int(remaining_seconds),
                        max(10, self.max_runtime_seconds // 2),
                    ),
                )
                markets[market_family] = self.finrlx.run_training(
                    market_family=market_family,
                    request={
                        "feature_store_root": str((self.root / "feature_store").resolve()),
                        "artifact_root": str(
                            Path(
                                getattr(
                                    self.finrlx,
                                    "artifact_root",
                                    self.root / "finrlx",
                                )
                            ).resolve()
                        ),
                        "max_rows": self.max_rows,
                        "max_runtime_seconds": per_market_budget,
                        "paper_only": True,
                    },
                )
            except Exception as exc:
                markets[market_family] = {
                    "status": "FAILED",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "paper_only": True,
                }
        return {
            "status": _aggregate_finrlx_status(markets.values()),
            "markets": markets,
            "paper_only": True,
        }

    def _run_market(self, db: Session, market_family: str, trigger: str, started: float) -> dict:
        active = db.scalar(
            select(TradingMLModelVersion)
            .where(
                TradingMLModelVersion.market_family == market_family,
                TradingMLModelVersion.status == "ACTIVE",
            )
            .order_by(desc(TradingMLModelVersion.activated_at), desc(TradingMLModelVersion.id))
            .limit(1)
        )
        if active is not None:
            loaded = self.registry.load_active(db, market_family)
            if loaded.status == "DEGRADED":
                self.promotion.rollback(
                    db,
                    active,
                    reason="; ".join(loaded.warnings) or "Active artifact failed verification.",
                )

        projection = self.projector.project(db, market_family=market_family, limit=self.max_rows)  # type: ignore[arg-type]
        rows = self._load_examples(market_family)
        run = TradingMLTrainingRun(
            run_uid=f"trading-ml-{market_family}-{uuid4().hex}",
            market_family=market_family,
            trigger=trigger,
            cursor_json=projection.source_cursor or {},
            resource_limits_json={
                "max_runtime_seconds": self.max_runtime_seconds,
                "max_rows": self.max_rows,
                "optuna_trials": min(12, self.settings.trading_ml_optuna_trials),
            },
            rows_considered=projection.rows_considered,
            rows_accepted=len(rows),
            rows_rejected=projection.rows_rejected,
            status="RUNNING",
        )
        db.add(run)
        db.flush()
        if not rows:
            run.status = "INSUFFICIENT_EVIDENCE"
            run.completed_at = datetime.utcnow()
            db.commit()
            return {
                "status": "INSUFFICIENT_EVIDENCE",
                "rows_considered": projection.rows_considered,
                "sample_count": 0,
                "reason": "No point-in-time cost-adjusted labels are available.",
            }

        # Rapid online learning is always shadow-only.
        shadow = OnlineShadowTrainer(self.root / "shadow").partial_fit(rows)
        latest_same_dataset = db.scalar(
            select(TradingMLModelVersion)
            .where(
                TradingMLModelVersion.market_family == market_family,
                TradingMLModelVersion.dataset_hash == shadow.dataset_hash,
                TradingMLModelVersion.algorithm == shadow.model_bundle.algorithm,
            )
            .order_by(desc(TradingMLModelVersion.id))
            .limit(1)
        )
        if latest_same_dataset is None:
            shadow_row = self.registry.store_candidate(
                db,
                market_family=market_family,
                result=shadow,
                evidence_lane_counts=Counter(row.evidence_lane for row in rows),
                asset_count=len({row.asset_key for row in rows}),
                regime_count=len({row.regime for row in rows}),
                setup_count=len({row.setup_type for row in rows}),
                explanation="Rapid SGD learner; permanently shadow-only.",
            )
            shadow_row.status = "SHADOW"
            shadow_row.promotion_decision = "SHADOW_ONLY"
            db.commit()

        if len(rows) < self.settings.trading_ml_min_replay_samples:
            run.status = "SHADOW"
            run.split_metadata_json = {"minimum_samples": self.settings.trading_ml_min_replay_samples}
            run.completed_at = datetime.utcnow()
            db.commit()
            return {
                "status": "SHADOW",
                "rows_considered": projection.rows_considered,
                "sample_count": len(rows),
                "minimum_samples": self.settings.trading_ml_min_replay_samples,
            }
        if len({row.asset_key for row in rows}) < self.settings.trading_ml_min_assets:
            run.status = "INSUFFICIENT_EVIDENCE"
            run.completed_at = datetime.utcnow()
            db.commit()
            return {
                "status": "INSUFFICIENT_EVIDENCE",
                "rows_considered": projection.rows_considered,
                "sample_count": len(rows),
                "reason": "Insufficient asset/pair diversity.",
            }
        if time.perf_counter() - started >= self.max_runtime_seconds * 0.35:
            run.status = "BUDGET_EXHAUSTED"
            run.completed_at = datetime.utcnow()
            db.commit()
            return {"status": "BUDGET_EXHAUSTED", "sample_count": len(rows), "rows_considered": projection.rows_considered}

        dataset_hash = shadow.dataset_hash
        existing = db.scalar(
            select(TradingMLModelVersion)
            .where(
                TradingMLModelVersion.market_family == market_family,
                TradingMLModelVersion.dataset_hash == dataset_hash,
                TradingMLModelVersion.algorithm == "hist_gradient_boosting_classifier_regressor",
            )
            .order_by(desc(TradingMLModelVersion.id))
            .limit(1)
        )
        if existing is not None:
            run.status = existing.status
            run.candidate_model_version_id = existing.id
            run.completed_at = datetime.utcnow()
            db.commit()
            return {
                "status": existing.status,
                "sample_count": len(rows),
                "rows_considered": projection.rows_considered,
                "model_uid": existing.model_uid,
                "reused_dataset": True,
            }

        try:
            search = BoundedOptunaChallengerSearch(
                max_trials=self.settings.trading_ml_optuna_trials,
                timeout_seconds=min(
                    self.settings.trading_ml_optuna_timeout_seconds,
                    max(1, int(self.max_runtime_seconds - (time.perf_counter() - started))),
                ),
                min_folds=self.settings.trading_ml_min_folds,
            ).search(rows)
            stable = SklearnTradingModelTrainer(
                min_folds=self.settings.trading_ml_min_folds,
                parameters=search.parameters,
            ).fit(rows)
        except InsufficientTrainingEvidenceError as exc:
            run.status = "INSUFFICIENT_EVIDENCE"
            run.rejection_reasons_json = {
                "evidence_gap": str(exc),
                "policy": "Leakage-safe validation cannot be relaxed to manufacture a challenger.",
            }
            run.completed_at = datetime.utcnow()
            run.duration_seconds = round(time.perf_counter() - started, 4)
            db.commit()
            return {
                "status": "INSUFFICIENT_EVIDENCE",
                "rows_considered": projection.rows_considered,
                "sample_count": len(rows),
                "reason": str(exc),
            }
        candidate = self.registry.store_candidate(
            db,
            market_family=market_family,
            result=stable,
            evidence_lane_counts=Counter(row.evidence_lane for row in rows),
            asset_count=len({row.asset_key for row in rows}),
            regime_count=len({row.regime for row in rows}),
            setup_count=len({row.setup_type for row in rows}),
            explanation="Stable deterministic challenger validated with purged walk-forward folds.",
        )
        decision = self.promotion.promote(db, candidate)
        run.candidate_model_version_id = candidate.id
        run.status = decision.status
        run.split_metadata_json = {"folds": len(stable.validation_result.folds) if stable.validation_result else 0}
        run.rejection_reasons_json = {
            "candidate": dict(stable.validation_metrics),
            "baseline": dict(stable.baseline_metrics),
            "promotion": {"status": decision.status, "failed_gates": list(decision.failed_gates)},
            "optuna": {
                "trials_completed": search.trials_completed,
                "duration_seconds": search.duration_seconds,
                "parameters": dict(search.parameters),
            },
        }
        run.completed_at = datetime.utcnow()
        run.duration_seconds = round(time.perf_counter() - started, 4)
        db.commit()
        return {
            "status": decision.status,
            "rows_considered": projection.rows_considered,
            "sample_count": len(rows),
            "model_uid": candidate.model_uid,
            "failed_gates": list(decision.failed_gates),
            "validation": dict(stable.validation_metrics),
        }

    def _load_examples(self, market_family: str) -> tuple[TradingMLExample, ...]:
        frame = (
            self.projector.scan(market_family=market_family)  # type: ignore[arg-type]
            .sort(["decision_timestamp", "outcome_timestamp", "source_uid"])
            .tail(self.max_rows)
            .collect()
        )
        return tuple(_example_from_store_row(row) for row in frame.to_dicts())

    def _state(self, db: Session) -> BackgroundJobState:
        row = db.scalar(
            select(BackgroundJobState).where(
                BackgroundJobState.job_name == self.job_name,
                BackgroundJobState.stage_name == "default",
            )
        )
        if row is None:
            row = BackgroundJobState(job_name=self.job_name, stage_name="default", status="idle", enabled=True)
            db.add(row)
            db.flush()
        return row


def _example_from_store_row(row: dict) -> TradingMLExample:
    return TradingMLExample(
        source_object_type=str(row["source_object_type"]),
        source_object_id=str(row["source_object_id"]),
        market_family=str(row["market_family"]),  # type: ignore[arg-type]
        evidence_lane=str(row["evidence_lane"]),
        decision_timestamp=row["decision_timestamp"],
        outcome_timestamp=row["outcome_timestamp"],
        asset_key=str(row["asset_key"]),
        setup_type=str(row["setup_type"]),
        regime=str(row["regime"]),
        features={
            name: row.get(name)
            for name in (*NUMERIC_FEATURES, *CATEGORICAL_FEATURES)
        },
        realized_net_r=float(row["realized_net_r"]),
        label_positive_r=int(row["label_positive_r"]),
        benchmark_excess=float(row["benchmark_excess"]) if row.get("benchmark_excess") is not None else None,
        sample_weight=float(row["sample_weight"]),
    )


def _aggregate_finrlx_status(results: Iterable[dict]) -> str:
    statuses = {str(result.get("status") or "FAILED").upper() for result in results}
    for preferred in (
        "VALIDATED_SHADOW",
        "READY_SHADOW",
        "INSUFFICIENT_EVIDENCE",
        "NO_VALIDATED_ARTIFACT",
        "BUDGET_EXHAUSTED",
        "DISABLED",
        "UNAVAILABLE",
        "REJECTED",
        "TIMEOUT",
        "FAILED",
    ):
        if preferred in statuses:
            return preferred
    return "FAILED"
