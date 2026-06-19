from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
import hashlib
import math
import random
import traceback
from statistics import mean, stdev
from uuid import uuid4

import pandas as pd
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Asset,
    FundamentalSnapshot,
    HistoricalPrediction,
    LearningEvent,
    LearningMetric,
    LearningRun,
    MacroSnapshot,
    MistakeAnalysis,
    ModelVersion,
    NewsArticle,
    NewsAssetLink,
    PredictionOutcome,
    PriceHistory,
    SignalPerformance,
    StrategyMemory,
)
from app.services.technical_analysis_engine import TechnicalAnalysisEngine


settings = get_settings()

TIMEFRAMES = {
    "short": {"horizon_days": 20, "label": "5-20 trading days"},
    "mid": {"horizon_days": 63, "label": "1-3 months"},
    "long": {"horizon_days": 252, "label": "6-12 months"},
}

BASE_SIGNAL_WEIGHTS = {
    "trend_structure": 0.18,
    "momentum": 0.16,
    "volume_confirmation": 0.13,
    "volatility_control": 0.12,
    "support_resistance": 0.10,
    "sentiment": 0.10,
    "narrative": 0.08,
    "fundamentals": 0.08,
    "regime": 0.05,
}

ERROR_TYPES = {
    "technical_false_breakout",
    "overbought_signal_ignored",
    "weak_volume_confirmation",
    "sentiment_overestimated",
    "fundamentals_ignored",
    "macro_regime_changed",
    "earnings_event_underestimated",
    "news_shock",
    "sector_rotation",
    "volatility_expansion",
    "support_resistance_wrong",
    "timeframe_mismatch",
    "overconfidence",
    "underconfidence",
    "insufficient_data",
    "random_market_noise",
}


class LearningLoopService:
    """Runs point-in-time historical simulations and updates Blum's strategy memory."""

    def __init__(self) -> None:
        self.sampler = HistoricalSamplerService()
        self.point_in_time = PointInTimeDataService()
        self.predictor = PredictionEngine()
        self.evaluator = OutcomeEvaluator()
        self.mistakes = MistakeAnalyzer()
        self.memory = StrategyMemoryService()
        self.model_scores = ModelScoreService()

    def run_batch(self, db: Session, batch_size: int | None = None, trigger: str = "manual") -> dict:
        requested_batch = int(batch_size or settings.learning_batch_size)
        batch = max(1, min(requested_batch, settings.learning_batch_size, 500))
        daily_guard = self.daily_guard(db, batch)
        run_id = f"learn-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
        run = LearningRun(
            run_id=run_id,
            trigger=trigger,
            status="running",
            evaluation_mode=settings.learning_evaluation_mode,
            asset_universe=settings.learning_asset_universe,
            batch_size=batch,
            anti_overfitting_report=daily_guard,
        )
        db.add(run)
        db.flush()

        if not daily_guard["allowed"]:
            run.status = "skipped"
            run.completed_at = datetime.utcnow()
            run.summary = {"reason": daily_guard["reason"], "requested_batch_size": requested_batch}
            event = LearningEvent(
                event_type="blum_learning_loop_skipped",
                severity="Warning",
                title="BLUM Learning Loop skipped by daily guard",
                description=daily_guard["reason"],
                payload={"run_id": run_id, "guard": daily_guard},
            )
            db.add(event)
            db.commit()
            return {"status": "skipped", "run_id": run_id, "guard": daily_guard}

        reports: list[dict] = []
        errors: list[dict] = []
        seen_samples: set[tuple[str, str]] = set()
        for _ in range(batch):
            try:
                sample = self.sampler.random_sample(db, seen_samples=seen_samples)
                if not sample:
                    errors.append({"stage": "sample", "error": "No eligible historical sample found."})
                    continue
                seen_samples.add((sample["asset"].ticker, sample["analysis_date"].isoformat()))
                reports.append(self.run_single_sample(db, run, sample))
            except Exception as exc:
                errors.append({"stage": "sample", "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(limit=4)})

        metrics = LearningDashboardService().aggregate_metrics(db)
        model_version = self.model_scores.recalculate(db)
        anti_overfitting = self.model_scores.anti_overfitting_report(db)
        run.status = "ok" if reports else "degraded"
        run.completed_at = datetime.utcnow()
        run.predictions_created = len(reports)
        run.outcomes_evaluated = sum(len(report.get("actual_outcome", {})) for report in reports)
        run.mistakes_found = sum(len(report.get("mistakes", [])) for report in reports)
        run.memory_updates = sum(len(report.get("memory_updates", [])) for report in reports)
        run.summary = {
            "reports_created": len(reports),
            "errors": errors[:8],
            "latest_reports": reports[-5:],
            "dashboard_metrics": metrics,
            "model_version": model_version,
        }
        run.anti_overfitting_report = anti_overfitting
        run.error_payload = {"errors": errors}
        db.add(
            LearningEvent(
                event_type="blum_learning_loop",
                severity="Info" if reports else "Warning",
                title="BLUM Learning Loop completed",
                description="Point-in-time historical simulations updated prediction outcomes, mistakes, strategy memory and adaptive signal scores.",
                payload={"run_id": run_id, "reports_created": len(reports), "errors": errors[:8], "anti_overfitting": anti_overfitting},
            )
        )
        db.commit()
        return {
            "status": run.status,
            "run_id": run_id,
            "batch_size": batch,
            "reports_created": len(reports),
            "errors": errors[:8],
            "metrics": metrics,
            "model_version": model_version,
            "anti_overfitting": anti_overfitting,
            "disclaimer": "Research learning loop only. It improves calibration and robustness; it does not create guaranteed market predictions.",
        }

    def run_single_sample(self, db: Session, run: LearningRun, sample: dict) -> dict:
        context = self.point_in_time.context_for(db, sample["asset"], sample["analysis_date"])
        prediction_context = dict(context)
        prediction_context.pop("future_prices", None)
        prediction_payload = self.predictor.predict(prediction_context)
        prediction = HistoricalPrediction(
            learning_run_id=run.id,
            asset_id=sample["asset"].id,
            ticker=sample["asset"].ticker,
            asset_type=sample["asset"].asset_type,
            sector=sample["asset"].sector or "Unknown",
            market=sample["asset"].country or "Unknown",
            market_regime=context["market_context"]["market_regime"],
            volatility_regime=context["market_context"]["volatility_regime"],
            analysis_date=sample["analysis_date"],
            initial_price=context["initial_price"],
            prediction_payload=prediction_payload,
            point_in_time_context=json_safe(context),
            expected_direction=prediction_payload["prediction"]["dominant_direction"],
            confidence=prediction_payload["prediction"]["aggregate_confidence"],
            model_version="blum-learning-loop-v1",
            data_quality_score=context["data_quality_score"],
        )
        db.add(prediction)
        db.flush()

        outcomes = []
        mistakes = []
        memory_updates = []
        for timeframe, frame_prediction in prediction_payload["timeframes"].items():
            outcome_payload = self.evaluator.evaluate(context, timeframe, frame_prediction)
            outcome = PredictionOutcome(
                prediction_id=prediction.id,
                ticker=prediction.ticker,
                timeframe=timeframe,
                horizon_days=outcome_payload["horizon_days"],
                evaluation_date=outcome_payload.get("evaluation_date"),
                price_at_evaluation=outcome_payload.get("price_at_evaluation"),
                realized_return=outcome_payload.get("realized_return"),
                max_favorable_excursion=outcome_payload.get("max_favorable_excursion"),
                max_adverse_excursion=outcome_payload.get("max_adverse_excursion"),
                drawdown=outcome_payload.get("drawdown"),
                time_to_target=outcome_payload.get("time_to_target"),
                time_to_invalidation=outcome_payload.get("time_to_invalidation"),
                target_hit=bool(outcome_payload.get("target_hit")),
                invalidation_hit=bool(outcome_payload.get("invalidation_hit")),
                direction_correct=outcome_payload.get("direction_correct"),
                false_positive=bool(outcome_payload.get("false_positive")),
                false_negative=bool(outcome_payload.get("false_negative")),
                missed_opportunity=bool(outcome_payload.get("missed_opportunity")),
                outcome_label=outcome_payload.get("outcome_label", "inconclusive"),
                confidence_calibration_error=outcome_payload.get("confidence_calibration_error"),
                metrics_payload=json_safe(outcome_payload),
            )
            db.add(outcome)
            db.flush()
            outcomes.append(outcome_payload)

            analysis = self.mistakes.analyze(context, prediction_payload, frame_prediction, outcome_payload)
            if analysis["persist"]:
                mistake = MistakeAnalysis(
                    prediction_id=prediction.id,
                    outcome_id=outcome.id,
                    ticker=prediction.ticker,
                    timeframe=timeframe,
                    error_type=analysis["error_type"],
                    severity=analysis["severity"],
                    predicted=json_safe(frame_prediction),
                    actual=json_safe(outcome_payload),
                    misleading_signal=analysis["misleading_signal"],
                    signal_to_weight_more=analysis["signal_to_weight_more"],
                    rule_adjustment=analysis["rule_adjustment"],
                    future_impact=analysis["future_impact"],
                    explanation=analysis["explanation"],
                    payload=json_safe(analysis),
                )
                db.add(mistake)
                mistakes.append(analysis)
            memory_updates.extend(self.memory.update_from_outcome(db, context, frame_prediction, outcome_payload, analysis))

        self.memory.update_signal_performance(db, context, prediction_payload, outcomes)
        report = {
            "asset": prediction.ticker,
            "analysis_date": prediction.analysis_date.isoformat(),
            "initial_price": prediction.initial_price,
            "timeframes": prediction_payload["timeframes"],
            "prediction": prediction_payload["prediction"],
            "actual_outcome": {outcome["timeframe"]: outcome for outcome in outcomes},
            "score": {
                "data_quality_score": prediction.data_quality_score,
                "confidence": prediction.confidence,
                "market_regime": prediction.market_regime,
                "volatility_regime": prediction.volatility_regime,
            },
            "mistakes": mistakes,
            "lessons_learned": [item["lesson"] for item in memory_updates],
            "memory_updates": memory_updates,
        }
        return json_safe(report)

    def daily_guard(self, db: Session, requested_batch: int) -> dict:
        start = datetime.combine(datetime.utcnow().date(), time.min)
        today_predictions = int(db.scalar(select(func.coalesce(func.sum(LearningRun.predictions_created), 0)).where(LearningRun.started_at >= start)) or 0)
        projected = today_predictions + requested_batch
        allowed = projected <= settings.learning_max_daily_runs
        return {
            "allowed": allowed,
            "today_predictions": today_predictions,
            "requested_batch": requested_batch,
            "max_daily_runs": settings.learning_max_daily_runs,
            "reason": "within daily limit" if allowed else "Learning max daily run guard prevents overfitting and excessive repeated sampling.",
        }


class HistoricalSamplerService:
    def __init__(self) -> None:
        self.rng = random.Random(self.seed())

    def random_sample(self, db: Session, seen_samples: set[tuple[str, str]] | None = None) -> dict | None:
        universe = {item.strip().lower() for item in settings.learning_asset_universe.split(",") if item.strip()}
        asset_types = []
        if "stocks" in universe or "stock" in universe:
            asset_types.append("Stock")
        if "etfs" in universe or "etf" in universe:
            asset_types.append("ETF")
        if not asset_types:
            asset_types = ["Stock", "ETF"]

        candidates = db.scalars(select(Asset).where(Asset.is_active.is_(True), Asset.asset_type.in_(asset_types))).all()
        self.rng.shuffle(candidates)
        min_rows = max(252, settings.learning_min_history_years * 252)
        for asset in candidates:
            stats = db.execute(
                select(func.count(PriceHistory.id), func.min(PriceHistory.date), func.max(PriceHistory.date)).where(PriceHistory.asset_id == asset.id)
            ).one()
            count, first_date, last_date = int(stats[0] or 0), as_date(stats[1]), as_date(stats[2])
            if count < min_rows or not first_date or not last_date:
                continue
            earliest = first_date + timedelta(days=max(365, settings.learning_min_history_years * 365))
            latest = last_date - timedelta(days=TIMEFRAMES["long"]["horizon_days"] * 2 + 30)
            if earliest >= latest:
                continue
            span = (latest - earliest).days
            for _ in range(8):
                analysis_date = nearest_trading_date(
                    db,
                    asset,
                    earliest + timedelta(days=self.rng.randint(0, max(1, span))),
                    latest,
                )
                if not analysis_date:
                    continue
                key = (asset.ticker, analysis_date.isoformat())
                if seen_samples and key in seen_samples:
                    continue
                return {"asset": asset, "analysis_date": analysis_date, "first_price_date": first_date, "last_price_date": last_date, "sample_rows": count}
        return None

    def seed(self) -> int:
        raw = settings.learning_random_seed or datetime.utcnow().strftime("%Y%m%d%H")
        return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8], 16)


