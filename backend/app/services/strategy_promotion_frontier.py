from __future__ import annotations

import random
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import ReplayStrategyValidation, StrategyCandidateVariant


class StrategyPromotionFrontierService:
    """Read-only research projection for executable strategies awaiting evidence."""

    def __init__(self, *, minimum_samples: int = 300):
        self.minimum_samples = max(300, int(minimum_samples))

    def snapshot(self, db: Session, limit: int = 20) -> dict[str, Any]:
        candidates = self._candidates(db)
        projected = [self._project(candidate, validation) for candidate, validation in candidates]
        projected.sort(key=lambda row: (row["frontier_score"], row["sample_size"]), reverse=True)
        return {
            "status": "READY" if projected else "NO_EXECUTABLE_CANDIDATES",
            "minimum_samples": self.minimum_samples,
            "candidate_count": len(projected),
            "candidates": projected[: max(1, int(limit))],
            "policy": "Research priority does not weaken promotion, cost, robustness, or forward-evidence gates.",
        }

    def research_specs(self, db: Session, *, limit: int, seed: int) -> tuple[dict, ...]:
        return tuple(self.research_plan(db, limit=limit, seed=seed)["specs"])

    def research_plan(
        self,
        db: Session,
        *,
        limit: int,
        seed: int,
        selection_history: dict[str, dict] | None = None,
    ) -> dict[str, Any]:
        bounded_limit = max(1, int(limit))
        rows = self._candidates(db)
        records = [
            (candidate, validation, self._project(candidate, validation))
            for candidate, validation in rows
        ]
        records.sort(key=lambda item: (item[2]["frontier_score"], item[2]["sample_size"]), reverse=True)
        history = selection_history or {}
        stalled = {
            candidate.fingerprint
            for candidate, _, projection in records
            if _stalled(history.get(candidate.fingerprint), projection["sample_size"])
        }
        allow_stalled_probe = int(seed) % 4 == 0
        preferred = [row for row in records if allow_stalled_probe or row[0].fingerprint not in stalled]
        deferred = [row for row in records if row[0].fingerprint in stalled and row not in preferred]
        rng = random.Random(int(seed))

        selected: list[tuple[Any, Any, dict, str]] = []
        selected_ids: set[int] = set()

        def take(pool, count: int, lane: str, *, shuffle: bool = False) -> None:
            available = [row for row in pool if row[0].id not in selected_ids]
            if shuffle:
                rng.shuffle(available)
            for row in available[: max(0, count)]:
                selected.append((*row, lane))
                selected_ids.add(row[0].id)

        if bounded_limit == 1:
            explore = len(records) > 1 and int(seed) % 10 < 3
            pool = list(preferred or deferred)
            take(pool, 1, "broad_exploration" if explore else "promotion_frontier", shuffle=explore)
        else:
            broad_slots = 1
            failure_slots = max(1, bounded_limit // 4) if bounded_limit >= 3 else 0
            coverage_slots = max(1, bounded_limit // 8) if bounded_limit >= 4 else 0
            frontier_slots = max(1, bounded_limit - broad_slots - failure_slots - coverage_slots)
            promotable = [row for row in preferred if _promising(row[2])]
            failures = [row for row in preferred if not _promising(row[2])]
            take(promotable, frontier_slots, "promotion_frontier")
            take(failures, failure_slots, "failure_replay")
            take(promotable, coverage_slots, "coverage_gap")
            take([*preferred, *deferred], broad_slots, "broad_exploration", shuffle=True)
            take([*preferred, *deferred], bounded_limit - len(selected), "broad_exploration")

        specs: list[dict] = []
        reasons: list[dict] = []
        for candidate, _, projection, lane in selected[:bounded_limit]:
            specification = dict(candidate.specification_json or {})
            executable = specification.get("executable_strategy")
            if not isinstance(executable, dict) or not executable:
                continue
            specs.append(dict(executable))
            reasons.append(
                {
                    "strategy_fingerprint": candidate.fingerprint,
                    "reason": lane,
                    "sample_size": projection["sample_size"],
                    "sample_gap": projection["sample_gap"],
                    "frontier_score": projection["frontier_score"],
                }
            )
        lanes = ("promotion_frontier", "failure_replay", "coverage_gap", "broad_exploration")
        return {
            "specs": specs,
            "reasons": reasons,
            "selection_mix": {lane: sum(1 for row in reasons if row["reason"] == lane) for lane in lanes},
            "stalled_rotations": len(stalled) if not allow_stalled_probe else 0,
        }

    @staticmethod
    def _candidates(db: Session) -> list[tuple[StrategyCandidateVariant, ReplayStrategyValidation | None]]:
        rows = db.scalars(
            select(StrategyCandidateVariant)
            .where(StrategyCandidateVariant.is_champion.is_(False))
            .order_by(desc(StrategyCandidateVariant.updated_at), desc(StrategyCandidateVariant.id))
            .limit(500)
        ).all()
        output = []
        for candidate in rows:
            specification = dict(candidate.specification_json or {})
            executable = specification.get("executable_strategy")
            if not isinstance(executable, dict):
                continue
            if (
                executable.get("regime_filter") == "trend_down_only"
                and number(executable.get("higher_timeframe_min_trend"), 0.0) >= 0.0
            ):
                continue
            validation = db.get(ReplayStrategyValidation, candidate.validation_id) if candidate.validation_id else None
            output.append((candidate, validation))
        return output

    def _project(
        self,
        candidate: StrategyCandidateVariant,
        validation: ReplayStrategyValidation | None,
    ) -> dict[str, Any]:
        metrics = dict(validation.metrics_json or {}) if validation else {}
        sample_size = int(validation.sample_size or 0) if validation else 0
        expectancy = number(metrics.get("net_expectancy_r"), number(metrics.get("expectancy_r"), 0.0))
        benchmark_excess = number(metrics.get("benchmark_excess"), 0.0)
        cost_coverage = number(metrics.get("cost_coverage"), 0.0)
        stability = number(metrics.get("experimental_stability_score"), number(metrics.get("stability_score"), 0.0))
        data_quality = number(metrics.get("data_quality_score"), 0.0)
        overfitting = (
            100.0
            if validation is None or validation.overfitting_score is None
            else float(validation.overfitting_score)
        )
        blockers = []
        if sample_size < self.minimum_samples:
            blockers.append("INSUFFICIENT_SAMPLE")
        if expectancy <= 0:
            blockers.append("NON_POSITIVE_EXPECTANCY")
        if benchmark_excess <= 0:
            blockers.append("NO_BENCHMARK_EXCESS")
        if cost_coverage < 1.0:
            blockers.append("INCOMPLETE_COST_EVIDENCE")
        if overfitting >= 70.0:
            blockers.append("OVERFITTING_RISK")
        frontier_score = (
            min(50.0, sample_size / self.minimum_samples * 50.0)
            + min(15.0, max(0.0, expectancy) * 60.0)
            + min(10.0, max(0.0, benchmark_excess) * 5.0)
            + min(15.0, stability * 0.15)
            + min(10.0, data_quality * 0.1)
            - max(0.0, overfitting - 40.0) * 0.25
        )
        return {
            "candidate_id": candidate.id,
            "strategy_fingerprint": candidate.fingerprint,
            "setup_type": candidate.setup_type,
            "sample_size": sample_size,
            "sample_gap": max(0, self.minimum_samples - sample_size),
            "expectancy_r": expectancy,
            "benchmark_excess": benchmark_excess,
            "cost_coverage": cost_coverage,
            "stability_score": stability,
            "overfitting_score": overfitting,
            "frontier_score": round(max(0.0, min(100.0, frontier_score)), 4),
            "blockers": blockers,
            "verdict": validation.verdict if validation else "NOT_VALIDATED",
        }


def number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _promising(projection: dict[str, Any]) -> bool:
    return (
        number(projection.get("expectancy_r"), 0.0) > 0
        and number(projection.get("benchmark_excess"), 0.0) > 0
        and number(projection.get("cost_coverage"), 0.0) >= 1.0
        and number(projection.get("overfitting_score"), 100.0) < 70.0
    )


def _stalled(history: dict | None, current_sample_size: int) -> bool:
    if not isinstance(history, dict):
        return False
    return (
        int(history.get("consecutive_no_progress") or 0) >= 3
        and int(history.get("last_sample_size") or 0) >= int(current_sample_size)
    )
