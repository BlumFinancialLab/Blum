from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import hashlib
from statistics import mean, median
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Asset,
    LearningEvent,
    HistoricalLiveComparison,
    LiveForwardPaperGame,
    LiveForwardPaperPosition,
    LiveForwardPaperTrade,
    LiveForwardPaperTradeEvent,
    PriceHistory,
    SignalPerformance,
    StrategyMemory,
    TradeLearningEvidence,
    TradingCapitalCycle,
    TradingGame,
    TradingGameEquityCurve,
    TradingGameTrade,
    TradingIntelligenceMetric,
)
from app.services.dashboard_snapshots import DashboardSnapshotService
from app.services.learning_loop import active_weight_context, learning_mode_metadata
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
            db.commit()
            query = select(TradingCapitalCycle).where(TradingCapitalCycle.game_id == game.id)
        else:
            query = select(TradingCapitalCycle)
        rows = db.scalars(query.order_by(desc(TradingCapitalCycle.cycle_number)).limit(limit)).all()
        return {"status": "ok", "game": serialize_game_lab(game) if game else None, "cycles": [serialize_cycle(row) for row in rows], "stats": cycle_stats(rows), "policy": LAB_POLICY}

    def current(self, db: Session, game_id: int | None = None) -> dict:
        game = TradeLedgerService().game(db, game_id)
        cycle = self.ensure_current_cycle(db, game) if game else None
        if cycle:
            db.commit()
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

    snapshot_type = "paper_forward_snapshot"

    def status(self, db: Session) -> dict:
        game = self.active_or_create_live_game(db)
        return self.status_payload(db, game)

    def status_readonly(self, db: Session) -> dict:
        game = self.active_game(db)
        if not game:
            return {
                "status": "NO_SNAPSHOTS",
                "readiness": "NO_SNAPSHOTS",
                "enabled": settings.live_trading_game_enabled,
                "current_blockers": ["no_live_forward_paper_game"],
                "policy": LAB_POLICY,
            }
        return self.status_payload(db, game)

    def status_payload(self, db: Session, game: LiveForwardPaperGame) -> dict:
        open_trades = int(db.scalar(select(func.count(LiveForwardPaperTrade.id)).where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status == "OPEN")) or 0)
        blocked = int(db.scalar(select(func.count(LiveForwardPaperTrade.id)).where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status == "DATA_BLOCKED")) or 0)
        latest_event = db.scalar(select(LiveForwardPaperTradeEvent).order_by(desc(LiveForwardPaperTradeEvent.event_timestamp)).limit(1))
        return {
            "status": "active" if settings.live_trading_game_enabled else "disabled",
            "readiness": "READY" if settings.live_trading_game_enabled else "DISABLED",
            "game": serialize_live_game(game),
            "counts": {
                "open": open_trades,
                "data_blocked": blocked,
                "closed": int(db.scalar(select(func.count(LiveForwardPaperTrade.id)).where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status == "CLOSED")) or 0),
            },
            "last_event": serialize_live_event(latest_event) if latest_event else None,
            "policy": LAB_POLICY,
        }

    def run_cycle(self, db: Session) -> dict:
        if not settings.live_trading_game_enabled:
            return {"status": "disabled", "policy": LAB_POLICY}
        game = self.active_or_create_live_game(db)
        candidates = self.scan_candidates(db)
        opened = self.open_eligible_trades(db, game, candidates)
        updated = self.update_open_trades(db, game)
        closed = updated.get("closed", [])
        lessons = self.publish_lessons(db, closed)
        self.refresh_live_game_counts(db, game)
        db.commit()
        snapshot = self.publish_snapshot(db)
        return {
            "status": "ok",
            "phases": {
                "scan_candidates": {"count": len(candidates)},
                "open_eligible_trades": opened,
                "update_open_trades": {"updated": len(updated.get("updated", [])), "data_blocked": len(updated.get("data_blocked", []))},
                "close_resolved_trades": {"closed": len(closed)},
                "publish_lessons": {"created": len(lessons)},
            },
            "game": serialize_live_game(game),
            "snapshot": snapshot,
            "sample_warning": "Live forward evidence is immature until enough timestamp-frozen trades close.",
            "policy": LAB_POLICY,
        }

    def scan_candidates(self, db: Session, limit: int = 30) -> list[dict]:
        from app.services.market_sniper import MarketSniperEngine

        payload = MarketSniperEngine().candidates(db, limit=limit, persist=False)
        return list(payload.get("candidates", []) or [])

    def active_or_create_live_game(self, db: Session) -> LiveForwardPaperGame:
        game = self.active_game(db)
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

    def active_game(self, db: Session) -> LiveForwardPaperGame | None:
        return db.scalar(select(LiveForwardPaperGame).where(LiveForwardPaperGame.status == "active").order_by(desc(LiveForwardPaperGame.started_at)).limit(1))

    def open_position(self, db: Session, game: LiveForwardPaperGame, candidate: dict) -> dict:
        opened = self.open_eligible_trades(db, game, [candidate])
        return opened.get("opened", [{}])[0] if opened.get("opened") else {"status": "skipped", "reason": opened.get("skipped_reason") or "not_opened"}

    def open_eligible_trades(self, db: Session, game: LiveForwardPaperGame, candidates: list[dict]) -> dict:
        opened: list[dict] = []
        skipped: list[dict] = []
        data_blocked: list[dict] = []
        duplicates: list[dict] = []
        for candidate in candidates:
            if game.open_positions >= settings.live_trading_game_max_open_positions:
                skipped.append({"ticker": candidate.get("ticker"), "reason": "max_open_positions_reached"})
                break
            trade = self.build_trade_from_candidate(db, game, candidate)
            if trade is None:
                duplicates.append({"ticker": candidate.get("ticker"), "reason": "duplicate_or_open_position"})
                continue
            if trade.status == "OPEN":
                opened.append(serialize_paper_forward_trade(trade, compact=True))
            elif trade.status == "DATA_BLOCKED":
                data_blocked.append(serialize_paper_forward_trade(trade, compact=True))
            else:
                skipped.append(serialize_paper_forward_trade(trade, compact=True))
        return {"opened": opened, "skipped": skipped, "data_blocked": data_blocked, "duplicates": duplicates}

    def build_trade_from_candidate(self, db: Session, game: LiveForwardPaperGame, candidate: dict) -> LiveForwardPaperTrade | None:
        now = datetime.utcnow()
        ticker = candidate.get("ticker")
        price = safe_float((candidate.get("price_context") or {}).get("latest_price"))
        plan = candidate.get("trade_plan") or {}
        setup_type = (candidate.get("setup") or {}).get("setup_type") or "active_setup"
        entry_trigger = plan.get("entry_trigger") or plan.get("confirmation_condition") or "live_candidate_actionable"
        feedback = self.feedback_metadata(db, ticker=ticker, setup_type=setup_type)
        duplicate_key = live_forward_duplicate_key(
            ticker=ticker,
            decision_date=now.date(),
            model_version=feedback["model_version_used"],
            setup_type=setup_type,
            entry_trigger=entry_trigger,
        )
        if not ticker or self.duplicate_or_open_trade(db, game, ticker, duplicate_key):
            return None

        actionable = live_candidate_is_actionable(candidate)
        status = "OPEN" if actionable else "SKIPPED"
        block_reason = ""
        if price <= 0:
            status = "DATA_BLOCKED"
            block_reason = "missing_live_entry_price"
        elif not actionable:
            block_reason = "candidate_not_actionable"

        risk_amount = game.current_capital * settings.live_trading_game_max_risk_per_trade / 100
        stop = safe_float(plan.get("invalidation_level")) or (price * 0.97 if price else None)
        risk_per_share = abs(price - stop) if price and stop else price * 0.02 if price else 1
        size = risk_amount / max(0.01, risk_per_share)
        target_1 = safe_float(plan.get("target_1")) or (price * 1.04 if price else None)
        target_2 = safe_float(plan.get("target_2")) or (price * 1.08 if price else None)
        trade_game = ensure_live_trade_game(db)
        ledger_trade = None
        if status == "OPEN":
            ledger_trade = TradingGameTrade(
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
                entry_trigger=entry_trigger,
                confirmation_condition=plan.get("confirmation_condition") or "Candidate met BLUM actionability threshold at decision timestamp.",
                position_size=round(size, 6),
                notional_value=round(size * price, 4) if price else 0.0,
                risk_amount=round(risk_amount, 4),
                risk_percent=settings.live_trading_game_max_risk_per_trade,
                stop_loss=stop,
                invalidation_level=stop,
                initial_target_1=target_1,
                initial_target_2=target_2,
                trailing_stop="Live forward paper trailing logic evaluates on future market refreshes.",
                capital_before=round(game.current_capital, 4),
                capital_after=round(game.current_capital, 4),
                reproducibility_score=candidate.get("reproducibility_score") or 70.0,
                data_quality_score=(candidate.get("price_context") or {}).get("data_quality_score"),
                outcome_label="open",
                payload={
                    "candidate_snapshot": compact_candidate(candidate),
                    "feedback_loop": feedback,
                    "no_future_data_policy": "No exit outcome is evaluated until later market data exists.",
                },
            )
            db.add(ledger_trade)
            db.flush()

        paper_trade = LiveForwardPaperTrade(
            trade_uid=f"pf-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
            game_id=game.id,
            ledger_trade_id=ledger_trade.id if ledger_trade else None,
            ticker=ticker,
            asset_name=(candidate.get("asset") or {}).get("name") or ticker,
            asset_type=(candidate.get("asset") or {}).get("asset_type"),
            sector=(candidate.get("asset") or {}).get("sector"),
            industry=(candidate.get("asset") or {}).get("industry"),
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
            frozen_decision_payload=freeze_decision_payload(candidate, feedback, now),
            actionability_state=candidate.get("actionability"),
            confidence=candidate.get("confidence"),
            sniper_score=candidate.get("sniper_score"),
            benchmark_ticker=game.benchmark_ticker,
            entry_trigger=entry_trigger,
            confirmation_condition=plan.get("confirmation_condition") or "Candidate met BLUM actionability threshold at decision timestamp.",
            entry_price=price,
            entry_date=now.date() if status == "OPEN" else None,
            opened_at=now if status == "OPEN" else None,
            stop_loss=stop,
            invalidation_level=stop,
            target_1=target_1,
            target_2=target_2,
            current_price=price,
            position_size=round(size, 6),
            notional_value=round(size * price, 4) if price else 0.0,
            risk_amount=round(risk_amount, 4),
            risk_percent=settings.live_trading_game_max_risk_per_trade,
            expected_risk=round(risk_per_share * size, 4) if price else None,
            expected_reward=round((target_1 - price) * size, 4) if price and target_1 else None,
            expected_r_multiple=round(((target_1 - price) / max(0.01, risk_per_share)), 4) if price and target_1 else None,
            duplicate_key=duplicate_key,
            expires_at=now + timedelta(days=30),
        )
        db.add(paper_trade)
        db.flush()
        self.add_event(db, paper_trade, "DECISION_CREATED", price, "Decision frozen from current BLUM evidence.", {"candidate": compact_candidate(candidate), "feedback": feedback})
        if status == "DATA_BLOCKED":
            self.add_event(db, paper_trade, "DATA_BLOCKED", None, block_reason, {"price_context": candidate.get("price_context")})
            return paper_trade
        if status == "SKIPPED":
            self.add_event(db, paper_trade, "DATA_BLOCKED" if block_reason == "missing_live_entry_price" else "ERROR", price, block_reason, {"actionability": candidate.get("actionability")})
            return paper_trade

        position = LiveForwardPaperPosition(
            game_id=game.id,
            trade_id=ledger_trade.id if ledger_trade else None,
            ticker=ticker,
            setup_type=setup_type,
            status="open",
            decision_timestamp=now,
            entry_price=price,
            current_price=price,
            position_size=round(size, 6),
            risk_amount=round(risk_amount, 4),
            stop_loss=stop,
            target_1=target_1,
            target_2=target_2,
            thesis_snapshot={"reason": ledger_trade.entry_reason if ledger_trade else "", "actionability": candidate.get("actionability")},
            data_snapshot={"price_context": candidate.get("price_context"), "timestamp": now.isoformat(), "paper_trade_id": paper_trade.id},
        )
        db.add(position)
        game.open_positions += 1
        game.exposure += paper_trade.notional_value or 0.0
        game.cash = max(0.0, game.cash - safe_float(paper_trade.notional_value))
        game.updated_at = now
        self.add_event(db, paper_trade, "ENTRY_TRIGGERED", price, entry_trigger, {"confirmation_condition": paper_trade.confirmation_condition})
        self.add_event(db, paper_trade, "POSITION_OPENED", price, "Paper position opened. No broker execution.", {"position_size": paper_trade.position_size, "risk_amount": paper_trade.risk_amount})
        return paper_trade

    def evaluate_open_positions(self, db: Session, game: LiveForwardPaperGame) -> list[dict]:
        return self.update_open_trades(db, game).get("closed", [])

    def update_open_trades(self, db: Session, game: LiveForwardPaperGame) -> dict:
        rows = db.scalars(
            select(LiveForwardPaperTrade)
            .where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status == "OPEN")
            .order_by(LiveForwardPaperTrade.created_at)
        ).all()
        updated: list[dict] = []
        closed: list[dict] = []
        data_blocked: list[dict] = []
        for paper_trade in rows:
            latest = latest_market_price_after(db, paper_trade.ticker, paper_trade.decision_timestamp)
            if latest is None:
                self.add_event(db, paper_trade, "DATA_BLOCKED", None, "No market price later than the decision timestamp is available yet.", {})
                data_blocked.append({"trade_id": paper_trade.id, "ticker": paper_trade.ticker, "reason": "no_future_market_data"})
                continue
            latest_date, latest_price = latest
            self.refresh_open_trade_mark_to_market(db, game, paper_trade, latest_date, latest_price)
            close_reason = close_reason_for(paper_trade, latest_price)
            if close_reason:
                closed.append(self.close_trade(db, game, paper_trade, latest_date, latest_price, close_reason))
            else:
                updated.append(serialize_paper_forward_trade(paper_trade, compact=True))
        return {"updated": updated, "closed": closed, "data_blocked": data_blocked}

    def refresh_open_trade_mark_to_market(self, db: Session, game: LiveForwardPaperGame, paper_trade: LiveForwardPaperTrade, latest_date: date, latest_price: float) -> None:
        entry = safe_float(paper_trade.entry_price)
        size = safe_float(paper_trade.position_size)
        pnl_per_share = latest_price - entry
        unrealized = pnl_per_share * size
        paper_trade.current_price = latest_price
        paper_trade.unrealized_pnl = round(unrealized, 4)
        paper_trade.max_favorable_excursion = round(max(safe_float(paper_trade.max_favorable_excursion), pnl_per_share), 4)
        paper_trade.max_adverse_excursion = round(min(safe_float(paper_trade.max_adverse_excursion), pnl_per_share), 4)
        paper_trade.updated_at = datetime.utcnow()
        position = live_position_for_paper_trade(db, game, paper_trade)
        if position:
            position.current_price = latest_price
            position.updated_at = datetime.utcnow()

    def close_trade(self, db: Session, game: LiveForwardPaperGame, paper_trade: LiveForwardPaperTrade, latest_date: date, latest_price: float, close_reason: str) -> dict:
        now = datetime.utcnow()
        entry = safe_float(paper_trade.entry_price)
        size = safe_float(paper_trade.position_size)
        pnl_per_share = latest_price - entry
        net = pnl_per_share * size
        risk = max(0.01, safe_float(paper_trade.risk_amount))
        benchmark_return = period_return(db, game.benchmark_ticker, paper_trade.decision_date, latest_date)
        asset_return = ((latest_price / entry) - 1) * 100 if entry else None
        status = "EXPIRED" if close_reason == "TIME_EXIT" else "INVALIDATED" if close_reason == "INVALIDATION_HIT" else "CLOSED"
        paper_trade.status = status
        paper_trade.close_reason = close_reason
        paper_trade.exit_price = latest_price
        paper_trade.exit_date = latest_date
        paper_trade.closed_at = now
        paper_trade.gross_pnl_eur = round(net, 4)
        paper_trade.net_pnl_eur = round(net, 4)
        paper_trade.pnl_per_share = round(pnl_per_share, 4)
        paper_trade.pnl_percent = round(asset_return, 4) if asset_return is not None else None
        paper_trade.r_multiple = round(net / risk, 4)
        paper_trade.benchmark_return_same_period = benchmark_return
        paper_trade.excess_return_vs_benchmark = round(asset_return - benchmark_return, 4) if asset_return is not None and benchmark_return is not None else None
        paper_trade.outcome_label = outcome_label_for(close_reason, net)
        paper_trade.stop_hit = close_reason == "STOP_HIT"
        paper_trade.target_1_hit = close_reason == "TARGET_1_HIT"
        paper_trade.target_2_hit = close_reason == "TARGET_2_HIT"
        paper_trade.invalidation_hit = close_reason == "INVALIDATION_HIT"
        paper_trade.lesson_learned = paper_forward_lesson(paper_trade)
        paper_trade.updated_at = now
        event_type = "TARGET_HIT" if close_reason in {"TARGET_1_HIT", "TARGET_2_HIT"} else close_reason
        self.add_event(db, paper_trade, event_type, latest_price, close_reason, {"net_pnl_eur": paper_trade.net_pnl_eur, "r_multiple": paper_trade.r_multiple})
        self.add_event(db, paper_trade, "POSITION_CLOSED", latest_price, f"Closed by {close_reason}.", {"outcome_label": paper_trade.outcome_label})
        self.add_event(db, paper_trade, "OUTCOME_EVALUATED", latest_price, paper_trade.lesson_learned or "", {"benchmark_return_same_period": benchmark_return, "excess_return_vs_benchmark": paper_trade.excess_return_vs_benchmark})
        ledger_trade = db.get(TradingGameTrade, paper_trade.ledger_trade_id) if paper_trade.ledger_trade_id else None
        if ledger_trade:
            update_legacy_live_trade(ledger_trade, paper_trade, game)
        position = live_position_for_paper_trade(db, game, paper_trade)
        if position:
            position.status = "closed"
            position.current_price = latest_price
            position.updated_at = now
        game.current_capital = round(safe_float(game.current_capital) + net, 4)
        game.realized_pl = round(safe_float(game.realized_pl) + net, 4)
        game.exposure = max(0.0, safe_float(game.exposure) - safe_float(paper_trade.notional_value))
        game.cash = round(safe_float(game.cash) + safe_float(paper_trade.notional_value) + net, 4)
        game.open_positions = max(0, int(game.open_positions or 0) - 1)
        game.updated_at = now
        live_ledger_game = ensure_live_trade_game(db)
        db.add(
            TradingGameEquityCurve(
                game_id=live_ledger_game.id,
                equity_date=latest_date,
                equity=game.current_capital,
                cash=game.cash,
                exposure=game.exposure,
                benchmark_return=benchmark_return,
                event_type="paper_forward_trade_closed",
                related_trade_id=ledger_trade.id if ledger_trade else None,
                annotation_payload={"paper_trade_id": paper_trade.id, "close_reason": close_reason, "outcome_label": paper_trade.outcome_label},
            )
        )
        return serialize_paper_forward_trade(paper_trade, compact=True)

    def publish_lessons(self, db: Session, closed: list[dict]) -> list[dict]:
        lessons: list[dict] = []
        for item in closed:
            paper_trade = db.get(LiveForwardPaperTrade, item.get("trade_id"))
            if not paper_trade or not paper_trade.ledger_trade_id:
                continue
            if db.scalar(select(TradeLearningEvidence.id).where(TradeLearningEvidence.trade_id == paper_trade.ledger_trade_id, TradeLearningEvidence.lesson_type == "paper_forward_outcome").limit(1)):
                continue
            lesson_type = "setup_confirmed" if safe_float(paper_trade.r_multiple) > 0 else "setup_failed"
            evidence = TradeLearningEvidence(
                trade_id=paper_trade.ledger_trade_id,
                game_id=ensure_live_trade_game(db).id,
                ticker=paper_trade.ticker,
                setup_type=paper_trade.setup_type,
                regime=(paper_trade.frozen_decision_payload or {}).get("market_regime") or "unknown",
                lesson_type="paper_forward_outcome",
                observation=paper_trade.lesson_learned or "Paper-forward trade closed and was logged for learning.",
                sample_size=1,
                supporting_trades_json={"paper_trade_id": paper_trade.id, "r_multiple": paper_trade.r_multiple, "outcome_label": paper_trade.outcome_label},
                affected_module="live_forward_paper_trading",
                action_taken="stored_for_feedback_loop",
                confidence=clamp(55 + safe_float(paper_trade.r_multiple) * 8),
            )
            db.add(evidence)
            self.update_memory_from_trade(db, paper_trade, lesson_type)
            db.add(
                LearningEvent(
                    event_type="paper_forward_trade_closed",
                    severity="Info",
                    title=f"{paper_trade.ticker} paper-forward {paper_trade.outcome_label or 'closed'}",
                    description=paper_trade.lesson_learned or "",
                    payload={"paper_trade_id": paper_trade.id, "ledger_trade_id": paper_trade.ledger_trade_id, "r_multiple": paper_trade.r_multiple},
                )
            )
            self.add_event(db, paper_trade, "LESSON_CREATED", paper_trade.exit_price, evidence.observation, {"lesson_type": lesson_type})
            lessons.append({"trade_id": paper_trade.id, "lesson_type": lesson_type, "observation": evidence.observation})
        return lessons

    def update_memory_from_trade(self, db: Session, paper_trade: LiveForwardPaperTrade, lesson_type: str) -> None:
        signal_name = f"paper_forward:{paper_trade.setup_type}"
        signal = db.scalar(select(SignalPerformance).where(SignalPerformance.signal_name == signal_name, SignalPerformance.timeframe == "daily", SignalPerformance.market_regime == "live_forward").limit(1))
        if signal is None:
            signal = SignalPerformance(
                signal_name=signal_name,
                timeframe="daily",
                market_regime="live_forward",
                sample_count=0,
                correct_count=0,
                false_positive_count=0,
                false_negative_count=0,
                reliability_score=50.0,
                evidence={},
            )
            db.add(signal)
        signal.sample_count += 1
        if safe_float(paper_trade.r_multiple) > 0:
            signal.correct_count += 1
        else:
            signal.false_positive_count += 1
        signal.reliability_score = round(clamp(40 + (signal.correct_count / max(1, signal.sample_count)) * 45 + min(10, signal.sample_count)), 2)
        signal.average_return = paper_trade.pnl_percent
        signal.evidence = {"latest_paper_trade_id": paper_trade.id, "latest_r_multiple": paper_trade.r_multiple, "lesson_type": lesson_type}

        key = f"paper_forward:{paper_trade.setup_type}:{paper_trade.ticker}"
        memory = db.scalar(select(StrategyMemory).where(StrategyMemory.memory_key == key).limit(1))
        if memory is None:
            memory = StrategyMemory(
                memory_key=key,
                category="paper_forward",
                lesson=paper_trade.lesson_learned or "",
                sample_count=0,
                positive_count=0,
                negative_count=0,
                reliability_score=50.0,
                evidence={},
            )
            db.add(memory)
        memory.sample_count += 1
        if safe_float(paper_trade.r_multiple) > 0:
            memory.positive_count += 1
        else:
            memory.negative_count += 1
        memory.lesson = paper_trade.lesson_learned or memory.lesson
        memory.reliability_score = round(clamp(35 + (memory.positive_count / max(1, memory.sample_count)) * 55), 2)
        memory.evidence = {"latest_paper_trade_id": paper_trade.id, "latest_outcome": paper_trade.outcome_label, "latest_r_multiple": paper_trade.r_multiple}
        memory.last_seen_at = datetime.utcnow()

    def has_open_position(self, db: Session, game: LiveForwardPaperGame, ticker: str | None) -> bool:
        if not ticker:
            return True
        return bool(db.scalar(select(LiveForwardPaperTrade.id).where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.ticker == ticker, LiveForwardPaperTrade.status == "OPEN").limit(1)))

    def duplicate_or_open_trade(self, db: Session, game: LiveForwardPaperGame, ticker: str, duplicate_key: str) -> bool:
        if self.has_open_position(db, game, ticker):
            return True
        return bool(db.scalar(select(LiveForwardPaperTrade.id).where(LiveForwardPaperTrade.duplicate_key == duplicate_key).limit(1)))

    def feedback_metadata(self, db: Session, *, ticker: str | None, setup_type: str) -> dict:
        model_version, weights, source = active_weight_context(db)
        signal_rows = db.scalars(select(SignalPerformance).order_by(desc(SignalPerformance.updated_at)).limit(6)).all()
        strategy_rows = db.scalars(select(StrategyMemory).order_by(desc(StrategyMemory.last_seen_at)).limit(6)).all()
        return {
            "model_version_used": model_version,
            "weights_used": weights,
            "weight_source": source,
            "confidence_adjustment": memory_confidence_adjustment(strategy_rows, signal_rows),
            "learning_memory_used": {"signal_performance": [serialize_signal_memory(row) for row in signal_rows]},
            "strategy_memory_used": {"rows": [serialize_strategy_memory(row) for row in strategy_rows]},
            "research_priority_used": {"ticker": ticker, "setup_type": setup_type, "source": "latest_live_forward_scan"},
            "learning_mode_metadata": learning_mode_metadata("paper_forward", {"mode": "paper_forward", "sampling_reason": "live_forward_paper"}),
        }

    def add_event(self, db: Session, paper_trade: LiveForwardPaperTrade, event_type: str, price_used: float | None, reason: str, payload: dict | None = None) -> LiveForwardPaperTradeEvent:
        event = LiveForwardPaperTradeEvent(
            paper_trade_id=paper_trade.id,
            event_type=event_type,
            price_used=price_used,
            reason=reason,
            payload=payload or {},
        )
        db.add(event)
        return event

    def refresh_live_game_counts(self, db: Session, game: LiveForwardPaperGame) -> None:
        game.open_positions = int(db.scalar(select(func.count(LiveForwardPaperTrade.id)).where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status == "OPEN")) or 0)
        game.updated_at = datetime.utcnow()

    def publish_snapshot(self, db: Session) -> dict:
        return DashboardSnapshotService().write(
            db,
            self.snapshot_type,
            self.snapshot_payload(db),
            source_modules={"producer": "LiveForwardPaperTradingService", "runtime_policy": "snapshot_after_worker_or_manual_post"},
            ttl_seconds=900,
        )

    def snapshot(self, db: Session) -> dict:
        return DashboardSnapshotService().latest(db, self.snapshot_type)

    def snapshot_payload(self, db: Session) -> dict:
        game = self.active_game(db)
        if not game:
            return {
                "readiness": "NO_SNAPSHOTS",
                "status": "missing",
                "explanation": "No live-forward paper game exists yet. The backend worker or POST /api/paper-forward/run must create the first cycle.",
                "policy": LAB_POLICY,
            }
        open_rows = db.scalars(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status == "OPEN").order_by(desc(LiveForwardPaperTrade.created_at)).limit(12)).all()
        closed_rows = db.scalars(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status.in_(["CLOSED", "EXPIRED", "INVALIDATED"])).order_by(desc(LiveForwardPaperTrade.closed_at)).limit(12)).all()
        candidate_rows = db.scalars(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status.in_(["CANDIDATE", "SKIPPED", "DATA_BLOCKED", "ERROR"])).order_by(desc(LiveForwardPaperTrade.created_at)).limit(12)).all()
        all_closed = db.scalars(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status.in_(["CLOSED", "EXPIRED", "INVALIDATED"]))).all()
        realized = sum(safe_float(row.net_pnl_eur) for row in all_closed)
        unrealized = sum(safe_float(row.unrealized_pnl) for row in open_rows)
        wins = sum(1 for row in all_closed if safe_float(row.net_pnl_eur) > 0)
        avg_r = mean([safe_float(row.r_multiple) for row in all_closed if row.r_multiple is not None]) if any(row.r_multiple is not None for row in all_closed) else None
        benchmark_excess = mean([safe_float(row.excess_return_vs_benchmark) for row in all_closed if row.excess_return_vs_benchmark is not None]) if any(row.excess_return_vs_benchmark is not None for row in all_closed) else None
        latest_lesson = db.scalar(select(TradeLearningEvidence).where(TradeLearningEvidence.affected_module == "live_forward_paper_trading").order_by(desc(TradeLearningEvidence.created_at)).limit(1))
        return {
            "readiness": "READY" if settings.live_trading_game_enabled else "DISABLED",
            "status": "ready",
            "last_worker_run": iso(game.updated_at),
            "game": serialize_live_game(game),
            "counts": {
                "candidates": len(candidate_rows),
                "open": len(open_rows),
                "recently_closed": len(closed_rows),
                "closed_total": len(all_closed),
                "data_blocked": sum(1 for row in candidate_rows if row.status == "DATA_BLOCKED"),
            },
            "candidates": [serialize_paper_forward_trade(row, compact=True) for row in candidate_rows],
            "open_positions": [serialize_paper_forward_trade(row, compact=True) for row in open_rows],
            "recently_closed": [serialize_paper_forward_trade(row, compact=True) for row in closed_rows],
            "equity_curve": self.equity_curve_points(db, game),
            "metrics": {
                "realized_pnl": round(realized, 4),
                "unrealized_pnl": round(unrealized, 4),
                "win_rate": round(wins / max(1, len(all_closed)), 4) if all_closed else None,
                "avg_r": round(avg_r, 4) if avg_r is not None else None,
                "benchmark_excess": round(benchmark_excess, 4) if benchmark_excess is not None else None,
            },
            "blockers": snapshot_blockers(candidate_rows, open_rows),
            "last_lesson": serialize_trade_lesson(latest_lesson) if latest_lesson else None,
            "policy": LAB_POLICY,
        }

    def equity_curve_points(self, db: Session, game: LiveForwardPaperGame) -> list[dict]:
        rows = db.scalars(
            select(LiveForwardPaperTrade)
            .where(LiveForwardPaperTrade.game_id == game.id, LiveForwardPaperTrade.status.in_(["CLOSED", "EXPIRED", "INVALIDATED"]))
            .order_by(LiveForwardPaperTrade.closed_at)
        ).all()
        equity = safe_float(game.starting_capital)
        points = [{"timestamp": iso(game.started_at), "equity": round(equity, 4), "event": "start"}]
        for row in rows:
            equity += safe_float(row.net_pnl_eur)
            points.append({"timestamp": iso(row.closed_at or row.updated_at), "equity": round(equity, 4), "ticker": row.ticker, "event": row.close_reason or row.outcome_label})
        return points[-120:]

    def paper_trades(self, db: Session, limit: int = 50, status: str | None = None) -> dict:
        query = select(LiveForwardPaperTrade).order_by(desc(LiveForwardPaperTrade.created_at))
        if status:
            query = query.where(LiveForwardPaperTrade.status == status.upper())
        rows = db.scalars(query.limit(max(1, min(limit, 200)))).all()
        return {"status": "ok", "rows": [serialize_paper_forward_trade(row, compact=True) for row in rows], "limit": limit, "policy": LAB_POLICY}

    def trade_detail(self, db: Session, trade_id: int) -> dict:
        row = db.get(LiveForwardPaperTrade, trade_id)
        if row is None:
            return {"status": "not_found", "trade_id": trade_id}
        events = db.scalars(select(LiveForwardPaperTradeEvent).where(LiveForwardPaperTradeEvent.paper_trade_id == row.id).order_by(LiveForwardPaperTradeEvent.event_timestamp)).all()
        return {"status": "ok", "trade": serialize_paper_forward_trade(row, compact=False), "events": [serialize_live_event(event) for event in events], "policy": LAB_POLICY}

    def events(self, db: Session, trade_id: int) -> dict:
        row = db.get(LiveForwardPaperTrade, trade_id)
        if row is None:
            return {"status": "not_found", "trade_id": trade_id, "events": []}
        events = db.scalars(select(LiveForwardPaperTradeEvent).where(LiveForwardPaperTradeEvent.paper_trade_id == row.id).order_by(LiveForwardPaperTradeEvent.event_timestamp)).all()
        return {"status": "ok", "trade_id": trade_id, "events": [serialize_live_event(event) for event in events], "policy": LAB_POLICY}

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


