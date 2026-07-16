from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import hashlib
from itertools import product
import json
import random
from statistics import mean
from uuid import uuid4

from scipy.stats import ttest_1samp
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import (
    HyperbolicReplayTrade,
    ReplayStrategyValidation,
    StrategyCandidateVariant,
    StrategyFactoryRun,
    StrategyPromotionEvent,
    StrategyValidationFold,
)
from app.services.strategy_factory_statistics import (
    backtest_overfitting_probability,
    benjamini_hochberg,
    build_purged_folds,
    deflated_sharpe_probability,
    evaluate_strategy_robustness,
)


FAMILY_DEFINITIONS: dict[str, dict] = {
    "momentum": {"setup_type": "momentum_breakout", "entries": ["close_breakout", "relative_strength_reclaim"]},
    "trend_following": {"setup_type": "trend_continuation", "entries": ["ma_alignment", "weekly_trend_confirmed"]},
    "breakout": {"setup_type": "swing_breakout", "entries": ["close_breakout", "breakout_retest"]},
    "pullback": {"setup_type": "pullback", "entries": ["ma20_reversal", "ma50_reclaim"]},
    "mean_reversion": {"setup_type": "mean_reversion", "entries": ["rsi_reversion", "bollinger_reclaim"]},
    "volatility_expansion": {"setup_type": "volatility_squeeze", "entries": ["squeeze_release", "atr_expansion"]},
    "earnings_news_reaction": {"setup_type": "post_earnings_drift", "entries": ["gap_hold", "post_event_reclaim"]},
    "relative_strength": {"setup_type": "sector_rotation_entry", "entries": ["benchmark_breakout", "sector_leadership"]},
    "cross_sectional_ranking": {"setup_type": "cross_sectional_momentum", "entries": ["top_decile", "top_quintile"]},
    "intraday_scalping": {
        "setup_type": "intraday_breakout",
        "replay_setup_types": ["intraday_breakout", "intraday_trend"],
        "entries": ["one_minute_breakout", "five_minute_pullback"],
        "timeframe_stack": ["1d", "15m", "5m", "1m"],
        "holding_periods": [15, 45],
    },
}

REPLAY_IMPLEMENTATIONS: dict[str, dict] = {
    "swing_breakout": {"entry_rule": "close_breakout", "stop_rule": "atr_or_one_percent", "target_rule": "two_r", "holding_period": 20},
    "pullback": {"entry_rule": "pullback_signal", "stop_rule": "atr_or_one_percent", "target_rule": "two_r", "holding_period": 20},
    "mean_reversion": {"entry_rule": "mean_reversion_signal", "stop_rule": "atr_or_one_percent", "target_rule": "two_r", "holding_period": 20},
    "intraday_breakout": {"entry_rule": "close_breakout", "stop_rule": "atr_or_one_percent", "target_rule": "two_r", "holding_period": 20},
    "intraday_trend": {"entry_rule": "five_minute_breakout", "stop_rule": "atr_or_one_percent", "target_rule": "two_r", "holding_period": 20},
}


class StrategyFamilyRegistry:
    def names(self) -> tuple[str, ...]:
        return tuple(FAMILY_DEFINITIONS)

    def variants(self, family: str, *, max_variants: int, seed: int) -> list[dict]:
        definition = FAMILY_DEFINITIONS.get(family)
        if definition is None:
            raise KeyError(f"unknown strategy family: {family}")
        timeframe_stack = list(definition.get("timeframe_stack") or ["1d"])
        holding_periods = list(definition.get("holding_periods") or [10, 20])
        combinations = [
            (definition["setup_type"], *combination)
            for combination in product(
                definition["entries"],
                ["atr_1_5", "structure"],
                ["two_r", "trailing_atr"],
                holding_periods,
                ["all", "aligned_only"],
            )
        ]
        random.Random(int(seed)).shuffle(combinations)
        variants: list[dict] = []
        canonical_combinations = []
        for setup_type in definition.get("replay_setup_types") or [definition["setup_type"]]:
            canonical = REPLAY_IMPLEMENTATIONS.get(setup_type)
            if canonical:
                canonical_combinations.append(
                    (
                        setup_type,
                        canonical["entry_rule"],
                        canonical["stop_rule"],
                        canonical["target_rule"],
                        canonical["holding_period"],
                        "all",
                    )
                )
        combinations = canonical_combinations + combinations
        seen: set[tuple] = set()
        for setup_type, entry, stop, target, holding, regime_filter in combinations:
            combination = (setup_type, entry, stop, target, holding, regime_filter)
            if combination in seen:
                continue
            seen.add(combination)
            canonical = REPLAY_IMPLEMENTATIONS.get(setup_type)
            variants.append(
                {
                    "family": family,
                    "setup_type": setup_type,
                    "market": "global",
                    "asset_class": "stocks,etfs",
                    "benchmark_ticker": "SPY",
                    "timeframe_stack": timeframe_stack,
                    "entry_rule": entry,
                    "stop_rule": stop,
                    "target_rule": target,
                    "holding_period": holding,
                    "regime_filter": regime_filter,
                    "complexity": 5,
                    "execution_model": "realistic_execution_v1",
                    "evidence_binding": "hyperbolic_replay_v1" if canonical and combination[1:5] == (
                        canonical["entry_rule"],
                        canonical["stop_rule"],
                        canonical["target_rule"],
                        canonical["holding_period"],
                    ) else "not_implemented",
                }
            )
            if len(variants) >= max(1, int(max_variants)):
                break
        return variants