class PointInTimeDataService:
    def context_for(self, db: Session, asset: Asset, analysis_date: date) -> dict:
        past_rows = db.scalars(
            select(PriceHistory)
            .where(PriceHistory.asset_id == asset.id, PriceHistory.date <= analysis_date)
            .order_by(PriceHistory.date)
        ).all()
        future_rows = db.scalars(
            select(PriceHistory)
            .where(
                PriceHistory.asset_id == asset.id,
                PriceHistory.date > analysis_date,
                PriceHistory.date <= analysis_date + timedelta(days=TIMEFRAMES["long"]["horizon_days"] * 2 + 30),
            )
            .order_by(PriceHistory.date)
        ).all()
        past_frame = price_frame(past_rows)
        future_frame = price_frame(future_rows)
        technical = TechnicalAnalysisEngine().analyze(past_frame, timeframe="1Y")
        news = self.news_as_of(db, asset, analysis_date)
        fundamentals = self.fundamentals_as_of(db, asset, analysis_date)
        macro = self.macro_as_of(db, analysis_date)
        market_context = self.market_context(db, analysis_date, past_frame)
        initial_price = float(past_frame["close"].iloc[-1]) if not past_frame.empty else None
        data_quality = data_quality_score(past_frame, news, fundamentals, macro)
        return {
            "asset": serialize_asset(asset),
            "analysis_date": analysis_date.isoformat(),
            "initial_price": round(initial_price, 4) if initial_price else None,
            "past_prices": past_frame,
            "future_prices": future_frame,
            "technical": technical,
            "news": news,
            "fundamentals": fundamentals,
            "macro": macro,
            "market_context": market_context,
            "data_quality_score": data_quality,
            "evaluation_data_availability": {"future_ohlcv_rows": len(future_frame)},
            "point_in_time_policy": {
                "prices": "Only stored OHLCV rows with date <= analysis_date are used for prediction.",
                "news": "Only linked public news with published_at <= analysis_date are used for prediction.",
                "fundamentals": "Fundamentals are used only when filing dates are point-in-time verified; otherwise they are marked unavailable.",
                "future": "Rows after analysis_date are hidden from PredictionEngine and used only by OutcomeEvaluator.",
            },
        }

    def news_as_of(self, db: Session, asset: Asset, analysis_date: date) -> dict:
        cutoff = datetime.combine(analysis_date, time.max)
        rows = db.execute(
            select(NewsArticle)
            .join(NewsAssetLink, NewsAssetLink.article_id == NewsArticle.id)
            .where(NewsAssetLink.asset_id == asset.id, NewsArticle.published_at <= cutoff)
            .order_by(desc(NewsArticle.published_at))
            .limit(80)
        ).scalars().all()
        recent = [row for row in rows if row.published_at and row.published_at >= cutoff - timedelta(days=14)]
        themes: dict[str, int] = defaultdict(int)
        quality = []
        for row in recent:
            for theme in (row.theme_tags or {}).get("themes", []):
                themes[str(theme)] += 1
            quality.append(float(row.quality_score or 0.0))
        return {
            "article_count_total_as_of": len(rows),
            "article_count_14d": len(recent),
            "average_quality_14d": round(mean(quality), 3) if quality else 0.0,
            "themes_14d": sorted([{"theme": key, "count": value} for key, value in themes.items()], key=lambda item: item["count"], reverse=True)[:8],
            "sample_headlines": [
                {
                    "title": row.title,
                    "source": row.source,
                    "published_at": row.published_at.isoformat() if row.published_at else None,
                    "themes": (row.theme_tags or {}).get("themes", []),
                }
                for row in recent[:8]
            ],
        }

    def fundamentals_as_of(self, db: Session, asset: Asset, analysis_date: date) -> dict:
        snapshots = db.scalars(
            select(FundamentalSnapshot)
            .where(FundamentalSnapshot.asset_id == asset.id, FundamentalSnapshot.period_end <= analysis_date)
            .order_by(desc(FundamentalSnapshot.period_end), desc(FundamentalSnapshot.created_at))
            .limit(6)
        ).all()
        for snapshot in snapshots:
            filed = latest_filing_date(snapshot.metrics)
            if filed and filed <= analysis_date:
                return {
                    "status": "ready",
                    "provider": snapshot.provider,
                    "period_end": snapshot.period_end.isoformat() if snapshot.period_end else None,
                    "latest_filed": filed.isoformat(),
                    "quality_score": snapshot.quality_score,
                    "metrics": compact_metrics(snapshot.metrics),
                }
        return {
            "status": "not_point_in_time_verified",
            "quality_score": 0,
            "message": "No stored fundamental snapshot had filing dates known by the simulated analysis date.",
        }

    def macro_as_of(self, db: Session, analysis_date: date) -> dict:
        rows = db.scalars(select(MacroSnapshot).where(MacroSnapshot.date <= analysis_date).order_by(desc(MacroSnapshot.date)).limit(30)).all()
        return {
            "status": "ready" if rows else "missing",
            "latest": [
                {"indicator": row.indicator, "date": row.date.isoformat() if row.date else None, "value": row.value, "provider": row.provider}
                for row in rows[:12]
            ],
        }

    def market_context(self, db: Session, analysis_date: date, asset_frame: pd.DataFrame) -> dict:
        benchmark = db.scalar(select(Asset).where(Asset.ticker == settings.default_benchmark).limit(1))
        benchmark_rows = []
        if benchmark:
            benchmark_rows = db.scalars(
                select(PriceHistory)
                .where(PriceHistory.asset_id == benchmark.id, PriceHistory.date <= analysis_date)
                .order_by(PriceHistory.date)
            ).all()
        frame = price_frame(benchmark_rows) if benchmark_rows else asset_frame
        regime = infer_market_regime(frame)
        volatility = infer_volatility_regime(frame)
        return {
            "benchmark": settings.default_benchmark if benchmark_rows else "asset_proxy",
            "market_regime": regime,
            "volatility_regime": volatility,
            "market_breadth": "not_available_point_in_time",
            "risk_sentiment": "risk_on" if regime in {"Bull Expansion", "Recovery", "Rotation"} else "risk_off" if regime in {"Risk-Off", "Panic"} else "balanced",
        }


