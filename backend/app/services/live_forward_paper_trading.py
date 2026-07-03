from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Asset,
    LearningEvent,
    LiveForwardPaperGame,
    LiveForwardPaperPosition,
    LiveForwardPaperTrade,
    LiveForwardPaperTradeEvent,
    PriceHistory,
    TradeLearningEvidence,
    TradingGameTrade,
)
from app.services.trading_intelligence_lab import (
    ActionabilityPolicy,
    LAB_POLICY,
    LiveForwardPaperTradingService as _TradingLabLiveForwardService,
    actionability_event_payload,
    diagnose_candidate_actionability,
    compact_candidate,
    ensure_live_trade_game,
    freeze_decision_payload,
    latest_market_price_after,
    live_position_for_paper_trade,
    live_forward_duplicate_key,
    paper_forward_actionability_summary,
    period_return,
    safe_float,
    serialize_live_event,
    serialize_paper_forward_trade,
    serialize_trade_lesson,
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

        diagnosis = diagnose_candidate_actionability(decision_payload, strict=True)
        decision_payload_with_diagnosis = {**decision_payload, "actionability_diagnosis": diagnosis.to_dict()}
        price = safe_float((decision_payload.get("price_context") or {}).get("latest_price"))
        if diagnosis.actionability_status == "DATA_BLOCKED":
            status = "DATA_BLOCKED"
            block_reason = diagnosis.rejection_reason
        elif diagnosis.actionability_status == "WAITING_FOR_TRIGGER":
            status = "WAITING_FOR_TRIGGER"
            block_reason = diagnosis.rejection_reason
        elif diagnosis.actionability_status != "ACTIONABLE":
            status = "SKIPPED"
            block_reason = diagnosis.rejection_reason
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
            frozen_decision_payload=freeze_decision_payload(decision_payload_with_diagnosis, feedback, now),
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
            payload={"candidate": compact_candidate(decision_payload), "feedback": feedback, "actionability_diagnosis": diagnosis.to_dict()},
            price_used=price if price > 0 else None,
        )
        if status == "DATA_BLOCKED":
            self.append_event(db, trade.id, "DATA_BLOCKED", block_reason, payload={"price_context": decision_payload.get("price_context"), "actionability_diagnosis": diagnosis.to_dict()})
        elif status in {"SKIPPED", "WAITING_FOR_TRIGGER"}:
            self.append_event(db, trade.id, "ACTIONABILITY_REJECTED", block_reason, payload=actionability_event_payload(decision_payload, diagnosis, feedback), price_used=price if price > 0 else None)
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

    def status_readonly(self, db: Session) -> dict:
        game = self.active_game(db)
        if not game:
            return {
                "status": "NO_SNAPSHOTS",
                "readiness": "NO_SNAPSHOTS",
                "enabled": settings.live_trading_game_enabled,
                "paper_forward_lifecycle_mode": "LIFECYCLE_DISABLED_BY_SETTINGS" if not settings.paper_forward_lifecycle_enabled else "LIFECYCLE_BLOCKED_BY_NO_ACTIONABLE_CANDIDATES",
                "actionability_summary": empty_actionability_summary(),
                "current_blockers": ["no_live_forward_paper_game"],
                "policy": LAB_POLICY,
            }
        return self.status_payload(db, game)

    def status_payload(self, db: Session, game: LiveForwardPaperGame) -> dict:
        payload = super().status_payload(db, game)
        summary = self.actionability_summary(db, game)
        mode = self.lifecycle_mode(summary)
        payload.update(
            {
                "paper_forward_lifecycle_mode": mode,
                "actionability_summary": summary,
                "current_blockers": sorted(set([*(payload.get("current_blockers", []) or []), *self.paper_forward_blockers_from_counts(summary)])),
                "lifecycle_message": lifecycle_message(mode),
            }
        )
        return payload

    def scan_candidates(self, db: Session, limit: int = 30) -> list[dict]:
        """Scan current stored market evidence without fabricating candidates.

        Primary candidates still come from Market Sniper. If that surface is too
        narrow, broaden scouting to active assets with stored OHLCV so the
        forward paper journal can freeze more real decisions and learn from the
        rejection/trigger evidence.
        """

        from app.services.market_sniper import MarketSniperEngine

        desired = max(1, min(int(limit or 30), 80))
        engine = MarketSniperEngine()
        candidates: list[dict] = []
        seen: set[str] = set()

        def add_candidate(item: dict, source: str) -> None:
            ticker = normalize_text(item.get("ticker")).upper()
            if not ticker or ticker in seen:
                return
            payload = dict(item)
            payload["scouting_source"] = source
            payload["scouting_policy"] = "real_stored_ohlcv_only_no_synthetic_candidates"
            seen.add(ticker)
            candidates.append(payload)

        try:
            payload = engine.candidates(db, limit=desired, persist=False)
            for item in payload.get("candidates", []) or []:
                add_candidate(item, "market_sniper_ranked_signals")
        except Exception as exc:
            db.add(
                LearningEvent(
                    event_type="paper_forward_scouting_degraded",
                    severity="Warning",
                    title="Paper-forward primary scouting failed",
                    description=f"{type(exc).__name__}: {exc}",
                    payload={"source": "market_sniper_ranked_signals"},
                )
            )

        if len(candidates) < desired:
            for asset in broad_ohlcv_universe(db, limit=desired * 3):
                if asset.ticker in seen:
                    continue
                try:
                    add_candidate(engine.evaluate_asset(db, asset, persist=False), "broad_ohlcv_universe")
                except Exception as exc:
                    db.add(
                        LearningEvent(
                            event_type="paper_forward_asset_scouting_skipped",
                            severity="Warning",
                            title=f"{asset.ticker} paper-forward scouting skipped",
                            description=f"{type(exc).__name__}: {exc}",
                            payload={"ticker": asset.ticker, "source": "broad_ohlcv_universe"},
                        )
                    )
                if len(candidates) >= desired:
                    break

        return candidates[:desired]

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
        skipped: list[dict] = []
        waiting: list[dict] = []
        for candidate in candidates:
            before_id = existing_candidate_id(db, self, candidate)
            trade = self.create_candidate(db, candidate)
            serialized = serialize_paper_forward_trade(trade, compact=True)
            if before_id == trade.id:
                duplicates.append(serialized)
            elif trade.status == "DATA_BLOCKED":
                blocked.append(serialized)
            elif trade.status == "SKIPPED":
                skipped.append(serialized)
            elif trade.status == "WAITING_FOR_TRIGGER":
                waiting.append(serialized)
            else:
                created.append(serialized)

        db.commit()
        snapshot = self.publish_snapshot(db)
        actionability_summary = snapshot.get("payload", {}).get("actionability_summary") if isinstance(snapshot, dict) else None
        return {
            "status": "ok",
            "mode": "foundation_candidate_freeze",
            "candidates_seen": len(candidates),
            "created": created,
            "duplicates": duplicates,
            "waiting_for_trigger": waiting,
            "skipped": skipped,
            "data_blocked": blocked,
            "actionability_summary": actionability_summary,
            "snapshot_status": snapshot.get("status"),
            "current_blockers": self.paper_forward_blockers_from_counts(actionability_summary) if actionability_summary else ([] if created or duplicates else ["no_candidate_decisions_available"]),
            "policy": LAB_POLICY,
        }

    def run_lifecycle(self, db: Session, *, override: bool = False) -> dict:
        """Advance frozen paper-forward candidates through the paper lifecycle.

        This is deliberately separate from run_once(): run_once only freezes
        candidates, while this method opens eligible paper positions, updates
        them with later market data, closes resolved trades and records lessons.
        """

        if not settings.live_trading_game_enabled:
            return {"status": "disabled", "policy": LAB_POLICY, "current_blockers": ["live_forward_paper_disabled"]}
        game = self.active_game(db)
        if not settings.paper_forward_lifecycle_enabled and not override:
            summary = self.actionability_summary(db, game) if game else empty_actionability_summary()
            return {
                "status": "disabled",
                "mode": "LIFECYCLE_DISABLED_BY_SETTINGS",
                "paper_forward_lifecycle_mode": "LIFECYCLE_DISABLED_BY_SETTINGS",
                "actionability_summary": summary,
                "current_blockers": sorted(set(["paper_forward_lifecycle_disabled_by_settings", *self.paper_forward_blockers_from_counts(summary)])),
                "policy": "Paper-forward lifecycle is currently disabled. BLUM is freezing decisions but not opening or closing trades.",
            }

        game = self.active_or_create_live_game(db)
        try:
            opened = self.open_eligible_trades(db)
            updated = self.update_open_trades(db)
            closed = self.close_resolved_trades(db)
            lessons = self.publish_lessons(db)
            self.refresh_live_game_counts(db, game)
            db.commit()
            snapshot = self.publish_snapshot(db)
            return {
                "status": "ok",
                "mode": "paper_forward_lifecycle",
                "paper_forward_lifecycle_mode": "LIFECYCLE_ENABLED",
                "phases": {
                    "open_eligible_trades": opened,
                    "update_open_trades": updated,
                    "close_resolved_trades": closed,
                    "publish_lessons": {"created": len(lessons), "lessons": lessons[:8]},
                },
                "actionability_summary": snapshot.get("payload", {}).get("actionability_summary") if isinstance(snapshot, dict) else None,
                "snapshot_status": snapshot.get("status"),
                "current_blockers": snapshot.get("payload", {}).get("current_blockers", []) if isinstance(snapshot, dict) else [],
                "policy": LAB_POLICY,
            }
        except Exception as exc:
            db.rollback()
            return {"status": "error", "mode": "paper_forward_lifecycle", "current_blockers": [str(exc)], "policy": LAB_POLICY}

    def open_eligible_trades(
        self,
        db: Session,
        game: LiveForwardPaperGame | None = None,
        candidates: list[dict] | None = None,
    ) -> dict:
        """Open persisted CANDIDATE rows only when frozen entry conditions trigger.

        The optional game/candidates parameters preserve the legacy Trading
        Intelligence Lab API. Calls with explicit candidates are delegated
        unchanged so existing run_cycle behavior remains backward-compatible.
        """

        if candidates is not None and game is not None:
            return super().open_eligible_trades(db, game, candidates)

        live_game = game or self.active_or_create_live_game(db)
        rows = db.scalars(
            select(LiveForwardPaperTrade)
            .where(LiveForwardPaperTrade.game_id == live_game.id, LiveForwardPaperTrade.status.in_(["CANDIDATE", "WAITING_FOR_TRIGGER"]))
            .order_by(LiveForwardPaperTrade.created_at)
            .limit(50)
        ).all()
        opened: list[dict] = []
        waiting: list[dict] = []
        data_blocked: list[dict] = []
        skipped: list[dict] = []

        for trade in rows:
            if int(live_game.open_positions or 0) >= settings.live_trading_game_max_open_positions:
                skipped.append({"trade_id": trade.id, "ticker": trade.ticker, "reason": "max_open_positions_reached"})
                break

            latest = latest_market_price_after(db, trade.ticker, trade.decision_timestamp)
            if latest is None:
                self.append_event_once(
                    db,
                    trade,
                    "DATA_BLOCKED",
                    "No market price later than the frozen decision timestamp is available yet.",
                    payload={"phase": "entry_evaluation"},
                )
                data_blocked.append({"trade_id": trade.id, "ticker": trade.ticker, "reason": "no_future_market_data"})
                continue

            latest_date, latest_price = latest
            condition = self.entry_condition_status(trade, latest_price)
            if not condition["eligible"]:
                waiting.append({"trade_id": trade.id, "ticker": trade.ticker, **condition})
                continue

            opened.append(self.open_candidate_trade(db, live_game, trade, latest_date, latest_price, condition))

        return {"opened": opened, "waiting": waiting, "data_blocked": data_blocked, "skipped": skipped}

    def update_open_trades(self, db: Session, game: LiveForwardPaperGame | None = None) -> dict:
        """Mark open persisted paper trades to market without closing them."""

        if game is not None:
            return super().update_open_trades(db, game)

        live_game = self.active_or_create_live_game(db)
        rows = db.scalars(
            select(LiveForwardPaperTrade)
            .where(LiveForwardPaperTrade.game_id == live_game.id, LiveForwardPaperTrade.status == "OPEN")
            .order_by(LiveForwardPaperTrade.created_at)
            .limit(100)
        ).all()
        updated: list[dict] = []
        data_blocked: list[dict] = []

        for trade in rows:
            latest = latest_market_price_after(db, trade.ticker, trade.decision_timestamp)
            if latest is None:
                self.append_event_once(
                    db,
                    trade,
                    "DATA_BLOCKED",
                    "No market price later than the frozen decision timestamp is available yet.",
                    payload={"phase": "position_update"},
                )
                data_blocked.append({"trade_id": trade.id, "ticker": trade.ticker, "reason": "no_future_market_data"})
                continue

            latest_date, latest_price = latest
            before_price = trade.current_price
            before_pnl = trade.unrealized_pnl
            self.refresh_open_trade_mark_to_market(db, live_game, trade, latest_date, latest_price)
            self.update_open_benchmark_context(db, live_game, trade, latest_date, latest_price)
            current_r = self.current_r_multiple(trade, latest_price)
            materially_changed = before_price != trade.current_price or before_pnl != trade.unrealized_pnl
            if materially_changed:
                self.add_event(
                    db,
                    trade,
                    "POSITION_UPDATED",
                    latest_price,
                    "Paper position marked to latest available market data.",
                    {
                        "latest_date": latest_date.isoformat(),
                        "unrealized_pnl": trade.unrealized_pnl,
                        "current_r_multiple": current_r,
                        "benchmark_return_same_period": trade.benchmark_return_same_period,
                        "excess_return_vs_benchmark": trade.excess_return_vs_benchmark,
                    },
                )
            updated.append({**serialize_paper_forward_trade(trade, compact=True), "current_r_multiple": current_r})

        return {"updated": updated, "data_blocked": data_blocked}

    def close_resolved_trades(self, db: Session) -> dict:
        """Close OPEN paper trades only when a deterministic lifecycle rule fires."""

        live_game = self.active_or_create_live_game(db)
        rows = db.scalars(
            select(LiveForwardPaperTrade)
            .where(LiveForwardPaperTrade.game_id == live_game.id, LiveForwardPaperTrade.status == "OPEN")
            .order_by(LiveForwardPaperTrade.created_at)
            .limit(100)
        ).all()
        closed: list[dict] = []
        data_blocked: list[dict] = []

        for trade in rows:
            latest = latest_market_price_after(db, trade.ticker, trade.decision_timestamp)
            if latest is None:
                if trade.expires_at and datetime.utcnow() >= trade.expires_at and trade.current_price:
                    latest_date = date.today()
                    latest_price = safe_float(trade.current_price)
                    closed_trade = self.close_trade(db, live_game, trade, latest_date, latest_price, "DATA_GAP")
                    self.evaluate_closed_trade(db, trade)
                    closed.append(closed_trade)
                else:
                    self.append_event_once(
                        db,
                        trade,
                        "DATA_BLOCKED",
                        "No market price later than the frozen decision timestamp is available yet.",
                        payload={"phase": "close_evaluation"},
                    )
                    data_blocked.append({"trade_id": trade.id, "ticker": trade.ticker, "reason": "no_future_market_data"})
                continue

            latest_date, latest_price = latest
            close_reason = self.close_reason_for_trade(trade, latest_price)
            if not close_reason:
                continue
            closed_trade = self.close_trade(db, live_game, trade, latest_date, latest_price, close_reason)
            self.evaluate_closed_trade(db, trade)
            closed.append(closed_trade)

        return {"closed": closed, "data_blocked": data_blocked}

    def evaluate_closed_trade(self, db: Session, trade: LiveForwardPaperTrade) -> dict:
        """Normalize paper-forward outcome fields after a close event."""

        net = safe_float(trade.net_pnl_eur)
        if trade.close_reason == "DATA_GAP":
            outcome = "DATA_INVALID"
        elif abs(net) < 0.0001:
            outcome = "BREAKEVEN"
        elif net > 0:
            outcome = "WIN"
        else:
            outcome = "LOSS"

        trade.outcome_label = outcome
        trade.lesson_learned = self.paper_forward_lesson(trade)
        ledger_trade = db.get(TradingGameTrade, trade.ledger_trade_id) if trade.ledger_trade_id else None
        if ledger_trade:
            ledger_trade.outcome_label = outcome
            ledger_trade.lesson_generated = trade.lesson_learned
            ledger_trade.payload = {
                **(ledger_trade.payload or {}),
                "paper_forward_trade_id": trade.id,
                "model_version_used": trade.model_version_used,
                "weights_used": trade.weights_used,
                "confidence_adjustment": trade.confidence_adjustment,
                "learning_memory_used": trade.learning_memory_used,
                "strategy_memory_used": trade.strategy_memory_used,
                "research_priority_used": trade.research_priority_used,
                "outcome": outcome,
                "benchmark_excess": trade.excess_return_vs_benchmark,
            }
        self.append_event_once(
            db,
            trade,
            "OUTCOME_EVALUATED",
            trade.lesson_learned or "Closed paper-forward trade evaluated.",
            payload={
                "outcome": outcome,
                "r_multiple": trade.r_multiple,
                "benchmark_excess": trade.excess_return_vs_benchmark,
            },
            price_used=trade.exit_price,
        )
        return {
            "trade_id": trade.id,
            "ticker": trade.ticker,
            "outcome": outcome,
            "r_multiple": trade.r_multiple,
            "benchmark_excess": trade.excess_return_vs_benchmark,
        }

    def create_lesson_from_trade(self, db: Session, trade: LiveForwardPaperTrade) -> dict | None:
        if trade.status not in {"CLOSED", "EXPIRED", "INVALIDATED"} or not trade.ledger_trade_id:
            return None
        existing = db.scalar(
            select(TradeLearningEvidence)
            .where(
                TradeLearningEvidence.trade_id == trade.ledger_trade_id,
                TradeLearningEvidence.lesson_type == "paper_forward_outcome",
            )
            .limit(1)
        )
        if existing:
            return serialize_trade_lesson(existing)

        lesson_type = "setup_confirmed" if safe_float(trade.r_multiple) > 0 else "setup_failed"
        observation = trade.lesson_learned or self.paper_forward_lesson(trade)
        evidence = TradeLearningEvidence(
            trade_id=trade.ledger_trade_id,
            game_id=ensure_live_trade_game(db).id,
            ticker=trade.ticker,
            setup_type=trade.setup_type,
            regime=(trade.frozen_decision_payload or {}).get("market_regime") or "unknown",
            lesson_type="paper_forward_outcome",
            observation=observation,
            sample_size=1,
            supporting_trades_json={
                "paper_forward_trade_id": trade.id,
                "model_version_used": trade.model_version_used,
                "setup_type": trade.setup_type,
                "outcome": trade.outcome_label,
                "r_multiple": trade.r_multiple,
                "benchmark_excess": trade.excess_return_vs_benchmark,
                "confidence": trade.confidence,
                "confidence_adjustment": trade.confidence_adjustment,
                "weights_used": trade.weights_used,
                "strategy_memory_used": trade.strategy_memory_used,
                "learning_memory_used": trade.learning_memory_used,
                "research_priority_used": trade.research_priority_used,
                "entry": {
                    "price": trade.entry_price,
                    "trigger": trade.entry_trigger,
                    "confirmation_condition": trade.confirmation_condition,
                    "stop_loss": trade.stop_loss,
                    "target_1": trade.target_1,
                    "target_2": trade.target_2,
                    "position_size": trade.position_size,
                },
                "exit": {
                    "price": trade.exit_price,
                    "reason": trade.close_reason,
                    "pnl": trade.net_pnl_eur,
                    "pnl_percent": trade.pnl_percent,
                    "r_multiple": trade.r_multiple,
                },
            },
            affected_module="live_forward_paper_trading",
            action_taken="stored_for_feedback_loop",
            confidence=max(0.0, min(100.0, 55 + safe_float(trade.r_multiple) * 8)),
        )
        db.add(evidence)
        self.update_memory_from_trade(db, trade, lesson_type)
        db.add(
            LearningEvent(
                event_type="paper_forward_trade_closed",
                severity="Info",
                title=f"{trade.ticker} paper-forward {trade.outcome_label or 'closed'}",
                description=observation,
                payload={
                    "paper_forward_trade_id": trade.id,
                    "ledger_trade_id": trade.ledger_trade_id,
                    "model_version_used": trade.model_version_used,
                    "setup_type": trade.setup_type,
                    "outcome": trade.outcome_label,
                    "r_multiple": trade.r_multiple,
                    "benchmark_excess": trade.excess_return_vs_benchmark,
                    "lesson": observation,
                },
            )
        )
        self.append_event_once(
            db,
            trade,
            "LESSON_CREATED",
            observation,
            payload={"lesson_type": lesson_type, "affected_module": "live_forward_paper_trading"},
            price_used=trade.exit_price,
        )
        db.flush()
        return serialize_trade_lesson(evidence)

    def publish_lessons(self, db: Session, closed: list[dict] | None = None) -> list[dict]:
        if closed is not None:
            return super().publish_lessons(db, closed)

        rows = db.scalars(
            select(LiveForwardPaperTrade)
            .where(LiveForwardPaperTrade.status.in_(["CLOSED", "EXPIRED", "INVALIDATED"]))
            .order_by(desc(LiveForwardPaperTrade.closed_at))
            .limit(100)
        ).all()
        lessons: list[dict] = []
        for trade in rows:
            lesson = self.create_lesson_from_trade(db, trade)
            if lesson:
                lessons.append(lesson)
        return lessons

    def snapshot_payload(self, db: Session) -> dict:
        payload = super().snapshot_payload(db)
        game = self.active_game(db)
        if not game:
            return payload

        total_counts = {
            "candidate_count": int(db.scalar(select(func.count(LiveForwardPaperTrade.id)).where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status == "CANDIDATE")) or 0),
            "open_count": int(db.scalar(select(func.count(LiveForwardPaperTrade.id)).where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status == "OPEN")) or 0),
            "closed_count": int(db.scalar(select(func.count(LiveForwardPaperTrade.id)).where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status == "CLOSED")) or 0),
            "expired_count": int(db.scalar(select(func.count(LiveForwardPaperTrade.id)).where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status == "EXPIRED")) or 0),
            "invalidated_count": int(db.scalar(select(func.count(LiveForwardPaperTrade.id)).where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status == "INVALIDATED")) or 0),
            "data_blocked_count": int(db.scalar(select(func.count(LiveForwardPaperTrade.id)).where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status == "DATA_BLOCKED")) or 0),
            "waiting_for_trigger_count": int(db.scalar(select(func.count(LiveForwardPaperTrade.id)).where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status == "WAITING_FOR_TRIGGER")) or 0),
            "skipped_count": int(db.scalar(select(func.count(LiveForwardPaperTrade.id)).where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status == "SKIPPED")) or 0),
            "error_count": int(db.scalar(select(func.count(LiveForwardPaperTrade.id)).where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status == "ERROR")) or 0),
        }
        latest_events = db.scalars(select(LiveForwardPaperTradeEvent).order_by(desc(LiveForwardPaperTradeEvent.event_timestamp)).limit(20)).all()
        actionability_summary = self.actionability_summary(db, game)
        lifecycle_mode = self.lifecycle_mode(actionability_summary)
        payload.update(
            {
                "readiness_status": payload.get("readiness"),
                "last_run_at": payload.get("last_worker_run"),
                "paper_forward_lifecycle_mode": lifecycle_mode,
                "actionability_policy": ActionabilityPolicy().to_dict(),
                "actionability_summary": actionability_summary,
                "candidate_count": total_counts["candidate_count"],
                "waiting_for_trigger_count": total_counts["waiting_for_trigger_count"],
                "skipped_count": total_counts["skipped_count"],
                "open_count": total_counts["open_count"],
                "closed_count": total_counts["closed_count"],
                "expired_count": total_counts["expired_count"],
                "invalidated_count": total_counts["invalidated_count"],
                "data_blocked_count": total_counts["data_blocked_count"],
                "error_count": total_counts["error_count"],
                "latest_candidates": payload.get("candidates", []),
                "recently_closed_trades": payload.get("recently_closed", []),
                "latest_events": [serialize_live_event(row) for row in latest_events],
                "realized_pnl": (payload.get("metrics") or {}).get("realized_pnl"),
                "unrealized_pnl": (payload.get("metrics") or {}).get("unrealized_pnl"),
                "average_r": (payload.get("metrics") or {}).get("avg_r"),
                "win_rate": (payload.get("metrics") or {}).get("win_rate"),
                "benchmark_excess": (payload.get("metrics") or {}).get("benchmark_excess"),
                "latest_lesson": payload.get("last_lesson"),
                "current_blockers": sorted(set([*(payload.get("blockers", []) or []), *self.paper_forward_blockers_from_counts(actionability_summary)])),
                "lifecycle_message": lifecycle_message(lifecycle_mode),
            }
        )
        payload["counts"] = {**(payload.get("counts") or {}), **total_counts}
        return payload

    def actionability_summary(self, db: Session, game: LiveForwardPaperGame | None = None) -> dict:
        game = game or self.active_game(db)
        if not game:
            return empty_actionability_summary()
        rows = db.scalars(
            select(LiveForwardPaperTrade)
            .where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status.in_(["CANDIDATE", "WAITING_FOR_TRIGGER", "SKIPPED", "DATA_BLOCKED", "ERROR"]))
            .order_by(desc(LiveForwardPaperTrade.created_at))
            .limit(250)
        ).all()
        return paper_forward_actionability_summary(rows)

    def lifecycle_mode(self, actionability_summary: dict | None = None) -> str:
        if not settings.paper_forward_lifecycle_enabled:
            return "CANDIDATE_FREEZE_ONLY"
        summary = actionability_summary or {}
        if int(summary.get("actionable_count") or 0) <= 0 and int(summary.get("waiting_for_trigger_count") or 0) <= 0:
            return "LIFECYCLE_BLOCKED_BY_NO_ACTIONABLE_CANDIDATES"
        return "LIFECYCLE_ENABLED"

    def paper_forward_blockers_from_counts(self, actionability_summary: dict | None) -> list[str]:
        summary = actionability_summary or {}
        blockers: list[str] = []
        if not settings.paper_forward_lifecycle_enabled:
            blockers.append("paper_forward_lifecycle_disabled_by_settings")
        total = int(summary.get("total_candidates") or 0)
        actionable = int(summary.get("actionable_count") or 0)
        waiting = int(summary.get("waiting_for_trigger_count") or 0)
        skipped = int(summary.get("skipped_count") or 0)
        blocked = int(summary.get("data_blocked_count") or 0)
        errors = int(summary.get("error_count") or 0)
        if total == 0:
            blockers.append("no_paper_forward_candidates")
        elif actionable == 0 and waiting == 0 and skipped > 0:
            blockers.append("all_candidates_skipped_by_actionability_policy")
        elif waiting > 0 and actionable == 0:
            blockers.append("actionable_candidates_waiting_for_entry_trigger")
        if blocked:
            blockers.append("paper_forward_data_blocked")
        if errors:
            blockers.append("paper_forward_errors_present")
        return blockers

    def open_candidate_trade(
        self,
        db: Session,
        game: LiveForwardPaperGame,
        trade: LiveForwardPaperTrade,
        latest_date: date,
        latest_price: float,
        condition: dict,
    ) -> dict:
        now = datetime.utcnow()
        if trade.status not in {"CANDIDATE", "WAITING_FOR_TRIGGER"}:
            return serialize_paper_forward_trade(trade, compact=True)

        ledger_game = ensure_live_trade_game(db)
        ledger_trade = db.get(TradingGameTrade, trade.ledger_trade_id) if trade.ledger_trade_id else None
        if ledger_trade is None:
            ledger_trade = TradingGameTrade(
                game_id=ledger_game.id,
                mode="live_forward_paper",
                ticker=trade.ticker,
                asset_name=trade.asset_name or trade.ticker,
                asset_type=trade.asset_type,
                sector=trade.sector,
                industry=trade.industry,
                setup_type=trade.setup_type,
                sniper_score_at_entry=trade.sniper_score,
                confidence_at_entry=trade.confidence,
                actionability_state_at_entry=trade.actionability_state,
                market_regime_at_entry=(trade.frozen_decision_payload or {}).get("market_regime"),
                benchmark_ticker=trade.benchmark_ticker or game.benchmark_ticker,
                timeframe="daily",
                decision_state=trade.actionability_state or "active_setup",
                entry_date=latest_date,
                entry_price=latest_price,
                entry_reason=f"Frozen paper-forward candidate opened after {condition.get('entry_type')} condition triggered.",
                entry_trigger=trade.entry_trigger,
                confirmation_condition=trade.confirmation_condition,
                position_size=round(safe_float(trade.position_size), 6),
                notional_value=round(safe_float(trade.position_size) * latest_price, 4),
                risk_amount=round(safe_float(trade.risk_amount), 4),
                risk_percent=trade.risk_percent,
                stop_loss=trade.stop_loss,
                invalidation_level=trade.invalidation_level,
                initial_target_1=trade.target_1,
                initial_target_2=trade.target_2,
                trailing_stop="Live forward paper trailing logic evaluates on future market refreshes.",
                capital_before=round(safe_float(game.current_capital), 4),
                capital_after=round(safe_float(game.current_capital), 4),
                reproducibility_score=70.0,
                data_quality_score=((trade.frozen_decision_payload or {}).get("price_context") or {}).get("data_quality_score"),
                outcome_label="open",
                payload={
                    "paper_forward_trade_id": trade.id,
                    "frozen_candidate": compact_candidate(trade.frozen_decision_payload or {}),
                    "model_version_used": trade.model_version_used,
                    "weights_used": trade.weights_used,
                    "confidence_adjustment": trade.confidence_adjustment,
                    "learning_memory_used": trade.learning_memory_used,
                    "strategy_memory_used": trade.strategy_memory_used,
                    "research_priority_used": trade.research_priority_used,
                    "entry_condition": condition,
                    "no_future_data_policy": "Candidate opened only after later market data met the frozen entry condition.",
                },
            )
            db.add(ledger_trade)
            db.flush()
            trade.ledger_trade_id = ledger_trade.id

        trade.status = "OPEN"
        trade.entry_price = latest_price
        trade.entry_date = latest_date
        trade.opened_at = now
        trade.current_price = latest_price
        trade.notional_value = round(safe_float(trade.position_size) * latest_price, 4)
        if trade.stop_loss:
            risk_per_share = abs(latest_price - safe_float(trade.stop_loss))
            trade.expected_risk = round(risk_per_share * safe_float(trade.position_size), 4)
        if trade.target_1:
            trade.expected_reward = round((safe_float(trade.target_1) - latest_price) * safe_float(trade.position_size), 4)
        if trade.expected_risk:
            trade.expected_r_multiple = round(safe_float(trade.expected_reward) / max(0.01, safe_float(trade.expected_risk)), 4)
        trade.updated_at = now

        if live_position_for_paper_trade(db, game, trade) is None:
            position = LiveForwardPaperPosition(
                game_id=game.id,
                trade_id=trade.ledger_trade_id,
                ticker=trade.ticker,
                setup_type=trade.setup_type,
                status="open",
                decision_timestamp=trade.decision_timestamp,
                entry_price=latest_price,
                current_price=latest_price,
                position_size=safe_float(trade.position_size),
                risk_amount=safe_float(trade.risk_amount),
                stop_loss=trade.stop_loss,
                target_1=trade.target_1,
                target_2=trade.target_2,
                thesis_snapshot={"actionability": trade.actionability_state, "confidence": trade.confidence},
                data_snapshot={"latest_date": latest_date.isoformat(), "entry_condition": condition, "paper_trade_id": trade.id},
            )
            db.add(position)

        game.open_positions = int(game.open_positions or 0) + 1
        game.exposure = round(safe_float(game.exposure) + safe_float(trade.notional_value), 4)
        game.cash = round(max(0.0, safe_float(game.cash) - safe_float(trade.notional_value)), 4)
        game.updated_at = now
        self.append_event_once(
            db,
            trade,
            "ENTRY_TRIGGERED",
            condition.get("reason") or "Frozen entry condition triggered.",
            payload=condition,
            price_used=latest_price,
        )
        self.append_event_once(
            db,
            trade,
            "POSITION_OPENED",
            "Paper position opened. No broker execution.",
            payload={"position_size": trade.position_size, "risk_amount": trade.risk_amount, "entry_date": latest_date.isoformat()},
            price_used=latest_price,
        )
        return serialize_paper_forward_trade(trade, compact=True)

    def entry_condition_status(self, trade: LiveForwardPaperTrade, latest_price: float) -> dict:
        plan = (trade.frozen_decision_payload or {}).get("trade_plan") or {}
        entry_type = normalize_text(plan.get("entry_type") or plan.get("order_type") or "MARKET").upper()
        entry_zone = plan.get("entry_zone") if isinstance(plan.get("entry_zone"), dict) else {}
        trigger_price = first_positive_float(
            plan.get("trigger_price"),
            plan.get("entry_trigger_price"),
            plan.get("breakout_level"),
            plan.get("confirmation_price"),
            entry_zone.get("high"),
            trade.entry_price,
        )
        limit_price = first_positive_float(
            plan.get("limit_price"),
            plan.get("pullback_price"),
            entry_zone.get("low"),
            trade.entry_price,
        )

        if entry_type in {"MARKET", "MKT"}:
            return {"eligible": True, "entry_type": "MARKET", "reason": "Market-style paper entry evaluated on latest future data."}
        if entry_type in {"ABOVE_TRIGGER", "BREAKOUT"}:
            eligible = latest_price >= trigger_price if trigger_price else False
            return {
                "eligible": eligible,
                "entry_type": entry_type,
                "trigger_price": trigger_price,
                "latest_price": latest_price,
                "reason": "Breakout/above-trigger condition met." if eligible else "Waiting for price above trigger.",
            }
        if entry_type == "BELOW_TRIGGER":
            eligible = latest_price <= trigger_price if trigger_price else False
            return {
                "eligible": eligible,
                "entry_type": entry_type,
                "trigger_price": trigger_price,
                "latest_price": latest_price,
                "reason": "Below-trigger condition met." if eligible else "Waiting for price below trigger.",
            }
        if entry_type in {"LIMIT", "PULLBACK"}:
            eligible = latest_price <= limit_price if limit_price else False
            return {
                "eligible": eligible,
                "entry_type": entry_type,
                "limit_price": limit_price,
                "latest_price": latest_price,
                "reason": "Limit/pullback condition met." if eligible else "Waiting for limit or pullback zone.",
            }
        return {
            "eligible": False,
            "entry_type": entry_type or "UNKNOWN",
            "latest_price": latest_price,
            "reason": "Unsupported or incomplete paper entry type.",
        }

    def close_reason_for_trade(self, trade: LiveForwardPaperTrade, latest_price: float) -> str | None:
        if trade.stop_loss and latest_price <= safe_float(trade.stop_loss):
            return "STOP_HIT"
        if trade.invalidation_level and latest_price <= safe_float(trade.invalidation_level):
            return "INVALIDATION_HIT"
        if trade.target_2 and latest_price >= safe_float(trade.target_2):
            return "TARGET_2_HIT"
        if trade.target_1 and latest_price >= safe_float(trade.target_1):
            return "TARGET_1_HIT"
        if trade.expires_at and datetime.utcnow() >= trade.expires_at:
            return "TIME_EXIT"
        return None

    def update_open_benchmark_context(self, db: Session, game: LiveForwardPaperGame, trade: LiveForwardPaperTrade, latest_date: date, latest_price: float) -> None:
        entry = safe_float(trade.entry_price)
        asset_return = ((latest_price / entry) - 1) * 100 if entry else None
        benchmark_return = period_return(db, trade.benchmark_ticker or game.benchmark_ticker, trade.decision_date, latest_date)
        trade.benchmark_return_same_period = benchmark_return
        trade.excess_return_vs_benchmark = round(asset_return - benchmark_return, 4) if asset_return is not None and benchmark_return is not None else None

    def current_r_multiple(self, trade: LiveForwardPaperTrade, latest_price: float) -> float | None:
        entry = safe_float(trade.entry_price)
        if not entry:
            return None
        risk_per_share = abs(entry - safe_float(trade.stop_loss or trade.invalidation_level))
        if risk_per_share <= 0:
            risk_per_share = safe_float(trade.risk_amount) / max(0.000001, safe_float(trade.position_size))
        if risk_per_share <= 0:
            return None
        return round((latest_price - entry) / risk_per_share, 4)

    def paper_forward_lesson(self, trade: LiveForwardPaperTrade) -> str:
        if trade.close_reason == "DATA_GAP":
            return f"{trade.setup_type} on {trade.ticker} could not be evaluated cleanly because the live-forward data stream had a gap."
        direction = "worked" if safe_float(trade.r_multiple) > 0 else "failed" if safe_float(trade.r_multiple) < 0 else "was neutral"
        benchmark_part = ""
        if trade.excess_return_vs_benchmark is not None:
            benchmark_part = f" Benchmark excess was {safe_float(trade.excess_return_vs_benchmark):.2f}%."
        return (
            f"{trade.setup_type} on {trade.ticker} {direction} in paper-forward lifecycle "
            f"with {safe_float(trade.r_multiple):.2f}R after {trade.close_reason or 'manual close'}."
            f"{benchmark_part} Store as evidence, not proof of edge."
        )

    def append_event_once(
        self,
        db: Session,
        trade: LiveForwardPaperTrade,
        event_type: str,
        reason: str,
        payload: dict[str, Any] | None = None,
        price_used: float | None = None,
    ) -> LiveForwardPaperTradeEvent | None:
        exists = db.scalar(
            select(LiveForwardPaperTradeEvent.id)
            .where(LiveForwardPaperTradeEvent.paper_trade_id == trade.id, LiveForwardPaperTradeEvent.event_type == event_type)
            .limit(1)
        )
        if exists:
            return None
        return self.add_event(db, trade, event_type, price_used, reason, payload)


