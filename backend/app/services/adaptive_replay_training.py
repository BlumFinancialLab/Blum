from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as day_time
from math import sqrt
from statistics import mean
import time

import psutil
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import BackgroundJobState, BlumLearningExperiment, HyperbolicReplayRun, HyperbolicReplayTrade, ReplayMarketBar, ReplayStrategyValidation
from app.services.central_brain_runtime import BackgroundJobStateService
from app.services.dashboard_snapshots import DashboardSnapshotService
from app.services.hyperbolic_replay import BlumHyperbolicReplayEngine, ReplayRunRequest
from app.services.performance import performance_recorder
from app.services.replay_validation import ReplayExperimentService, ReplayLearningFeedbackService, ReplayWalkForwardValidator
from app.services.worker_runtime import runtime_worker_coordinator
from app.services.alpha_strategy_factory import strategy_factory_snapshot
from app.services.strategy_promotion_frontier import StrategyPromotionFrontierService


REPLAY_SNAPSHOT_TYPE = "hyperbolic_replay_training_summary"


@dataclass(frozen=True)
class ReplayResourceSample:
    cpu_percent: float
    memory_percent: float
    api_p95_ms: float
    active_jobs: int
    average_batch_duration_seconds: float = 0.0
    dataset_rows: int = 0


@dataclass(frozen=True)
class ReplayTrainingConfig:
    target_trades_per_day: int
    max_seconds_per_cycle: int
    max_assets_per_cycle: int
    max_trades_per_cycle: int
    max_experiments_per_cycle: int
    min_promotion_samples: int
    markets: tuple[str, ...] = ("UNITED STATES", "USA", "ITALY", "GERMANY", "FRANCE", "EUROPE")
    timeframes: tuple[str, ...] = ("1d", "15m", "5m", "1m")
    min_data_quality: float = 35.0
    cpu_throttle_percent: float = 80.0
    cpu_pause_percent: float = 95.0
    memory_throttle_percent: float = 80.0
    memory_pause_percent: float = 92.0
    api_throttle_p95_ms: float = 2000.0
    api_pause_p95_ms: float = 5000.0

    @classmethod
    def from_settings(cls) -> "ReplayTrainingConfig":
        settings = get_settings()
        markets = [value.strip().upper() for value in settings.replay_markets.split(",") if value.strip()]
        if "FOREX" not in markets:
            markets.append("FOREX")
        return cls(
            target_trades_per_day=max(1, settings.replay_target_validated_trades_per_day),
            max_seconds_per_cycle=max(1, min(120, settings.replay_max_seconds_per_cycle)),
            max_assets_per_cycle=max(1, settings.replay_max_assets_per_cycle),
            max_trades_per_cycle=max(1, settings.replay_max_trades_per_cycle),
            max_experiments_per_cycle=max(1, min(8, settings.replay_max_experiments_per_cycle)),
            min_promotion_samples=max(300, settings.replay_min_promotion_samples),
            markets=tuple(markets),
            timeframes=tuple(value.strip() for value in settings.replay_timeframes.split(",") if value.strip()),
            min_data_quality=max(0.0, min(100.0, settings.replay_min_data_quality)),
            cpu_throttle_percent=settings.replay_cpu_throttle_percent,
            cpu_pause_percent=settings.replay_cpu_pause_percent,
            memory_throttle_percent=settings.replay_memory_throttle_percent,
            memory_pause_percent=settings.replay_memory_pause_percent,
            api_throttle_p95_ms=settings.replay_api_throttle_p95_ms,
            api_pause_p95_ms=settings.replay_api_pause_p95_ms,
        )


