from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from statistics import mean, median
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Asset,
    HistoricalLiveComparison,
    LiveForwardPaperGame,
    LiveForwardPaperPosition,
    PriceHistory,
    TradingCapitalCycle,
    TradingGame,
    TradingGameEquityCurve,
    TradingGameTrade,
    TradingIntelligenceMetric,
)
from app.services.trade_transparency import (
    TRANSPARENCY_POLICY,
    TradeLedgerService,
    order_trade_query,
    safe_float,
    clamp,
)


settings = get_settings()

LAB_POLICY = (
    "Trading Intelligence Lab is paper research only. Historical simulation and live forward paper data are "
    "evidence streams, not financial advice and not proof of future outperformance."
)


class AdvancedTradeLedgerAnalyticsService:
    """Filterable, aggregatable trade ledger analytics across every simulated action."""

    def ledger(self, db: Session, **kwargs) -> dict:
        return TradeLedgerService().ledger(db, **kwargs)

    def summary(self, db: Session, game_id: int | None = None, **filters) -> dict:
        game = TradeLedgerService().game(db, game_id)
        if not game:
            return {"status": "no_game", "summary": {}, "policy": LAB_POLICY}
        TradingCapitalCycleService().ensure_current_cycle(db, game, mutate=False)
        rows = db.scalars(query_trades(game.id, **filters)).all()
        return {"status": "ok", "game": serialize_game_lab(game), "summary": ledger_summary(rows), "policy": LAB_POLICY}

    def by_ticker(self, db: Session, ticker: str, game_id: int | None = None, limit: int = 200) -> dict:
        game = TradeLedgerService().game(db, game_id)
        if not game:
            return {"status": "no_game", "rows": []}
        rows = db.scalars(query_trades(game.id, ticker=ticker).order_by(desc(TradingGameTrade.created_at)).limit(limit)).all()
        return {"status": "ok", "ticker": ticker.upper(), "summary": ledger_summary(rows), "rows": [TradeLedgerService().serialize_trade(db, row) for row in rows], "policy": LAB_POLICY}

    def by_setup(self, db: Session, setup_type: str, game_id: int | None = None, limit: int = 200) -> dict:
        game = TradeLedgerService().game(db, game_id)
        if not game:
            return {"status": "no_game", "rows": []}
        rows = db.scalars(query_trades(game.id, setup_type=setup_type).order_by(desc(TradingGameTrade.created_at)).limit(limit)).all()
        return {"status": "ok", "setup_type": setup_type, "summary": ledger_summary(rows), "rows": [TradeLedgerService().serialize_trade(db, row) for row in rows], "policy": LAB_POLICY}

    def by_outcome(self, db: Session, outcome_label: str, game_id: int | None = None, limit: int = 200) -> dict:
        game = TradeLedgerService().game(db, game_id)
        if not game:
            return {"status": "no_game", "rows": []}
        rows = db.scalars(query_trades(game.id, outcome_label=outcome_label).order_by(desc(TradingGameTrade.created_at)).limit(limit)).all()
        return {"status": "ok", "outcome_label": outcome_label, "summary": ledger_summary(rows), "rows": [TradeLedgerService().serialize_trade(db, row) for row in rows], "policy": LAB_POLICY}

    def by_cycle(self, db: Session, cycle_id: int, limit: int = 500) -> dict:
        cycle = db.get(TradingCapitalCycle, cycle_id)
        if not cycle:
            return {"status": "not_found", "cycle_id": cycle_id, "rows": []}
        rows = db.scalars(
            select(TradingGameTrade)
            .where(TradingGameTrade.capital_cycle_id == cycle.id)
            .order_by(desc(TradingGameTrade.created_at))
            .limit(limit)
        ).all()
        return {"status": "ok", "cycle": serialize_cycle(cycle), "summary": ledger_summary(rows), "rows": [TradeLedgerService().serialize_trade(db, row) for row in rows], "policy": LAB_POLICY}


