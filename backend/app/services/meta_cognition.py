from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from statistics import mean, pstdev
import math
import time
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import (
    AlphaLossAttribution,
    AlphaRecoveryAction,
    CapitalPreservationAlpha,
    DashboardSnapshot,
    LearningFactorImportance,
    LearningFocusPriority,
    MetaCognitionEvent,
    MissedWinner,
    ReasoningNoiseFlag,
    TradingGame,
    TradingGameTrade,
)
from app.services.dashboard_snapshots import DashboardSnapshotService
from app.services.trade_transparency import safe_float


META_POLICY = (
    "Meta-Cognition is evidence-bound. It evaluates which BLUM reasoning factors deserve more trust, "
    "more sampling or lower influence from stored outcomes only. It does not self-modify source code, "
    "does not apply risky weight changes automatically and does not claim alpha without benchmark-relative evidence."
)

SNAPSHOT_TYPE = "meta_cognition_summary"
MIN_FACTOR_SAMPLE = 12

FACTOR_DEFINITIONS = [
    ("technical", "technical"),
    ("momentum", "momentum"),
    ("volume", "technical"),
    ("volatility", "risk"),
    ("sentiment", "sentiment"),
    ("narrative", "narrative"),
    ("fundamentals", "fundamental"),
    ("business_quality", "fundamental"),
    ("regime", "regime"),
    ("sector_rotation", "regime"),
    ("benchmark_relative_strength", "benchmark"),
    ("decision_superiority", "decision"),
    ("sniper_score", "execution"),
    ("entry_timing", "execution"),
    ("exit_timing", "execution"),
    ("no_trade_filter", "risk"),
    ("capital_allocation", "portfolio"),
    ("position_sizing", "portfolio"),
    ("portfolio_interaction", "portfolio"),
    ("alpha_recovery", "learning"),
    ("confidence_calibration", "learning"),
]


class LearningImportanceEngine:
    """Measures which BLUM reasoning factors create value, destroy value or add noise."""

    def latest(self, db: Session, limit: int = 120) -> dict:
        rows = db.scalars(select(LearningFactorImportance).order_by(desc(LearningFactorImportance.calculated_at)).limit(limit)).all()
        return {
            "status": "ready" if rows else "missing",
            "rows": [serialize_factor(row) for row in rows],
            "summary": summarize_factors(rows),
            "policy": META_POLICY,
        }

    def recalculate(self, db: Session, persist: bool = False) -> dict:
        game = latest_game(db)
        trades = latest_trades(db, game.id if game else None)
        alpha_loss = db.scalars(select(AlphaLossAttribution).order_by(desc(AlphaLossAttribution.created_at)).limit(200)).all()
        missed = db.scalars(select(MissedWinner).order_by(desc(MissedWinner.created_at)).limit(200)).all()
        preservation = db.scalars(select(CapitalPreservationAlpha).order_by(desc(CapitalPreservationAlpha.created_at)).limit(200)).all()
        actions = db.scalars(select(AlphaRecoveryAction).order_by(desc(AlphaRecoveryAction.created_at)).limit(120)).all()
        payloads = [
            self.factor_payload(name, family, trades, alpha_loss, missed, preservation, actions)
            for name, family in FACTOR_DEFINITIONS
        ]
        if persist:
            for payload in payloads:
                db.add(
                    LearningFactorImportance(
                        factor_name=payload["factor_name"],
                        factor_family=payload["factor_family"],
                        horizon=payload.get("horizon"),
                        regime=payload.get("regime"),
                        sector=payload.get("sector"),
                        sample_size=payload["sample_size"],
                        alpha_contribution=payload["alpha_contribution"],
                        alpha_loss_contribution=payload["alpha_loss_contribution"],
                        missed_winner_contribution=payload["missed_winner_contribution"],
                        capital_preservation_contribution=payload["capital_preservation_contribution"],
                        noise_score=payload["noise_score"],
                        overvaluation_score=payload["overvaluation_score"],
                        undervaluation_score=payload["undervaluation_score"],
                        reliability_score=payload["reliability_score"],
                        evidence_quality=payload["evidence_quality"],
                        confidence=payload["confidence"],
                        recommended_weight_action=payload["recommended_weight_action"],
                        explanation=payload["explanation"],
                        warnings_json=payload["warnings"],
                    )
                )
            db.commit()
        return {
            "status": "ready" if payloads else "insufficient_evidence",
            "rows": payloads,
            "summary": summarize_factor_payloads(payloads),
            "policy": META_POLICY,
        }

    def factor_payload(
        self,
        factor_name: str,
        factor_family: str,
        trades: list[TradingGameTrade],
        alpha_loss: list[AlphaLossAttribution],
        missed: list[MissedWinner],
        preservation: list[CapitalPreservationAlpha],
        actions: list[AlphaRecoveryAction],
    ) -> dict:
        matched_trades = [trade for trade in trades if trade_matches_factor(trade, factor_name)]
        matched_alpha_loss = [row for row in alpha_loss if attribution_matches_factor(row, factor_name)]
        matched_missed = [row for row in missed if missed_matches_factor(row, factor_name)]
        matched_preservation = [row for row in preservation if preservation_matches_factor(row, factor_name)]
        matched_actions = [row for row in actions if action_matches_factor(row, factor_name)]

        positive_alpha = sum(max(0.0, safe_float(row.excess_return_vs_benchmark)) for row in matched_trades)
        negative_alpha = sum(abs(min(0.0, safe_float(row.excess_return_vs_benchmark))) for row in matched_trades)
        alpha_loss_contribution = negative_alpha + sum(abs(safe_float(row.contribution_value)) for row in matched_alpha_loss)
        missed_contribution = sum(max(0.0, safe_float(row.benchmark_relative_return)) for row in matched_missed)
        capital_preservation = sum(max(0.0, safe_float(row.capital_preserved)) for row in matched_preservation)
        r_values = [safe_float(row.realized_r_multiple) for row in matched_trades if row.realized_r_multiple is not None]
        sample_size = len(matched_trades) + len(matched_alpha_loss) + len(matched_missed) + len(matched_preservation) + len(matched_actions)
        variance = pstdev(r_values) if len(r_values) >= 2 else 0.0
        sign_reversals = min(100.0, 100.0 * min(positive_alpha, negative_alpha) / max(positive_alpha + negative_alpha, 1.0))
        tiny_sample_penalty = max(0.0, 60.0 - sample_size * 5.0) if sample_size < MIN_FACTOR_SAMPLE else 0.0
        noise_score = clamp(tiny_sample_penalty + min(30.0, variance * 8.0) + sign_reversals * 0.35)
        evidence_quality = clamp(min(100.0, sample_size / 50.0 * 100.0) - (20.0 if not matched_trades else 0.0))
        gross_value = positive_alpha + capital_preservation
        gross_harm = alpha_loss_contribution + missed_contribution
        reliability = clamp(50.0 + gross_value * 2.0 - gross_harm * 2.0 - noise_score * 0.35)
        overvaluation = clamp(alpha_loss_contribution * 3.0 + noise_score * 0.45 + max(0.0, len(matched_actions) - 2) * 5.0)
        undervaluation = clamp((positive_alpha + missed_contribution + capital_preservation) * 2.0 - alpha_loss_contribution)
        confidence = clamp(evidence_quality * 0.65 + min(100.0, sample_size * 4.0) * 0.35)
        recommended = recommended_action(sample_size, reliability, noise_score, overvaluation, undervaluation, matched_alpha_loss, matched_missed)
        warnings = factor_warnings(sample_size, noise_score, matched_alpha_loss, matched_missed)
        return {
            "factor_name": factor_name,
            "factor_family": factor_family,
            "horizon": "multi_horizon",
            "regime": most_common([row.market_regime_at_entry for row in matched_trades]),
            "sector": most_common([row.sector for row in matched_trades]),
            "sample_size": sample_size,
            "alpha_contribution": round(positive_alpha, 4),
            "alpha_loss_contribution": round(alpha_loss_contribution, 4),
            "missed_winner_contribution": round(missed_contribution, 4),
            "capital_preservation_contribution": round(capital_preservation, 4),
            "noise_score": round(noise_score, 2),
            "overvaluation_score": round(overvaluation, 2),
            "undervaluation_score": round(undervaluation, 2),
            "reliability_score": round(reliability, 2),
            "evidence_quality": round(evidence_quality, 2),
            "confidence": round(confidence, 2),
            "recommended_weight_action": recommended,
            "explanation": factor_explanation(factor_name, sample_size, reliability, noise_score, recommended, positive_alpha, alpha_loss_contribution, missed_contribution, capital_preservation),
            "warnings": warnings,
            "evidence": {
                "trade_ids": [row.id for row in matched_trades[:20]],
                "alpha_loss_ids": [row.id for row in matched_alpha_loss[:20]],
                "missed_winner_ids": [row.id for row in matched_missed[:20]],
                "capital_preservation_ids": [row.id for row in matched_preservation[:20]],
                "action_ids": [row.id for row in matched_actions[:20]],
            },
        }


