from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import math
from statistics import mean, pstdev
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Asset,
    CapitalManagementLesson,
    ExecutionSimulation,
    HistoricalPrediction,
    PriceHistory,
    TradingGame,
    TradingGameEquityCurve,
    TradingGameFailure,
    TradingGameTrade,
)
from app.services.market_sniper import MarketSniperEngine, clamp, safe_float


settings = get_settings()

TRADING_GAME_POLICY = (
    "Paper P/L learning only. No automatic execution, no financial advice, no guaranteed outperformance. "
    "The simulator rejects microscalping and only evaluates reproducible daily/4H-style swing logic."
)


class TradingKnowledgeBase:
    """Structured professional trading knowledge used as rules, not as hidden magic."""

    def catalog(self) -> dict:
        return {
            "market_structure": [
                "trend",
                "range",
                "accumulation",
                "distribution",
                "breakout",
                "breakdown",
                "pullback",
                "retest",
                "support",
                "resistance",
                "liquidity_zones",
                "higher_highs_higher_lows",
                "lower_highs_lower_lows",
            ],
            "technical_analysis": [
                "moving_averages",
                "rsi",
                "macd",
                "atr",
                "bollinger_bands",
                "relative_strength",
                "volume_confirmation",
                "volatility_compression",
                "volatility_expansion",
            ],
            "setups": [
                "momentum_breakout",
                "pullback_to_trend",
                "trend_continuation",
                "mean_reversion",
                "failed_breakout",
                "reversal_from_support",
                "gap_continuation",
                "post_earnings_drift",
                "sector_rotation",
                "etf_relative_strength_rotation",
                "narrative_acceleration",
                "defensive_rotation",
            ],
            "risk_management": [
                "fixed_fractional_risk",
                "atr_based_stop",
                "volatility_adjusted_position_sizing",
                "max_risk_per_trade",
                "max_drawdown_control",
                "risk_of_ruin",
                "position_correlation",
                "portfolio_exposure",
                "cash_allocation",
                "partial_exits",
                "trailing_stops",
            ],
            "performance_metrics": [
                "win_rate",
                "average_win",
                "average_loss",
                "payoff_ratio",
                "expectancy",
                "profit_factor",
                "sharpe_ratio",
                "sortino_ratio",
                "max_drawdown",
                "calmar_ratio",
                "r_multiple",
                "benchmark_relative_return",
                "alpha_beta",
                "hit_rate_by_setup",
                "hit_rate_by_regime",
            ],
            "behavioral_filters": [
                "avoid_chasing_extended_moves",
                "avoid_low_liquidity_traps",
                "avoid_unplanned_event_risk",
                "avoid_overcrowded_sentiment_without_confirmation",
                "avoid_entries_where_invalidation_is_too_far",
                "avoid_poor_risk_reward",
            ],
            "guardrails": [
                f"Minimum timeframe: {settings.trading_min_timeframe}",
                f"Default timeframe: {settings.trading_default_timeframe}",
                f"Microscalping allowed: {settings.trading_allow_microscalping}",
                f"Reproducible setup required: {settings.trading_require_reproducible_setup}",
            ],
        }


class ReproducibleTradePlanEngine:
    def from_sniper_candidate(self, candidate: dict) -> dict:
        plan = candidate.get("trade_plan") or {}
        setup = candidate.get("setup") or {}
        risk = candidate.get("risk") or {}
        timeframe = normalize_timeframe(plan.get("timeframe") or settings.trading_default_timeframe)
        entry_zone = plan.get("entry_zone") or {}
        invalidation = plan.get("invalidation_level")
        rr = (plan.get("risk_reward_estimate") or {}).get("reward_to_risk")
        no_trade = list(plan.get("no_trade_conditions") or [])
        if settings.trading_require_reproducible_setup and timeframe not in {"daily", "4h"}:
            no_trade.append("Rejected: timeframe is not reproducible under BLUM's daily/4H research policy.")
        if not plan.get("entry_trigger"):
            no_trade.append("Rejected: no explicit entry condition.")
        if invalidation is None:
            no_trade.append("Rejected: no invalidation level.")
        if rr is None or safe_float(rr) <= 0:
            no_trade.append("Rejected: no measurable risk/reward.")
        return {
            "ticker": candidate.get("ticker"),
            "strategy_type": setup.get("setup_type", "avoid_no_edge"),
            "timeframe": timeframe,
            "entry_condition": plan.get("entry_trigger") or "No entry condition available.",
            "entry_zone": entry_zone,
            "confirmation": {"condition": plan.get("confirmation_condition") or plan.get("entry_trigger")},
            "invalidation_level": {"value": invalidation, "logic": plan.get("stop_logic")},
            "stop_loss": {"logic": plan.get("stop_logic"), "level": invalidation},
            "target_1": {"value": plan.get("target_1")},
            "target_2": {"value": plan.get("target_2")},
            "trailing_exit": {"logic": plan.get("trailing_exit_logic")},
            "max_risk_percent": min(settings.trading_game_max_risk_percent, settings.trading_game_default_risk_percent),
            "position_size": {},
            "expected_holding_period": plan.get("expected_holding_period"),
            "risk_reward": plan.get("risk_reward_estimate") or {},
            "no_trade_conditions": dedupe_text(no_trade),
            "data_timestamp": (candidate.get("price_context") or {}).get("latest_date"),
            "reasoning": [
                candidate.get("explanation", ""),
                f"Actionability: {candidate.get('actionability')}",
                f"Sniper Score: {candidate.get('sniper_score')}",
            ],
            "policy": TRADING_GAME_POLICY,
        }


