from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean
from typing import Any

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    BenchmarkMethodologyValidation,
    BlumTradingPowerScore,
    LearningRun,
    LiveForwardPaperGame,
    LiveForwardPaperTrade,
)
from app.services.copy_readiness_evidence import CopyReadinessSummaryService
from app.services.institutional_pilot import (
    PilotPolicyThresholds,
    PilotReadinessContext,
    evaluate_pilot_readiness,
)
from app.services.promoted_strategy_registry import BlumPromotedStrategyRegistry


LEARNING_SERIES_LIMIT = 30
PAPER_TRADE_LIMIT = 120
PILOT_EVIDENCE_MAX_AGE_HOURS = 36


class BrainLearningProofService:
    """Build bounded, read-only evidence projections for the Brain surface."""

    def snapshot(self, db: Session) -> dict:
        trading_proof = self._trading_proof(db)
        copy_summary = CopyReadinessSummaryService().summary(db)
        registry_status = BlumPromotedStrategyRegistry().status(db)
        methodology = db.scalar(
            select(BenchmarkMethodologyValidation)
            .order_by(desc(BenchmarkMethodologyValidation.created_at), desc(BenchmarkMethodologyValidation.id))
            .limit(1)
        )
        return {
            "brain_progress": self._brain_progress(db),
            "learning_proof": self._learning_proof(db),
            "trading_proof": trading_proof,
            "copy_readiness": _copy_readiness_proof(copy_summary),
            "institutional_pilot": _institutional_pilot_proof(
                copy_summary=copy_summary,
                trading_proof=trading_proof,
                registry_status=registry_status,
                methodology=methodology,
            ),
        }

    def _brain_progress(self, db: Session) -> dict:
        rows = db.scalars(
            select(BlumTradingPowerScore)
            .order_by(desc(BlumTradingPowerScore.calculated_at))
            .limit(LEARNING_SERIES_LIMIT)
        ).all()
        series = [
            {
                "timestamp": _iso(row.calculated_at),
                "brain_score": _number(row.score),
                "decision_quality": _number(row.decision_quality_score),
                "learning_velocity": _number(row.learning_velocity_score),
                "evidence_quality": _number(row.statistical_confidence_score),
            }
            for row in reversed(rows)
        ]
        return {
            "series": series,
            "sample_size": len(series),
            "trend": _score_trend(series),
            "evidence_warning": _sample_warning(len(series), "Brain score snapshots", minimum=5),
        }

    def _learning_proof(self, db: Session) -> dict:
        rows = db.scalars(
            select(LearningRun).order_by(desc(LearningRun.started_at)).limit(LEARNING_SERIES_LIMIT)
        ).all()
        ordered = list(reversed(rows))
        productive = [row for row in ordered if _run_is_productive(row)]
        predictions = sum(int(row.predictions_created or 0) for row in ordered)
        outcomes = sum(int(row.outcomes_evaluated or 0) for row in ordered)
        memory_updates = sum(int(row.memory_updates or 0) for row in ordered)
        series = [
            {
                "timestamp": _iso(row.started_at),
                "status": row.status,
                "predictions": int(row.predictions_created or 0),
                "outcomes": int(row.outcomes_evaluated or 0),
                "memory_updates": int(row.memory_updates or 0),
            }
            for row in ordered
        ]
        return {
            "cycles_observed": len(ordered),
            "productive_cycles": len(productive),
            "predictions_created": predictions,
            "outcomes_evaluated": outcomes,
            "memory_updates": memory_updates,
            "outcome_conversion_rate": _ratio(outcomes, predictions),
            "memory_updates_per_prediction": _ratio(memory_updates, predictions),
            "latest_productive_cycle_at": _iso(productive[-1].started_at) if productive else None,
            "series": series,
            "trend": _learning_trend(productive),
            "sample_warning": _sample_warning(len(productive), "productive learning cycles", minimum=5),
        }

    def _trading_proof(self, db: Session) -> dict:
        game = db.scalar(
            select(LiveForwardPaperGame)
            .order_by(desc(LiveForwardPaperGame.updated_at), desc(LiveForwardPaperGame.id))
            .limit(1)
        )
        if game is None:
            return _empty_trading_proof("No paper-forward game exists yet.")

        terminal_statuses = ("CLOSED", "EXITED", "EXPIRED", "INVALIDATED")
        closed_rows = db.scalars(
            select(LiveForwardPaperTrade)
            .where(LiveForwardPaperTrade.game_id == game.id)
            .where(
                or_(
                    LiveForwardPaperTrade.closed_at.is_not(None),
                    LiveForwardPaperTrade.exit_price.is_not(None),
                    LiveForwardPaperTrade.close_reason.is_not(None),
                    func.upper(LiveForwardPaperTrade.status).in_(terminal_statuses),
                )
            )
            .order_by(
                desc(
                    func.coalesce(
                        LiveForwardPaperTrade.closed_at,
                        LiveForwardPaperTrade.updated_at,
                        LiveForwardPaperTrade.decision_timestamp,
                    )
                )
            )
            .limit(PAPER_TRADE_LIMIT)
        ).all()
        open_rows = db.scalars(
            select(LiveForwardPaperTrade)
            .where(LiveForwardPaperTrade.game_id == game.id)
            .where(func.upper(LiveForwardPaperTrade.status) == "OPEN")
            .where(LiveForwardPaperTrade.closed_at.is_(None))
            .where(LiveForwardPaperTrade.exit_price.is_(None))
            .where(LiveForwardPaperTrade.close_reason.is_(None))
            .order_by(desc(LiveForwardPaperTrade.decision_timestamp))
            .limit(PAPER_TRADE_LIMIT)
        ).all()
        closed = sorted(
            closed_rows,
            key=lambda row: row.closed_at or row.updated_at or row.decision_timestamp,
        )
        pnl_values = [_number(row.net_pnl_eur) for row in closed if row.net_pnl_eur is not None]
        r_values = [_number(row.r_multiple) for row in closed if row.r_multiple is not None]
        wins = sum(1 for row in closed if _trade_won(row))
        losses = sum(1 for row in closed if _trade_lost(row))
        breakeven = max(0, len(closed) - wins - losses)
        equity_series, benchmark_coverage = _equity_series(closed, _starting_capital(game))
        realized_pnl = round(sum(value for value in pnl_values if value is not None), 4)
        unrealized_pnl = round(sum(_number(row.unrealized_pnl) or 0.0 for row in open_rows), 4)
        current_capital = _number(game.current_capital) or _starting_capital(game)
        daily_losses = [
            abs(_number(row.net_pnl_eur) or 0.0)
            for row in closed
            if (row.closed_at or row.updated_at or row.decision_timestamp).date() == datetime.utcnow().date()
            and (_number(row.net_pnl_eur) or 0.0) < 0
        ]
        open_risk = sum(max(0.0, _number(row.risk_amount) or 0.0) for row in open_rows)
        final_point = equity_series[-1] if equity_series else None
        benchmark_return = _equity_return(final_point, "benchmark_equity", _starting_capital(game))
        blum_return = _equity_return(final_point, "blum_equity", _starting_capital(game))
        profit_factor = _profit_factor(pnl_values)
        return {
            "status": "ready" if closed else "insufficient_evidence",
            "evidence_class": "PAPER_FORWARD_EVIDENCE",
            "game_id": game.game_id,
            "starting_capital": _starting_capital(game),
            "current_capital": _number(game.current_capital),
            "closed_trades": len(closed),
            "open_trades": len(open_rows),
            "wins": wins,
            "losses": losses,
            "breakeven": breakeven,
            "win_rate": _ratio(wins, len(closed)),
            "realized_pnl_eur": realized_pnl,
            "unrealized_pnl_eur": unrealized_pnl,
            "expectancy_r": _average(r_values),
            "profit_factor": profit_factor,
            "max_drawdown_pct": _max_drawdown(equity_series),
            "daily_loss_pct": round(sum(daily_losses) / current_capital * 100.0, 4) if current_capital > 0 else None,
            "aggregate_open_risk_pct": round(open_risk / current_capital * 100.0, 4) if current_capital > 0 else None,
            "blum_return_pct": blum_return,
            "benchmark_return_pct": benchmark_return,
            "benchmark_excess_pct": _difference(blum_return, benchmark_return),
            "benchmark_coverage": benchmark_coverage,
            "equity_series": equity_series,
            "trend": _pnl_trend(pnl_values),
            "sample_warning": _sample_warning(len(closed), "closed paper-forward trades", minimum=30),
            "benchmark_warning": None if benchmark_coverage == 1.0 else "Benchmark coverage is incomplete; comparison is not conclusive.",
            "curve_method": "Cumulative net P/L and same-holding-period benchmark contribution, normalized to game starting capital.",
        }