class CapitalPreservationAlphaEngine:
    """Measures value created by waiting, avoiding or rejecting weak setups."""

    def latest(self, db: Session, limit: int = 120) -> dict:
        rows = db.scalars(select(CapitalPreservationAlpha).order_by(desc(CapitalPreservationAlpha.created_at)).limit(limit)).all()
        return {"status": "ready" if rows else "missing", "rows": [serialize_preservation(row) for row in rows], "summary": summarize_preservation(rows), "policy": META_POLICY}

    def evaluate(self, db: Session, persist: bool = False, limit: int = 300) -> dict:
        game = latest_game(db)
        trades = latest_trades(db, game.id if game else None, limit=limit)
        candidates = [row for row in trades if row.decision_state in {"avoid", "wait_for_trigger"} or row.missed_entry]
        payloads = [self.payload_for_trade(row) for row in candidates]
        if persist:
            for payload in payloads:
                if preservation_exists(db, payload.get("no_trade_decision_id")):
                    continue
                db.add(
                    CapitalPreservationAlpha(
                        no_trade_decision_id=payload.get("no_trade_decision_id"),
                        ticker=payload["ticker"],
                        decision_date=payload.get("decision_date"),
                        setup_type=payload.get("setup_type"),
                        no_trade_reason=payload["no_trade_reason"],
                        horizon=payload.get("horizon"),
                        future_return=payload.get("future_return"),
                        benchmark_return=payload.get("benchmark_return"),
                        avoided_loss=payload["avoided_loss"],
                        missed_gain=payload["missed_gain"],
                        capital_preserved=payload["capital_preserved"],
                        opportunity_cost=payload["opportunity_cost"],
                        was_correct=payload.get("was_correct"),
                        quality_score=payload["quality_score"],
                        explanation=payload["explanation"],
                    )
                )
            db.commit()
        return {"status": "ready" if payloads else "insufficient_evidence", "rows": payloads, "summary": summarize_preservation_payloads(payloads), "policy": META_POLICY}

    def payload_for_trade(self, trade: TradingGameTrade) -> dict:
        future_return = first_not_none(trade.pnl_percent, trade.excess_return_vs_benchmark)
        benchmark_return = first_not_none(trade.benchmark_return_same_period, trade.benchmark_return)
        excess = safe_float(trade.excess_return_vs_benchmark)
        avoided_loss = abs(excess) if excess < 0 else 0.0
        missed_gain = excess if excess > 0 else 0.0
        notional = safe_float(trade.notional_value) or safe_float(trade.capital_before) * max(0.01, safe_float(trade.risk_percent) / 100.0)
        capital_preserved = avoided_loss * notional / 100.0 if avoided_loss > 0 else 0.0
        opportunity_cost = missed_gain * notional / 100.0 if missed_gain > 0 else 0.0
        was_correct = avoided_loss > 0 if avoided_loss or missed_gain else None
        quality = clamp((70.0 if was_correct else 35.0 if was_correct is False else 45.0) + min(20.0, abs(excess)))
        reason = trade.outcome_label or trade.decision_state or "no_trade_decision"
        return {
            "no_trade_decision_id": trade.id,
            "ticker": trade.ticker,
            "decision_date": trade.entry_date,
            "setup_type": trade.setup_type,
            "no_trade_reason": reason,
            "horizon": trade.timeframe or "daily",
            "future_return": future_return,
            "benchmark_return": benchmark_return,
            "avoided_loss": round(avoided_loss, 4),
            "missed_gain": round(missed_gain, 4),
            "capital_preserved": round(capital_preserved, 4),
            "opportunity_cost": round(opportunity_cost, 4),
            "was_correct": was_correct,
            "quality_score": round(quality, 2),
            "explanation": (
                f"No-trade preserved capital because {trade.ticker} underperformed benchmark after avoidance."
                if was_correct
                else f"No-trade missed opportunity because {trade.ticker} outperformed after avoidance."
                if was_correct is False
                else f"No-trade evidence for {trade.ticker} is inconclusive."
            ),
        }


