from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
import math
import re
from statistics import fmean, pstdev

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    HyperbolicReplayTrade,
    LiveForwardPaperTrade,
    ReplayStrategyValidation,
    StrategyEvidenceSnapshot,
)
from app.services.copy_readiness_metrics import (
    INTRADAY_FORWARD_EVIDENCE,
    PAPER_FORWARD_EVIDENCE,
    REPLAY_EVIDENCE,
    WALK_FORWARD_EVIDENCE,
    canonical_evidence_class,
    concentration,
    wilson_interval,
)


TERMINAL_FORWARD_STATUSES = frozenset({"CLOSED", "EXPIRED", "INVALIDATED"})
TERMINAL_REPLAY_STATES = frozenset({"CLOSED", "COMPLETED", "EXITED", "SETTLED"})
MAX_PROJECT_ITEMS = 500
MAX_QUERY_LIMIT = 100


@dataclass(frozen=True)
class _EvidenceRow:
    source_type: str
    source_id: int
    strategy_id: str
    setup_type: str
    evidence_class: str
    total_trade: bool
    terminal: bool
    gross_pnl: float | None
    net_pnl: float | None
    costs_paid: float | None
    slippage: float | None
    r_multiple: float | None
    benchmark_return: float | None
    benchmark_excess: float | None
    ticker: str | None
    market: str | None
    timeframe: str | None
    regime: str | None
    timestamp: datetime | None
    warnings: tuple[str, ...] = ()
    sample_size: int = 1
    reported_win_rate: float | None = None


def strategy_identity(setup_type: str, promoted_validation_id: int | None) -> tuple[str, list[str]]:
    """Return the durable strategy identifier used by all evidence projections."""

    if promoted_validation_id:
        return f"validation:{promoted_validation_id}", []
    return f"setup:{normalize_setup(setup_type)}", ["strategy_identity_fallback"]