def _copy_readiness_proof(summary: dict) -> dict:
    strategy_forward = _number(summary.get("strategy_forward_trades"))
    required_strategy = _number(summary.get("required_strategy_forward_trades"))
    observation_days = _number(summary.get("observation_days"))
    required_days = _number(summary.get("required_observation_days"))
    return {
        **summary,
        "strategy_forward_progress": _progress(strategy_forward, required_strategy),
        "global_forward_progress": _progress(
            _number(summary.get("global_forward_trades")),
            _number(summary.get("required_global_forward_trades")),
        ),
        "observation_progress": _progress(observation_days, required_days),
        "capital_strategy_forward_progress": _progress(
            strategy_forward,
            _number(summary.get("required_capital_strategy_forward_trades")),
        ),
        "capital_global_forward_progress": _progress(
            _number(summary.get("global_forward_trades")),
            _number(summary.get("required_capital_global_forward_trades")),
        ),
        "capital_observation_progress": _progress(
            observation_days,
            _number(summary.get("required_capital_observation_days")),
        ),
        "copy_trading_allowed": summary.get("copy_readiness_status") in {
            "COPY_READY_PAPER_ONLY",
            "COPY_READY_HIGH_CONFIDENCE",
        },
        "evidence_warning": None
        if summary.get("copy_readiness_status") in {"COPY_READY_PAPER_ONLY", "COPY_READY_HIGH_CONFIDENCE"}
        else "Paper evidence is not mature enough for copy trading.",
    }