class PredictionEngine:
    def predict(self, context: dict) -> dict:
        technical = context["technical"]
        signal_scores = self.signal_scores(context)
        aggregate_score = weighted_score(signal_scores, BASE_SIGNAL_WEIGHTS)
        dominant_direction = direction_from_score(aggregate_score, technical)
        confidence = confidence_from_evidence(aggregate_score, context["data_quality_score"], context["market_context"], technical)
        timeframes = {
            timeframe: self.timeframe_prediction(timeframe, config, context, signal_scores, aggregate_score, dominant_direction, confidence)
            for timeframe, config in TIMEFRAMES.items()
        }
        return {
            "asset": context["asset"],
            "analysis_date": context["analysis_date"],
            "initial_price": context["initial_price"],
            "prediction": {
                "dominant_direction": dominant_direction,
                "aggregate_confidence": confidence,
                "aggregate_score": round(aggregate_score, 2),
                "signal_scores": signal_scores,
                "reasoning": self.reasoning(context, signal_scores, dominant_direction),
            },
            "timeframes": timeframes,
            "anti_leakage": context["point_in_time_policy"],
        }

    def signal_scores(self, context: dict) -> dict:
        technical = context["technical"]
        indicators = technical.get("technical_indicators") or {}
        volume = technical.get("volume") or {}
        volatility = technical.get("volatility") or {}
        levels = technical.get("levels") or {}
        fundamentals = context["fundamentals"]
        news = context["news"]
        regime = context["market_context"]["market_regime"]
        return {
            "trend_structure": score_trend(technical),
            "momentum": score_momentum(indicators),
            "volume_confirmation": clamp(45 + safe_float(volume.get("relative_volume")) * 20),
            "volatility_control": score_volatility(volatility),
            "support_resistance": score_levels(levels),
            "sentiment": clamp(45 + news.get("average_quality_14d", 0) * 18 + min(12, news.get("article_count_14d", 0) * 1.5)),
            "narrative": clamp(40 + min(35, news.get("article_count_14d", 0) * 2.2) + min(20, len(news.get("themes_14d", [])) * 3)),
            "fundamentals": safe_float(fundamentals.get("quality_score")) if fundamentals.get("status") == "ready" else 35.0,
            "regime": 70.0 if regime in {"Bull Expansion", "Recovery", "Rotation"} else 42.0 if regime in {"Risk-Off", "Panic"} else 55.0,
        }

    def timeframe_prediction(self, timeframe: str, config: dict, context: dict, signal_scores: dict, aggregate: float, direction: str, confidence: float) -> dict:
        price = safe_float(context["initial_price"])
        technical = context["technical"]
        levels = technical.get("levels") or {}
        risk_reward = technical.get("risk_reward_estimate") or {}
        horizon = config["horizon_days"]
        scale = {"short": 0.65, "mid": 1.0, "long": 1.55}[timeframe]
        base_move = max(1.5, abs(aggregate - 50) * 0.22 * scale)
        if direction == "bullish":
            move_range = [round(base_move, 2), round(base_move * 1.9, 2)]
            target = price * (1 + move_range[1] / 100) if price else None
        elif direction == "bearish":
            move_range = [round(-base_move * 1.9, 2), round(-base_move, 2)]
            target = price * (1 + move_range[0] / 100) if price else None
        else:
            move_range = [round(-base_move, 2), round(base_move, 2)]
            target = levels.get("nearest_resistance") or levels.get("nearest_support")
        invalidation = levels.get("invalidation_level") or (price * 0.94 if price else None)
        if direction == "bearish" and price:
            invalidation = levels.get("nearest_resistance") or price * 1.05
        return {
            "timeframe": timeframe,
            "horizon_days": horizon,
            "bias": direction,
            "expected_move_percent": move_range,
            "estimated_probability": round(confidence / 100, 3),
            "entry_zone_informational": price_zone(price, levels, direction),
            "invalidation_level": round_float(invalidation),
            "target_zone": target_zone(target) if target else "not_available",
            "risk": risk_label(context, signal_scores),
            "confidence": round(confidence * (0.94 if timeframe == "long" else 1.0), 1),
            "technical_reason": technical.get("technical_summary", "Technical evidence unavailable."),
            "fundamental_reason": fundamental_reason(context["fundamentals"]),
            "sentiment_reason": sentiment_reason(context["news"]),
            "narrative_reason": narrative_reason(context["news"]),
            "signals_used": sorted(signal_scores, key=signal_scores.get, reverse=True),
            "risk_reward_estimate": risk_reward,
            "validation_policy": "Forecast generated only from point-in-time context; future prices are hidden until outcome evaluation.",
        }

    def reasoning(self, context: dict, signal_scores: dict, direction: str) -> dict:
        strongest = sorted(signal_scores.items(), key=lambda item: item[1], reverse=True)[:3]
        weakest = sorted(signal_scores.items(), key=lambda item: item[1])[:3]
        return {
            "why_now": f"{context['asset']['ticker']} is simulated as {direction} because strongest point-in-time factors are {', '.join(key for key, _ in strongest)}.",
            "supporting_evidence": [f"{key}: {value:.1f}/100" for key, value in strongest],
            "contradicting_evidence": [f"{key}: {value:.1f}/100" for key, value in weakest if value < 50],
            "missing_data": missing_data(context),
            "intellectual_honesty": "The forecast is probabilistic. It is evaluated later against real future OHLCV and can be wrong.",
        }


