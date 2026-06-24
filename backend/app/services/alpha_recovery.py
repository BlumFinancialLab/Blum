from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
from statistics import mean
import time
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import (
    AlphaLossAttribution,
    AlphaRecoveryAction,
    BenchmarkMethodologyValidation,
    CapitalAllocationSnapshot,
    DashboardSnapshot,
    DecisionUniverseSnapshot,
    LearningBenchmarkComparison,
    MissedWinner,
    TradingGame,
    TradingGameTrade,
)
from app.services.dashboard_snapshots import DashboardSnapshotService
from app.services.trade_transparency import safe_float


ALPHA_RECOVERY_POLICY = (
    "Alpha Recovery is evidence attribution only. It diagnoses benchmark-relative underperformance, "
    "missed winners and recoverable process weaknesses from stored BLUM data. It does not claim alpha, "
    "does not fabricate missing evidence and does not change source code or trading rules by itself."
)

MIN_VALID_BENCHMARK_SAMPLE = 12
SNAPSHOT_TYPE = "alpha_recovery_summary"


class BenchmarkMethodologyValidator:
    """Validates benchmark comparisons before BLUM learns from them."""

    def latest(self, db: Session, limit: int = 40) -> dict:
        rows = db.scalars(
            select(BenchmarkMethodologyValidation)
            .order_by(desc(BenchmarkMethodologyValidation.created_at))
            .limit(limit)
        ).all()
        return {"status": "ready" if rows else "missing", "rows": [serialize_validation(row) for row in rows], "policy": ALPHA_RECOVERY_POLICY}

    def validate_latest(self, db: Session, benchmark_name: str | None = None, persist: bool = False) -> dict:
        comparisons = latest_benchmark_comparisons(db, benchmark_name)
        validations = [self.validate_row(row) for row in comparisons]
        if persist and validations:
            for payload in validations:
                db.add(
                    BenchmarkMethodologyValidation(
                        benchmark_comparison_id=payload.get("benchmark_comparison_id"),
                        benchmark_name=payload["benchmark_name"],
                        mode=payload["mode"],
                        period_start=payload.get("period_start"),
                        period_end=payload.get("period_end"),
                        methodology_valid=payload["methodology_valid"],
                        confidence=payload["confidence"],
                        corrected_excess_return=payload.get("corrected_excess_return"),
                        warnings_json=payload["warnings"],
                        validation_checks_json=payload["checks"],
                        explanation=payload["explanation"],
                    )
                )
            db.commit()
        return {
            "status": "ready" if validations else "missing",
            "rows": [json_safe(payload) for payload in validations],
            "policy": ALPHA_RECOVERY_POLICY,
        }

    def validate_row(self, row: LearningBenchmarkComparison) -> dict:
        warnings: list[str] = []
        checks: dict[str, bool] = {}

        checks["has_period_start"] = row.period_start is not None
        checks["has_period_end"] = row.period_end is not None
        checks["has_returns"] = row.blum_return is not None and row.benchmark_return is not None
        checks["sample_size_sufficient"] = int(row.sample_size or 0) >= MIN_VALID_BENCHMARK_SAMPLE
        checks["mode_consistent"] = bool(row.mode)
        checks["horizon_consistent"] = bool(row.period_start and row.period_end and row.period_start < row.period_end)
        checks["confidence_not_empty"] = bool(row.statistical_confidence)

        if not checks["has_period_start"] or not checks["has_period_end"]:
            warnings.append("benchmark_period_missing")
        if row.period_start and row.period_end and row.period_start >= row.period_end:
            warnings.append("benchmark_period_invalid")
        if not checks["has_returns"]:
            warnings.append("benchmark_returns_missing")
        if not checks["sample_size_sufficient"]:
            warnings.append("insufficient_sample_size")
        if row.result_label == "insufficient_sample":
            warnings.append("comparison_marked_insufficient")
        if row.benchmark_name in {"random_asset_selection_proxy", "random_entry_exit_proxy"}:
            warnings.append("baseline_proxy_not_external_market_benchmark")

        corrected_excess = None
        if row.blum_return is not None and row.benchmark_return is not None:
            corrected_excess = float(row.blum_return) - float(row.benchmark_return)
            if row.excess_return is not None and abs(corrected_excess - float(row.excess_return)) > 1e-6:
                warnings.append("stored_excess_return_mismatch_corrected")
        elif row.excess_return is not None:
            corrected_excess = float(row.excess_return)

        core_checks = ["has_period_start", "has_period_end", "has_returns", "horizon_consistent", "sample_size_sufficient"]
        valid = all(checks[item] for item in core_checks)
        confidence = 100.0 * sum(1 for value in checks.values() if value) / max(1, len(checks))
        if warnings:
            confidence = max(0.0, confidence - min(30.0, len(warnings) * 5.0))

        explanation = (
            f"{row.benchmark_name} methodology valid for learning."
            if valid
            else f"{row.benchmark_name} methodology is not valid enough for alpha-loss learning."
        )
        if warnings:
            explanation += f" Warnings: {', '.join(warnings)}."

        return {
            "benchmark_comparison_id": row.id,
            "benchmark_name": row.benchmark_name,
            "mode": row.mode,
            "period_start": row.period_start,
            "period_end": row.period_end,
            "methodology_valid": valid,
            "confidence": round(confidence, 2),
            "corrected_excess_return": corrected_excess,
            "warnings": warnings,
            "checks": checks,
            "explanation": explanation,
        }