class TradingCapitalCycleService:
    """Caps the paper bankroll into auditable 100 EUR to target cycles."""

    def ensure_current_cycle(self, db: Session, game: TradingGame | None = None, mutate: bool = True) -> TradingCapitalCycle | None:
        game = game or TradeLedgerService().game(db)
        if not game:
            return None
        if game.target_capital is None and mutate:
            game.target_capital = settings.trading_game_target_capital
        active = db.scalar(
            select(TradingCapitalCycle)
            .where(TradingCapitalCycle.game_id == game.id, TradingCapitalCycle.status == "active")
            .order_by(desc(TradingCapitalCycle.started_at))
            .limit(1)
        )
        if active:
            self.refresh_cycle(db, active)
            if mutate:
                self.enforce_boundaries(db, game, active)
            return active

        if not mutate:
            return db.scalar(
                select(TradingCapitalCycle)
                .where(TradingCapitalCycle.game_id == game.id)
                .order_by(desc(TradingCapitalCycle.cycle_number))
                .limit(1)
            )

        latest_number = int(db.scalar(select(func.max(TradingCapitalCycle.cycle_number)).where(TradingCapitalCycle.game_id == game.id)) or 0)
        if mutate and latest_number == 0 and safe_float(game.current_capital) >= settings.trading_game_target_capital:
            legacy = self.create_cycle(db, game, latest_number + 1, status="active", start_capital=settings.trading_game_initial_capital)
            self.backfill_uncycled_trades(db, game, legacy)
            self.close_cycle(db, game, legacy, "target_reached", "Legacy active game already exceeded target before cycle tracking was introduced.")
            self.reset_game_for_new_cycle(game)
            return self.create_cycle(db, game, latest_number + 2, status="active", start_capital=settings.trading_game_initial_capital)

        return self.create_cycle(db, game, latest_number + 1, status="active", start_capital=safe_float(game.current_capital, settings.trading_game_initial_capital))

    def record_trade(self, db: Session, game: TradingGame, trade: TradingGameTrade) -> TradingCapitalCycle | None:
        cycle = self.ensure_current_cycle(db, game)
        if not cycle:
            return None
        trade.capital_cycle_id = cycle.id
        trade.mode = trade.mode or "historical_simulation"
        self.refresh_cycle(db, cycle)
        self.enforce_boundaries(db, game, cycle)
        return cycle

    def enforce_boundaries(self, db: Session, game: TradingGame, cycle: TradingCapitalCycle) -> None:
        target = safe_float(game.target_capital, settings.trading_game_target_capital)
        if safe_float(game.current_capital) >= target and settings.trading_game_reset_on_target:
            self.close_cycle(db, game, cycle, "target_reached", f"Cycle reached the {target:.2f} EUR target and was reset to preserve realism.")
            self.reset_game_for_new_cycle(game)
            self.create_cycle(db, game, cycle.cycle_number + 1, status="active", start_capital=settings.trading_game_initial_capital)
        elif safe_float(game.current_capital) <= 0 and settings.trading_game_reset_on_bankruptcy:
            self.close_cycle(db, game, cycle, "bankrupt", "Paper capital reached zero; cycle restarted with stricter learning context.")
            self.reset_game_for_new_cycle(game)
            self.create_cycle(db, game, cycle.cycle_number + 1, status="active", start_capital=settings.trading_game_initial_capital)
        elif cycle.started_at and (datetime.utcnow() - cycle.started_at).days >= settings.trading_game_max_cycle_days:
            self.close_cycle(db, game, cycle, "expired", "Cycle exceeded max configured age and was archived for clean measurement.")
            self.reset_game_for_new_cycle(game)
            self.create_cycle(db, game, cycle.cycle_number + 1, status="active", start_capital=settings.trading_game_initial_capital)

    def create_cycle(self, db: Session, game: TradingGame, cycle_number: int, status: str, start_capital: float) -> TradingCapitalCycle:
        cycle = TradingCapitalCycle(
            game_id=game.id,
            cycle_number=cycle_number,
            status=status,
            start_capital=round(start_capital, 4),
            target_capital=settings.trading_game_target_capital,
            final_capital=round(start_capital, 4),
            lessons_json={"policy": "Cycle starts at fixed paper capital and is closed at target, bankruptcy, manual close or expiry."},
        )
        db.add(cycle)
        db.flush()
        game.active_cycle_id = cycle.id if status == "active" else game.active_cycle_id
        game.target_capital = settings.trading_game_target_capital
        return cycle

    def close_cycle(self, db: Session, game: TradingGame, cycle: TradingCapitalCycle, status: str, reason: str) -> None:
        self.refresh_cycle(db, cycle)
        cycle.status = status
        cycle.ended_at = datetime.utcnow()
        cycle.final_capital = safe_float(game.current_capital)
        cycle.reached_target = status == "target_reached"
        cycle.went_to_zero = status == "bankrupt"
        cycle.success_reason = reason if status == "target_reached" else cycle.success_reason
        cycle.failure_reason = reason if status == "bankrupt" else cycle.failure_reason
        cycle.updated_at = datetime.utcnow()
        if status == "target_reached":
            game.target_cycles_completed = int(game.target_cycles_completed or 0) + 1
        if status == "bankrupt":
            game.bankrupt_cycles = int(game.bankrupt_cycles or 0) + 1
        game.active_cycle_id = None

    def reset_game_for_new_cycle(self, game: TradingGame) -> None:
        capital = float(settings.trading_game_initial_capital)
        game.current_capital = capital
        game.cash = capital
        game.exposure = 0.0
        game.unrealized_pl = 0.0
        game.peak_capital = capital
        game.max_drawdown = 0.0
        game.realized_pl = 0.0
        game.updated_at = datetime.utcnow()

    def backfill_uncycled_trades(self, db: Session, game: TradingGame, cycle: TradingCapitalCycle) -> None:
        rows = db.scalars(select(TradingGameTrade).where(TradingGameTrade.game_id == game.id, TradingGameTrade.capital_cycle_id.is_(None))).all()
        for row in rows:
            row.capital_cycle_id = cycle.id
            row.mode = row.mode or "historical_simulation"
        self.refresh_cycle(db, cycle)

    def refresh_cycle(self, db: Session, cycle: TradingCapitalCycle) -> TradingCapitalCycle:
        rows = db.scalars(select(TradingGameTrade).where(TradingGameTrade.capital_cycle_id == cycle.id).order_by(TradingGameTrade.created_at)).all()
        active = executable_trades(rows)
        labels = Counter(row.outcome_label or row.decision_state for row in rows)
        pnl_values = [safe_float(row.net_pnl_eur if row.net_pnl_eur is not None else row.realized_pl) for row in active]
        r_values = [safe_float(row.realized_r_multiple) for row in active if row.realized_r_multiple is not None]
        positives = [value for value in r_values if value > 0]
        negatives = [abs(value) for value in r_values if value < 0]
        best = max(active, key=lambda row: safe_float(row.net_pnl_eur if row.net_pnl_eur is not None else row.realized_pl), default=None)
        worst = min(active, key=lambda row: safe_float(row.net_pnl_eur if row.net_pnl_eur is not None else row.realized_pl), default=None)
        final_capital = cycle.start_capital + sum(pnl_values)
        cycle.final_capital = round(final_capital, 4)
        cycle.return_percent = round((final_capital / max(0.01, cycle.start_capital) - 1) * 100, 4)
        cycle.trades_count = len(rows)
        cycle.wins = labels["win"] + labels["target_hit"] + labels["partial_profit"]
        cycle.losses = labels["loss"] + labels["stopped_out"]
        cycle.missed_entries = labels["missed_entry"]
        cycle.target_hits = labels["target_hit"]
        cycle.stop_hits = labels["stopped_out"]
        cycle.no_trade_correct = labels["no_trade_correct"]
        cycle.no_trade_missed_opportunity = labels["no_trade_missed_opportunity"]
        cycle.profit_factor = round(sum(positives) / max(0.01, sum(negatives)), 4) if r_values else None
        cycle.expectancy_r = round(mean(r_values), 4) if r_values else None
        cycle.max_drawdown = min((safe_float(row.capital_after) / max(0.01, safe_float(row.capital_before)) - 1) * 100 for row in active) if active else 0.0
        cycle.benchmark_return = round(mean([safe_float(row.benchmark_return_same_period) for row in active if row.benchmark_return_same_period is not None]), 4) if any(row.benchmark_return_same_period is not None for row in active) else None
        cycle.excess_return_vs_benchmark = round(mean([safe_float(row.excess_return_vs_benchmark) for row in active if row.excess_return_vs_benchmark is not None]), 4) if any(row.excess_return_vs_benchmark is not None for row in active) else None
        cycle.best_trade_id = best.id if best else None
        cycle.worst_trade_id = worst.id if worst else None
        cycle.lessons_json = {
            "best_trade": trade_ref(best),
            "worst_trade": trade_ref(worst),
            "sample_warning": len(active) < 30,
            "policy": "Cycle metrics are paper research and must be read with sample-size context.",
        }
        cycle.updated_at = datetime.utcnow()
        return cycle

    def cycles(self, db: Session, game_id: int | None = None, limit: int = 100) -> dict:
        game = TradeLedgerService().game(db, game_id)
        if game:
            self.ensure_current_cycle(db, game)
            query = select(TradingCapitalCycle).where(TradingCapitalCycle.game_id == game.id)
        else:
            query = select(TradingCapitalCycle)
        rows = db.scalars(query.order_by(desc(TradingCapitalCycle.cycle_number)).limit(limit)).all()
        return {"status": "ok", "game": serialize_game_lab(game) if game else None, "cycles": [serialize_cycle(row) for row in rows], "stats": cycle_stats(rows), "policy": LAB_POLICY}

    def current(self, db: Session, game_id: int | None = None) -> dict:
        game = TradeLedgerService().game(db, game_id)
        cycle = self.ensure_current_cycle(db, game) if game else None
        return {"status": "ok" if cycle else "no_cycle", "game": serialize_game_lab(game) if game else None, "cycle": serialize_cycle(cycle) if cycle else None, "policy": LAB_POLICY}

    def get(self, db: Session, cycle_id: int) -> dict:
        cycle = db.get(TradingCapitalCycle, cycle_id)
        return {"status": "ok" if cycle else "not_found", "cycle": serialize_cycle(cycle) if cycle else None, "policy": LAB_POLICY}

    def reset(self, db: Session, game_id: int | None = None) -> dict:
        game = TradeLedgerService().game(db, game_id)
        if not game:
            return {"status": "no_game"}
        active = self.ensure_current_cycle(db, game)
        if active:
            self.close_cycle(db, game, active, "manually_closed", "Manual cycle reset requested.")
        self.reset_game_for_new_cycle(game)
        new_cycle = self.create_cycle(db, game, (active.cycle_number + 1 if active else 1), status="active", start_capital=settings.trading_game_initial_capital)
        db.commit()
        return {"status": "ok", "cycle": serialize_cycle(new_cycle), "game": serialize_game_lab(game), "policy": LAB_POLICY}

    def stats(self, db: Session, game_id: int | None = None) -> dict:
        rows = db.scalars(select(TradingCapitalCycle).where(TradingCapitalCycle.game_id == game_id) if game_id else select(TradingCapitalCycle)).all()
        return {"status": "ok", "stats": cycle_stats(rows), "policy": LAB_POLICY}