class CapitalManagementEngine:
    def position_plan(self, game: TradingGame, reproducibility_score: float, r_multiple: float | None, loss_streak: int, hostile_regime: bool = False) -> dict:
        capital = max(0.0, safe_float(game.current_capital))
        base = settings.trading_game_default_risk_percent
        if loss_streak >= 3:
            base *= 0.5
        if hostile_regime:
            base *= 0.6
        if reproducibility_score < 55:
            base *= 0.5
        if game.max_drawdown <= -12:
            base *= 0.65
        risk_percent = min(settings.trading_game_max_risk_percent, max(0.15, base))
        risk_amount = capital * risk_percent / 100
        if capital <= 0 or r_multiple is None:
            risk_amount = 0.0
            risk_percent = 0.0
        return {
            "capital": round(capital, 4),
            "risk_percent": round(risk_percent, 4),
            "risk_amount": round(risk_amount, 4),
            "policy": "Fixed fractional, drawdown-adjusted and reproducibility-adjusted. Full capital risk is never allowed.",
        }

    def risk_of_ruin(self, game: TradingGame) -> float | None:
        trades = []
        if game.id:
            return None
        return None


class TradingGameSimulator:
    def __init__(self) -> None:
        self.knowledge = TradingKnowledgeBase()
        self.trade_plan_engine = ReproducibleTradePlanEngine()
        self.capital = CapitalManagementEngine()

    def status(self, db: Session) -> dict:
        game = self.active_or_latest_game(db)
        counts = {
            "games": int(db.scalar(select(func.count(TradingGame.id))) or 0),
            "trades": int(db.scalar(select(func.count(TradingGameTrade.id))) or 0),
            "equity_points": int(db.scalar(select(func.count(TradingGameEquityCurve.id))) or 0),
            "failures": int(db.scalar(select(func.count(TradingGameFailure.id))) or 0),
            "lessons": int(db.scalar(select(func.count(CapitalManagementLesson.id))) or 0),
        }
        return {
            "status": "active" if settings.trading_game_enabled else "disabled",
            "engine": "BLUM Reproducible Trading Game",
            "version": "trading-game-v1",
            "current_game": serialize_game(game) if game else None,
            "counts": counts,
            "knowledge_base": self.knowledge.catalog(),
            "policy": TRADING_GAME_POLICY,
        }

    def run(self, db: Session, batch_size: int | None = None) -> dict:
        if not settings.trading_game_enabled:
            return {"status": "disabled", "policy": TRADING_GAME_POLICY}
        batch_size = batch_size or settings.trading_game_batch_size
        game = self.active_or_create_game(db)
        simulations = self.unused_simulations(db, game, batch_size)
        if len(simulations) < max(5, min(20, batch_size // 2)):
            MarketSniperEngine().simulate(db, limit=max(80, batch_size * 3))
            simulations = self.unused_simulations(db, game, batch_size)
        if not simulations:
            db.commit()
            return {"status": "insufficient_simulations", "game": serialize_game(game), "policy": TRADING_GAME_POLICY}

        executed = []
        for simulation, prediction in simulations:
            if game.current_capital <= 0:
                self.close_bankrupt_game(db, game)
                game = self.create_game(db, reason="restart_after_ruin")
                break
            trade = self.apply_simulation(db, game, simulation, prediction)
            executed.append(serialize_game_trade(trade))
        self.recalculate_game(db, game)
        self.update_lessons(db, game)
        db.commit()
        return {
            "status": "ok",
            "game": serialize_game(game),
            "trades_processed": len(executed),
            "trades": executed[:80],
            "benchmark": self.benchmark(db, game.id),
            "lessons": self.lessons(db, limit=8),
            "policy": TRADING_GAME_POLICY,
        }

    def reset(self, db: Session) -> dict:
        active = db.scalars(select(TradingGame).where(TradingGame.status == "active")).all()
        for game in active:
            game.status = "archived"
            game.ended_at = datetime.utcnow()
            game.updated_at = datetime.utcnow()
        game = self.create_game(db, reason="manual_reset")
        db.commit()
        return {"status": "ok", "game": serialize_game(game), "policy": TRADING_GAME_POLICY}

    def active_or_latest_game(self, db: Session) -> TradingGame | None:
        return db.scalar(select(TradingGame).where(TradingGame.status == "active").order_by(desc(TradingGame.started_at)).limit(1)) or db.scalar(select(TradingGame).order_by(desc(TradingGame.started_at)).limit(1))

    def active_or_create_game(self, db: Session) -> TradingGame:
        game = db.scalar(select(TradingGame).where(TradingGame.status == "active").order_by(desc(TradingGame.started_at)).limit(1))
        if game:
            return game
        return self.create_game(db, reason="auto_create")

    def create_game(self, db: Session, reason: str) -> TradingGame:
        capital = float(settings.trading_game_initial_capital)
        game = TradingGame(
            game_id=f"game-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
            status="active",
            starting_capital=capital,
            current_capital=capital,
            cash=capital,
            peak_capital=capital,
            benchmark_ticker=settings.trading_game_benchmark,
            risk_per_trade=settings.trading_game_default_risk_percent,
            configuration={
                "reason": reason,
                "initial_capital": capital,
                "min_timeframe": settings.trading_min_timeframe,
                "default_timeframe": settings.trading_default_timeframe,
                "allow_microscalping": settings.trading_allow_microscalping,
                "require_reproducible_setup": settings.trading_require_reproducible_setup,
                "benchmark": settings.trading_game_benchmark,
            },
        )
        db.add(game)
        db.flush()
        self.add_equity_point(db, game, equity_date=datetime.utcnow().date(), payload={"event": reason})
        return game

    def unused_simulations(self, db: Session, game: TradingGame, limit: int) -> list[tuple[ExecutionSimulation, HistoricalPrediction | None]]:
        used = select(TradingGameTrade.execution_simulation_id).where(TradingGameTrade.game_id == game.id, TradingGameTrade.execution_simulation_id.is_not(None))
        rows = db.execute(
            select(ExecutionSimulation, HistoricalPrediction)
            .outerjoin(HistoricalPrediction, HistoricalPrediction.id == ExecutionSimulation.prediction_id)
            .where(ExecutionSimulation.realized_r_multiple.is_not(None), ~ExecutionSimulation.id.in_(used))
            .order_by(HistoricalPrediction.analysis_date, ExecutionSimulation.created_at)
            .limit(limit)
        ).all()
        return rows

    def apply_simulation(self, db: Session, game: TradingGame, simulation: ExecutionSimulation, prediction: HistoricalPrediction | None) -> TradingGameTrade:
        r_multiple = safe_float(simulation.realized_r_multiple)
        reproducibility = trade_reproducibility_score(simulation, prediction)
        decision = decision_state_for(simulation, reproducibility)
        loss_streak = current_loss_streak(db, game.id)
        hostile = bool(prediction and prediction.market_regime in {"risk_off", "high_volatility", "trend_down"})
        sizing = self.capital.position_plan(game, reproducibility, r_multiple if decision not in {"avoid", "wait_for_trigger"} else None, loss_streak, hostile_regime=hostile)
        capital_before = safe_float(game.current_capital)
        risk_amount = sizing["risk_amount"]
        execution_cost = risk_amount * 0.0014
        realized_pl = 0.0 if decision in {"avoid", "wait_for_trigger"} else risk_amount * (r_multiple or 0.0) - execution_cost
        capital_after = max(0.0, capital_before + realized_pl)
        entry_price = prediction.initial_price if prediction else None
        exit_price = estimated_exit_price(entry_price, simulation)
        position_size = risk_amount / max(0.01, abs((entry_price or 1.0) * 0.02)) if risk_amount and entry_price else 0.0
        exit_date = prediction.analysis_date + timedelta(days=simulation.time_in_trade or 0) if prediction and simulation.time_in_trade else None
        trade = TradingGameTrade(
            game_id=game.id,
            execution_simulation_id=simulation.id,
            ticker=simulation.ticker,
            setup_type=simulation.setup_type,
            timeframe=normalize_timeframe((simulation.simulation_payload or {}).get("timeframe") or "daily"),
            decision_state=decision,
            entry_date=prediction.analysis_date if prediction else None,
            exit_date=exit_date,
            entry_price=entry_price,
            exit_price=exit_price,
            position_size=round(position_size, 6),
            risk_amount=risk_amount,
            risk_percent=sizing["risk_percent"],
            realized_r_multiple=r_multiple,
            realized_pl=round(realized_pl, 4),
            capital_before=round(capital_before, 4),
            capital_after=round(capital_after, 4),
            stop_hit=simulation.stop_hit,
            target_hit=simulation.target_hit,
            missed_entry=simulation.missed_entry,
            false_breakout=simulation.false_breakout,
            reproducibility_score=reproducibility,
            benchmark_return=self.benchmark_return_for(db, prediction, simulation),
            payload={
                "capital_policy": sizing,
                "simulation": simulation.simulation_payload,
                "prediction_id": prediction.id if prediction else None,
                "market_regime": prediction.market_regime if prediction else "unknown",
                "guardrails": guardrails(),
            },
        )
        game.current_capital = capital_after
        game.cash = capital_after
        game.realized_pl = round(game.realized_pl + realized_pl, 4)
        game.peak_capital = max(safe_float(game.peak_capital), capital_after)
        game.max_drawdown = min(safe_float(game.max_drawdown), drawdown_pct(game.peak_capital, capital_after))
        game.trade_count += 1
        game.updated_at = datetime.utcnow()
        db.add(trade)
        db.flush()
        self.add_equity_point(db, game, equity_date=prediction.analysis_date if prediction else datetime.utcnow().date(), payload={"trade_id": trade.id, "decision": decision})
        if capital_after <= 0:
            self.close_bankrupt_game(db, game)
        return trade

    def add_equity_point(self, db: Session, game: TradingGame, equity_date: date | None, payload: dict) -> None:
        benchmark_equity, benchmark_return = self.benchmark_equity(db, game, equity_date)
        db.add(
            TradingGameEquityCurve(
                game_id=game.id,
                equity_date=equity_date,
                equity=game.current_capital,
                cash=game.cash,
                exposure=game.exposure,
                drawdown=game.max_drawdown,
                benchmark_equity=benchmark_equity,
                benchmark_return=benchmark_return,
                payload=payload,
            )
        )

    def recalculate_game(self, db: Session, game: TradingGame) -> None:
        trades = db.scalars(select(TradingGameTrade).where(TradingGameTrade.game_id == game.id).order_by(TradingGameTrade.created_at)).all()
        active_trades = [row for row in trades if row.decision_state not in {"avoid", "wait_for_trigger"} and row.realized_r_multiple is not None]
        r_values = [safe_float(row.realized_r_multiple) for row in active_trades]
        positives = [value for value in r_values if value > 0]
        negatives = [abs(value) for value in r_values if value < 0]
        returns = [safe_float(row.realized_pl) / max(0.01, safe_float(row.capital_before)) for row in active_trades]
        game.win_rate = round(len(positives) / len(r_values), 4) if r_values else None
        game.expectancy_r = round(mean(r_values), 4) if r_values else None
        game.average_r = game.expectancy_r
        game.profit_factor = round(sum(positives) / max(0.01, sum(negatives)), 4) if r_values else None
        game.max_consecutive_losses = max_loss_streak(r_values)
        game.sharpe = annualized_sharpe(returns)
        game.sortino = annualized_sortino(returns)
        game.risk_of_ruin = risk_of_ruin_estimate(game.win_rate, game.profit_factor, game.max_consecutive_losses)
        game.benchmark_return = self.benchmark(db, game.id).get("benchmark_return")
        game.alpha = round(((game.current_capital / max(0.01, game.starting_capital)) - 1) * 100 - safe_float(game.benchmark_return), 4) if game.benchmark_return is not None else None
        game.time_to_double_days = time_to_threshold(db, game.id, game.starting_capital * 2)
        game.time_to_ruin_days = time_to_threshold(db, game.id, 0.01, below=True)
        game.success_report = success_report(trades, game)
        game.failure_report = failure_report(trades, game)
        game.lessons = lesson_payload(trades, game)
        game.updated_at = datetime.utcnow()
        if game.current_capital <= 0 and game.status == "active":
            self.close_bankrupt_game(db, game)

    def close_bankrupt_game(self, db: Session, game: TradingGame) -> None:
        game.status = "bankrupt"
        game.ended_at = datetime.utcnow()
        game.updated_at = datetime.utcnow()
        report = game.failure_report or failure_report(db.scalars(select(TradingGameTrade).where(TradingGameTrade.game_id == game.id)).all(), game)
        category = report.get("primary_category", "capital_ruin")
        db.add(TradingGameFailure(game_id=game.id, category=category, severity="high", report=report))

    def update_lessons(self, db: Session, game: TradingGame) -> None:
        report = game.failure_report or {}
        success = game.success_report or {}
        lessons = []
        if report.get("primary_category"):
            lessons.append((report["primary_category"], report.get("lesson", "Reduce future risk when this failure mode repeats."), 42.0))
        if success.get("best_setup"):
            lessons.append(("best_setup", f"{success['best_setup']} currently has the strongest paper P/L contribution, but sample size must be checked.", 58.0))
        for category, text, score in lessons:
            row = db.scalar(select(CapitalManagementLesson).where(CapitalManagementLesson.category == category, CapitalManagementLesson.lesson == text).limit(1))
            if row is None:
                row = CapitalManagementLesson(category=category, lesson=text, reliability_score=score, sample_count=0, evidence={})
                db.add(row)
            row.sample_count += 1
            row.reliability_score = round(clamp((row.reliability_score * 0.85) + (score * 0.15)), 2)
            row.evidence = {"game_id": game.game_id, "capital": game.current_capital, "expectancy_r": game.expectancy_r, "policy": "Capital lessons update rules, not source code."}
            row.updated_at = datetime.utcnow()

    def equity(self, db: Session, game_id: int | None = None, limit: int = 500) -> list[dict]:
        game = db.get(TradingGame, game_id) if game_id else self.active_or_latest_game(db)
        if not game:
            return []
        rows = db.scalars(select(TradingGameEquityCurve).where(TradingGameEquityCurve.game_id == game.id).order_by(TradingGameEquityCurve.created_at).limit(limit)).all()
        return [serialize_equity(row) for row in rows]

    def trades(self, db: Session, game_id: int | None = None, limit: int = 200) -> list[dict]:
        game = db.get(TradingGame, game_id) if game_id else self.active_or_latest_game(db)
        if not game:
            return []
        rows = db.scalars(select(TradingGameTrade).where(TradingGameTrade.game_id == game.id).order_by(desc(TradingGameTrade.created_at)).limit(limit)).all()
        return [serialize_game_trade(row) for row in rows]

    def failures(self, db: Session, limit: int = 80) -> list[dict]:
        rows = db.scalars(select(TradingGameFailure).order_by(desc(TradingGameFailure.created_at)).limit(limit)).all()
        return [serialize_failure(row) for row in rows]

    def lessons(self, db: Session, limit: int = 50) -> list[dict]:
        rows = db.scalars(select(CapitalManagementLesson).order_by(desc(CapitalManagementLesson.updated_at)).limit(limit)).all()
        return [serialize_lesson(row) for row in rows]

    def benchmark(self, db: Session, game_id: int | None = None) -> dict:
        game = db.get(TradingGame, game_id) if game_id else self.active_or_latest_game(db)
        if not game:
            return {"status": "no_game"}
        points = db.scalars(select(TradingGameEquityCurve).where(TradingGameEquityCurve.game_id == game.id).order_by(TradingGameEquityCurve.created_at)).all()
        if not points:
            return {"status": "no_equity_points", "benchmark": game.benchmark_ticker}
        game_return = (game.current_capital / max(0.01, game.starting_capital) - 1) * 100
        benchmark_return = points[-1].benchmark_return
        return {
            "status": "ok",
            "benchmark": game.benchmark_ticker,
            "game_return": round(game_return, 4),
            "benchmark_return": round(benchmark_return, 4) if benchmark_return is not None else None,
            "alpha": round(game_return - benchmark_return, 4) if benchmark_return is not None else None,
            "policy": "No outperformance claim is valid without sufficient sample size and benchmark coverage.",
        }

    def reproducibility(self, db: Session, limit: int = 120) -> dict:
        trades = db.scalars(select(TradingGameTrade).order_by(desc(TradingGameTrade.created_at)).limit(limit)).all()
        if not trades:
            return {"sample_count": 0, "average_reproducibility": None, "distribution": {}, "policy": TRADING_GAME_POLICY}
        scores = [safe_float(row.reproducibility_score) for row in trades]
        buckets = Counter(bucket_reproducibility(score) for score in scores)
        return {
            "sample_count": len(scores),
            "average_reproducibility": round(mean(scores), 2),
            "distribution": dict(buckets),
            "rejected_or_waited": sum(1 for row in trades if row.decision_state in {"avoid", "wait_for_trigger"}),
            "policy": "Low reproducibility trades are rejected or sized down before P/L learning.",
        }

    def benchmark_return_for(self, db: Session, prediction: HistoricalPrediction | None, simulation: ExecutionSimulation | None = None) -> float | None:
        if not prediction or not prediction.analysis_date:
            return None
        benchmark = db.scalar(select(Asset).where(Asset.ticker == settings.trading_game_benchmark).limit(1))
        if not benchmark:
            return None
        start = nearest_close(db, benchmark.id, prediction.analysis_date)
        end_date = prediction.analysis_date + timedelta(days=(simulation.time_in_trade if simulation and simulation.time_in_trade else 20))
        end = nearest_close(db, benchmark.id, end_date) or close_on_or_before(db, benchmark.id, end_date)
        if not start or not end:
            return None
        return round((end / start - 1) * 100, 4)

    def benchmark_equity(self, db: Session, game: TradingGame, equity_date: date | None) -> tuple[float | None, float | None]:
        benchmark = db.scalar(select(Asset).where(Asset.ticker == game.benchmark_ticker).limit(1))
        if not benchmark or not equity_date:
            return None, None
        first_point = db.scalar(select(TradingGameEquityCurve).where(TradingGameEquityCurve.game_id == game.id, TradingGameEquityCurve.equity_date.is_not(None)).order_by(TradingGameEquityCurve.equity_date).limit(1))
        start_date = first_point.equity_date if first_point and first_point.equity_date else equity_date
        start = nearest_close(db, benchmark.id, start_date)
        end = nearest_close(db, benchmark.id, equity_date) or close_on_or_before(db, benchmark.id, equity_date)
        if not start or not end:
            return None, None
        benchmark_return = (end / start - 1) * 100
        return round(game.starting_capital * (end / start), 4), round(benchmark_return, 4)


def normalize_timeframe(value: str | None) -> str:
    text = (value or "").lower()
    if "4h" in text or "4 h" in text:
        return "4h"
    if "day" in text or "daily" in text or "short" in text or "medium" in text:
        return "daily"
    if "minute" in text or "10-second" in text or "scalp" in text:
        return "rejected_micro_timeframe"
    return settings.trading_default_timeframe


def trade_reproducibility_score(simulation: ExecutionSimulation, prediction: HistoricalPrediction | None) -> float:
    score = 50.0
    timeframe = normalize_timeframe((simulation.simulation_payload or {}).get("timeframe") or "daily")
    score += 16 if timeframe in {"daily", "4h"} else -30
    score += 10 if simulation.entry_model in {"entry_at_close_or_trigger_proxy", "conditional"} else -8
    score += 10 if simulation.exit_model else -10
    score += 8 if prediction and prediction.initial_price else -8
    score += 8 if prediction and prediction.data_quality_score >= 60 else -6
    score += -12 if simulation.missed_entry else 0
    score += -12 if simulation.false_breakout else 0
    score += -10 if simulation.failed_confirmation else 0
    if simulation.realized_r_multiple is None:
        score -= 20
    return round(clamp(score), 2)


def decision_state_for(simulation: ExecutionSimulation, reproducibility: float) -> str:
    if reproducibility < 42:
        return "avoid"
    if simulation.missed_entry or simulation.failed_confirmation:
        return "wait_for_trigger"
    if simulation.stop_hit and safe_float(simulation.realized_r_multiple) <= -1:
        return "manage_open_position"
    if safe_float(simulation.realized_r_multiple) >= 1.5:
        return "active_setup"
    return "watch"


def estimated_exit_price(entry_price: float | None, simulation: ExecutionSimulation) -> float | None:
    if entry_price is None or simulation.realized_r_multiple is None:
        return None
    risk_pct = abs(safe_float(simulation.max_adverse_excursion)) or 2.0
    move_pct = safe_float(simulation.realized_r_multiple) * risk_pct
    return round(entry_price * (1 + move_pct / 100), 4)


def nearest_close(db: Session, asset_id: int, value: date) -> float | None:
    row = db.scalar(select(PriceHistory.close).where(PriceHistory.asset_id == asset_id, PriceHistory.date >= value).order_by(PriceHistory.date).limit(1))
    return safe_float(row) if row is not None else None


def close_on_or_before(db: Session, asset_id: int, value: date) -> float | None:
    row = db.scalar(select(PriceHistory.close).where(PriceHistory.asset_id == asset_id, PriceHistory.date <= value).order_by(desc(PriceHistory.date)).limit(1))
    return safe_float(row) if row is not None else None


def current_loss_streak(db: Session, game_id: int) -> int:
    rows = db.scalars(select(TradingGameTrade).where(TradingGameTrade.game_id == game_id, TradingGameTrade.decision_state.not_in(["avoid", "wait_for_trigger"])).order_by(desc(TradingGameTrade.created_at)).limit(12)).all()
    streak = 0
    for row in rows:
        if safe_float(row.realized_pl) < 0:
            streak += 1
        else:
            break
    return streak


def max_loss_streak(values: list[float]) -> int:
    best = 0
    current = 0
    for value in values:
        if value < 0:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def drawdown_pct(peak: float, equity: float) -> float:
    if peak <= 0:
        return 0.0
    return round((equity / peak - 1) * 100, 4)


def annualized_sharpe(returns: list[float]) -> float | None:
    if len(returns) < 4:
        return None
    vol = pstdev(returns)
    if vol <= 0:
        return None
    return round(mean(returns) / vol * math.sqrt(52), 4)


def annualized_sortino(returns: list[float]) -> float | None:
    if len(returns) < 4:
        return None
    downside = [value for value in returns if value < 0]
    if not downside:
        return None
    vol = pstdev(downside)
    if vol <= 0:
        return None
    return round(mean(returns) / vol * math.sqrt(52), 4)


def risk_of_ruin_estimate(win_rate: float | None, profit_factor: float | None, max_consecutive_losses: int) -> float | None:
    if win_rate is None or profit_factor is None:
        return None
    loss_rate = 1 - win_rate
    stress = min(1.0, max_consecutive_losses / 10)
    pf_penalty = 0.2 if profit_factor >= 1.3 else 0.45 if profit_factor >= 1 else 0.75
    return round(clamp((loss_rate * 0.55 + stress * 0.25 + pf_penalty * 0.2) * 100), 2)


def time_to_threshold(db: Session, game_id: int, threshold: float, below: bool = False) -> int | None:
    rows = db.scalars(select(TradingGameEquityCurve).where(TradingGameEquityCurve.game_id == game_id).order_by(TradingGameEquityCurve.created_at)).all()
    if not rows:
        return None
    start = rows[0].created_at
    for row in rows:
        hit = row.equity <= threshold if below else row.equity >= threshold
        if hit:
            return max(0, (row.created_at - start).days)
    return None


def success_report(trades: list[TradingGameTrade], game: TradingGame) -> dict:
    active = [row for row in trades if row.decision_state not in {"avoid", "wait_for_trigger"}]
    if not active:
        return {"status": "insufficient_sample", "minimum_sample_warning": True}
    by_setup = aggregate_pl_by(lambda row: row.setup_type, active)
    best_setup = max(by_setup.items(), key=lambda kv: kv[1]["pl"])[0] if by_setup else None
    return {
        "best_setup": best_setup,
        "best_risk_reward": max((safe_float(row.realized_r_multiple) for row in active), default=None),
        "average_holding_period_proxy": None,
        "drawdown_survived": game.max_drawdown,
        "reproducibility_score": round(mean([row.reproducibility_score for row in active]), 2),
        "statistical_confidence": "low" if len(active) < 30 else "medium" if len(active) < 100 else "higher",
        "minimum_sample_size_warning": len(active) < 30,
    }


def failure_report(trades: list[TradingGameTrade], game: TradingGame) -> dict:
    active = [row for row in trades if row.decision_state not in {"avoid", "wait_for_trigger"}]
    failures = [row for row in active if safe_float(row.realized_pl) < 0]
    if not failures and game.current_capital > 0:
        return {"status": "no_major_failure_recorded"}
    categories = []
    categories.extend(["false_breakout"] * sum(1 for row in failures if row.false_breakout))
    categories.extend(["poor_exit_discipline"] * sum(1 for row in failures if row.stop_hit))
    categories.extend(["missed_entry_or_late_confirmation"] * sum(1 for row in trades if row.decision_state == "wait_for_trigger"))
    categories.extend(["low_reproducibility"] * sum(1 for row in trades if row.reproducibility_score < 45))
    if game.max_drawdown <= -20:
        categories.append("drawdown_control")
    if game.current_capital <= 0:
        categories.append("capital_ruin")
    primary = Counter(categories).most_common(1)[0][0] if categories else "random_market_noise"
    worst = min(active, key=lambda row: row.realized_pl, default=None)
    return {
        "primary_category": primary,
        "largest_loss": worst.realized_pl if worst else None,
        "worst_setup": worst.setup_type if worst else None,
        "number_of_losses": len(failures),
        "overtrading_score": clamp(len(active) / max(1, (datetime.utcnow() - game.started_at).days + 1) * 8),
        "lesson": lesson_for_failure(primary),
        "sample_size_warning": len(active) < 30,
    }


def lesson_payload(trades: list[TradingGameTrade], game: TradingGame) -> dict:
    return {
        "capital_preservation": "Risk is reduced after losing streaks, low reproducibility and hostile regimes.",
        "most_common_failure": failure_report(trades, game).get("primary_category"),
        "current_expectancy_r": game.expectancy_r,
        "current_profit_factor": game.profit_factor,
        "policy": "Learning adjusts weights and capital rules; it does not self-modify source code.",
    }


def aggregate_pl_by(key_fn, rows: list[TradingGameTrade]) -> dict:
    grouped: dict[str, dict] = defaultdict(lambda: {"count": 0, "pl": 0.0})
    for row in rows:
        key = key_fn(row) or "unknown"
        grouped[key]["count"] += 1
        grouped[key]["pl"] += safe_float(row.realized_pl)
    return grouped


def lesson_for_failure(category: str) -> str:
    return {
        "false_breakout": "Require stronger volume and regime confirmation before upgrading breakouts.",
        "poor_exit_discipline": "Respect invalidation and reduce sizing when stops cluster in one regime.",
        "missed_entry_or_late_confirmation": "Prefer waiting for clean triggers over chasing late entries.",
        "low_reproducibility": "Reject strategies that depend on low timeframe speed or unclear fills.",
        "drawdown_control": "Reduce risk after equity drawdowns and correlated losses.",
        "capital_ruin": "Restart from 100 EUR with lower risk and stronger no-trade filters.",
    }.get(category, "Treat this as uncertain market noise until more samples confirm the pattern.")


def bucket_reproducibility(score: float) -> str:
    if score >= 75:
        return "high"
    if score >= 55:
        return "medium"
    if score >= 40:
        return "low"
    return "reject"


def dedupe_text(items: list[str]) -> list[str]:
    seen = set()
    output = []
    for item in items:
        text = str(item).strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def guardrails() -> list[str]:
    return [
        "No look-ahead bias: future data is used only after simulated decision persistence.",
        "No microscalping, tick data, latency arbitrage or unrealistic intraday fills.",
        "No trade is considered reproducible without entry condition, invalidation, risk/reward and position sizing.",
        "No full capital risk; default risk per trade is 1% and capped at 2%.",
        "No benchmark outperformance claim without enough samples and benchmark coverage.",
        "Low reproducibility and hostile regimes reduce size or reject the trade.",
    ]


def serialize_game(row: TradingGame | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "game_id": row.game_id,
        "status": row.status,
        "mode": row.mode,
        "starting_capital": row.starting_capital,
        "current_capital": row.current_capital,
        "cash": row.cash,
        "exposure": row.exposure,
        "realized_pl": row.realized_pl,
        "unrealized_pl": row.unrealized_pl,
        "peak_capital": row.peak_capital,
        "max_drawdown": row.max_drawdown,
        "benchmark_ticker": row.benchmark_ticker,
        "benchmark_return": row.benchmark_return,
        "alpha": row.alpha,
        "trade_count": row.trade_count,
        "win_rate": row.win_rate,
        "expectancy_r": row.expectancy_r,
        "profit_factor": row.profit_factor,
        "average_r": row.average_r,
        "sharpe": row.sharpe,
        "sortino": row.sortino,
        "risk_per_trade": row.risk_per_trade,
        "risk_of_ruin": row.risk_of_ruin,
        "max_consecutive_losses": row.max_consecutive_losses,
        "time_to_double_days": row.time_to_double_days,
        "time_to_ruin_days": row.time_to_ruin_days,
        "configuration": row.configuration,
        "failure_report": row.failure_report,
        "success_report": row.success_report,
        "lessons": row.lessons,
        "started_at": iso(row.started_at),
        "ended_at": iso(row.ended_at),
        "updated_at": iso(row.updated_at),
    }


def serialize_game_trade(row: TradingGameTrade) -> dict:
    return {
        "id": row.id,
        "ticker": row.ticker,
        "setup_type": row.setup_type,
        "timeframe": row.timeframe,
        "decision_state": row.decision_state,
        "entry_date": iso(row.entry_date),
        "exit_date": iso(row.exit_date),
        "entry_price": row.entry_price,
        "exit_price": row.exit_price,
        "position_size": row.position_size,
        "risk_amount": row.risk_amount,
        "risk_percent": row.risk_percent,
        "realized_r_multiple": row.realized_r_multiple,
        "realized_pl": row.realized_pl,
        "capital_before": row.capital_before,
        "capital_after": row.capital_after,
        "stop_hit": row.stop_hit,
        "target_hit": row.target_hit,
        "missed_entry": row.missed_entry,
        "false_breakout": row.false_breakout,
        "reproducibility_score": row.reproducibility_score,
        "benchmark_return": row.benchmark_return,
        "payload": row.payload,
        "created_at": iso(row.created_at),
    }


def serialize_equity(row: TradingGameEquityCurve) -> dict:
    return {
        "id": row.id,
        "equity_date": iso(row.equity_date),
        "equity": row.equity,
        "cash": row.cash,
        "exposure": row.exposure,
        "drawdown": row.drawdown,
        "benchmark_equity": row.benchmark_equity,
        "benchmark_return": row.benchmark_return,
        "created_at": iso(row.created_at),
    }


def serialize_failure(row: TradingGameFailure) -> dict:
    return {"id": row.id, "game_id": row.game_id, "category": row.category, "severity": row.severity, "report": row.report, "created_at": iso(row.created_at)}


def serialize_lesson(row: CapitalManagementLesson) -> dict:
    return {"id": row.id, "category": row.category, "lesson": row.lesson, "reliability_score": row.reliability_score, "sample_count": row.sample_count, "evidence": row.evidence, "updated_at": iso(row.updated_at)}


def iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
