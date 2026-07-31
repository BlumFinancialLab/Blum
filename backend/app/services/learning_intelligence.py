from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
import hashlib
import json
from statistics import mean, median, pstdev

from sqlalchemy import and_, desc, func, not_, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Asset,
    BlumTradingPowerScore,
    LearningBenchmarkComparison,
    LearningProgressSnapshot,
    LearningRun,
    LearningStrengthWeaknessMap,
    LiveForwardPaperTrade,
    PriceHistory,
    SelfImprovementAction,
    TradingGame,
    TradingGameTrade,
)
from app.services.trade_transparency import TradeLedgerService, TradingGameRealityCheckService, clamp, safe_float
from app.services.paper_forward_direction import TRUSTED_ACCOUNTING_STATUSES
from app.services.trading_intelligence_lab import (
    HistoricalLiveComparisonService,
    LAB_POLICY,
    TradingCapitalCycleService,
    TradingIntelligenceMetricsService,
    cycle_stats,
    executable_trades,
    metric_payload,
    sample_context,
)


settings = get_settings()

LEARNING_INTELLIGENCE_POLICY = (
    "Learning Intelligence is a benchmark-aware research dashboard. It must expose weakness, sample-size limits "
    "and benchmark underperformance instead of presenting simulated P/L as proof."
)

MARKET_BENCHMARKS = ["SPY", "QQQ", "VTI", "DIA", "IWM"]
SECTOR_BENCHMARKS = ["XLK", "XLF", "XLV", "XLY", "XLE", "XLI", "XLP", "XLU", "XLC", "XLB", "XLRE"]
BASELINE_BENCHMARKS = [
    ("cash_no_trade_baseline", "baseline"),
    ("random_asset_selection_proxy", "baseline"),
    ("random_entry_exit_proxy", "baseline"),
    ("momentum_baseline_proxy", "baseline"),
    ("moving_average_crossover_proxy", "baseline"),
    ("sector_rotation_proxy", "baseline"),
]