class TradingIntelligenceMetricsService:
    """Measures whether trading decisions are improving, not only whether P/L is positive."""

    def overview(self, db: Session, game_id: int | None = None, persist: bool = False) -> dict:
        game = TradeLedgerService().game(db, game_id)
        if not game:
            return {"status": "no_game", "metrics": {}}
        rows = db.scalars(select(TradingGameTrade).where(TradingGameTrade.game_id == game.id).order_by(TradingGameTrade.created_at)).all()
        metrics = metric_payload(rows, scope="game", scope_id=str(game.id), window_type="all", window_size=None)
        if persist:
            self.persist_metric(db, metrics)
            db.commit()
        return {"status": "ok", "game": serialize_game_lab(game), "metrics": metrics, "warnings": intelligence_warnings(metrics), "policy": LAB_POLICY}

    def rolling(self, db: Session, game_id: int | None = None, windows: tuple[int, ...] = (30, 100)) -> dict:
        game = TradeLedgerService().game(db, game_id)
        if not game:
            return {"status": "no_game", "windows": []}
        rows = db.scalars(select(TradingGameTrade).where(TradingGameTrade.game_id == game.id).order_by(TradingGameTrade.created_at)).all()
        payloads = [metric_payload(rows[-window:], scope="game", scope_id=str(game.id), window_type="rolling", window_size=window) for window in windows]
        return {"status": "ok", "windows": payloads, "policy": LAB_POLICY}

    def by_dimension(self, db: Session, dimension: str, game_id: int | None = None) -> dict:
        game = TradeLedgerService().game(db, game_id)
        if not game:
            return {"status": "no_game", "rows": []}
        rows = db.scalars(select(TradingGameTrade).where(TradingGameTrade.game_id == game.id).order_by(TradingGameTrade.created_at)).all()
        key_fn = {
            "setup": lambda row: row.setup_type,
            "regime": lambda row: row.market_regime_at_entry or "unknown",
            "sector": lambda row: row.sector or "Unknown",
            "cycle": lambda row: str(row.capital_cycle_id or "uncycled"),
        }[dimension]
        grouped: dict[str, list[TradingGameTrade]] = defaultdict(list)
        for row in rows:
            grouped[key_fn(row)].append(row)
        output = [metric_payload(items, scope=dimension, scope_id=key, window_type="all", window_size=None) for key, items in grouped.items()]
        output.sort(key=lambda item: safe_float(item.get("intelligence_growth_score")), reverse=True)
        return {"status": "ok", "dimension": dimension, "rows": output, "policy": LAB_POLICY}

    def persist_metric(self, db: Session, payload: dict) -> TradingIntelligenceMetric:
        row = TradingIntelligenceMetric(
            scope=payload["scope"],
            scope_id=payload.get("scope_id"),
            window_type=payload["window_type"],
            window_size=payload.get("window_size"),
            trades_count=payload["trades_count"],
            win_rate=payload.get("win_rate"),
            loss_rate=payload.get("loss_rate"),
            missed_entry_rate=payload.get("missed_entry_rate"),
            target_hit_rate=payload.get("target_hit_rate"),
            stop_hit_rate=payload.get("stop_hit_rate"),
            no_trade_correct_rate=payload.get("no_trade_correct_rate"),
            no_trade_missed_opportunity_rate=payload.get("no_trade_missed_opportunity_rate"),
            expectancy_r=payload.get("expectancy_r"),
            profit_factor=payload.get("profit_factor"),
            average_r=payload.get("average_r"),
            median_r=payload.get("median_r"),
            max_drawdown=payload.get("max_drawdown"),
            benchmark_excess=payload.get("benchmark_excess"),
            entry_timing_score=payload.get("entry_timing_score"),
            exit_timing_score=payload.get("exit_timing_score"),
            sizing_quality_score=payload.get("sizing_quality_score"),
            risk_reward_quality_score=payload.get("risk_reward_quality_score"),
            reproducibility_score=payload.get("reproducibility_score"),
            trade_quality_score=payload.get("trade_quality_score"),
            intelligence_growth_score=payload.get("intelligence_growth_score"),
            notes_json=payload.get("notes_json") or {},
        )
        db.add(row)
        return row


