from __future__ import annotations

from datetime import datetime, timedelta
import hashlib

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import (
    Asset,
    IntradayNoTradeDecision,
    IntradayPaperRun,
    LearningEvent,
    ReplayMarketBar,
    StrategyMemory,
    TradeLearningEvidence,
)
from app.services.intraday_contracts import IntradayDecision


class IntradayNoTradeLearningService:
    """Freeze no-trade decisions and evaluate them only after future bars exist."""

    def __init__(self, *, evaluation_minutes: int = 30):
        self.evaluation_minutes = max(1, int(evaluation_minutes))

    def record(
        self,
        db: Session,
        *,
        run: IntradayPaperRun,
        asset: Asset,
        decision: IntradayDecision,
    ) -> IntradayNoTradeDecision | None:
        price = float(decision.entry_price or 0.0)
        if price <= 0:
            return None
        uid = self._uid(asset.ticker, decision)
        existing = db.scalar(select(IntradayNoTradeDecision).where(IntradayNoTradeDecision.decision_uid == uid).limit(1))
        if existing is not None:
            return existing
        costs = dict(decision.costs or {})
        row = IntradayNoTradeDecision(
            decision_uid=uid,
            run_id=run.id,
            asset_id=asset.id,
            ticker=asset.ticker.upper(),
            setup_type=decision.setup_type,
            market=decision.market,
            desk=decision.desk,
            benchmark_ticker=decision.benchmark_ticker,
            reason_code=decision.reason_code,
            status="PENDING",
            decision_timestamp=decision.decision_timestamp,
            evaluation_due_at=decision.decision_timestamp + timedelta(minutes=self.evaluation_minutes),
            theoretical_price=price,
            expected_move_bps=float(decision.expected_move_bps or 0.0),
            expected_cost_bps=float(costs.get("total_round_trip_bps") or 0.0),
            decision_payload={
                "status": decision.status,
                "reason_code": decision.reason_code,
                "explanation": decision.explanation,
                "strategy_id": decision.strategy_id,
                "validation_id": decision.validation_id,
                "regime": decision.regime,
                "session": decision.session,
                "costs": costs,
                "no_future_data_policy": "Outcome is evaluated only from bars after decision_timestamp.",
            },
        )
        db.add(row)
        db.flush()
        return row

    def evaluate_due(self, db: Session, *, now: datetime, limit: int = 100) -> dict:
        rows = db.scalars(
            select(IntradayNoTradeDecision)
            .where(
                IntradayNoTradeDecision.status == "PENDING",
                IntradayNoTradeDecision.evaluation_due_at <= now,
            )
            .order_by(IntradayNoTradeDecision.evaluation_due_at, IntradayNoTradeDecision.id)
            .limit(max(1, min(500, int(limit))))
        ).all()
        evaluated = 0
        outcomes: dict[str, int] = {}
        for row in rows:
            bar = db.scalar(
                select(ReplayMarketBar)
                .where(
                    ReplayMarketBar.asset_id == row.asset_id,
                    ReplayMarketBar.timeframe == "1m",
                    ReplayMarketBar.bar_timestamp >= row.evaluation_due_at,
                    ReplayMarketBar.bar_timestamp <= now,
                )
                .order_by(desc(ReplayMarketBar.bar_timestamp))
                .limit(1)
            )
            if bar is None:
                continue
            future_return = (float(bar.close) / max(float(row.theoretical_price), 1e-9) - 1.0) * 100.0
            benchmark_return = self._benchmark_return(db, row, now)
            outcome = self._classify(row, future_return)
            row.status = "EVALUATED"
            row.evaluated_at = now
            row.future_return = round(future_return, 6)
            row.benchmark_return = benchmark_return
            row.outcome_label = outcome
            row.capital_preserved = round(max(0.0, -future_return), 6)
            row.opportunity_cost = round(max(0.0, future_return), 6)
            row.evaluation_payload = {
                "future_bar_timestamp": bar.bar_timestamp.isoformat(),
                "future_close": float(bar.close),
                "future_return_pct": row.future_return,
                "benchmark_return_pct": benchmark_return,
                "outcome": outcome,
            }
            self._persist_learning(db, row)
            evaluated += 1
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
        db.flush()
        return {"status": "COMPLETED", "pending_checked": len(rows), "evaluated": evaluated, "outcomes": outcomes}

    @staticmethod
    def _classify(row: IntradayNoTradeDecision, future_return: float) -> str:
        opportunity_threshold = max(0.25, float(row.expected_move_bps or 0.0) / 100.0)
        if future_return >= opportunity_threshold:
            return "MISSED_OPPORTUNITY"
        if future_return <= -0.10:
            return "CORRECT_NO_TRADE"
        if row.reason_code in {"COSTS_KILL_EDGE", "SPREAD_TOO_WIDE", "EXPECTED_MOVE_TOO_SMALL"}:
            return "EDGE_DESTROYED_BY_COSTS"
        if row.reason_code == "WAITING_FOR_TRIGGER" and future_return <= 0:
            return "SIGNAL_DECAY_BEFORE_ENTRY"
        return "CORRECT_NO_TRADE"

    @staticmethod
    def _benchmark_return(db: Session, row: IntradayNoTradeDecision, now: datetime) -> float | None:
        if not row.benchmark_ticker:
            return None
        benchmark = db.scalar(select(Asset).where(func.upper(Asset.ticker) == row.benchmark_ticker.upper()).limit(1))
        if benchmark is None:
            return None
        start = db.scalar(
            select(ReplayMarketBar)
            .where(ReplayMarketBar.asset_id == benchmark.id, ReplayMarketBar.bar_timestamp <= row.decision_timestamp)
            .order_by(desc(ReplayMarketBar.bar_timestamp))
            .limit(1)
        )
        end = db.scalar(
            select(ReplayMarketBar)
            .where(ReplayMarketBar.asset_id == benchmark.id, ReplayMarketBar.bar_timestamp <= now)
            .order_by(desc(ReplayMarketBar.bar_timestamp))
            .limit(1)
        )
        if start is None or end is None or float(start.close or 0.0) <= 0:
            return None
        return round((float(end.close) / float(start.close) - 1.0) * 100.0, 6)

    @staticmethod
    def _persist_learning(db: Session, row: IntradayNoTradeDecision) -> None:
        identity = f"intraday_no_trade:{row.id}"
        if db.scalar(select(TradeLearningEvidence.id).where(TradeLearningEvidence.action_taken == identity).limit(1)) is not None:
            return
        missed = row.outcome_label == "MISSED_OPPORTUNITY"
        lesson_type = "no_trade_filter_missed_opportunity" if missed else "no_trade_filter_confirmed"
        observation = (
            f"{row.reason_code} missed {row.future_return:.2f}% after rejection."
            if missed
            else f"{row.reason_code} avoided or neutralized a {row.future_return:.2f}% subsequent move."
        )
        db.add(
            TradeLearningEvidence(
                ticker=row.ticker,
                setup_type=row.setup_type,
                regime=str((row.decision_payload or {}).get("regime") or "unknown"),
                lesson_type=lesson_type,
                observation=observation,
                sample_size=1,
                supporting_trades_json={
                    "no_trade_decision_id": row.id,
                    "outcome_label": row.outcome_label,
                    "future_return": row.future_return,
                    "benchmark_return": row.benchmark_return,
                    "reason_code": row.reason_code,
                },
                affected_module="intraday_no_trade_filter",
                action_taken=identity,
                confidence=30.0,
            )
        )
        memory_key = f"intraday_no_trade:{row.reason_code}:{row.market}:{(row.decision_payload or {}).get('regime') or 'unknown'}"
        memory = db.scalar(select(StrategyMemory).where(StrategyMemory.memory_key == memory_key).limit(1))
        if memory is None:
            memory = StrategyMemory(
                memory_key=memory_key,
                category="intraday_no_trade",
                conditions={"reason": row.reason_code, "market": row.market, "regime": (row.decision_payload or {}).get("regime")},
                evidence={},
            )
            db.add(memory)
        memory.sample_count = int(memory.sample_count or 0) + 1
        memory.positive_count = int(memory.positive_count or 0) + (0 if missed else 1)
        memory.negative_count = int(memory.negative_count or 0) + (1 if missed else 0)
        memory.reliability_score = round(memory.positive_count / max(1, memory.sample_count) * 100.0, 4)
        memory.lesson = observation
        memory.evidence = {"latest_no_trade_decision_id": row.id, "outcome_label": row.outcome_label}
        memory.last_seen_at = row.evaluated_at
        db.add(
            LearningEvent(
                event_type="intraday_no_trade_evaluated",
                severity="Info",
                title=f"{row.ticker} no-trade outcome",
                description=observation,
                payload={"no_trade_decision_id": row.id, "outcome_label": row.outcome_label},
            )
        )

    @staticmethod
    def _uid(ticker: str, decision: IntradayDecision) -> str:
        raw = f"{ticker.upper()}|{decision.validation_id}|{decision.decision_timestamp.isoformat()}|{decision.reason_code}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