class BlumTradingPowerScoreService:
    """Strict composite score for current BLUM trading intelligence evidence."""

    def get(self, db: Session) -> dict:
        return self.calculate(db, persist=False)

    def recalculate(self, db: Session) -> dict:
        return self.calculate(db, persist=True)

    def persist_if_evidence_changed(self, db: Session) -> dict:
        """Persist one score projection for each distinct productive evidence state."""

        source = self._evidence_source(db)
        if source is None:
            return {"status": "skipped", "reason": "no_productive_learning_evidence"}

        fingerprint = hashlib.sha256(
            json.dumps(source, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        latest = db.scalar(
            select(BlumTradingPowerScore)
            .order_by(desc(BlumTradingPowerScore.calculated_at), desc(BlumTradingPowerScore.id))
            .limit(1)
        )
        latest_fingerprint = (latest.warnings_json or {}).get("evidence_fingerprint") if latest else None
        if latest_fingerprint == fingerprint:
            return {
                "status": "unchanged",
                "reason": "evidence_state_already_projected",
                "row_id": latest.id,
                "evidence_fingerprint": fingerprint,
            }

        payload = self.calculate(db, persist=True)
        row = db.get(BlumTradingPowerScore, payload["row_id"])
        row.warnings_json = {
            **(row.warnings_json or {}),
            "evidence_fingerprint": fingerprint,
            "evidence_source": source,
        }
        db.commit()
        return {
            **payload,
            "status": "persisted",
            "evidence_fingerprint": fingerprint,
            "evidence_source": source,
        }

    def _evidence_source(self, db: Session) -> dict | None:
        productive_run = db.scalar(
            select(LearningRun)
            .where(
                or_(
                    LearningRun.predictions_created > 0,
                    LearningRun.outcomes_evaluated > 0,
                    LearningRun.memory_updates > 0,
                )
            )
            .order_by(desc(LearningRun.started_at), desc(LearningRun.id))
            .limit(1)
        )
        if productive_run is None:
            return None

        closed_statuses = ("CLOSED", "EXITED", "EXPIRED", "INVALIDATED")
        forex_identity = or_(
            LiveForwardPaperTrade.ticker.like("%=X"),
            func.lower(func.coalesce(LiveForwardPaperTrade.asset_type, "")).in_(
                ("forex", "fx", "currency", "currency_pair", "forex_pair")
            ),
            func.lower(func.coalesce(LiveForwardPaperTrade.market, "")).in_(
                ("forex", "fx", "currency")
            ),
        )
        eligible_directional_accounting = or_(
            not_(forex_identity),
            and_(
                LiveForwardPaperTrade.accounting_status.in_(TRUSTED_ACCOUNTING_STATUSES),
                LiveForwardPaperTrade.side.in_(("LONG", "SHORT")),
            ),
        )
        eligible_closed_filter = and_(
            LiveForwardPaperTrade.status.in_(closed_statuses),
            eligible_directional_accounting,
        )
        last_closed_at = db.scalar(
            select(func.max(LiveForwardPaperTrade.closed_at)).where(eligible_closed_filter)
        )
        return {
            "learning_run_pk": productive_run.id,
            "learning_run_id": productive_run.run_id,
            "predictions_created": int(productive_run.predictions_created or 0),
            "outcomes_evaluated": int(productive_run.outcomes_evaluated or 0),
            "memory_updates": int(productive_run.memory_updates or 0),
            "historical_trade_count": int(db.scalar(select(func.count(TradingGameTrade.id))) or 0),
            "paper_forward_closed_count": int(
                db.scalar(
                    select(func.count(LiveForwardPaperTrade.id)).where(
                        eligible_closed_filter
                    )
                )
                or 0
            ),
            "paper_forward_last_closed_at": last_closed_at.isoformat() if last_closed_at else None,
        }

    def calculate(self, db: Session, persist: bool = False) -> dict:
        game = latest_trading_game(db)
        rows = game_trades(db, game.id if game else None)
        metrics = metric_payload(rows, scope="game", scope_id=str(game.id) if game else None, window_type="all", window_size=None)
        live_metrics = HistoricalLiveComparisonService().compare(db).get("live") or {}
        cycles = db.scalars(select_by_game_cycle(game.id if game else None)).all() if game else []
        cycle_payload = cycle_stats(cycles)
        reality = TradingGameRealityCheckService().evaluate(db, game.id if game else None, persist=False) if game else {}
        benchmark_rows = BenchmarkComparisonService().comparisons(db, persist=False).get("rows", [])
        progress = LearningProgressEvaluator().overview(db, persist=False)

        components = trading_power_components(rows, metrics, live_metrics, cycle_payload, reality, benchmark_rows, progress)
        score = trading_power_score(components)
        classification = classify_trading_power_score(score)
        warnings = trading_power_warnings(metrics, live_metrics, cycle_payload, reality, benchmark_rows, rows)
        explanation = trading_power_explanation(score, classification, components, warnings, metrics, benchmark_rows)
        truth = truth_panel_from_payload(score, classification, warnings, benchmark_rows, metrics, live_metrics)
        payload = {
            "status": "ok" if game else "no_game",
            "calculated_at": datetime.utcnow().isoformat(),
            "mode": "historical_plus_live",
            "scope": "global",
            "score": round(score, 2),
            "classification": classification,
            "components": components,
            "warnings": warnings,
            "truth_panel": truth,
            "sample_size": metrics.get("trades_count", 0),
            "live_sample_size": live_metrics.get("trades_count", 0),
            "statistical_confidence": statistical_confidence_label(metrics.get("trades_count", 0), live_metrics.get("trades_count", 0), sample_context(rows)),
            "explanation": explanation,
            "policy": LEARNING_INTELLIGENCE_POLICY,
        }
        if persist:
            row = BlumTradingPowerScore(
                mode=payload["mode"],
                scope=payload["scope"],
                score=payload["score"],
                classification=classification,
                benchmark_relative_score=components["benchmark_relative_score"],
                expectancy_score=components["expectancy_score"],
                drawdown_control_score=components["drawdown_control_score"],
                win_loss_quality_score=components["win_loss_quality_score"],
                missed_entry_penalty=components["missed_entry_penalty"],
                risk_management_score=components["risk_management_score"],
                capital_cycle_score=components["capital_cycle_score"],
                live_forward_validation_score=components["live_forward_validation_score"],
                regime_robustness_score=components["regime_robustness_score"],
                setup_diversity_score=components["setup_diversity_score"],
                statistical_confidence_score=components["statistical_confidence_score"],
                reproducibility_score=components["reproducibility_score"],
                decision_quality_score=components["decision_quality_score"],
                learning_velocity_score=components["learning_velocity_score"],
                explanation=explanation,
                warnings_json={"warnings": warnings, "truth_panel": truth},
            )
            db.add(row)
            db.commit()
            payload["row_id"] = row.id
        return payload


class BenchmarkComparisonService:
    """Compares BLUM against market benchmarks and simple internal baselines."""

    def comparisons(self, db: Session, persist: bool = False) -> dict:
        game = latest_trading_game(db)
        rows = game_trades(db, game.id if game else None)
        closed = executable_trades(rows)
        output = []
        for name in MARKET_BENCHMARKS:
            output.append(self.compare_to_benchmark(db, name, "market", closed))
        for name in SECTOR_BENCHMARKS:
            output.append(self.compare_to_benchmark(db, name, "sector", closed))
        for name, kind in BASELINE_BENCHMARKS:
            output.append(self.compare_to_baseline(name, kind, closed))
        if persist:
            for item in output:
                db.add(
                    LearningBenchmarkComparison(
                        mode=item["mode"],
                        benchmark_name=item["benchmark_name"],
                        benchmark_type=item["benchmark_type"],
                        period_start=parse_date_value(item.get("period_start")),
                        period_end=parse_date_value(item.get("period_end")),
                        blum_return=item.get("blum_return"),
                        benchmark_return=item.get("benchmark_return"),
                        excess_return=item.get("excess_return"),
                        blum_max_drawdown=item.get("blum_max_drawdown"),
                        benchmark_max_drawdown=item.get("benchmark_max_drawdown"),
                        blum_volatility=item.get("blum_volatility"),
                        benchmark_volatility=item.get("benchmark_volatility"),
                        sharpe_proxy=item.get("sharpe_proxy"),
                        sortino_proxy=item.get("sortino_proxy"),
                        calmar_proxy=item.get("calmar_proxy"),
                        information_ratio_proxy=item.get("information_ratio_proxy"),
                        hit_rate_vs_benchmark=item.get("hit_rate_vs_benchmark"),
                        risk_adjusted_advantage=item.get("risk_adjusted_advantage"),
                        sample_size=item.get("sample_size", 0),
                        statistical_confidence=item.get("statistical_confidence", "very low evidence"),
                        result_label=item.get("result_label", "insufficient_sample"),
                        explanation=item.get("explanation", ""),
                    )
                )
            db.commit()
        return {"status": "ok", "rows": output, "policy": LEARNING_INTELLIGENCE_POLICY}

    def detail(self, db: Session, benchmark_name: str) -> dict:
        rows = self.comparisons(db, persist=False).get("rows", [])
        needle = benchmark_name.upper()
        row = next((item for item in rows if item["benchmark_name"].upper() == needle), None)
        return {"status": "ok" if row else "not_found", "benchmark": row, "policy": LEARNING_INTELLIGENCE_POLICY}

    def compare_to_benchmark(self, db: Session, benchmark: str, benchmark_type: str, rows: list[TradingGameTrade]) -> dict:
        returns = trade_returns(rows)
        benchmark_returns = benchmark_returns_for_rows(db, rows, benchmark)
        sample = min(len(returns), len(benchmark_returns)) if benchmark_returns else len(returns)
        blum_return = mean(returns) if returns else None
        benchmark_return = mean(benchmark_returns) if benchmark_returns else price_period_return(db, benchmark, rows)
        excess = blum_return - benchmark_return if blum_return is not None and benchmark_return is not None else None
        hit_rate = hit_rate_vs_benchmark(returns, benchmark_returns)
        label = benchmark_result_label(excess, sample)
        confidence = statistical_confidence_label(sample, 0, sample_context(rows))
        explanation = benchmark_explanation(benchmark, benchmark_type, sample, blum_return, benchmark_return, excess, label, benchmark_returns)
        return {
            "mode": "historical_simulation",
            "benchmark_name": benchmark,
            "benchmark_type": benchmark_type,
            "period_start": first_date(rows),
            "period_end": last_date(rows),
            "blum_return": round_or_none(blum_return),
            "benchmark_return": round_or_none(benchmark_return),
            "excess_return": round_or_none(excess),
            "blum_max_drawdown": round_or_none(min(returns) if returns else None),
            "benchmark_max_drawdown": round_or_none(min(benchmark_returns) if benchmark_returns else None),
            "blum_volatility": round_or_none(pstdev(returns) if len(returns) > 1 else None),
            "benchmark_volatility": round_or_none(pstdev(benchmark_returns) if len(benchmark_returns) > 1 else None),
            "sharpe_proxy": ratio_or_none(blum_return, pstdev(returns) if len(returns) > 1 else None),
            "sortino_proxy": ratio_or_none(blum_return, downside_volatility(returns)),
            "calmar_proxy": ratio_or_none(blum_return, abs(min(returns)) if returns else None),
            "information_ratio_proxy": ratio_or_none(excess, pstdev([a - b for a, b in zip(returns, benchmark_returns)]) if len(benchmark_returns) > 1 else None),
            "hit_rate_vs_benchmark": round_or_none(hit_rate),
            "risk_adjusted_advantage": round_or_none((excess or 0) - abs((min(returns) if returns else 0) - (min(benchmark_returns) if benchmark_returns else 0)) * 0.25 if excess is not None else None),
            "sample_size": sample,
            "statistical_confidence": confidence,
            "result_label": label,
            "explanation": explanation,
        }

    def compare_to_baseline(self, name: str, benchmark_type: str, rows: list[TradingGameTrade]) -> dict:
        returns = trade_returns(rows)
        benchmark = baseline_return(name, rows)
        sample = len(returns)
        blum_return = mean(returns) if returns else None
        excess = blum_return - benchmark if blum_return is not None and benchmark is not None else None
        label = benchmark_result_label(excess, sample)
        return {
            "mode": "historical_simulation",
            "benchmark_name": name,
            "benchmark_type": benchmark_type,
            "period_start": first_date(rows),
            "period_end": last_date(rows),
            "blum_return": round_or_none(blum_return),
            "benchmark_return": round_or_none(benchmark),
            "excess_return": round_or_none(excess),
            "blum_max_drawdown": round_or_none(min(returns) if returns else None),
            "benchmark_max_drawdown": None,
            "blum_volatility": round_or_none(pstdev(returns) if len(returns) > 1 else None),
            "benchmark_volatility": None,
            "sharpe_proxy": ratio_or_none(blum_return, pstdev(returns) if len(returns) > 1 else None),
            "sortino_proxy": ratio_or_none(blum_return, downside_volatility(returns)),
            "calmar_proxy": ratio_or_none(blum_return, abs(min(returns)) if returns else None),
            "information_ratio_proxy": None,
            "hit_rate_vs_benchmark": round_or_none(sum(1 for value in returns if benchmark is not None and value > benchmark) / max(1, len(returns)) if returns else None),
            "risk_adjusted_advantage": round_or_none(excess),
            "sample_size": sample,
            "statistical_confidence": statistical_confidence_label(sample, 0, sample_context(rows)),
            "result_label": label,
            "explanation": baseline_explanation(name, sample, benchmark, excess, label),
        }


class LearningProgressEvaluator:
    """Measures rolling improvement, deterioration and inconclusive zones."""

    def overview(self, db: Session, persist: bool = False) -> dict:
        game = latest_trading_game(db)
        rows = game_trades(db, game.id if game else None)
        windows = self.rolling(db).get("windows", [])
        all_metric = metric_payload(rows, "game", str(game.id) if game else None, "all", None)
        trend = progress_trend_label(windows)
        score = intelligence_growth_score(windows, all_metric)
        payload = {
            "status": "ok" if game else "no_game",
            "summary": progress_explanation(trend, score, windows, all_metric),
            "trend_label": trend,
            "intelligence_growth_score": round(score, 2),
            "current": all_metric,
            "rolling": windows,
            "policy": LEARNING_INTELLIGENCE_POLICY,
        }
        if persist:
            db.add(progress_snapshot_row(all_metric, trend, score, None))
            for item in windows:
                db.add(progress_snapshot_row(item, progress_trend_label([item]), safe_float(item.get("intelligence_growth_score")), item.get("window_size")))
            db.commit()
        return payload

    def rolling(self, db: Session) -> dict:
        game = latest_trading_game(db)
        rows = game_trades(db, game.id if game else None)
        payloads = []
        for window in (30, 100, 250):
            payloads.append(metric_payload(rows[-window:], "game", str(game.id) if game else None, "rolling", window))
        return {"status": "ok" if game else "no_game", "windows": payloads, "policy": LEARNING_INTELLIGENCE_POLICY}

    def by_dimension(self, db: Session, dimension: str) -> dict:
        service = TradingIntelligenceMetricsService()
        if dimension == "setup":
            return service.by_dimension(db, "setup")
        if dimension == "regime":
            return service.by_dimension(db, "regime")
        return {"status": "not_supported", "dimension": dimension, "rows": []}


class LearningWeaknessMapService:
    """Finds where BLUM is strong, weak or statistically under-covered."""

    def map(self, db: Session, dimension: str | None = None, persist: bool = False) -> dict:
        dimensions = [dimension] if dimension else ["setup", "regime", "sector", "engine"]
        rows: list[dict] = []
        for dim in dimensions:
            rows.extend(self.dimension_rows(db, dim))
        rows.sort(key=lambda item: (priority_rank(item["priority"]), item["weakness_score"]), reverse=True)
        if persist:
            for item in rows:
                db.add(
                    LearningStrengthWeaknessMap(
                        dimension=item["dimension"],
                        entity=item["entity"],
                        strength_score=item["strength_score"],
                        weakness_score=item["weakness_score"],
                        sample_size=item["sample_size"],
                        evidence=item["evidence"],
                        main_problem=item["main_problem"],
                        recommended_action=item["recommended_action"],
                        priority=item["priority"],
                        status=item["status"],
                    )
                )
            db.commit()
        return {"status": "ok", "dimension": dimension or "all", "rows": rows, "policy": LEARNING_INTELLIGENCE_POLICY}

    def dimension_rows(self, db: Session, dimension: str) -> list[dict]:
        if dimension in {"setup", "regime", "sector"}:
            metrics = TradingIntelligenceMetricsService().by_dimension(db, dimension).get("rows", [])
            return [weakness_from_metric(dimension, row) for row in metrics]
        return self.engine_rows(db)

    def engine_rows(self, db: Session) -> list[dict]:
        from app.models import TradeEngineAttribution

        attributions = db.scalars(select(TradeEngineAttribution)).all()
        grouped: dict[str, list] = defaultdict(list)
        for row in attributions:
            grouped[row.engine_name or "unknown"].append(row)
        output = []
        for engine, items in grouped.items():
            sample = len(items)
            correct = sum(1 for item in items if item.was_correct)
            avg_quality = mean([safe_float(item.evidence_quality) for item in items]) if items else 0
            strength = clamp((correct / max(1, sample)) * 70 + avg_quality * 0.3)
            weakness = clamp(100 - strength + (30 if sample < settings.self_improvement_min_sample_size else 0))
            output.append(
                {
                    "dimension": "engine",
                    "entity": engine,
                    "strength_score": round(strength, 2),
                    "weakness_score": round(weakness, 2),
                    "sample_size": sample,
                    "evidence": {"correct": correct, "average_evidence_quality": round(avg_quality, 2)},
                    "main_problem": "Engine evidence is statistically thin." if sample < settings.self_improvement_min_sample_size else "Engine attribution quality needs monitoring.",
                    "recommended_action": "Collect more attributed trades before changing engine weights." if sample < settings.self_improvement_min_sample_size else "Compare this engine against benchmark-relative outcomes before weight changes.",
                    "priority": "high" if weakness >= 70 else "medium" if weakness >= 45 else "low",
                    "status": "open",
                }
            )
        return output


class SelfImprovementActionEngine:
    """Converts measured weakness into auditable, reversible improvement proposals."""

    def list(self, db: Session, limit: int = 80) -> dict:
        rows = db.scalars(select(SelfImprovementAction).order_by(desc(SelfImprovementAction.created_at)).limit(limit)).all()
        if not rows:
            generated = self.generate(db, persist=False).get("actions", [])
            return {"status": "preview", "actions": generated[:limit], "policy": LEARNING_INTELLIGENCE_POLICY}
        return {"status": "ok", "actions": [serialize_action(row) for row in rows], "policy": LEARNING_INTELLIGENCE_POLICY}

    def generate(self, db: Session, persist: bool = True) -> dict:
        weakness_rows = LearningWeaknessMapService().map(db, persist=False).get("rows", [])
        actions = [self.action_from_weakness(row) for row in weakness_rows if row["weakness_score"] >= 45]
        actions = dedupe_actions(actions)
        if persist:
            existing = {
                (row.source_dimension, row.detected_problem, row.affected_module, row.status)
                for row in db.scalars(select(SelfImprovementAction).where(SelfImprovementAction.status.in_(["proposed", "testing", "applied"]))).all()
            }
            inserted = []
            for action in actions:
                key = (action["source_dimension"], action["detected_problem"], action["affected_module"], action["status"])
                if key in existing:
                    continue
                row = SelfImprovementAction(**action)
                db.add(row)
                inserted.append(row)
            db.commit()
            actions = [serialize_action(row) for row in inserted] or actions
        return {
            "status": "ok",
            "actions": actions,
            "auto_apply": {
                "enabled": settings.self_improvement_enabled,
                "global_auto_apply": settings.self_improvement_auto_apply,
                "low_risk_auto_apply": settings.self_improvement_auto_apply_low_risk,
                "min_sample_size": settings.self_improvement_min_sample_size,
                "policy": "No source code self-modification. Actions are auditable parameter or sampling proposals.",
            },
            "policy": LEARNING_INTELLIGENCE_POLICY,
        }

    def apply(self, db: Session, action_id: int) -> dict:
        row = db.get(SelfImprovementAction, action_id)
        if not row:
            return {"status": "not_found", "action_id": action_id}
        if not settings.self_improvement_enabled:
            return {"status": "disabled", "action": serialize_action(row), "reason": "SELF_IMPROVEMENT_ENABLED=false"}
        if not settings.self_improvement_auto_apply and not (settings.self_improvement_auto_apply_low_risk and row.priority == "low"):
            row.status = "testing"
            row.notes_json = {
                **(row.notes_json or {}),
                "applied": False,
                "reason": "Auto-apply is disabled. Action moved to testing queue for human review.",
                "reversible": True,
            }
            db.commit()
            return {"status": "testing_only", "action": serialize_action(row), "policy": LEARNING_INTELLIGENCE_POLICY}
        row.status = "applied"
        row.applied_at = datetime.utcnow()
        row.notes_json = {**(row.notes_json or {}), "applied": True, "reversible": True, "source_code_modified": False}
        db.commit()
        return {"status": "applied", "action": serialize_action(row), "policy": LEARNING_INTELLIGENCE_POLICY}

    def evaluate(self, db: Session, action_id: int) -> dict:
        row = db.get(SelfImprovementAction, action_id)
        if not row:
            return {"status": "not_found", "action_id": action_id}
        before = row.before_metric
        after = latest_metric_for_action(db, row)
        row.after_metric = after
        row.improvement_observed = after is not None and before is not None and after > before
        if row.improvement_observed is False and settings.self_improvement_rollback_enabled:
            row.status = "retired"
        elif row.improvement_observed:
            row.status = "applied"
        db.commit()
        return {"status": "ok", "action": serialize_action(row), "policy": LEARNING_INTELLIGENCE_POLICY}

    def action_from_weakness(self, weakness: dict) -> dict:
        action = self_improvement_action_from_weakness(weakness)
        return action


class LearningIntelligenceDashboardService:
    """Single control-room payload for the frontend and chat."""

    def dashboard(self, db: Session) -> dict:
        trading_power = BlumTradingPowerScoreService().get(db)
        benchmarks = BenchmarkComparisonService().comparisons(db, persist=False)
        progress = LearningProgressEvaluator().overview(db, persist=False)
        weakness = LearningWeaknessMapService().map(db, persist=False)
        actions = SelfImprovementActionEngine().list(db, limit=40)
        live = HistoricalLiveComparisonService().compare(db)
        return {
            "status": "ok",
            "generated_at": datetime.utcnow().isoformat(),
            "trading_power": trading_power,
            "benchmarks": benchmarks,
            "progress": progress,
            "weakness_map": weakness,
            "self_improvement": actions,
            "historical_vs_live": live,
            "truth_panel": trading_power.get("truth_panel", []),
            "policy": LEARNING_INTELLIGENCE_POLICY,
        }


def latest_trading_game(db: Session) -> TradingGame | None:
    return TradeLedgerService().game(db)


def game_trades(db: Session, game_id: int | None = None) -> list[TradingGameTrade]:
    if game_id:
        return list(db.scalars(select(TradingGameTrade).where(TradingGameTrade.game_id == game_id).order_by(TradingGameTrade.created_at)).all())
    return list(db.scalars(select(TradingGameTrade).order_by(TradingGameTrade.created_at)).all())


def select_by_game_cycle(game_id: int | None):
    from app.models import TradingCapitalCycle

    query = select(TradingCapitalCycle)
    if game_id is not None:
        query = query.where(TradingCapitalCycle.game_id == game_id)
    return query


def trading_power_components(rows: list[TradingGameTrade], metrics: dict, live_metrics: dict, cycle_payload: dict, reality: dict, benchmark_rows: list[dict], progress: dict) -> dict:
    benchmark_excess_values = [safe_float(item.get("excess_return")) for item in benchmark_rows if item.get("result_label") != "insufficient_sample" and item.get("excess_return") is not None]
    avg_excess = mean(benchmark_excess_values) if benchmark_excess_values else safe_float(metrics.get("benchmark_excess"))
    setup_count = len({row.setup_type for row in rows if row.setup_type})
    regime_count = len({row.market_regime_at_entry for row in rows if row.market_regime_at_entry})
    ticker_count = len({row.ticker for row in rows if row.ticker})
    sample = int(metrics.get("trades_count") or 0)
    live_sample = int(live_metrics.get("trades_count") or 0)
    return {
        "benchmark_relative_score": round(clamp(50 + avg_excess * 4), 2),
        "expectancy_score": round(clamp(50 + safe_float(metrics.get("expectancy_r")) * 25), 2),
        "drawdown_control_score": round(clamp(100 + safe_float(metrics.get("max_drawdown")) * 4), 2) if metrics.get("max_drawdown") is not None else 35.0,
        "win_loss_quality_score": round(clamp(50 + (safe_float(metrics.get("win_rate")) - safe_float(metrics.get("loss_rate"))) * 60), 2),
        "missed_entry_penalty": round(clamp(safe_float(metrics.get("missed_entry_rate")) * 100), 2),
        "risk_management_score": round(clamp(mean(compact_numbers([metrics.get("sizing_quality_score"), metrics.get("risk_reward_quality_score"), reality.get("realism_score")])) if compact_numbers([metrics.get("sizing_quality_score"), metrics.get("risk_reward_quality_score"), reality.get("realism_score")]) else 35), 2),
        "capital_cycle_score": round(clamp(40 + safe_float(cycle_payload.get("target_hit_rate")) * 35 + safe_float(cycle_payload.get("survival_rate")) * 25), 2),
        "live_forward_validation_score": round(clamp(10 + min(50, live_sample) * 1.2 + safe_float(live_metrics.get("expectancy_r")) * 15), 2),
        "regime_robustness_score": round(clamp(20 + min(6, regime_count) * 10 + min(6, setup_count) * 4), 2),
        "setup_diversity_score": round(clamp(15 + min(12, setup_count) * 5 + min(20, ticker_count) * 1.2), 2),
        "statistical_confidence_score": round(clamp(10 + min(250, sample) * 0.22 + min(80, live_sample) * 0.35 + min(6, regime_count) * 4), 2),
        "reproducibility_score": round(clamp(safe_float(metrics.get("reproducibility_score"), 35)), 2),
        "decision_quality_score": round(clamp(mean(compact_numbers([metrics.get("entry_timing_score"), metrics.get("exit_timing_score"), metrics.get("trade_quality_score")])) if compact_numbers([metrics.get("entry_timing_score"), metrics.get("exit_timing_score"), metrics.get("trade_quality_score")]) else 35), 2),
        "learning_velocity_score": round(clamp(safe_float(progress.get("intelligence_growth_score"), metrics.get("intelligence_growth_score") or 0)), 2),
    }


def trading_power_score(components: dict) -> float:
    weights = {
        "benchmark_relative_score": 0.13,
        "expectancy_score": 0.11,
        "drawdown_control_score": 0.08,
        "win_loss_quality_score": 0.08,
        "risk_management_score": 0.10,
        "capital_cycle_score": 0.07,
        "live_forward_validation_score": 0.12,
        "regime_robustness_score": 0.07,
        "setup_diversity_score": 0.05,
        "statistical_confidence_score": 0.10,
        "reproducibility_score": 0.05,
        "decision_quality_score": 0.08,
        "learning_velocity_score": 0.06,
    }
    raw = sum(safe_float(components.get(key)) * weight for key, weight in weights.items())
    penalty = safe_float(components.get("missed_entry_penalty")) * 0.08
    return clamp(raw - penalty)


def classify_trading_power_score(score: float) -> str:
    if score <= 20:
        return "Not usable"
    if score <= 40:
        return "Weak / experimental"
    if score <= 60:
        return "Learning but not reliable"
    if score <= 75:
        return "Promising research system"
    if score <= 85:
        return "Strong paper-trading evidence"
    if score <= 95:
        return "Advanced alpha research candidate"
    return "Exceptional, requires external validation"


def statistical_confidence_label(sample_size: int | None, live_sample_size: int | None = 0, context: dict | None = None) -> str:
    sample = int(sample_size or 0)
    live_sample = int(live_sample_size or 0)
    regimes = int((context or {}).get("regimes") or 0)
    tickers = int((context or {}).get("tickers") or 0)
    if sample < 30:
        return "very low evidence"
    if sample < 100 or tickers < 8:
        return "low evidence"
    if sample < 250 or regimes < 3 or live_sample < 10:
        return "medium evidence"
    if sample < 750 or live_sample < 30:
        return "strong evidence"
    return "high confidence"


def benchmark_result_label(excess_return: float | None, sample_size: int) -> str:
    if sample_size < 30 or excess_return is None:
        return "insufficient_sample"
    if sample_size < 100 and abs(excess_return) < 2:
        return "inconclusive"
    if excess_return > 1:
        return "outperforming"
    if excess_return < -1:
        return "underperforming"
    return "similar"


def truth_panel_from_payload(score: float, classification: str, warnings: list[str], benchmarks: list[dict], metrics: dict, live_metrics: dict) -> list[str]:
    rows = [f"BLUM Trading Power Score: {score:.1f}/100 ({classification})."]
    spy = next((item for item in benchmarks if item.get("benchmark_name") == "SPY"), None)
    qqq = next((item for item in benchmarks if item.get("benchmark_name") == "QQQ"), None)
    for item, label in [(spy, "SPY"), (qqq, "QQQ")]:
        if not item:
            continue
        result = item.get("result_label")
        excess = item.get("excess_return")
        if result == "underperforming":
            rows.append(f"BLUM is underperforming {label} on the current evidence ({round_or_none(excess)}% excess).")
        elif result == "outperforming":
            rows.append(f"BLUM is outperforming {label}, but this is still evidence-bound ({round_or_none(excess)}% excess).")
        else:
            rows.append(f"BLUM vs {label}: {result}; no strong conclusion.")
    if int(live_metrics.get("trades_count") or 0) < 30:
        rows.append("Live paper evidence is not mature yet; historical results are weaker evidence than forward paper trades.")
    if safe_float(metrics.get("missed_entry_rate")) > 0.25:
        rows.append("Missed entries remain a major weakness and must penalize actionability.")
    rows.extend(warnings[:4])
    return dedupe_strings(rows)


def trading_power_warnings(metrics: dict, live_metrics: dict, cycles: dict, reality: dict, benchmarks: list[dict], rows: list[TradingGameTrade]) -> list[str]:
    warnings = []
    sample = int(metrics.get("trades_count") or 0)
    if sample < 100:
        warnings.append("Sample is still too small for a robust alpha claim.")
    if int(live_metrics.get("trades_count") or 0) < 30:
        warnings.append("Live forward paper sample is too small; historical simulation can overstate edge.")
    if safe_float(metrics.get("missed_entry_rate")) > 0.25:
        warnings.append("Missed-entry rate is high; BLUM may identify ideas but fail timing.")
    if any(item.get("result_label") == "underperforming" for item in benchmarks if item.get("benchmark_name") in {"SPY", "QQQ", "VTI"}):
        warnings.append("At least one major benchmark is currently beating BLUM on comparable evidence.")
    if (reality.get("warnings") or []):
        warnings.extend(str(item).replace("_", " ") for item in reality.get("warnings", [])[:3])
    if len({row.market_regime_at_entry for row in rows if row.market_regime_at_entry}) < 3 and sample > 0:
        warnings.append("Regime coverage is thin; robustness across market conditions is not proven.")
    return dedupe_strings(warnings)


def trading_power_explanation(score: float, classification: str, components: dict, warnings: list[str], metrics: dict, benchmarks: list[dict]) -> str:
    strongest = sorted(components.items(), key=lambda item: safe_float(item[1]), reverse=True)[:2]
    weakest = sorted((item for item in components.items() if item[0] != "missed_entry_penalty"), key=lambda item: safe_float(item[1]))[:2]
    benchmark_state = Counter(item.get("result_label") for item in benchmarks)
    return (
        f"Score {score:.1f}/100 ({classification}). Strongest components: "
        f"{', '.join(f'{name}={value}' for name, value in strongest)}. Weakest components: "
        f"{', '.join(f'{name}={value}' for name, value in weakest)}. Benchmark states: {dict(benchmark_state)}. "
        f"Trades: {metrics.get('trades_count', 0)}. Main warning: {warnings[0] if warnings else 'no critical warning'}."
    )


def benchmark_returns_for_rows(db: Session, rows: list[TradingGameTrade], benchmark: str) -> list[float]:
    direct = [safe_float(row.benchmark_return_same_period) for row in rows if (row.benchmark_ticker or "").upper() == benchmark.upper() and row.benchmark_return_same_period is not None]
    if direct:
        return direct
    period_return = price_period_return(db, benchmark, rows)
    if period_return is not None:
        return [period_return for _ in rows]
    fallback = [safe_float(row.benchmark_return_same_period) for row in rows if row.benchmark_return_same_period is not None]
    return fallback


def price_period_return(db: Session, ticker: str, rows: list[TradingGameTrade]) -> float | None:
    start = parse_date_value(first_date(rows))
    end = parse_date_value(last_date(rows))
    if not start or not end:
        return None
    asset = db.scalar(select(Asset).where(Asset.ticker == ticker).limit(1))
    if not asset:
        return None
    first = db.scalar(select(PriceHistory).where(PriceHistory.asset_id == asset.id, PriceHistory.date >= start).order_by(PriceHistory.date).limit(1))
    last = db.scalar(select(PriceHistory).where(PriceHistory.asset_id == asset.id, PriceHistory.date <= end).order_by(desc(PriceHistory.date)).limit(1))
    if not first or not last or not first.close:
        return None
    return (last.close / first.close - 1) * 100


def baseline_return(name: str, rows: list[TradingGameTrade]) -> float | None:
    returns = trade_returns(rows)
    if not returns:
        return None
    if name == "cash_no_trade_baseline":
        return 0.0
    if name == "random_asset_selection_proxy":
        benchmarks = [safe_float(row.benchmark_return_same_period) for row in rows if row.benchmark_return_same_period is not None]
        return median(benchmarks) if benchmarks else 0.0
    if name == "random_entry_exit_proxy":
        return median(returns) * 0.65
    if name == "momentum_baseline_proxy":
        momentum_rows = [row for row in rows if "momentum" in (row.setup_type or "")]
        values = trade_returns(momentum_rows)
        return mean(values) if values else median(returns)
    if name == "moving_average_crossover_proxy":
        trend_rows = [row for row in rows if "trend" in (row.setup_type or "") or "pullback" in (row.setup_type or "")]
        values = trade_returns(trend_rows)
        return mean(values) if values else median(returns)
    if name == "sector_rotation_proxy":
        sector_rows = [row for row in rows if "sector" in (row.setup_type or "") or "rotation" in (row.setup_type or "")]
        values = trade_returns(sector_rows)
        return mean(values) if values else median(returns)
    return None


def trade_returns(rows: list[TradingGameTrade]) -> list[float]:
    output = []
    for row in rows:
        value = row.pnl_percent
        if value is None:
            value = safe_float(row.net_pnl_eur if row.net_pnl_eur is not None else row.realized_pl) / max(0.01, safe_float(row.capital_before)) * 100
        output.append(safe_float(value))
    return output


def weakness_from_metric(dimension: str, metric: dict) -> dict:
    sample = int(metric.get("trades_count") or 0)
    missed = safe_float(metric.get("missed_entry_rate"))
    stop = safe_float(metric.get("stop_hit_rate"))
    expectancy = safe_float(metric.get("expectancy_r"))
    benchmark = safe_float(metric.get("benchmark_excess"))
    quality = safe_float(metric.get("trade_quality_score"), 45)
    weakness = clamp((missed * 28) + (stop * 22) + max(0, -expectancy) * 22 + max(0, -benchmark) * 2 + max(0, 55 - quality) * 0.45 + (25 if sample < settings.self_improvement_min_sample_size else 0))
    strength = clamp(100 - weakness + max(0, expectancy) * 12 + max(0, benchmark) * 0.8)
    problem, action, module = weakness_problem_action(dimension, metric, weakness)
    priority = "high" if weakness >= 70 or missed > 0.4 or stop > 0.65 or benchmark < -5 else "medium" if weakness >= 45 or missed > 0.25 or stop > 0.5 or benchmark < -1 else "low"
    return {
        "dimension": dimension,
        "entity": str(metric.get("scope_id") or "unknown"),
        "strength_score": round(strength, 2),
        "weakness_score": round(weakness, 2),
        "sample_size": sample,
        "evidence": metric,
        "main_problem": problem,
        "recommended_action": action,
        "priority": priority,
        "status": "open",
        "affected_module": module,
    }


def weakness_problem_action(dimension: str, metric: dict, weakness: float) -> tuple[str, str, str]:
    entity = str(metric.get("scope_id") or "unknown").replace("_", " ")
    if safe_float(metric.get("missed_entry_rate")) > 0.25:
        return (
            f"High missed-entry rate in {dimension}={entity}.",
            "Test pullback-retest entry logic against breakout-close entry logic and penalize late entries.",
            "EntryExitEngine",
        )
    if safe_float(metric.get("stop_hit_rate")) > 0.55:
        return (
            f"Stop-hit rate is elevated in {dimension}={entity}.",
            "Re-test stop placement, ATR buffers and hostile-regime no-trade filters.",
            "RiskEngine",
        )
    if safe_float(metric.get("benchmark_excess")) < -1:
        return (
            f"Underperforming benchmark in {dimension}={entity}.",
            "Compare against passive benchmark and simple momentum baseline before increasing confidence.",
            "BenchmarkComparisonService",
        )
    if metric.get("trades_count", 0) < settings.self_improvement_min_sample_size:
        return (
            f"Insufficient sample in {dimension}={entity}.",
            "Increase adaptive Learning Loop sampling before changing weights.",
            "LearningLoopService",
        )
    if weakness >= 45:
        return (
            f"Mixed decision quality in {dimension}={entity}.",
            "Study entry, exit and no-trade outcomes separately before changing Sniper Score.",
            "SniperScoreCalculator",
        )
    return (
        f"No critical weakness in {dimension}={entity}.",
        "Keep monitoring and avoid overfitting to a strong but narrow sample.",
        "MetaIntelligence",
    )


def self_improvement_action_from_weakness(weakness: dict) -> dict:
    metric = weakness.get("evidence") or {}
    sample = int(weakness.get("sample_size") or 0)
    priority = weakness.get("priority") or "medium"
    source_dimension = f"{weakness.get('dimension')}:{weakness.get('entity')}"
    return {
        "source_metric": "learning_strength_weakness_map",
        "source_dimension": source_dimension,
        "detected_problem": weakness.get("main_problem") or "Measured weakness without classified problem.",
        "recommended_action": weakness.get("recommended_action") or "Collect more samples before changing parameters.",
        "affected_module": weakness.get("affected_module") or "LearningLoopService",
        "priority": priority,
        "expected_impact": "Reduce false positives, missed entries or benchmark underperformance while preserving reversibility.",
        "status": "proposed",
        "before_metric": metric.get("intelligence_growth_score") or metric.get("expectancy_r"),
        "after_metric": None,
        "improvement_observed": None,
        "notes_json": {
            "sample_size": sample,
            "auto_apply_allowed": settings.self_improvement_auto_apply or (settings.self_improvement_auto_apply_low_risk and priority == "low"),
            "reversible": True,
            "source_code_self_modification": False,
            "requires_human_review": priority != "low" or not settings.self_improvement_auto_apply,
        },
    }


def latest_metric_for_action(db: Session, action: SelfImprovementAction) -> float | None:
    dimension, _, entity = (action.source_dimension or "").partition(":")
    rows = LearningWeaknessMapService().map(db, dimension if dimension else None, persist=False).get("rows", [])
    match = next((row for row in rows if row.get("entity") == entity), None)
    if not match:
        return None
    evidence = match.get("evidence") or {}
    return evidence.get("intelligence_growth_score") or evidence.get("expectancy_r")


def progress_snapshot_row(payload: dict, trend: str, growth: float, window_size: int | None) -> LearningProgressSnapshot:
    return LearningProgressSnapshot(
        window_type=payload.get("window_type") or "all",
        window_size=window_size,
        trades_count=payload.get("trades_count", 0),
        win_rate=payload.get("win_rate"),
        missed_entry_rate=payload.get("missed_entry_rate"),
        loss_rate=payload.get("loss_rate"),
        target_hit_rate=payload.get("target_hit_rate"),
        stop_hit_rate=payload.get("stop_hit_rate"),
        expectancy_r=payload.get("expectancy_r"),
        benchmark_excess=payload.get("benchmark_excess"),
        max_drawdown=payload.get("max_drawdown"),
        trade_quality_avg=payload.get("trade_quality_score"),
        confidence_calibration_error=None,
        repeated_mistake_rate=None,
        intelligence_growth_score=round(growth, 2),
        trend_label=trend,
        explanation=progress_explanation(trend, growth, [payload], payload),
    )


def progress_trend_label(windows: list[dict]) -> str:
    latest = next((item for item in windows if item.get("window_size") == 30), None)
    prior = next((item for item in windows if item.get("window_size") == 100), None)
    if not latest or not prior or latest.get("trades_count", 0) < 15 or prior.get("trades_count", 0) < 30:
        return "inconclusive"
    delta = safe_float(latest.get("expectancy_r")) - safe_float(prior.get("expectancy_r"))
    if delta > 0.08:
        return "improving"
    if delta < -0.08:
        return "deteriorating"
    return "stable"


def intelligence_growth_score(windows: list[dict], current: dict) -> float:
    base = safe_float(current.get("intelligence_growth_score"))
    latest = next((item for item in windows if item.get("window_size") == 30), None)
    prior = next((item for item in windows if item.get("window_size") == 100), None)
    if latest and prior:
        delta = safe_float(latest.get("intelligence_growth_score")) - safe_float(prior.get("intelligence_growth_score"))
        base += delta * 0.35
    return clamp(base)


def progress_explanation(trend: str, score: float, windows: list[dict], current: dict) -> str:
    return (
        f"Learning trend is {trend}; Intelligence Growth Score is {score:.1f}/100. "
        f"Current sample: {current.get('trades_count', 0)} trades/actions. "
        "The score is cautious when live evidence, sample size or benchmark confirmation are incomplete."
    )


def benchmark_explanation(benchmark: str, benchmark_type: str, sample: int, blum_return: float | None, benchmark_return: float | None, excess: float | None, label: str, benchmark_returns: list[float]) -> str:
    source = "same-period benchmark rows" if benchmark_returns else "price-history period proxy or unavailable fallback"
    return (
        f"BLUM vs {benchmark} ({benchmark_type}) uses {source}. Sample={sample}. "
        f"BLUM trade-weighted return={round_or_none(blum_return)}%, benchmark={round_or_none(benchmark_return)}%, "
        f"excess={round_or_none(excess)}%. Result={label}."
    )


def baseline_explanation(name: str, sample: int, baseline: float | None, excess: float | None, label: str) -> str:
    return (
        f"{name} is an internal baseline proxy built from the same decision ledger, not an external execution proof. "
        f"Sample={sample}; baseline={round_or_none(baseline)}%; excess={round_or_none(excess)}%; result={label}."
    )


def downside_volatility(values: list[float]) -> float | None:
    downside = [value for value in values if value < 0]
    return pstdev(downside) if len(downside) > 1 else None


def ratio_or_none(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or abs(denominator) < 0.0001:
        return None
    return round(numerator / denominator, 4)


def hit_rate_vs_benchmark(returns: list[float], benchmark_returns: list[float]) -> float | None:
    if not returns or not benchmark_returns:
        return None
    paired = list(zip(returns, benchmark_returns))
    return sum(1 for blum, bench in paired if blum > bench) / max(1, len(paired))


def round_or_none(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def compact_numbers(values: list[object]) -> list[float]:
    return [safe_float(value) for value in values if value is not None]


def first_date(rows: list[TradingGameTrade]) -> str | None:
    dates = [row.entry_date for row in rows if row.entry_date]
    return min(dates).isoformat() if dates else None


def last_date(rows: list[TradingGameTrade]) -> str | None:
    dates = [row.exit_date or row.entry_date for row in rows if row.exit_date or row.entry_date]
    return max(dates).isoformat() if dates else None


def parse_date_value(value: str | date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def dedupe_strings(rows: list[str]) -> list[str]:
    output = []
    seen = set()
    for row in rows:
        text = str(row).strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def dedupe_actions(rows: list[dict]) -> list[dict]:
    output = []
    seen = set()
    for row in rows:
        key = (row.get("source_dimension"), row.get("detected_problem"), row.get("affected_module"))
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output


def priority_rank(priority: str) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(priority, 0)


def serialize_action(row: SelfImprovementAction) -> dict:
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "source_metric": row.source_metric,
        "source_dimension": row.source_dimension,
        "detected_problem": row.detected_problem,
        "recommended_action": row.recommended_action,
        "affected_module": row.affected_module,
        "priority": row.priority,
        "expected_impact": row.expected_impact,
        "status": row.status,
        "applied_at": row.applied_at.isoformat() if row.applied_at else None,
        "before_metric": row.before_metric,
        "after_metric": row.after_metric,
        "improvement_observed": row.improvement_observed,
        "notes_json": row.notes_json,
    }