def _institutional_pilot_proof(
    *,
    copy_summary: dict,
    trading_proof: dict,
    registry_status: dict,
    methodology: BenchmarkMethodologyValidation | None,
) -> dict:
    settings = get_settings()
    thresholds = PilotPolicyThresholds(
        global_forward_trades=settings.limited_external_validation_global_forward_trades,
        strategy_forward_trades=settings.limited_external_validation_strategy_forward_trades,
        observation_days=settings.limited_external_validation_observation_days,
        max_evidence_drawdown_pct=settings.limited_external_validation_max_drawdown,
        max_replay_forward_decay_pct=settings.limited_external_validation_max_decay_pct,
        min_tickers=settings.limited_external_validation_min_tickers,
        min_regimes=settings.limited_external_validation_min_regimes,
        max_ticker_concentration=settings.limited_external_validation_max_ticker_concentration,
        max_market_concentration=settings.limited_external_validation_max_market_concentration,
    )
    promoted_count = int(registry_status.get("eligible_intraday_strategies") or 0)
    context = PilotReadinessContext(
        copy_readiness_status=str(copy_summary.get("copy_readiness_status") or "NOT_READY"),
        real_capital_eligibility=str(copy_summary.get("real_capital_eligibility") or "NOT_ELIGIBLE"),
        global_forward_trades=_integer_or_none(copy_summary.get("global_forward_trades")),
        strategy_forward_trades=_integer_or_none(copy_summary.get("strategy_forward_trades")),
        observation_days=_integer_or_none(copy_summary.get("observation_days")),
        promoted_strategy_count=promoted_count,
        exact_fingerprint_match=copy_summary.get("exact_fingerprint_match"),
        evidence_fresh=_evidence_is_fresh(copy_summary.get("evaluated_at")),
        benchmark_methodology_valid=(methodology.methodology_valid if methodology is not None else None),
        costs_available=copy_summary.get("costs_available"),
        slippage_available=copy_summary.get("slippage_available"),
        data_quality_available=copy_summary.get("data_quality_available"),
        runtime_healthy=True,
        persistence_healthy=True,
        net_expectancy=_first_present_number(
            copy_summary.get("net_expectancy"), trading_proof.get("expectancy_r")
        ),
        benchmark_excess=_first_present_number(
            copy_summary.get("benchmark_excess"), trading_proof.get("benchmark_excess_pct")
        ),
        evidence_max_drawdown_pct=_number(copy_summary.get("max_drawdown")),
        replay_forward_decay_pct=_number(copy_summary.get("replay_forward_decay_pct")),
        ticker_count=_integer_or_none(copy_summary.get("ticker_count")),
        regime_count=_integer_or_none(copy_summary.get("regime_count")),
        ticker_concentration=_number(copy_summary.get("ticker_concentration")),
        market_concentration=_number(copy_summary.get("market_concentration")),
        daily_loss_pct=_number(trading_proof.get("daily_loss_pct")),
        pilot_drawdown_pct=_number(trading_proof.get("max_drawdown_pct")),
        aggregate_open_risk_pct=_number(trading_proof.get("aggregate_open_risk_pct")),
        strategy_operational_status="PROMOTED" if promoted_count > 0 else None,
    )
    payload = evaluate_pilot_readiness(context, thresholds).to_payload()
    return {
        **payload,
        "promoted_strategy_count": promoted_count,
        "strategy_registry_status": registry_status.get("status"),
        "evidence_evaluated_at": copy_summary.get("evaluated_at"),
        "benchmark_methodology_status": (
            "VALID" if methodology is not None and methodology.methodology_valid else "INVALID"
            if methodology is not None
            else "MISSING"
        ),
    }