class MetaCognitionEngine:
    """Evaluates whether BLUM's learning process is improving future decision quality."""

    def events(self, db: Session, limit: int = 120) -> dict:
        rows = db.scalars(select(MetaCognitionEvent).order_by(desc(MetaCognitionEvent.created_at)).limit(limit)).all()
        return {"status": "ready" if rows else "missing", "rows": [serialize_event(row) for row in rows], "summary": summarize_events(rows), "policy": META_POLICY}

    def summary(self, db: Session) -> dict:
        snapshot = DashboardSnapshotService().latest(db, SNAPSHOT_TYPE)
        return {
            "status": snapshot.get("status"),
            "snapshot": snapshot,
            "factor_importance": LearningImportanceEngine().latest(db, limit=24),
            "capital_preservation": CapitalPreservationAlphaEngine().latest(db, limit=24),
            "learning_focus": LearningFocusOptimizer().latest(db, limit=24),
            "noise": ReasoningNoiseDetector().latest(db, limit=24),
            "events": self.events(db, limit=24),
            "conclusion": meta_conclusion(db),
            "policy": META_POLICY,
        }

    def evaluate(self, db: Session, persist: bool = False) -> dict:
        actions = db.scalars(select(AlphaRecoveryAction).order_by(desc(AlphaRecoveryAction.created_at)).limit(120)).all()
        payloads = [self.event_for_action(row) for row in actions]
        if persist:
            for payload in payloads:
                if event_exists(db, payload["source_event_type"], payload.get("source_event_id")):
                    continue
                db.add(
                    MetaCognitionEvent(
                        source_event_type=payload["source_event_type"],
                        source_event_id=payload.get("source_event_id"),
                        evaluated_module=payload["evaluated_module"],
                        evaluated_action=payload["evaluated_action"],
                        before_metric=payload.get("before_metric"),
                        after_metric=payload.get("after_metric"),
                        delta=payload.get("delta"),
                        sample_size=payload["sample_size"],
                        benchmark_context=payload.get("benchmark_context", {}),
                        live_or_historical=payload["live_or_historical"],
                        improvement_observed=payload.get("improvement_observed"),
                        degradation_observed=payload.get("degradation_observed"),
                        overfitting_risk=payload["overfitting_risk"],
                        confidence=payload["confidence"],
                        conclusion=payload["conclusion"],
                        recommended_next_step=payload["recommended_next_step"],
                        notes_json=payload.get("notes", {}),
                    )
                )
            db.commit()
        return {"status": "ready" if payloads else "insufficient_evidence", "rows": payloads, "summary": summarize_event_payloads(payloads), "policy": META_POLICY}

    def recalculate_all(self, db: Session) -> dict:
        started = time.perf_counter()
        preservation = CapitalPreservationAlphaEngine().evaluate(db, persist=True)
        factors = LearningImportanceEngine().recalculate(db, persist=True)
        noise = ReasoningNoiseDetector().detect(db, persist=True)
        focus = LearningFocusOptimizer().generate(db, persist=True)
        events = self.evaluate(db, persist=True)
        conclusion = meta_conclusion(db)
        summary = {
            "status": "ready",
            "generated_at": datetime.utcnow().isoformat(),
            "top_alpha_factor": first_item((factors.get("summary") or {}).get("top_alpha_creators")),
            "top_alpha_destroyer": first_item((factors.get("summary") or {}).get("top_alpha_destroyers")),
            "noisiest_factor": first_item((factors.get("summary") or {}).get("noisiest_factors")),
            "most_undervalued_factor": first_item((factors.get("summary") or {}).get("undervalued_factors")),
            "strongest_capital_preservation_rule": first_item((preservation.get("summary") or {}).get("top_preservers")),
            "weakest_current_module": first_item((noise.get("summary") or {}).get("highest_severity")),
            "next_learning_focus": first_item((focus.get("rows") or [])),
            "meta_cognition_conclusion": conclusion,
            "factor_importance_summary": factors.get("summary"),
            "capital_preservation_summary": preservation.get("summary"),
            "noise_summary": noise.get("summary"),
            "learning_focus_summary": focus.get("summary"),
            "events_summary": events.get("summary"),
            "policy": META_POLICY,
        }
        summary = json_safe(summary)
        DashboardSnapshotService().write(
            db,
            SNAPSHOT_TYPE,
            summary,
            source_modules={"meta_cognition": "explicit_recalculate"},
            ttl_seconds=900,
            warnings=conclusion.get("warnings", []),
            computation_duration_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        return summary

    def event_for_action(self, action: AlphaRecoveryAction) -> dict:
        before = action.before_metric
        after = action.after_metric
        delta = (after - before) if before is not None and after is not None else None
        sample_size = int((action.evidence_json or {}).get("sample_size") or (action.evidence_json or {}).get("missed_winner_count") or 0)
        improvement = delta is not None and delta > 0
        degradation = delta is not None and delta < 0
        overfit = 75.0 if sample_size < MIN_FACTOR_SAMPLE else 35.0 if sample_size < 50 else 15.0
        confidence = clamp(min(100.0, sample_size * 4.0) - overfit * 0.25)
        conclusion = (
            "Learning action improved the measured metric."
            if improvement
            else "Learning action degraded the measured metric."
            if degradation
            else "Learning action has no completed before/after validation yet."
        )
        return {
            "source_event_type": "alpha_recovery_action",
            "source_event_id": action.id,
            "evaluated_module": action.affected_module,
            "evaluated_action": action.recommended_action,
            "before_metric": before,
            "after_metric": after,
            "delta": delta,
            "sample_size": sample_size,
            "benchmark_context": {"benchmark_name": action.benchmark_name, "validation_status": action.validation_status},
            "live_or_historical": "historical",
            "improvement_observed": improvement if delta is not None else None,
            "degradation_observed": degradation if delta is not None else None,
            "overfitting_risk": round(overfit, 2),
            "confidence": round(confidence, 2),
            "conclusion": conclusion,
            "recommended_next_step": "Keep testing out-of-sample before applying weight changes." if delta is None else "Retain only if benchmark-relative improvement persists with larger samples.",
            "notes": action.evidence_json or {},
        }


class LearningFocusOptimizer:
    """Chooses where future Learning Loop cycles should focus."""

    def latest(self, db: Session, limit: int = 80) -> dict:
        rows = db.scalars(
            select(LearningFocusPriority)
            .where(LearningFocusPriority.status.in_(["proposed", "active"]))
            .order_by(desc(LearningFocusPriority.expected_learning_value), desc(LearningFocusPriority.created_at))
            .limit(limit)
        ).all()
        return {"status": "ready" if rows else "missing", "rows": [serialize_focus(row) for row in rows], "summary": summarize_focus(rows), "policy": META_POLICY}

    def generate(self, db: Session, persist: bool = False) -> dict:
        factors = db.scalars(select(LearningFactorImportance).order_by(desc(LearningFactorImportance.calculated_at)).limit(160)).all()
        alpha_loss = db.scalars(select(AlphaLossAttribution).order_by(desc(AlphaLossAttribution.created_at)).limit(160)).all()
        actions = db.scalars(select(AlphaRecoveryAction).order_by(desc(AlphaRecoveryAction.created_at)).limit(80)).all()
        preservation = db.scalars(select(CapitalPreservationAlpha).order_by(desc(CapitalPreservationAlpha.created_at)).limit(120)).all()
        payloads: list[dict] = []
        for row in factors:
            if row.sample_size < MIN_FACTOR_SAMPLE or row.noise_score > 65 or row.alpha_loss_contribution > row.alpha_contribution:
                payloads.append(focus_payload_from_factor(row))
        for row in alpha_loss:
            if row.category not in {"outperformance_no_alpha_loss", "insufficient_attribution_evidence"}:
                payloads.append(focus_payload_from_alpha_loss(row))
        for row in actions:
            if row.status in {"proposed", "testing"}:
                payloads.append(focus_payload_from_action(row))
        missed_no_trades = [row for row in preservation if row.missed_gain > row.avoided_loss]
        for row in missed_no_trades[:20]:
            payloads.append(focus_payload_from_preservation(row))
        payloads = dedupe_payloads(payloads, ("priority_type", "target"))[:120]
        if persist:
            for payload in payloads:
                if focus_exists(db, payload):
                    continue
                db.add(
                    LearningFocusPriority(
                        priority_type=payload["priority_type"],
                        target=payload["target"],
                        reason=payload["reason"],
                        expected_learning_value=payload["expected_learning_value"],
                        urgency=payload["urgency"],
                        sample_gap=payload["sample_gap"],
                        linked_alpha_loss_id=payload.get("linked_alpha_loss_id"),
                        linked_factor_importance_id=payload.get("linked_factor_importance_id"),
                        linked_recovery_action_id=payload.get("linked_recovery_action_id"),
                        status=payload.get("status", "proposed"),
                        notes_json=payload.get("notes", {}),
                    )
                )
            db.commit()
        return {"status": "ready" if payloads else "insufficient_evidence", "rows": payloads, "summary": summarize_focus_payloads(payloads), "policy": META_POLICY}


class ReasoningNoiseDetector:
    """Detects factor or rule evidence that may be noisy or overfit."""

    def latest(self, db: Session, limit: int = 80) -> dict:
        rows = db.scalars(select(ReasoningNoiseFlag).order_by(desc(ReasoningNoiseFlag.created_at)).limit(limit)).all()
        return {"status": "ready" if rows else "missing", "rows": [serialize_noise(row) for row in rows], "summary": summarize_noise(rows), "policy": META_POLICY}

    def detect(self, db: Session, persist: bool = False) -> dict:
        factors = db.scalars(select(LearningFactorImportance).order_by(desc(LearningFactorImportance.calculated_at)).limit(160)).all()
        payloads: list[dict] = []
        for row in factors:
            if row.sample_size < MIN_FACTOR_SAMPLE and abs(row.alpha_contribution - row.alpha_loss_contribution) > 5:
                payloads.append(noise_payload(row, "tiny_sample_effect", "high" if row.sample_size < 5 else "medium", "Freeze factor influence until more samples exist."))
            if row.noise_score > 70:
                payloads.append(noise_payload(row, "unstable_factor_contribution", "high", "Require independent confirmation before trusting this factor."))
            if row.overvaluation_score > 70 and row.reliability_score < 45:
                payloads.append(noise_payload(row, "overvalued_factor", "high", "Decrease or freeze weight after out-of-sample validation."))
            if row.confidence < 35 and row.recommended_weight_action in {"increase_weight", "decrease_weight"}:
                payloads.append(noise_payload(row, "false_confidence_risk", "medium", "Block weight action because confidence is too low."))
        payloads = dedupe_payloads(payloads, ("factor_name", "noise_type"))
        if persist:
            for payload in payloads:
                if noise_exists(db, payload):
                    continue
                db.add(
                    ReasoningNoiseFlag(
                        factor_name=payload["factor_name"],
                        module_name=payload["module_name"],
                        noise_type=payload["noise_type"],
                        sample_size=payload["sample_size"],
                        evidence=payload.get("evidence", {}),
                        severity=payload["severity"],
                        recommended_action=payload["recommended_action"],
                        status=payload.get("status", "open"),
                        explanation=payload["explanation"],
                    )
                )
            db.commit()
        return {"status": "ready" if payloads else "no_noise_detected", "rows": payloads, "summary": summarize_noise_payloads(payloads), "policy": META_POLICY}


def trade_matches_factor(trade: TradingGameTrade, factor: str) -> bool:
    setup = (trade.setup_type or "").lower()
    outcome = (trade.outcome_label or "").lower()
    decision = (trade.decision_state or "").lower()
    payload = trade.payload or {}
    if factor == "technical":
        return any(key in setup for key in ["breakout", "pullback", "reversal", "trend", "mean_reversion"])
    if factor == "momentum":
        return "momentum" in setup or safe_float(trade.realized_r_multiple) > 1
    if factor == "volume":
        return "volume" in str(payload).lower() or "breakout" in setup
    if factor == "volatility":
        return "volatility" in setup or trade.max_adverse_excursion is not None
    if factor == "sentiment":
        return "sentiment" in str(payload).lower()
    if factor == "narrative":
        return "narrative" in setup or "narrative" in str(payload).lower()
    if factor == "fundamentals":
        return "earnings" in setup or "fundamental" in str(payload).lower()
    if factor == "business_quality":
        return "business_quality" in str(payload).lower() or "quality" in setup
    if factor == "regime":
        return bool(trade.market_regime_at_entry)
    if factor == "sector_rotation":
        return "rotation" in setup or bool(trade.sector)
    if factor == "benchmark_relative_strength":
        return trade.excess_return_vs_benchmark is not None
    if factor == "decision_superiority":
        return trade.opportunity_score_at_entry is not None or trade.decision_state in {"active_setup", "avoid", "wait_for_trigger"}
    if factor == "sniper_score":
        return trade.sniper_score_at_entry is not None or trade.actionability_state_at_entry is not None
    if factor == "entry_timing":
        return trade.entry_date is not None or trade.missed_entry
    if factor == "exit_timing":
        return trade.exit_date is not None or trade.exit_reason is not None or outcome in {"time_exit", "trailing_exit", "stopped_out"}
    if factor == "no_trade_filter":
        return decision in {"avoid", "wait_for_trigger"} or trade.missed_entry
    if factor == "capital_allocation":
        return trade.notional_value is not None or trade.risk_percent is not None
    if factor == "position_sizing":
        return trade.risk_percent is not None or trade.position_size is not None
    if factor == "portfolio_interaction":
        return bool(trade.sector)
    if factor == "alpha_recovery":
        return trade.missed_entry or safe_float(trade.excess_return_vs_benchmark) < 0
    if factor == "confidence_calibration":
        return trade.confidence_at_entry is not None
    return False


def attribution_matches_factor(row: AlphaLossAttribution, factor: str) -> bool:
    category = (row.category or "").lower()
    if factor == "entry_timing":
        return category in {"missed_entry", "late_entry"}
    if factor == "exit_timing":
        return category in {"poor_exit", "premature_exit"}
    if factor == "capital_allocation":
        return category in {"weak_capital_allocation", "excessive_cash"}
    if factor == "position_sizing":
        return category in {"weak_capital_allocation", "concentration_error"}
    if factor == "decision_superiority":
        return category in {"wrong_asset_selection", "weak_sector_selection"}
    if factor == "sector_rotation":
        return category in {"weak_sector_selection", "sector_rotation"}
    if factor == "alpha_recovery":
        return True
    if factor == "no_trade_filter":
        return category == "missed_entry"
    return factor in category


def missed_matches_factor(row: MissedWinner, factor: str) -> bool:
    text = f"{row.rejection_reason} {row.blocked_rule} {row.suggested_learning_action} {row.evidence_json}".lower()
    if factor == "entry_timing":
        return "entry" in text or "trigger" in text
    if factor == "no_trade_filter":
        return "reject" in text or "not_selected" in text or "blocked" in text
    if factor == "decision_superiority":
        return True
    if factor == "alpha_recovery":
        return True
    if factor == "sector_rotation":
        return "sector" in text
    if factor == "momentum":
        return "momentum" in text or "breakout" in text
    return factor in text


def preservation_matches_factor(row: CapitalPreservationAlpha, factor: str) -> bool:
    text = f"{row.no_trade_reason} {row.explanation}".lower()
    if factor == "no_trade_filter":
        return True
    if factor == "capital_allocation":
        return row.capital_preserved > 0
    if factor == "entry_timing":
        return row.missed_gain > 0
    return factor in text


def action_matches_factor(row: AlphaRecoveryAction, factor: str) -> bool:
    text = f"{row.action_type} {row.detected_problem} {row.recommended_action} {row.affected_module}".lower()
    return factor in text or (factor == "alpha_recovery" and "recover" in text)


def recommended_action(sample: int, reliability: float, noise: float, overvaluation: float, undervaluation: float, alpha_loss: list, missed: list) -> str:
    if sample < MIN_FACTOR_SAMPLE:
        return "freeze_until_more_samples"
    if noise > 75:
        return "require_confirmation"
    if overvaluation > 70 and reliability < 45:
        return "decrease_weight"
    if undervaluation > 70 and reliability > 55:
        return "increase_weight"
    if alpha_loss and missed:
        return "regime_specific_only"
    if reliability > 60 and noise < 45:
        return "keep_weight"
    return "freeze_until_more_samples"


def factor_warnings(sample: int, noise: float, alpha_loss: list, missed: list) -> list[str]:
    warnings = []
    if sample < MIN_FACTOR_SAMPLE:
        warnings.append("insufficient_sample_size")
    if noise > 70:
        warnings.append("high_noise_score")
    if alpha_loss:
        warnings.append("linked_to_alpha_loss")
    if missed:
        warnings.append("linked_to_missed_winners")
    return warnings


def factor_explanation(factor: str, sample: int, reliability: float, noise: float, action: str, alpha: float, loss: float, missed: float, preserved: float) -> str:
    return (
        f"{factor} has sample {sample}, reliability {reliability:.1f}, noise {noise:.1f}. "
        f"Measured alpha {alpha:.2f}, alpha loss {loss:.2f}, missed-winner drag {missed:.2f}, capital preservation {preserved:.2f}. "
        f"Recommended action: {action}."
    )


def focus_payload_from_factor(row: LearningFactorImportance) -> dict:
    sample_gap = max(0, MIN_FACTOR_SAMPLE - row.sample_size)
    return {
        "priority_type": "factor_importance_focus",
        "target": row.factor_name,
        "reason": f"{row.factor_name} needs more study: reliability {row.reliability_score:.1f}, noise {row.noise_score:.1f}, action {row.recommended_weight_action}.",
        "expected_learning_value": round(max(row.alpha_loss_contribution, row.missed_winner_contribution, row.noise_score / 10.0), 4),
        "urgency": "high" if row.noise_score > 70 or row.alpha_loss_contribution > row.alpha_contribution else "medium",
        "sample_gap": sample_gap,
        "linked_factor_importance_id": row.id,
        "status": "proposed",
        "notes": {"recommended_weight_action": row.recommended_weight_action, "confidence": row.confidence},
    }


def focus_payload_from_alpha_loss(row: AlphaLossAttribution) -> dict:
    target = row.ticker or row.setup_type or row.category
    return {
        "priority_type": "alpha_loss_replay",
        "target": str(target),
        "reason": f"Replay alpha-loss category {row.category} with contribution {row.contribution_value:.2f}.",
        "expected_learning_value": round(abs(safe_float(row.contribution_value)), 4),
        "urgency": "high" if abs(safe_float(row.contribution_value)) > 5 else "medium",
        "sample_gap": max(0, MIN_FACTOR_SAMPLE - row.sample_size),
        "linked_alpha_loss_id": row.id,
        "status": "proposed",
        "notes": {"category": row.category, "benchmark_name": row.benchmark_name},
    }


def focus_payload_from_action(row: AlphaRecoveryAction) -> dict:
    return {
        "priority_type": "recovery_action_validation",
        "target": row.action_type,
        "reason": row.detected_problem,
        "expected_learning_value": abs(safe_float(row.before_metric)) if row.before_metric is not None else 5.0,
        "urgency": row.priority,
        "sample_gap": max(0, 50 - int((row.evidence_json or {}).get("sample_size") or 0)),
        "linked_recovery_action_id": row.id,
        "status": "proposed",
        "notes": {"affected_module": row.affected_module, "validation_status": row.validation_status},
    }


def focus_payload_from_preservation(row: CapitalPreservationAlpha) -> dict:
    return {
        "priority_type": "capital_preservation_replay",
        "target": row.ticker,
        "reason": f"No-trade decision missed gain {row.missed_gain:.2f}; replay avoidance logic.",
        "expected_learning_value": round(row.missed_gain, 4),
        "urgency": "high" if row.missed_gain > 5 else "medium",
        "sample_gap": MIN_FACTOR_SAMPLE,
        "status": "proposed",
        "notes": {"no_trade_decision_id": row.no_trade_decision_id, "setup_type": row.setup_type},
    }


def noise_payload(row: LearningFactorImportance, noise_type: str, severity: str, action: str) -> dict:
    return {
        "factor_name": row.factor_name,
        "module_name": row.factor_family,
        "noise_type": noise_type,
        "sample_size": row.sample_size,
        "evidence": {
            "factor_importance_id": row.id,
            "noise_score": row.noise_score,
            "reliability_score": row.reliability_score,
            "confidence": row.confidence,
            "alpha_contribution": row.alpha_contribution,
            "alpha_loss_contribution": row.alpha_loss_contribution,
        },
        "severity": severity,
        "recommended_action": action,
        "status": "open",
        "explanation": f"{row.factor_name} flagged as {noise_type}: sample {row.sample_size}, noise {row.noise_score:.1f}, confidence {row.confidence:.1f}.",
    }


def latest_game(db: Session) -> TradingGame | None:
    return db.scalar(select(TradingGame).order_by(desc(TradingGame.updated_at)).limit(1))


def latest_trades(db: Session, game_id: int | None, limit: int = 1000) -> list[TradingGameTrade]:
    query = select(TradingGameTrade).order_by(desc(TradingGameTrade.created_at)).limit(limit)
    if game_id:
        query = query.where(TradingGameTrade.game_id == game_id)
    return db.scalars(query).all()


def preservation_exists(db: Session, trade_id: int | None) -> bool:
    return bool(trade_id and db.scalar(select(CapitalPreservationAlpha.id).where(CapitalPreservationAlpha.no_trade_decision_id == trade_id).limit(1)))


def event_exists(db: Session, source_type: str, source_id: int | None) -> bool:
    if source_id is None:
        return False
    return bool(db.scalar(select(MetaCognitionEvent.id).where(MetaCognitionEvent.source_event_type == source_type, MetaCognitionEvent.source_event_id == source_id).limit(1)))


def focus_exists(db: Session, payload: dict) -> bool:
    return bool(db.scalar(select(LearningFocusPriority.id).where(LearningFocusPriority.priority_type == payload["priority_type"], LearningFocusPriority.target == payload["target"], LearningFocusPriority.status.in_(["proposed", "active"])).limit(1)))


def noise_exists(db: Session, payload: dict) -> bool:
    return bool(db.scalar(select(ReasoningNoiseFlag.id).where(ReasoningNoiseFlag.factor_name == payload["factor_name"], ReasoningNoiseFlag.noise_type == payload["noise_type"], ReasoningNoiseFlag.status == "open").limit(1)))


def meta_conclusion(db: Session) -> dict:
    factors = db.scalars(select(LearningFactorImportance).order_by(desc(LearningFactorImportance.calculated_at)).limit(80)).all()
    focus = db.scalars(select(LearningFocusPriority).where(LearningFocusPriority.status.in_(["proposed", "active"])).order_by(desc(LearningFocusPriority.expected_learning_value)).limit(10)).all()
    noise = db.scalars(select(ReasoningNoiseFlag).where(ReasoningNoiseFlag.status == "open").order_by(desc(ReasoningNoiseFlag.created_at)).limit(20)).all()
    warnings = []
    if not factors:
        warnings.append("missing_factor_importance")
        return {"summary": "Insufficient evidence. Meta-Cognition needs factor importance, no-trade outcomes and learning action evaluation.", "warnings": warnings}
    top_alpha = max(factors, key=lambda row: row.alpha_contribution, default=None)
    top_loss = max(factors, key=lambda row: row.alpha_loss_contribution, default=None)
    next_focus = focus[0] if focus else None
    if any(row.sample_size < MIN_FACTOR_SAMPLE for row in factors[:10]):
        warnings.append("some_top_factors_have_low_sample_size")
    if noise:
        warnings.append("open_reasoning_noise_flags")
    return {
        "summary": (
            f"Top alpha factor: {top_alpha.factor_name if top_alpha else 'n/a'}. "
            f"Top alpha-loss factor: {top_loss.factor_name if top_loss else 'n/a'}. "
            f"Next learning focus: {next_focus.target if next_focus else 'no active focus yet'}."
        ),
        "warnings": warnings,
        "top_alpha_factor": serialize_factor(top_alpha) if top_alpha else None,
        "top_alpha_loss_factor": serialize_factor(top_loss) if top_loss else None,
        "next_focus": serialize_focus(next_focus) if next_focus else None,
    }


def summarize_factors(rows: list[LearningFactorImportance]) -> dict:
    return summarize_factor_payloads([serialize_factor(row, raw=True) for row in rows])


def summarize_factor_payloads(rows: list[dict]) -> dict:
    return {
        "top_alpha_creators": top_rows(rows, "alpha_contribution"),
        "top_alpha_destroyers": top_rows(rows, "alpha_loss_contribution"),
        "noisiest_factors": top_rows(rows, "noise_score"),
        "undervalued_factors": top_rows(rows, "undervaluation_score"),
        "overvalued_factors": top_rows(rows, "overvaluation_score"),
    }


def summarize_preservation(rows: list[CapitalPreservationAlpha]) -> dict:
    return summarize_preservation_payloads([serialize_preservation(row, raw=True) for row in rows])


def summarize_preservation_payloads(rows: list[dict]) -> dict:
    return {
        "rows": len(rows),
        "capital_preserved": round(sum(safe_float(row.get("capital_preserved")) for row in rows), 4),
        "opportunity_cost": round(sum(safe_float(row.get("opportunity_cost")) for row in rows), 4),
        "correct_rate": ratio(sum(1 for row in rows if row.get("was_correct") is True), sum(1 for row in rows if row.get("was_correct") is not None)),
        "top_preservers": top_rows(rows, "capital_preserved"),
        "top_missed_no_trades": top_rows(rows, "opportunity_cost"),
    }


def summarize_events(rows: list[MetaCognitionEvent]) -> dict:
    return summarize_event_payloads([serialize_event(row, raw=True) for row in rows])


def summarize_event_payloads(rows: list[dict]) -> dict:
    evaluated = [row for row in rows if row.get("delta") is not None]
    return {
        "events": len(rows),
        "evaluated_events": len(evaluated),
        "learning_action_success_rate": ratio(sum(1 for row in evaluated if row.get("improvement_observed")), len(evaluated)),
        "degradation_rate": ratio(sum(1 for row in evaluated if row.get("degradation_observed")), len(evaluated)),
        "average_delta": safe_mean([row.get("delta") for row in evaluated]),
    }


def summarize_focus(rows: list[LearningFocusPriority]) -> dict:
    return summarize_focus_payloads([serialize_focus(row, raw=True) for row in rows])


def summarize_focus_payloads(rows: list[dict]) -> dict:
    return {
        "priorities": len(rows),
        "by_type": dict(Counter(row.get("priority_type") for row in rows)),
        "highest_value": top_rows(rows, "expected_learning_value"),
    }


def summarize_noise(rows: list[ReasoningNoiseFlag]) -> dict:
    return summarize_noise_payloads([serialize_noise(row, raw=True) for row in rows])


def summarize_noise_payloads(rows: list[dict]) -> dict:
    severity_rank = {"high": 3, "medium": 2, "low": 1}
    sorted_rows = sorted(rows, key=lambda row: (severity_rank.get(str(row.get("severity")), 0), row.get("sample_size") or 0), reverse=True)
    return {"flags": len(rows), "by_type": dict(Counter(row.get("noise_type") for row in rows)), "highest_severity": sorted_rows[:5]}


def serialize_factor(row: LearningFactorImportance | None, raw: bool = False) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "calculated_at": row.calculated_at if raw else iso(row.calculated_at),
        "factor_name": row.factor_name,
        "factor_family": row.factor_family,
        "horizon": row.horizon,
        "regime": row.regime,
        "sector": row.sector,
        "sample_size": row.sample_size,
        "alpha_contribution": row.alpha_contribution,
        "alpha_loss_contribution": row.alpha_loss_contribution,
        "missed_winner_contribution": row.missed_winner_contribution,
        "capital_preservation_contribution": row.capital_preservation_contribution,
        "noise_score": row.noise_score,
        "overvaluation_score": row.overvaluation_score,
        "undervaluation_score": row.undervaluation_score,
        "reliability_score": row.reliability_score,
        "evidence_quality": row.evidence_quality,
        "confidence": row.confidence,
        "recommended_weight_action": row.recommended_weight_action,
        "explanation": row.explanation,
        "warnings": row.warnings_json or [],
    }


