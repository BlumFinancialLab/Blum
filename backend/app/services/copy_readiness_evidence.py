from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
import re
from statistics import fmean, pstdev

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.core.config import Settings, get_settings
from app.models import (
    EvidenceTimelineEvent,
    HyperbolicReplayTrade,
    LiveForwardPaperTrade,
    LiveForwardPaperTradeEvent,
    ReplayStrategyValidation,
    StrategyEvidenceSnapshot,
    StrategyReadinessHistory,
)
from app.services.copy_readiness_metrics import (
    EvidenceProvenance,
    ForwardEvidenceProvenance,
    INTRADAY_FORWARD_EVIDENCE,
    PAPER_FORWARD_EVIDENCE,
    REPLAY_EVIDENCE,
    ReadinessContext,
    ReadinessThresholds,
    WALK_FORWARD_EVIDENCE,
    canonical_evidence_class,
    concentration,
    evaluate_capital_eligibility,
    evaluate_copy_readiness,
    evaluate_decay,
    wilson_interval,
)
from app.services.paper_forward_direction import paper_trade_evidence_is_eligible


TERMINAL_FORWARD_STATUSES = frozenset({"CLOSED", "EXPIRED", "INVALIDATED"})
TERMINAL_REPLAY_STATES = frozenset({"CLOSED", "COMPLETED", "EXITED", "SETTLED"})
MAX_PROJECT_ITEMS = 500
MAX_QUERY_LIMIT = 100
MAX_READINESS_STRATEGIES = 100
FORWARD_EVIDENCE_CLASSES = frozenset({PAPER_FORWARD_EVIDENCE, INTRADAY_FORWARD_EVIDENCE})
REPLAY_EVIDENCE_CLASSES = frozenset({REPLAY_EVIDENCE, WALK_FORWARD_EVIDENCE})
READY_STATUSES = frozenset({"COPY_READY_PAPER_ONLY", "COPY_READY_HIGH_CONFIDENCE"})