class LiveForwardPaperTradingService:
    """Forward-only paper mode using current BLUM setup evidence without future data."""

    def status(self, db: Session) -> dict:
        game = self.active_or_create_live_game(db)
        positions = db.scalars(select(LiveForwardPaperPosition).where(LiveForwardPaperPosition.game_id == game.id, LiveForwardPaperPosition.status == "open").order_by(desc(LiveForwardPaperPosition.created_at))).all()
        return {"status": "active" if settings.live_trading_game_enabled else "disabled", "game": serialize_live_game(game), "open_positions": [serialize_live_position(row) for row in positions], "policy": LAB_POLICY}

    def run_cycle(self, db: Session) -> dict:
        if not settings.live_trading_game_enabled:
            return {"status": "disabled", "policy": LAB_POLICY}
        game = self.active_or_create_live_game(db)
        closed = self.evaluate_open_positions(db, game)
        if game.open_positions >= settings.live_trading_game_max_open_positions:
            db.commit()
            return {"status": "ok", "opened": [], "closed": closed, "reason": "max_open_positions_reached", "game": serialize_live_game(game), "policy": LAB_POLICY}
        from app.services.market_sniper import MarketSniperEngine

        candidates = MarketSniperEngine().candidates(db, limit=30, persist=False).get("candidates", [])
        opened = []
        for candidate in candidates:
            if game.open_positions >= settings.live_trading_game_max_open_positions:
                break
            if not live_candidate_is_actionable(candidate):
                continue
            if self.has_open_position(db, game, candidate.get("ticker")):
                continue
            opened.append(self.open_position(db, game, candidate))
        db.commit()
        return {"status": "ok", "opened": opened, "closed": closed, "game": serialize_live_game(game), "sample_warning": "Live forward evidence is immature until enough timestamp-frozen trades close.", "policy": LAB_POLICY}

    def active_or_create_live_game(self, db: Session) -> LiveForwardPaperGame:
        game = db.scalar(select(LiveForwardPaperGame).where(LiveForwardPaperGame.status == "active").order_by(desc(LiveForwardPaperGame.started_at)).limit(1))
        if game:
            return game
        game = LiveForwardPaperGame(
            game_id=f"live-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
            starting_capital=settings.live_trading_game_initial_capital,
            current_capital=settings.live_trading_game_initial_capital,
            target_capital=settings.live_trading_game_target_capital,
            cash=settings.live_trading_game_initial_capital,
            benchmark_ticker=settings.live_trading_game_benchmark,
            configuration={
                "max_open_positions": settings.live_trading_game_max_open_positions,
                "max_risk_per_trade": settings.live_trading_game_max_risk_per_trade,
                "require_actionable_setup": settings.live_trading_game_require_actionable_setup,
                "allow_fractional_shares": settings.live_trading_game_allow_fractional_shares,
                "policy": "Forward paper decisions are timestamp-frozen and evaluated only after later market refreshes.",
            },
        )
        db.add(game)
        db.flush()
        return game

    def open_position(self, db: Session, game: LiveForwardPaperGame, candidate: dict) -> dict:
        ticker = candidate.get("ticker")
        price = safe_float((candidate.get("price_context") or {}).get("latest_price"))
        plan = candidate.get("trade_plan") or {}
        risk_amount = game.current_capital * settings.live_trading_game_max_risk_per_trade / 100
        stop = safe_float(plan.get("invalidation_level")) or (price * 0.97 if price else None)
        risk_per_share = abs(price - stop) if price and stop else price * 0.02 if price else 1
        size = risk_amount / max(0.01, risk_per_share)
        trade_game = ensure_live_trade_game(db)
        trade = TradingGameTrade(
            game_id=trade_game.id,
            mode="live_forward_paper",
            ticker=ticker,
            asset_name=(candidate.get("asset") or {}).get("name") or ticker,
            asset_type=(candidate.get("asset") or {}).get("asset_type"),
            sector=(candidate.get("asset") or {}).get("sector"),
            setup_type=(candidate.get("setup") or {}).get("setup_type") or "active_setup",
            confidence_at_entry=candidate.get("confidence"),
            actionability_state_at_entry=candidate.get("actionability"),
            market_regime_at_entry=(candidate.get("market_regime") or {}).get("regime_primary"),
            benchmark_ticker=game.benchmark_ticker,
            timeframe="daily",
            decision_state=candidate.get("actionability") or "active_setup",
            entry_date=datetime.utcnow().date(),
            entry_price=price,
            entry_reason=f"Live forward paper setup frozen from BLUM candidate scan at {datetime.utcnow().isoformat()}.",
            entry_trigger=plan.get("entry_trigger") or plan.get("confirmation_condition") or "live_candidate_actionable",
            confirmation_condition=plan.get("confirmation_condition") or "Candidate met BLUM actionability threshold at decision timestamp.",
            position_size=round(size, 6),
            notional_value=round(size * price, 4) if price else 0.0,
            risk_amount=round(risk_amount, 4),
            risk_percent=settings.live_trading_game_max_risk_per_trade,
            stop_loss=stop,
            invalidation_level=stop,
            initial_target_1=safe_float(plan.get("target_1")) or (price * 1.04 if price else None),
            initial_target_2=safe_float(plan.get("target_2")) or (price * 1.08 if price else None),
            trailing_stop="Live forward paper trailing logic evaluates on future market refreshes.",
            capital_before=round(game.current_capital, 4),
            capital_after=round(game.current_capital, 4),
            reproducibility_score=candidate.get("reproducibility_score") or 70.0,
            data_quality_score=(candidate.get("price_context") or {}).get("data_quality_score"),
            outcome_label="open",
            payload={"candidate_snapshot": compact_candidate(candidate), "no_future_data_policy": "No exit outcome is evaluated until later market data exists."},
        )
        db.add(trade)
        db.flush()
        position = LiveForwardPaperPosition(
            game_id=game.id,
            trade_id=trade.id,
            ticker=ticker,
            setup_type=trade.setup_type,
            entry_price=price,
            current_price=price,
            position_size=round(size, 6),
            risk_amount=round(risk_amount, 4),
            stop_loss=stop,
            target_1=trade.initial_target_1,
            target_2=trade.initial_target_2,
            thesis_snapshot={"reason": trade.entry_reason, "actionability": trade.actionability_state_at_entry},
            data_snapshot={"price_context": candidate.get("price_context"), "timestamp": datetime.utcnow().isoformat()},
        )
        db.add(position)
        game.open_positions += 1
        game.exposure += trade.notional_value or 0.0
        game.cash = max(0.0, game.cash - safe_float(trade.notional_value))
        game.updated_at = datetime.utcnow()
        return {"trade_id": trade.id, "ticker": ticker, "entry_price": price, "position_size": size, "policy": "Paper only; decision frozen."}

    def evaluate_open_positions(self, db: Session, game: LiveForwardPaperGame) -> list[dict]:
        closed = []
        positions = db.scalars(select(LiveForwardPaperPosition).where(LiveForwardPaperPosition.game_id == game.id, LiveForwardPaperPosition.status == "open")).all()
        for position in positions:
            latest = latest_price_after(db, position.ticker, position.decision_timestamp)
            if not latest:
                continue
            latest_date, latest_price = latest
            position.current_price = latest_price
            trade = db.get(TradingGameTrade, position.trade_id) if position.trade_id else None
            if not trade:
                continue
            outcome = None
            if position.stop_loss and latest_price <= position.stop_loss:
                outcome = "stopped_out"
            elif position.target_2 and latest_price >= position.target_2:
                outcome = "target_hit"
            elif position.target_1 and latest_price >= position.target_1:
                outcome = "partial_profit"
            if not outcome:
                continue
            pnl_per_share = latest_price - safe_float(position.entry_price)
            net = pnl_per_share * safe_float(position.position_size)
            trade.exit_date = latest_date
            trade.exit_price = latest_price
            trade.net_pnl_eur = round(net, 4)
            trade.gross_pnl_eur = round(net, 4)
            trade.pnl_per_share = round(pnl_per_share, 4)
            trade.pnl_percent = round(net / max(0.01, safe_float(trade.capital_before)) * 100, 4)
            trade.realized_pl = trade.net_pnl_eur
            trade.realized_r_multiple = round(net / max(0.01, safe_float(trade.risk_amount)), 4)
            trade.capital_after = round(safe_float(trade.capital_before) + net, 4)
            trade.outcome_label = outcome
            trade.target_hit = outcome in {"target_hit", "partial_profit"}
            trade.stop_hit = outcome == "stopped_out"
            trade.exit_reason = f"Live forward paper position closed on {latest_date.isoformat()} because {outcome.replace('_', ' ')} triggered."
            position.status = "closed"
            position.updated_at = datetime.utcnow()
            game.current_capital = round(game.current_capital + net, 4)
            game.realized_pl = round(game.realized_pl + net, 4)
            game.open_positions = max(0, game.open_positions - 1)
            game.updated_at = datetime.utcnow()
            closed.append({"trade_id": trade.id, "ticker": trade.ticker, "outcome": outcome, "net_pnl_eur": trade.net_pnl_eur})
        return closed

    def has_open_position(self, db: Session, game: LiveForwardPaperGame, ticker: str | None) -> bool:
        if not ticker:
            return True
        return bool(db.scalar(select(LiveForwardPaperPosition.id).where(LiveForwardPaperPosition.game_id == game.id, LiveForwardPaperPosition.ticker == ticker, LiveForwardPaperPosition.status == "open").limit(1)))

    def positions(self, db: Session) -> dict:
        game = self.active_or_create_live_game(db)
        rows = db.scalars(select(LiveForwardPaperPosition).where(LiveForwardPaperPosition.game_id == game.id).order_by(desc(LiveForwardPaperPosition.created_at))).all()
        return {"status": "ok", "game": serialize_live_game(game), "positions": [serialize_live_position(row) for row in rows], "policy": LAB_POLICY}

    def trades(self, db: Session) -> dict:
        game = ensure_live_trade_game(db)
        rows = db.scalars(select(TradingGameTrade).where(TradingGameTrade.game_id == game.id, TradingGameTrade.mode == "live_forward_paper").order_by(desc(TradingGameTrade.created_at))).all()
        return {"status": "ok", "rows": [TradeLedgerService().serialize_trade(db, row) for row in rows], "summary": ledger_summary(rows), "policy": LAB_POLICY}

    def ledger(self, db: Session, limit: int = 200) -> dict:
        game = ensure_live_trade_game(db)
        return TradeLedgerService().ledger(db, game_id=game.id, limit=limit, refresh=True)

    def equity(self, db: Session) -> dict:
        game = ensure_live_trade_game(db)
        points = db.scalars(select(TradingGameEquityCurve).where(TradingGameEquityCurve.game_id == game.id).order_by(TradingGameEquityCurve.created_at)).all()
        return {"status": "ok", "game": serialize_game_lab(game), "points": [{"timestamp": iso(row.equity_date or row.created_at), "equity": row.equity, "benchmark_equity": row.benchmark_equity} for row in points], "policy": LAB_POLICY}

    def metrics(self, db: Session) -> dict:
        game = ensure_live_trade_game(db)
        rows = db.scalars(select(TradingGameTrade).where(TradingGameTrade.game_id == game.id, TradingGameTrade.mode == "live_forward_paper").order_by(TradingGameTrade.created_at)).all()
        return {"status": "ok", "metrics": metric_payload(rows, scope="live_forward_paper", scope_id=str(game.id), window_type="all", window_size=None), "policy": LAB_POLICY}

    def compare_historical(self, db: Session) -> dict:
        return HistoricalLiveComparisonService().compare(db)