class AlphaLossAttributionEngine:
    """Decomposes benchmark-relative alpha loss into measurable causes."""

    def latest(self, db: Session, benchmark_name: str | None = None, limit: int = 120) -> dict:
        query = select(AlphaLossAttribution).order_by(desc(AlphaLossAttribution.created_at)).limit(limit)
        if benchmark_name:
            query = query.where(AlphaLossAttribution.benchmark_name == benchmark_name.upper())
        rows = db.scalars(query).all()
        return {
            "status": "ready" if rows else "missing",
            "rows": [serialize_attribution(row) for row in rows],
            "summary": summarize_attributions(rows),
            "policy": ALPHA_RECOVERY_POLICY,
        }

    def calculate(self, db: Session, benchmark_name: str | None = None, persist: bool = False) -> dict:
        validations = latest_validations(db, benchmark_name)
        if not validations:
            return {
                "status": "blocked",
                "reason": "No stored valid benchmark methodology rows. Run benchmark methodology validation first.",
                "rows": [],
                "policy": ALPHA_RECOVERY_POLICY,
            }

        game = latest_game(db)
        trades = latest_trades(db, game.id if game else None)
        capital_snapshot = db.scalar(select(CapitalAllocationSnapshot).order_by(desc(CapitalAllocationSnapshot.calculated_at)).limit(1))
        payloads: list[dict] = []
        for validation in validations:
            if not validation.methodology_valid:
                continue
            payloads.extend(self._attribute_for_validation(validation, trades, capital_snapshot))

        if persist and payloads:
            for payload in payloads:
                db.add(
                    AlphaLossAttribution(
                        methodology_validation_id=payload.get("methodology_validation_id"),
                        benchmark_name=payload["benchmark_name"],
                        mode=payload["mode"],
                        period_start=payload.get("period_start"),
                        period_end=payload.get("period_end"),
                        total_alpha_loss=payload["total_alpha_loss"],
                        category=payload["category"],
                        ticker=payload.get("ticker"),
                        setup_type=payload.get("setup_type"),
                        sector=payload.get("sector"),
                        engine_name=payload.get("engine_name"),
                        capital_allocation_bucket=payload.get("capital_allocation_bucket"),
                        contribution_value=payload["contribution_value"],
                        contribution_percent=payload.get("contribution_percent"),
                        sample_size=payload.get("sample_size", 0),
                        confidence=payload.get("confidence", 0.0),
                        evidence_json=payload.get("evidence", {}),
                        explanation=payload.get("explanation", ""),
                    )
                )
            db.commit()
        return {
            "status": "ready" if payloads else "insufficient_evidence",
            "rows": [json_safe(payload) for payload in payloads],
            "summary": summarize_payload_attributions(payloads),
            "policy": ALPHA_RECOVERY_POLICY,
        }

    def _attribute_for_validation(
        self,
        validation: BenchmarkMethodologyValidation,
        trades: list[TradingGameTrade],
        capital_snapshot: CapitalAllocationSnapshot | None,
    ) -> list[dict]:
        benchmark_excess = safe_float(validation.corrected_excess_return)
        if benchmark_excess >= 0:
            return [self._payload(validation, "outperformance_no_alpha_loss", 0.0, [], "BLUM is not underperforming this benchmark on the validated comparison.")]

        total_alpha_loss = abs(benchmark_excess)
        rows: list[dict] = []
        active = [trade for trade in trades if trade.decision_state not in {"avoid", "wait_for_trigger"}]

        missed = [trade for trade in trades if trade.missed_entry and safe_float(trade.excess_return_vs_benchmark) > 0]
        if missed:
            rows.append(self._scoped_trade_payload(validation, "missed_entry", missed, total_alpha_loss))

        wrong_selection = [trade for trade in active if safe_float(trade.excess_return_vs_benchmark) < 0]
        if wrong_selection:
            rows.append(self._scoped_trade_payload(validation, "wrong_asset_selection", wrong_selection, total_alpha_loss))

        premature = [
            trade for trade in active
            if trade.max_favorable_excursion is not None
            and trade.realized_r_multiple is not None
            and safe_float(trade.max_favorable_excursion) - safe_float(trade.realized_r_multiple) >= 1.0
        ]
        if premature:
            rows.append(self._scoped_trade_payload(validation, "premature_exit", premature, total_alpha_loss, use_r_gap=True))

        weak_allocation = [
            trade for trade in active
            if safe_float(trade.excess_return_vs_benchmark) > 0 and safe_float(trade.risk_percent) < 0.75
        ]
        if weak_allocation:
            rows.append(self._scoped_trade_payload(validation, "weak_capital_allocation", weak_allocation, total_alpha_loss, allocation_bucket="underallocated_winners"))

        poor_exit = [trade for trade in active if safe_float(trade.net_pnl_eur if trade.net_pnl_eur is not None else trade.realized_pl) < 0 and not trade.stop_hit]
        if poor_exit:
            rows.append(self._scoped_trade_payload(validation, "poor_exit", poor_exit, total_alpha_loss))

        if capital_snapshot and safe_float(capital_snapshot.cash_reserve_percent) > 35 and total_alpha_loss > 0:
            contribution = total_alpha_loss * min(1.0, safe_float(capital_snapshot.cash_reserve_percent) / 100.0)
            rows.append(
                self._payload(
                    validation,
                    "excessive_cash",
                    contribution,
                    [],
                    "Cash reserve was high during benchmark underperformance; this is measurable cash drag, not a claim that full deployment was safe.",
                    capital_allocation_bucket="cash_reserve",
                    evidence={
                        "cash_reserve_percent": capital_snapshot.cash_reserve_percent,
                        "allocation_quality_score": capital_snapshot.allocation_quality_score,
                        "snapshot_id": capital_snapshot.id,
                    },
                )
            )

        if not rows:
            rows.append(
                self._payload(
                    validation,
                    "insufficient_attribution_evidence",
                    0.0,
                    [],
                    "Benchmark underperformance exists, but stored trade-level evidence is insufficient to attribute the cause.",
                )
            )
        return normalize_contribution_percent(rows, total_alpha_loss)

    def _scoped_trade_payload(
        self,
        validation: BenchmarkMethodologyValidation,
        category: str,
        trades: list[TradingGameTrade],
        total_alpha_loss: float,
        *,
        use_r_gap: bool = False,
        allocation_bucket: str | None = None,
    ) -> dict:
        if use_r_gap:
            contribution = sum(max(0.0, safe_float(row.max_favorable_excursion) - safe_float(row.realized_r_multiple)) for row in trades)
        else:
            contribution = sum(abs(safe_float(row.excess_return_vs_benchmark)) for row in trades)
        contribution = min(max(contribution, 0.0), max(total_alpha_loss, contribution))
        common_ticker = most_common([row.ticker for row in trades])
        common_setup = most_common([row.setup_type for row in trades])
        common_sector = most_common([row.sector or "unknown" for row in trades])
        confidence = min(95.0, 40.0 + len(trades) * 6.0)
        evidence = {
            "trade_ids": [row.id for row in trades[:20]],
            "tickers": dict(Counter(row.ticker for row in trades).most_common(10)),
            "setups": dict(Counter(row.setup_type for row in trades).most_common(10)),
            "total_trade_count": len(trades),
            "total_excess_return_vs_benchmark": round(sum(safe_float(row.excess_return_vs_benchmark) for row in trades), 4),
            "average_r_multiple": safe_mean([row.realized_r_multiple for row in trades]),
            "average_risk_percent": safe_mean([row.risk_percent for row in trades]),
        }
        explanation = alpha_category_explanation(category, len(trades), common_ticker, common_setup)
        return self._payload(
            validation,
            category,
            contribution,
            trades,
            explanation,
            ticker=common_ticker,
            setup_type=common_setup,
            sector=common_sector,
            capital_allocation_bucket=allocation_bucket,
            confidence=confidence,
            evidence=evidence,
        )

    def _payload(
        self,
        validation: BenchmarkMethodologyValidation,
        category: str,
        contribution: float,
        trades: list[TradingGameTrade],
        explanation: str,
        *,
        ticker: str | None = None,
        setup_type: str | None = None,
        sector: str | None = None,
        engine_name: str | None = None,
        capital_allocation_bucket: str | None = None,
        confidence: float | None = None,
        evidence: dict | None = None,
    ) -> dict:
        return {
            "methodology_validation_id": validation.id,
            "benchmark_name": validation.benchmark_name,
            "mode": validation.mode,
            "period_start": validation.period_start,
            "period_end": validation.period_end,
            "total_alpha_loss": abs(safe_float(validation.corrected_excess_return)) if safe_float(validation.corrected_excess_return) < 0 else 0.0,
            "category": category,
            "ticker": ticker,
            "setup_type": setup_type,
            "sector": sector,
            "engine_name": engine_name,
            "capital_allocation_bucket": capital_allocation_bucket,
            "contribution_value": round(contribution, 4),
            "contribution_percent": None,
            "sample_size": len(trades),
            "confidence": round(confidence if confidence is not None else min(90.0, 35.0 + len(trades) * 5.0), 2),
            "evidence": evidence or {},
            "explanation": explanation,
        }