def _evidence_is_fresh(value: Any) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return False
    return parsed >= datetime.utcnow() - timedelta(hours=PILOT_EVIDENCE_MAX_AGE_HOURS)


def _integer_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _equity_series(rows: list[LiveForwardPaperTrade], starting_capital: float) -> tuple[list[dict], float]:
    blum_equity = starting_capital
    benchmark_equity = starting_capital
    peak = starting_capital
    benchmark_rows = 0
    points: list[dict] = []
    for row in rows:
        pnl = _number(row.net_pnl_eur)
        if pnl is not None:
            blum_equity += pnl
        peak = max(peak, blum_equity)
        benchmark_pnl = _benchmark_pnl(row)
        if benchmark_pnl is not None:
            benchmark_equity += benchmark_pnl
            benchmark_rows += 1
        points.append(
            {
                "timestamp": _iso(row.closed_at or row.updated_at or row.decision_timestamp),
                "ticker": row.ticker,
                "blum_equity": round(blum_equity, 4),
                "benchmark_equity": round(benchmark_equity, 4) if benchmark_pnl is not None else None,
                "trade_pnl_eur": pnl,
                "benchmark_pnl_eur": benchmark_pnl,
                "drawdown_pct": round(((peak - blum_equity) / peak) * 100.0, 4) if peak > 0 else None,
            }
        )
    return points, _ratio(benchmark_rows, len(rows)) or 0.0


def _benchmark_pnl(row: LiveForwardPaperTrade) -> float | None:
    benchmark_return = _number(row.benchmark_return_same_period)
    notional = _number(row.notional_value)
    if notional is None and row.entry_price is not None and row.position_size is not None:
        notional = _number(row.entry_price * row.position_size)
    if benchmark_return is None or notional is None:
        return None
    return round(notional * benchmark_return / 100.0, 4)


def _max_drawdown(points: list[dict]) -> float | None:
    values = [point.get("drawdown_pct") for point in points if point.get("drawdown_pct") is not None]
    return max(values) if values else None


def _starting_capital(game: LiveForwardPaperGame) -> float:
    value = _number(game.starting_capital)
    return value if value is not None and value > 0 else 100.0


def _equity_return(point: dict | None, key: str, starting_capital: float) -> float | None:
    if point is None or point.get(key) is None or starting_capital <= 0:
        return None
    return round(((float(point[key]) - starting_capital) / starting_capital) * 100.0, 4)


def _trade_is_closed(row: LiveForwardPaperTrade) -> bool:
    return bool(
        row.closed_at
        or row.exit_price is not None
        or row.close_reason
        or str(row.status or "").upper() in {"CLOSED", "EXITED", "EXPIRED", "INVALIDATED"}
    )


