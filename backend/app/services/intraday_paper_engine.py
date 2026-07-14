from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from time import monotonic
from typing import Callable, Iterable
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Asset,
    FeedbackLoopAudit,
    IntradayPaperRun,
    LearningEvent,
    LiveForwardPaperGame,
    LiveForwardPaperTrade,
    ReplayMarketBar,
    SignalPerformance,
    StrategyMemory,
    TradeLearningEvidence,
    TradingGameTrade,
)
from app.services.intraday_contracts import INTRADAY_TRADE_CANDIDATE, PAPER_FORWARD_INTRADAY, IntradayDecision
from app.services.intraday_market_data import StrictIntradayDataGateway
from app.services.intraday_opportunity import BlumIntradayOpportunityEngine, IntradayPortfolioState
from app.services.live_forward_paper_trading import LiveForwardPaperTradingService
from app.services.cross_market_orchestrator import enabled_agents, parse_names
from app.services.copy_readiness_evidence import EvidenceTimelineService, strategy_identity
from app.services.market_desks import MarketDeskRegistry
from app.services.promoted_strategy_registry import BlumPromotedStrategyRegistry, normalize_market
from app.services.trading_intelligence_lab import ensure_live_trade_game


INTRADAY_MODE = "INTRADAY_PAPER_FORWARD"
TERMINAL_STATUSES = {"CLOSED", "EXPIRED", "INVALIDATED"}
settings = get_settings()