class MissedWinnersEngine:
    """Finds ignored or underweighted opportunities that later outperformed."""

    def latest(self, db: Session, limit: int = 80) -> dict:
        rows = db.scalars(select(MissedWinner).order_by(desc(MissedWinner.created_at)).limit(limit)).all()
        return {"status": "ready" if rows else "missing", "rows": [serialize_missed_winner(row) for row in rows], "policy": ALPHA_RECOVERY_POLICY}

    def detect(self, db: Session, persist: bool = False, limit: int = 80) -> dict:
        payloads = self._from_trades(db, limit) + self._from_decision_snapshots(db, limit)
        payloads = dedupe_payloads(payloads, key_fields=("ticker", "decision_date", "source_trade_id", "source_snapshot_id"))[:limit]
        if persist and payloads:
            for payload in payloads:
                if missed_winner_exists(db, payload):
                    continue
                db.add(
                    MissedWinner(
                        ticker=payload["ticker"],
                        decision_date=payload.get("decision_date"),
                        benchmark_name=payload.get("benchmark_name", "SPY"),
                        future_return=payload.get("future_return"),
                        benchmark_relative_return=payload.get("benchmark_relative_return"),
                        blum_rank_at_decision=payload.get("blum_rank_at_decision"),
                        rejection_reason=payload.get("rejection_reason", ""),
                        confidence_at_decision=payload.get("confidence_at_decision"),
                        blocked_rule=payload.get("blocked_rule"),
                        missed_signals_json=payload.get("missed_signals", []),
                        suggested_learning_action=payload.get("suggested_learning_action", ""),
                        source_snapshot_id=payload.get("source_snapshot_id"),
                        source_trade_id=payload.get("source_trade_id"),
                        evidence_json=payload.get("evidence", {}),
                    )
                )
            db.commit()
        return {
            "status": "ready" if payloads else "insufficient_evidence",
            "rows": [json_safe(payload) for payload in payloads],
            "policy": ALPHA_RECOVERY_POLICY,
        }

    def _from_trades(self, db: Session, limit: int) -> list[dict]:
        game = latest_game(db)
        rows = latest_trades(db, game.id if game else None, limit=limit * 3)
        output = []
        for trade in rows:
            excess = safe_float(trade.excess_return_vs_benchmark)
            if not trade.missed_entry or excess <= 0:
                continue
            output.append(
                {
                    "ticker": trade.ticker,
                    "decision_date": trade.entry_date,
                    "benchmark_name": trade.benchmark_ticker or "SPY",
                    "future_return": trade.pnl_percent,
                    "benchmark_relative_return": trade.excess_return_vs_benchmark,
                    "blum_rank_at_decision": None,
                    "rejection_reason": trade.outcome_label or "missed_entry",
                    "confidence_at_decision": trade.confidence_at_entry,
                    "blocked_rule": "entry_condition_not_triggered",
                    "missed_signals": compact_trade_signals(trade),
                    "suggested_learning_action": "Replay this missed entry in alpha_loss_replay mode and test earlier confirmation or pullback-retest logic.",
                    "source_trade_id": trade.id,
                    "source_snapshot_id": None,
                    "evidence": {
                        "trade_id": trade.id,
                        "setup_type": trade.setup_type,
                        "sector": trade.sector,
                        "excess_return_vs_benchmark": trade.excess_return_vs_benchmark,
                    },
                }
            )
        return output

    def _from_decision_snapshots(self, db: Session, limit: int) -> list[dict]:
        snapshots = db.scalars(select(DecisionUniverseSnapshot).order_by(desc(DecisionUniverseSnapshot.timestamp)).limit(limit)).all()
        output: list[dict] = []
        for snapshot in snapshots:
            selected = (snapshot.selected_asset or "").upper()
            for candidate in extract_candidates(snapshot.candidates_json):
                ticker = str(candidate.get("ticker") or candidate.get("symbol") or "").upper()
                if not ticker or ticker == selected:
                    continue
                future_return = first_float(candidate, "future_return", "forward_return", "realized_return", "return_30d")
                relative_return = first_float(candidate, "benchmark_relative_return", "excess_return", "excess_return_vs_benchmark")
                if relative_return is None and future_return is not None:
                    relative_return = future_return - safe_float((snapshot.benchmark_snapshot or {}).get("benchmark_return"))
                if relative_return is None or relative_return <= 0:
                    continue
                output.append(
                    {
                        "ticker": ticker,
                        "decision_date": snapshot.timestamp.date() if snapshot.timestamp else None,
                        "benchmark_name": str((snapshot.benchmark_snapshot or {}).get("benchmark") or "SPY"),
                        "future_return": future_return,
                        "benchmark_relative_return": relative_return,
                        "blum_rank_at_decision": int(candidate.get("rank")) if str(candidate.get("rank", "")).isdigit() else None,
                        "rejection_reason": str(candidate.get("rejection_reason") or candidate.get("decision_state") or "not_selected"),
                        "confidence_at_decision": first_float(candidate, "confidence", "score", "conviction"),
                        "blocked_rule": candidate.get("blocked_rule"),
                        "missed_signals": candidate.get("signals") if isinstance(candidate.get("signals"), list) else [],
                        "suggested_learning_action": "Increase opportunity recall replay for rejected winners in the same regime and sector.",
                        "source_snapshot_id": snapshot.id,
                        "source_trade_id": None,
                        "evidence": {
                            "snapshot_id": snapshot.id,
                            "selected_asset": selected,
                            "market_regime": snapshot.market_regime,
                            "selected_rank": snapshot.selected_rank,
                            "candidate": candidate,
                        },
                    }
                )
        return output