class OutcomeEvaluator:
    def evaluate(self, context: dict, timeframe: str, prediction: dict) -> dict:
        future = context["future_prices"].copy()
        initial_price = safe_float(context["initial_price"])
        horizon = int(prediction["horizon_days"])
        analysis_date = parse_date(context["analysis_date"])
        if future.empty or not initial_price:
            return self.inconclusive(timeframe, horizon, "No future OHLCV rows are stored for the evaluation horizon.")
        future["date"] = pd.to_datetime(future["date"]).dt.date
        window = future.head(horizon).copy()
        if window.empty:
            return self.inconclusive(timeframe, horizon, "No future OHLCV rows exist before the target horizon.")
        if len(window) < max(5, int(horizon * 0.70)):
            return self.inconclusive(timeframe, horizon, "Future OHLCV rows are not mature enough for this horizon.")
        evaluation_row = window.iloc[-1]
        evaluation_price = safe_float(evaluation_row["close"])
        realized = pct(initial_price, evaluation_price)
        high_return = pct(initial_price, float(window["high"].astype(float).max()))
        low_return = pct(initial_price, float(window["low"].astype(float).min()))
        target_values = target_values_from_zone(prediction.get("target_zone"), initial_price)
        invalidation = safe_float(prediction.get("invalidation_level"))
        bias = prediction.get("bias", "neutral")
        target_hit, time_to_target = hit_target(window, initial_price, bias, target_values)
        invalidation_hit, time_to_invalidation = hit_invalidation(window, invalidation, bias)
        direction_correct = classify_direction(realized, bias)
        outcome_label = classify_prediction_outcome(direction_correct, target_hit, invalidation_hit, realized, bias)
        confidence = safe_float(prediction.get("confidence")) / 100
        realized_binary = 1.0 if direction_correct is True else 0.0 if direction_correct is False else 0.5
        false_positive = bool(bias == "bullish" and outcome_label == "wrong")
        false_negative = bool(bias in {"neutral", "bearish"} and high_return >= 8.0 and not target_hit)
        missed = bool(false_negative or (bias == "neutral" and abs(realized) >= 8.0))
        return {
            "timeframe": timeframe,
            "horizon_days": horizon,
            "evaluation_date": evaluation_row["date"],
            "price_at_evaluation": round(evaluation_price, 4),
            "realized_return": round(realized, 3),
            "max_favorable_excursion": round(high_return if bias != "bearish" else -low_return, 3),
            "max_adverse_excursion": round(low_return if bias != "bearish" else -high_return, 3),
            "drawdown": round(min(0.0, low_return), 3),
            "target_hit": target_hit,
            "invalidation_hit": invalidation_hit,
            "time_to_target": time_to_target,
            "time_to_invalidation": time_to_invalidation,
            "direction_correct": direction_correct,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "missed_opportunity": missed,
            "outcome_label": outcome_label,
            "confidence_calibration_error": round(abs(confidence - realized_binary), 4),
            "risk_reward_realized": realized_risk_reward(realized, low_return),
            "why_right_or_wrong": why_outcome(outcome_label, bias, realized, target_hit, invalidation_hit),
        }

    def inconclusive(self, timeframe: str, horizon: int, reason: str) -> dict:
        return {
            "timeframe": timeframe,
            "horizon_days": horizon,
            "evaluation_date": None,
            "price_at_evaluation": None,
            "realized_return": None,
            "max_favorable_excursion": None,
            "max_adverse_excursion": None,
            "drawdown": None,
            "target_hit": False,
            "invalidation_hit": False,
            "direction_correct": None,
            "false_positive": False,
            "false_negative": False,
            "missed_opportunity": False,
            "outcome_label": "inconclusive",
            "confidence_calibration_error": None,
            "why_right_or_wrong": reason,
        }


class MistakeAnalyzer:
    def analyze(self, context: dict, prediction_payload: dict, prediction: dict, outcome: dict) -> dict:
        outcome_label = outcome.get("outcome_label")
        bias = prediction.get("bias")
        confidence = safe_float(prediction.get("confidence"))
        technical = context["technical"]
        indicators = technical.get("technical_indicators") or {}
        volume = technical.get("volume") or {}
        volatility = technical.get("volatility") or {}
        error_type = "random_market_noise"
        severity = "Info"
        if outcome_label == "inconclusive":
            error_type = "insufficient_data"
        elif outcome_label == "correct":
            error_type = "underconfidence" if confidence < 50 else "random_market_noise"
        elif outcome.get("invalidation_hit"):
            error_type = "support_resistance_wrong"
            severity = "Warning"
        elif bias == "bullish" and safe_float(indicators.get("rsi")) >= 75:
            error_type = "overbought_signal_ignored"
            severity = "Warning"
        elif bias == "bullish" and safe_float(volume.get("relative_volume")) < 1.1:
            error_type = "weak_volume_confirmation"
            severity = "Warning"
        elif volatility.get("regime") == "high":
            error_type = "volatility_expansion"
            severity = "Warning"
        elif confidence >= 70 and outcome_label == "wrong":
            error_type = "overconfidence"
            severity = "High"
        elif context["news"].get("article_count_14d", 0) > 8 and outcome_label == "wrong":
            error_type = "sentiment_overestimated"
            severity = "Warning"
        if error_type not in ERROR_TYPES and error_type not in {"correct_thesis_confirmed"}:
            error_type = "random_market_noise"
        explanation = mistake_explanation(error_type, context, prediction, outcome)
        persist = outcome_label in {"wrong", "correct"} or error_type in {"overconfidence", "underconfidence", "insufficient_data"}
        return {
            "persist": persist,
            "error_type": error_type,
            "severity": severity,
            "misleading_signal": misleading_signal(error_type),
            "signal_to_weight_more": signal_to_weight_more(error_type),
            "rule_adjustment": rule_adjustment(error_type),
            "future_impact": future_impact(error_type),
            "explanation": explanation,
            "outcome_label": outcome_label,
        }


class StrategyMemoryService:
    def update_from_outcome(self, db: Session, context: dict, prediction: dict, outcome: dict, analysis: dict) -> list[dict]:
        lessons = lessons_for(context, prediction, outcome, analysis)
        updates = []
        for lesson in lessons:
            key = stable_key(lesson["category"], lesson["lesson"])
            row = db.scalar(select(StrategyMemory).where(StrategyMemory.memory_key == key).limit(1))
            if row is None:
                row = StrategyMemory(memory_key=key, category=lesson["category"], lesson=lesson["lesson"], conditions=lesson["conditions"])
                db.add(row)
            row.sample_count = int(row.sample_count or 0) + 1
            if outcome.get("outcome_label") == "correct":
                row.positive_count = int(row.positive_count or 0) + 1
            elif outcome.get("outcome_label") == "wrong":
                row.negative_count = int(row.negative_count or 0) + 1
            row.reliability_score = memory_reliability(int(row.positive_count or 0), int(row.negative_count or 0), int(row.sample_count or 0))
            row.evidence = merge_evidence(row.evidence, context, prediction, outcome, analysis)
            row.last_seen_at = datetime.utcnow()
            row.updated_at = datetime.utcnow()
            updates.append({"memory_key": row.memory_key, "category": row.category, "lesson": row.lesson, "reliability_score": row.reliability_score})
        return updates

    def update_signal_performance(self, db: Session, context: dict, prediction_payload: dict, outcomes: list[dict]) -> None:
        signals = prediction_payload["prediction"].get("signal_scores", {})
        for signal_name, score in signals.items():
            for outcome in outcomes:
                timeframe = outcome["timeframe"]
                regime = context["market_context"]["market_regime"]
                row = db.scalar(
                    select(SignalPerformance)
                    .where(SignalPerformance.signal_name == signal_name, SignalPerformance.timeframe == timeframe, SignalPerformance.market_regime == regime)
                    .limit(1)
                )
                if row is None:
                    row = SignalPerformance(signal_name=signal_name, timeframe=timeframe, market_regime=regime)
                    db.add(row)
                row.sample_count = int(row.sample_count or 0) + 1
                if outcome.get("direction_correct") is True:
                    row.correct_count = int(row.correct_count or 0) + 1
                if outcome.get("false_positive"):
                    row.false_positive_count = int(row.false_positive_count or 0) + 1
                if outcome.get("false_negative"):
                    row.false_negative_count = int(row.false_negative_count or 0) + 1
                returns = (row.evidence or {}).get("returns", [])
                drawdowns = (row.evidence or {}).get("drawdowns", [])
                if outcome.get("realized_return") is not None:
                    returns = (returns + [outcome["realized_return"]])[-200:]
                if outcome.get("drawdown") is not None:
                    drawdowns = (drawdowns + [outcome["drawdown"]])[-200:]
                positives = [value for value in returns if value > 0]
                negatives = [abs(value) for value in returns if value < 0]
                correct_rate = int(row.correct_count or 0) / max(1, int(row.sample_count or 0))
                false_penalty = int(row.false_positive_count or 0) / max(1, int(row.sample_count or 0)) * 18
                row.average_return = round(mean(returns), 4) if returns else None
                row.average_drawdown = round(mean(drawdowns), 4) if drawdowns else None
                row.profit_factor = round(sum(positives) / max(0.01, sum(negatives)), 4) if returns else None
                row.reliability_score = round(clamp(35 + correct_rate * 55 + min(10, max(-8, (row.average_return or 0))) - false_penalty), 2)
                row.weight_adjustment = round((row.reliability_score - 50) / 500, 4)
                row.evidence = {
                    "returns": returns,
                    "drawdowns": drawdowns,
                    "last_signal_score": score,
                    "last_outcome": outcome.get("outcome_label"),
                    "policy": "Reliability changes gradually and is penalized for false positives.",
                }
                row.updated_at = datetime.utcnow()