class BlumIntradayPaperEngine:
    """Bounded command service for strict, forward-only intraday paper trades."""

    def __init__(
        self,
        *,
        registry: BlumPromotedStrategyRegistry | None = None,
        gateway: StrictIntradayDataGateway | None = None,
        opportunity: BlumIntradayOpportunityEngine | None = None,
        now_provider: Callable[[], datetime] = datetime.utcnow,
        refresh_missing: bool = True,
        max_assets: int | None = None,
        max_runtime_seconds: float | None = None,
        max_holding_minutes: int | None = None,
    ):
        self.registry = registry or BlumPromotedStrategyRegistry()
        self.gateway = gateway or StrictIntradayDataGateway(
            refresh_missing=refresh_missing,
            max_one_minute_age=timedelta(minutes=settings.intraday_max_one_minute_age_minutes),
        )
        self.opportunity = opportunity or BlumIntradayOpportunityEngine(
            min_expected_move_bps=settings.intraday_min_expected_move_bps,
            max_spread_to_target_ratio=settings.intraday_max_spread_to_target_ratio,
            min_liquidity_score=settings.intraday_min_liquidity_score,
            max_open_positions=settings.intraday_max_open_positions,
            max_positions_per_market=settings.intraday_max_positions_per_market,
            max_positions_per_desk=settings.intraday_max_positions_per_desk,
            max_positions_per_asset_class=settings.intraday_max_positions_per_asset_class,
            max_total_risk_percent=settings.intraday_max_total_risk_percent,
            min_volatility_bps=settings.intraday_min_volatility_bps,
        )
        self.now_provider = now_provider
        self.max_assets = max(1, int(max_assets if max_assets is not None else settings.intraday_max_assets_per_run))
        self.max_runtime_seconds = max(1.0, float(max_runtime_seconds if max_runtime_seconds is not None else settings.intraday_max_runtime_seconds))
        self.max_holding_minutes = max(1, int(max_holding_minutes if max_holding_minutes is not None else settings.intraday_max_holding_minutes))
        self.paper = LiveForwardPaperTradingService()
        self.learning = IntradayPaperLearningService()
        self._desk_context: dict[int, tuple[str, str]] = {}

    def run_once(self, db: Session, *, trigger: str = "manual", assets: Iterable[Asset] | None = None) -> dict:
        if not settings.intraday_paper_enabled:
            return {"status": "DISABLED", "evidence_type": PAPER_FORWARD_INTRADAY, "blockers": ["intraday_paper_disabled"]}
        now = self.now_provider()
        started = monotonic()
        run = IntradayPaperRun(
            run_uid=f"intraday-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
            trigger=trigger,
            status="RUNNING",
            started_at=now,
        )
        db.add(run)
        db.flush()
        blockers: list[dict] = []
        decisions: list[dict] = []
        try:
            game = self.paper.active_or_create_live_game(db)
            lifecycle = self._manage_open_trades(db, game=game, now=now)
            run.trades_updated = lifecycle["trades_updated"]
            run.trades_closed = lifecycle["trades_closed"]

            selected_assets = list(assets)[: self.max_assets] if assets is not None else self._discover_assets(db)
            if not selected_assets:
                blockers.append({"reason": "NO_DESK_ASSETS_WITH_INTRADAY_DATA", "detail": "No enabled USA/Europe desk asset currently has stored one-minute data."})
            run.assets_checked = 0
            seen_markets: set[str] = set()
            for asset in selected_assets:
                if monotonic() - started >= self.max_runtime_seconds:
                    blockers.append({"ticker": asset.ticker, "reason": "RUNTIME_BUDGET_EXHAUSTED"})
                    break
                market = normalize_market(asset.country or asset.exchange or "")
                seen_markets.add(market)
                run.assets_checked += 1
                strategies = self.registry.list_eligible(db, market=market, asset_class=asset.asset_type or asset.category or "Stock")
                if not strategies:
                    blockers.append({"ticker": asset.ticker, "market": market, "reason": "NO_PROMOTED_INTRADAY_STRATEGY"})
                    continue
                data = self.gateway.load(db, asset=asset, now=now)
                if not data.ready:
                    blockers.append({"ticker": asset.ticker, "market": market, "reason": "INTRADAY_DATA_BLOCKED", "blockers": list(data.blockers)})
                    continue
                for strategy in strategies:
                    portfolio = self._portfolio_state(db, game)
                    desk, benchmark = self._desk_context.get(asset.id, desk_and_benchmark(asset))
                    decision = self.opportunity.evaluate(
                        strategy=strategy,
                        data=data,
                        portfolio=portfolio,
                        desk=desk,
                        benchmark_ticker=benchmark,
                        asset_type=asset.asset_type or "Stock",
                    )
                    decisions.append(json_safe(decision.to_dict()))
                    if decision.status != INTRADAY_TRADE_CANDIDATE:
                        self._count_rejection(run, decision.reason_code)
                        continue
                    run.candidates_found += 1
                    trade, created = self._open_trade(db, game=game, run=run, asset=asset, decision=decision)
                    if created:
                        run.candidates_approved += 1
                        run.trades_opened += 1
                    else:
                        blockers.append({"ticker": trade.ticker, "reason": "DUPLICATE_INTRADAY_DECISION"})

            run.markets_checked = len(seen_markets)
            run.status = self._terminal_status(run=run, blockers=blockers, decisions=decisions)
            run.completed_at = now
            run.duration_seconds = round(monotonic() - started, 4)
            run.data_blockers = blockers
            run.summary_json = {
                "decisions": decisions[:50],
                "lifecycle": lifecycle,
                "policy": "Strict 1d/15m/5m/1m paper-forward evidence; no timeframe fallback or broker execution.",
            }
            self.paper.refresh_live_game_counts(db, game)
            db.commit()
            try:
                self.paper.publish_snapshot(db)
                db.commit()
            except Exception as snapshot_exc:
                db.rollback()
                blockers.append({"reason": "SNAPSHOT_REFRESH_FAILED", "detail": str(snapshot_exc)})
            return self._serialize_run(run, blockers)
        except Exception as exc:
            db.rollback()
            failed = IntradayPaperRun(
                run_uid=f"intraday-failed-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
                trigger=trigger,
                status="ERROR",
                started_at=now,
                completed_at=self.now_provider(),
                duration_seconds=round(monotonic() - started, 4),
                data_blockers=[{"reason": type(exc).__name__, "detail": str(exc)}],
                summary_json={"error": str(exc)},
            )
            db.add(failed)
            db.commit()
            return self._serialize_run(failed, failed.data_blockers)

    def _discover_assets(self, db: Session) -> list[Asset]:
        agent_types = enabled_agents(parse_names(settings.blum_enabled_market_desk_agents), stale_after_hours=settings.paper_forward_scan_stale_data_max_age_hours)
        discovery = MarketDeskRegistry(agents=agent_types).discover(db)
        ranked: list[Asset] = []
        seen: set[int] = set()
        for agent in discovery.available_agents:
            if agent.agent_name not in {"WallStreetAgent", "SP500Agent", "NasdaqAgent", "DowJonesAgent", "Russell2000Agent", "FTSEMIBAgent", "DAXAgent", "CAC40Agent", "ETFDeskAgent"}:
                continue
            for asset in list(getattr(agent, "_eligible_assets", None) or []):
                if asset.id in seen:
                    continue
                seen.add(asset.id)
                self._desk_context[asset.id] = (agent.agent_name, agent.benchmark)
                ranked.append(asset)
                if len(ranked) >= self.max_assets:
                    return ranked
        return ranked

    def _portfolio_state(self, db: Session, game: LiveForwardPaperGame) -> IntradayPortfolioState:
        rows = db.scalars(
            select(LiveForwardPaperTrade).where(
                LiveForwardPaperTrade.game_id == game.id,
                LiveForwardPaperTrade.trading_mode == INTRADAY_MODE,
                LiveForwardPaperTrade.status == "OPEN",
            )
        ).all()
        markets = Counter(row.market or "UNKNOWN" for row in rows)
        desks = Counter(row.desk or "UNKNOWN" for row in rows)
        classes = Counter(row.asset_type or "UNKNOWN" for row in rows)
        return IntradayPortfolioState(
            capital=float(game.current_capital or game.starting_capital or 0.0),
            open_tickers=frozenset(row.ticker.upper() for row in rows),
            positions_by_market=dict(markets),
            positions_by_desk=dict(desks),
            positions_by_asset_class=dict(classes),
            total_open_positions=len(rows),
            total_risk_percent=sum(float(row.risk_percent or 0.0) for row in rows),
        )

    def _open_trade(
        self,
        db: Session,
        *,
        game: LiveForwardPaperGame,
        run: IntradayPaperRun,
        asset: Asset,
        decision: IntradayDecision,
    ) -> tuple[LiveForwardPaperTrade, bool]:
        trigger_timestamp = (decision.evidence.get("data_timestamps") or {}).get("1m") or decision.decision_timestamp.isoformat()
        duplicate_key = f"intraday:{asset.ticker}:{decision.validation_id}:{trigger_timestamp}"
        existing = db.scalar(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.duplicate_key == duplicate_key).limit(1))
        if existing:
            return existing, False

        feedback = self.paper.feedback_metadata(db, ticker=asset.ticker, setup_type=decision.setup_type)
        costs = decision.costs or {}
        observed_entry = float(decision.entry_price or 0.0)
        one_way_bps = float(costs.get("one_way_bps") or 0.0)
        entry_fill = observed_entry * (1 + one_way_bps / 10_000)
        quantity = float(decision.sizing.quantity if decision.sizing else 0.0)
        risk_per_share = max(0.0001, entry_fill - float(decision.stop_price or entry_fill))
        frozen = {
            "evidence_type": PAPER_FORWARD_INTRADAY,
            "trading_mode": INTRADAY_MODE,
            "strategy": {
                "id": decision.strategy_id,
                "validation_id": decision.validation_id,
                "setup_type": decision.setup_type,
            },
            "decision_timestamp": decision.decision_timestamp.isoformat(),
            "observed_entry_price": observed_entry,
            "paper_entry_fill": entry_fill,
            "stop_price": decision.stop_price,
            "target_price": decision.target_price,
            "costs": costs,
            "evidence": decision.evidence,
            "regime": decision.regime,
            "session": decision.session,
            "feedback": feedback,
            "no_future_data_policy": "Only market bars timestamped at or before this decision were used.",
        }
        trade = LiveForwardPaperTrade(
            trade_uid=f"ipf-{decision.decision_timestamp.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
            game_id=game.id,
            ticker=asset.ticker.upper(),
            asset_name=asset.name or asset.ticker,
            asset_type=asset.asset_type,
            sector=asset.sector,
            setup_type=decision.setup_type,
            status="OPEN",
            decision_timestamp=decision.decision_timestamp,
            decision_date=decision.decision_timestamp.date(),
            model_version_used=feedback["model_version_used"],
            weights_used=feedback["weights_used"],
            confidence_adjustment=float(feedback.get("confidence_adjustment") or 0.0),
            learning_memory_used=feedback["learning_memory_used"],
            strategy_memory_used=feedback["strategy_memory_used"],
            research_priority_used=feedback["research_priority_used"],
            frozen_decision_payload=frozen,
            trading_mode=INTRADAY_MODE,
            evidence_type=PAPER_FORWARD_INTRADAY,
            promoted_validation_id=decision.validation_id,
            intraday_run_id=run.id,
            market=normalize_market(decision.market),
            desk=decision.desk,
            session_name=decision.session,
            timeframe_stack=["1d", "15m", "5m", "1m"],
            data_timestamps=decision.evidence.get("data_timestamps") or {},
            execution_costs=costs,
            net_expectancy_bps=decision.net_expectancy_bps,
            sizing_reason=decision.sizing.reason if decision.sizing else None,
            actionability_state="active_setup",
            confidence=decision.confidence,
            sniper_score=decision.edge_score,
            benchmark_ticker=decision.benchmark_ticker,
            entry_trigger="Strict 1m trigger after 5m confirmation inside 15m setup and 1d regime.",
            confirmation_condition="All promoted-strategy and strict data gates passed.",
            entry_price=entry_fill,
            entry_date=decision.decision_timestamp.date(),
            opened_at=decision.decision_timestamp,
            stop_loss=decision.stop_price,
            invalidation_level=decision.stop_price,
            target_1=decision.target_price,
            target_2=None,
            trailing_stop=decision.trailing_stop,
            position_size=quantity,
            notional_value=quantity * entry_fill,
            risk_amount=quantity * risk_per_share,
            risk_percent=float(decision.sizing.risk_percent if decision.sizing else 0.0),
            expected_risk=quantity * risk_per_share,
            expected_reward=quantity * max(0.0, float(decision.target_price or entry_fill) - entry_fill),
            expected_r_multiple=max(0.0, float(decision.target_price or entry_fill) - entry_fill) / risk_per_share,
            current_price=entry_fill,
            last_managed_bar_at=decision.decision_timestamp,
            duplicate_key=duplicate_key,
            intraday_metadata={"observed_entry_price": observed_entry, "entry_one_way_bps": one_way_bps},
        )
        db.add(trade)
        db.flush()
        self._create_ledger_trade(db, game, trade)
        self.paper.append_event(db, trade.id, "INTRADAY_TRADE_CANDIDATE", "Promoted strategy passed all strict intraday gates.", frozen, observed_entry)
        self.paper.append_event(db, trade.id, "INTRADAY_TRADE_OPENED", "Paper position opened with adverse execution cost model; no broker execution.", {"quantity": quantity, "entry_fill": entry_fill}, entry_fill)
        game.cash = max(0.0, float(game.cash or 0.0) - float(trade.notional_value or 0.0))
        game.exposure = float(game.exposure or 0.0) + float(trade.notional_value or 0.0)
        game.open_positions = int(game.open_positions or 0) + 1
        game.updated_at = decision.decision_timestamp
        return trade, True

    def _create_ledger_trade(self, db: Session, game: LiveForwardPaperGame, trade: LiveForwardPaperTrade) -> None:
        ledger_game = ensure_live_trade_game(db)
        ledger = TradingGameTrade(
            game_id=ledger_game.id,
            mode="live_forward_paper",
            ticker=trade.ticker,
            asset_name=trade.asset_name or trade.ticker,
            asset_type=trade.asset_type,
            sector=trade.sector,
            setup_type=trade.setup_type,
            sniper_score_at_entry=trade.sniper_score,
            confidence_at_entry=trade.confidence,
            actionability_state_at_entry=trade.actionability_state,
            market_regime_at_entry=(trade.frozen_decision_payload or {}).get("regime"),
            benchmark_ticker=trade.benchmark_ticker or game.benchmark_ticker,
            timeframe="1m",
            decision_state="active_setup",
            entry_date=trade.entry_date,
            entry_price=trade.entry_price,
            entry_reason="Strict promoted intraday setup confirmed.",
            entry_trigger=trade.entry_trigger,
            confirmation_condition=trade.confirmation_condition,
            position_size=trade.position_size,
            notional_value=trade.notional_value,
            risk_amount=trade.risk_amount,
            risk_percent=trade.risk_percent,
            stop_loss=trade.stop_loss,
            invalidation_level=trade.invalidation_level,
            initial_target_1=trade.target_1,
            capital_before=game.current_capital,
            capital_after=game.current_capital,
            reproducibility_score=90.0,
            data_quality_score=minimum_quality_from_trade(trade),
            outcome_label="open",
            payload={"paper_forward_trade_id": trade.id, "evidence_type": PAPER_FORWARD_INTRADAY, "frozen_decision_payload": trade.frozen_decision_payload},
        )
        db.add(ledger)
        db.flush()
        trade.ledger_trade_id = ledger.id

    def _manage_open_trades(self, db: Session, *, game: LiveForwardPaperGame, now: datetime) -> dict:
        rows = db.scalars(
            select(LiveForwardPaperTrade).where(
                LiveForwardPaperTrade.game_id == game.id,
                LiveForwardPaperTrade.trading_mode == INTRADAY_MODE,
                LiveForwardPaperTrade.status == "OPEN",
            )
        ).all()
        updated = 0
        closed = 0
        for trade in rows:
            asset = db.scalar(select(Asset).where(func.upper(Asset.ticker) == trade.ticker.upper()).limit(1))
            if not asset:
                continue
            bars = db.scalars(
                select(ReplayMarketBar)
                .where(
                    ReplayMarketBar.asset_id == asset.id,
                    ReplayMarketBar.timeframe == "1m",
                    ReplayMarketBar.bar_timestamp > (trade.last_managed_bar_at or trade.opened_at or trade.decision_timestamp),
                    ReplayMarketBar.bar_timestamp <= now,
                )
                .order_by(ReplayMarketBar.bar_timestamp)
                .limit(500)
            ).all()
            for bar in bars:
                updated += 1
                trade.last_managed_bar_at = bar.bar_timestamp
                trade.current_price = float(bar.close)
                trade.holding_minutes = max(0.0, (bar.bar_timestamp - (trade.opened_at or trade.decision_timestamp)).total_seconds() / 60)
                self._update_excursions(trade, bar)
                close_reason, raw_exit = self._exit_for_bar(trade, bar)
                if close_reason:
                    self._close_trade(db, game=game, trade=trade, bar=bar, raw_exit=raw_exit, reason=close_reason)
                    closed += 1
                    self.learning.apply_closed_trade(db, trade)
                    break
                trade.trailing_stop = max(float(trade.trailing_stop or 0.0), float(bar.close) - max(0.0001, float(bar.high) - float(bar.low)) * 1.2)
                trade.unrealized_pnl = (float(bar.close) - float(trade.entry_price or bar.close)) * float(trade.position_size or 0.0)
                self.paper.append_event(db, trade.id, "INTRADAY_TRADE_UPDATED", "Position marked using a later one-minute bar.", {"bar_timestamp": bar.bar_timestamp.isoformat()}, float(bar.close))
        return {"trades_updated": updated, "trades_closed": closed}

    def _exit_for_bar(self, trade: LiveForwardPaperTrade, bar: ReplayMarketBar) -> tuple[str | None, float | None]:
        low = float(bar.low if bar.low is not None else bar.close)
        high = float(bar.high if bar.high is not None else bar.close)
        if trade.stop_loss and low <= float(trade.stop_loss):
            return "STOP_HIT", min(float(trade.stop_loss), float(bar.open or bar.close))
        if trade.invalidation_level and low <= float(trade.invalidation_level):
            return "INVALIDATION_HIT", min(float(trade.invalidation_level), float(bar.open or bar.close))
        if trade.target_1 and high >= float(trade.target_1):
            return "TARGET_HIT", float(trade.target_1)
        if trade.trailing_stop and low <= float(trade.trailing_stop) and float(trade.trailing_stop) > float(trade.entry_price or 0.0):
            return "TRAILING_STOP", float(trade.trailing_stop)
        opened_at = trade.opened_at or trade.decision_timestamp
        holding = (bar.bar_timestamp - opened_at).total_seconds() / 60
        if bar.bar_timestamp.date() > opened_at.date():
            return "MARKET_CLOSE", float(bar.open or bar.close)
        if holding >= self.max_holding_minutes:
            return "TIME_STOP", float(bar.close)
        return None, None

    def _close_trade(self, db: Session, *, game: LiveForwardPaperGame, trade: LiveForwardPaperTrade, bar: ReplayMarketBar, raw_exit: float, reason: str) -> None:
        costs = trade.execution_costs or {}
        one_way_bps = float(costs.get("one_way_bps") or 0.0)
        exit_fill = float(raw_exit) * (1 - one_way_bps / 10_000)
        quantity = float(trade.position_size or 0.0)
        observed_entry = float((trade.intraday_metadata or {}).get("observed_entry_price") or trade.entry_price or 0.0)
        gross = (float(raw_exit) - observed_entry) * quantity
        net = (exit_fill - float(trade.entry_price or 0.0)) * quantity
        total_cost = max(0.0, gross - net)
        initial_risk = max(0.0001, float(trade.expected_risk or trade.risk_amount or 0.0001))
        trade.status = "CLOSED"
        trade.close_reason = reason
        trade.exit_price = exit_fill
        trade.exit_date = bar.bar_timestamp.date()
        trade.closed_at = bar.bar_timestamp
        trade.gross_pnl_eur = round(gross, 6)
        trade.net_pnl_eur = round(net, 6)
        trade.pnl_per_share = round(exit_fill - float(trade.entry_price or 0.0), 6)
        trade.pnl_percent = round((exit_fill / float(trade.entry_price or 1.0) - 1) * 100, 6)
        trade.r_multiple = round(net / initial_risk, 6)
        trade.costs_paid = round(total_cost, 6)
        trade.spread_cost = round(float(costs.get("spread_bps") or 0.0) / 10_000 * observed_entry * quantity, 6)
        trade.slippage_cost = round(float(costs.get("slippage_bps") or 0.0) * 2 / 10_000 * observed_entry * quantity, 6)
        trade.commission_cost = round(float(costs.get("commission_bps") or 0.0) * 2 / 10_000 * observed_entry * quantity, 6)
        trade.stop_hit = reason == "STOP_HIT"
        trade.invalidation_hit = reason == "INVALIDATION_HIT"
        trade.target_1_hit = reason == "TARGET_HIT"
        trade.outcome_label = "win" if net > 0 else "loss" if net < 0 else "breakeven"
        self._update_benchmark_outcome(db, trade, bar.bar_timestamp)
        trade.lesson_learned = intraday_lesson(trade)
        trade.unrealized_pnl = 0.0
        game.cash = float(game.cash or 0.0) + exit_fill * quantity
        game.exposure = max(0.0, float(game.exposure or 0.0) - float(trade.notional_value or 0.0))
        game.realized_pl = float(game.realized_pl or 0.0) + net
        game.current_capital = float(game.cash or 0.0) + float(game.exposure or 0.0)
        game.open_positions = max(0, int(game.open_positions or 0) - 1)
        game.updated_at = bar.bar_timestamp
        ledger = db.get(TradingGameTrade, trade.ledger_trade_id) if trade.ledger_trade_id else None
        if ledger:
            ledger.exit_date = trade.exit_date
            ledger.exit_price = exit_fill
            ledger.exit_reason = reason
            ledger.holding_days = max(0, (trade.exit_date - trade.entry_date).days) if trade.entry_date else 0
            ledger.gross_pnl_eur = trade.gross_pnl_eur
            ledger.net_pnl_eur = trade.net_pnl_eur
            ledger.pnl_percent = trade.pnl_percent
            ledger.pnl_per_share = trade.pnl_per_share
            ledger.r_multiple = trade.r_multiple
            ledger.outcome_label = trade.outcome_label
            ledger.capital_after = game.current_capital
            ledger.benchmark_return_same_period = trade.benchmark_return_same_period
            ledger.excess_return_vs_benchmark = trade.excess_return_vs_benchmark
        self.paper.append_event(db, trade.id, "INTRADAY_TRADE_CLOSED", f"Intraday paper trade closed: {reason}.", {"bar_timestamp": bar.bar_timestamp.isoformat(), "gross_pnl": gross, "net_pnl": net, "costs_paid": total_cost}, exit_fill)
        self.paper.append_event(db, trade.id, "INTRADAY_OUTCOME_EVALUATED", "Closed intraday outcome evaluated against stored benchmark data when available.", {"r_multiple": trade.r_multiple, "benchmark_return": trade.benchmark_return_same_period, "benchmark_excess": trade.excess_return_vs_benchmark}, exit_fill)

    def _update_benchmark_outcome(self, db: Session, trade: LiveForwardPaperTrade, exit_timestamp: datetime) -> None:
        benchmark = db.scalar(select(Asset).where(func.upper(Asset.ticker) == str(trade.benchmark_ticker or "").upper()).limit(1))
        if benchmark is None:
            return
        entry_row = db.scalar(
            select(ReplayMarketBar)
            .where(ReplayMarketBar.asset_id == benchmark.id, ReplayMarketBar.timeframe == "1m", ReplayMarketBar.bar_timestamp <= (trade.opened_at or trade.decision_timestamp))
            .order_by(desc(ReplayMarketBar.bar_timestamp))
            .limit(1)
        )
        exit_row = db.scalar(
            select(ReplayMarketBar)
            .where(ReplayMarketBar.asset_id == benchmark.id, ReplayMarketBar.timeframe == "1m", ReplayMarketBar.bar_timestamp <= exit_timestamp)
            .order_by(desc(ReplayMarketBar.bar_timestamp))
            .limit(1)
        )
        if entry_row is None or exit_row is None or float(entry_row.close or 0.0) <= 0:
            return
        benchmark_return = (float(exit_row.close) / float(entry_row.close) - 1) * 100
        trade.benchmark_return_same_period = round(benchmark_return, 6)
        trade.excess_return_vs_benchmark = round(float(trade.pnl_percent or 0.0) - benchmark_return, 6)

    @staticmethod
    def _update_excursions(trade: LiveForwardPaperTrade, bar: ReplayMarketBar) -> None:
        entry = float(trade.entry_price or 0.0)
        if entry <= 0:
            return
        high = float(bar.high if bar.high is not None else bar.close)
        low = float(bar.low if bar.low is not None else bar.close)
        trade.max_favorable_excursion = max(float(trade.max_favorable_excursion or 0.0), (high / entry - 1) * 100)
        trade.max_adverse_excursion = min(float(trade.max_adverse_excursion or 0.0), (low / entry - 1) * 100)

    @staticmethod
    def _count_rejection(run: IntradayPaperRun, reason: str) -> None:
        if "COST" in reason or "SPREAD" in reason or "EXPECTED_MOVE" in reason:
            run.rejected_due_to_costs += 1
        elif "CONCENTRATION" in reason or "MAX_OPEN" in reason:
            run.rejected_due_to_concentration += 1
        else:
            run.rejected_due_to_risk += 1

    @staticmethod
    def _terminal_status(*, run: IntradayPaperRun, blockers: list[dict], decisions: list[dict]) -> str:
        blocker_reasons = {str(blocker.get("reason") or "") for blocker in blockers}
        if "RUNTIME_BUDGET_EXHAUSTED" in blocker_reasons:
            return "PAUSED_FOR_RUNTIME"
        if run.trades_opened or run.trades_updated or run.trades_closed:
            return "COMPLETED"
        decision_reasons = {str(decision.get("reason_code") or "") for decision in decisions}
        if decision_reasons and decision_reasons == {"SESSION_NOT_ALLOWED"}:
            return "MARKET_CLOSED"
        if blocker_reasons & {"NO_DESK_ASSETS_WITH_INTRADAY_DATA", "INTRADAY_DATA_BLOCKED"}:
            return "DATA_BLOCKED"
        return "COMPLETED"

    @staticmethod
    def _serialize_run(run: IntradayPaperRun, blockers: list[dict]) -> dict:
        return {
            "status": run.status,
            "run_id": run.run_uid,
            "assets_checked": run.assets_checked,
            "markets_checked": run.markets_checked,
            "candidates_found": run.candidates_found,
            "candidates_approved": run.candidates_approved,
            "trades_opened": run.trades_opened,
            "trades_updated": run.trades_updated,
            "trades_closed": run.trades_closed,
            "rejected_due_to_costs": run.rejected_due_to_costs,
            "rejected_due_to_risk": run.rejected_due_to_risk,
            "rejected_due_to_concentration": run.rejected_due_to_concentration,
            "blockers": blockers,
            "data_blockers": blockers,
            "next_action": "Continue on the next fresh one-minute bar." if run.trades_opened or run.trades_updated else "Resolve recorded blockers; never force activity.",
            "duration_seconds": run.duration_seconds,
            "evidence_type": PAPER_FORWARD_INTRADAY,
        }