class HistoricalLiveComparisonService:
    def compare(self, db: Session, persist: bool = False) -> dict:
        historical_game = db.scalar(select(TradingGame).where(TradingGame.mode != "live_forward_paper").order_by(desc(TradingGame.started_at)).limit(1))
        live_game = db.scalar(select(TradingGame).where(TradingGame.mode == "live_forward_paper").order_by(desc(TradingGame.started_at)).limit(1))
        historical_rows = db.scalars(select(TradingGameTrade).where(TradingGameTrade.game_id == historical_game.id).order_by(TradingGameTrade.created_at)).all() if historical_game else []
        live_rows = db.scalars(select(TradingGameTrade).where(TradingGameTrade.game_id == live_game.id).order_by(TradingGameTrade.created_at)).all() if live_game else []
        historical = metric_payload(historical_rows, scope="historical_simulation", scope_id=str(historical_game.id) if historical_game else None, window_type="all", window_size=None)
        live = metric_payload(live_rows, scope="live_forward_paper", scope_id=str(live_game.id) if live_game else None, window_type="all", window_size=None)
        warning = comparison_warning(historical, live)
        payload = {"status": "ok", "historical": historical, "live": live, "sample_warning": warning, "policy": "Live forward paper evidence is stronger than historical replay, but only after enough timestamp-frozen trades close."}
        if persist:
            row = HistoricalLiveComparison(
                historical_sample_size=historical["trades_count"],
                live_sample_size=live["trades_count"],
                historical_win_rate=historical.get("win_rate"),
                live_win_rate=live.get("win_rate"),
                historical_expectancy=historical.get("expectancy_r"),
                live_expectancy=live.get("expectancy_r"),
                historical_target_hit_rate=historical.get("target_hit_rate"),
                live_target_hit_rate=live.get("target_hit_rate"),
                historical_missed_entry_rate=historical.get("missed_entry_rate"),
                live_missed_entry_rate=live.get("missed_entry_rate"),
                historical_max_drawdown=historical.get("max_drawdown"),
                live_max_drawdown=live.get("max_drawdown"),
                historical_benchmark_excess=historical.get("benchmark_excess"),
                live_benchmark_excess=live.get("benchmark_excess"),
                historical_profit_factor=historical.get("profit_factor"),
                live_profit_factor=live.get("profit_factor"),
                sample_warning=warning,
                comparison_payload=payload,
            )
            db.add(row)
            db.commit()
        return payload