class ModelScoreService:
    def recalculate(self, db: Session) -> dict:
        rows = db.scalars(select(SignalPerformance).order_by(desc(SignalPerformance.updated_at)).limit(600)).all()
        if not rows:
            return {"status": "insufficient_sample", "version": None}
        previous = active_model_version(db)
        previous_weights = previous.weights if previous else BASE_SIGNAL_WEIGHTS
        new_weights = dict(BASE_SIGNAL_WEIGHTS)
        for signal_name in new_weights:
            matching = [row for row in rows if row.signal_name == signal_name and row.sample_count >= 3]
            if not matching:
                continue
            avg_reliability = mean(row.reliability_score for row in matching)
            new_weights[signal_name] = max(0.03, new_weights[signal_name] + (avg_reliability - 50) / 1000)
        new_weights = normalize_weights(new_weights)
        anti = self.anti_overfitting_report(db)
        version = f"learning-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        row = ModelVersion(
            version=version,
            model_name="BLUM Learning Loop",
            weights=new_weights,
            previous_weights=previous_weights,
            training_window={"source": "historical_predictions", "evaluation_mode": settings.learning_evaluation_mode},
            validation_metrics=LearningDashboardService().aggregate_metrics(db),
            anti_overfitting_report=anti,
            change_log="Adaptive signal reliability weights recalculated from point-in-time historical outcomes. Source code unchanged.",
            is_active=True,
        )
        if previous:
            previous.is_active = False
        db.add(row)
        db.add(
            LearningMetric(
                metric_name="model_weight_recalibration",
                timeframe="all",
                metric_value=anti.get("robustness_score"),
                sample_count=int(anti.get("sample_count", 0)),
                payload={"version": version, "weights": new_weights, "anti_overfitting": anti},
            )
        )
        return {"status": "updated", "version": version, "weights": new_weights, "anti_overfitting": anti}

    def anti_overfitting_report(self, db: Session) -> dict:
        total = int(db.scalar(select(func.count(PredictionOutcome.id)).where(PredictionOutcome.outcome_label.in_(["correct", "wrong", "neutral"]))) or 0)
        tickers = int(db.scalar(select(func.count(func.distinct(HistoricalPrediction.ticker)))) or 0)
        sectors = int(db.scalar(select(func.count(func.distinct(HistoricalPrediction.sector)))) or 0)
        regimes = int(db.scalar(select(func.count(func.distinct(HistoricalPrediction.market_regime)))) or 0)
        outcomes = db.scalars(select(PredictionOutcome).where(PredictionOutcome.outcome_label.in_(["correct", "wrong", "neutral"])).limit(5000)).all()
        correct = sum(1 for row in outcomes if row.outcome_label == "correct")
        wrong = sum(1 for row in outcomes if row.outcome_label == "wrong")
        usable = correct + wrong
        hit_rate = correct / usable if usable else None
        suspicious = bool(hit_rate is not None and hit_rate > 0.82 and usable < 250)
        coverage_score = min(100, tickers * 2.0 + sectors * 6.0 + regimes * 5.0)
        sample_score = min(100, total / 10)
        penalty = 25 if suspicious else 0
        robustness = clamp((coverage_score * 0.45) + (sample_score * 0.45) + (0 if suspicious else 10) - penalty)
        return {
            "sample_count": total,
            "distinct_tickers": tickers,
            "distinct_sectors": sectors,
            "distinct_regimes": regimes,
            "hit_rate": round(hit_rate, 4) if hit_rate is not None else None,
            "temporal_validation": settings.learning_evaluation_mode,
            "walk_forward_validation": settings.learning_evaluation_mode == "walk_forward",
            "train_test_policy": "Historical samples are point-in-time; future OHLCV is only used after prediction persistence.",
            "overfitting_warning": suspicious,
            "robustness_score": round(robustness, 2),
            "policy": "Penalize perfect-looking strategies, small samples, narrow ticker coverage and single-regime optimization.",
        }