class IntradayPaperLearningService:
    """Translate a resolved intraday trade into idempotent forward evidence."""

    def apply_closed_trade(self, db: Session, trade: LiveForwardPaperTrade) -> dict:
        if trade.status not in TERMINAL_STATUSES or trade.closed_at is None:
            return {"status": "not_closed", "trade_id": trade.id}
        identity = f"intraday_trade:{trade.id}"
        existing = db.scalar(select(TradeLearningEvidence).where(TradeLearningEvidence.action_taken == identity).limit(1))
        if existing:
            return {"status": "duplicate", "trade_id": trade.id, "evidence_id": existing.id}
        positive = float(trade.net_pnl_eur or 0.0) > 0
        lesson_type = "setup_confirmed" if positive else "setup_failed"
        observation = intraday_lesson(trade)
        evidence = TradeLearningEvidence(
            trade_id=trade.ledger_trade_id,
            ticker=trade.ticker,
            setup_type=trade.setup_type,
            regime=(trade.frozen_decision_payload or {}).get("regime") or "unknown",
            lesson_type=lesson_type,
            observation=observation,
            sample_size=1,
            supporting_trades_json={
                "paper_forward_trade_id": trade.id,
                "evidence_type": PAPER_FORWARD_INTRADAY,
                "market": trade.market,
                "desk": trade.desk,
                "timeframe_stack": trade.timeframe_stack,
                "session": trade.session_name,
                "exit_reason": trade.close_reason,
                "costs_paid": trade.costs_paid,
                "r_multiple": trade.r_multiple,
                "benchmark_excess": trade.excess_return_vs_benchmark,
            },
            affected_module="intraday_paper_engine",
            action_taken=identity,
            confidence=max(10.0, min(90.0, 50.0 + abs(float(trade.r_multiple or 0.0)) * 10.0)),
        )
        db.add(evidence)
        memory_key = f"intraday:{trade.setup_type}:{trade.market or 'unknown'}:{(trade.frozen_decision_payload or {}).get('regime') or 'unknown'}"
        memory = db.scalar(select(StrategyMemory).where(StrategyMemory.memory_key == memory_key).limit(1))
        if memory is None:
            memory = StrategyMemory(memory_key=memory_key, category="intraday_paper", conditions={"setup": trade.setup_type, "market": trade.market, "regime": (trade.frozen_decision_payload or {}).get("regime")}, evidence={})
            db.add(memory)
        memory.sample_count = int(memory.sample_count or 0) + 1
        memory.positive_count = int(memory.positive_count or 0) + (1 if positive else 0)
        memory.negative_count = int(memory.negative_count or 0) + (0 if positive else 1)
        memory.reliability_score = round(memory.positive_count / max(1, memory.sample_count) * 100, 4)
        memory.lesson = observation
        memory.evidence = {"latest_trade_id": trade.id, "latest_r_multiple": trade.r_multiple, "latest_costs_paid": trade.costs_paid, "evidence_type": PAPER_FORWARD_INTRADAY}
        memory.last_seen_at = trade.closed_at

        signal_name = f"intraday:{trade.setup_type}"
        signal = db.scalar(select(SignalPerformance).where(SignalPerformance.signal_name == signal_name, SignalPerformance.timeframe == "1m", SignalPerformance.market_regime == ((trade.frozen_decision_payload or {}).get("regime") or "unknown")).limit(1))
        if signal is None:
            signal = SignalPerformance(signal_name=signal_name, timeframe="1m", market_regime=(trade.frozen_decision_payload or {}).get("regime") or "unknown")
            db.add(signal)
        signal.sample_count = int(signal.sample_count or 0) + 1
        signal.correct_count = int(signal.correct_count or 0) + (1 if positive else 0)
        signal.false_positive_count = int(signal.false_positive_count or 0) + (0 if positive else 1)
        signal.reliability_score = round(signal.correct_count / max(1, signal.sample_count) * 100, 4)
        signal.average_return = running_average(signal.average_return, signal.sample_count, float(trade.pnl_percent or 0.0))
        signal.evidence = {"latest_trade_id": trade.id, "evidence_type": PAPER_FORWARD_INTRADAY, "costs_paid": trade.costs_paid}
        audit = FeedbackLoopAudit(
            ticker=trade.ticker,
            model_version_used=trade.model_version_used or "base-static",
            learned_knowledge_json={"lesson": observation, "strategy_memory_key": memory_key, "signal": signal_name},
            changes_applied_json={"strategy_reliability": memory.reliability_score, "signal_reliability": signal.reliability_score},
            future_decision_json={"source_trade_id": trade.id, "evidence_type": PAPER_FORWARD_INTRADAY, "applies_to_future_only": True},
            outcome_json={"r_multiple": trade.r_multiple, "net_pnl": trade.net_pnl_eur, "benchmark_excess": trade.excess_return_vs_benchmark, "close_reason": trade.close_reason},
            improvement_detected=False,
            evidence_grade="insufficient" if signal.sample_count < 30 else "forward_sample",
            summary="Closed intraday paper outcome stored for future-only confidence and reliability calibration.",
        )
        db.add(audit)
        db.add(LearningEvent(event_type="intraday_paper_trade_closed", severity="Info", title=f"{trade.ticker} intraday paper outcome", description=observation, payload={"paper_forward_trade_id": trade.id, "evidence_type": PAPER_FORWARD_INTRADAY, "r_multiple": trade.r_multiple}))
        db.flush()
        strategy_id = strategy_identity(trade.setup_type, trade.promoted_validation_id)[0]
        timeline = EvidenceTimelineService()
        timeline.append_once(
            db,
            event_key=f"intraday-lesson:{trade.id}",
            event_type="lesson_created",
            strategy_id=strategy_id,
            trade_id=trade.id,
            payload={"evidence_id": evidence.id, "lesson_type": lesson_type, "observation": observation},
        )
        timeline.append_once(
            db,
            event_key=f"intraday-memory:{trade.id}",
            event_type="memory_updated",
            strategy_id=strategy_id,
            trade_id=trade.id,
            payload={"strategy_memory_key": memory_key, "signal_name": signal_name, "sample_size": signal.sample_count},
        )
        return {"status": "applied", "trade_id": trade.id, "evidence_id": evidence.id, "memory_key": memory_key}


