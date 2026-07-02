from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import LiveForwardPaperTrade, LiveForwardPaperTradeEvent
from app.services.trading_intelligence_lab import (
    LAB_POLICY,
    LiveForwardPaperTradingService as _TradingLabLiveForwardService,
    compact_candidate,
    freeze_decision_payload,
    live_candidate_is_actionable,
    live_forward_duplicate_key,
    safe_float,
    serialize_live_event,
    serialize_paper_forward_trade,
)


settings = get_settings()


class LiveForwardPaperTradingService(_TradingLabLiveForwardService):
    """Foundation API for timestamp-frozen live-forward paper decisions.

    The Trading Intelligence Lab still owns the complete open/update/close paper
    lifecycle. This service adds the conservative foundation surface requested
    by /api/paper-forward: create immutable decision candidates, append events,
    and run one non-closing candidate scan.
    """

    def create_candidate(self, db: Session, decision_payload: dict[str, Any]) -> LiveForwardPaperTrade:
        """Persist one idempotent frozen paper-forward candidate.

        This method intentionally does not open a position, write broker state,
        or evaluate outcomes. Future lifecycle changes are appended as events.
        """

        game = self.active_or_create_live_game(db)
        now = datetime.utcnow()
        ticker = normalize_text(decision_payload.get("ticker")).upper()
        plan = decision_payload.get("trade_plan") or {}
        setup_type = normalize_text((decision_payload.get("setup") or {}).get("setup_type")) or "unknown_setup"
        entry_trigger = normalize_text(plan.get("entry_trigger") or plan.get("confirmation_condition")) or "live_forward_candidate"
        feedback = self.feedback_metadata(db, ticker=ticker, setup_type=setup_type)
        duplicate_key = live_forward_duplicate_key(
            ticker=ticker,
            decision_date=now.date(),
            model_version=feedback["model_version_used"],
            setup_type=setup_type,
            entry_trigger=entry_trigger,
        )
        existing = db.scalar(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.duplicate_key == duplicate_key).limit(1))
        if existing:
            return existing

        price = safe_float((decision_payload.get("price_context") or {}).get("latest_price"))
        if not ticker or price <= 0:
            status = "DATA_BLOCKED"
            block_reason = "missing_ticker_or_live_entry_price"
        elif not live_candidate_is_actionable(decision_payload):
            status = "SKIPPED"
            block_reason = "candidate_not_actionable"
        else:
            status = "CANDIDATE"
            block_reason = ""

        risk_amount = safe_float(game.current_capital) * settings.live_trading_game_max_risk_per_trade / 100
        stop = safe_float(plan.get("invalidation_level") or plan.get("stop_price")) or (price * 0.97 if price else None)
        risk_per_share = abs(price - stop) if price and stop else price * 0.02 if price else 1.0
        size = risk_amount / max(0.01, risk_per_share)
        target_1 = safe_float(plan.get("target_1")) or (price * 1.04 if price else None)
        target_2 = safe_float(plan.get("target_2")) or (price * 1.08 if price else None)

        trade = LiveForwardPaperTrade(
            trade_uid=f"pf-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
            game_id=game.id,
            ticker=ticker or "UNKNOWN",
            asset_name=(decision_payload.get("asset") or {}).get("name") or ticker or "Unknown asset",
            asset_type=(decision_payload.get("asset") or {}).get("asset_type"),
            sector=(decision_payload.get("asset") or {}).get("sector"),
            industry=(decision_payload.get("asset") or {}).get("industry"),
            setup_type=setup_type,
            status=status,
            decision_timestamp=now,
            decision_date=now.date(),
            model_version_used=feedback["model_version_used"],
            weights_used=feedback["weights_used"],
            confidence_adjustment=safe_float(feedback.get("confidence_adjustment")),
            learning_memory_used=feedback["learning_memory_used"],
            strategy_memory_used=feedback["strategy_memory_used"],
            research_priority_used=feedback["research_priority_used"],
            frozen_decision_payload=freeze_decision_payload(decision_payload, feedback, now),
            actionability_state=decision_payload.get("actionability"),
            confidence=decision_payload.get("confidence"),
            sniper_score=decision_payload.get("sniper_score"),
            benchmark_ticker=game.benchmark_ticker,
            entry_trigger=entry_trigger,
            confirmation_condition=plan.get("confirmation_condition") or "Frozen candidate only; entry must be evaluated by future lifecycle logic.",
            entry_price=price if price > 0 else None,
            stop_loss=stop,
            invalidation_level=stop,
            target_1=target_1,
            target_2=target_2,
            current_price=price if price > 0 else None,
            position_size=round(size, 6) if price > 0 else 0.0,
            notional_value=round(size * price, 4) if price > 0 else 0.0,
            risk_amount=round(risk_amount, 4),
            risk_percent=settings.live_trading_game_max_risk_per_trade,
            expected_risk=round(risk_per_share * size, 4) if price > 0 else None,
            expected_reward=round((target_1 - price) * size, 4) if price > 0 and target_1 else None,
            expected_r_multiple=round(((target_1 - price) / max(0.01, risk_per_share)), 4) if price > 0 and target_1 else None,
            duplicate_key=duplicate_key,
        )
        db.add(trade)
        db.flush()
        self.append_event(
            db,
            trade.id,
            "DECISION_CREATED",
            "Decision frozen from current BLUM evidence.",
            payload={"candidate": compact_candidate(decision_payload), "feedback": feedback},
            price_used=price if price > 0 else None,
        )
        if status == "DATA_BLOCKED":
            self.append_event(db, trade.id, "DATA_BLOCKED", block_reason, payload={"price_context": decision_payload.get("price_context")})
        elif status == "SKIPPED":
            self.append_event(db, trade.id, "ERROR", block_reason, payload={"actionability": decision_payload.get("actionability")})
        return trade

    def append_event(
        self,
        db: Session,
        trade_id: int,
        event_type: str,
        reason: str,
        payload: dict[str, Any] | None = None,
        price_used: float | None = None,
    ) -> LiveForwardPaperTradeEvent:
        trade = db.get(LiveForwardPaperTrade, trade_id)
        if trade is None:
            raise ValueError(f"Paper-forward trade not found: {trade_id}")
        event = self.add_event(db, trade, event_type, price_used, reason, payload)
        db.flush()
        return event

    def run_once(self, db: Session) -> dict:
        """Run one foundation scan without opening/closing positions."""

        if not settings.live_trading_game_enabled:
            return {"status": "disabled", "created": [], "duplicates": [], "current_blockers": ["live_forward_paper_disabled"], "policy": LAB_POLICY}
        try:
            candidates = self.scan_candidates(db)
        except Exception as exc:
            db.rollback()
            return {"status": "error", "created": [], "duplicates": [], "current_blockers": [str(exc)], "policy": LAB_POLICY}

        created: list[dict] = []
        duplicates: list[dict] = []
        blocked: list[dict] = []
        for candidate in candidates:
            before_id = existing_candidate_id(db, self, candidate)
            trade = self.create_candidate(db, candidate)
            serialized = serialize_paper_forward_trade(trade, compact=True)
            if before_id == trade.id:
                duplicates.append(serialized)
            elif trade.status == "DATA_BLOCKED":
                blocked.append(serialized)
            else:
                created.append(serialized)

        db.commit()
        snapshot = self.publish_snapshot(db)
        return {
            "status": "ok",
            "mode": "foundation_candidate_freeze",
            "candidates_seen": len(candidates),
            "created": created,
            "duplicates": duplicates,
            "data_blocked": blocked,
            "snapshot_status": snapshot.get("status"),
            "current_blockers": [] if created or duplicates else ["no_candidate_decisions_available"],
            "policy": LAB_POLICY,
        }


def existing_candidate_id(db: Session, service: LiveForwardPaperTradingService, candidate: dict[str, Any]) -> int | None:
    now = datetime.utcnow()
    ticker = normalize_text(candidate.get("ticker")).upper()
    setup_type = normalize_text((candidate.get("setup") or {}).get("setup_type")) or "unknown_setup"
    plan = candidate.get("trade_plan") or {}
    entry_trigger = normalize_text(plan.get("entry_trigger") or plan.get("confirmation_condition")) or "live_forward_candidate"
    feedback = service.feedback_metadata(db, ticker=ticker, setup_type=setup_type)
    duplicate_key = live_forward_duplicate_key(
        ticker=ticker,
        decision_date=now.date(),
        model_version=feedback["model_version_used"],
        setup_type=setup_type,
        entry_trigger=entry_trigger,
    )
    return db.scalar(select(LiveForwardPaperTrade.id).where(LiveForwardPaperTrade.duplicate_key == duplicate_key).limit(1))


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def serialize_foundation_event(row: LiveForwardPaperTradeEvent) -> dict:
    return serialize_live_event(row)