class LearningDashboardService:
    def dashboard(self, db: Session) -> dict:
        latest_run = db.scalar(select(LearningRun).order_by(desc(LearningRun.started_at)).limit(1))
        metrics = self.aggregate_metrics(db)
        return {
            "status": "active" if settings.enable_learning_loop else "passive",
            "configuration": {
                "batch_size": settings.learning_batch_size,
                "max_daily_runs": settings.learning_max_daily_runs,
                "min_history_years": settings.learning_min_history_years,
                "asset_universe": settings.learning_asset_universe,
                "evaluation_mode": settings.learning_evaluation_mode,
            },
            "latest_run": serialize_run(latest_run) if latest_run else None,
            "metrics": metrics,
            "signal_performance": self.signal_performance(db),
            "strategy_memory": self.strategy_memory(db),
            "mistakes": self.mistake_summary(db),
            "model_versions": [serialize_model_version(row) for row in db.scalars(select(ModelVersion).order_by(desc(ModelVersion.created_at)).limit(8)).all()],
            "policy": "BLUM Learning Loop optimizes calibration and robustness, not artificial 100% winrate.",
        }

    def aggregate_metrics(self, db: Session) -> dict:
        outcomes = db.scalars(select(PredictionOutcome).where(PredictionOutcome.outcome_label.in_(["correct", "wrong", "neutral"]))).all()
        by_timeframe = {}
        for timeframe in TIMEFRAMES:
            subset = [row for row in outcomes if row.timeframe == timeframe]
            by_timeframe[timeframe] = metric_block(subset)
        all_metrics = metric_block(outcomes)
        return {
            "simulations": int(db.scalar(select(func.count(HistoricalPrediction.id))) or 0),
            "outcomes": len(outcomes),
            "accuracy": {key: value["accuracy"] for key, value in by_timeframe.items()},
            "by_timeframe": by_timeframe,
            "overall": all_metrics,
            "confidence_calibration": confidence_calibration(outcomes),
        }

    def signal_performance(self, db: Session, limit: int = 16) -> list[dict]:
        return [serialize_signal_performance(row) for row in db.scalars(select(SignalPerformance).order_by(desc(SignalPerformance.reliability_score)).limit(limit)).all()]

    def strategy_memory(self, db: Session, limit: int = 16) -> list[dict]:
        return [serialize_strategy_memory(row) for row in db.scalars(select(StrategyMemory).order_by(desc(StrategyMemory.reliability_score), desc(StrategyMemory.updated_at)).limit(limit)).all()]

    def mistake_summary(self, db: Session) -> list[dict]:
        rows = db.execute(select(MistakeAnalysis.error_type, func.count(MistakeAnalysis.id)).group_by(MistakeAnalysis.error_type).order_by(desc(func.count(MistakeAnalysis.id))).limit(16)).all()
        return [{"error_type": row[0], "count": int(row[1])} for row in rows]

    def runs(self, db: Session, limit: int = 50) -> list[dict]:
        return [serialize_run(row) for row in db.scalars(select(LearningRun).order_by(desc(LearningRun.started_at)).limit(limit)).all()]

    def predictions(self, db: Session, ticker: str | None = None, limit: int = 80) -> list[dict]:
        query = select(HistoricalPrediction).order_by(desc(HistoricalPrediction.created_at)).limit(limit)
        if ticker:
            query = select(HistoricalPrediction).where(HistoricalPrediction.ticker == ticker.upper()).order_by(desc(HistoricalPrediction.created_at)).limit(limit)
        return [serialize_prediction(row) for row in db.scalars(query).all()]

    def chat_memory(self, db: Session, query: str, assets: list[Asset] | None = None, limit: int = 8) -> dict:
        tickers = {asset.ticker for asset in assets or []}
        terms = {token.lower() for token in query.split() if len(token) > 3}
        memory_rows = db.scalars(select(StrategyMemory).order_by(desc(StrategyMemory.updated_at)).limit(200)).all()
        ranked = []
        for row in memory_rows:
            text = f"{row.category} {row.lesson} {row.conditions}".lower()
            score = sum(1 for token in terms if token in text)
            if score or not terms:
                ranked.append((score, row))
        ranked.sort(key=lambda item: (item[0], item[1].reliability_score, item[1].updated_at), reverse=True)
        perf_query = select(SignalPerformance).order_by(desc(SignalPerformance.reliability_score)).limit(limit)
        return {
            "strategy_memory": [serialize_strategy_memory(row) for _, row in ranked[:limit]],
            "signal_reliability": [serialize_signal_performance(row) for row in db.scalars(perf_query).all()],
            "ticker_recent_predictions": self.predictions(db, next(iter(tickers)) if tickers else None, limit=6) if tickers else [],
            "summary": "Learning Loop memory is based on point-in-time historical simulations and should adjust confidence, not create certainty.",
        }


def nearest_trading_date(db: Session, asset: Asset, target: date, latest: date) -> date | None:
    row = db.scalar(
        select(PriceHistory.date)
        .where(PriceHistory.asset_id == asset.id, PriceHistory.date >= target, PriceHistory.date <= latest)
        .order_by(PriceHistory.date)
        .limit(1)
    )
    return as_date(row)


def price_frame(rows: list[PriceHistory]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "date": row.date,
                "open": row.open if row.open is not None else row.close,
                "high": row.high if row.high is not None else row.close,
                "low": row.low if row.low is not None else row.close,
                "close": row.close,
                "volume": row.volume or 0,
            }
            for row in rows
        ]
    ).sort_values("date")


def latest_filing_date(metrics: dict) -> date | None:
    dates = []
    for value in (metrics or {}).values():
        if isinstance(value, dict) and value.get("filed"):
            parsed = parse_date(value.get("filed"))
            if parsed:
                dates.append(parsed)
    return max(dates) if dates else None


def compact_metrics(metrics: dict) -> dict:
    output = {}
    for key in ["revenue", "net_income", "operating_income", "assets", "liabilities", "operating_cash_flow", "eps_diluted"]:
        if key in metrics:
            output[key] = metrics[key]
    return output


def infer_market_regime(frame: pd.DataFrame) -> str:
    if frame is None or frame.empty or len(frame) < 80:
        return "Sideways"
    close = frame["close"].astype(float)
    ret_3m = pct(float(close.iloc[-64]), float(close.iloc[-1])) if len(close) > 64 else 0
    ret_1m = pct(float(close.iloc[-22]), float(close.iloc[-1])) if len(close) > 22 else 0
    vol = close.pct_change().tail(30).std() * math.sqrt(252) * 100
    drawdown = (float(close.iloc[-1]) / float(close.tail(126).max()) - 1) * 100
    if drawdown < -18 and vol > 35:
        return "Panic"
    if ret_3m < -8 or drawdown < -12:
        return "Risk-Off"
    if ret_3m > 12 and ret_1m > 2:
        return "Bull Expansion"
    if ret_3m > 6 and ret_1m < 0:
        return "Bull Maturity"
    if ret_3m > 0 and ret_1m > 4:
        return "Rotation"
    if ret_3m > 3:
        return "Recovery"
    return "Sideways"


def infer_volatility_regime(frame: pd.DataFrame) -> str:
    if frame is None or frame.empty or len(frame) < 30:
        return "Unknown"
    vol = frame["close"].astype(float).pct_change().tail(30).std() * math.sqrt(252) * 100
    if vol >= 45:
        return "High"
    if vol >= 25:
        return "Medium"
    return "Low"


def data_quality_score(past: pd.DataFrame, news: dict, fundamentals: dict, macro: dict) -> float:
    score = min(40, len(past) / 12)
    score += min(20, len(past.tail(252)) / 13)
    score += min(15, news.get("article_count_total_as_of", 0) * 1.5)
    score += 15 if fundamentals.get("status") == "ready" else 4
    score += 10 if macro.get("status") == "ready" else 3
    return round(clamp(score), 2)


def score_trend(technical: dict) -> float:
    if technical.get("status") != "ready":
        return 35.0
    direction = technical.get("trend_direction")
    alignment = (technical.get("moving_averages") or {}).get("alignment")
    score = 50.0
    if direction == "uptrend":
        score += 22
    elif direction in {"downtrend", "bearish"}:
        score -= 18
    if alignment == "bullish_stack":
        score += 16
    elif alignment == "bearish_stack":
        score -= 15
    return clamp(score)


def score_momentum(indicators: dict) -> float:
    rsi = safe_float(indicators.get("rsi"))
    macd = safe_float(indicators.get("macd_hist"))
    score = 50 + max(-18, min(18, macd * 1.2))
    if 48 <= rsi <= 68:
        score += 12
    elif 68 < rsi <= 76:
        score += 4
    elif rsi > 76:
        score -= 10
    elif rsi < 38:
        score -= 8
    return clamp(score)


def score_volatility(volatility: dict) -> float:
    regime = volatility.get("regime")
    if regime == "low":
        return 68
    if regime == "medium":
        return 58
    if regime == "high":
        return 38
    return 50


def score_levels(levels: dict) -> float:
    support = safe_float(levels.get("nearest_support"))
    resistance = safe_float(levels.get("nearest_resistance"))
    if not support or not resistance:
        return 45
    spread = abs(resistance - support) / max(1, support) * 100
    return clamp(48 + min(22, spread * 1.2))


def weighted_score(scores: dict, weights: dict) -> float:
    total = sum(weights.values()) or 1
    return sum(safe_float(scores.get(key)) * weight for key, weight in weights.items()) / total


def direction_from_score(score: float, technical: dict) -> str:
    trend = technical.get("trend_direction")
    if score >= 61 and trend != "downtrend":
        return "bullish"
    if score <= 42 or trend == "downtrend":
        return "bearish"
    return "neutral"


def confidence_from_evidence(score: float, data_quality: float, market_context: dict, technical: dict) -> float:
    distance = abs(score - 50)
    confidence = 38 + distance * 0.72 + data_quality * 0.25
    if market_context.get("market_regime") in {"Panic", "Risk-Off"}:
        confidence -= 6
    if technical.get("status") != "ready":
        confidence -= 18
    return round(clamp(confidence, 15, 82), 1)


def price_zone(price: float | None, levels: dict, direction: str) -> str:
    if not price:
        return "not_available"
    if direction == "bullish":
        anchor = safe_float(levels.get("breakout_level")) or price
        return f"{anchor * 0.99:.2f}-{anchor * 1.01:.2f}"
    if direction == "bearish":
        anchor = safe_float(levels.get("breakdown_level")) or price
        return f"{anchor * 0.99:.2f}-{anchor * 1.01:.2f}"
    return f"{price * 0.98:.2f}-{price * 1.02:.2f}"