def _trade_is_open(row: LiveForwardPaperTrade) -> bool:
    return str(row.status or "").upper() == "OPEN" and not _trade_is_closed(row)


def _trade_won(row: LiveForwardPaperTrade) -> bool:
    label = str(row.outcome_label or row.close_reason or "").lower()
    return label in {"win", "target_hit", "target_1_hit", "target_2_hit"} or (_number(row.net_pnl_eur) or 0.0) > 0


def _trade_lost(row: LiveForwardPaperTrade) -> bool:
    label = str(row.outcome_label or row.close_reason or "").lower()
    return label in {"loss", "stopped_out", "stop_hit", "invalidated", "thesis_invalidated"} or (_number(row.net_pnl_eur) or 0.0) < 0


def _run_is_productive(row: LearningRun) -> bool:
    return any(
        int(value or 0) > 0
        for value in (row.predictions_created, row.outcomes_evaluated, row.memory_updates)
    )


def _learning_trend(rows: list[LearningRun]) -> str:
    if len(rows) < 4:
        return "insufficient_evidence"
    middle = len(rows) // 2
    previous = [_run_conversion(row) for row in rows[:middle]]
    recent = [_run_conversion(row) for row in rows[middle:]]
    return _compare_means(previous, recent)


def _score_trend(series: list[dict]) -> str:
    if len(series) < 2:
        return "insufficient_evidence"
    previous = _number(series[0].get("brain_score"))
    current = _number(series[-1].get("brain_score"))
    if previous is None or current is None:
        return "insufficient_evidence"
    if current > previous:
        return "improving"
    if current < previous:
        return "deteriorating"
    return "stable"


def _pnl_trend(values: list[float | None]) -> str:
    present = [value for value in values if value is not None]
    if len(present) < 10:
        return "insufficient_evidence"
    middle = len(present) // 2
    return _compare_means(present[:middle], present[middle:])


def _compare_means(previous: list[float], recent: list[float]) -> str:
    if not previous or not recent:
        return "insufficient_evidence"
    before = mean(previous)
    after = mean(recent)
    if after > before:
        return "improving"
    if after < before:
        return "deteriorating"
    return "stable"


def _run_conversion(row: LearningRun) -> float:
    return _ratio(int(row.outcomes_evaluated or 0), int(row.predictions_created or 0)) or 0.0


def _profit_factor(values: list[float | None]) -> float | None:
    wins = sum(value for value in values if value is not None and value > 0)
    losses = sum(abs(value) for value in values if value is not None and value < 0)
    if losses <= 0:
        return None
    return round(wins / losses, 4)


def _average(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return round(mean(present), 4) if present else None


def _progress(value: float | None, target: float | None) -> float | None:
    if value is None or target is None or target <= 0:
        return None
    return round(max(0.0, min(1.0, value / target)), 4)


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    if denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 4)


def _difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(left - right, 4)


def _sample_warning(sample_size: int, label: str, *, minimum: int) -> str | None:
    if sample_size >= minimum:
        return None
    return f"Only {sample_size} {label} are available; at least {minimum} are required for a directional conclusion."


def _empty_trading_proof(reason: str) -> dict:
    return {
        "status": "no_data",
        "evidence_class": "PAPER_FORWARD_EVIDENCE",
        "closed_trades": 0,
        "open_trades": 0,
        "wins": 0,
        "losses": 0,
        "breakeven": 0,
        "win_rate": None,
        "realized_pnl_eur": None,
        "unrealized_pnl_eur": None,
        "expectancy_r": None,
        "profit_factor": None,
        "max_drawdown_pct": None,
        "blum_return_pct": None,
        "benchmark_return_pct": None,
        "benchmark_excess_pct": None,
        "benchmark_coverage": None,
        "equity_series": [],
        "trend": "insufficient_evidence",
        "sample_warning": reason,
        "benchmark_warning": "No matched benchmark evidence exists yet.",
        "curve_method": None,
    }


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 4)


def _first_present_number(*values: Any) -> float | None:
    for value in values:
        parsed = _number(value)
        if parsed is not None:
            return parsed
    return None


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else (value.isoformat() if hasattr(value, "isoformat") else None)