class AlphaRecoveryActionEngine:
    """Converts measured alpha-loss causes into reversible recovery experiments."""

    def latest(self, db: Session, limit: int = 80) -> dict:
        rows = db.scalars(select(AlphaRecoveryAction).order_by(desc(AlphaRecoveryAction.created_at)).limit(limit)).all()
        return {"status": "ready" if rows else "missing", "rows": [serialize_action(row) for row in rows], "policy": ALPHA_RECOVERY_POLICY}

    def generate(self, db: Session, persist: bool = False) -> dict:
        attributions = db.scalars(select(AlphaLossAttribution).order_by(desc(AlphaLossAttribution.created_at)).limit(120)).all()
        missed = db.scalars(select(MissedWinner).order_by(desc(MissedWinner.created_at)).limit(120)).all()
        payloads = self._actions_from_evidence(attributions, missed)
        if persist and payloads:
            for payload in payloads:
                if action_exists(db, payload):
                    continue
                db.add(
                    AlphaRecoveryAction(
                        action_type=payload["action_type"],
                        detected_problem=payload["detected_problem"],
                        recommended_action=payload["recommended_action"],
                        affected_module=payload["affected_module"],
                        benchmark_name=payload.get("benchmark_name"),
                        expected_impact=payload["expected_impact"],
                        before_metric=payload.get("before_metric"),
                        after_metric=payload.get("after_metric"),
                        status=payload.get("status", "proposed"),
                        rollback_available=True,
                        priority=payload.get("priority", "medium"),
                        validation_status=payload.get("validation_status", "untested"),
                        evidence_json=payload.get("evidence", {}),
                    )
                )
            db.commit()
        return {"status": "ready" if payloads else "insufficient_evidence", "rows": payloads, "policy": ALPHA_RECOVERY_POLICY}

    def replay_priorities(self, db: Session, limit: int = 30) -> dict:
        missed = db.scalars(select(MissedWinner).order_by(desc(MissedWinner.benchmark_relative_return), desc(MissedWinner.created_at)).limit(limit)).all()
        actions = db.scalars(select(AlphaRecoveryAction).where(AlphaRecoveryAction.status == "proposed").order_by(desc(AlphaRecoveryAction.created_at)).limit(limit)).all()
        return {
            "status": "ready" if missed or actions else "missing",
            "mode": "alpha_loss_replay",
            "priorities": {
                "missed_winners": [serialize_missed_winner(row) for row in missed],
                "recovery_actions": [serialize_action(row) for row in actions],
            },
            "sampling_instruction": "Prioritize replay of missed winners, rejected winners, poor exits, weak allocation and benchmark underperformance periods.",
            "policy": ALPHA_RECOVERY_POLICY,
        }

    def _actions_from_evidence(self, attributions: list[AlphaLossAttribution], missed: list[MissedWinner]) -> list[dict]:
        output: list[dict] = []
        by_category = Counter(row.category for row in attributions if row.category not in {"outperformance_no_alpha_loss", "insufficient_attribution_evidence"})
        top_categories = [item for item, _ in by_category.most_common(5)]
        for category in top_categories:
            rows = [row for row in attributions if row.category == category]
            benchmark = most_common([row.benchmark_name for row in rows])
            before_metric = -sum(abs(safe_float(row.contribution_value)) for row in rows)
            output.append(action_payload_for_category(category, benchmark, before_metric, rows))
        if missed:
            tickers = dict(Counter(row.ticker for row in missed).most_common(8))
            benchmark = most_common([row.benchmark_name for row in missed])
            output.append(
                {
                    "action_type": "alpha_loss_replay",
                    "detected_problem": f"{len(missed)} missed or rejected outperformers are stored for replay.",
                    "recommended_action": "Run Learning Loop alpha_loss_replay on missed winners and compare earlier trigger, pullback-retest and sector-relative-strength logic.",
                    "affected_module": "Learning Loop",
                    "benchmark_name": benchmark,
                    "expected_impact": "Improve opportunity recall and reduce future missed-winner rate if replay tests validate a rule.",
                    "before_metric": safe_mean([row.benchmark_relative_return for row in missed]),
                    "after_metric": None,
                    "priority": "high" if len(missed) >= 5 else "medium",
                    "validation_status": "needs_replay",
                    "evidence": {"missed_winner_count": len(missed), "top_tickers": tickers},
                }
            )
        return dedupe_payloads(output, key_fields=("action_type", "detected_problem", "affected_module"))