def live_forward_duplicate_key(*, ticker: str | None, decision_date: date, model_version: str, setup_type: str, entry_trigger: str) -> str:
    raw = "|".join(
        [
            (ticker or "").upper(),
            decision_date.isoformat(),
            model_version or "base-static",
            setup_type or "unknown_setup",
            entry_trigger or "unknown_trigger",
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def freeze_decision_payload(candidate: dict, feedback: dict, decision_timestamp: datetime) -> dict:
    return {
        "decision_timestamp": decision_timestamp.isoformat(),
        "ticker": candidate.get("ticker"),
        "asset": candidate.get("asset") or {},
        "setup": candidate.get("setup") or {},
        "actionability": candidate.get("actionability"),
        "sniper_score": candidate.get("sniper_score"),
        "confidence": candidate.get("confidence"),
        "trade_plan": candidate.get("trade_plan") or {},
        "price_context": candidate.get("price_context") or {},
        "market_regime": (candidate.get("market_regime") or {}).get("regime_primary"),
        "feedback_loop": feedback,
        "no_future_data_policy": "Frozen payload contains only data available at decision timestamp. Future prices are appended as events only.",
    }


def latest_market_price_after(db: Session, ticker: str, timestamp: datetime) -> tuple[date, float] | None:
    asset = db.scalar(select(Asset).where(Asset.ticker == ticker).limit(1))
    if not asset:
        return None
    row = db.scalar(
        select(PriceHistory)
        .where(PriceHistory.asset_id == asset.id, PriceHistory.date > timestamp.date())
        .order_by(desc(PriceHistory.date))
        .limit(1)
    )
    return (row.date, safe_float(row.close)) if row else None


def price_on_or_before(db: Session, ticker: str | None, target_date: date | None) -> float | None:
    if not ticker or not target_date:
        return None
    asset = db.scalar(select(Asset).where(Asset.ticker == ticker).limit(1))
    if not asset:
        return None
    row = db.scalar(
        select(PriceHistory)
        .where(PriceHistory.asset_id == asset.id, PriceHistory.date <= target_date)
        .order_by(desc(PriceHistory.date))
        .limit(1)
    )
    return safe_float(row.close) if row else None


def period_return(db: Session, ticker: str | None, start_date: date | None, end_date: date | None) -> float | None:
    start = price_on_or_before(db, ticker, start_date)
    end = price_on_or_before(db, ticker, end_date)
    if not start or not end:
        return None
    return round(((end / start) - 1) * 100, 4)


def close_reason_for(row: LiveForwardPaperTrade, latest_price: float) -> str | None:
    if row.stop_loss and latest_price <= row.stop_loss:
        return "STOP_HIT"
    if row.invalidation_level and latest_price <= row.invalidation_level:
        return "INVALIDATION_HIT"
    if row.target_2 and latest_price >= row.target_2:
        return "TARGET_2_HIT"
    if row.target_1 and latest_price >= row.target_1:
        return "TARGET_1_HIT"
    if row.expires_at and datetime.utcnow() >= row.expires_at:
        return "TIME_EXIT"
    return None


def outcome_label_for(close_reason: str, net_pnl: float) -> str:
    if close_reason == "STOP_HIT":
        return "stopped_out"
    if close_reason in {"TARGET_1_HIT", "TARGET_2_HIT"}:
        return "target_hit"
    if close_reason == "TIME_EXIT":
        return "time_exit"
    if close_reason == "INVALIDATION_HIT":
        return "thesis_invalidated"
    return "win" if net_pnl > 0 else "loss" if net_pnl < 0 else "breakeven"


def paper_forward_lesson(row: LiveForwardPaperTrade) -> str:
    r_value = safe_float(row.r_multiple)
    if row.close_reason in {"TARGET_1_HIT", "TARGET_2_HIT"}:
        return f"{row.setup_type} on {row.ticker} reached target in live-forward paper mode with {r_value:.2f}R; retain evidence but require larger live sample."
    if row.close_reason == "STOP_HIT":
        return f"{row.setup_type} on {row.ticker} hit the predefined stop; review entry timing, volatility and confirmation quality."
    if row.close_reason == "INVALIDATION_HIT":
        return f"{row.setup_type} on {row.ticker} invalidated the thesis; lower confidence for similar setups until more evidence accumulates."
    if row.close_reason == "TIME_EXIT":
        return f"{row.setup_type} on {row.ticker} expired without resolving; review holding period and signal decay assumptions."
    return f"{row.setup_type} on {row.ticker} closed with {r_value:.2f}R; store as paper-forward evidence."


def update_legacy_live_trade(ledger_trade: TradingGameTrade, paper_trade: LiveForwardPaperTrade, game: LiveForwardPaperGame) -> None:
    ledger_trade.exit_date = paper_trade.exit_date
    ledger_trade.exit_price = paper_trade.exit_price
    ledger_trade.net_pnl_eur = paper_trade.net_pnl_eur
    ledger_trade.gross_pnl_eur = paper_trade.gross_pnl_eur
    ledger_trade.pnl_per_share = paper_trade.pnl_per_share
    ledger_trade.pnl_percent = paper_trade.pnl_percent
    ledger_trade.realized_pl = safe_float(paper_trade.net_pnl_eur)
    ledger_trade.realized_r_multiple = paper_trade.r_multiple
    ledger_trade.capital_after = round(safe_float(game.current_capital) + safe_float(paper_trade.net_pnl_eur), 4)
    ledger_trade.outcome_label = paper_trade.outcome_label
    ledger_trade.target_hit = bool(paper_trade.target_1_hit or paper_trade.target_2_hit)
    ledger_trade.target_1_hit = paper_trade.target_1_hit
    ledger_trade.target_2_hit = paper_trade.target_2_hit
    ledger_trade.stop_hit = paper_trade.stop_hit
    ledger_trade.invalidation_hit = paper_trade.invalidation_hit
    ledger_trade.exit_reason = f"Live-forward paper trade closed by {paper_trade.close_reason}."
    ledger_trade.exit_trigger = paper_trade.close_reason
    ledger_trade.max_favorable_excursion = paper_trade.max_favorable_excursion
    ledger_trade.max_adverse_excursion = paper_trade.max_adverse_excursion
    ledger_trade.benchmark_return_same_period = paper_trade.benchmark_return_same_period
    ledger_trade.excess_return_vs_benchmark = paper_trade.excess_return_vs_benchmark
    ledger_trade.lesson_generated = paper_trade.lesson_learned
    ledger_trade.payload = {
        **(ledger_trade.payload or {}),
        "paper_forward_trade_id": paper_trade.id,
        "model_version_used": paper_trade.model_version_used,
        "weights_used": paper_trade.weights_used,
        "confidence_adjustment": paper_trade.confidence_adjustment,
        "learning_memory_used": paper_trade.learning_memory_used,
        "strategy_memory_used": paper_trade.strategy_memory_used,
        "research_priority_used": paper_trade.research_priority_used,
    }


def live_position_for_paper_trade(db: Session, game: LiveForwardPaperGame, paper_trade: LiveForwardPaperTrade) -> LiveForwardPaperPosition | None:
    if not paper_trade.ledger_trade_id:
        return None
    return db.scalar(
        select(LiveForwardPaperPosition)
        .where(
            LiveForwardPaperPosition.game_id == game.id,
            LiveForwardPaperPosition.trade_id == paper_trade.ledger_trade_id,
        )
        .limit(1)
    )


def serialize_paper_forward_trade(row: LiveForwardPaperTrade, *, compact: bool = False) -> dict:
    payload = {
        "trade_id": row.id,
        "trade_uid": row.trade_uid,
        "game_id": row.game_id,
        "ledger_trade_id": row.ledger_trade_id,
        "ticker": row.ticker,
        "setup_type": row.setup_type,
        "status": row.status,
        "close_reason": row.close_reason,
        "decision_timestamp": iso(row.decision_timestamp),
        "decision_date": iso(row.decision_date),
        "model_version_used": row.model_version_used,
        "entry_price": row.entry_price,
        "current_price": row.current_price,
        "exit_price": row.exit_price,
        "stop_loss": row.stop_loss,
        "invalidation_level": row.invalidation_level,
        "target_1": row.target_1,
        "target_2": row.target_2,
        "position_size": row.position_size,
        "risk_amount": row.risk_amount,
        "risk_percent": row.risk_percent,
        "expected_reward": row.expected_reward,
        "expected_r_multiple": row.expected_r_multiple,
        "unrealized_pnl": row.unrealized_pnl,
        "net_pnl_eur": row.net_pnl_eur,
        "pnl_percent": row.pnl_percent,
        "pnl_per_share": row.pnl_per_share,
        "r_multiple": row.r_multiple,
        "benchmark_return_same_period": row.benchmark_return_same_period,
        "excess_return_vs_benchmark": row.excess_return_vs_benchmark,
        "outcome_label": row.outcome_label,
        "lesson_learned": row.lesson_learned,
        "confidence": row.confidence,
        "sniper_score": row.sniper_score,
        "actionability_state": row.actionability_state,
        "feedback_loop_audit_id": row.feedback_loop_audit_id,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }
    if compact:
        return payload
    payload.update(
        {
            "asset_name": row.asset_name,
            "asset_type": row.asset_type,
            "sector": row.sector,
            "industry": row.industry,
            "weights_used": row.weights_used,
            "confidence_adjustment": row.confidence_adjustment,
            "learning_memory_used": row.learning_memory_used,
            "strategy_memory_used": row.strategy_memory_used,
            "research_priority_used": row.research_priority_used,
            "frozen_decision_payload": row.frozen_decision_payload,
            "entry_trigger": row.entry_trigger,
            "confirmation_condition": row.confirmation_condition,
            "opened_at": iso(row.opened_at),
            "closed_at": iso(row.closed_at),
            "max_favorable_excursion": row.max_favorable_excursion,
            "max_adverse_excursion": row.max_adverse_excursion,
            "target_1_hit": row.target_1_hit,
            "target_2_hit": row.target_2_hit,
            "stop_hit": row.stop_hit,
            "invalidation_hit": row.invalidation_hit,
            "expires_at": iso(row.expires_at),
        }
    )
    return payload


def serialize_live_event(row: LiveForwardPaperTradeEvent) -> dict:
    return {
        "id": row.id,
        "trade_id": row.paper_trade_id,
        "timestamp": iso(row.event_timestamp),
        "event_type": row.event_type,
        "price_used": row.price_used,
        "reason": row.reason,
        "payload": row.payload,
    }


def serialize_signal_memory(row: SignalPerformance) -> dict:
    return {
        "signal_name": row.signal_name,
        "timeframe": row.timeframe,
        "market_regime": row.market_regime,
        "sample_count": row.sample_count,
        "reliability_score": row.reliability_score,
        "weight_adjustment": row.weight_adjustment,
    }


def serialize_strategy_memory(row: StrategyMemory) -> dict:
    return {
        "memory_key": row.memory_key,
        "category": row.category,
        "sample_count": row.sample_count,
        "reliability_score": row.reliability_score,
        "lesson": row.lesson,
    }


def memory_confidence_adjustment(strategy_rows: list[StrategyMemory], signal_rows: list[SignalPerformance]) -> float:
    values = [safe_float(row.reliability_score, 50.0) for row in strategy_rows] + [safe_float(row.reliability_score, 50.0) for row in signal_rows]
    if not values:
        return 0.0
    return round(clamp((mean(values) - 50.0) / 10.0, -8.0, 8.0), 4)


def serialize_trade_lesson(row: TradeLearningEvidence) -> dict:
    return {
        "id": row.id,
        "ticker": row.ticker,
        "setup_type": row.setup_type,
        "lesson_type": row.lesson_type,
        "observation": row.observation,
        "confidence": row.confidence,
        "created_at": iso(row.created_at),
    }


def snapshot_blockers(candidate_rows: list[LiveForwardPaperTrade], open_rows: list[LiveForwardPaperTrade]) -> list[str]:
    blockers: list[str] = []
    if not open_rows:
        blockers.append("no_open_paper_forward_positions")
    if any(row.status == "DATA_BLOCKED" for row in candidate_rows):
        blockers.append("some_candidates_blocked_by_missing_market_data")
    if len(candidate_rows) == 0 and len(open_rows) == 0:
        blockers.append("no_recent_candidates_in_snapshot")
    return blockers


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