def intraday_snapshot_summary(db: Session, *, now: datetime | None = None) -> dict:
    """Read-only projection; callers must never trigger the intraday command."""

    now = now or datetime.utcnow()
    day = now.date()
    latest_run = db.scalar(select(IntradayPaperRun).order_by(desc(IntradayPaperRun.started_at)).limit(1))
    rows = db.scalars(select(LiveForwardPaperTrade).where(LiveForwardPaperTrade.evidence_type == PAPER_FORWARD_INTRADAY).order_by(desc(LiveForwardPaperTrade.created_at)).limit(500)).all()
    today_rows = [row for row in rows if (row.decision_date or row.created_at.date()) == day]
    closed = [row for row in rows if row.status in TERMINAL_STATUSES]
    costs = sum(float(row.costs_paid or 0.0) for row in closed)
    open_rows = [row for row in rows if row.status == "OPEN"]
    rejection_counts = {
        "rejected_due_to_costs": int(latest_run.rejected_due_to_costs or 0) if latest_run else 0,
        "rejected_due_to_concentration": int(latest_run.rejected_due_to_concentration or 0) if latest_run else 0,
    }
    if not latest_run:
        inactivity_reason = "No intraday run has completed."
        next_action = "Wait for the bounded backend worker or invoke the explicit manual POST."
    elif not rows:
        latest_blockers = latest_run.data_blockers or []
        inactivity_reason = str((latest_blockers[0] if latest_blockers else {}).get("reason") or "No strategy passed all forward gates.")
        next_action = "Resolve the recorded data/promotion blocker; do not force a paper trade."
    else:
        inactivity_reason = None
        next_action = "Manage open positions from later one-minute bars and continue strict scans."
    return {
        "status": latest_run.status if latest_run else "NO_INTRADAY_RUNS",
        "intraday_engine_status": latest_run.status if latest_run else "NO_INTRADAY_RUNS",
        "last_run_at": latest_run.started_at.isoformat() if latest_run else None,
        "last_run_duration_seconds": latest_run.duration_seconds if latest_run else None,
        "intraday_scans_today": int(db.scalar(select(func.count(IntradayPaperRun.id)).where(func.date(IntradayPaperRun.started_at) == day)) or 0),
        "candidates_today": len(today_rows),
        "intraday_candidates_today": len(today_rows),
        "trades_opened_today": sum(1 for row in today_rows if row.opened_at is not None),
        "intraday_opened_today": sum(1 for row in today_rows if row.opened_at is not None),
        "trades_closed_today": sum(1 for row in rows if row.closed_at and row.closed_at.date() == day),
        "intraday_closed_today": sum(1 for row in rows if row.closed_at and row.closed_at.date() == day),
        "open_positions": len(open_rows),
        "open_positions_by_market": dict(Counter(row.market or "UNKNOWN" for row in open_rows)),
        "open_positions_by_desk": dict(Counter(row.desk or "UNKNOWN" for row in open_rows)),
        "open_positions_by_ticker": dict(Counter(row.ticker for row in open_rows)),
        "distinct_markets_traded_today": len({row.market for row in today_rows if row.market}),
        "distinct_tickers_traded_today": len({row.ticker for row in today_rows if row.ticker}),
        "closed_sample_size": len(closed),
        "realized_pnl": round(sum(float(row.net_pnl_eur or 0.0) for row in closed), 4) if closed else None,
        "average_r": round(sum(float(row.r_multiple or 0.0) for row in closed) / len(closed), 4) if closed else None,
        "benchmark_excess": average_present([row.excess_return_vs_benchmark for row in closed]),
        "average_holding_minutes": average_present([row.holding_minutes for row in closed]),
        "avg_holding_minutes": average_present([row.holding_minutes for row in closed]),
        "avg_net_r": round(sum(float(row.r_multiple or 0.0) for row in closed) / len(closed), 4) if closed else None,
        "realized_intraday_pnl": round(sum(float(row.net_pnl_eur or 0.0) for row in closed), 4) if closed else None,
        "intraday_benchmark_excess": average_present([row.excess_return_vs_benchmark for row in closed]),
        "costs_paid": round(costs, 4) if closed else None,
        **rejection_counts,
        "reason_if_no_intraday_trades": inactivity_reason,
        "next_intraday_action": next_action,
        "markets": dict(Counter(row.market or "UNKNOWN" for row in rows)),
        "desks": dict(Counter(row.desk or "UNKNOWN" for row in rows)),
        "setups": dict(Counter(row.setup_type for row in rows)),
        "latest_blockers": latest_run.data_blockers if latest_run else ["No intraday run has completed."],
        "evidence_type": PAPER_FORWARD_INTRADAY,
        "policy": "Read-only forward paper evidence. No trade or recalculation is triggered by this snapshot.",
    }