class AlphaRecoveryDashboardService:
    """Snapshot-safe dashboard surface for alpha loss and recovery."""

    def dashboard(self, db: Session) -> dict:
        snapshot = DashboardSnapshotService().latest(db, SNAPSHOT_TYPE)
        payload = {
            "status": snapshot.get("status"),
            "snapshot": snapshot,
            "latest_methodology": BenchmarkMethodologyValidator().latest(db, limit=12),
            "latest_attribution": AlphaLossAttributionEngine().latest(db, limit=24),
            "missed_winners": MissedWinnersEngine().latest(db, limit=24),
            "recovery_actions": AlphaRecoveryActionEngine().latest(db, limit=24),
            "truth_layer": self.truth_layer(db),
            "policy": ALPHA_RECOVERY_POLICY,
        }
        if snapshot.get("payload"):
            payload["summary"] = snapshot["payload"]
        return payload

    def recalculate(self, db: Session, benchmark_name: str | None = None) -> dict:
        started = time.perf_counter()
        methodology = BenchmarkMethodologyValidator().validate_latest(db, benchmark_name=benchmark_name, persist=True)
        attribution = AlphaLossAttributionEngine().calculate(db, benchmark_name=benchmark_name, persist=True)
        missed = MissedWinnersEngine().detect(db, persist=True)
        actions = AlphaRecoveryActionEngine().generate(db, persist=True)
        truth = self.truth_layer(db)
        summary = {
            "status": "ready",
            "generated_at": datetime.utcnow().isoformat(),
            "methodology": methodology,
            "attribution_summary": attribution.get("summary"),
            "missed_winners_count": len(missed.get("rows", [])),
            "recovery_actions_count": len(actions.get("rows", [])),
            "truth_layer": truth,
            "policy": ALPHA_RECOVERY_POLICY,
        }
        DashboardSnapshotService().write(
            db,
            SNAPSHOT_TYPE,
            summary,
            source_modules={"alpha_recovery": "explicit_recalculate"},
            ttl_seconds=900,
            warnings=truth.get("warnings", []),
            computation_duration_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        return summary

    def truth_layer(self, db: Session) -> dict:
        validations = db.scalars(select(BenchmarkMethodologyValidation).order_by(desc(BenchmarkMethodologyValidation.created_at)).limit(20)).all()
        attributions = db.scalars(select(AlphaLossAttribution).order_by(desc(AlphaLossAttribution.created_at)).limit(60)).all()
        missed = db.scalars(select(MissedWinner).order_by(desc(MissedWinner.created_at)).limit(40)).all()
        lines: list[str] = []
        warnings: list[str] = []
        invalid = [row for row in validations if not row.methodology_valid]
        valid = [row for row in validations if row.methodology_valid]
        if invalid and not valid:
            lines.append("Benchmark methodology is not valid enough for alpha-loss learning. Do not draw recovery conclusions yet.")
            warnings.append("invalid_benchmark_methodology")
        if valid:
            underperforming = [row for row in valid if safe_float(row.corrected_excess_return) < 0]
            outperforming = [row for row in valid if safe_float(row.corrected_excess_return) > 0]
            if underperforming:
                worst = min(underperforming, key=lambda row: safe_float(row.corrected_excess_return))
                lines.append(f"BLUM is underperforming {worst.benchmark_name} by {safe_float(worst.corrected_excess_return):.2f}% on validated stored evidence.")
            if outperforming:
                best = max(outperforming, key=lambda row: safe_float(row.corrected_excess_return))
                lines.append(f"BLUM is outperforming {best.benchmark_name} by {safe_float(best.corrected_excess_return):.2f}% on validated stored evidence.")
        actionable = [row for row in attributions if row.category not in {"outperformance_no_alpha_loss", "insufficient_attribution_evidence"}]
        if actionable:
            top = max(actionable, key=lambda row: abs(safe_float(row.contribution_value)))
            lines.append(f"Largest measured alpha-loss cause: {top.category.replace('_', ' ')} ({safe_float(top.contribution_value):.2f} contribution units).")
        elif valid:
            lines.append("Alpha loss exists in some comparisons, but stored trade evidence is still insufficient for precise cause attribution.")
        if missed:
            lines.append(f"{len(missed)} missed or rejected winners are available for alpha-loss replay.")
        if not lines:
            lines.append("Insufficient evidence. Run benchmark comparison, trade ledger refresh and explicit alpha recovery recalculation.")
            warnings.append("insufficient_evidence")
        return {"lines": lines[:6], "warnings": warnings, "policy": "Truth first: no alpha claim without valid methodology, sample size and stored evidence."}


def latest_benchmark_comparisons(db: Session, benchmark_name: str | None = None, limit: int = 80) -> list[LearningBenchmarkComparison]:
    query = select(LearningBenchmarkComparison).order_by(desc(LearningBenchmarkComparison.calculated_at)).limit(limit)
    if benchmark_name:
        query = query.where(LearningBenchmarkComparison.benchmark_name == benchmark_name.upper())
    rows = db.scalars(query).all()
    latest: dict[tuple[str, str], LearningBenchmarkComparison] = {}
    for row in rows:
        latest.setdefault((row.mode, row.benchmark_name), row)
    return list(latest.values())


def latest_validations(db: Session, benchmark_name: str | None = None, limit: int = 80) -> list[BenchmarkMethodologyValidation]:
    query = select(BenchmarkMethodologyValidation).order_by(desc(BenchmarkMethodologyValidation.created_at)).limit(limit)
    if benchmark_name:
        query = query.where(BenchmarkMethodologyValidation.benchmark_name == benchmark_name.upper())
    rows = db.scalars(query).all()
    latest: dict[tuple[str, str], BenchmarkMethodologyValidation] = {}
    for row in rows:
        latest.setdefault((row.mode, row.benchmark_name), row)
    return list(latest.values())


def latest_game(db: Session) -> TradingGame | None:
    return db.scalar(select(TradingGame).order_by(desc(TradingGame.updated_at)).limit(1))


def latest_trades(db: Session, game_id: int | None, limit: int = 1000) -> list[TradingGameTrade]:
    query = select(TradingGameTrade).order_by(desc(TradingGameTrade.created_at)).limit(limit)
    if game_id:
        query = query.where(TradingGameTrade.game_id == game_id)
    return db.scalars(query).all()


def normalize_contribution_percent(rows: list[dict], total_alpha_loss: float) -> list[dict]:
    total = sum(abs(safe_float(row.get("contribution_value"))) for row in rows)
    denom = total if total > 0 else total_alpha_loss
    for row in rows:
        row["contribution_percent"] = round(abs(safe_float(row.get("contribution_value"))) / denom, 4) if denom > 0 else None
    return rows


def summarize_attributions(rows: list[AlphaLossAttribution]) -> dict:
    return summarize_payload_attributions([serialize_attribution(row, raw=True) for row in rows])


def summarize_payload_attributions(rows: list[dict]) -> dict:
    by_category: dict[str, float] = defaultdict(float)
    by_ticker: dict[str, float] = defaultdict(float)
    by_setup: dict[str, float] = defaultdict(float)
    by_sector: dict[str, float] = defaultdict(float)
    for row in rows:
        value = abs(safe_float(row.get("contribution_value")))
        by_category[str(row.get("category") or "unknown")] += value
        if row.get("ticker"):
            by_ticker[str(row["ticker"])] += value
        if row.get("setup_type"):
            by_setup[str(row["setup_type"])] += value
        if row.get("sector"):
            by_sector[str(row["sector"])] += value
    return {
        "by_category": sorted_dict(by_category),
        "by_ticker": sorted_dict(by_ticker),
        "by_setup": sorted_dict(by_setup),
        "by_sector": sorted_dict(by_sector),
        "top_category": next(iter(sorted_dict(by_category)), None),
    }


def serialize_validation(row: BenchmarkMethodologyValidation) -> dict:
    return {
        "id": row.id,
        "benchmark_comparison_id": row.benchmark_comparison_id,
        "benchmark_name": row.benchmark_name,
        "mode": row.mode,
        "period_start": iso(row.period_start),
        "period_end": iso(row.period_end),
        "methodology_valid": row.methodology_valid,
        "confidence": row.confidence,
        "corrected_excess_return": row.corrected_excess_return,
        "warnings": row.warnings_json or [],
        "checks": row.validation_checks_json or {},
        "explanation": row.explanation,
        "created_at": iso(row.created_at),
    }


def serialize_attribution(row: AlphaLossAttribution, raw: bool = False) -> dict:
    payload = {
        "id": row.id,
        "methodology_validation_id": row.methodology_validation_id,
        "benchmark_name": row.benchmark_name,
        "mode": row.mode,
        "period_start": row.period_start if raw else iso(row.period_start),
        "period_end": row.period_end if raw else iso(row.period_end),
        "total_alpha_loss": row.total_alpha_loss,
        "category": row.category,
        "ticker": row.ticker,
        "setup_type": row.setup_type,
        "sector": row.sector,
        "engine_name": row.engine_name,
        "capital_allocation_bucket": row.capital_allocation_bucket,
        "contribution_value": row.contribution_value,
        "contribution_percent": row.contribution_percent,
        "sample_size": row.sample_size,
        "confidence": row.confidence,
        "evidence": row.evidence_json or {},
        "explanation": row.explanation,
        "created_at": row.created_at if raw else iso(row.created_at),
    }
    return payload


def serialize_missed_winner(row: MissedWinner) -> dict:
    return {
        "id": row.id,
        "ticker": row.ticker,
        "decision_date": iso(row.decision_date),
        "benchmark_name": row.benchmark_name,
        "future_return": row.future_return,
        "benchmark_relative_return": row.benchmark_relative_return,
        "blum_rank_at_decision": row.blum_rank_at_decision,
        "rejection_reason": row.rejection_reason,
        "confidence_at_decision": row.confidence_at_decision,
        "blocked_rule": row.blocked_rule,
        "missed_signals": row.missed_signals_json or [],
        "suggested_learning_action": row.suggested_learning_action,
        "source_snapshot_id": row.source_snapshot_id,
        "source_trade_id": row.source_trade_id,
        "evidence": row.evidence_json or {},
        "created_at": iso(row.created_at),
    }


def serialize_action(row: AlphaRecoveryAction) -> dict:
    return {
        "id": row.id,
        "created_at": iso(row.created_at),
        "action_type": row.action_type,
        "detected_problem": row.detected_problem,
        "recommended_action": row.recommended_action,
        "affected_module": row.affected_module,
        "benchmark_name": row.benchmark_name,
        "expected_impact": row.expected_impact,
        "before_metric": row.before_metric,
        "after_metric": row.after_metric,
        "status": row.status,
        "rollback_available": row.rollback_available,
        "priority": row.priority,
        "validation_status": row.validation_status,
        "evidence": row.evidence_json or {},
    }


def compact_trade_signals(trade: TradingGameTrade) -> list[dict]:
    return [
        {"name": "setup_type", "value": trade.setup_type},
        {"name": "decision_state", "value": trade.decision_state},
        {"name": "confidence", "value": trade.confidence_at_entry},
        {"name": "excess_return_vs_benchmark", "value": trade.excess_return_vs_benchmark},
    ]


def extract_candidates(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("candidates", "rows", "ranked_candidates", "top_candidates"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def first_float(payload: dict, *keys: str) -> float | None:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def missed_winner_exists(db: Session, payload: dict) -> bool:
    if payload.get("source_trade_id"):
        return bool(db.scalar(select(MissedWinner.id).where(MissedWinner.source_trade_id == payload["source_trade_id"]).limit(1)))
    if payload.get("source_snapshot_id"):
        return bool(
            db.scalar(
                select(MissedWinner.id)
                .where(MissedWinner.source_snapshot_id == payload["source_snapshot_id"], MissedWinner.ticker == payload["ticker"])
                .limit(1)
            )
        )
    return False


def action_exists(db: Session, payload: dict) -> bool:
    return bool(
        db.scalar(
            select(AlphaRecoveryAction.id)
            .where(
                AlphaRecoveryAction.action_type == payload["action_type"],
                AlphaRecoveryAction.detected_problem == payload["detected_problem"],
                AlphaRecoveryAction.status.in_(["proposed", "testing", "applied"]),
            )
            .limit(1)
        )
    )


def action_payload_for_category(category: str, benchmark: str | None, before_metric: float, rows: list[AlphaLossAttribution]) -> dict:
    specs = {
        "missed_entry": (
            "Learning Loop",
            "Run alpha_loss_replay on missed entries and compare earlier trigger, breakout-close and pullback-retest logic.",
            "Reduce missed-entry rate if replay confirms a reproducible trigger improvement.",
            "high",
        ),
        "wrong_asset_selection": (
            "Decision Superiority",
            "Replay same-date opportunity universes and test ranking thresholds against future outperformers.",
            "Improve opportunity precision and ranking accuracy versus benchmark alternatives.",
            "high",
        ),
        "weak_capital_allocation": (
            "Adaptive Capital Allocation",
            "Test confidence-adjusted and benchmark-relative sizing on underallocated winners.",
            "Improve alpha capture without increasing drawdown if sizing tests validate.",
            "high",
        ),
        "premature_exit": (
            "Exit Engine",
            "Backtest trailing exits versus target exits for trades where MFE exceeded realized R.",
            "Reduce premature exit drag while preserving invalidation discipline.",
            "medium",
        ),
        "poor_exit": (
            "Exit Engine",
            "Audit exit triggers that created losses without stop/invalidation evidence.",
            "Improve exit timing quality and reduce avoidable drawdown.",
            "medium",
        ),
        "excessive_cash": (
            "Portfolio Intelligence",
            "Test cash-reserve policy against market regime and benchmark underperformance windows.",
            "Lower cash drag only when regime and risk controls support deployment.",
            "medium",
        ),
    }
    module, recommended, impact, priority = specs.get(
        category,
        ("Learning Loop", f"Increase sampling for {category} evidence and require more samples before changing rules.", "Improve evidence depth.", "medium"),
    )
    return {
        "action_type": f"recover_{category}",
        "detected_problem": f"Alpha loss attribution identified {category.replace('_', ' ')} as a measured weakness.",
        "recommended_action": recommended,
        "affected_module": module,
        "benchmark_name": benchmark,
        "expected_impact": impact,
        "before_metric": before_metric,
        "after_metric": None,
        "priority": priority,
        "validation_status": "needs_out_of_sample_test",
        "evidence": {
            "category": category,
            "sample_size": sum(row.sample_size for row in rows),
            "attribution_ids": [row.id for row in rows[:20]],
            "contribution_value": sum(safe_float(row.contribution_value) for row in rows),
        },
    }


def alpha_category_explanation(category: str, count: int, ticker: str | None, setup: str | None) -> str:
    label = category.replace("_", " ")
    scope = f" Most common evidence: {ticker or 'mixed tickers'} / {setup or 'mixed setups'}."
    return f"{label.title()} is supported by {count} stored trade evidence rows.{scope}"


def most_common(values: list[str | None]) -> str | None:
    cleaned = [value for value in values if value]
    if not cleaned:
        return None
    return Counter(cleaned).most_common(1)[0][0]


def safe_mean(values: list[Any]) -> float | None:
    cleaned = [safe_float(value) for value in values if value is not None]
    return round(mean(cleaned), 4) if cleaned else None


def sorted_dict(values: dict[str, float]) -> dict[str, float]:
    return {key: round(value, 4) for key, value in sorted(values.items(), key=lambda item: abs(item[1]), reverse=True)}


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


def json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
