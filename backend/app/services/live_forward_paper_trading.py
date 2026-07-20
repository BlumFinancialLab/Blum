from __future__ import annotations

from datetime import date, datetime, timedelta
import math
import re
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, func, or_, select
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
    SniperScore,
    TradeLearningEvidence,
    TradePlan,
    TradingGameTrade,
)
from app.services.trading_intelligence_lab import (
    ActionabilityPolicy,
    LAB_POLICY,
    LiveForwardPaperTradingService as _TradingLabLiveForwardService,
    actionability_event_payload,
    diagnose_candidate_actionability,
    compact_candidate,
    candidate_evidence_fingerprint,
    ensure_live_trade_game,
    freeze_decision_payload,
    latest_market_price_after,
    live_position_for_paper_trade,
    live_forward_duplicate_key,
    paper_forward_actionability_summary,
    period_return,
    price_on_or_before,
    safe_float,
    serialize_live_event,
    serialize_paper_forward_trade,
    serialize_paper_forward_trades,
    serialize_trade_lesson,
)
from app.services.paper_forward_opportunity_scanner import (
    BLOCKED_CANDIDATE,
    DATA_BLOCKED_CANDIDATE,
    TRADE_CANDIDATE,
    WATCHLIST_CANDIDATE,
    PaperForwardOpportunityScanner,
)
from app.services.copy_readiness_evidence import CopyReadinessSummaryService