def desk_and_benchmark(asset: Asset) -> tuple[str, str]:
    country = normalize_market(asset.country or "")
    exchange = str(asset.exchange or "").upper()
    if country == "USA" and "NASDAQ" in exchange:
        return "NasdaqAgent", "QQQ"
    if country == "USA":
        return "WallStreetAgent", "SPY"
    if country == "ITALY":
        return "FTSEMIBAgent", "FTSEMIB.MI"
    if country == "GERMANY":
        return "DAXAgent", "^GDAXI"
    if country == "FRANCE":
        return "CAC40Agent", "^FCHI"
    return "CrossMarketAgent", "SPY"


def intraday_lesson(trade: LiveForwardPaperTrade) -> str:
    result = "worked" if float(trade.net_pnl_eur or 0.0) > 0 else "failed"
    return f"{trade.setup_type} {result} in {trade.market or 'unknown'} / {(trade.frozen_decision_payload or {}).get('regime') or 'unknown'} after costs; exit={trade.close_reason}, R={float(trade.r_multiple or 0.0):.2f}."


def running_average(previous: float | None, sample_count: int, value: float) -> float:
    previous_count = max(0, int(sample_count) - 1)
    return round(((float(previous or 0.0) * previous_count) + value) / max(1, int(sample_count)), 6)


def minimum_quality_from_trade(trade: LiveForwardPaperTrade) -> float | None:
    evidence = (trade.frozen_decision_payload or {}).get("evidence") or {}
    values = [float(value) for value in (evidence.get("quality_scores") or {}).values() if value is not None]
    return min(values) if values else None


def average_present(values: list[float | None]) -> float | None:
    present = [float(value) for value in values if value is not None]
    return round(sum(present) / len(present), 4) if present else None


def json_safe(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(item) for item in value]
    return value