class ReplayResourceMonitor:
    def read(self, db: Session | None = None) -> ReplayResourceSample:
        diagnostics = performance_recorder.diagnostics()
        api_p95 = float((diagnostics.get("summary") or {}).get("p95_response_ms") or 0.0)
        active_jobs = int(runtime_worker_coordinator.snapshot().get("running_count") or 0)
        average_duration = 0.0
        dataset_rows = 0
        if db is not None:
            durations = db.scalars(
                select(HyperbolicReplayRun.duration_seconds)
                .where(HyperbolicReplayRun.duration_seconds > 0)
                .order_by(desc(HyperbolicReplayRun.started_at))
                .limit(20)
            ).all()
            average_duration = mean(float(value) for value in durations) if durations else 0.0
            dataset_rows = int(db.scalar(select(func.count(ReplayMarketBar.id))) or 0)
        return ReplayResourceSample(
            cpu_percent=float(psutil.cpu_percent(interval=None)),
            memory_percent=float(psutil.virtual_memory().percent),
            api_p95_ms=api_p95,
            active_jobs=active_jobs,
            average_batch_duration_seconds=average_duration,
            dataset_rows=dataset_rows,
        )


class ReplayTrainingSnapshotService:
    def snapshot(self, db: Session) -> dict:
        snapshot = DashboardSnapshotService().latest(db, REPLAY_SNAPSHOT_TYPE)
        if not snapshot.get("payload"):
            return self.defaults(snapshot_status="missing")
        return {**self.defaults(snapshot_status=snapshot.get("status", "ready")), **dict(snapshot["payload"]), "last_snapshot_timestamp": snapshot.get("created_at")}

    def write(self, db: Session, payload: dict) -> dict:
        warnings = list(payload.get("warnings") or [])
        DashboardSnapshotService().write(
            db,
            REPLAY_SNAPSHOT_TYPE,
            {**self.defaults(snapshot_status="ready"), **payload},
            source_modules={"engine": "BlumHyperbolicReplayEngine", "controller": "BlumAdaptiveTrainingController"},
            ttl_seconds=1800,
            warnings=warnings,
        )
        return self.snapshot(db)

    @staticmethod
    def defaults(*, snapshot_status: str) -> dict:
        settings = get_settings()
        return {
            "replay_engine_status": "INITIALIZING",
            "trades_replayed_today": 0,
            "validated_trades_today": 0,
            "target_trades_per_day": int(settings.replay_target_validated_trades_per_day),
            "throughput_percent": 0.0,
            "markets_replayed": [],
            "timeframes_replayed": [],
            "active_experiments": 0,
            "completed_experiments": 0,
            "promoted_strategies": 0,
            "rejected_no_edge": 0,
            "rejected_overfitting": 0,
            "rejected_unstable": 0,
            "current_cpu_budget": None,
            "current_memory_budget": None,
            "adaptive_training_state": "BUDGET_WAIT",
            "latest_replay_run_at": None,
            "latest_productive_run_at": None,
            "reason_if_target_missed": "No replay training snapshot has been produced yet.",
            "warnings": [],
            "snapshot_status": snapshot_status,
            "evidence_policy": "Replay evidence remains separate from paper-forward and live-forward evidence.",
            "strategy_factory": {"status": "NO_FACTORY_RUNS", "examined_variants": 0, "promoted_to_paper": 0},
            "promotion_frontier": {"status": "NO_EXECUTABLE_CANDIDATES", "candidates": []},
            "research_strategy_fingerprints": [],
        }


def refresh_strategy_factory_state(db: Session) -> dict:
    """Refresh only the factory projection after its independent worker completes."""

    service = ReplayTrainingSnapshotService()
    current = service.snapshot(db)
    current.pop("last_snapshot_timestamp", None)
    current["strategy_factory"] = strategy_factory_snapshot(db)
    return service.write(db, current)


