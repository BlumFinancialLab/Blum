from __future__ import annotations

from datetime import datetime
import hashlib
from itertools import product

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    BlumLearningExperiment,
    FeedbackLoopAudit,
    HyperbolicReplayTrade,
    LearningEvent,
    LearningFocusPriority,
    ModelVersion,
    ReplayStrategyValidation,
    SignalPerformance,
    StrategyMemory,
)


class ReplayExperimentService:
    def __init__(self, max_experiments: int = 5):
        self.max_experiments = max(1, min(8, int(max_experiments)))

    def bounded_variants(self, hypothesis: dict) -> list[dict]:
        entries = hypothesis.get("entry_triggers") or ["close_breakout", "pullback_retest"]
        stops = hypothesis.get("stop_methods") or ["atr_1_5", "structure"]
        targets = hypothesis.get("target_methods") or ["two_r", "trailing_atr"]
        holding_periods = hypothesis.get("holding_periods") or [10, 20]
        timeframe_combinations = hypothesis.get("timeframe_combinations") or [hypothesis.get("timeframes", ["1d"])]
        regime_filters = hypothesis.get("regime_filters") or ["all", "aligned_only"]
        variants = []
        for entry, stop, target, holding, timeframes, regime_filter in product(
            entries,
            stops,
            targets,
            holding_periods,
            timeframe_combinations,
            regime_filters,
        ):
            variants.append(
                {
                    "setup_type": hypothesis.get("setup_type", "swing_breakout"),
                    "market": hypothesis.get("market", "global"),
                    "timeframes": list(timeframes),
                    "timeframe_combination": list(timeframes),
                    "entry_trigger": entry,
                    "stop_method": stop,
                    "target_method": target,
                    "holding_period": int(holding),
                    "regime_filter": regime_filter,
                    "confidence_threshold": float(hypothesis.get("confidence_threshold", 60.0)),
                    "risk_reward_threshold": float(hypothesis.get("risk_reward_threshold", 1.5)),
                }
            )
            if len(variants) >= self.max_experiments:
                break
        return variants

    def persist(self, db: Session, variant: dict, *, training_window: dict, validation_window: dict) -> BlumLearningExperiment:
        key = "|".join(
            [
                variant["setup_type"],
                variant["market"],
                variant["entry_trigger"],
                variant["stop_method"],
                variant["target_method"],
                str(training_window.get("start")),
            ]
        )
        experiment_id = f"replay-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:20]}"
        row = db.scalar(select(BlumLearningExperiment).where(BlumLearningExperiment.experiment_id == experiment_id))
        if row is None:
            row = BlumLearningExperiment(
                experiment_id=experiment_id,
                hypothesis=(
                    f"Test {variant['setup_type']} using {variant['entry_trigger']}, "
                    f"{variant['stop_method']} and {variant['target_method']} after realistic costs."
                ),
                target_market=variant["market"],
                target_asset_class="stocks,etfs",
                target_setup=variant["setup_type"],
                training_window=training_window,
                validation_window=validation_window,
                benchmark_asset="SPY",
                status="TESTING",
                source_payload={"evidence_type": "REPLAY_EVIDENCE", "parameters": variant},
            )
            db.add(row)
            db.flush()
        return row


class ReplayWalkForwardValidator:
    def __init__(self, min_sample_size: int = 300, min_windows: int = 2, max_drawdown: float = -25.0):
        self.min_sample_size = max(300, int(min_sample_size))
        self.min_windows = max(2, int(min_windows))
        self.max_drawdown = float(max_drawdown)

    def verdict(self, evidence: dict) -> dict:
        sample = int(evidence.get("sample_size") or 0)
        markets = set(evidence.get("markets") or [])
        windows = evidence.get("windows") or []
        excess = float(evidence.get("benchmark_excess") or 0.0)
        expectancy = float(evidence.get("expectancy_r") or 0.0)
        drawdown = float(evidence.get("max_drawdown") or 0.0)
        overfitting = float(evidence.get("overfitting_score") or 100.0)
        stability = float(evidence.get("stability_score") or 0.0)
        if sample < self.min_sample_size:
            verdict, reason = "NEEDS_MORE_EVIDENCE", f"Validated sample {sample} is below {self.min_sample_size}."
        elif overfitting > 50:
            verdict, reason = "REJECTED_OVERFITTING", "Overfitting risk exceeds the permitted threshold."
        elif excess <= 0 or expectancy <= 0:
            verdict, reason = "REJECTED_NO_EDGE", "Out-of-sample benchmark excess or expectancy is not positive."
        elif drawdown < self.max_drawdown:
            verdict, reason = "REJECTED_BAD_DRAWDOWN", "Maximum drawdown exceeds the risk budget."
        elif len(markets) < 2 or len(windows) < self.min_windows or stability < 55:
            verdict, reason = "REJECTED_UNSTABLE", "Evidence is not stable across independent windows and markets."
        else:
            verdict, reason = "PROMOTED_TO_PAPER", "All sample, risk-adjusted edge, stability, market and overfitting gates passed."
        return {
            "verdict": verdict,
            "reason": reason,
            "sample_size": sample,
            "markets": sorted(markets),
            "window_count": len(windows),
            "benchmark_excess": excess,
            "expectancy_r": expectancy,
            "max_drawdown": drawdown,
            "overfitting_score": overfitting,
            "stability_score": stability,
        }

    def persist(self, db: Session, *, experiment: BlumLearningExperiment, evidence: dict) -> ReplayStrategyValidation:
        result = self.verdict(evidence)
        row = ReplayStrategyValidation(
            experiment_id=experiment.id,
            setup_type=experiment.target_setup,
            evidence_type="WALK_FORWARD_EVIDENCE",
            sample_size=result["sample_size"],
            markets_json=result["markets"],
            windows_json=evidence.get("windows") or [],
            metrics_json={**evidence, **result},
            overfitting_score=result["overfitting_score"],
            verdict=result["verdict"],
            explanation=result["reason"],
        )
        db.add(row)
        experiment.sample_size = result["sample_size"]
        experiment.status = result["verdict"]
        experiment.result_summary = result
        experiment.conclusion = result["reason"]
        experiment.updated_at = datetime.utcnow()
        db.flush()
        return row