def normalize_setup(value: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    return normalized.strip("_") or "unknown"


class StrategyEvidenceProjector:
    """Append class-specific evidence cards from persisted replay and paper records."""

    def project(self, db: Session, *, max_items: int = MAX_PROJECT_ITEMS) -> dict:
        remaining = _bounded_limit(max_items, maximum=MAX_PROJECT_ITEMS)
        source_rows: list[_EvidenceRow] = []

        for loader in (
            self._load_replay_rows,
            self._load_walk_forward_rows,
            self._load_paper_forward_rows,
            self._load_intraday_forward_rows,
        ):
            if remaining <= 0:
                break
            rows = loader(db, limit=remaining)
            source_rows.extend(rows)
            remaining -= len(rows)

        grouped: dict[tuple[str, str, str], list[_EvidenceRow]] = defaultdict(list)
        for row in source_rows:
            grouped[(row.strategy_id, row.setup_type, row.evidence_class)].append(row)

        snapshots = [self._snapshot_for_rows(key, rows) for key, rows in grouped.items()]
        db.add_all(snapshots)
        db.flush()
        return {
            "source_rows_processed": len(source_rows),
            "snapshots_created": len(snapshots),
            "max_items": _bounded_limit(max_items, maximum=MAX_PROJECT_ITEMS),
        }

    def _load_replay_rows(self, db: Session, *, limit: int) -> list[_EvidenceRow]:
        rows = db.scalars(
            select(HyperbolicReplayTrade)
            .order_by(HyperbolicReplayTrade.decision_timestamp.desc(), HyperbolicReplayTrade.id.desc())
            .limit(limit)
        ).all()
        evidence: list[_EvidenceRow] = []
        for row in rows:
            strategy_id, warnings = strategy_identity(row.setup_type, None)
            execution = row.execution_payload or {}
            outcome = row.outcome_payload or {}
            gross = _number(row.gross_pnl)
            net = _number(row.net_pnl)
            costs = _first_number(execution, "costs_paid", "total_costs", "commission_cost", "commission")
            if costs is None and gross is not None and net is not None:
                costs = max(0.0, gross - net)
            evidence.append(
                _EvidenceRow(
                    source_type="hyperbolic_replay_trade",
                    source_id=row.id,
                    strategy_id=strategy_id,
                    setup_type=normalize_setup(row.setup_type),
                    evidence_class=REPLAY_EVIDENCE,
                    total_trade=True,
                    terminal=(str(row.state or "").upper() in TERMINAL_REPLAY_STATES or row.exit_timestamp is not None),
                    gross_pnl=gross,
                    net_pnl=net if net is not None else _net_from_gross(gross, costs),
                    costs_paid=costs,
                    slippage=_first_number(execution, "slippage_cost", "slippage"),
                    r_multiple=_number(row.r_multiple),
                    benchmark_return=_first_number(outcome, "benchmark_return", "benchmark_return_same_period"),
                    benchmark_excess=_number(row.benchmark_excess),
                    ticker=row.ticker,
                    market=row.market,
                    timeframe=row.timeframe,
                    regime=_string(outcome.get("regime")),
                    timestamp=row.exit_timestamp or row.decision_timestamp or row.created_at,
                    warnings=tuple(warnings),
                )
            )
        return evidence

    def _load_walk_forward_rows(self, db: Session, *, limit: int) -> list[_EvidenceRow]:
        rows = db.scalars(
            select(ReplayStrategyValidation)
            .order_by(ReplayStrategyValidation.created_at.desc(), ReplayStrategyValidation.id.desc())
            .limit(limit)
        ).all()
        evidence: list[_EvidenceRow] = []
        for row in rows:
            metrics = row.metrics_json or {}
            strategy_id, warnings = strategy_identity(row.setup_type, row.id)
            sample_size = max(0, _integer(row.sample_size))
            evidence.append(
                _EvidenceRow(
                    source_type="replay_strategy_validation",
                    source_id=row.id,
                    strategy_id=strategy_id,
                    setup_type=normalize_setup(row.setup_type),
                    evidence_class=WALK_FORWARD_EVIDENCE,
                    total_trade=sample_size > 0,
                    terminal=sample_size > 0,
                    gross_pnl=_first_number(metrics, "gross_expectancy", "gross_pnl", "expectancy"),
                    net_pnl=_first_number(metrics, "net_expectancy", "expectancy_r", "expectancy"),
                    costs_paid=_first_number(metrics, "total_costs", "costs_paid"),
                    slippage=_first_number(metrics, "average_slippage", "slippage"),
                    r_multiple=_first_number(metrics, "average_r", "expectancy_r"),
                    benchmark_return=_first_number(metrics, "benchmark_return", "benchmark_return_same_period"),
                    benchmark_excess=_first_number(metrics, "benchmark_excess", "excess_return_vs_benchmark"),
                    ticker=None,
                    market=_string((row.markets_json or [None])[0]),
                    timeframe=_string((metrics.get("timeframe_stack") or [None])[-1]),
                    regime=_regime_from_windows(row.windows_json),
                    timestamp=row.created_at,
                    warnings=tuple(warnings),
                    sample_size=sample_size,
                    reported_win_rate=_first_number(metrics, "win_rate"),
                )
            )
        return evidence

    def _load_paper_forward_rows(self, db: Session, *, limit: int) -> list[_EvidenceRow]:
        intraday = or_(
            LiveForwardPaperTrade.evidence_type.in_(("PAPER_FORWARD_INTRADAY", INTRADAY_FORWARD_EVIDENCE)),
            LiveForwardPaperTrade.trading_mode.ilike("%INTRADAY%"),
        )
        rows = db.scalars(
            select(LiveForwardPaperTrade)
            .where(~intraday)
            .order_by(LiveForwardPaperTrade.decision_timestamp.desc(), LiveForwardPaperTrade.id.desc())
            .limit(limit)
        ).all()
        return [self._forward_row(row, evidence_class=PAPER_FORWARD_EVIDENCE) for row in rows]

    def _load_intraday_forward_rows(self, db: Session, *, limit: int) -> list[_EvidenceRow]:
        intraday = or_(
            LiveForwardPaperTrade.evidence_type.in_(("PAPER_FORWARD_INTRADAY", INTRADAY_FORWARD_EVIDENCE)),
            LiveForwardPaperTrade.trading_mode.ilike("%INTRADAY%"),
        )
        rows = db.scalars(
            select(LiveForwardPaperTrade)
            .where(intraday)
            .order_by(LiveForwardPaperTrade.decision_timestamp.desc(), LiveForwardPaperTrade.id.desc())
            .limit(limit)
        ).all()
        return [self._forward_row(row, evidence_class=INTRADAY_FORWARD_EVIDENCE) for row in rows]

    def _forward_row(self, row: LiveForwardPaperTrade, *, evidence_class: str) -> _EvidenceRow:
        strategy_id, warnings = strategy_identity(row.setup_type, row.promoted_validation_id)
        payload = row.frozen_decision_payload or {}
        costs = _number(row.costs_paid)
        gross = _number(row.gross_pnl_eur)
        net = _number(row.net_pnl_eur)
        terminal = str(row.status or "").upper() in TERMINAL_FORWARD_STATUSES and row.closed_at is not None
        return _EvidenceRow(
            source_type="live_forward_paper_trade",
            source_id=row.id,
            strategy_id=strategy_id,
            setup_type=normalize_setup(row.setup_type),
            evidence_class=evidence_class,
            total_trade=True,
            terminal=terminal,
            gross_pnl=gross,
            net_pnl=net if net is not None else _net_from_gross(gross, costs),
            costs_paid=costs,
            slippage=_number(row.slippage_cost),
            r_multiple=_number(row.r_multiple),
            benchmark_return=_number(row.benchmark_return_same_period),
            benchmark_excess=_number(row.excess_return_vs_benchmark),
            ticker=row.ticker,
            market=row.market,
            timeframe=_string((row.timeframe_stack or [None])[-1]),
            regime=_string(payload.get("regime")) or _string((row.intraday_metadata or {}).get("regime")),
            timestamp=row.closed_at or row.decision_timestamp or row.created_at,
            warnings=tuple(warnings),
        )

    def _snapshot_for_rows(
        self,
        key: tuple[str, str, str],
        rows: list[_EvidenceRow],
    ) -> StrategyEvidenceSnapshot:
        strategy_id, setup_type, evidence_class = key
        terminal_rows = [row for row in rows if row.terminal]
        gross_values = _numbers(row.gross_pnl for row in terminal_rows)
        net_values = _numbers(row.net_pnl for row in terminal_rows)
        r_values = _numbers(row.r_multiple for row in terminal_rows)
        benchmark_returns = _numbers(row.benchmark_return for row in terminal_rows)
        benchmark_excesses = _numbers(row.benchmark_excess for row in terminal_rows)
        costs = _numbers(row.costs_paid for row in terminal_rows)
        slippages = _numbers(row.slippage for row in terminal_rows)
        summary_rows = [row for row in terminal_rows if row.sample_size > 1 and row.reported_win_rate is not None]
        raw_rows = [row for row in terminal_rows if row not in summary_rows]
        raw_wins = sum(1 for row in raw_rows if row.net_pnl is not None and row.net_pnl > 0)
        summary_sample_size = sum(row.sample_size for row in summary_rows)
        summary_wins = sum((row.reported_win_rate or 0.0) * row.sample_size for row in summary_rows)
        measured_sample_size = len([row for row in raw_rows if row.net_pnl is not None]) + summary_sample_size
        wins = raw_wins + summary_wins
        regimes = _regime_groups(terminal_rows)
        timestamps = [row.timestamp for row in rows if row.timestamp is not None]
        warnings = sorted({warning for row in rows for warning in row.warnings})
        if not benchmark_returns:
            warnings.append("benchmark_unavailable")
        if not costs:
            warnings.append("costs_unavailable")
        if summary_rows:
            warnings.append("confidence_interval_unavailable_from_summary_metrics")

        metrics = {
            "data_timestamp": max(timestamps).isoformat() if timestamps else None,
            "metric_provenance": {
                "source_models": sorted({row.source_type for row in rows}),
                "performance_rows": "terminal outcomes only",
                "benchmark": "stored source benchmark values only",
                "costs": "stored costs_paid; net pnl falls back to gross pnl minus stored costs",
            },
            "best_regime": _regime_extreme(regimes, reverse=True),
            "worst_regime": _regime_extreme(regimes, reverse=False),
        }
        return StrategyEvidenceSnapshot(
            strategy_id=strategy_id,
            setup_type=setup_type,
            evidence_class=evidence_class,
            total_trades=sum(row.sample_size for row in rows if row.total_trade),
            closed_trades=sum(row.sample_size for row in terminal_rows),
            forward_trades=sum(row.sample_size for row in terminal_rows) if evidence_class in {PAPER_FORWARD_EVIDENCE, INTRADAY_FORWARD_EVIDENCE} else 0,
            win_rate=wins / measured_sample_size if measured_sample_size else None,
            gross_expectancy=_mean(gross_values),
            net_expectancy=_mean(net_values),
            average_r=_mean(r_values),
            profit_factor=_profit_factor(net_values),
            sharpe_proxy=_sharpe_proxy(net_values),
            sortino_proxy=_sortino_proxy(net_values),
            max_drawdown=_max_drawdown(terminal_rows),
            benchmark_return=_mean(benchmark_returns),
            benchmark_excess=_mean(benchmark_excesses),
            total_costs=sum(costs) if costs else None,
            average_slippage=_mean(slippages),
            metrics_json=metrics,
            markets_json=sorted({row.market for row in rows if row.market}),
            timeframes_json=sorted({row.timeframe for row in rows if row.timeframe}),
            source_rows_json=[
                {"source_type": row.source_type, "source_id": row.source_id, "timestamp": row.timestamp.isoformat() if row.timestamp else None}
                for row in rows
            ],
            warnings_json=sorted(set(warnings)),
            concentration_json={
                "tickers": concentration([row.ticker or "" for row in terminal_rows]),
                "markets": concentration([row.market or "" for row in terminal_rows]),
            },
            regimes_json=regimes,
            confidence_interval_json=(
                wilson_interval(round(wins), measured_sample_size) if not summary_rows else None
            )
            or {},
            evaluated_at=datetime.utcnow(),
        )


class StrategyEvidenceQuery:
    """Read the newest immutable card per strategy and evidence class."""

    def latest_cards(
        self,
        db: Session,
        *,
        limit: int,
        offset: int,
        strategy_id: str | None = None,
    ) -> dict:
        bounded_limit = _bounded_limit(limit, maximum=MAX_QUERY_LIMIT)
        bounded_offset = max(0, _integer(offset))
        rank = func.row_number().over(
            partition_by=(StrategyEvidenceSnapshot.strategy_id, StrategyEvidenceSnapshot.evidence_class),
            order_by=(StrategyEvidenceSnapshot.evaluated_at.desc(), StrategyEvidenceSnapshot.id.desc()),
        ).label("rank")
        ranked = select(StrategyEvidenceSnapshot.id.label("id"), rank).subquery()
        statement = (
            select(StrategyEvidenceSnapshot)
            .join(ranked, StrategyEvidenceSnapshot.id == ranked.c.id)
            .where(ranked.c.rank == 1)
        )
        if strategy_id is not None:
            statement = statement.where(StrategyEvidenceSnapshot.strategy_id == strategy_id)
        total = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
        rows = db.scalars(
            statement.order_by(StrategyEvidenceSnapshot.evaluated_at.desc(), StrategyEvidenceSnapshot.id.desc())
            .offset(bounded_offset)
            .limit(bounded_limit)
        ).all()
        return {
            "items": [_serialize_snapshot(row) for row in rows],
            "total": total,
            "limit": bounded_limit,
            "offset": bounded_offset,
        }


def _serialize_snapshot(row: StrategyEvidenceSnapshot) -> dict:
    return {
        "id": row.id,
        "strategy_id": row.strategy_id,
        "setup_type": row.setup_type,
        "evidence_class": row.evidence_class,
        "total_trades": row.total_trades,
        "closed_trades": row.closed_trades,
        "forward_trades": row.forward_trades,
        "win_rate": row.win_rate,
        "gross_expectancy": row.gross_expectancy,
        "net_expectancy": row.net_expectancy,
        "average_r": row.average_r,
        "profit_factor": row.profit_factor,
        "sharpe_proxy": row.sharpe_proxy,
        "sortino_proxy": row.sortino_proxy,
        "max_drawdown": row.max_drawdown,
        "benchmark_return": row.benchmark_return,
        "benchmark_excess": row.benchmark_excess,
        "total_costs": row.total_costs,
        "average_slippage": row.average_slippage,
        "metrics": row.metrics_json or {},
        "markets": row.markets_json or [],
        "timeframes": row.timeframes_json or [],
        "source_rows": row.source_rows_json or [],
        "warnings": row.warnings_json or [],
        "concentration": row.concentration_json or {},
        "regimes": row.regimes_json or [],
        "confidence_interval": row.confidence_interval_json or {},
        "evaluated_at": row.evaluated_at.isoformat() if row.evaluated_at else None,
    }


def _bounded_limit(value: int, *, maximum: int) -> int:
    return min(maximum, max(1, _integer(value)))


def _integer(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _first_number(values: dict, *keys: str) -> float | None:
    for key in keys:
        number = _number(values.get(key))
        if number is not None:
            return number
    return None


def _string(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _net_from_gross(gross: float | None, costs: float | None) -> float | None:
    if gross is None:
        return None
    return gross - costs if costs is not None else gross


def _numbers(values) -> list[float]:
    return [number for value in values if (number := _number(value)) is not None]


def _mean(values: list[float]) -> float | None:
    return fmean(values) if values else None


def _profit_factor(values: list[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    return gains / losses if gains > 0 and losses > 0 else None


def _sharpe_proxy(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    deviation = pstdev(values)
    return fmean(values) / deviation if deviation > 0 else None


def _sortino_proxy(values: list[float]) -> float | None:
    downside = [value for value in values if value < 0]
    if not values or not downside:
        return None
    deviation = math.sqrt(fmean(value * value for value in downside))
    return fmean(values) / deviation if deviation > 0 else None


def _max_drawdown(rows: list[_EvidenceRow]) -> float | None:
    values = [(row.timestamp, row.net_pnl) for row in rows if row.net_pnl is not None]
    if not values:
        return None
    equity = peak = 0.0
    drawdown = 0.0
    for _, net_pnl in sorted(values, key=lambda item: item[0] or datetime.min):
        equity += net_pnl or 0.0
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return abs(drawdown)


def _regime_from_windows(windows: list | None) -> str | None:
    for window in windows or []:
        if isinstance(window, dict):
            regime = _string(window.get("regime"))
            if regime:
                return regime
    return None


def _regime_groups(rows: list[_EvidenceRow]) -> list[dict]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row.regime and row.net_pnl is not None:
            grouped[row.regime].append(row.net_pnl)
    return [
        {"regime": regime, "closed_trades": len(values), "net_expectancy": _mean(values)}
        for regime, values in sorted(grouped.items())
    ]


def _regime_extreme(regimes: list[dict], *, reverse: bool) -> str | None:
    measured = [row for row in regimes if _number(row.get("net_expectancy")) is not None]
    if not measured:
        return None
    return sorted(
        measured,
        key=lambda row: (_number(row["net_expectancy"]) or 0.0, str(row["regime"])),
        reverse=reverse,
    )[0]["regime"]