def query_trades(game_id: int, **filters):
    query = select(TradingGameTrade).where(TradingGameTrade.game_id == game_id)
    if filters.get("ticker"):
        query = query.where(TradingGameTrade.ticker == str(filters["ticker"]).upper())
    if filters.get("setup_type"):
        query = query.where(TradingGameTrade.setup_type == filters["setup_type"])
    if filters.get("outcome_label"):
        query = query.where(TradingGameTrade.outcome_label == filters["outcome_label"])
    if filters.get("actionability_state"):
        query = query.where(TradingGameTrade.actionability_state_at_entry == filters["actionability_state"])
    if filters.get("capital_cycle_id"):
        query = query.where(TradingGameTrade.capital_cycle_id == filters["capital_cycle_id"])
    return query


def ledger_summary(rows: list[TradingGameTrade]) -> dict:
    labels = Counter(row.outcome_label or row.decision_state for row in rows)
    active = executable_trades(rows)
    pnl_values = [safe_float(row.net_pnl_eur if row.net_pnl_eur is not None else row.realized_pl) for row in active]
    r_values = [safe_float(row.realized_r_multiple) for row in active if row.realized_r_multiple is not None]
    best = max(active, key=lambda row: safe_float(row.net_pnl_eur if row.net_pnl_eur is not None else row.realized_pl), default=None)
    worst = min(active, key=lambda row: safe_float(row.net_pnl_eur if row.net_pnl_eur is not None else row.realized_pl), default=None)
    return {
        "total_trades": len(rows),
        "closed_trades": sum(1 for row in rows if row.exit_date is not None),
        "open_trades": sum(1 for row in rows if row.exit_date is None and row.outcome_label == "open"),
        "wins": labels["win"] + labels["target_hit"] + labels["partial_profit"],
        "losses": labels["loss"] + labels["stopped_out"],
        "missed_entries": labels["missed_entry"],
        "target_hits": labels["target_hit"],
        "stop_hits": labels["stopped_out"],
        "invalidated_trades": labels["thesis_invalidated"] + labels["stopped_out"],
        "no_trade_decisions": labels["no_trade_correct"] + labels["no_trade_missed_opportunity"],
        "no_trade_correct": labels["no_trade_correct"],
        "no_trade_missed_opportunity": labels["no_trade_missed_opportunity"],
        "average_pnl": round(mean(pnl_values), 4) if pnl_values else None,
        "median_pnl": round(median(pnl_values), 4) if pnl_values else None,
        "total_pnl": round(sum(pnl_values), 4),
        "average_r": round(mean(r_values), 4) if r_values else None,
        "average_holding_days": round(mean([safe_float(row.holding_days) for row in rows if row.holding_days is not None]), 2) if any(row.holding_days is not None for row in rows) else None,
        "best_trade": trade_ref(best),
        "worst_trade": trade_ref(worst),
        "best_setup": top_group(active, lambda row: row.setup_type),
        "worst_setup": bottom_group(active, lambda row: row.setup_type),
        "best_ticker": top_group(active, lambda row: row.ticker),
        "worst_ticker": bottom_group(active, lambda row: row.ticker),
        "benchmark_excess_total": round(sum(safe_float(row.excess_return_vs_benchmark) for row in active if row.excess_return_vs_benchmark is not None), 4),
        "sample_size_warning": len(active) < 30,
        "reliability_context": sample_context(rows),
    }


