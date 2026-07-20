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

    def research_plan(self, db: Session, *, limit: int, seed: int) -> dict[str, Any]:
        bounded_limit = max(1, int(limit))
        rows = self._candidates(db)
        records = [
            (candidate, validation, self._project(candidate, validation))
            for candidate, validation in rows
        ]
        records.sort(key=lambda item: (item[2]["frontier_score"], item[2]["sample_size"]), reverse=True)
        near_count = bounded_limit if bounded_limit == 1 else max(1, bounded_limit - 1)
        selected = records[:near_count]
        selected_ids = {candidate.id for candidate, _, _ in selected}
        exploration = [row for row in records if row[0].id not in selected_ids]
        random.Random(int(seed)).shuffle(exploration)
        selected.extend(exploration[: bounded_limit - len(selected)])
        specs: list[dict] = []
        reasons: list[dict] = []
        for index, (candidate, _, projection) in enumerate(selected):
            specification = dict(candidate.specification_json or {})
            executable = specification.get("executable_strategy")
            if not isinstance(executable, dict) or not executable:
                continue
            specs.append(dict(executable))
            reasons.append(
                {
                    "strategy_fingerprint": candidate.fingerprint,
                    "reason": "near_frontier" if index < near_count else "broad_exploration",
                    "sample_gap": projection["sample_gap"],
                    "frontier_score": projection["frontier_score"],
                }
            )
        exploration_count = sum(1 for row in reasons if row["reason"] == "broad_exploration")
        return {
            "specs": specs,
            "reasons": reasons,
            "selection_mix": {
                "near_frontier": len(reasons) - exploration_count,
                "broad_exploration": exploration_count,
            },
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
            if not isinstance(specification.get("executable_strategy"), dict):
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