def target_zone(target: float | None) -> str:
    if not target:
        return "not_available"
    return f"{target * 0.99:.2f}-{target * 1.01:.2f}"


def target_values_from_zone(zone: str | None, initial_price: float) -> list[float]:
    if not zone or zone == "not_available":
        return []
    values = []
    for chunk in str(zone).replace("–", "-").split("-"):
        try:
            values.append(float(chunk.strip()))
        except ValueError:
            pass
    return values or [initial_price]


def hit_target(window: pd.DataFrame, initial_price: float, bias: str, targets: list[float]) -> tuple[bool, int | None]:
    if not targets:
        return False, None
    target = max(targets) if bias != "bearish" else min(targets)
    for index, row in enumerate(window.itertuples(index=False), start=1):
        if bias == "bearish" and safe_float(row.low) <= target:
            return True, index
        if bias != "bearish" and safe_float(row.high) >= target:
            return True, index
    return False, None


def hit_invalidation(window: pd.DataFrame, invalidation: float, bias: str) -> tuple[bool, int | None]:
    if not invalidation:
        return False, None
    for index, row in enumerate(window.itertuples(index=False), start=1):
        if bias == "bearish" and safe_float(row.high) >= invalidation:
            return True, index
        if bias != "bearish" and safe_float(row.low) <= invalidation:
            return True, index
    return False, None


def classify_direction(realized: float, bias: str) -> bool | None:
    if bias == "bullish":
        return realized > 1.0
    if bias == "bearish":
        return realized < -1.0
    if abs(realized) <= 3.0:
        return True
    return None


def classify_prediction_outcome(direction_correct: bool | None, target_hit: bool, invalidation_hit: bool, realized: float, bias: str) -> str:
    if invalidation_hit and direction_correct is False:
        return "wrong"
    if target_hit and direction_correct is not False:
        return "correct"
    if direction_correct is True:
        return "correct"
    if direction_correct is False:
        return "wrong"
    return "neutral"


def realized_risk_reward(realized: float, adverse: float) -> float | None:
    risk = abs(min(adverse, 0))
    return round(realized / risk, 4) if risk > 0 else None


def why_outcome(label: str, bias: str, realized: float, target_hit: bool, invalidation_hit: bool) -> str:
    if label == "correct":
        return f"The {bias} thesis was supported: realized return {realized:.2f}%, target_hit={target_hit}, invalidation_hit={invalidation_hit}."
    if label == "wrong":
        return f"The {bias} thesis failed: realized return {realized:.2f}%, target_hit={target_hit}, invalidation_hit={invalidation_hit}."
    return f"The {bias} thesis produced an inconclusive/neutral outcome: realized return {realized:.2f}%."


def mistake_explanation(error_type: str, context: dict, prediction: dict, outcome: dict) -> str:
    ticker = context["asset"]["ticker"]
    if outcome.get("outcome_label") == "correct":
        return f"BLUM was directionally correct on {ticker}; this strengthens similar evidence but does not prove a permanent edge."
    return f"BLUM classified the {ticker} {prediction.get('timeframe')} setup as {prediction.get('bias')}, but outcome was {outcome.get('outcome_label')}. Primary error class: {error_type}."


def misleading_signal(error_type: str) -> str:
    return {
        "overbought_signal_ignored": "Momentum was treated as continuation even though RSI was stretched.",
        "weak_volume_confirmation": "Price structure looked constructive but volume confirmation was weak.",
        "sentiment_overestimated": "News/narrative intensity may have been over-weighted versus price confirmation.",
        "support_resistance_wrong": "Invalidation/support-resistance zone was too close, stale or structurally weak.",
        "volatility_expansion": "Volatility regime expanded faster than the setup could absorb.",
        "overconfidence": "Confidence was too high relative to evidence diversity.",
        "underconfidence": "Confidence was too low relative to realized follow-through.",
        "insufficient_data": "Historical window lacked enough verified data for robust evaluation.",
    }.get(error_type, "No single misleading signal can be isolated; random market noise remains possible.")


def signal_to_weight_more(error_type: str) -> str:
    return {
        "weak_volume_confirmation": "relative_volume and accumulation/distribution",
        "sentiment_overestimated": "price/sentiment divergence and source quality",
        "support_resistance_wrong": "ATR-adjusted invalidation and level recency",
        "volatility_expansion": "ATR percent, realized volatility and regime instability",
        "overconfidence": "contradicting evidence and sample-size penalty",
        "underconfidence": "aligned trend/volume/fundamental confirmation",
    }.get(error_type, "independent confirmations and out-of-sample sample size")


def rule_adjustment(error_type: str) -> str:
    return {
        "overbought_signal_ignored": "Reduce breakout confidence when RSI > 75 unless volume is expanding and pullback quality is acceptable.",
        "weak_volume_confirmation": "Require relative volume > 1.3x for breakout confidence upgrades.",
        "sentiment_overestimated": "Treat narrative/news as context until price and sector confirmation agree.",
        "support_resistance_wrong": "Use ATR-adjusted buffers around invalidation rather than raw pivot levels only.",
        "volatility_expansion": "Increase risk penalty in high-volatility regimes.",
        "overconfidence": "Cap confidence when evidence comes from fewer than three independent factors.",
        "underconfidence": "Allow moderate confidence upgrade when trend, volume and fundamentals are aligned out-of-sample.",
    }.get(error_type, "Aggregate more similar cases before changing weights.")


def future_impact(error_type: str) -> str:
    return f"Future BLUM scoring should adjust the relevant factor weight for {error_type} only after repeated out-of-sample confirmation."


def lessons_for(context: dict, prediction: dict, outcome: dict, analysis: dict) -> list[dict]:
    technical = context["technical"]
    indicators = technical.get("technical_indicators") or {}
    volume = technical.get("volume") or {}
    lessons = []
    if safe_float(indicators.get("rsi")) > 75:
        lessons.append(
            {
                "category": "momentum_risk",
                "lesson": "RSI above 75 increases false-breakout risk unless volume and trend quality independently confirm.",
                "conditions": {"rsi_gt": 75, "timeframe": prediction.get("timeframe")},
            }
        )
    if safe_float(volume.get("relative_volume")) > 1.5:
        lessons.append(
            {
                "category": "volume_confirmation",
                "lesson": "Momentum breakout reliability improves when relative volume is above 1.5x.",
                "conditions": {"relative_volume_gt": 1.5, "timeframe": prediction.get("timeframe")},
            }
        )
    if context["fundamentals"].get("status") != "ready" and prediction.get("bias") == "bullish":
        lessons.append(
            {
                "category": "fundamental_gap",
                "lesson": "Bullish technical setups without point-in-time verified fundamentals need lower confidence.",
                "conditions": {"fundamentals": "not_point_in_time_verified"},
            }
        )
    if analysis.get("error_type") in {"sentiment_overestimated", "weak_volume_confirmation", "volatility_expansion"}:
        lessons.append(
            {
                "category": analysis["error_type"],
                "lesson": rule_adjustment(analysis["error_type"]),
                "conditions": {"error_type": analysis["error_type"], "timeframe": prediction.get("timeframe")},
            }
        )
    if not lessons:
        lessons.append(
            {
                "category": "general_calibration",
                "lesson": "Use repeated out-of-sample outcomes before changing confidence materially.",
                "conditions": {"outcome_label": outcome.get("outcome_label"), "timeframe": prediction.get("timeframe")},
            }
        )
    return lessons


def memory_reliability(positive: int, negative: int, sample_count: int) -> float:
    usable = positive + negative
    if usable == 0:
        return 50.0
    rate = positive / usable
    sample_bonus = min(12, math.log1p(sample_count) * 4)
    return round(clamp(35 + rate * 50 + sample_bonus - (negative / max(1, sample_count)) * 12), 2)