def empty_actionability_summary() -> dict:
    return {
        "total_candidates": 0,
        "actionable_count": 0,
        "waiting_for_trigger_count": 0,
        "skipped_count": 0,
        "data_blocked_count": 0,
        "error_count": 0,
        "status_distribution": {},
        "top_rejection_reasons": [],
        "latest_actionable_candidate": None,
        "latest_waiting_candidate": None,
        "latest_skipped_candidate": None,
        "latest_data_blocked_candidate": None,
    }


def lifecycle_message(mode: str) -> str:
    messages = {
        "CANDIDATE_FREEZE_ONLY": "Paper-forward lifecycle is currently disabled. BLUM is freezing decisions but not opening or closing trades.",
        "LIFECYCLE_ENABLED": "Paper-forward lifecycle is enabled. BLUM may open only candidates that pass actionability and trigger checks.",
        "LIFECYCLE_DISABLED_BY_SETTINGS": "Paper-forward lifecycle is disabled by settings. Manual lifecycle runs require explicit override.",
        "LIFECYCLE_BLOCKED_BY_NO_ACTIONABLE_CANDIDATES": "Lifecycle is enabled but no actionable candidates are available.",
    }
    return messages.get(mode, "Paper-forward lifecycle state is unknown.")


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


def broad_ohlcv_universe(db: Session, *, limit: int = 90, min_rows: int = 120) -> list[Asset]:
    row_count = func.count(PriceHistory.id)
    latest_date = func.max(PriceHistory.date)
    rows = db.execute(
        select(Asset, row_count.label("row_count"), latest_date.label("latest_price_date"))
        .join(PriceHistory, PriceHistory.asset_id == Asset.id)
            .where(Asset.is_active.is_(True), func.lower(Asset.asset_type).in_(["stock", "etf"]))
        .group_by(Asset.id)
        .having(row_count >= max(30, int(min_rows)))
        .order_by(desc(latest_date), desc(row_count), Asset.ticker)
        .limit(max(1, int(limit)))
    ).all()
    return [asset for asset, _, _ in rows]


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def first_positive_float(*values: Any) -> float | None:
    for value in values:
        parsed = safe_float(value)
        if parsed > 0:
            return parsed
    return None


def serialize_foundation_event(row: LiveForwardPaperTradeEvent) -> dict:
    return serialize_live_event(row)