class ChampionChallengerRegistry:
    def promote(
        self,
        db: Session,
        candidate: StrategyCandidateVariant,
        validation: ReplayStrategyValidation,
    ) -> dict:
        if validation.verdict != "PROMOTED_TO_PAPER" or int(validation.sample_size or 0) < 300:
            return {"status": "not_promoted", "reason": "certification gates are not satisfied"}
        registry_key = self.registry_key(candidate)
        if candidate.is_champion:
            return {
                "status": "already_champion",
                "candidate_id": candidate.id,
                "previous_candidate_id": None,
                "registry_key": registry_key,
                "reversible": True,
            }
        champions = db.scalars(
            select(StrategyCandidateVariant).where(
                StrategyCandidateVariant.family == candidate.family,
                StrategyCandidateVariant.market == candidate.market,
                StrategyCandidateVariant.asset_class == candidate.asset_class,
                StrategyCandidateVariant.is_champion.is_(True),
            )
        ).all()
        previous = next((row for row in champions if list(row.timeframe_stack or []) == list(candidate.timeframe_stack or [])), None)
        if previous is not None:
            previous.is_champion = False
            previous.lifecycle_state = "CHALLENGER_REPLACED"
        candidate.is_champion = True
        candidate.lifecycle_state = "PROMOTED"
        candidate.final_verdict = "PROMOTED_TO_PAPER"
        event = StrategyPromotionEvent(
            candidate_id=candidate.id,
            validation_id=validation.id,
            previous_candidate_id=previous.id if previous else None,
            registry_key=registry_key,
            event_type="PROMOTED",
            reason=validation.explanation,
            evidence_json={
                "sample_size": validation.sample_size,
                "metrics": validation.metrics_json,
                "previous_candidate_id": previous.id if previous else None,
            },
            reversible=True,
        )
        db.add(event)
        db.flush()
        return {
            "status": "promoted",
            "candidate_id": candidate.id,
            "previous_candidate_id": previous.id if previous else None,
            "registry_key": registry_key,
            "reversible": True,
            "event_id": event.id,
        }

    @staticmethod
    def registry_key(candidate: StrategyCandidateVariant) -> str:
        stack = "-".join(candidate.timeframe_stack or ["1d"])
        return f"{candidate.family}:{candidate.market}:{candidate.asset_class}:{stack}"