class BlumAdaptiveTrainingController:
    def __init__(
        self,
        *,
        engine: BlumHyperbolicReplayEngine | None = None,
        resource_monitor: ReplayResourceMonitor | None = None,
        config: ReplayTrainingConfig | None = None,
        promotion_frontier: StrategyPromotionFrontierService | None = None,
    ):
        self.engine = engine or BlumHyperbolicReplayEngine()
        self.resource_monitor = resource_monitor or ReplayResourceMonitor()
        self.config = config or ReplayTrainingConfig.from_settings()
        self.promotion_frontier = promotion_frontier or StrategyPromotionFrontierService(
            minimum_samples=self.config.min_promotion_samples
        )

    def run_once(self, db: Session, trigger: str = "manual") -> dict:
        started = time.perf_counter()
        resources = self.resource_monitor.read(db)
        state = self._state(resources)
        limits = self._limits(state)
        job_state = BackgroundJobStateService()
        existing = db.scalar(
            select(BackgroundJobState).where(
                BackgroundJobState.job_name == "hyperbolic_replay_training",
                BackgroundJobState.stage_name == "replay_slice",
            )
        )
        cursor = dict(existing.cursor_json or {}) if existing else {}
        if state in {"PAUSED_FOR_RUNTIME", "BUDGET_WAIT"}:
            reason = (
                "Replay paused because CPU, memory, or API latency exceeded the runtime safety budget."
                if state == "PAUSED_FOR_RUNTIME"
                else "Replay is waiting because the configured background-job concurrency budget is in use."
            )
            payload = self._snapshot_payload(
                db,
                run_summary={"status": state, "trades_generated": 0, "trades_validated": 0, "markets_selected": [], "timeframes_used": [], "blockers": []},
                resources=resources,
                state=state,
                reason=reason,
            )
            return ReplayTrainingSnapshotService().write(db, payload)

        job_state.start(
            db,
            "hyperbolic_replay_training",
            stage_name="replay_slice",
            max_items=limits["max_trades"],
            cursor=cursor,
        )
        try:
            research_plan = self.promotion_frontier.research_plan(
                db,
                limit=limits["max_experiments"],
                seed=int(datetime.utcnow().timestamp() // 900),
                selection_history=dict(cursor.get("research_selection_history") or {}),
            )
            run_summary = self.engine.run_cycle(
                db,
                ReplayRunRequest(
                    max_assets=limits["max_assets"],
                    max_trades=limits["max_trades"],
                    max_seconds=limits["max_seconds"],
                    trigger=trigger,
                    fetch_missing=True,
                    after_asset_id=cursor.get("asset_id"),
                    markets=list(self.config.markets),
                    timeframes=self.config.timeframes,
                    strategy_specs=tuple(research_plan["specs"]) or None,
                ),
            )
            run_summary["research_strategy_fingerprints"] = [
                row["strategy_fingerprint"] for row in research_plan["reasons"]
            ]
            run_summary["research_selection"] = research_plan
            selection_history = _updated_selection_history(
                dict(cursor.get("research_selection_history") or {}),
                research_plan.get("reasons") or [],
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - started) * 1000
            job_state.fail(
                db,
                "hyperbolic_replay_training",
                stage_name="replay_slice",
                duration_ms=duration_ms,
                error_message=str(exc),
            )
            payload = self._snapshot_payload(
                db,
                run_summary={"status": "ERROR", "trades_generated": 0, "trades_validated": 0, "markets_selected": [], "timeframes_used": [], "blockers": [{"code": "REPLAY_RUNTIME_ERROR"}]},
                resources=resources,
                state="ERROR",
                reason="Replay cycle failed; the persisted cursor is retained for the next isolated retry.",
            )
            return ReplayTrainingSnapshotService().write(db, payload)
        learning = self._apply_learning(db, run_summary)
        run_summary["experiments_run"] = learning["experiments_run"]
        run_summary["strategies_promoted"] = learning["strategies_promoted"]
        run_summary["strategies_rejected"] = learning["strategies_rejected"]
        run_summary["memory_updates"] = learning["memory_updates"]
        reason = self._miss_reason(run_summary, state)
        payload = self._snapshot_payload(db, run_summary=run_summary, resources=resources, state=state, reason=reason)
        payload["resource_limits_applied"] = limits
        payload["controller_runtime_seconds"] = round(time.perf_counter() - started, 4)
        snapshot = ReplayTrainingSnapshotService().write(db, payload)
        job_state.complete(
            db,
            "hyperbolic_replay_training",
            stage_name="replay_slice",
            duration_ms=(time.perf_counter() - started) * 1000,
            items_processed=int(run_summary.get("trades_validated") or 0),
            cursor={
                **dict(run_summary.get("next_cursor") or {}),
                "research_selection_history": selection_history,
            },
            payload={"run_id": run_summary.get("run_id"), "state": state},
        )
        return {**run_summary, **snapshot, "adaptive_training_state": state, "resource_limits_applied": limits}

    def _state(self, sample: ReplayResourceSample) -> str:
        if sample.active_jobs >= 4:
            return "BUDGET_WAIT"
        if sample.cpu_percent >= self.config.cpu_pause_percent or sample.memory_percent >= self.config.memory_pause_percent or sample.api_p95_ms >= self.config.api_pause_p95_ms:
            return "PAUSED_FOR_RUNTIME"
        if sample.cpu_percent >= self.config.cpu_throttle_percent or sample.memory_percent >= self.config.memory_throttle_percent or sample.api_p95_ms >= self.config.api_throttle_p95_ms:
            return "THROTTLED"
        return "RUNNING"

    def _limits(self, state: str) -> dict:
        factor = 0.35 if state == "THROTTLED" else 1.0
        return {
            "max_seconds": max(5, int(self.config.max_seconds_per_cycle * factor)),
            "max_assets": max(1, int(self.config.max_assets_per_cycle * factor)),
            "max_trades": max(1, int(self.config.max_trades_per_cycle * factor)),
            "max_experiments": max(1, int(self.config.max_experiments_per_cycle * factor)),
        }

    def _apply_learning(self, db: Session, run_summary: dict) -> dict:
        run = db.scalar(select(HyperbolicReplayRun).where(HyperbolicReplayRun.run_id == run_summary.get("run_id")))
        if run is None:
            return {"memory_updates": 0, "experiments_run": 0, "strategies_promoted": 0, "strategies_rejected": 0}
        trades = db.scalars(select(HyperbolicReplayTrade).where(HyperbolicReplayTrade.run_id == run.id)).all()
        feedback = ReplayLearningFeedbackService()
        memory_updates = 0
        for trade in trades:
            result = feedback.apply_evaluated_trade(db, trade)
            memory_updates += int(result.get("status") == "applied")
        grouped: dict[str, list[HyperbolicReplayTrade]] = {}
        for trade in trades:
            grouped.setdefault(trade.strategy_fingerprint, []).append(trade)
        experiments_run = 0
        promoted = 0
        rejected = 0
        experiment_service = ReplayExperimentService(self._limits("RUNNING")["max_experiments"])
        validator = ReplayWalkForwardValidator(min_sample_size=self.config.min_promotion_samples)
        for strategy_fingerprint, rows in list(grouped.items())[: self.config.max_experiments_per_cycle]:
            setup_type = rows[0].setup_type
            variant = experiment_service.bounded_variants(
                {
                    "setup_type": setup_type,
                    "strategy_fingerprint": strategy_fingerprint,
                    "executable_strategy": (rows[0].decision_payload or {}).get("executable_strategy"),
                    "market": rows[0].market,
                    "timeframes": [rows[0].timeframe],
                }
            )[0]
            experiment = experiment_service.persist(
                db,
                variant,
                training_window={"mode": "chronological_replay", "start": rows[0].decision_timestamp.isoformat(), "end": rows[-1].decision_timestamp.isoformat()},
                validation_window={"mode": "walk_forward_validation", "evidence_type": "WALK_FORWARD_EVIDENCE"},
            )
            all_rows = db.scalars(
                select(HyperbolicReplayTrade)
                .where(
                    HyperbolicReplayTrade.strategy_fingerprint == strategy_fingerprint,
                    HyperbolicReplayTrade.state == "REPLAY_EVALUATED",
                )
                .order_by(HyperbolicReplayTrade.decision_timestamp)
                .limit(5000)
            ).all()
            evidence = _validation_evidence(all_rows)
            validation = validator.persist(db, experiment=experiment, evidence=evidence)
            promotion = feedback.apply_validation(db, validation)
            promoted += int(promotion.get("status") == "promoted")
            rejected += int(validation.verdict.startswith("REJECTED"))
            experiments_run += 1
        run.experiments_run = experiments_run
        summary = dict(run.summary_json or {})
        summary["learning_feedback"] = {"memory_updates": memory_updates, "experiments_run": experiments_run, "strategies_promoted": promoted, "strategies_rejected": rejected}
        summary["research_selection"] = run_summary.get("research_selection") or {}
        run.summary_json = summary
        db.commit()
        return {"memory_updates": memory_updates, "experiments_run": experiments_run, "strategies_promoted": promoted, "strategies_rejected": rejected}

    def _snapshot_payload(self, db: Session, *, run_summary: dict, resources: ReplayResourceSample, state: str, reason: str) -> dict:
        start_today = datetime.combine(datetime.utcnow().date(), day_time.min)
        totals = db.execute(
            select(
                func.coalesce(func.sum(HyperbolicReplayRun.trades_generated), 0),
                func.coalesce(func.sum(HyperbolicReplayRun.trades_validated), 0),
            ).where(HyperbolicReplayRun.started_at >= start_today)
        ).one()
        generated_today = int(totals[0] or run_summary.get("trades_generated") or 0)
        validated_today = int(totals[1] or run_summary.get("trades_validated") or 0)
        latest_productive = db.scalar(
            select(HyperbolicReplayRun)
            .where(HyperbolicReplayRun.trades_validated > 0)
            .order_by(desc(HyperbolicReplayRun.completed_at))
            .limit(1)
        )
        verdicts = dict(
            db.execute(select(ReplayStrategyValidation.verdict, func.count(ReplayStrategyValidation.id)).group_by(ReplayStrategyValidation.verdict)).all()
        )
        unresolved_statuses = ["PROPOSED", "TESTING", "NEEDS_MORE_EVIDENCE"]
        active = db.scalar(select(func.count(BlumLearningExperiment.id)).where(BlumLearningExperiment.status.in_(unresolved_statuses))) or 0
        completed = db.scalar(select(func.count(BlumLearningExperiment.id)).where(~BlumLearningExperiment.status.in_(unresolved_statuses))) or 0
        dataset_rows = int(db.scalar(select(func.count(ReplayMarketBar.id))) or 0)
        return {
            "replay_engine_status": run_summary.get("status", state),
            "trades_replayed_today": generated_today,
            "validated_trades_today": validated_today,
            "target_trades_per_day": self.config.target_trades_per_day,
            "throughput_percent": round(min(100.0, validated_today / self.config.target_trades_per_day * 100), 2),
            "markets_replayed": run_summary.get("markets_selected") or [],
            "timeframes_replayed": run_summary.get("timeframes_used") or [],
            "active_experiments": int(active),
            "completed_experiments": int(completed),
            "promoted_strategies": int(verdicts.get("PROMOTED_TO_PAPER", 0)),
            "rejected_no_edge": int(verdicts.get("REJECTED_NO_EDGE", 0)),
            "rejected_overfitting": int(verdicts.get("REJECTED_OVERFITTING", 0)),
            "rejected_unstable": int(verdicts.get("REJECTED_UNSTABLE", 0)),
            "current_cpu_budget": round(resources.cpu_percent, 2),
            "current_memory_budget": round(resources.memory_percent, 2),
            "api_p95_ms": round(resources.api_p95_ms, 2),
            "active_jobs": resources.active_jobs,
            "average_batch_duration_seconds": round(resources.average_batch_duration_seconds, 4),
            "dataset_rows": dataset_rows,
            "adaptive_training_state": state,
            "latest_replay_run_at": datetime.utcnow().isoformat(),
            "latest_productive_run_at": latest_productive.completed_at.isoformat() if latest_productive and latest_productive.completed_at else None,
            "reason_if_target_missed": reason,
            "blockers": run_summary.get("blockers") or [],
            "warnings": [reason] if reason and validated_today < self.config.target_trades_per_day else [],
            "strategy_factory": strategy_factory_snapshot(db),
            "promotion_frontier": self.promotion_frontier.snapshot(db),
            "research_strategy_fingerprints": run_summary.get("research_strategy_fingerprints") or [],
            "useful_evidence_ratio": round(
                int(run_summary.get("trades_validated") or 0)
                / max(1, int(run_summary.get("trades_generated") or 0)),
                4,
            ),
            "research_selection_mix": (run_summary.get("research_selection") or {}).get("selection_mix") or {},
            "stalled_strategy_rotations": int(
                (run_summary.get("research_selection") or {}).get("stalled_rotations") or 0
            ),
            "research_queue_starved": bool(
                (run_summary.get("research_selection") or {}).get("specs") == []
                and (run_summary.get("research_selection") or {}).get("reasons") == []
            ),
        }

    def _miss_reason(self, summary: dict, state: str) -> str:
        if int(summary.get("trades_validated") or 0) > 0:
            return "Daily target remains in progress; continue bounded replay cycles."
        if state == "THROTTLED":
            return "Runtime load throttled replay intensity."
        blockers = summary.get("blockers") or []
        if blockers:
            return "No validated trades in this cycle because verified timeframe coverage or setup eligibility was insufficient."
        return "No eligible cost-adjusted replay setup was produced in this bounded cycle."


def _validation_evidence(rows: list[HyperbolicReplayTrade]) -> dict:
    r_values = [float(row.r_multiple or 0.0) for row in rows]
    markets = sorted({row.market for row in rows if row.market})
    sample = len(rows)
    window_size = max(1, sample // 3)
    windows = []
    for index in range(0, sample, window_size):
        subset = r_values[index : index + window_size]
        if subset:
            windows.append({"index": len(windows) + 1, "sample_size": len(subset), "expectancy_r": round(mean(subset), 6)})
    drawdown = _max_drawdown_r(r_values)
    benchmark_values = [float(row.benchmark_excess) for row in rows if row.benchmark_excess is not None]
    wins = [value for value in r_values if value > 0]
    losses = [value for value in r_values if value < 0]
    average_r = mean(r_values) if r_values else 0.0
    standard_deviation = _standard_deviation(r_values)
    downside_deviation = _standard_deviation([min(0.0, value) for value in r_values])
    regime_groups: dict[str, list[float]] = {}
    for row, r_value in zip(rows, r_values):
        regime = str((row.decision_payload or {}).get("regime") or "unknown")
        regime_groups.setdefault(regime, []).append(r_value)
    regime_expectancy = {key: round(mean(values), 6) for key, values in regime_groups.items() if values}
    return {
        "sample_size": sample,
        "markets": markets,
        "windows": windows,
        "benchmark_excess": mean(benchmark_values) if benchmark_values else 0.0,
        "expectancy_r": average_r,
        "average_r": average_r,
        "win_rate": len(wins) / sample * 100 if sample else 0.0,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "sharpe_proxy": average_r / standard_deviation * sqrt(sample) if standard_deviation > 0 else 0.0,
        "sortino_proxy": average_r / downside_deviation * sqrt(sample) if downside_deviation > 0 else 0.0,
        "max_drawdown": drawdown,
        "overfitting_score": 20.0 if sample >= 300 and len(markets) >= 2 else 70.0,
        "stability_score": _stability_score(windows),
        "out_of_sample_improvement": False,
        "evidence_type": "WALK_FORWARD_EVIDENCE",
        "benchmark_status": "available" if benchmark_values else "missing",
        "regime_dependency": {
            "expectancy_by_regime": regime_expectancy,
            "regimes_observed": len(regime_expectancy),
        },
    }


def _max_drawdown_r(values: list[float]) -> float:
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return round(drawdown, 6)


def _stability_score(windows: list[dict]) -> float:
    if len(windows) < 2:
        return 0.0
    positive = sum(1 for row in windows if float(row["expectancy_r"]) > 0)
    return round(positive / len(windows) * 100, 2)


def _updated_selection_history(existing: dict, reasons: list[dict], *, maximum: int = 100) -> dict:
    history = {
        str(key): dict(value)
        for key, value in existing.items()
        if isinstance(value, dict)
    }
    for row in reasons:
        fingerprint = str(row.get("strategy_fingerprint") or "")
        if not fingerprint:
            continue
        sample_size = int(row.get("sample_size") or 0)
        previous = history.get(fingerprint) or {}
        no_progress = (
            int(previous.get("consecutive_no_progress") or 0) + 1
            if previous and sample_size <= int(previous.get("last_sample_size") or 0)
            else 0
        )
        history[fingerprint] = {
            "last_sample_size": sample_size,
            "consecutive_no_progress": no_progress,
        }
    return dict(list(history.items())[-max(1, int(maximum)):])


def _standard_deviation(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    average = mean(values)
    return (sum((value - average) ** 2 for value in values) / len(values)) ** 0.5