def metric_payload(rows: list[TradingGameTrade], scope: str, scope_id: str | None, window_type: str, window_size: int | None) -> dict:
    labels = Counter(row.outcome_label or row.decision_state for row in rows)
    active = executable_trades(rows)
    r_values = [safe_float(row.realized_r_multiple) for row in active if row.realized_r_multiple is not None]
    positives = [value for value in r_values if value > 0]
    negatives = [abs(value) for value in r_values if value < 0]
    quality_values = [safe_float(row.trade_quality_score) for row in rows if row.trade_quality_score is not None]
    reproducibility_values = [safe_float(row.reproducibility_score) for row in rows if row.reproducibility_score is not None]
    benchmark = [safe_float(row.excess_return_vs_benchmark) for row in active if row.excess_return_vs_benchmark is not None]
    denom = max(1, len(rows))
    active_denom = max(1, len(active))
    entry_score = 100 - min(100, labels["missed_entry"] / denom * 100)
    exit_score = 100 - min(100, labels["stopped_out"] / active_denom * 100)
    rr_score = clamp(50 + (mean(r_values) if r_values else 0) * 18)
    growth_score = clamp(
        (safe_rate(labels["win"] + labels["target_hit"] + labels["partial_profit"], active_denom) * 0.22)
        + (safe_rate(labels["no_trade_correct"], max(1, labels["no_trade_correct"] + labels["no_trade_missed_opportunity"])) * 0.14)
        + (rr_score * 0.24)
        + ((mean(quality_values) if quality_values else 45) * 0.22)
        + ((mean(reproducibility_values) if reproducibility_values else 45) * 0.18)
    )
    return {
        "scope": scope,
        "scope_id": scope_id,
        "window_type": window_type,
        "window_size": window_size,
        "trades_count": len(rows),
        "win_rate": round(safe_rate(labels["win"] + labels["target_hit"] + labels["partial_profit"], active_denom), 4),
        "loss_rate": round(safe_rate(labels["loss"] + labels["stopped_out"], active_denom), 4),
        "missed_entry_rate": round(safe_rate(labels["missed_entry"], denom), 4),
        "target_hit_rate": round(safe_rate(labels["target_hit"], active_denom), 4),
        "stop_hit_rate": round(safe_rate(labels["stopped_out"], active_denom), 4),
        "no_trade_correct_rate": round(safe_rate(labels["no_trade_correct"], denom), 4),
        "no_trade_missed_opportunity_rate": round(safe_rate(labels["no_trade_missed_opportunity"], denom), 4),
        "expectancy_r": round(mean(r_values), 4) if r_values else None,
        "profit_factor": round(sum(positives) / max(0.01, sum(negatives)), 4) if r_values else None,
        "average_r": round(mean(r_values), 4) if r_values else None,
        "median_r": round(median(r_values), 4) if r_values else None,
        "max_drawdown": min((safe_float(row.capital_after) / max(0.01, safe_float(row.capital_before)) - 1) * 100 for row in active) if active else None,
        "benchmark_excess": round(mean(benchmark), 4) if benchmark else None,
        "entry_timing_score": round(entry_score, 2),
        "exit_timing_score": round(exit_score, 2),
        "sizing_quality_score": round(mean([sizing_score(row) for row in rows]), 2) if rows else None,
        "risk_reward_quality_score": round(rr_score, 2),
        "reproducibility_score": round(mean(reproducibility_values), 2) if reproducibility_values else None,
        "trade_quality_score": round(mean(quality_values), 2) if quality_values else None,
        "intelligence_growth_score": round(growth_score, 2),
        "notes_json": {"warnings": intelligence_warnings_raw(len(rows), labels), "policy": LAB_POLICY},
    }


def executable_trades(rows: list[TradingGameTrade]) -> list[TradingGameTrade]:
    return [row for row in rows if row.decision_state not in {"avoid", "wait_for_trigger"} and (row.outcome_label or "") not in {"no_trade_correct", "no_trade_missed_opportunity", "missed_entry", "open"}]


def safe_rate(numerator: float, denominator: float) -> float:
    return 0.0 if denominator <= 0 else numerator / denominator


def top_group(rows: list[TradingGameTrade], key_fn) -> dict | None:
    grouped = group_pnl(rows, key_fn)
    return max(grouped, key=lambda item: item["pnl"], default=None)


def bottom_group(rows: list[TradingGameTrade], key_fn) -> dict | None:
    grouped = group_pnl(rows, key_fn)
    return min(grouped, key=lambda item: item["pnl"], default=None)


def group_pnl(rows: list[TradingGameTrade], key_fn) -> list[dict]:
    grouped: dict[str, dict] = defaultdict(lambda: {"count": 0, "pnl": 0.0})
    for row in rows:
        key = key_fn(row) or "unknown"
        grouped[key]["count"] += 1
        grouped[key]["pnl"] += safe_float(row.net_pnl_eur if row.net_pnl_eur is not None else row.realized_pl)
    return [{"key": key, "count": value["count"], "pnl": round(value["pnl"], 4)} for key, value in grouped.items()]


def sample_context(rows: list[TradingGameTrade]) -> dict:
    tickers = {row.ticker for row in rows if row.ticker}
    sectors = {row.sector for row in rows if row.sector}
    regimes = {row.market_regime_at_entry for row in rows if row.market_regime_at_entry}
    warnings = []
    if len(rows) < 30:
        warnings.append("too_few_trades")
    if len(tickers) < 8:
        warnings.append("too_few_tickers")
    if len(regimes) < 3:
        warnings.append("too_few_regimes")
    return {"tickers": len(tickers), "sectors": len(sectors), "regimes": len(regimes), "warnings": warnings}


def cycle_stats(rows: list[TradingCapitalCycle]) -> dict:
    completed = [row for row in rows if row.reached_target]
    bankrupt = [row for row in rows if row.went_to_zero]
    closed = [row for row in rows if row.ended_at and row.started_at]
    return {
        "cycles": len(rows),
        "target_cycles_completed": len(completed),
        "bankrupt_cycles": len(bankrupt),
        "active_cycles": sum(1 for row in rows if row.status == "active"),
        "average_days_to_target": round(mean([(row.ended_at - row.started_at).days for row in completed if row.ended_at and row.started_at]), 2) if completed else None,
        "average_days_to_bankruptcy": round(mean([(row.ended_at - row.started_at).days for row in bankrupt if row.ended_at and row.started_at]), 2) if bankrupt else None,
        "best_cycle": serialize_cycle(max(rows, key=lambda row: safe_float(row.return_percent), default=None)),
        "worst_cycle": serialize_cycle(min(rows, key=lambda row: safe_float(row.return_percent), default=None)),
        "target_hit_rate": round(len(completed) / max(1, len(closed)), 4) if closed else 0.0,
        "survival_rate": round(1 - len(bankrupt) / max(1, len(closed)), 4) if closed else 1.0,
    }


def serialize_cycle(row: TradingCapitalCycle | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "game_id": row.game_id,
        "cycle_number": row.cycle_number,
        "started_at": iso(row.started_at),
        "ended_at": iso(row.ended_at),
        "start_capital": row.start_capital,
        "target_capital": row.target_capital,
        "final_capital": row.final_capital,
        "status": row.status,
        "reached_target": row.reached_target,
        "went_to_zero": row.went_to_zero,
        "return_percent": row.return_percent,
        "max_drawdown": row.max_drawdown,
        "trades_count": row.trades_count,
        "wins": row.wins,
        "losses": row.losses,
        "missed_entries": row.missed_entries,
        "target_hits": row.target_hits,
        "stop_hits": row.stop_hits,
        "no_trade_correct": row.no_trade_correct,
        "no_trade_missed_opportunity": row.no_trade_missed_opportunity,
        "profit_factor": row.profit_factor,
        "expectancy_r": row.expectancy_r,
        "benchmark_return": row.benchmark_return,
        "excess_return_vs_benchmark": row.excess_return_vs_benchmark,
        "best_trade_id": row.best_trade_id,
        "worst_trade_id": row.worst_trade_id,
        "failure_reason": row.failure_reason,
        "success_reason": row.success_reason,
        "lessons_json": row.lessons_json,
        "updated_at": iso(row.updated_at),
    }