class ReplayLearningFeedbackService:
    def apply_evaluated_trade(self, db: Session, trade: HyperbolicReplayTrade) -> dict:
        if trade.state != "REPLAY_EVALUATED" or trade.evidence_type != "REPLAY_EVIDENCE":
            return {"status": "ignored", "reason": "Only evaluated replay evidence may update replay memory."}
        memory_key = f"replay:{trade.setup_type}:{trade.market}:{trade.timeframe}"
        memory = db.scalar(select(StrategyMemory).where(StrategyMemory.memory_key == memory_key))
        if memory is None:
            memory = StrategyMemory(
                memory_key=memory_key,
                category="hyperbolic_replay",
                lesson=f"{trade.setup_type} replay evidence for {trade.market}/{trade.timeframe} must remain cost and regime aware.",
                conditions={"setup_type": trade.setup_type, "market": trade.market, "timeframe": trade.timeframe},
                reliability_score=50.0,
                evidence={"evidence_type": "REPLAY_EVIDENCE", "trade_ids": []},
            )
            db.add(memory)
            db.flush()
        evidence = dict(memory.evidence or {})
        trade_ids = list(evidence.get("trade_ids") or [])
        if trade.id in trade_ids:
            return {"status": "already_applied", "memory_key": memory_key}
        trade_ids.append(trade.id)
        positive = float(trade.r_multiple or 0.0) > 0
        memory.sample_count += 1
        memory.positive_count += int(positive)
        memory.negative_count += int(not positive)
        memory.reliability_score = round(memory.positive_count / max(1, memory.sample_count) * 100, 2)
        memory.evidence = {
            **evidence,
            "evidence_type": "REPLAY_EVIDENCE",
            "trade_ids": trade_ids[-500:],
            "latest_r_multiple": trade.r_multiple,
            "latest_cost_profile": (trade.execution_payload or {}).get("cost_profile"),
            "latest_trade_id": trade.id,
            "replay_run_id": trade.run_id,
            "market": trade.market,
            "regime": (trade.decision_payload or {}).get("regime"),
            "timeframe": trade.timeframe,
            "benchmark_ticker": (trade.decision_payload or {}).get("benchmark_ticker"),
            "benchmark_excess": trade.benchmark_excess,
            "validation_status": "REPLAY_EVALUATED",
        }
        memory.last_seen_at = datetime.utcnow()

        signal_name = f"replay_{trade.setup_type}"
        signal = db.scalar(
            select(SignalPerformance).where(
                SignalPerformance.signal_name == signal_name,
                SignalPerformance.timeframe == trade.timeframe,
                SignalPerformance.market_regime == trade.market,
            )
        )
        if signal is None:
            signal = SignalPerformance(
                signal_name=signal_name,
                timeframe=trade.timeframe,
                market_regime=trade.market,
                sample_count=0,
                correct_count=0,
                false_positive_count=0,
                false_negative_count=0,
            )
            db.add(signal)
        signal.sample_count = int(signal.sample_count or 0) + 1
        signal.correct_count = int(signal.correct_count or 0) + int(positive)
        signal.false_positive_count = int(signal.false_positive_count or 0) + int(not positive)
        signal.reliability_score = round(signal.correct_count / max(1, signal.sample_count) * 100, 2)
        signal.evidence = {
            "evidence_type": "REPLAY_EVIDENCE",
            "latest_trade_id": trade.id,
            "replay_run_id": trade.run_id,
            "market": trade.market,
            "regime": (trade.decision_payload or {}).get("regime"),
            "cost_profile": (trade.execution_payload or {}).get("cost_profile"),
            "benchmark_excess": trade.benchmark_excess,
        }

        db.add(
            FeedbackLoopAudit(
                prediction_id=None,
                ticker=trade.ticker,
                model_version_used="hyperbolic-replay-v1",
                learned_knowledge_json={
                    "memory_key": memory_key,
                    "r_multiple": trade.r_multiple,
                    "market": trade.market,
                    "regime": (trade.decision_payload or {}).get("regime"),
                    "timeframe": trade.timeframe,
                },
                changes_applied_json={"memory_updated": True, "signal_reliability_updated": True, "reversible": True},
                future_decision_json={"requires_out_of_sample_validation": True, "learning_focus_key": memory_key},
                outcome_json={
                    "evidence_type": "REPLAY_EVIDENCE",
                    "trade_id": trade.id,
                    "replay_run_id": trade.run_id,
                    "cost_profile": (trade.execution_payload or {}).get("cost_profile"),
                    "benchmark_ticker": (trade.decision_payload or {}).get("benchmark_ticker"),
                    "benchmark_excess": trade.benchmark_excess,
                },
                improvement_detected=False,
                evidence_grade="replay_only",
                summary="Replay evidence updated memory; paper-forward confirmation is still required.",
            )
        )
        db.add(
            LearningEvent(
                event_type="hyperbolic_replay_trade_evaluated",
                severity="Info",
                title=f"Replay trade evaluated for {trade.ticker}",
                description=f"{trade.setup_type} produced {float(trade.r_multiple or 0.0):.2f}R after modeled costs.",
                payload={"evidence_type": "REPLAY_EVIDENCE", "trade_id": trade.id, "memory_key": memory_key},
            )
        )
        if not positive:
            existing_focus = db.scalar(
                select(LearningFocusPriority).where(
                    LearningFocusPriority.priority_type == "replay_failure",
                    LearningFocusPriority.target == memory_key,
                    LearningFocusPriority.status.in_(["active", "proposed"]),
                )
            )
            if existing_focus is None:
                db.add(
                    LearningFocusPriority(
                        priority_type="replay_failure",
                        target=memory_key,
                        reason="Negative cost-adjusted replay outcome requires more independent samples.",
                        expected_learning_value=60.0,
                        urgency="medium",
                        sample_gap=max(0, 300 - memory.sample_count),
                        status="proposed",
                        notes_json={
                            "evidence_type": "REPLAY_EVIDENCE",
                            "trade_id": trade.id,
                            "replay_run_id": trade.run_id,
                            "market": trade.market,
                            "regime": (trade.decision_payload or {}).get("regime"),
                            "timeframe": trade.timeframe,
                        },
                    )
                )
        db.flush()
        return {"status": "applied", "memory_key": memory_key, "signal_name": signal_name}

    def apply_validation(self, db: Session, validation: ReplayStrategyValidation) -> dict:
        metrics = validation.metrics_json or {}
        active = db.scalar(select(ModelVersion).where(ModelVersion.is_active.is_(True)).order_by(ModelVersion.created_at.desc()))
        candidate_score = float(metrics.get("out_of_sample_score") or 0.0)
        baseline_score = float(((active.validation_metrics or {}) if active else {}).get("out_of_sample_score") or 0.0)
        eligible = (
            validation.verdict == "PROMOTED_TO_PAPER"
            and validation.sample_size >= 300
            and bool(metrics.get("out_of_sample_improvement"))
            and candidate_score > baseline_score
            and len(validation.markets_json or []) >= 2
            and len(validation.windows_json or []) >= 2
        )
        if not eligible:
            return {"status": "not_promoted", "reason": "Validated out-of-sample improvement gates are not satisfied."}
        weights = metrics.get("candidate_weights")
        if not isinstance(weights, dict) or not weights:
            return {"status": "not_promoted", "reason": "No reversible candidate weights were supplied."}
        if active:
            active.is_active = False
        version = ModelVersion(
            version=f"replay-oos-{validation.id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            model_name="BLUM Learning Loop",
            weights=weights,
            previous_weights=dict(active.weights or {}) if active else {},
            training_window={"evidence_type": "REPLAY_EVIDENCE", "sample_size": validation.sample_size},
            validation_metrics=metrics,
            anti_overfitting_report={"score": validation.overfitting_score},
            change_log="Promoted only after multi-market, multi-window out-of-sample replay validation.",
            is_active=True,
        )
        db.add(version)
        db.flush()
        return {"status": "promoted", "model_version": version.version}