def merge_evidence(existing: dict, context: dict, prediction: dict, outcome: dict, analysis: dict) -> dict:
    samples = (existing or {}).get("samples", [])
    samples.append(
        {
            "ticker": context["asset"]["ticker"],
            "analysis_date": context["analysis_date"],
            "timeframe": prediction.get("timeframe"),
            "bias": prediction.get("bias"),
            "outcome": outcome.get("outcome_label"),
            "realized_return": outcome.get("realized_return"),
            "error_type": analysis.get("error_type"),
        }
    )
    return {"samples": samples[-40:], "last_update_policy": "Evidence is append-only and capped to latest samples for compact storage."}


def active_model_version(db: Session) -> ModelVersion | None:
    return db.scalar(select(ModelVersion).where(ModelVersion.is_active.is_(True)).order_by(desc(ModelVersion.created_at)).limit(1))


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(value)) for value in weights.values()) or 1.0
    return {key: round(max(0.0, float(value)) / total, 4) for key, value in weights.items()}


def metric_block(rows: list[PredictionOutcome]) -> dict:
    if not rows:
        return {"sample_count": 0, "accuracy": None, "average_return": None, "average_drawdown": None, "profit_factor": None, "sharpe_proxy": None, "max_drawdown": None}
    correct = sum(1 for row in rows if row.outcome_label == "correct")
    wrong = sum(1 for row in rows if row.outcome_label == "wrong")
    usable = correct + wrong
    returns = [float(row.realized_return) for row in rows if row.realized_return is not None]
    drawdowns = [float(row.drawdown) for row in rows if row.drawdown is not None]
    positives = [value for value in returns if value > 0]
    negatives = [abs(value) for value in returns if value < 0]
    return {
        "sample_count": len(rows),
        "accuracy": round(correct / usable, 4) if usable else None,
        "win_rate": round(correct / max(1, len(rows)), 4),
        "average_return": round(mean(returns), 4) if returns else None,
        "average_drawdown": round(mean(drawdowns), 4) if drawdowns else None,
        "profit_factor": round(sum(positives) / max(0.01, sum(negatives)), 4) if returns else None,
        "sharpe_proxy": round(mean(returns) / max(0.01, stdev(returns)), 4) if len(returns) > 2 else None,
        "max_drawdown": round(min(drawdowns), 4) if drawdowns else None,
        "false_positive_rate": round(sum(1 for row in rows if row.false_positive) / max(1, len(rows)), 4),
    }


def confidence_calibration(rows: list[PredictionOutcome]) -> dict:
    values = [row.confidence_calibration_error for row in rows if row.confidence_calibration_error is not None]
    if not values:
        return {"status": "insufficient_sample", "mean_absolute_error": None, "sample_count": 0}
    error = mean(float(value) for value in values)
    return {"status": "calibrated" if error <= 0.28 else "needs_attention", "mean_absolute_error": round(error, 4), "sample_count": len(values)}


def serialize_run(row: LearningRun | None) -> dict | None:
    if row is None:
        return None
    return {
        "run_id": row.run_id,
        "trigger": row.trigger,
        "status": row.status,
        "evaluation_mode": row.evaluation_mode,
        "batch_size": row.batch_size,
        "predictions_created": row.predictions_created,
        "outcomes_evaluated": row.outcomes_evaluated,
        "mistakes_found": row.mistakes_found,
        "memory_updates": row.memory_updates,
        "started_at": iso(row.started_at),
        "completed_at": iso(row.completed_at),
        "summary": row.summary,
        "anti_overfitting_report": row.anti_overfitting_report,
    }


def serialize_prediction(row: HistoricalPrediction) -> dict:
    return {
        "id": row.id,
        "ticker": row.ticker,
        "asset_type": row.asset_type,
        "sector": row.sector,
        "market": row.market,
        "analysis_date": iso(row.analysis_date),
        "initial_price": row.initial_price,
        "expected_direction": row.expected_direction,
        "confidence": row.confidence,
        "market_regime": row.market_regime,
        "volatility_regime": row.volatility_regime,
        "data_quality_score": row.data_quality_score,
        "prediction": row.prediction_payload.get("prediction", {}) if row.prediction_payload else {},
        "timeframes": row.prediction_payload.get("timeframes", {}) if row.prediction_payload else {},
        "created_at": iso(row.created_at),
    }


def serialize_signal_performance(row: SignalPerformance) -> dict:
    return {
        "signal_name": row.signal_name,
        "timeframe": row.timeframe,
        "market_regime": row.market_regime,
        "sample_count": row.sample_count,
        "correct_count": row.correct_count,
        "false_positive_count": row.false_positive_count,
        "false_negative_count": row.false_negative_count,
        "average_return": row.average_return,
        "average_drawdown": row.average_drawdown,
        "profit_factor": row.profit_factor,
        "reliability_score": row.reliability_score,
        "weight_adjustment": row.weight_adjustment,
        "updated_at": iso(row.updated_at),
    }


def serialize_strategy_memory(row: StrategyMemory) -> dict:
    return {
        "memory_key": row.memory_key,
        "category": row.category,
        "lesson": row.lesson,
        "conditions": row.conditions,
        "reliability_score": row.reliability_score,
        "sample_count": row.sample_count,
        "positive_count": row.positive_count,
        "negative_count": row.negative_count,
        "last_seen_at": iso(row.last_seen_at),
    }


def serialize_model_version(row: ModelVersion) -> dict:
    return {
        "version": row.version,
        "model_name": row.model_name,
        "is_active": row.is_active,
        "weights": row.weights,
        "validation_metrics": row.validation_metrics,
        "anti_overfitting_report": row.anti_overfitting_report,
        "change_log": row.change_log,
        "created_at": iso(row.created_at),
    }


def fundamental_reason(fundamentals: dict) -> str:
    if fundamentals.get("status") == "ready":
        return f"Point-in-time verified fundamentals available with quality score {fundamentals.get('quality_score')}."
    return "Fundamentals are not point-in-time verified for this simulated date and are not used as hard evidence."


def sentiment_reason(news: dict) -> str:
    return f"{news.get('article_count_14d', 0)} linked headlines in the prior 14 days; average source quality {news.get('average_quality_14d', 0)}."


def narrative_reason(news: dict) -> str:
    themes = ", ".join(item["theme"] for item in news.get("themes_14d", [])[:4]) or "no dominant stored theme"
    return f"Dominant point-in-time themes: {themes}."


def risk_label(context: dict, scores: dict) -> str:
    if context["market_context"]["market_regime"] in {"Panic", "Risk-Off"} or scores.get("volatility_control", 50) < 42:
        return "High"
    if min(scores.values()) < 42:
        return "Medium"
    return "Low/Medium"


def missing_data(context: dict) -> list[str]:
    missing = []
    if context["fundamentals"].get("status") != "ready":
        missing.append("point-in-time verified fundamentals")
    if context["news"].get("article_count_total_as_of", 0) == 0:
        missing.append("linked historical news")
    if context["macro"].get("status") != "ready":
        missing.append("macro snapshots")
    return missing or ["no critical missing point-in-time field"]


def serialize_asset(asset: Asset) -> dict:
    return {
        "ticker": asset.ticker,
        "name": asset.name,
        "asset_type": asset.asset_type,
        "sector": asset.sector,
        "industry": asset.industry,
        "country": asset.country,
        "currency": asset.currency,
        "exchange": asset.exchange,
    }


def stable_key(category: str, lesson: str) -> str:
    return f"{category}:{hashlib.sha256(lesson.encode('utf-8')).hexdigest()[:18]}"


def parse_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except Exception:
        return None


def as_date(value) -> date | None:
    return parse_date(value)


def pct(start: float, end: float) -> float:
    return ((end / start) - 1) * 100 if start else 0.0


def safe_float(value) -> float:
    try:
        if value is None:
            return 0.0
        numeric = float(value)
        return numeric if math.isfinite(numeric) else 0.0
    except (TypeError, ValueError):
        return 0.0


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def round_float(value) -> float | None:
    return round(safe_float(value), 4) if value is not None else None


def iso(value) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else str(value) if value is not None else None


def json_safe(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items() if key not in {"past_prices", "future_prices"}}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except Exception:
            pass
    return str(value)