def serialize_preservation(row: CapitalPreservationAlpha, raw: bool = False) -> dict:
    return {
        "id": row.id,
        "no_trade_decision_id": row.no_trade_decision_id,
        "ticker": row.ticker,
        "decision_date": row.decision_date if raw else iso(row.decision_date),
        "setup_type": row.setup_type,
        "no_trade_reason": row.no_trade_reason,
        "horizon": row.horizon,
        "future_return": row.future_return,
        "benchmark_return": row.benchmark_return,
        "avoided_loss": row.avoided_loss,
        "missed_gain": row.missed_gain,
        "capital_preserved": row.capital_preserved,
        "opportunity_cost": row.opportunity_cost,
        "was_correct": row.was_correct,
        "quality_score": row.quality_score,
        "explanation": row.explanation,
        "created_at": row.created_at if raw else iso(row.created_at),
    }


def serialize_event(row: MetaCognitionEvent, raw: bool = False) -> dict:
    return {
        "id": row.id,
        "created_at": row.created_at if raw else iso(row.created_at),
        "source_event_type": row.source_event_type,
        "source_event_id": row.source_event_id,
        "evaluated_module": row.evaluated_module,
        "evaluated_action": row.evaluated_action,
        "before_metric": row.before_metric,
        "after_metric": row.after_metric,
        "delta": row.delta,
        "sample_size": row.sample_size,
        "benchmark_context": row.benchmark_context or {},
        "live_or_historical": row.live_or_historical,
        "improvement_observed": row.improvement_observed,
        "degradation_observed": row.degradation_observed,
        "overfitting_risk": row.overfitting_risk,
        "confidence": row.confidence,
        "conclusion": row.conclusion,
        "recommended_next_step": row.recommended_next_step,
        "notes": row.notes_json or {},
    }