LIFECYCLE_EVENT_TYPES = {
    "DECISION_CREATED": "signal_created",
    "TRADE_CANDIDATE_CREATED": "signal_created",
    "INTRADAY_TRADE_CANDIDATE": "signal_created",
    "POSITION_OPENED": "trade_opened",
    "INTRADAY_TRADE_OPENED": "trade_opened",
    "POSITION_UPDATED": "trade_updated",
    "POSITION_CLOSED": "trade_closed",
    "STOP_HIT": "trade_closed",
    "TARGET_HIT": "trade_closed",
    "TARGET_1_HIT": "trade_closed",
    "TARGET_2_HIT": "trade_closed",
    "INVALIDATION_HIT": "trade_closed",
    "TIME_EXIT": "trade_closed",
    "OUTCOME_EVALUATED": "outcome_evaluated",
    "LESSON_CREATED": "lesson_created",
    "MEMORY_UPDATED": "memory_updated",
}


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
        rows = db.scalars(
            select(LiveForwardPaperTrade)
            .where(_not_identified_as_intraday())
            .order_by(LiveForwardPaperTrade.decision_timestamp.desc(), LiveForwardPaperTrade.id.desc())
            .limit(limit)
        ).all()
        return [self._forward_row(row, evidence_class=PAPER_FORWARD_EVIDENCE) for row in rows]

    def _load_intraday_forward_rows(self, db: Session, *, limit: int) -> list[_EvidenceRow]:
        rows = db.scalars(
            select(LiveForwardPaperTrade)
            .where(_identified_as_intraday())
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
        eligible = paper_trade_evidence_is_eligible(row)
        if not eligible:
            warnings = [*warnings, "directional_accounting_not_verified"]
        terminal = (
            eligible
            and str(row.status or "").upper() in TERMINAL_FORWARD_STATUSES
            and row.closed_at is not None
        )
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
            confidence_interval_json=wilson_interval(round(wins), measured_sample_size) if not summary_rows else None,
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
        later = aliased(StrategyEvidenceSnapshot)
        later_snapshot_exists = select(later.id).where(
            later.strategy_id == StrategyEvidenceSnapshot.strategy_id,
            later.evidence_class == StrategyEvidenceSnapshot.evidence_class,
            or_(
                later.evaluated_at > StrategyEvidenceSnapshot.evaluated_at,
                and_(
                    later.evaluated_at == StrategyEvidenceSnapshot.evaluated_at,
                    later.id > StrategyEvidenceSnapshot.id,
                ),
            ),
        ).exists()
        statement = select(StrategyEvidenceSnapshot).where(~later_snapshot_exists)
        if strategy_id is not None:
            statement = statement.where(StrategyEvidenceSnapshot.strategy_id == strategy_id)
        rows = db.scalars(
            statement.order_by(StrategyEvidenceSnapshot.evaluated_at.desc(), StrategyEvidenceSnapshot.id.desc())
            .offset(bounded_offset)
            .limit(bounded_limit + 1)
        ).all()
        has_more = len(rows) > bounded_limit
        page_rows = rows[:bounded_limit]
        return {
            "items": [_serialize_snapshot(row) for row in page_rows],
            "limit": bounded_limit,
            "offset": bounded_offset,
            "has_more": has_more,
            "next_offset": bounded_offset + bounded_limit if has_more else None,
        }


class EvidenceTimelineService:
    """Append immutable timeline events while treating only event-key conflicts as idempotent."""

    def append_once(
        self,
        db: Session,
        *,
        event_key: str,
        event_type: str,
        strategy_id: str | None,
        trade_id: int | None,
        payload: dict,
    ) -> EvidenceTimelineEvent:
        with db.no_autoflush:
            existing = db.scalar(
                select(EvidenceTimelineEvent)
                .where(EvidenceTimelineEvent.event_key == event_key)
                .limit(1)
            )
        if existing is not None:
            return existing

        event = EvidenceTimelineEvent(
            event_key=event_key,
            event_type=event_type,
            strategy_id=strategy_id,
            trade_id=trade_id,
            payload_json=dict(payload),
        )
        try:
            with db.begin_nested():
                db.add(event)
                db.flush()
        except IntegrityError:
            with db.no_autoflush:
                existing = db.scalar(
                    select(EvidenceTimelineEvent)
                    .where(EvidenceTimelineEvent.event_key == event_key)
                    .limit(1)
                )
            if existing is not None:
                return existing
            raise
        return event


class BlumCopyReadinessEngine:
    """Evaluate the newest immutable evidence projections and append readiness history."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        timeline: EvidenceTimelineService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.timeline = timeline or EvidenceTimelineService()

    def recalculate(self, db: Session, *, max_strategies: int = MAX_READINESS_STRATEGIES) -> dict:
        bounded_max = _bounded_strategy_limit(max_strategies)
        thresholds = _readiness_thresholds(self.settings)
        cards = _latest_evidence_cards(db, max_strategies=bounded_max)
        cards_by_strategy: dict[str, list[StrategyEvidenceSnapshot]] = defaultdict(list)
        strategy_order: list[str] = []
        for card in cards:
            if card.strategy_id not in cards_by_strategy:
                strategy_order.append(card.strategy_id)
            cards_by_strategy[card.strategy_id].append(card)

        previous_history = _latest_readiness_by_strategy(db, strategy_order)
        global_forward_cards = [card for card in cards if card.evidence_class in FORWARD_EVIDENCE_CLASSES]
        global_forward_evidence = tuple(_forward_provenance(card, compatible=True) for card in global_forward_cards)
        global_forward_sample = _sum_closed_counts(global_forward_cards)
        strategies: list[dict] = []
        timeline_events_created = 0

        for strategy_id in strategy_order:
            strategy_cards = cards_by_strategy[strategy_id]
            replay_card = _newest_card(
                card for card in strategy_cards if card.evidence_class in REPLAY_EVIDENCE_CLASSES
            )
            forward_card = _newest_card(
                card for card in strategy_cards if card.evidence_class in FORWARD_EVIDENCE_CLASSES
            )
            prior = previous_history.get(strategy_id)
            replay_provenance = _replay_provenance(replay_card) if replay_card is not None else None
            compatible = _cards_are_compatible(replay_card, forward_card)
            forward_provenance = (
                _forward_provenance(forward_card, compatible=compatible)
                if forward_card is not None
                else None
            )
            decay = evaluate_decay(
                _decay_payload(replay_card, replay_provenance),
                _decay_payload(forward_card, forward_provenance),
                thresholds,
            )
            context = _readiness_context(
                replay_card=replay_card,
                forward_card=forward_card,
                replay_provenance=replay_provenance,
                forward_provenance=forward_provenance,
                global_forward_evidence=global_forward_evidence,
                global_forward_sample=global_forward_sample,
                decay=decay,
                previous_status=prior.copy_readiness_status if prior is not None else None,
            )
            decision = evaluate_copy_readiness(context, thresholds)
            eligibility = evaluate_capital_eligibility(context, decision, thresholds)
            history = StrategyReadinessHistory(
                strategy_id=strategy_id,
                previous_copy_readiness_status=prior.copy_readiness_status if prior is not None else None,
                copy_readiness_status=decision.status,
                maturity_score=decision.maturity_score,
                global_forward_trades=global_forward_sample,
                strategy_forward_trades=forward_card.closed_trades if forward_card is not None else None,
                observation_days=_observation_days(forward_card),
                passed_gates_json=list(decision.passed_gates),
                failed_gates_json=list(decision.failed_gates),
                blockers_json=list(decision.blockers),
                reasons_json=_decision_reasons(decision.status, decision.blockers, decay["status"]),
                decay_status=decay["status"],
                real_capital_eligibility=eligibility,
                threshold_version=self.settings.copy_readiness_threshold_version,
            )
            db.add(history)
            db.flush()

            evidence_ids = sorted(card.id for card in strategy_cards)
            transition_payload = {
                "strategy_id": strategy_id,
                "readiness_history_id": history.id,
                "evidence_snapshot_ids": evidence_ids,
                "threshold_version": self.settings.copy_readiness_threshold_version,
            }
            previous_status = prior.copy_readiness_status if prior is not None else None
            if previous_status != decision.status:
                timeline_events_created += self._append_transition(
                    db,
                    transition_kind="copy-readiness",
                    event_type="copy_readiness_change",
                    strategy_id=strategy_id,
                    previous_value=previous_status,
                    new_value=decision.status,
                    payload=transition_payload,
                )
            previous_eligibility = prior.real_capital_eligibility if prior is not None else None
            if previous_eligibility != eligibility:
                timeline_events_created += self._append_transition(
                    db,
                    transition_kind="capital-eligibility",
                    event_type="capital_eligibility_change",
                    strategy_id=strategy_id,
                    previous_value=previous_eligibility,
                    new_value=eligibility,
                    payload=transition_payload,
                )

            strategies.append(
                {
                    "strategy_id": strategy_id,
                    "copy_readiness_status": decision.status,
                    "previous_copy_readiness_status": previous_status,
                    "maturity_score": decision.maturity_score,
                    "global_forward_trades": global_forward_sample,
                    "strategy_forward_trades": forward_card.closed_trades if forward_card is not None else None,
                    "observation_days": context.observation_days,
                    "decay_status": decay["status"],
                    "performance_decay_pct": decay["performance_decay_pct"],
                    "real_capital_eligibility": eligibility,
                    "blockers": list(decision.blockers),
                    "next_milestone": decision.next_milestone,
                    "replay_evidence_snapshot_id": replay_card.id if replay_card is not None else None,
                    "forward_evidence_snapshot_id": forward_card.id if forward_card is not None else None,
                    "threshold_version": self.settings.copy_readiness_threshold_version,
                }
            )

        db.flush()
        return {
            "strategies_evaluated": len(strategies),
            "timeline_events_created": timeline_events_created,
            "max_strategies": bounded_max,
            "threshold_version": self.settings.copy_readiness_threshold_version,
            "strategies": strategies,
        }

    def _append_transition(
        self,
        db: Session,
        *,
        transition_kind: str,
        event_type: str,
        strategy_id: str,
        previous_value: str | None,
        new_value: str,
        payload: dict,
    ) -> int:
        transition = {
            "kind": transition_kind,
            "strategy_id": strategy_id,
            "previous": previous_value,
            "new": new_value,
            "evidence_snapshot_ids": payload["evidence_snapshot_ids"],
            "threshold_version": payload["threshold_version"],
        }
        digest = hashlib.sha256(json.dumps(transition, sort_keys=True).encode("utf-8")).hexdigest()
        event_key = f"{transition_kind}:{digest}"
        with db.no_autoflush:
            existed = db.scalar(
                select(EvidenceTimelineEvent.id)
                .where(EvidenceTimelineEvent.event_key == event_key)
                .limit(1)
            )
        self.timeline.append_once(
            db,
            event_key=event_key,
            event_type=event_type,
            strategy_id=strategy_id,
            trade_id=None,
            payload={**payload, "previous": previous_value, "new": new_value},
        )
        return 0 if existed is not None else 1


class CopyReadinessSummaryService:
    """Return a compact aggregate from the latest persisted readiness row per strategy."""

    def __init__(self, *, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def summary(self, db: Session) -> dict:
        rows = _all_latest_readiness(db)
        thresholds = _readiness_thresholds(self.settings)
        if not rows:
            return {
                "copy_readiness_status": "NOT_READY",
                "real_capital_eligibility": "NOT_ELIGIBLE",
                "maturity_score": None,
                "global_forward_trades": None,
                "strategy_forward_trades": None,
                "observation_days": None,
                "required_global_forward_trades": thresholds.global_forward_trades,
                "required_strategy_forward_trades": thresholds.strategy_forward_trades,
                "required_observation_days": thresholds.observation_days,
                "required_capital_global_forward_trades": thresholds.capital_global_forward_trades,
                "required_capital_strategy_forward_trades": thresholds.capital_strategy_forward_trades,
                "required_capital_observation_days": thresholds.capital_observation_days,
                "selected_strategy_id": None,
                "passed_gates": [],
                "failed_gates": [],
                "exact_fingerprint_match": None,
                "net_expectancy": None,
                "benchmark_excess": None,
                "max_drawdown": None,
                "replay_forward_decay_pct": None,
                "ticker_count": None,
                "regime_count": None,
                "ticker_concentration": None,
                "market_concentration": None,
                "costs_available": False,
                "slippage_available": False,
                "data_quality_available": False,
                "total_strategies": 0,
                "ready_strategies": 0,
                "not_ready_strategies": 0,
                "decay_summary": {},
                "blockers": [],
                "next_milestone": "Collect compatible replay and terminal forward evidence.",
                "threshold_version": self.settings.copy_readiness_threshold_version,
                "evaluated_at": None,
            }

        statuses = [row.copy_readiness_status for row in rows]
        eligibilities = [row.real_capital_eligibility for row in rows]
        ready_count = sum(status in READY_STATUSES for status in statuses)
        blockers = sorted({blocker for row in rows for blocker in (row.blockers_json or [])})
        decay_summary = dict(sorted(Counter(row.decay_status or "INSUFFICIENT_EVIDENCE" for row in rows).items()))
        evaluated_at = max((row.evaluated_at for row in rows if row.evaluated_at is not None), default=None)
        selected = max(
            rows,
            key=lambda row: (
                row.real_capital_eligibility == "ELIGIBLE_FOR_LIMITED_EXTERNAL_VALIDATION",
                row.copy_readiness_status == "COPY_READY_HIGH_CONFIDENCE",
                row.maturity_score or 0.0,
                row.evaluated_at or datetime.min,
                row.id,
            ),
        )
        selected_cards = [
            card
            for card in _latest_evidence_cards(db, max_strategies=min(MAX_READINESS_STRATEGIES, max(1, len(rows))))
            if card.strategy_id == selected.strategy_id
        ]
        replay_card = _newest_card(card for card in selected_cards if card.evidence_class in REPLAY_EVIDENCE_CLASSES)
        forward_card = _newest_card(card for card in selected_cards if card.evidence_class in FORWARD_EVIDENCE_CLASSES)
        compatible = _cards_are_compatible(replay_card, forward_card)
        replay_provenance = _replay_provenance(replay_card) if replay_card is not None else None
        forward_provenance = (
            _forward_provenance(forward_card, compatible=compatible) if forward_card is not None else None
        )
        decay = evaluate_decay(
            _decay_payload(replay_card, replay_provenance),
            _decay_payload(forward_card, forward_provenance),
            thresholds,
        )
        concentration_values = forward_card.concentration_json if forward_card is not None else {}
        ticker_concentration = (concentration_values or {}).get("tickers") or {}
        market_concentration = (concentration_values or {}).get("markets") or {}
        return {
            "copy_readiness_status": _aggregate_readiness_status(statuses),
            "real_capital_eligibility": _aggregate_eligibility(eligibilities),
            "maturity_score": max(
                (row.maturity_score for row in rows if row.maturity_score is not None),
                default=None,
            ),
            "global_forward_trades": max(
                (row.global_forward_trades for row in rows if row.global_forward_trades is not None),
                default=None,
            ),
            "strategy_forward_trades": max(
                (row.strategy_forward_trades for row in rows if row.strategy_forward_trades is not None),
                default=None,
            ),
            "observation_days": max(
                (row.observation_days for row in rows if row.observation_days is not None),
                default=None,
            ),
            "required_global_forward_trades": thresholds.global_forward_trades,
            "required_strategy_forward_trades": thresholds.strategy_forward_trades,
            "required_observation_days": thresholds.observation_days,
            "required_capital_global_forward_trades": thresholds.capital_global_forward_trades,
            "required_capital_strategy_forward_trades": thresholds.capital_strategy_forward_trades,
            "required_capital_observation_days": thresholds.capital_observation_days,
            "selected_strategy_id": selected.strategy_id,
            "passed_gates": list(selected.passed_gates_json or []),
            "failed_gates": list(selected.failed_gates_json or []),
            "exact_fingerprint_match": "strategy_forward_provenance" in (selected.passed_gates_json or []),
            "net_expectancy": forward_card.net_expectancy if forward_card is not None else None,
            "benchmark_excess": forward_card.benchmark_excess if forward_card is not None else None,
            "max_drawdown": forward_card.max_drawdown if forward_card is not None else None,
            "replay_forward_decay_pct": decay.get("performance_decay_pct"),
            "ticker_count": _optional_non_negative_int(ticker_concentration.get("distinct_count")),
            "regime_count": len(forward_card.regimes_json or []) if forward_card is not None else None,
            "ticker_concentration": _number(ticker_concentration.get("top_share")),
            "market_concentration": _number(market_concentration.get("top_share")),
            "costs_available": forward_card is not None and forward_card.total_costs is not None,
            "slippage_available": forward_card is not None and forward_card.average_slippage is not None,
            "data_quality_available": _data_quality_available(forward_card),
            "total_strategies": len(rows),
            "ready_strategies": ready_count,
            "not_ready_strategies": len(rows) - ready_count,
            "decay_summary": decay_summary,
            "blockers": blockers,
            "next_milestone": None if ready_count else (f"Satisfy {blockers[0]}." if blockers else "Collect more forward evidence."),
            "threshold_version": self.settings.copy_readiness_threshold_version,
            "evaluated_at": evaluated_at.isoformat() if evaluated_at is not None else None,
        }


class CopyReadinessQueryService:
    """Bounded read model for strategy readiness and evidence timeline APIs."""

    def strategies(self, db: Session, *, limit: int = 25, offset: int = 0) -> dict:
        bounded_limit = _bounded_limit(limit, maximum=MAX_QUERY_LIMIT)
        bounded_offset = max(0, int(offset or 0))
        later = aliased(StrategyReadinessHistory)
        rows = db.scalars(
            select(StrategyReadinessHistory)
            .where(
                ~select(later.id)
                .where(
                    later.strategy_id == StrategyReadinessHistory.strategy_id,
                    or_(
                        later.evaluated_at > StrategyReadinessHistory.evaluated_at,
                        and_(
                            later.evaluated_at == StrategyReadinessHistory.evaluated_at,
                            later.id > StrategyReadinessHistory.id,
                        ),
                    ),
                )
                .exists()
            )
            .order_by(StrategyReadinessHistory.evaluated_at.desc(), StrategyReadinessHistory.id.desc())
            .offset(bounded_offset)
            .limit(bounded_limit + 1)
        ).all()
        has_more = len(rows) > bounded_limit
        return {
            "rows": [_serialize_readiness(row) for row in rows[:bounded_limit]],
            "limit": bounded_limit,
            "offset": bounded_offset,
            "has_more": has_more,
            "next_offset": bounded_offset + bounded_limit if has_more else None,
        }

    def strategy(self, db: Session, strategy_id: str) -> dict | None:
        history = db.scalar(
            select(StrategyReadinessHistory)
            .where(StrategyReadinessHistory.strategy_id == strategy_id)
            .order_by(StrategyReadinessHistory.evaluated_at.desc(), StrategyReadinessHistory.id.desc())
            .limit(1)
        )
        if history is None:
            return None
        cards = StrategyEvidenceQuery().latest_cards(db, limit=8, offset=0, strategy_id=strategy_id)
        return {"readiness": _serialize_readiness(history), "evidence": cards}

    def timeline(self, db: Session, strategy_id: str, *, limit: int = 50, offset: int = 0) -> dict:
        bounded_limit = _bounded_limit(limit, maximum=MAX_QUERY_LIMIT)
        bounded_offset = max(0, int(offset or 0))
        rows = db.scalars(
            select(EvidenceTimelineEvent)
            .where(EvidenceTimelineEvent.strategy_id == strategy_id)
            .order_by(EvidenceTimelineEvent.event_timestamp.desc(), EvidenceTimelineEvent.id.desc())
            .offset(bounded_offset)
            .limit(bounded_limit + 1)
        ).all()
        has_more = len(rows) > bounded_limit
        return {
            "strategy_id": strategy_id,
            "rows": [_serialize_timeline_event(row) for row in rows[:bounded_limit]],
            "limit": bounded_limit,
            "offset": bounded_offset,
            "has_more": has_more,
            "next_offset": bounded_offset + bounded_limit if has_more else None,
        }


def copy_readiness_projections(
    db: Session,
    trades: list[LiveForwardPaperTrade],
) -> dict[int, dict]:
    """Batch-load evidence projections for serialized paper trades.

    The function performs bounded projection reads only. It never recalculates
    readiness and deliberately leaves unavailable financial evidence as null.
    """

    identified = {
        trade.id: strategy_identity(trade.setup_type, trade.promoted_validation_id)[0]
        for trade in trades
        if trade.id is not None
    }
    strategy_ids = sorted(set(identified.values()))
    if not strategy_ids:
        return {}

    histories = _latest_readiness_by_strategy(db, strategy_ids)
    later = aliased(StrategyEvidenceSnapshot)
    cards = db.scalars(
        select(StrategyEvidenceSnapshot)
        .where(
            StrategyEvidenceSnapshot.strategy_id.in_(strategy_ids),
            ~select(later.id)
            .where(
                later.strategy_id == StrategyEvidenceSnapshot.strategy_id,
                later.evidence_class == StrategyEvidenceSnapshot.evidence_class,
                or_(
                    later.evaluated_at > StrategyEvidenceSnapshot.evaluated_at,
                    and_(
                        later.evaluated_at == StrategyEvidenceSnapshot.evaluated_at,
                        later.id > StrategyEvidenceSnapshot.id,
                    ),
                ),
            )
            .exists(),
        )
        .order_by(StrategyEvidenceSnapshot.evaluated_at.desc(), StrategyEvidenceSnapshot.id.desc())
        .limit(min(MAX_QUERY_LIMIT * 4, len(strategy_ids) * 4))
    ).all()
    cards_by_strategy: dict[str, list[StrategyEvidenceSnapshot]] = defaultdict(list)
    for card in cards:
        cards_by_strategy[card.strategy_id].append(card)

    return {
        trade.id: _trade_readiness_projection(
            trade,
            identified[trade.id],
            histories.get(identified[trade.id]),
            cards_by_strategy.get(identified[trade.id], []),
        )
        for trade in trades
        if trade.id in identified
    }


def append_trade_evidence_event(
    db: Session,
    trade: LiveForwardPaperTrade,
    source_event: LiveForwardPaperTradeEvent,
) -> EvidenceTimelineEvent | None:
    """Mirror a persisted paper lifecycle event into the canonical timeline."""

    canonical_type = LIFECYCLE_EVENT_TYPES.get(str(source_event.event_type or "").upper())
    if canonical_type is None:
        return None
    strategy_id = strategy_identity(trade.setup_type, trade.promoted_validation_id)[0]
    return EvidenceTimelineService().append_once(
        db,
        event_key=f"paper-forward-event:{source_event.id}:{canonical_type}",
        event_type=canonical_type,
        strategy_id=strategy_id,
        trade_id=trade.id,
        payload={
            "source_event_id": source_event.id,
            "source_event_type": source_event.event_type,
            "ticker": trade.ticker,
            "status": trade.status,
            "price_used": source_event.price_used,
            "reason": source_event.reason,
            "evidence_class": canonical_evidence_class(trade.evidence_type, trade.trading_mode),
            "event_payload": dict(source_event.payload or {}),
        },
    )


def _trade_readiness_projection(
    trade: LiveForwardPaperTrade,
    strategy_id: str,
    history: StrategyReadinessHistory | None,
    cards: list[StrategyEvidenceSnapshot],
) -> dict:
    forward_card = _newest_card(card for card in cards if card.evidence_class in FORWARD_EVIDENCE_CLASSES)
    replay_card = _newest_card(card for card in cards if card.evidence_class in REPLAY_EVIDENCE_CLASSES)
    strategy_status = history.copy_readiness_status if history is not None else "INSUFFICIENT_EVIDENCE"
    copy_status = strategy_status if strategy_status in READY_STATUSES else "NOT_COPY_READY"
    blockers = list(history.blockers_json or []) if history is not None else ["readiness_not_evaluated"]
    reasons = list(history.reasons_json or []) if history is not None else []
    warnings = sorted(
        {
            *(forward_card.warnings_json or [] if forward_card is not None else []),
            *(replay_card.warnings_json or [] if replay_card is not None else []),
            *blockers,
        }
    )
    regime_payload = (trade.frozen_decision_payload or {}).get("market_regime")
    if regime_payload is None:
        regime_payload = (trade.frozen_decision_payload or {}).get("regime")
    concentration_payload = forward_card.concentration_json or {} if forward_card is not None else {}
    ticker_concentration = (concentration_payload.get("tickers") or {}).get("top_share")
    invalidation = trade.invalidation_level or trade.stop_loss
    eligibility = history.real_capital_eligibility if history is not None else "NOT_ELIGIBLE"
    reason_to_copy = (
        "Evidence gates passed. This remains an autonomous research classification, not a real-money instruction."
        if copy_status in READY_STATUSES
        else None
    )
    reason_not_to_copy = None if copy_status in READY_STATUSES else (
        reasons[0] if reasons else f"Strategy evidence status is {strategy_status}."
    )
    maximum_paper_risk = 1.0 if strategy_status == "COPY_READY_HIGH_CONFIDENCE" else 0.5 if strategy_status == "COPY_READY_PAPER_ONLY" else 0.0
    return {
        "strategy_id": strategy_id,
        "copy_readiness_status": copy_status,
        "strategy_readiness_status": strategy_status,
        "quant_edge_score": history.maturity_score if history is not None else None,
        "sample_size": (replay_card.closed_trades if replay_card is not None else None),
        "forward_sample_size": (history.strategy_forward_trades if history is not None else None),
        "expected_net_edge": (forward_card.net_expectancy if forward_card is not None else None),
        "estimated_costs": (forward_card.total_costs if forward_card is not None else None),
        "evidence_confidence": (forward_card.confidence_interval_json if forward_card is not None else None),
        "benchmark_context": {
            "benchmark_ticker": trade.benchmark_ticker,
            "benchmark_return": forward_card.benchmark_return if forward_card is not None else None,
            "benchmark_excess": forward_card.benchmark_excess if forward_card is not None else None,
        },
        "current_regime": regime_payload,
        "concentration_risk": ticker_concentration,
        "reason_to_copy": reason_to_copy,
        "reason_not_to_copy": reason_not_to_copy,
        "invalidation_condition": invalidation,
        "maximum_suggested_paper_risk": maximum_paper_risk,
        "evidence_warning": "; ".join(warnings) if warnings else None,
        "real_capital_eligibility": eligibility,
        "paper_trading_actionability": trade.actionability_state,
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
        "confidence_interval": row.confidence_interval_json,
        "evaluated_at": row.evaluated_at.isoformat() if row.evaluated_at else None,
    }


def _serialize_readiness(row: StrategyReadinessHistory) -> dict:
    return {
        "id": row.id,
        "strategy_id": row.strategy_id,
        "previous_copy_readiness_status": row.previous_copy_readiness_status,
        "copy_readiness_status": row.copy_readiness_status,
        "maturity_score": row.maturity_score,
        "global_forward_trades": row.global_forward_trades,
        "strategy_forward_trades": row.strategy_forward_trades,
        "observation_days": row.observation_days,
        "passed_gates": row.passed_gates_json or [],
        "failed_gates": row.failed_gates_json or [],
        "blockers": row.blockers_json or [],
        "reasons": row.reasons_json or [],
        "decay_status": row.decay_status,
        "real_capital_eligibility": row.real_capital_eligibility,
        "threshold_version": row.threshold_version,
        "evaluated_at": row.evaluated_at.isoformat() if row.evaluated_at else None,
    }


def _serialize_timeline_event(row: EvidenceTimelineEvent) -> dict:
    return {
        "id": row.id,
        "event_key": row.event_key,
        "event_type": row.event_type,
        "strategy_id": row.strategy_id,
        "trade_id": row.trade_id,
        "payload": row.payload_json or {},
        "event_timestamp": row.event_timestamp.isoformat() if row.event_timestamp else None,
    }


def _readiness_thresholds(settings: Settings) -> ReadinessThresholds:
    return ReadinessThresholds(
        global_forward_trades=settings.copy_readiness_global_forward_trades,
        strategy_forward_trades=settings.copy_readiness_strategy_forward_trades,
        observation_days=settings.copy_readiness_observation_days,
        max_drawdown=settings.copy_readiness_max_drawdown,
        max_decay_pct=settings.copy_readiness_max_decay_pct,
        min_tickers=settings.copy_readiness_min_tickers,
        min_regimes=settings.copy_readiness_min_regimes,
        max_ticker_concentration=settings.copy_readiness_max_ticker_concentration,
        max_market_concentration=settings.copy_readiness_max_market_concentration,
        high_confidence_global_forward_trades=settings.copy_readiness_high_confidence_global_forward_trades,
        high_confidence_strategy_forward_trades=settings.copy_readiness_high_confidence_strategy_forward_trades,
        high_confidence_observation_days=settings.copy_readiness_high_confidence_observation_days,
        high_confidence_max_drawdown=settings.copy_readiness_high_confidence_max_drawdown,
        high_confidence_max_decay_pct=settings.copy_readiness_high_confidence_max_decay_pct,
        high_confidence_min_tickers=settings.copy_readiness_high_confidence_min_tickers,
        high_confidence_min_regimes=settings.copy_readiness_high_confidence_min_regimes,
        high_confidence_max_ticker_concentration=settings.copy_readiness_high_confidence_max_ticker_concentration,
        high_confidence_max_market_concentration=settings.copy_readiness_high_confidence_max_market_concentration,
        capital_global_forward_trades=settings.limited_external_validation_global_forward_trades,
        capital_strategy_forward_trades=settings.limited_external_validation_strategy_forward_trades,
        capital_observation_days=settings.limited_external_validation_observation_days,
        capital_max_drawdown=settings.limited_external_validation_max_drawdown,
        capital_max_decay_pct=settings.limited_external_validation_max_decay_pct,
        capital_min_tickers=settings.limited_external_validation_min_tickers,
        capital_min_regimes=settings.limited_external_validation_min_regimes,
        capital_max_ticker_concentration=settings.limited_external_validation_max_ticker_concentration,
        capital_max_market_concentration=settings.limited_external_validation_max_market_concentration,
    )


def _latest_evidence_cards(db: Session, *, max_strategies: int) -> list[StrategyEvidenceSnapshot]:
    if max_strategies <= 0:
        return []
    later = aliased(StrategyEvidenceSnapshot)
    later_snapshot_exists = select(later.id).where(
        later.strategy_id == StrategyEvidenceSnapshot.strategy_id,
        later.evidence_class == StrategyEvidenceSnapshot.evidence_class,
        or_(
            later.evaluated_at > StrategyEvidenceSnapshot.evaluated_at,
            and_(
                later.evaluated_at == StrategyEvidenceSnapshot.evaluated_at,
                later.id > StrategyEvidenceSnapshot.id,
            ),
        ),
    ).exists()
    candidates = db.scalars(
        select(StrategyEvidenceSnapshot)
        .where(~later_snapshot_exists)
        .order_by(StrategyEvidenceSnapshot.evaluated_at.desc(), StrategyEvidenceSnapshot.id.desc())
        .limit(max_strategies * 4)
    ).all()
    selected_ids: list[str] = []
    for card in candidates:
        if card.strategy_id not in selected_ids:
            selected_ids.append(card.strategy_id)
            if len(selected_ids) == max_strategies:
                break
    selected = set(selected_ids)
    return [card for card in candidates if card.strategy_id in selected]


def _latest_readiness_by_strategy(
    db: Session,
    strategy_ids: list[str],
) -> dict[str, StrategyReadinessHistory]:
    if not strategy_ids:
        return {}
    later = aliased(StrategyReadinessHistory)
    later_history_exists = select(later.id).where(
        later.strategy_id == StrategyReadinessHistory.strategy_id,
        or_(
            later.evaluated_at > StrategyReadinessHistory.evaluated_at,
            and_(
                later.evaluated_at == StrategyReadinessHistory.evaluated_at,
                later.id > StrategyReadinessHistory.id,
            ),
        ),
    ).exists()
    rows = db.scalars(
        select(StrategyReadinessHistory).where(
            StrategyReadinessHistory.strategy_id.in_(strategy_ids),
            ~later_history_exists,
        )
    ).all()
    return {row.strategy_id: row for row in rows}


def _all_latest_readiness(db: Session) -> list[StrategyReadinessHistory]:
    later = aliased(StrategyReadinessHistory)
    later_history_exists = select(later.id).where(
        later.strategy_id == StrategyReadinessHistory.strategy_id,
        or_(
            later.evaluated_at > StrategyReadinessHistory.evaluated_at,
            and_(
                later.evaluated_at == StrategyReadinessHistory.evaluated_at,
                later.id > StrategyReadinessHistory.id,
            ),
        ),
    ).exists()
    return db.scalars(
        select(StrategyReadinessHistory)
        .where(~later_history_exists)
        .order_by(StrategyReadinessHistory.evaluated_at.desc(), StrategyReadinessHistory.id.desc())
    ).all()


def _newest_card(cards) -> StrategyEvidenceSnapshot | None:
    return max(cards, key=lambda card: (card.evaluated_at or datetime.min, card.id), default=None)


def _replay_provenance(card: StrategyEvidenceSnapshot) -> EvidenceProvenance:
    return EvidenceProvenance(
        canonical_evidence_class=card.evidence_class,
        source_projection_id=f"strategy_evidence_snapshot:{card.id}",
        strategy_identity=card.strategy_id,
        horizon=_card_horizon(card),
        terminal=_closed_count(card) is not None,
        closed_count=_closed_count(card),
    )


def _forward_provenance(
    card: StrategyEvidenceSnapshot,
    *,
    compatible: bool,
) -> ForwardEvidenceProvenance:
    return ForwardEvidenceProvenance(
        canonical_evidence_class=card.evidence_class,
        source_projection_id=f"strategy_evidence_snapshot:{card.id}",
        strategy_identity=card.strategy_id,
        horizon=_card_horizon(card),
        terminal=_closed_count(card) is not None,
        closed_count=_closed_count(card),
        compatible_with_replay=compatible,
    )


def _cards_are_compatible(
    replay_card: StrategyEvidenceSnapshot | None,
    forward_card: StrategyEvidenceSnapshot | None,
) -> bool:
    if replay_card is None or forward_card is None:
        return False
    replay_horizon = _card_horizon(replay_card)
    forward_horizon = _card_horizon(forward_card)
    return (
        replay_card.strategy_id == forward_card.strategy_id
        and replay_horizon is not None
        and replay_horizon == forward_horizon
    )


def _card_horizon(card: StrategyEvidenceSnapshot) -> str | None:
    horizons = sorted({str(value).strip() for value in (card.timeframes_json or []) if str(value or "").strip()})
    return horizons[0] if len(horizons) == 1 else None


def _closed_count(card: StrategyEvidenceSnapshot) -> int | None:
    value = card.closed_trades
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _sum_closed_counts(cards: list[StrategyEvidenceSnapshot]) -> int | None:
    counts = [_closed_count(card) for card in cards]
    return sum(counts) if counts and all(value is not None for value in counts) else None


def _decay_payload(
    card: StrategyEvidenceSnapshot | None,
    provenance: EvidenceProvenance | ForwardEvidenceProvenance | None,
) -> dict | None:
    if card is None:
        return None
    return {
        "provenance": provenance,
        "net_expectancy": card.net_expectancy,
        "profit_factor": card.profit_factor,
        "sharpe_proxy": card.sharpe_proxy,
        "max_drawdown": card.max_drawdown,
        "total_costs": card.total_costs,
        "signal_failure_rate": (card.metrics_json or {}).get("signal_failure_rate"),
    }


def _readiness_context(
    *,
    replay_card: StrategyEvidenceSnapshot | None,
    forward_card: StrategyEvidenceSnapshot | None,
    replay_provenance: EvidenceProvenance | None,
    forward_provenance: ForwardEvidenceProvenance | None,
    global_forward_evidence: tuple[ForwardEvidenceProvenance, ...],
    global_forward_sample: int | None,
    decay: dict,
    previous_status: str | None,
) -> ReadinessContext:
    concentration_values = forward_card.concentration_json if forward_card is not None else {}
    ticker_concentration = (concentration_values or {}).get("tickers") or {}
    market_concentration = (concentration_values or {}).get("markets") or {}
    return ReadinessContext(
        replay_sample=_closed_count(replay_card) if replay_card is not None else None,
        global_forward_sample=global_forward_sample,
        forward_sample=_closed_count(forward_card) if forward_card is not None else None,
        replay_evidence=replay_provenance,
        strategy_forward_evidence=forward_provenance,
        global_forward_evidence=global_forward_evidence,
        observation_days=_observation_days(forward_card),
        net_expectancy=forward_card.net_expectancy if forward_card is not None else None,
        benchmark_excess=forward_card.benchmark_excess if forward_card is not None else None,
        max_drawdown=forward_card.max_drawdown if forward_card is not None else None,
        decay_status=str(decay["status"]),
        decay_pct=decay["performance_decay_pct"],
        ticker_count=_optional_non_negative_int(ticker_concentration.get("distinct_count")),
        regime_count=len(forward_card.regimes_json or []) if forward_card is not None else None,
        ticker_concentration=_number(ticker_concentration.get("top_share")),
        market_concentration=_number(market_concentration.get("top_share")),
        costs_available=forward_card is not None and forward_card.total_costs is not None,
        slippage_available=forward_card is not None and forward_card.average_slippage is not None,
        data_quality_available=_data_quality_available(forward_card),
        previous_status=previous_status,
    )


def _observation_days(card: StrategyEvidenceSnapshot | None) -> int | None:
    if card is None:
        return None
    dates = []
    for source in card.source_rows_json or []:
        if not isinstance(source, dict):
            continue
        timestamp = source.get("timestamp")
        if not timestamp:
            continue
        try:
            dates.append(datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).date())
        except ValueError:
            continue
    if not dates:
        return None
    return (max(dates) - min(dates)).days


def _data_quality_available(card: StrategyEvidenceSnapshot | None) -> bool:
    if card is None:
        return False
    blockers = {
        "data_quality_unavailable",
        "strategy_identity_conflict",
    }
    return not blockers.intersection(str(value) for value in (card.warnings_json or []))


def _decision_reasons(status: str, blockers: tuple[str, ...], decay_status: str) -> list[str]:
    reasons = [f"decay_status:{decay_status}"]
    if blockers:
        reasons.extend(f"blocked_by:{blocker}" for blocker in blockers)
    else:
        reasons.append(f"readiness_status:{status}")
    return reasons


def _aggregate_readiness_status(statuses: list[str]) -> str:
    for status in ("SUSPENDED", "DEGRADED"):
        if status in statuses:
            return status
    for status in (
        "COPY_READY_HIGH_CONFIDENCE",
        "COPY_READY_PAPER_ONLY",
        "FORWARD_EVIDENCE_GROWING",
        "FORWARD_EVIDENCE_LOW",
        "REPLAY_ONLY",
        "NOT_READY",
    ):
        if status in statuses:
            return status
    return "NOT_READY"


def _aggregate_eligibility(values: list[str | None]) -> str:
    for value in (
        "ELIGIBLE_FOR_LIMITED_EXTERNAL_VALIDATION",
        "PAPER_ONLY",
        "OBSERVE_ONLY",
        "NOT_ELIGIBLE",
    ):
        if value in values:
            return value
    return "NOT_ELIGIBLE"


def _optional_non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _bounded_strategy_limit(value: int) -> int:
    return min(MAX_READINESS_STRATEGIES, max(0, _integer(value)))


def _bounded_limit(value: int, *, maximum: int) -> int:
    return min(maximum, max(1, _integer(value)))


def _identified_as_intraday():
    return or_(
        LiveForwardPaperTrade.evidence_type.in_(("PAPER_FORWARD_INTRADAY", INTRADAY_FORWARD_EVIDENCE)),
        and_(
            LiveForwardPaperTrade.trading_mode.ilike("%INTRADAY%"),
            or_(
                LiveForwardPaperTrade.evidence_type.is_(None),
                LiveForwardPaperTrade.evidence_type.not_in((
                    "PAPER_FORWARD_INTRADAY_EXPERIMENTAL",
                    "PAPER_FORWARD_INVALID_ENTRY_GEOMETRY",
                )),
            ),
        ),
    )


def _not_identified_as_intraday():
    return and_(
        or_(
            LiveForwardPaperTrade.evidence_type.is_(None),
            LiveForwardPaperTrade.evidence_type.not_in((
                "PAPER_FORWARD_INTRADAY_EXPERIMENTAL",
                "PAPER_FORWARD_INVALID_ENTRY_GEOMETRY",
            )),
        ),
        or_(
            LiveForwardPaperTrade.evidence_type.is_(None),
            LiveForwardPaperTrade.evidence_type.not_in(("PAPER_FORWARD_INTRADAY", INTRADAY_FORWARD_EVIDENCE)),
        ),
        or_(
            LiveForwardPaperTrade.trading_mode.is_(None),
            ~LiveForwardPaperTrade.trading_mode.ilike("%INTRADAY%"),
        ),
    )


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