class AlphaStrategyFactory:
    def __init__(self, registry: StrategyFamilyRegistry | None = None, champions: ChampionChallengerRegistry | None = None):
        self.registry = registry or StrategyFamilyRegistry()
        self.champions = champions or ChampionChallengerRegistry()

    def run_once(
        self,
        db: Session,
        *,
        families: list[str] | None = None,
        max_variants_per_family: int = 4,
        seed: int = 7,
        trigger: str = "scheduled",
    ) -> dict:
        selected = families or list(self.registry.names())
        selected_families = [str(family) for family in selected]
        now = datetime.utcnow()
        run = StrategyFactoryRun(
            run_uid=f"factory-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
            hypothesis_family=factory_hypothesis_key(selected_families),
            generation_seed=int(seed),
            status="RUNNING",
            budgets_json={
                "max_variants_per_family": max_variants_per_family,
                "trigger": trigger,
                "selected_families": selected_families,
            },
        )
        db.add(run)
        db.flush()
        specifications = [
            specification
            for family in selected
            for specification in self.registry.variants(family, max_variants=max_variants_per_family, seed=seed)
        ]
        new_candidates: list[StrategyCandidateVariant] = []
        evaluation_candidates: list[StrategyCandidateVariant] = []
        for specification in specifications:
            fingerprint = strategy_fingerprint(specification)
            existing = db.scalar(select(StrategyCandidateVariant).where(StrategyCandidateVariant.fingerprint == fingerprint))
            if existing is not None:
                if self._has_new_evidence(db, existing):
                    existing.lifecycle_state = "REVALIDATING"
                    evaluation_candidates.append(existing)
                continue
            candidate = StrategyCandidateVariant(
                factory_run_id=run.id,
                fingerprint=fingerprint,
                family=specification["family"],
                setup_type=specification["setup_type"],
                market=specification["market"],
                asset_class=specification["asset_class"],
                timeframe_stack=specification["timeframe_stack"],
                specification_json=specification,
                complexity=specification["complexity"],
                benchmark_ticker=specification["benchmark_ticker"],
                lifecycle_state="VALIDATING",
            )
            db.add(candidate)
            db.flush()
            new_candidates.append(candidate)
            evaluation_candidates.append(candidate)

        evidence_by_candidate = [(candidate, self._candidate_evidence(db, candidate)) for candidate in evaluation_candidates]
        corrections = benjamini_hochberg(
            [float(evidence.get("raw_p_value") or 1.0) for _, evidence in evidence_by_candidate],
            false_discovery_rate=0.05,
        )
        rejection_counts: Counter[str] = Counter()
        promoted_count = 0
        for index, (candidate, evidence) in enumerate(evidence_by_candidate):
            correction = corrections[index]
            evidence["adjusted_p_value"] = correction.adjusted_p_value
            evidence["multiple_testing_significant"] = correction.significant
            evidence["family_size"] = len(evidence_by_candidate)
            result = evaluate_strategy_robustness(evidence, seed=seed)
            validation = ReplayStrategyValidation(
                experiment_id=None,
                setup_type=candidate.setup_type,
                evidence_type="PURGED_WALK_FORWARD_EVIDENCE",
                sample_size=result.sample_size,
                markets_json=list(evidence.get("markets") or []),
                windows_json=list(evidence.get("windows") or []),
                metrics_json=result.metrics,
                overfitting_score=round(result.overfitting_probability * 100.0, 4),
                verdict=result.verdict,
                explanation=result.reason,
            )
            db.add(validation)
            db.flush()
            candidate.validation_id = validation.id
            candidate.final_verdict = result.verdict
            candidate.lifecycle_state = (
                "CERTIFIED"
                if result.verdict == "PROMOTED_TO_PAPER"
                else "AWAITING_EVIDENCE"
                if result.verdict == "NEEDS_MORE_EVIDENCE"
                else "REJECTED"
            )
            self._persist_folds(db, candidate, evidence)
            if result.verdict == "PROMOTED_TO_PAPER":
                promotion = self.champions.promote(db, candidate, validation)
                promoted_count += int(promotion.get("status") == "promoted")
            else:
                rejection_counts[result.verdict] += 1

        run.variants_examined = len(specifications)
        run.promoted_count = promoted_count
        run.rejection_counts_json = dict(rejection_counts)
        run.status = "COMPLETED"
        run.completed_at = datetime.utcnow()
        run.summary_json = {
            "new_candidates": len(new_candidates),
            "revalidated_candidates": len(evaluation_candidates) - len(new_candidates),
            "duplicate_candidates": len(specifications) - len(new_candidates),
            "rejection_counts": dict(rejection_counts),
            "promoted_count": promoted_count,
            "policy": "Only purged, cost-adjusted, multiple-testing-corrected evidence can promote.",
        }
        db.commit()
        return {
            "status": run.status,
            "run_id": run.id,
            "run_uid": run.run_uid,
            "variants_examined": len(specifications),
            "new_candidates": len(new_candidates),
            "revalidated_candidates": len(evaluation_candidates) - len(new_candidates),
            "rejection_counts": dict(rejection_counts),
            "promoted_to_paper": promoted_count,
        }

    @staticmethod
    def _candidate_replay_rows(db: Session, candidate: StrategyCandidateVariant) -> list[HyperbolicReplayTrade]:
        specification = dict(candidate.specification_json or {})
        if specification.get("evidence_binding") != "hyperbolic_replay_v1":
            return []
        expected_timeframes = tuple(candidate.timeframe_stack or [])
        rows = db.scalars(
            select(HyperbolicReplayTrade)
            .where(
                HyperbolicReplayTrade.setup_type == candidate.setup_type,
                HyperbolicReplayTrade.state == "REPLAY_EVALUATED",
            )
            .order_by(HyperbolicReplayTrade.decision_timestamp)
            .limit(5_000)
        ).all()
        return [
            row
            for row in rows
            if tuple((row.decision_payload or {}).get("required_timeframes") or []) == expected_timeframes
        ]

    @staticmethod
    def _candidate_evidence(db: Session, candidate: StrategyCandidateVariant) -> dict:
        specification = dict(candidate.specification_json or {})
        binding = specification.get("evidence_binding")
        rows = AlphaStrategyFactory._candidate_replay_rows(db, candidate)
        returns = [float(row.r_multiple or 0.0) for row in rows]
        excess = [float(row.benchmark_excess) for row in rows if row.benchmark_excess is not None]
        windows = split_windows(returns, 3)
        tickers = sorted({row.ticker for row in rows if row.ticker})
        markets = sorted({row.market for row in rows if row.market})
        regimes = sorted({str((row.decision_payload or {}).get("regime") or "unknown") for row in rows})
        pnl_by_asset: dict[str, float] = defaultdict(float)
        for row in rows:
            pnl_by_asset[row.ticker] += max(0.0, float(row.net_pnl or 0.0))
        positive_total = sum(pnl_by_asset.values())
        contributions = {ticker: value / positive_total for ticker, value in pnl_by_asset.items()} if positive_total > 0 else {}
        raw_p = 1.0
        if len(returns) >= 2:
            test = ttest_1samp(returns, popmean=0.0, alternative="greater")
            raw_p = float(test.pvalue) if test.pvalue == test.pvalue else 1.0
        rank_pairs = [(index + 1, index + 1 if row["expectancy_r"] > 0 else len(windows)) for index, row in enumerate(windows)]
        costs_complete = bool(rows) and all(bool((row.execution_payload or {}).get("cost_profile")) for row in rows)
        quality = mean([float(row.data_quality_score or 0.0) for row in rows]) if rows else 0.0
        return {
            "sample_size": len(rows),
            "returns_r": returns,
            "benchmark_excess_returns": excess,
            "markets": markets,
            "tickers": tickers,
            "regimes": regimes,
            "windows": windows,
            "max_drawdown": max_drawdown(returns),
            "raw_p_value": raw_p,
            "overfitting_probability": backtest_overfitting_probability(rank_pairs, variants=max(2, len(windows))),
            "deflated_sharpe_probability": deflated_sharpe_probability(returns, trials=max(1, len(windows))),
            "stability_by_window": [100.0 if row["expectancy_r"] > 0 else 0.0 for row in windows],
            "stability_by_market": group_stability(rows, key=lambda row: row.market),
            "stability_by_regime": group_stability(rows, key=lambda row: str((row.decision_payload or {}).get("regime") or "unknown")),
            "asset_pnl_contributions": contributions,
            "cost_coverage": 1.0 if costs_complete else 0.0,
            "data_quality_score": quality,
            "complexity": candidate.complexity,
            "timeframe_stack": list(candidate.timeframe_stack or []),
            "supported_asset_classes": ["Stock", "ETF"],
            "entry_rules": {"trigger": (candidate.specification_json or {}).get("entry_rule")},
            "stop_rules": {"method": (candidate.specification_json or {}).get("stop_rule")},
            "target_rules": {"method": (candidate.specification_json or {}).get("target_rule")},
            "certification_version": "alpha_strategy_factory_v1",
            "evidence_binding": binding,
            "evidence_binding_status": "EXECUTED_IMPLEMENTATION" if binding == "hyperbolic_replay_v1" else "IMPLEMENTATION_NOT_AVAILABLE",
        }

    @staticmethod
    def _has_new_evidence(db: Session, candidate: StrategyCandidateVariant) -> bool:
        if candidate.is_champion:
            return False
        validation = db.get(ReplayStrategyValidation, candidate.validation_id) if candidate.validation_id else None
        if validation is not None and (candidate.specification_json or {}).get("evidence_binding") != "hyperbolic_replay_v1":
            return False
        current_sample = len(AlphaStrategyFactory._candidate_replay_rows(db, candidate))
        return validation is None or current_sample != int(validation.sample_size or 0)

    @staticmethod
    def _persist_folds(db: Session, candidate: StrategyCandidateVariant, evidence: dict) -> None:
        existing = int(
            db.scalar(select(func.count(StrategyValidationFold.id)).where(StrategyValidationFold.candidate_id == candidate.id))
            or 0
        )
        if existing:
            return
        rows = evidence.get("timestamps") or []
        if not rows:
            trades = AlphaStrategyFactory._candidate_replay_rows(db, candidate)
            rows = [trade.decision_timestamp for trade in trades]
        rows = sorted({timestamp for timestamp in rows if timestamp is not None})
        if len(rows) < 12:
            return
        for fold in build_purged_folds(rows, n_splits=3, purge_bars=5, embargo_bars=3):
            db.add(
                StrategyValidationFold(
                    candidate_id=candidate.id,
                    fold_number=fold.fold_number,
                    train_start=fold.train_start,
                    train_end=fold.train_end,
                    validation_start=fold.validation_start,
                    validation_end=fold.validation_end,
                    purge_bars=fold.purge_bars,
                    embargo_bars=fold.embargo_bars,
                    train_count=len(fold.train_indices),
                    validation_count=len(fold.validation_indices),
                    metrics_json={"embargo_end_index": fold.embargo_end_index},
                    coverage_json={"timeframe_stack": list(candidate.timeframe_stack or [])},
                    warnings_json=[],
                )
            )