def serialize_focus(row: LearningFocusPriority | None, raw: bool = False) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "created_at": row.created_at if raw else iso(row.created_at),
        "priority_type": row.priority_type,
        "target": row.target,
        "reason": row.reason,
        "expected_learning_value": row.expected_learning_value,
        "urgency": row.urgency,
        "sample_gap": row.sample_gap,
        "linked_alpha_loss_id": row.linked_alpha_loss_id,
        "linked_factor_importance_id": row.linked_factor_importance_id,
        "linked_recovery_action_id": row.linked_recovery_action_id,
        "status": row.status,
        "notes": row.notes_json or {},
    }


def serialize_noise(row: ReasoningNoiseFlag, raw: bool = False) -> dict:
    return {
        "id": row.id,
        "created_at": row.created_at if raw else iso(row.created_at),
        "factor_name": row.factor_name,
        "module_name": row.module_name,
        "noise_type": row.noise_type,
        "sample_size": row.sample_size,
        "evidence": row.evidence or {},
        "severity": row.severity,
        "recommended_action": row.recommended_action,
        "status": row.status,
        "explanation": row.explanation,
    }


def top_rows(rows: list[dict], key: str, limit: int = 5) -> list[dict]:
    return [row for row in sorted(rows, key=lambda item: safe_float(item.get(key)), reverse=True)[:limit] if safe_float(row.get(key)) != 0]


def first_item(value: Any) -> Any:
    if isinstance(value, list) and value:
        return value[0]
    return value


def first_not_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def ratio(num: int | float, den: int | float) -> float | None:
    return round(float(num) / float(den), 4) if den else None


def safe_mean(values: list[Any]) -> float | None:
    cleaned = [safe_float(value) for value in values if value is not None and math.isfinite(safe_float(value))]
    return round(mean(cleaned), 4) if cleaned else None


def most_common(values: list[Any]) -> str | None:
    cleaned = [str(value) for value in values if value]
    return Counter(cleaned).most_common(1)[0][0] if cleaned else None


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def dedupe_payloads(rows: list[dict], key_fields: tuple[str, ...]) -> list[dict]:
    seen: set[tuple[Any, ...]] = set()
    output = []
    for row in rows:
        key = tuple(row.get(field) for field in key_fields)
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output


def iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