def serialize_game_lab(game: TradingGame | None) -> dict | None:
    if game is None:
        return None
    return {
        "id": game.id,
        "game_id": game.game_id,
        "status": game.status,
        "mode": game.mode,
        "starting_capital": game.starting_capital,
        "current_capital": game.current_capital,
        "target_capital": game.target_capital or settings.trading_game_target_capital,
        "target_cycles_completed": game.target_cycles_completed,
        "bankrupt_cycles": game.bankrupt_cycles,
        "active_cycle_id": game.active_cycle_id,
        "trade_count": game.trade_count,
        "profit_factor": game.profit_factor,
        "expectancy_r": game.expectancy_r,
        "risk_of_ruin": game.risk_of_ruin,
        "updated_at": iso(game.updated_at),
    }


def trade_ref(row: TradingGameTrade | None) -> dict | None:
    if row is None:
        return None
    return {"trade_id": row.id, "ticker": row.ticker, "setup_type": row.setup_type, "net_pnl_eur": row.net_pnl_eur, "r_multiple": row.realized_r_multiple, "outcome_label": row.outcome_label}


def sizing_score(row: TradingGameTrade) -> float:
    if row.decision_state in {"avoid", "wait_for_trigger"}:
        return 75.0
    if 0 < safe_float(row.risk_percent) <= settings.trading_game_max_risk_percent:
        return 88.0
    return 35.0


def intelligence_warnings(payload: dict) -> list[str]:
    return payload.get("notes_json", {}).get("warnings", []) if payload else []


def intelligence_warnings_raw(count: int, labels: Counter) -> list[str]:
    warnings = []
    if count < 30:
        warnings.append("too_few_trades")
    if labels["missed_entry"] / max(1, count) > 0.35:
        warnings.append("missed_entry_rate_high")
    if labels["stopped_out"] / max(1, count) > 0.25:
        warnings.append("stop_hit_rate_high")
    return warnings


def latest_price_after(db: Session, ticker: str, timestamp: datetime) -> tuple[datetime, float] | None:
    asset = db.scalar(select(Asset).where(Asset.ticker == ticker).limit(1))
    if not asset:
        return None
    row = db.scalar(
        select(PriceHistory)
        .where(PriceHistory.asset_id == asset.id, PriceHistory.date > timestamp.date())
        .order_by(PriceHistory.date)
        .limit(1)
    )
    return (row.date, safe_float(row.close)) if row else None


def live_candidate_is_actionable(candidate: dict) -> bool:
    action = str(candidate.get("actionability") or "").lower()
    if settings.live_trading_game_require_actionable_setup and action not in {"active_setup", "actionable_if_confirmed"}:
        return False
    price = safe_float((candidate.get("price_context") or {}).get("latest_price"))
    return bool(candidate.get("ticker") and price > 0)


def ensure_live_trade_game(db: Session) -> TradingGame:
    game = db.scalar(select(TradingGame).where(TradingGame.mode == "live_forward_paper", TradingGame.status == "active").order_by(desc(TradingGame.started_at)).limit(1))
    if game:
        return game
    capital = settings.live_trading_game_initial_capital
    game = TradingGame(
        game_id=f"live-ledger-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
        status="active",
        mode="live_forward_paper",
        starting_capital=capital,
        current_capital=capital,
        cash=capital,
        peak_capital=capital,
        target_capital=settings.live_trading_game_target_capital,
        benchmark_ticker=settings.live_trading_game_benchmark,
        configuration={"mode": "live_forward_paper", "policy": "Forward-only paper ledger."},
    )
    db.add(game)
    db.flush()
    db.add(TradingGameEquityCurve(game_id=game.id, equity_date=datetime.utcnow().date(), equity=capital, cash=capital, exposure=0.0, drawdown=0.0, event_type="live_game_start", payload={"mode": "live_forward_paper"}))
    return game


def serialize_live_game(row: LiveForwardPaperGame) -> dict:
    return {
        "id": row.id,
        "game_id": row.game_id,
        "status": row.status,
        "starting_capital": row.starting_capital,
        "current_capital": row.current_capital,
        "target_capital": row.target_capital,
        "cash": row.cash,
        "exposure": row.exposure,
        "realized_pl": row.realized_pl,
        "benchmark_ticker": row.benchmark_ticker,
        "open_positions": row.open_positions,
        "cycle_number": row.cycle_number,
        "configuration": row.configuration,
        "started_at": iso(row.started_at),
        "updated_at": iso(row.updated_at),
    }


def serialize_live_position(row: LiveForwardPaperPosition) -> dict:
    return {
        "id": row.id,
        "game_id": row.game_id,
        "trade_id": row.trade_id,
        "ticker": row.ticker,
        "setup_type": row.setup_type,
        "status": row.status,
        "decision_timestamp": iso(row.decision_timestamp),
        "entry_price": row.entry_price,
        "current_price": row.current_price,
        "position_size": row.position_size,
        "risk_amount": row.risk_amount,
        "stop_loss": row.stop_loss,
        "target_1": row.target_1,
        "target_2": row.target_2,
        "thesis_snapshot": row.thesis_snapshot,
        "data_snapshot": row.data_snapshot,
        "no_future_data_policy": row.no_future_data_policy,
        "updated_at": iso(row.updated_at),
    }


def compact_candidate(candidate: dict) -> dict:
    return {
        "ticker": candidate.get("ticker"),
        "actionability": candidate.get("actionability"),
        "sniper_score": candidate.get("sniper_score"),
        "confidence": candidate.get("confidence"),
        "setup": candidate.get("setup"),
        "trade_plan": candidate.get("trade_plan"),
        "price_context": candidate.get("price_context"),
    }


def comparison_warning(historical: dict, live: dict) -> str:
    if safe_float(live.get("trades_count")) < 30:
        return "Live forward sample is too small for conclusions."
    if safe_float(historical.get("trades_count")) < 100:
        return "Historical sample is still thin; compare with caution."
    return "Comparison has basic sample coverage but remains paper research."


def iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