settings = get_settings()
PAPER_FORWARD_INVALID_ENTRY_GEOMETRY = "PAPER_FORWARD_INVALID_ENTRY_GEOMETRY"


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
            evidence_fingerprint=candidate_evidence_fingerprint(decision_payload),
        )
        existing = db.scalar(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.duplicate_key == duplicate_key).limit(1))
        if existing:
            return existing

        scanner_block = decision_payload.get("opportunity_scanner") if isinstance(decision_payload.get("opportunity_scanner"), dict) else {}
        classification = decision_payload.get("paper_forward_classification") or scanner_block.get("classification")
        diagnosis = diagnose_candidate_actionability(decision_payload, strict=True)
        diagnosis_payload = diagnosis.to_dict()
        if classification == WATCHLIST_CANDIDATE and diagnosis.actionability_status != "DATA_BLOCKED":
            diagnosis_payload = {
                **diagnosis_payload,
                "actionability_status": "WAITING_FOR_TRIGGER",
                "rejection_reason": decision_payload.get("classification_reason") or diagnosis.rejection_reason,
                "should_wait": True,
                "scanner_original_status": diagnosis.actionability_status,
            }
        decision_payload_with_diagnosis = {
            **decision_payload,
            "paper_forward_classification": classification or classification_from_diagnosis(diagnosis.actionability_status),
            "actionability_diagnosis": diagnosis_payload,
        }
        price = safe_float((decision_payload.get("price_context") or {}).get("latest_price"))
        if classification == DATA_BLOCKED_CANDIDATE or diagnosis_payload["actionability_status"] == "DATA_BLOCKED":
            status = "DATA_BLOCKED"
            block_reason = diagnosis_payload["rejection_reason"]
        elif classification == WATCHLIST_CANDIDATE or diagnosis_payload["actionability_status"] == "WAITING_FOR_TRIGGER":
            status = "WAITING_FOR_TRIGGER"
            block_reason = diagnosis_payload["rejection_reason"]
        elif classification == BLOCKED_CANDIDATE or diagnosis_payload["actionability_status"] != "ACTIONABLE":
            status = "SKIPPED"
            block_reason = diagnosis_payload["rejection_reason"]
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
            confidence=(
                decision_payload.get("confidence")
                if decision_payload.get("confidence") is not None
                else diagnosis_payload.get("confidence")
            ),
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
            payload={"candidate": compact_candidate(decision_payload), "feedback": feedback, "actionability_diagnosis": diagnosis_payload},
            price_used=price if price > 0 else None,
        )
        self.append_event(
            db,
            trade.id,
            "OPPORTUNITY_SCANNED",
            "Opportunity scanned by the global paper-forward scanner.",
            payload={
                "classification": decision_payload_with_diagnosis["paper_forward_classification"],
                "scanner": scanner_block,
                "candidate": compact_candidate(decision_payload_with_diagnosis),
            },
            price_used=price if price > 0 else None,
        )
        if scanner_block.get("rank") is not None:
            self.append_event(
                db,
                trade.id,
                "CROSS_MARKET_RANKED",
                "Candidate ranked inside the cross-market paper-forward scan.",
                payload={
                    "rank": scanner_block.get("rank"),
                    "score": scanner_block.get("score"),
                    "market": scanner_block.get("market"),
                    "asset_class": scanner_block.get("asset_class"),
                    "benchmark_asset": scanner_block.get("benchmark_asset"),
                    "classification": decision_payload_with_diagnosis["paper_forward_classification"],
                },
                price_used=price if price > 0 else None,
            )
        benchmark_context = decision_payload_with_diagnosis.get("benchmark_context") if isinstance(decision_payload_with_diagnosis.get("benchmark_context"), dict) else {}
        if benchmark_context:
            self.append_event(
                db,
                trade.id,
                "BENCHMARK_MAPPED" if benchmark_context.get("benchmark_available") else "BENCHMARK_MISSING",
                benchmark_context.get("benchmark_reason") or benchmark_context.get("benchmark_blocker") or "Benchmark context stored.",
                payload=benchmark_context,
                price_used=price if price > 0 else None,
            )
        self.append_event(
            db,
            trade.id,
            "ACTIONABILITY_CLASSIFIED",
            decision_payload_with_diagnosis.get("classification_reason") or block_reason or "Paper-forward candidate classified.",
            payload={
                "classification": decision_payload_with_diagnosis["paper_forward_classification"],
                "asset": decision_payload_with_diagnosis.get("asset") or {},
                "market": ((decision_payload_with_diagnosis.get("asset") or {}).get("market")),
                "asset_type": ((decision_payload_with_diagnosis.get("asset") or {}).get("asset_type")),
                "rank": scanner_block.get("rank"),
                "score": scanner_block.get("score"),
                "actionability_diagnosis": diagnosis_payload,
            },
            price_used=price if price > 0 else None,
        )
        classification_event = {
            TRADE_CANDIDATE: "TRADE_CANDIDATE_CREATED",
            WATCHLIST_CANDIDATE: "WATCHLIST_CANDIDATE_CREATED",
            BLOCKED_CANDIDATE: "CANDIDATE_BLOCKED",
            DATA_BLOCKED_CANDIDATE: "DATA_BLOCKED",
        }.get(decision_payload_with_diagnosis["paper_forward_classification"])
        if classification_event and classification_event != "DATA_BLOCKED":
            self.append_event(
                db,
                trade.id,
                classification_event,
                decision_payload_with_diagnosis.get("classification_reason") or block_reason or classification_event,
                payload={"classification": decision_payload_with_diagnosis["paper_forward_classification"], "scanner": scanner_block},
                price_used=price if price > 0 else None,
            )
        if status == "DATA_BLOCKED":
            self.append_event(db, trade.id, "DATA_BLOCKED", block_reason, payload={"price_context": decision_payload.get("price_context"), "actionability_diagnosis": diagnosis_payload})
        elif status in {"SKIPPED", "WAITING_FOR_TRIGGER"}:
            self.append_event(db, trade.id, "ACTIONABILITY_REJECTED", block_reason, payload={**actionability_event_payload(decision_payload, diagnosis, feedback), "classification": decision_payload_with_diagnosis["paper_forward_classification"]}, price_used=price if price > 0 else None)
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

        desired = max(1, min(int(limit or 30), settings.paper_forward_max_candidates_per_run, 40))
        engine = MarketSniperEngine()
        candidates: list[dict] = stored_sniper_candidates(db, limit=desired)
        seen: set[str] = set()
        for item in candidates:
            ticker = normalize_text(item.get("ticker")).upper()
            if ticker:
                seen.add(ticker)

        def add_candidate(item: dict, source: str) -> None:
            ticker = normalize_text(item.get("ticker")).upper()
            if not ticker or ticker in seen:
                return
            payload = dict(item)
            payload["scouting_source"] = source
            payload["scouting_policy"] = "real_stored_ohlcv_only_no_synthetic_candidates"
            seen.add(ticker)
            candidates.append(payload)

        remaining = max(0, desired - len(candidates))
        if remaining:
            fallback_limit = min(remaining, 6)
            try:
                payload = engine.candidates(db, limit=fallback_limit, persist=False)
                for item in payload.get("candidates", []) or []:
                    add_candidate(item, "market_sniper_live_fallback_limited")
            except Exception as exc:
                db.add(
                    LearningEvent(
                        event_type="paper_forward_scouting_degraded",
                        severity="Warning",
                        title="Paper-forward limited live fallback failed",
                        description=f"{type(exc).__name__}: {exc}",
                        payload={"source": "market_sniper_live_fallback_limited", "fallback_limit": fallback_limit},
                    )
                )

        if len(candidates) < desired:
            for asset in broad_ohlcv_universe(db, limit=min(12, desired * 2)):
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
            scanner_report = PaperForwardOpportunityScanner().scan(db)
            candidates = scanner_report.get("candidate_payloads_for_persistence") or []
        except Exception as exc:
            db.rollback()
            return {"status": "error", "created": [], "duplicates": [], "current_blockers": [str(exc)], "policy": LAB_POLICY}

        created: list[dict] = []
        created_trade_candidates: list[dict] = []
        created_watchlist_candidates: list[dict] = []
        created_blocked_candidates: list[dict] = []
        created_data_blocked_candidates: list[dict] = []
        duplicates: list[dict] = []
        blocked: list[dict] = []
        skipped: list[dict] = []
        waiting: list[dict] = []
        for candidate in candidates:
            before_id = existing_candidate_id(db, self, candidate)
            trade = self.create_candidate(db, candidate)
            serialized = serialize_paper_forward_trade(trade, compact=True)
            classification = candidate.get("paper_forward_classification")
            if before_id == trade.id:
                duplicates.append(serialized)
            elif trade.status == "DATA_BLOCKED":
                blocked.append(serialized)
                created_data_blocked_candidates.append(serialized)
            elif trade.status == "SKIPPED":
                skipped.append(serialized)
                created_blocked_candidates.append(serialized)
            elif trade.status == "WAITING_FOR_TRIGGER":
                waiting.append(serialized)
                created_watchlist_candidates.append(serialized)
            else:
                created.append(serialized)
                if classification == TRADE_CANDIDATE:
                    created_trade_candidates.append(serialized)

        db.commit()
        snapshot = self.publish_snapshot(db)
        actionability_summary = snapshot.get("payload", {}).get("actionability_summary") if isinstance(snapshot, dict) else None
        scanner_report = {
            **scanner_report,
            "created_trade_candidates": created_trade_candidates,
            "created_watchlist_candidates": created_watchlist_candidates,
            "created_blocked_candidates": created_blocked_candidates,
            "created_data_blocked_candidates": created_data_blocked_candidates,
            "duplicates": duplicates,
        }
        response_scanner_report = {
            key: value
            for key, value in scanner_report.items()
            if key != "candidate_payloads_for_persistence"
        }
        return {
            "status": "ok",
            "mode": "foundation_candidate_freeze",
            "candidates_seen": len(candidates),
            "created": created,
            "duplicates": duplicates,
            "waiting_for_trigger": waiting,
            "skipped": skipped,
            "data_blocked": blocked,
            "scanner_summary": response_scanner_report,
            "markets_scanned": scanner_report.get("markets_scanned"),
            "asset_classes_scanned": scanner_report.get("asset_classes_scanned"),
            "skipped_markets": scanner_report.get("skipped_markets"),
            "enabled_market_desk_agents": scanner_report.get("enabled_market_desk_agents", []),
            "agents_run": scanner_report.get("agents_run", []),
            "agents_skipped": scanner_report.get("agents_skipped", []),
            "opportunities_by_agent": scanner_report.get("opportunities_by_agent", {}),
            "top_cross_market_opportunities": scanner_report.get("top_cross_market_opportunities", []),
            "quant_edge_summary": scanner_report.get("quant_edge_summary", {}),
            "diversification_summary": scanner_report.get("diversification_summary", {}),
            "best_cross_market_candidate": scanner_report.get("best_cross_market_candidate"),
            "reason_if_no_trade_candidates": scanner_report.get("reason_if_no_trade_candidates"),
            "actionability_summary": actionability_summary,
            "snapshot_status": snapshot.get("status"),
            "current_blockers": self.paper_forward_blockers_from_counts(actionability_summary) if actionability_summary else ([] if created or duplicates else ["no_candidate_decisions_available"]),
            "policy": LAB_POLICY,
        }

    def run_cycle(self, db: Session) -> dict:
        """Backward-compatible entrypoint without the legacy raw scan bypass."""

        if settings.paper_forward_lifecycle_enabled:
            return self.run_lifecycle(db)
        return self.run_once(db)

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
            events_before = int(db.scalar(select(func.count(LiveForwardPaperTradeEvent.id))) or 0)
            opened = self.open_eligible_trades(db)
            updated = self.update_open_trades(db)
            closed = self.close_resolved_trades(db)
            quarantined = self.quarantine_invalid_entry_geometry(db)
            lessons = self.publish_lessons(db)
            self.refresh_live_game_counts(db, game)
            events_after = int(db.scalar(select(func.count(LiveForwardPaperTradeEvent.id))) or 0)
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
                    "quarantine_invalid_entry_geometry": quarantined,
                    "publish_lessons": {"created": len(lessons), "lessons": lessons[:8]},
                },
                "candidates_checked": len(opened.get("opened", [])) + len(opened.get("waiting", [])) + len(opened.get("data_blocked", [])) + len(opened.get("skipped", [])),
                "opened_trades": len(opened.get("opened", [])),
                "updated_trades": len(updated.get("updated", [])),
                "closed_trades": len(closed.get("closed", [])),
                "blocked_candidates": len(opened.get("data_blocked", [])) + len(opened.get("skipped", [])),
                "waiting_for_trigger": len(opened.get("waiting", [])),
                "events_created": max(0, events_after - events_before),
                "next_action": "Run /api/paper-forward/run-lifecycle again after fresh market data or candidate creation.",
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
        rows = self.lifecycle_candidates(db, live_game)
        opened: list[dict] = []
        waiting: list[dict] = []
        data_blocked: list[dict] = []
        skipped: list[dict] = []
        open_tickers = {
            str(ticker).upper()
            for ticker in db.scalars(
                select(LiveForwardPaperTrade.ticker).where(
                    LiveForwardPaperTrade.game_id == live_game.id,
                    LiveForwardPaperTrade.status.in_(["ORDER_SUBMITTED", "PARTIALLY_FILLED", "OPEN"]),
                )
            ).all()
            if ticker
        }

        for trade in rows:
            if int(live_game.open_positions or 0) >= settings.live_trading_game_max_open_positions:
                skipped.append({"trade_id": trade.id, "ticker": trade.ticker, "reason": "max_open_positions_reached"})
                break
            if trade.ticker.upper() in open_tickers:
                skipped.append({"trade_id": trade.id, "ticker": trade.ticker, "reason": "ticker_position_already_open"})
                continue

            classification = classification_from_trade(trade)
            watchlist_can_mature = classification == WATCHLIST_CANDIDATE and waiting_candidate_can_mature(trade)
            if classification != TRADE_CANDIDATE and not watchlist_can_mature:
                waiting.append({
                    "trade_id": trade.id,
                    "ticker": trade.ticker,
                    "reason": "non_trade_candidate",
                    "classification": classification,
                })
                continue

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
            entry_window = self.entry_window_status(trade, latest_date)
            if not entry_window["valid"]:
                trade.status = "SKIPPED"
                trade.outcome_label = "SIGNAL_DECAY_BEFORE_ENTRY"
                trade.lesson_learned = entry_window["explanation"]
                trade.updated_at = datetime.utcnow()
                self.append_event_once(
                    db,
                    trade,
                    "SIGNAL_DECAY_BEFORE_ENTRY",
                    entry_window["explanation"],
                    payload=entry_window,
                    price_used=latest_price,
                )
                skipped.append(
                    {
                        "trade_id": trade.id,
                        "ticker": trade.ticker,
                        **entry_window,
                        "reason": "signal_decay_before_entry",
                    }
                )
                continue

            condition = self.entry_condition_status(trade, latest_price)
            if not condition["eligible"]:
                waiting.append({"trade_id": trade.id, "ticker": trade.ticker, **condition})
                continue

            geometry = self.entry_risk_geometry_status(trade, latest_price)
            if not geometry["valid"]:
                trade.status = "SKIPPED"
                trade.outcome_label = "NO_TRADE_ENTRY_GEOMETRY"
                trade.lesson_learned = geometry["reason"]
                trade.updated_at = datetime.utcnow()
                self.append_event_once(
                    db,
                    trade,
                    "ENTRY_RISK_REWARD_DETERIORATED",
                    geometry["reason"],
                    payload=geometry,
                    price_used=latest_price,
                )
                skipped.append(
                    {
                        "trade_id": trade.id,
                        "ticker": trade.ticker,
                        **geometry,
                        "reason": "entry_risk_reward_deteriorated",
                        "explanation": geometry["reason"],
                    }
                )
                continue

            if watchlist_can_mature:
                self.append_event_once(
                    db,
                    trade,
                    "WATCHLIST_TRIGGER_CONFIRMED",
                    "A later market observation confirmed the explicit trigger stored in the frozen watchlist decision.",
                    payload={"condition": condition, "original_classification": classification},
                    price_used=latest_price,
                )

            opened.append(self.open_candidate_trade(db, live_game, trade, latest_date, latest_price, condition))
            open_tickers.add(trade.ticker.upper())

        return {"opened": opened, "waiting": waiting, "data_blocked": data_blocked, "skipped": skipped}

    def lifecycle_candidates(self, db: Session, game: LiveForwardPaperGame) -> list[LiveForwardPaperTrade]:
        """Use the scanner's persisted composite rank before watchlist and recency tie-breakers."""

        rows = list(
            db.scalars(
                select(LiveForwardPaperTrade)
                .where(
                    LiveForwardPaperTrade.game_id == game.id,
                    LiveForwardPaperTrade.status.in_(["CANDIDATE", "WAITING_FOR_TRIGGER"]),
                )
                .order_by(desc(LiveForwardPaperTrade.decision_timestamp))
                .limit(250)
            ).all()
        )
        return sorted(rows, key=lifecycle_candidate_priority)[:50]

    def entry_risk_geometry_status(self, trade: LiveForwardPaperTrade, entry_price: float) -> dict[str, Any]:
        stop = safe_float(trade.stop_loss or trade.invalidation_level)
        target = safe_float(trade.target_1)
        risk = entry_price - stop
        reward = target - entry_price
        risk_reward = reward / risk if risk > 0 else None
        valid = bool(
            entry_price > 0
            and stop > 0
            and target > 0
            and risk > 0
            and reward > 0
            and risk_reward is not None
            and risk_reward >= settings.paper_forward_min_risk_reward
        )
        reason = (
            "Entry geometry remains valid at the observed execution price."
            if valid
            else (
                "No trade: the frozen stop/target geometry deteriorated at the observed entry price "
                f"(actual R/R {risk_reward:.2f}, minimum {settings.paper_forward_min_risk_reward:.2f})."
                if risk_reward is not None
                else "No trade: the frozen stop/target geometry is invalid at the observed entry price."
            )
        )
        return {
            "valid": valid,
            "entry_price": entry_price,
            "stop_loss": stop or None,
            "target_1": target or None,
            "actual_risk": risk if risk > 0 else None,
            "actual_reward": reward if reward > 0 else None,
            "actual_risk_reward": round(risk_reward, 4) if risk_reward is not None else None,
            "minimum_risk_reward": settings.paper_forward_min_risk_reward,
            "reason": reason,
        }

    def quarantine_invalid_entry_geometry(self, db: Session) -> dict[str, Any]:
        rows = db.scalars(
            select(LiveForwardPaperTrade)
            .join(
                LiveForwardPaperTradeEvent,
                LiveForwardPaperTradeEvent.paper_trade_id == LiveForwardPaperTrade.id,
            )
            .where(
                LiveForwardPaperTrade.status.in_(["CLOSED", "EXPIRED", "INVALIDATED"]),
                LiveForwardPaperTrade.entry_price.is_not(None),
                or_(
                    LiveForwardPaperTrade.evidence_type.is_(None),
                    LiveForwardPaperTrade.evidence_type != PAPER_FORWARD_INVALID_ENTRY_GEOMETRY,
                ),
                LiveForwardPaperTradeEvent.event_type == "WATCHLIST_TRIGGER_CONFIRMED",
            )
            .order_by(desc(LiveForwardPaperTrade.closed_at), desc(LiveForwardPaperTrade.id))
            .limit(100)
        ).all()
        quarantined: list[int] = []
        for trade in rows:
            geometry = self.entry_risk_geometry_status(trade, safe_float(trade.entry_price))
            if geometry["valid"]:
                continue
            trade.evidence_type = PAPER_FORWARD_INVALID_ENTRY_GEOMETRY
            trade.outcome_label = "EVIDENCE_QUARANTINED"
            trade.lesson_learned = (
                "Evidence quarantined: the watchlist setup opened after its frozen risk/reward geometry had deteriorated."
            )
            trade.updated_at = datetime.utcnow()
            ledger_trade = db.get(TradingGameTrade, trade.ledger_trade_id) if trade.ledger_trade_id else None
            if ledger_trade is not None:
                ledger_trade.outcome_label = "EVIDENCE_QUARANTINED"
                ledger_trade.lesson_generated = trade.lesson_learned
                ledger_trade.payload = {
                    **(ledger_trade.payload or {}),
                    "evidence_quarantined": True,
                    "quarantine_reason": "invalid_entry_geometry",
                    "entry_geometry": geometry,
                }
            learning_evidence = db.scalars(
                select(TradeLearningEvidence).where(TradeLearningEvidence.trade_id == trade.ledger_trade_id)
            ).all() if trade.ledger_trade_id else []
            for evidence in learning_evidence:
                evidence.lesson_type = "paper_forward_quarantined"
                evidence.action_taken = "excluded_from_learning_evidence"
                evidence.observation = trade.lesson_learned
            self.append_event_once(
                db,
                trade,
                "EVIDENCE_QUARANTINED",
                trade.lesson_learned,
                payload={"reason": "invalid_entry_geometry", "entry_geometry": geometry},
                price_used=trade.entry_price,
            )
            db.add(
                LearningEvent(
                    event_type="paper_forward_evidence_quarantined",
                    severity="Warning",
                    title=f"{trade.ticker} paper-forward evidence quarantined",
                    description=trade.lesson_learned,
                    payload={"paper_forward_trade_id": trade.id, "entry_geometry": geometry},
                )
            )
            quarantined.append(trade.id)
        return {"quarantined": quarantined, "count": len(quarantined)}

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
            self.ensure_trade_expiration(db, trade)
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
        if trade.evidence_type == PAPER_FORWARD_INVALID_ENTRY_GEOMETRY:
            return None
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
        from app.services.intraday_paper_engine import intraday_snapshot_summary
        from app.services.paper_execution_lifecycle import execution_reality_snapshot

        payload["intraday"] = intraday_snapshot_summary(db)
        payload["execution_reality"] = execution_reality_snapshot(db)
        payload.update({key: value for key, value in payload["intraday"].items() if key.startswith("intraday_") or key in {"open_positions_by_market", "open_positions_by_desk", "open_positions_by_ticker", "distinct_markets_traded_today", "distinct_tickers_traded_today", "average_holding_minutes", "avg_holding_minutes", "average_r", "avg_net_r", "realized_pnl", "realized_intraday_pnl", "benchmark_excess", "costs_paid", "rejected_due_to_costs", "rejected_due_to_concentration", "reason_if_no_intraday_trades", "next_intraday_action"}})
        payload["copy_readiness"] = CopyReadinessSummaryService().summary(db)
        readiness_rows = [*(payload.get("candidates") or []), *(payload.get("open_positions") or [])]
        payload["copy_ready_open_candidates"] = [
            row for row in readiness_rows
            if row.get("copy_readiness_status") in {"COPY_READY_PAPER_ONLY", "COPY_READY_HIGH_CONFIDENCE"}
        ][:8]
        payload["not_copy_ready_open_candidates"] = [
            row for row in readiness_rows
            if row.get("copy_readiness_status") not in {"COPY_READY_PAPER_ONLY", "COPY_READY_HIGH_CONFIDENCE"}
        ][:8]
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
        scanner_rows = db.scalars(
            select(LiveForwardPaperTrade)
            .where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status.in_(["CANDIDATE", "WAITING_FOR_TRIGGER", "SKIPPED", "DATA_BLOCKED", "ERROR"]))
            .order_by(desc(LiveForwardPaperTrade.created_at))
            .limit(250)
        ).all()
        actionability_summary = self.actionability_summary(db, game)
        scanner_summary = paper_forward_scanner_snapshot_summary(scanner_rows)
        scanner_summary = {**scanner_summary, **latest_scanner_event_summary(db, scanner_summary)}
        lifecycle_mode = self.lifecycle_mode(actionability_summary)
        opened_today = int(db.scalar(select(func.count(LiveForwardPaperTrade.id)).where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status == "OPEN", func.date(LiveForwardPaperTrade.opened_at) == date.today())) or 0)
        closed_today = int(db.scalar(select(func.count(LiveForwardPaperTrade.id)).where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status.in_(["CLOSED", "EXPIRED", "INVALIDATED"]), func.date(LiveForwardPaperTrade.closed_at) == date.today())) or 0)
        latest_open_trades = db.scalars(
            select(LiveForwardPaperTrade)
            .where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status == "OPEN")
            .order_by(desc(LiveForwardPaperTrade.opened_at))
            .limit(8)
        ).all()
        latest_closed_trades = db.scalars(
            select(LiveForwardPaperTrade)
            .where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status.in_(["CLOSED", "EXPIRED", "INVALIDATED"]))
            .order_by(desc(LiveForwardPaperTrade.closed_at))
            .limit(8)
        ).all()
        payload.update(
            {
                "lifecycle_enabled": bool(settings.paper_forward_lifecycle_enabled),
                "readiness_status": payload.get("readiness"),
                "last_run_at": payload.get("last_worker_run"),
                "paper_forward_lifecycle_mode": lifecycle_mode,
                "lifecycle_mode": lifecycle_mode,
                "actionability_policy": ActionabilityPolicy().to_dict(),
                "actionability_summary": actionability_summary,
                "candidate_count": total_counts["candidate_count"],
                "waiting_for_trigger_count": total_counts["waiting_for_trigger_count"],
                "skipped_count": total_counts["skipped_count"],
                "open_count": total_counts["open_count"],
                "open_count_reason": paper_forward_open_count_reason(total_counts["open_count"], total_counts["candidate_count"], total_counts["waiting_for_trigger_count"]),
                "closed_count": total_counts["closed_count"],
                "closed_count_reason": paper_forward_closed_count_reason(
                    total_counts["closed_count"],
                    total_counts["open_count"],
                    total_counts["candidate_count"],
                    total_counts["waiting_for_trigger_count"],
                ),
                "expired_count": total_counts["expired_count"],
                "invalidated_count": total_counts["invalidated_count"],
                "data_blocked_count": total_counts["data_blocked_count"],
                "error_count": total_counts["error_count"],
                "opened_today": opened_today,
                "closed_today": closed_today,
                "latest_open_trades": serialize_paper_forward_trades(db, latest_open_trades, compact=True),
                "latest_closed_trades": serialize_paper_forward_trades(db, latest_closed_trades, compact=True),
                "latest_lifecycle_events": [serialize_live_event(row) for row in latest_events],
                "reason_if_no_open_trades": total_counts["open_count"] == 0 and paper_forward_open_count_reason(total_counts["open_count"], total_counts["candidate_count"], total_counts["waiting_for_trigger_count"]) or None,
                "reason_if_no_closed_trades": total_counts["closed_count"] == 0 and paper_forward_closed_count_reason(
                    total_counts["closed_count"],
                    total_counts["open_count"],
                    total_counts["candidate_count"],
                    total_counts["waiting_for_trigger_count"],
                ) or None,
                "next_lifecycle_action": (
                    "Enable PAPER_FORWARD_LIFECYCLE_ENABLED to activate paper-forward lifecycle." if not settings.paper_forward_lifecycle_enabled else
                    "Run /api/paper-forward/run-lifecycle after fresh market data and candidate creation." if total_counts["open_count"] == 0 else
                    "Continue monitoring open trades with /api/paper-forward/run-lifecycle as new market data arrives."
                ),
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
                **scanner_summary,
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

        geometry = self.entry_risk_geometry_status(trade, latest_price)
        actual_risk_per_share = safe_float(geometry.get("actual_risk"))
        if actual_risk_per_share > 0:
            risk_adjusted_size = safe_float(trade.risk_amount) / actual_risk_per_share
            frozen_size = safe_float(trade.position_size)
            trade.position_size = round(
                min(frozen_size, risk_adjusted_size) if frozen_size > 0 else risk_adjusted_size,
                6,
            )
            condition = {
                **condition,
                "risk_adjusted_position_size": trade.position_size,
                "actual_risk_per_share": actual_risk_per_share,
            }

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
        trade.expires_at = now + timedelta(days=self.expected_holding_days(trade))
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
        benchmark_price_at_open = price_on_or_before(db, trade.benchmark_ticker or game.benchmark_ticker, latest_date)
        plan = (trade.frozen_decision_payload or {}).get("trade_plan") or {}
        self.append_event_once(
            db,
            trade,
            "PAPER_TRADE_OPENED",
            "Paper-forward trade opened after the frozen entry condition was met.",
            payload={
                "opened_at": now.isoformat(),
                "open_price": latest_price,
                "quantity": trade.position_size,
                "notional_value": trade.notional_value,
                "stop_price": trade.stop_loss,
                "target_1": trade.target_1,
                "target_2": trade.target_2,
                "initial_risk": trade.expected_risk,
                "expected_holding_days": plan.get("expected_holding_days") or plan.get("expected_holding_period"),
                "benchmark_price_at_open": benchmark_price_at_open,
                "model_version_used": trade.model_version_used,
                "weights_used": trade.weights_used,
                "strategy_memory_used": trade.strategy_memory_used,
                "frozen_decision_payload": trade.frozen_decision_payload,
            },
            price_used=latest_price,
        )
        return serialize_paper_forward_trade(trade, compact=True)

    def expected_holding_days(self, trade: LiveForwardPaperTrade) -> int:
        plan = (trade.frozen_decision_payload or {}).get("trade_plan") or {}
        raw = plan.get("expected_holding_days") or plan.get("expected_holding_period")
        values: list[float] = []
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            values = [float(raw)]
        elif isinstance(raw, str):
            values = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", raw)]
        requested = max(values) if values else float(settings.paper_forward_max_holding_days)
        return max(1, min(int(settings.paper_forward_max_holding_days), int(math.ceil(requested))))

    def entry_window_status(self, trade: LiveForwardPaperTrade, observed_at: date | datetime) -> dict:
        """Reject an entry signal observed after its frozen decision horizon."""

        decision_at = trade.decision_timestamp or trade.created_at or datetime.utcnow()
        observed_on = observed_at.date() if isinstance(observed_at, datetime) else observed_at
        expires_on = decision_at.date() + timedelta(days=self.expected_holding_days(trade))
        valid = observed_on <= expires_on
        return {
            "valid": valid,
            "entry_window_expires_on": expires_on.isoformat(),
            "observed_on": observed_on.isoformat(),
            "explanation": (
                "The frozen entry window expired before confirmation; opening now would use a stale thesis."
                if not valid
                else "The latest observation remains inside the frozen entry window."
            ),
        }

    def ensure_trade_expiration(self, db: Session, trade: LiveForwardPaperTrade) -> datetime:
        if trade.expires_at is not None:
            return trade.expires_at
        base = trade.opened_at or trade.decision_timestamp or trade.created_at or datetime.utcnow()
        trade.expires_at = base + timedelta(days=self.expected_holding_days(trade))
        self.append_event_once(
            db,
            trade,
            "TIME_STOP_ASSIGNED",
            "A bounded paper-forward time stop was assigned from the frozen plan.",
            payload={
                "expires_at": trade.expires_at.isoformat(),
                "holding_days": self.expected_holding_days(trade),
                "backfilled": trade.opened_at is not None,
            },
        )
        return trade.expires_at

    def entry_condition_status(self, trade: LiveForwardPaperTrade, latest_price: float) -> dict:
        plan = (trade.frozen_decision_payload or {}).get("trade_plan") or {}
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
        entry_type = normalize_text(plan.get("entry_type") or plan.get("order_type")).upper()
        if not entry_type:
            if trigger_price:
                entry_type = "ABOVE_TRIGGER"
            elif limit_price:
                entry_type = "PULLBACK"
            else:
                entry_type = "MARKET"

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
        entry_price = safe_float(trade.entry_price)
        stop_loss = safe_float(trade.stop_loss)
        invalidation = safe_float(trade.invalidation_level)
        target_1 = safe_float(trade.target_1)
        target_2 = safe_float(trade.target_2)
        if stop_loss and (not entry_price or stop_loss < entry_price) and latest_price <= stop_loss:
            return "STOP_HIT"
        if invalidation and (not entry_price or invalidation < entry_price) and latest_price <= invalidation:
            return "INVALIDATION_HIT"
        if target_2 and (not entry_price or target_2 > entry_price) and latest_price >= target_2:
            return "TARGET_2_HIT"
        if target_1 and (not entry_price or target_1 > entry_price) and latest_price >= target_1:
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
        evidence_fingerprint=candidate_evidence_fingerprint(candidate),
    )
    return db.scalar(select(LiveForwardPaperTrade.id).where(LiveForwardPaperTrade.duplicate_key == duplicate_key).limit(1))


def stored_sniper_candidates(db: Session, *, limit: int) -> list[dict]:
    rows = db.execute(
        select(SniperScore, TradePlan, Asset)
        .join(TradePlan, TradePlan.sniper_score_id == SniperScore.id)
        .join(Asset, Asset.id == SniperScore.asset_id)
        .where(Asset.is_active.is_(True))
        .order_by(desc(SniperScore.created_at), desc(SniperScore.sniper_score), desc(TradePlan.confidence))
        .limit(max(1, int(limit)) * 4)
    ).all()
    seen: set[str] = set()
    output: list[dict] = []
    for score, plan, asset in rows:
        ticker = normalize_text(score.ticker or plan.ticker or asset.ticker).upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        output.append(
            {
                "ticker": ticker,
                "asset": {
                    "ticker": ticker,
                    "name": asset.name,
                    "asset_type": asset.asset_type,
                    "sector": asset.sector,
                    "industry": asset.industry,
                    "country": asset.country,
                    "exchange": asset.exchange,
                    "currency": asset.currency,
                },
                "setup": {
                    "setup_type": score.setup_type or plan.setup_type or "unknown_setup",
                    "historical_reliability": plan.historical_setup_reliability,
                },
                "actionability": score.actionability or plan.actionability,
                "sniper_score": safe_float(score.sniper_score),
                "confidence": safe_float(plan.confidence or score.confidence),
                "trade_plan": {
                    "entry_zone": plan.entry_zone,
                    "entry_trigger": plan.entry_trigger,
                    "confirmation_condition": plan.confirmation_condition,
                    "invalidation_level": plan.invalidation_level,
                    "stop_logic": plan.stop_logic,
                    "target_1": plan.target_1,
                    "target_2": plan.target_2,
                    "trailing_exit_logic": plan.trailing_exit_logic,
                    "partial_exit_logic": plan.partial_exit_logic,
                    "no_trade_conditions": plan.no_trade_conditions,
                    "expected_holding_period": plan.expected_holding_period,
                    "risk_reward_estimate": plan.risk_reward_estimate,
                    "confidence": plan.confidence,
                    "historical_setup_reliability": plan.historical_setup_reliability,
                    "timeframe": plan.timeframe,
                },
                "price_context": latest_price_context_for_asset(db, asset, data_quality_score=score.data_quality_score),
                "score_components": score.components,
                "explanation": score.explanation or "Stored Market Sniper evidence from prior background evaluation.",
                "scouting_source": "stored_sniper_trade_plan",
                "scouting_policy": "stored_evidence_first_no_page_render_recalculation",
                "persisted_ids": {"sniper_score_id": score.id, "trade_plan_id": plan.id},
            }
        )
        if len(output) >= limit:
            break
    return output


def latest_price_context_for_asset(db: Session, asset: Asset, *, data_quality_score: float | None = None) -> dict:
    latest = db.scalar(select(PriceHistory).where(PriceHistory.asset_id == asset.id).order_by(desc(PriceHistory.date)).limit(1))
    rows = int(db.scalar(select(func.count(PriceHistory.id)).where(PriceHistory.asset_id == asset.id)) or 0)
    return {
        "latest_price": safe_float(latest.close, None) if latest else None,
        "latest_date": latest.date.isoformat() if latest and latest.date else None,
        "latest_volume": safe_float(latest.volume, None) if latest else None,
        "rows": rows,
        "data_quality_score": safe_float(data_quality_score, 0.0),
    }


def broad_ohlcv_universe(db: Session, *, limit: int = 90, min_rows: int = 120) -> list[Asset]:
    row_count = func.count(PriceHistory.id)
    latest_date = func.max(PriceHistory.date)
    rows = db.execute(
        select(Asset, row_count.label("row_count"), latest_date.label("latest_price_date"))
        .join(PriceHistory, PriceHistory.asset_id == Asset.id)
        .where(Asset.is_active.is_(True))
        .group_by(Asset.id)
        .having(row_count >= max(30, int(min_rows)))
        .order_by(desc(latest_date), desc(row_count), Asset.ticker)
        .limit(max(1, int(limit)))
    ).all()
    return [asset for asset, _, _ in rows]


def classification_from_diagnosis(actionability_status: str) -> str:
    if actionability_status == "ACTIONABLE":
        return TRADE_CANDIDATE
    if actionability_status == "WAITING_FOR_TRIGGER":
        return WATCHLIST_CANDIDATE
    if actionability_status == "DATA_BLOCKED":
        return DATA_BLOCKED_CANDIDATE
    return BLOCKED_CANDIDATE


def paper_forward_scanner_snapshot_summary(rows: list[LiveForwardPaperTrade]) -> dict:
    classifications = [classification_from_trade(row) for row in rows]
    counts = {name: classifications.count(name) for name in [TRADE_CANDIDATE, WATCHLIST_CANDIDATE, BLOCKED_CANDIDATE, DATA_BLOCKED_CANDIDATE]}
    latest_run_at = max((row.created_at for row in rows if row.created_at), default=None)
    by_market: dict[str, dict[str, int]] = {}
    by_asset_class: set[str] = set()
    assets_by_market: dict[str, int] = {}
    for row in rows:
        payload = row.frozen_decision_payload or {}
        asset = payload.get("asset") if isinstance(payload, dict) else {}
        market = str((asset or {}).get("market") or "unknown")
        asset_class = str((asset or {}).get("asset_class") or row.asset_type or "unknown")
        classification = classification_from_trade(row)
        by_asset_class.add(asset_class)
        assets_by_market[market] = assets_by_market.get(market, 0) + 1
        by_market.setdefault(market, {TRADE_CANDIDATE: 0, WATCHLIST_CANDIDATE: 0, BLOCKED_CANDIDATE: 0, DATA_BLOCKED_CANDIDATE: 0})
        by_market[market][classification] += 1

    trade_rows = [row for row in rows if classification_from_trade(row) == TRADE_CANDIDATE]
    watch_rows = [row for row in rows if classification_from_trade(row) == WATCHLIST_CANDIDATE]
    blocked_rows = [row for row in rows if classification_from_trade(row) == BLOCKED_CANDIDATE]
    data_blocked_rows = [row for row in rows if classification_from_trade(row) == DATA_BLOCKED_CANDIDATE]
    skipped_markets = skipped_market_summary(rows)
    top_blockers = actionability_summary_blockers(rows)
    return {
        "scanner_last_run_at": latest_run_at.isoformat() if latest_run_at else None,
        "scanned_count": len(rows),
        "trade_candidate_count": counts[TRADE_CANDIDATE],
        "watchlist_candidate_count": counts[WATCHLIST_CANDIDATE],
        "blocked_candidate_count": counts[BLOCKED_CANDIDATE],
        "data_blocked_candidate_count": counts[DATA_BLOCKED_CANDIDATE],
        "latest_trade_candidates": [serialize_paper_forward_trade(row, compact=True) for row in trade_rows[:8]],
        "latest_watchlist_candidates": [serialize_paper_forward_trade(row, compact=True) for row in watch_rows[:8]],
        "latest_blocked_candidates": [serialize_paper_forward_trade(row, compact=True) for row in blocked_rows[:8]],
        "latest_data_blocked_candidates": [serialize_paper_forward_trade(row, compact=True) for row in data_blocked_rows[:8]],
        "blocker_breakdown": top_blockers,
        "best_trade_candidate": serialize_paper_forward_trade(trade_rows[0], compact=True) if trade_rows else None,
        "best_watchlist_candidate": serialize_paper_forward_trade(watch_rows[0], compact=True) if watch_rows else None,
        "best_cross_market_candidate": serialize_paper_forward_trade(rows[0], compact=True) if rows else None,
        "reason_if_no_trade_candidates": "" if trade_rows else no_trade_candidates_reason(top_blockers),
        "markets_scanned": sorted(assets_by_market),
        "asset_classes_scanned": sorted(by_asset_class),
        "assets_scanned_by_market": assets_by_market,
        "trade_candidates_by_market": {market: counts[TRADE_CANDIDATE] for market, counts in by_market.items() if counts[TRADE_CANDIDATE]},
        "watchlist_candidates_by_market": {market: counts[WATCHLIST_CANDIDATE] for market, counts in by_market.items() if counts[WATCHLIST_CANDIDATE]},
        "blocked_candidates_by_market": {market: counts[BLOCKED_CANDIDATE] for market, counts in by_market.items() if counts[BLOCKED_CANDIDATE]},
        "data_blocked_candidates_by_market": {market: counts[DATA_BLOCKED_CANDIDATE] for market, counts in by_market.items() if counts[DATA_BLOCKED_CANDIDATE]},
        "skipped_markets": skipped_markets,
        "reason_if_markets_were_skipped": "; ".join(f"{item['market']}: {item['reason']}" for item in skipped_markets),
        "next_possible_action": "Wait for entry triggers or enable lifecycle only after forward evidence is sufficient." if watch_rows else "Hydrate more market data or review scanner blockers.",
        "learning_acceleration_status": "no_recent_acceleration",
        "priority_markets": [],
        "priority_setups": [],
        "repeated_blockers": [],
        "missed_opportunity_targets": [],
        "enabled_market_desk_agents": [],
        "agents_run": [],
        "agents_skipped": [],
        "opportunities_by_agent": {},
        "best_opportunity_by_agent": {},
        "top_cross_market_opportunities": [],
        "quant_edge_summary": {},
        "rejected_no_edge_count": 0,
        "rejected_overfitting_count": 0,
        "rejected_insufficient_sample_count": 0,
        "diversification_summary": {},
        "repeated_ticker_warning": False,
        "reason_if_same_tickers_repeat": None,
    }


def latest_scanner_event_summary(db: Session, fallback_summary: dict) -> dict:
    row = db.scalar(select(LearningEvent).where(LearningEvent.event_type == "OPPORTUNITY_SCANNED").order_by(desc(LearningEvent.created_at)).limit(1))
    if row is None or not isinstance(row.payload, dict):
        return {}
    fallback_timestamp = fallback_summary.get("scanner_last_run_at")
    if fallback_timestamp and row.created_at and row.created_at.isoformat() <= str(fallback_timestamp):
        return {}
    payload = row.payload
    acceleration = payload.get("learning_acceleration") if isinstance(payload.get("learning_acceleration"), dict) else {}
    return {
        "scanner_last_run_at": row.created_at.isoformat() if row.created_at else payload.get("generated_at"),
        "scanned_count": payload.get("scanned_count", fallback_summary.get("scanned_count")),
        "trade_candidate_count": payload.get("trade_candidate_count", fallback_summary.get("trade_candidate_count")),
        "watchlist_candidate_count": payload.get("watchlist_candidate_count", fallback_summary.get("watchlist_candidate_count")),
        "blocked_candidate_count": payload.get("blocked_candidate_count", fallback_summary.get("blocked_candidate_count")),
        "data_blocked_candidate_count": payload.get("data_blocked_candidate_count", fallback_summary.get("data_blocked_candidate_count")),
        "blocker_breakdown": payload.get("top_blockers", fallback_summary.get("blocker_breakdown")),
        "best_trade_candidate": payload.get("best_trade_candidate", fallback_summary.get("best_trade_candidate")),
        "best_watchlist_candidate": payload.get("best_watchlist_candidate", fallback_summary.get("best_watchlist_candidate")),
        "best_cross_market_candidate": payload.get("best_cross_market_candidate", fallback_summary.get("best_cross_market_candidate")),
        "reason_if_no_trade_candidates": payload.get("reason_if_no_trade_candidates", fallback_summary.get("reason_if_no_trade_candidates")),
        "markets_scanned": payload.get("markets_scanned", fallback_summary.get("markets_scanned")),
        "asset_classes_scanned": payload.get("asset_classes_scanned", fallback_summary.get("asset_classes_scanned")),
        "assets_scanned_by_market": payload.get("assets_scanned_by_market", fallback_summary.get("assets_scanned_by_market")),
        "trade_candidates_by_market": payload.get("trade_candidates_by_market", fallback_summary.get("trade_candidates_by_market")),
        "watchlist_candidates_by_market": payload.get("watchlist_candidates_by_market", fallback_summary.get("watchlist_candidates_by_market")),
        "blocked_candidates_by_market": payload.get("blocked_candidates_by_market", fallback_summary.get("blocked_candidates_by_market")),
        "data_blocked_candidates_by_market": payload.get("data_blocked_candidates_by_market", fallback_summary.get("data_blocked_candidates_by_market")),
        "skipped_markets": payload.get("skipped_markets", fallback_summary.get("skipped_markets")),
        "reason_if_markets_were_skipped": payload.get("reason_if_markets_were_skipped", fallback_summary.get("reason_if_markets_were_skipped")),
        "next_possible_action": payload.get("next_possible_action", fallback_summary.get("next_possible_action")),
        "learning_acceleration_status": acceleration.get("status") or fallback_summary.get("learning_acceleration_status") or "no_recent_acceleration",
        "priority_markets": acceleration.get("priority_markets") or fallback_summary.get("priority_markets") or [],
        "priority_setups": acceleration.get("priority_setups") or fallback_summary.get("priority_setups") or [],
        "repeated_blockers": acceleration.get("repeated_blockers") or fallback_summary.get("repeated_blockers") or [],
        "missed_opportunity_targets": acceleration.get("missed_opportunity_targets") or fallback_summary.get("missed_opportunity_targets") or [],
        "enabled_market_desk_agents": payload.get("enabled_market_desk_agents", fallback_summary.get("enabled_market_desk_agents", [])),
        "agents_run": payload.get("agents_run", fallback_summary.get("agents_run", [])),
        "agents_skipped": payload.get("agents_skipped", fallback_summary.get("agents_skipped", [])),
        "opportunities_by_agent": payload.get("opportunities_by_agent", fallback_summary.get("opportunities_by_agent", {})),
        "best_opportunity_by_agent": payload.get("best_opportunity_by_agent", fallback_summary.get("best_opportunity_by_agent", {})),
        "top_cross_market_opportunities": payload.get("top_cross_market_opportunities", fallback_summary.get("top_cross_market_opportunities", [])),
        "quant_edge_summary": payload.get("quant_edge_summary", fallback_summary.get("quant_edge_summary", {})),
        "rejected_no_edge_count": payload.get("rejected_no_edge_count", fallback_summary.get("rejected_no_edge_count", 0)),
        "rejected_overfitting_count": payload.get("rejected_overfitting_count", fallback_summary.get("rejected_overfitting_count", 0)),
        "rejected_insufficient_sample_count": payload.get("rejected_insufficient_sample_count", fallback_summary.get("rejected_insufficient_sample_count", 0)),
        "diversification_summary": payload.get("diversification_summary", fallback_summary.get("diversification_summary", {})),
        "repeated_ticker_warning": payload.get("repeated_ticker_warning", fallback_summary.get("repeated_ticker_warning", False)),
        "reason_if_same_tickers_repeat": payload.get("reason_if_same_tickers_repeat", fallback_summary.get("reason_if_same_tickers_repeat")),
    }


def paper_forward_open_count_reason(open_count: int, candidate_count: int, waiting_for_trigger_count: int) -> str:
    if open_count > 0:
        return "Paper-forward has open positions currently being tracked."
    if waiting_for_trigger_count > 0:
        return "No paper-forward trades have opened yet because candidates are waiting for explicit entry triggers."
    if candidate_count > 0:
        return "No paper-forward trades have opened yet; candidates are frozen and lifecycle execution is not active unless explicitly enabled."
    return "No paper-forward trades have opened yet because no eligible candidates are stored."


def paper_forward_closed_count_reason(closed_count: int, open_count: int, candidate_count: int, waiting_for_trigger_count: int) -> str:
    if closed_count > 0:
        return "Closed paper-forward trades are available and can feed forward alpha evidence."
    if open_count > 0:
        return "No paper-forward trades have closed yet because open positions are still being monitored."
    if candidate_count > 0 or waiting_for_trigger_count > 0:
        return "No paper-forward trades have closed yet; candidates must first open and then reach stop, target, invalidation, or expiry."
    return "No paper-forward trades have closed yet because no paper-forward candidates have matured into positions."


def classification_from_trade(row: LiveForwardPaperTrade) -> str:
    payload = row.frozen_decision_payload or {}
    classification = payload.get("paper_forward_classification") if isinstance(payload, dict) else None
    if classification in {TRADE_CANDIDATE, WATCHLIST_CANDIDATE, BLOCKED_CANDIDATE, DATA_BLOCKED_CANDIDATE}:
        return classification
    if row.status == "CANDIDATE":
        return TRADE_CANDIDATE
    if row.status == "WAITING_FOR_TRIGGER":
        return WATCHLIST_CANDIDATE
    if row.status == "DATA_BLOCKED":
        return DATA_BLOCKED_CANDIDATE
    return BLOCKED_CANDIDATE


def waiting_candidate_can_mature(row: LiveForwardPaperTrade) -> bool:
    payload = row.frozen_decision_payload if isinstance(row.frozen_decision_payload, dict) else {}
    diagnosis = payload.get("actionability_diagnosis") if isinstance(payload.get("actionability_diagnosis"), dict) else {}
    scanner_original_status = str(diagnosis.get("scanner_original_status") or diagnosis.get("actionability_status") or "")
    plan = payload.get("trade_plan") if isinstance(payload.get("trade_plan"), dict) else {}
    entry_type = normalize_text(plan.get("entry_type") or plan.get("order_type")).upper()
    entry_zone = plan.get("entry_zone") if isinstance(plan.get("entry_zone"), dict) else {}
    has_numeric_trigger = first_positive_float(
        plan.get("trigger_price"),
        plan.get("entry_trigger_price"),
        plan.get("breakout_level"),
        plan.get("confirmation_price"),
        entry_zone.get("high"),
    ) is not None
    has_numeric_limit = first_positive_float(
        plan.get("limit_price"),
        plan.get("pullback_price"),
        entry_zone.get("low"),
    ) is not None
    explicit_condition = (
        entry_type in {"ABOVE_TRIGGER", "BREAKOUT", "BELOW_TRIGGER"} and has_numeric_trigger
    ) or (
        entry_type in {"LIMIT", "PULLBACK"} and has_numeric_limit
    ) or (not entry_type and (has_numeric_trigger or has_numeric_limit))
    return (
        row.status == "WAITING_FOR_TRIGGER"
        and scanner_original_status == "WAITING_FOR_TRIGGER"
        and bool(diagnosis.get("should_wait"))
        and explicit_condition
    )


def lifecycle_candidate_priority(row: LiveForwardPaperTrade) -> tuple[float, float, float, float]:
    payload = row.frozen_decision_payload if isinstance(row.frozen_decision_payload, dict) else {}
    scanner = payload.get("opportunity_scanner") if isinstance(payload.get("opportunity_scanner"), dict) else {}
    composite_score = safe_float(scanner.get("score"), safe_float(row.sniper_score))
    timestamp = row.decision_timestamp.timestamp() if row.decision_timestamp else 0.0
    return (
        0.0 if row.status == "CANDIDATE" else 1.0,
        -composite_score,
        -safe_float(row.sniper_score),
        -timestamp,
    )


def skipped_market_summary(rows: list[LiveForwardPaperTrade]) -> list[dict]:
    scanned = set()
    for row in rows:
        payload = row.frozen_decision_payload or {}
        asset = payload.get("asset") if isinstance(payload, dict) else {}
        scanned.add(str((asset or {}).get("market") or "unknown"))
    enabled = [item.strip().lower() for item in str(settings.paper_forward_enabled_markets).split(",") if item.strip()]
    return [{"market": market, "reason": "MARKET_DATA_UNAVAILABLE"} for market in enabled if market not in scanned]


def actionability_summary_blockers(rows: list[LiveForwardPaperTrade]) -> list[dict]:
    from app.services.trading_intelligence_lab import actionability_diagnosis_from_trade

    counts = {}
    for row in rows:
        diagnosis = actionability_diagnosis_from_trade(row)
        reason = diagnosis.get("rejection_reason") or "unknown"
        if diagnosis.get("actionability_status") == "ACTIONABLE":
            continue
        counts[reason] = counts.get(reason, 0) + 1
    return [{"reason": reason, "count": count} for reason, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:8]]


def no_trade_candidates_reason(blockers: list[dict]) -> str:
    if not blockers:
        return "No trade candidates created because no scannable opportunity rows are stored yet."
    return "No trade candidates created because " + ", ".join(f"{item['count']} {item['reason']}" for item in blockers[:5]) + "."


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