def factory_hypothesis_key(families: list[str]) -> str:
    if len(families) == 1 and len(families[0]) <= 80:
        return families[0]
    serialized = ",".join(families)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]
    return f"multi_family:{len(families)}:{digest}"


def strategy_fingerprint(specification: dict) -> str:
    canonical = json.dumps(specification, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def split_windows(values: list[float], count: int) -> list[dict]:
    if not values:
        return []
    size = max(1, len(values) // max(1, count))
    output = []
    for start in range(0, len(values), size):
        subset = values[start : start + size]
        if subset:
            output.append({"id": f"w{len(output) + 1}", "sample_size": len(subset), "expectancy_r": round(mean(subset), 8)})
    return output[:count]


def group_stability(rows: list[HyperbolicReplayTrade], *, key) -> list[float]:
    groups: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        groups[str(key(row))].append(float(row.r_multiple or 0.0))
    return [100.0 if mean(values) > 0 else 0.0 for values in groups.values()]


def max_drawdown(values: list[float]) -> float:
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return round(drawdown, 8)


def strategy_factory_snapshot(db: Session) -> dict:
    verdict_rows = db.execute(
        select(StrategyCandidateVariant.final_verdict, func.count(StrategyCandidateVariant.id)).group_by(StrategyCandidateVariant.final_verdict)
    ).all()
    verdicts = {str(verdict or "PENDING"): int(count) for verdict, count in verdict_rows}
    latest = db.scalar(select(StrategyFactoryRun).order_by(desc(StrategyFactoryRun.started_at), desc(StrategyFactoryRun.id)).limit(1))
    promotions = int(db.scalar(select(func.count(StrategyCandidateVariant.id)).where(StrategyCandidateVariant.is_champion.is_(True))) or 0)
    examined = int(db.scalar(select(func.count(StrategyCandidateVariant.id))) or 0)
    rejected = {key: value for key, value in verdicts.items() if key.startswith("REJECTED") or key == "NEEDS_MORE_EVIDENCE"}
    primary_blocker = max(rejected.items(), key=lambda item: item[1])[0] if rejected else None
    return {
        "status": "READY" if latest else "NO_FACTORY_RUNS",
        "examined_variants": examined,
        "rejection_counts": rejected,
        "promoted_to_paper": promotions,
        "champions": promotions,
        "challengers": max(0, int(verdicts.get("PROMOTED_TO_PAPER", 0)) - promotions),
        "primary_blocker": primary_blocker,
        "latest_run_at": latest.completed_at.isoformat() if latest and latest.completed_at else None,
        "latest_run_status": latest.status if latest else None,
        "policy": "Promotion requires purged walk-forward, realistic costs, robustness, concentration, and multiple-testing gates.",
    }
