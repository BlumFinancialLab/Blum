from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time
from statistics import mean, median

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Asset,
    EquityCurveAnnotation,
    ExecutionSimulation,
    HistoricalPrediction,
    TradeEngineAttribution,
    TradeLearningEvidence,
    TradeQualityScore,
    TradingGame,
    TradingGameEquityCurve,
    TradingGameRealityCheck,
    TradingGameTrade,
)


settings = get_settings()

TRANSPARENCY_POLICY = (
    "Paper trading transparency only. Simulated P/L is research evidence, not a promise of future performance. "
    "Every trade is tied to entry, exit, risk, benchmark and learning evidence when data exists."
)


class TradeLedgerService:
    """Auditable trade ledger for BLUM's reproducible paper Trading Game."""

    def ledger(
        self,
        db: Session,
        game_id: int | None = None,
        ticker: str | None = None,
        setup_type: str | None = None,
        outcome_label: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        min_r: float | None = None,
        max_r: float | None = None,
        only_open: bool = False,
        only_closed: bool = False,
        sort_by: str = "created_at_desc",
        limit: int = 200,
        offset: int = 0,
        refresh: bool = True,
        use_snapshot: bool = True,
        include_trace: bool = False,
    ) -> dict:
        if use_snapshot and self._can_use_ledger_snapshot(
            ticker=ticker,
            setup_type=setup_type,
            outcome_label=outcome_label,
            start_date=start_date,
            end_date=end_date,
            min_r=min_r,
            max_r=max_r,
            only_open=only_open,
            only_closed=only_closed,
            sort_by=sort_by,
        ):
            from app.services.trading_game_runtime import TradingGameRuntimeSnapshotService

            snapshot_payload = TradingGameRuntimeSnapshotService().ledger_from_snapshot(db, game_id=game_id, limit=limit, offset=offset)
            if snapshot_payload is not None:
                return snapshot_payload
        game = self.game(db, game_id)
        if not game:
            return {"status": "no_game", "rows": [], "summary": {}, "policy": TRANSPARENCY_POLICY}
        from app.services.trading_game_runtime import RuntimeTrace, payload_size_bytes

        trace = RuntimeTrace("trading_game_ledger_live_read")
        if refresh:
            with trace.phase("refresh_transparency"):
                self.refresh_game_transparency(db, game, commit=False, persist_reality=False)
        with trace.phase("base_trade_query"):
            query = select(TradingGameTrade).where(TradingGameTrade.game_id == game.id)
            if ticker:
                query = query.where(TradingGameTrade.ticker == ticker.upper())
            if setup_type:
                query = query.where(TradingGameTrade.setup_type == setup_type)
            if outcome_label:
                query = query.where(TradingGameTrade.outcome_label == outcome_label)
            parsed_start = parse_date(start_date)
            parsed_end = parse_date(end_date)
            if parsed_start:
                query = query.where(TradingGameTrade.entry_date >= parsed_start)
            if parsed_end:
                query = query.where(TradingGameTrade.entry_date <= parsed_end)
            if min_r is not None:
                query = query.where(TradingGameTrade.realized_r_multiple >= min_r)
            if max_r is not None:
                query = query.where(TradingGameTrade.realized_r_multiple <= max_r)
            if only_open:
                query = query.where(TradingGameTrade.exit_date.is_(None))
            if only_closed:
                query = query.where(TradingGameTrade.exit_date.is_not(None))
            total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
            query = order_trade_query(query, sort_by).limit(limit).offset(offset)
            rows = db.scalars(query).all()
        with trace.phase("attribution_loading"):
            attribution_count = 0
        with trace.phase("evidence_loading"):
            evidence_count = 0
        with trace.phase("benchmark_loading"):
            benchmark_count = sum(1 for row in rows if row.benchmark_return_same_period is not None or row.benchmark_return is not None)
        with trace.phase("quality_loading"):
            quality_count = sum(1 for row in rows if row.trade_quality_score is not None)
        with trace.phase("prediction_loading"):
            prediction_count = sum(1 for row in rows if row.thesis_id)
        with trace.phase("serialization"):
            serialized_rows = [self.serialize_trade(db, row) for row in rows]
            summary = self.summary_for_game(db, game)
        payload = {
            "status": "ok",
            "snapshot_status": "miss",
            "game": serialize_game_header(game),
            "summary": summary,
            "rows": serialized_rows,
            "total": total,
            "limit": limit,
            "offset": offset,
            "filters": {
                "game_id": game_id,
                "ticker": ticker,
                "setup_type": setup_type,
                "outcome_label": outcome_label,
                "start_date": start_date,
                "end_date": end_date,
                "min_r": min_r,
                "max_r": max_r,
                "only_open": only_open,
                "only_closed": only_closed,
                "sort_by": sort_by,
            },
            "policy": TRANSPARENCY_POLICY,
        }
        with trace.phase("json_generation"):
            response_size = payload_size_bytes(payload)
        trace.add(
            snapshot_miss=True,
            base_trade_query_count=2,
            attribution_loading_queries=0,
            evidence_loading_queries=0,
            benchmark_loading_queries=0,
            quality_loading_queries=0,
            prediction_loading_queries=0,
            attribution_rows=attribution_count,
            evidence_rows=evidence_count,
            benchmark_rows=benchmark_count,
            quality_rows=quality_count,
            prediction_links=prediction_count,
            row_count=len(rows),
            total_trades=total,
            response_size_bytes=response_size,
        )
        payload["runtime_trace"] = trace.payload()
        return payload

    def detail(self, db: Session, trade_id: int) -> dict:
        trade = db.get(TradingGameTrade, trade_id)
        if not trade:
            return {"status": "not_found", "trade_id": trade_id, "policy": TRANSPARENCY_POLICY}
        game = db.get(TradingGame, trade.game_id)
        if game:
            self.refresh_trade(db, game, trade)
        attribution = TradeAttributionService().for_trade(db, trade_id)
        quality = TradeQualityEvaluator().for_trade(db, trade_id)
        pnl = PnLBreakdownService().trade_breakdown(db, trade_id)
        learning = TradeLearningEvidenceService().for_trade(db, trade_id)
        replay = TradeReplayService().replay(db, trade_id, self.serialize_trade(db, trade))
        return {
            "status": "ok",
            "trade": self.serialize_trade(db, trade),
            "replay": replay,
            "attribution": attribution,
            "quality": quality,
            "pnl_breakdown": pnl,
            "learning_outcome": learning,
            "policy": TRANSPARENCY_POLICY,
        }

    def refresh_game_transparency(self, db: Session, game: TradingGame, commit: bool = True, persist_reality: bool = True) -> dict:
        trades = db.scalars(select(TradingGameTrade).where(TradingGameTrade.game_id == game.id).order_by(TradingGameTrade.created_at)).all()
        for trade in trades:
            self.refresh_trade(db, game, trade)
        reality = TradingGameRealityCheckService().evaluate(db, game, persist=persist_reality)
        summary = self.summary_for_game(db, game, trades=trades)
        game.ledger_summary = summary
        game.reality_check_summary = reality
        game.transparency_updated_at = datetime.utcnow()
        game.updated_at = datetime.utcnow()
        EquityCurveAnnotationService().refresh(db, game, trades)
        if commit:
            db.commit()
        else:
            db.flush()
        return {"status": "ok", "trades": len(trades), "summary": summary, "reality_check": reality}

    def refresh_trades_incremental(
        self,
        db: Session,
        game: TradingGame,
        trades: list[TradingGameTrade],
        *,
        commit: bool = True,
        persist_reality: bool = True,
    ) -> dict:
        """Enrich new trades without replaying transparency for the full ledger."""

        for trade in trades:
            self.refresh_trade(db, game, trade)
        reality = TradingGameRealityCheckService().evaluate(db, game, persist=persist_reality)
        summary = self.summary_for_game(db, game)
        game.ledger_summary = summary
        game.reality_check_summary = reality
        game.transparency_updated_at = datetime.utcnow()
        game.updated_at = datetime.utcnow()
        EquityCurveAnnotationService().refresh(db, game, trades)
        if commit:
            db.commit()
        else:
            db.flush()
        return {
            "status": "ok",
            "trades_enriched": len(trades),
            "summary": summary,
            "reality_check": reality,
            "mode": "incremental",
        }

    def refresh_trade(self, db: Session, game: TradingGame, trade: TradingGameTrade) -> TradingGameTrade:
        asset = db.scalar(select(Asset).where(Asset.ticker == trade.ticker).limit(1))
        simulation = db.get(ExecutionSimulation, trade.execution_simulation_id) if trade.execution_simulation_id else None
        prediction = db.get(HistoricalPrediction, simulation.prediction_id) if simulation and simulation.prediction_id else None
        payload = dict(trade.payload or {})
        sim_payload = (simulation.simulation_payload if simulation else None) or payload.get("simulation") or {}
        trade.asset_name = trade.asset_name or (asset.name if asset else trade.ticker)
        trade.asset_type = trade.asset_type or (asset.asset_type if asset else None)
        trade.sector = trade.sector or (asset.sector if asset else None)
        trade.industry = trade.industry or (asset.industry if asset else None)
        trade.thesis_id = trade.thesis_id or (prediction.id if prediction else payload.get("prediction_id"))
        trade.confidence_at_entry = coalesce_float(trade.confidence_at_entry, prediction.confidence if prediction else None)
        trade.actionability_state_at_entry = trade.actionability_state_at_entry or trade.decision_state
        trade.market_regime_at_entry = trade.market_regime_at_entry or (prediction.market_regime if prediction else payload.get("market_regime"))
        trade.sector_regime_at_entry = trade.sector_regime_at_entry or trade.sector or "unknown"
        trade.benchmark_ticker = trade.benchmark_ticker or game.benchmark_ticker
        trade.data_quality_score = coalesce_float(trade.data_quality_score, prediction.data_quality_score if prediction else None)
        trade.max_favorable_excursion = coalesce_float(trade.max_favorable_excursion, simulation.max_favorable_excursion if simulation else None)
        trade.max_adverse_excursion = coalesce_float(trade.max_adverse_excursion, simulation.max_adverse_excursion if simulation else None)
        trade.holding_days = trade.holding_days if trade.holding_days is not None else holding_days(trade)
        trade.entry_reason = trade.entry_reason or entry_reason_for(trade, prediction, simulation)
        trade.entry_trigger = trade.entry_trigger or str(sim_payload.get("entry_model") or (simulation.entry_model if simulation else "entry_at_close_or_trigger_proxy"))
        trade.confirmation_condition = trade.confirmation_condition or confirmation_for(trade, simulation)
        risk_per_share = risk_per_share_for(trade)
        trade.notional_value = coalesce_float(trade.notional_value, (trade.entry_price or 0.0) * safe_float(trade.position_size))
        trade.max_expected_loss = coalesce_float(trade.max_expected_loss, trade.risk_amount)
        trade.stop_loss = coalesce_float(trade.stop_loss, stop_level_for(trade, risk_per_share))
        trade.invalidation_level = coalesce_float(trade.invalidation_level, trade.stop_loss)
        trade.initial_target_1 = coalesce_float(trade.initial_target_1, target_level_for(trade, risk_per_share, 1.5))
        trade.initial_target_2 = coalesce_float(trade.initial_target_2, target_level_for(trade, risk_per_share, 2.5))
        trade.trailing_stop = trade.trailing_stop or "ATR/time-stop proxy from historical execution simulation."
        trade.exit_reason = trade.exit_reason or exit_reason_for(trade, simulation)
        trade.exit_trigger = trade.exit_trigger or (simulation.exit_model if simulation else "historical_outcome_proxy")
        gross = safe_float(trade.risk_amount) * safe_float(trade.realized_r_multiple)
        estimated_cost = safe_float(trade.risk_amount) * ((safe_float(trade.slippage_bps) + safe_float(trade.spread_bps)) / 10000)
        trade.gross_pnl_eur = coalesce_float(trade.gross_pnl_eur, gross)
        trade.net_pnl_eur = coalesce_float(trade.net_pnl_eur, trade.realized_pl if trade.realized_pl is not None else gross - estimated_cost)
        trade.pnl_percent = coalesce_float(trade.pnl_percent, pct_return(trade.capital_before, trade.net_pnl_eur))
        trade.pnl_per_share = coalesce_float(trade.pnl_per_share, pnl_per_share_for(trade))
        trade.target_1_hit = trade.target_1_hit if trade.target_1_hit is not None else bool(trade.target_hit)
        trade.target_2_hit = trade.target_2_hit if trade.target_2_hit is not None else bool(trade.target_hit and safe_float(trade.realized_r_multiple) >= 2)
        trade.invalidation_hit = trade.invalidation_hit if trade.invalidation_hit is not None else bool(trade.stop_hit)
        trade.benchmark_return_same_period = coalesce_float(trade.benchmark_return_same_period, trade.benchmark_return)
        asset_return = price_return_pct(trade.entry_price, trade.exit_price)
        if asset_return is None:
            asset_return = trade.pnl_percent
        trade.excess_return_vs_benchmark = coalesce_float(
            trade.excess_return_vs_benchmark,
            asset_return - safe_float(trade.benchmark_return_same_period) if asset_return is not None and trade.benchmark_return_same_period is not None else None,
        )
        trade.outcome_label = trade.outcome_label or outcome_label_for(trade, simulation)
        quality_payload = TradeQualityEvaluator().score_trade(trade)
        trade.trade_quality_score = coalesce_float(trade.trade_quality_score, quality_payload["final_trade_quality_score"])
        trade.lesson_generated = trade.lesson_generated or lesson_for_trade(trade)
        TradeAttributionService().ensure_for_trade(db, trade)
        TradeQualityEvaluator().ensure_for_trade(db, trade, quality_payload)
        TradeLearningEvidenceService().ensure_for_trade(db, trade)
        return trade

    def summary_for_game(self, db: Session, game: TradingGame, trades: list[TradingGameTrade] | None = None) -> dict:
        trades = trades if trades is not None else db.scalars(select(TradingGameTrade).where(TradingGameTrade.game_id == game.id)).all()
        active = [row for row in trades if row.decision_state not in {"avoid", "wait_for_trigger"}]
        winners = [row for row in active if safe_float(row.net_pnl_eur if row.net_pnl_eur is not None else row.realized_pl) > 0]
        losers = [row for row in active if safe_float(row.net_pnl_eur if row.net_pnl_eur is not None else row.realized_pl) < 0]
        by_setup = grouped_pnl(active, lambda row: row.setup_type)
        by_ticker = grouped_pnl(active, lambda row: row.ticker)
        best = max(active, key=lambda row: safe_float(row.net_pnl_eur if row.net_pnl_eur is not None else row.realized_pl), default=None)
        worst = min(active, key=lambda row: safe_float(row.net_pnl_eur if row.net_pnl_eur is not None else row.realized_pl), default=None)
        return {
            "trade_count": len(trades),
            "active_trade_count": len(active),
            "closed_trade_count": sum(1 for row in active if row.exit_date is not None),
            "open_trade_count": sum(1 for row in active if row.exit_date is None),
            "total_realized_pnl": round(sum(safe_float(row.net_pnl_eur if row.net_pnl_eur is not None else row.realized_pl) for row in active), 4),
            "winners": len(winners),
            "losers": len(losers),
            "largest_winner": serialize_trade_link(best) if best else None,
            "largest_loser": serialize_trade_link(worst) if worst else None,
            "pnl_by_setup": by_setup,
            "pnl_by_ticker": dict(list(by_ticker.items())[:12]),
            "policy": "Ledger summary is derived from persisted trade rows; no trade details are fabricated.",
        }

    def game(self, db: Session, game_id: int | None = None) -> TradingGame | None:
        if game_id:
            return db.get(TradingGame, game_id)
        return db.scalar(select(TradingGame).where(TradingGame.status == "active").order_by(desc(TradingGame.started_at)).limit(1)) or db.scalar(select(TradingGame).order_by(desc(TradingGame.started_at)).limit(1))

    def _can_use_ledger_snapshot(
        self,
        *,
        ticker: str | None,
        setup_type: str | None,
        outcome_label: str | None,
        start_date: str | None,
        end_date: str | None,
        min_r: float | None,
        max_r: float | None,
        only_open: bool,
        only_closed: bool,
        sort_by: str,
    ) -> bool:
        return (
            ticker is None
            and setup_type is None
            and outcome_label is None
            and start_date is None
            and end_date is None
            and min_r is None
            and max_r is None
            and not only_open
            and not only_closed
            and sort_by == "created_at_desc"
        )

    def serialize_trade(self, db: Session, trade: TradingGameTrade) -> dict:
        return {
            "trade_id": trade.id,
            "id": trade.id,
            "game_id": trade.game_id,
            "mode": trade.mode,
            "capital_cycle_id": trade.capital_cycle_id,
            "ticker": trade.ticker,
            "asset_name": trade.asset_name,
            "asset_type": trade.asset_type,
            "sector": trade.sector,
            "industry": trade.industry,
            "setup_type": trade.setup_type,
            "thesis_id": trade.thesis_id,
            "sniper_score_at_entry": trade.sniper_score_at_entry,
            "opportunity_score_at_entry": trade.opportunity_score_at_entry,
            "confidence_at_entry": trade.confidence_at_entry,
            "actionability_state_at_entry": trade.actionability_state_at_entry,
            "market_regime_at_entry": trade.market_regime_at_entry,
            "sector_regime_at_entry": trade.sector_regime_at_entry,
            "benchmark_ticker": trade.benchmark_ticker,
            "timeframe": trade.timeframe,
            "decision_state": trade.decision_state,
            "entry_date": iso(trade.entry_date),
            "entry_price": trade.entry_price,
            "entry_reason": trade.entry_reason,
            "entry_trigger": trade.entry_trigger,
            "confirmation_condition": trade.confirmation_condition,
            "position_size": trade.position_size,
            "notional_value": trade.notional_value,
            "capital_before_trade": trade.capital_before,
            "risk_percent": trade.risk_percent,
            "risk_amount_eur": trade.risk_amount,
            "stop_loss": trade.stop_loss,
            "invalidation_level": trade.invalidation_level,
            "initial_target_1": trade.initial_target_1,
            "initial_target_2": trade.initial_target_2,
            "trailing_stop": trade.trailing_stop,
            "max_expected_loss": trade.max_expected_loss,
            "exit_date": iso(trade.exit_date),
            "exit_price": trade.exit_price,
            "exit_reason": trade.exit_reason,
            "exit_trigger": trade.exit_trigger,
            "holding_days": trade.holding_days,
            "gross_pnl_eur": trade.gross_pnl_eur,
            "net_pnl_eur": trade.net_pnl_eur,
            "realized_pl": trade.realized_pl,
            "unrealized_pnl_eur": unrealized_pnl_for_open_trade(trade),
            "pnl_percent": trade.pnl_percent,
            "pnl_per_share": trade.pnl_per_share,
            "r_multiple": trade.realized_r_multiple,
            "max_favorable_excursion": trade.max_favorable_excursion,
            "max_adverse_excursion": trade.max_adverse_excursion,
            "target_1_hit": trade.target_1_hit,
            "target_2_hit": trade.target_2_hit,
            "stop_hit": trade.stop_hit,
            "invalidation_hit": trade.invalidation_hit,
            "missed_entry": trade.missed_entry,
            "false_breakout": trade.false_breakout,
            "benchmark_return_same_period": trade.benchmark_return_same_period,
            "excess_return_vs_benchmark": trade.excess_return_vs_benchmark,
            "trade_quality_score": trade.trade_quality_score,
            "reproducibility_score": trade.reproducibility_score,
            "data_quality_score": trade.data_quality_score,
            "outcome_label": trade.outcome_label,
            "lesson_generated": trade.lesson_generated,
            "created_at": iso(trade.created_at),
            "payload": compact_payload(trade.payload),
        }


class TradeReplayService:
    def replay(self, db: Session, trade_id: int, trade_payload: dict | None = None) -> dict:
        trade = db.get(TradingGameTrade, trade_id)
        if not trade:
            return {"status": "not_found", "trade_id": trade_id}
        payload = trade_payload or TradeLedgerService().serialize_trade(db, trade)
        return {
            "status": "ok",
            "trade_summary": {
                "ticker": trade.ticker,
                "setup_type": trade.setup_type,
                "outcome_label": trade.outcome_label,
                "net_pnl_eur": trade.net_pnl_eur,
                "r_multiple": trade.realized_r_multiple,
            },
            "entry_decision": {
                "why_considered": trade.entry_reason,
                "why_actionable": f"Decision state at entry was {trade.actionability_state_at_entry or trade.decision_state}.",
                "confirmation": trade.confirmation_condition,
                "known_risks": known_risks_for(trade),
                "regime": trade.market_regime_at_entry,
            },
            "exit_decision": {
                "reason": trade.exit_reason,
                "trigger": trade.exit_trigger,
                "target_reached": trade.target_hit,
                "stop_hit": trade.stop_hit,
                "thesis_invalidated": trade.invalidation_hit,
            },
            "thesis_link": {"thesis_id": trade.thesis_id, "note": "Historical prediction id is used when no proprietary thesis id is linked."},
            "engine_votes": TradeAttributionService().for_trade(db, trade_id),
            "signals_at_entry": {
                "setup_type": trade.setup_type,
                "confidence": trade.confidence_at_entry,
                "reproducibility": trade.reproducibility_score,
                "risk_percent": trade.risk_percent,
            },
            "signals_at_exit": {
                "exit_reason": trade.exit_reason,
                "r_multiple": trade.realized_r_multiple,
                "max_favorable_excursion": trade.max_favorable_excursion,
                "max_adverse_excursion": trade.max_adverse_excursion,
            },
            "benchmark_comparison": {
                "benchmark": trade.benchmark_ticker,
                "benchmark_return_same_period": trade.benchmark_return_same_period,
                "excess_return_vs_benchmark": trade.excess_return_vs_benchmark,
            },
            "pnl_breakdown": PnLBreakdownService().trade_breakdown(db, trade_id),
            "risk_management": {
                "capital_before": trade.capital_before,
                "risk_amount_eur": trade.risk_amount,
                "risk_percent": trade.risk_percent,
                "position_size": trade.position_size,
                "invalidation_level": trade.invalidation_level,
                "max_expected_loss": trade.max_expected_loss,
            },
            "learning_outcome": TradeLearningEvidenceService().for_trade(db, trade_id),
            "raw_trade": payload,
            "policy": TRANSPARENCY_POLICY,
        }


class TradeAttributionService:
    def for_trade(self, db: Session, trade_id: int) -> list[dict]:
        trade = db.get(TradingGameTrade, trade_id)
        if not trade:
            return []
        self.ensure_for_trade(db, trade)
        rows = db.scalars(select(TradeEngineAttribution).where(TradeEngineAttribution.trade_id == trade.id).order_by(desc(TradeEngineAttribution.contribution_score))).all()
        return [serialize_attribution(row) for row in rows]

    def ensure_for_trade(self, db: Session, trade: TradingGameTrade) -> None:
        for item in attribution_components(trade):
            row = db.scalar(select(TradeEngineAttribution).where(TradeEngineAttribution.trade_id == trade.id, TradeEngineAttribution.engine_name == item["engine_name"]).limit(1))
            if row is None:
                row = TradeEngineAttribution(trade_id=trade.id, engine_name=item["engine_name"])
                db.add(row)
            row.vote = item["vote"]
            row.confidence = item["confidence"]
            row.contribution_score = item["contribution_score"]
            row.evidence_quality = item["evidence_quality"]
            row.was_correct = item["was_correct"]
            row.reliability_delta = item["reliability_delta"]
            row.explanation = item["explanation"]


class TradeQualityEvaluator:
    def for_trade(self, db: Session, trade_id: int) -> dict:
        trade = db.get(TradingGameTrade, trade_id)
        if not trade:
            return {"status": "not_found", "trade_id": trade_id}
        payload = self.ensure_for_trade(db, trade)
        return payload

    def ensure_for_trade(self, db: Session, trade: TradingGameTrade, payload: dict | None = None) -> dict:
        payload = payload or self.score_trade(trade)
        row = db.scalar(select(TradeQualityScore).where(TradeQualityScore.trade_id == trade.id).limit(1))
        if row is None:
            row = TradeQualityScore(trade_id=trade.id)
            db.add(row)
        for key, value in payload.items():
            if hasattr(row, key):
                setattr(row, key, value)
        return {"status": "ok", **payload}

    def score_trade(self, trade: TradingGameTrade) -> dict:
        components = trade_quality_components(trade)
        component_values = [
            components["entry_quality"],
            components["exit_quality"],
            components["risk_reward_quality"],
            components["sizing_quality"],
            components["regime_alignment"],
            components["reproducibility_quality"],
            components["thesis_consistency"],
            components["benchmark_relative_quality"],
            components["rule_compliance"],
        ]
        raw = mean(component_values)
        final = clamp(raw - components["luck_factor"] * 0.18)
        explanation = explain_quality(trade, components, final)
        return {**components, "final_trade_quality_score": round(final, 2), "explanation": explanation}


class EquityCurveAnnotationService:
    def annotated_equity(
        self,
        db: Session,
        game_id: int | None = None,
        limit: int = 800,
        *,
        refresh: bool = False,
        use_snapshot: bool = True,
        include_trace: bool = False,
    ) -> dict:
        if use_snapshot:
            from app.services.trading_game_runtime import TradingGameRuntimeSnapshotService

            snapshot_payload = TradingGameRuntimeSnapshotService().equity_from_snapshot(db, game_id=game_id, limit=limit)
            if snapshot_payload is not None:
                return snapshot_payload
        game = TradeLedgerService().game(db, game_id)
        if not game:
            return {"status": "no_game", "equity_curve_points": [], "benchmark_curve_points": [], "annotations": []}
        from app.services.trading_game_runtime import RuntimeTrace, payload_size_bytes

        trace = RuntimeTrace("equity_curve_annotated_live_read")
        if refresh:
            with trace.phase("annotation_refresh"):
                trades = db.scalars(select(TradingGameTrade).where(TradingGameTrade.game_id == game.id).order_by(TradingGameTrade.created_at)).all()
                self.refresh(db, game, trades)
        with trace.phase("equity_points_loading"):
            points = db.scalars(select(TradingGameEquityCurve).where(TradingGameEquityCurve.game_id == game.id).order_by(TradingGameEquityCurve.created_at).limit(limit)).all()
        with trace.phase("annotations_loading"):
            annotations = db.scalars(select(EquityCurveAnnotation).where(EquityCurveAnnotation.game_id == game.id).order_by(EquityCurveAnnotation.timestamp).limit(limit)).all()
        with trace.phase("benchmark_loading"):
            benchmark_curve_points = [{"timestamp": iso(row.equity_date or row.created_at), "value": row.benchmark_equity, "return": row.benchmark_return} for row in points]
        with trace.phase("serialization"):
            payload = {
                "status": "ok",
                "snapshot_status": "miss",
                "game": serialize_game_header(game),
                "equity_curve_points": [serialize_equity_point(row) for row in points],
                "benchmark_curve_points": benchmark_curve_points,
                "annotations": [serialize_annotation(row) for row in annotations],
                "policy": "Markers connect equity movement to trade entries, exits, drawdowns, rule events and benchmark divergence when those events exist.",
            }
        with trace.phase("json_generation"):
            size = payload_size_bytes(payload)
        trace.add(
            snapshot_miss=True,
            equity_points_queries=1,
            annotations_queries=1,
            benchmark_loading_queries=0,
            point_count=len(points),
            annotation_count=len(annotations),
            response_size_bytes=size,
        )
        payload["runtime_trace"] = trace.payload()
        return payload

    def refresh(self, db: Session, game: TradingGame, trades: list[TradingGameTrade]) -> None:
        for trade in trades:
            if trade.entry_date:
                self.ensure_annotation(
                    db,
                    game,
                    trade,
                    "trade_entry",
                    as_datetime(trade.entry_date),
                    f"{trade.ticker} entry",
                    trade.entry_reason or f"{trade.setup_type} entry",
                    0.0,
                    trade.capital_before,
                )
            event_type = exit_event_type(trade)
            self.ensure_annotation(
                db,
                game,
                trade,
                event_type,
                as_datetime(trade.exit_date) if trade.exit_date else trade.created_at,
                f"{trade.ticker} {trade.outcome_label or event_type}",
                trade.exit_reason or trade.lesson_generated or "Trade outcome recorded.",
                trade.net_pnl_eur if trade.net_pnl_eur is not None else trade.realized_pl,
                trade.capital_after,
            )
        if game.status == "bankrupt":
            self.ensure_game_annotation(db, game, "bankruptcy_event", game.ended_at or game.updated_at, "Game reached capital ruin", "Paper game stopped and a failure report was persisted.", game.current_capital)

    def ensure_annotation(self, db: Session, game: TradingGame, trade: TradingGameTrade, event_type: str, timestamp: datetime, label: str, description: str, pnl: float | None, capital: float | None) -> None:
        existing = db.scalar(select(EquityCurveAnnotation).where(EquityCurveAnnotation.game_id == game.id, EquityCurveAnnotation.related_trade_id == trade.id, EquityCurveAnnotation.event_type == event_type).limit(1))
        if existing:
            existing.timestamp = timestamp
            existing.label = label
            existing.description = description
            existing.pnl_impact = pnl
            existing.capital_after_event = capital
            return
        db.add(
            EquityCurveAnnotation(
                game_id=game.id,
                timestamp=timestamp,
                event_type=event_type,
                label=label,
                description=description,
                related_trade_id=trade.id,
                related_thesis_id=trade.thesis_id,
                pnl_impact=pnl,
                capital_after_event=capital,
                payload={"ticker": trade.ticker, "setup_type": trade.setup_type, "outcome_label": trade.outcome_label},
            )
        )

    def ensure_game_annotation(self, db: Session, game: TradingGame, event_type: str, timestamp: datetime, label: str, description: str, capital: float | None) -> None:
        existing = db.scalar(select(EquityCurveAnnotation).where(EquityCurveAnnotation.game_id == game.id, EquityCurveAnnotation.event_type == event_type, EquityCurveAnnotation.related_trade_id.is_(None)).limit(1))
        if existing:
            existing.timestamp = timestamp
            existing.label = label
            existing.description = description
            existing.capital_after_event = capital
            return
        db.add(EquityCurveAnnotation(game_id=game.id, timestamp=timestamp, event_type=event_type, label=label, description=description, capital_after_event=capital, payload={}))


class TradeLearningEvidenceService:
    def list(
        self,
        db: Session,
        setup_type: str | None = None,
        ticker: str | None = None,
        regime: str | None = None,
        lesson_type: str | None = None,
        min_sample_size: int | None = None,
        affected_module: str | None = None,
        limit: int = 120,
    ) -> dict:
        query = select(TradeLearningEvidence)
        if setup_type:
            query = query.where(TradeLearningEvidence.setup_type == setup_type)
        if ticker:
            query = query.where(TradeLearningEvidence.ticker == ticker.upper())
        if regime:
            query = query.where(TradeLearningEvidence.regime == regime)
        if lesson_type:
            query = query.where(TradeLearningEvidence.lesson_type == lesson_type)
        if min_sample_size is not None:
            query = query.where(TradeLearningEvidence.sample_size >= min_sample_size)
        if affected_module:
            query = query.where(TradeLearningEvidence.affected_module == affected_module)
        rows = db.scalars(query.order_by(desc(TradeLearningEvidence.created_at)).limit(limit)).all()
        return {"status": "ok", "rows": [serialize_learning_evidence(row) for row in rows], "policy": "Learning evidence links trade outcomes to future rule proposals and module adjustments."}

    def for_trade(self, db: Session, trade_id: int) -> list[dict]:
        rows = db.scalars(select(TradeLearningEvidence).where(TradeLearningEvidence.trade_id == trade_id).order_by(desc(TradeLearningEvidence.created_at))).all()
        return [serialize_learning_evidence(row) for row in rows]

    def ensure_for_trade(self, db: Session, trade: TradingGameTrade) -> None:
        lesson_type = lesson_type_for(trade)
        existing = db.scalar(select(TradeLearningEvidence).where(TradeLearningEvidence.trade_id == trade.id, TradeLearningEvidence.lesson_type == lesson_type).limit(1))
        if existing:
            existing.observation = trade.lesson_generated or existing.observation
            existing.confidence = confidence_for_lesson(trade)
            return
        similar_ids = similar_trade_ids(db, trade)
        db.add(
            TradeLearningEvidence(
                trade_id=trade.id,
                game_id=trade.game_id,
                ticker=trade.ticker,
                setup_type=trade.setup_type,
                regime=trade.market_regime_at_entry or "unknown",
                lesson_type=lesson_type,
                observation=trade.lesson_generated or lesson_for_trade(trade),
                sample_size=len(similar_ids),
                supporting_trades_json={"trade_ids": similar_ids[:20]},
                contradicted_rules_json={},
                affected_module=affected_module_for_lesson(lesson_type),
                action_taken=action_for_lesson(lesson_type),
                confidence=confidence_for_lesson(trade),
            )
        )


class TradingGameRealityCheckService:
    def evaluate(self, db: Session, game_id_or_game: int | TradingGame | None = None, persist: bool = False) -> dict:
        game = game_id_or_game if isinstance(game_id_or_game, TradingGame) else TradeLedgerService().game(db, game_id_or_game)
        if not game:
            return {"status": "no_game", "warnings": ["no_trading_game"]}
        trades = db.scalars(select(TradingGameTrade).where(TradingGameTrade.game_id == game.id).order_by(TradingGameTrade.created_at)).all()
        payload = reality_check_payload(game, trades)
        if persist:
            row = TradingGameRealityCheck(
                game_id=game.id,
                trades_count=payload["trades_count"],
                unique_tickers=payload["unique_tickers"],
                unique_sectors=payload["unique_sectors"],
                unique_regimes=payload["unique_regimes"],
                profit_concentration_top_1=payload["profit_concentration_top_1"],
                profit_concentration_top_3=payload["profit_concentration_top_3"],
                sample_quality_score=payload["sample_quality_score"],
                realism_score=payload["realism_score"],
                statistical_confidence=payload["statistical_confidence"],
                warnings_json={"warnings": payload["warnings"]},
                explanation=payload["explanation"],
            )
            db.add(row)
            game.reality_check_summary = payload
        return payload


class PnLBreakdownService:
    def game_breakdown(self, db: Session, game_id: int | None = None) -> dict:
        game = TradeLedgerService().game(db, game_id)
        if not game:
            return {"status": "no_game"}
        trades = db.scalars(select(TradingGameTrade).where(TradingGameTrade.game_id == game.id).order_by(TradingGameTrade.created_at)).all()
        active = [row for row in trades if row.decision_state not in {"avoid", "wait_for_trigger"}]
        pnl_values = [safe_float(row.net_pnl_eur if row.net_pnl_eur is not None else row.realized_pl) for row in active]
        winners = [value for value in pnl_values if value > 0]
        losers = [value for value in pnl_values if value < 0]
        return {
            "status": "ok",
            "game": serialize_game_header(game),
            "total_realized_pnl": round(sum(pnl_values), 4),
            "total_unrealized_pnl": safe_float(game.unrealized_pl),
            "fees_estimate": round(sum(fees_estimate(row) for row in active), 4),
            "slippage_estimate": round(sum(slippage_estimate(row) for row in active), 4),
            "largest_winner": max(pnl_values) if pnl_values else None,
            "largest_loser": min(pnl_values) if pnl_values else None,
            "average_winner": round(mean(winners), 4) if winners else None,
            "average_loser": round(mean(losers), 4) if losers else None,
            "median_winner": round(median(winners), 4) if winners else None,
            "median_loser": round(median(losers), 4) if losers else None,
            "pnl_by_setup": grouped_pnl(active, lambda row: row.setup_type),
            "pnl_by_ticker": grouped_pnl(active, lambda row: row.ticker),
            "pnl_by_sector": grouped_pnl(active, lambda row: row.sector or "Unknown"),
            "pnl_by_regime": grouped_pnl(active, lambda row: row.market_regime_at_entry or "unknown"),
            "pnl_by_engine": pnl_by_engine(db, active),
            "pnl_by_holding_period_bucket": grouped_pnl(active, lambda row: holding_bucket(row.holding_days)),
            "policy": "P/L breakdown uses stored paper trades and includes cost estimates from slippage/spread settings.",
        }

    def trade_breakdown(self, db: Session, trade_id: int) -> dict:
        trade = db.get(TradingGameTrade, trade_id)
        if not trade:
            return {"status": "not_found", "trade_id": trade_id}
        net = safe_float(trade.net_pnl_eur if trade.net_pnl_eur is not None else trade.realized_pl)
        return {
            "status": "ok",
            "trade_id": trade.id,
            "ticker": trade.ticker,
            "gross_pnl_eur": trade.gross_pnl_eur,
            "net_pnl_eur": net,
            "fees_estimate": fees_estimate(trade),
            "slippage_estimate": slippage_estimate(trade),
            "spread_cost_estimate": spread_cost_estimate(trade),
            "pnl_per_share": trade.pnl_per_share,
            "pnl_percent": trade.pnl_percent,
            "r_multiple": trade.realized_r_multiple,
            "benchmark_relative_pnl": trade.excess_return_vs_benchmark,
            "contribution_to_total_game_pnl": contribution_to_game_pnl(db, trade),
            "policy": "Trade P/L is simulated paper P/L. Costs are explicit estimates, not broker statements.",
        }


def trade_quality_components(trade: TradingGameTrade) -> dict:
    has_entry = trade.entry_price is not None and bool(trade.entry_trigger)
    has_exit = trade.exit_date is not None or trade.decision_state in {"avoid", "wait_for_trigger"}
    has_stop = trade.invalidation_level is not None or trade.stop_loss is not None
    rr = safe_float(trade.realized_r_multiple)
    entry_quality = clamp(35 + (22 if has_entry else -15) + (18 if has_stop else -25) + safe_float(trade.reproducibility_score) * 0.25)
    exit_quality = clamp(45 + (20 if has_exit else -20) + (12 if trade.target_hit or trade.stop_hit or trade.holding_days else 0) + (8 if trade.exit_reason else -8))
    risk_reward_quality = clamp(50 + min(30, max(-30, rr * 14)) + (10 if has_stop else -20))
    sizing_quality = clamp(86 if 0 < safe_float(trade.risk_percent) <= settings.trading_game_max_risk_percent else 72 if trade.decision_state in {"avoid", "wait_for_trigger"} else 35)
    hostile = trade.market_regime_at_entry in {"risk_off", "high_volatility", "trend_down"}
    regime_alignment = clamp(76 if not hostile else 42 if trade.setup_type in {"momentum_breakout", "trend_continuation"} else 58)
    reproducibility_quality = clamp(trade.reproducibility_score)
    thesis_consistency = clamp(50 + (14 if trade.confidence_at_entry else -6) + (12 if trade.thesis_id else -8) + (10 if trade.entry_reason else -5))
    benchmark_relative_quality = clamp(50 + safe_float(trade.excess_return_vs_benchmark) * 1.5)
    rule_compliance = clamp(88 - (0 if has_stop else 25) - (20 if safe_float(trade.risk_percent) > settings.trading_game_max_risk_percent else 0) - (12 if trade.timeframe not in {"daily", "4h"} else 0))
    luck_factor = clamp((22 if safe_float(trade.net_pnl_eur if trade.net_pnl_eur is not None else trade.realized_pl) > 0 and entry_quality < 55 else 0) + (18 if abs(safe_float(trade.max_favorable_excursion)) > 18 and trade.reproducibility_score < 55 else 0))
    return {
        "entry_quality": round(entry_quality, 2),
        "exit_quality": round(exit_quality, 2),
        "risk_reward_quality": round(risk_reward_quality, 2),
        "sizing_quality": round(sizing_quality, 2),
        "regime_alignment": round(regime_alignment, 2),
        "reproducibility_quality": round(reproducibility_quality, 2),
        "thesis_consistency": round(thesis_consistency, 2),
        "benchmark_relative_quality": round(benchmark_relative_quality, 2),
        "rule_compliance": round(rule_compliance, 2),
        "luck_factor": round(luck_factor, 2),
    }


def reality_check_payload(game: TradingGame, trades: list[TradingGameTrade]) -> dict:
    active = [row for row in trades if row.decision_state not in {"avoid", "wait_for_trigger"}]
    pnl_values = sorted([safe_float(row.net_pnl_eur if row.net_pnl_eur is not None else row.realized_pl) for row in active if safe_float(row.net_pnl_eur if row.net_pnl_eur is not None else row.realized_pl) > 0], reverse=True)
    total_positive = sum(pnl_values)
    top_1 = pnl_values[0] / total_positive if total_positive else None
    top_3 = sum(pnl_values[:3]) / total_positive if total_positive else None
    warnings = []
    if len(active) < 30:
        warnings.append("insufficient_sample_size")
    if safe_float(game.profit_factor) >= 3 and len(active) < 100:
        warnings.append("high_profit_factor_low_sample")
    if top_1 and top_1 > 0.4:
        warnings.append("profit_concentrated_in_few_trades")
    if top_3 and top_3 > 0.65:
        warnings.append("profit_concentrated_in_few_trades")
    unique_regimes = len({row.market_regime_at_entry for row in active if row.market_regime_at_entry})
    unique_sectors = len({row.sector for row in active if row.sector})
    unique_tickers = len({row.ticker for row in active})
    if unique_regimes < 3:
        warnings.append("too_few_regimes_tested")
    if unique_sectors < 4:
        warnings.append("too_few_sectors_tested")
    if any(is_fractional(row.position_size) for row in active):
        warnings.append("fractional_share_simplification")
    if safe_float(game.max_drawdown) > -1 and len(active) > 10:
        warnings.append("unrealistically_low_drawdown")
    sample_quality = clamp(len(active) * 1.8 + unique_tickers * 2.4 + unique_sectors * 4 + unique_regimes * 6)
    realism = clamp(82 - len(set(warnings)) * 6 + (8 if active else -18))
    confidence = "low" if len(active) < 30 else "medium" if len(active) < 100 or len(warnings) >= 3 else "higher"
    explanation = reality_explanation(warnings, len(active))
    return {
        "status": "ok",
        "game_id": game.id,
        "trades_count": len(active),
        "unique_tickers": unique_tickers,
        "unique_sectors": unique_sectors,
        "unique_regimes": unique_regimes,
        "profit_concentration_top_1": round(top_1, 4) if top_1 is not None else None,
        "profit_concentration_top_3": round(top_3, 4) if top_3 is not None else None,
        "sample_quality_score": round(sample_quality, 2),
        "realism_score": round(realism, 2),
        "statistical_confidence": confidence,
        "warnings": sorted(set(warnings)),
        "explanation": explanation,
        "evaluated_at": datetime.utcnow().isoformat(),
    }


def attribution_components(trade: TradingGameTrade) -> list[dict]:
    r = safe_float(trade.realized_r_multiple)
    direction_correct = None if trade.decision_state in {"avoid", "wait_for_trigger"} else r > 0
    benchmark_good = trade.excess_return_vs_benchmark is not None and safe_float(trade.excess_return_vs_benchmark) > 0
    engines = [
        ("Technical Engine", "bullish" if trade.setup_type in {"momentum_breakout", "trend_continuation", "pullback_to_trend"} else "neutral", trade.confidence_at_entry or 50, 20, trade.reproducibility_score, direction_correct, "Setup structure and technical trigger created the initial trade hypothesis."),
        ("Sniper Engine", trade.decision_state or "watch", trade.sniper_score_at_entry or trade.reproducibility_score, 24, trade.trade_quality_score or trade.reproducibility_score, direction_correct, "Actionability, invalidation and R-multiple feasibility controlled whether the setup was tradable."),
        ("Regime Engine", trade.market_regime_at_entry or "unknown", 62 if trade.market_regime_at_entry else 35, 14, 55, None if trade.market_regime_at_entry is None else not (trade.market_regime_at_entry in {"risk_off", "high_volatility"} and r < 0), "Market regime adjusted confidence and position risk."),
        ("Learning Loop", "evidence_weighted", trade.reproducibility_score, 15, trade.reproducibility_score, direction_correct, "Historical execution simulation and reproducibility score supplied learning evidence."),
        ("Trading Game Capital Manager", "risk_managed", 90 if safe_float(trade.risk_percent) <= settings.trading_game_max_risk_percent else 30, 16, 80, safe_float(trade.risk_percent) <= settings.trading_game_max_risk_percent, "Position size was capped by paper risk budget and current capital."),
        ("Benchmark Evaluator", "outperform" if benchmark_good else "underperform_or_unknown", 60 if trade.excess_return_vs_benchmark is not None else 25, 11, 60, benchmark_good if trade.excess_return_vs_benchmark is not None else None, "Same-period benchmark comparison prevents mistaking beta for edge."),
    ]
    return [
        {
            "engine_name": name,
            "vote": vote,
            "confidence": round(clamp(confidence), 2),
            "contribution_score": round(clamp(contribution), 2),
            "evidence_quality": round(clamp(evidence_quality), 2),
            "was_correct": was_correct,
            "reliability_delta": round((6 if was_correct else -6) if was_correct is not None else 0, 2),
            "explanation": explanation,
        }
        for name, vote, confidence, contribution, evidence_quality, was_correct, explanation in engines
    ]


def grouped_pnl(rows: list[TradingGameTrade], key_fn) -> dict:
    grouped: dict[str, dict] = defaultdict(lambda: {"count": 0, "pnl": 0.0, "average_r": []})
    for row in rows:
        key = key_fn(row) or "unknown"
        grouped[key]["count"] += 1
        grouped[key]["pnl"] += safe_float(row.net_pnl_eur if row.net_pnl_eur is not None else row.realized_pl)
        if row.realized_r_multiple is not None:
            grouped[key]["average_r"].append(safe_float(row.realized_r_multiple))
    output = {}
    for key, value in sorted(grouped.items(), key=lambda kv: kv[1]["pnl"], reverse=True):
        output[key] = {"count": value["count"], "pnl": round(value["pnl"], 4), "average_r": round(mean(value["average_r"]), 4) if value["average_r"] else None}
    return output


def pnl_by_engine(db: Session, trades: list[TradingGameTrade]) -> dict:
    output: dict[str, dict] = defaultdict(lambda: {"count": 0, "pnl": 0.0})
    for trade in trades:
        rows = db.scalars(select(TradeEngineAttribution).where(TradeEngineAttribution.trade_id == trade.id)).all()
        for row in rows:
            output[row.engine_name]["count"] += 1
            output[row.engine_name]["pnl"] += safe_float(trade.net_pnl_eur if trade.net_pnl_eur is not None else trade.realized_pl) * safe_float(row.contribution_score) / 100
    return {key: {"count": value["count"], "attributed_pnl": round(value["pnl"], 4)} for key, value in sorted(output.items(), key=lambda kv: kv[1]["pnl"], reverse=True)}


def similar_trade_ids(db: Session, trade: TradingGameTrade) -> list[int]:
    rows = db.scalars(
        select(TradingGameTrade.id)
        .where(
            TradingGameTrade.setup_type == trade.setup_type,
            TradingGameTrade.market_regime_at_entry == trade.market_regime_at_entry,
        )
        .order_by(desc(TradingGameTrade.created_at))
        .limit(80)
    ).all()
    return list(rows)


def serialize_game_header(game: TradingGame) -> dict:
    return {
        "id": game.id,
        "game_id": game.game_id,
        "status": game.status,
        "starting_capital": game.starting_capital,
        "current_capital": game.current_capital,
        "target_capital": game.target_capital,
        "active_cycle_id": game.active_cycle_id,
        "target_cycles_completed": game.target_cycles_completed,
        "bankrupt_cycles": game.bankrupt_cycles,
        "realized_pl": game.realized_pl,
        "benchmark_ticker": game.benchmark_ticker,
        "trade_count": game.trade_count,
        "profit_factor": game.profit_factor,
        "expectancy_r": game.expectancy_r,
        "max_drawdown": game.max_drawdown,
        "updated_at": iso(game.updated_at),
        "transparency_updated_at": iso(game.transparency_updated_at),
    }


def serialize_attribution(row: TradeEngineAttribution) -> dict:
    return {
        "id": row.id,
        "trade_id": row.trade_id,
        "engine_name": row.engine_name,
        "vote": row.vote,
        "confidence": row.confidence,
        "contribution_score": row.contribution_score,
        "evidence_quality": row.evidence_quality,
        "was_directionally_correct": row.was_correct,
        "was_correct": row.was_correct,
        "post_trade_reliability_delta": row.reliability_delta,
        "reliability_delta": row.reliability_delta,
        "explanation": row.explanation,
        "created_at": iso(row.created_at),
    }


def serialize_learning_evidence(row: TradeLearningEvidence) -> dict:
    return {
        "id": row.id,
        "trade_id": row.trade_id,
        "game_id": row.game_id,
        "ticker": row.ticker,
        "setup_type": row.setup_type,
        "regime": row.regime,
        "lesson_type": row.lesson_type,
        "observation": row.observation,
        "sample_size": row.sample_size,
        "supporting_trades_json": row.supporting_trades_json,
        "contradicted_rules_json": row.contradicted_rules_json,
        "proposed_rule_id": row.proposed_rule_id,
        "affected_module": row.affected_module,
        "action_taken": row.action_taken,
        "confidence": row.confidence,
        "created_at": iso(row.created_at),
    }


def serialize_annotation(row: EquityCurveAnnotation) -> dict:
    return {
        "id": row.id,
        "timestamp": iso(row.timestamp),
        "event_type": row.event_type,
        "label": row.label,
        "description": row.description,
        "related_trade_id": row.related_trade_id,
        "related_thesis_id": row.related_thesis_id,
        "pnl_impact": row.pnl_impact,
        "capital_after_event": row.capital_after_event,
        "payload": row.payload,
    }


def serialize_equity_point(row: TradingGameEquityCurve) -> dict:
    return {
        "id": row.id,
        "timestamp": iso(row.equity_date or row.created_at),
        "equity_date": iso(row.equity_date),
        "equity": row.equity,
        "cash": row.cash,
        "exposure": row.exposure,
        "drawdown": row.drawdown,
        "benchmark_equity": row.benchmark_equity,
        "benchmark_return": row.benchmark_return,
        "event_type": row.event_type,
        "related_trade_id": row.related_trade_id,
        "annotation_payload": row.annotation_payload,
        "created_at": iso(row.created_at),
    }


def serialize_trade_link(row: TradingGameTrade) -> dict:
    return {"trade_id": row.id, "ticker": row.ticker, "setup_type": row.setup_type, "net_pnl_eur": row.net_pnl_eur if row.net_pnl_eur is not None else row.realized_pl, "r_multiple": row.realized_r_multiple}


def order_trade_query(query, sort_by: str):
    mapping = {
        "pnl_desc": desc(TradingGameTrade.net_pnl_eur),
        "pnl_asc": TradingGameTrade.net_pnl_eur,
        "r_desc": desc(TradingGameTrade.realized_r_multiple),
        "r_asc": TradingGameTrade.realized_r_multiple,
        "quality_desc": desc(TradingGameTrade.trade_quality_score),
        "entry_date_desc": desc(TradingGameTrade.entry_date),
        "entry_date_asc": TradingGameTrade.entry_date,
    }
    return query.order_by(mapping.get(sort_by, desc(TradingGameTrade.created_at)))


def outcome_label_for(trade: TradingGameTrade, simulation: ExecutionSimulation | None = None) -> str:
    if trade.missed_entry:
        return "missed_entry"
    if trade.decision_state == "avoid":
        if simulation and safe_float(simulation.opportunity_cost) > 0:
            return "no_trade_missed_opportunity"
        return "no_trade_correct"
    if trade.decision_state == "wait_for_trigger":
        return "missed_entry" if safe_float(trade.realized_r_multiple) > 0 else "no_trade_correct"
    if trade.stop_hit:
        return "stopped_out"
    if trade.target_hit and safe_float(trade.realized_r_multiple) > 0:
        return "target_hit"
    if safe_float(trade.realized_r_multiple) >= 0.15:
        return "win"
    if safe_float(trade.realized_r_multiple) <= -0.15:
        return "loss"
    return "breakeven"


def lesson_type_for(trade: TradingGameTrade) -> str:
    if trade.outcome_label in {"target_hit", "win"}:
        return "setup_confirmed"
    if trade.outcome_label in {"stopped_out", "loss"}:
        if trade.false_breakout:
            return "setup_failed"
        return "exit_logic_confirmed" if trade.stop_hit else "setup_failed"
    if trade.outcome_label == "missed_entry":
        return "entry_timing_bad"
    if trade.outcome_label == "no_trade_missed_opportunity":
        return "no_trade_filter_missed_opportunity"
    if trade.outcome_label == "no_trade_correct":
        return "no_trade_filter_confirmed"
    if trade.excess_return_vs_benchmark is not None and safe_float(trade.excess_return_vs_benchmark) < 0:
        return "benchmark_underperformance"
    return "setup_confirmed"


def lesson_for_trade(trade: TradingGameTrade) -> str:
    label = trade.outcome_label or outcome_label_for(trade)
    setup = trade.setup_type.replace("_", " ")
    regime = trade.market_regime_at_entry or "unknown regime"
    if label in {"target_hit", "win"}:
        return f"{setup} worked in {regime}; keep checking whether benchmark excess and sample size confirm real edge."
    if label in {"stopped_out", "loss"}:
        return f"{setup} failed or stopped out in {regime}; review confirmation quality, invalidation distance and regime filter before increasing confidence."
    if label == "missed_entry":
        return f"{setup} produced a missed-entry outcome; study whether the trigger is too strict or the entry zone too narrow."
    if label == "no_trade_missed_opportunity":
        return f"No-trade filter may have been too conservative for {setup}; replay similar cases before changing rules."
    if label == "no_trade_correct":
        return f"No-trade decision protected capital for {setup}; keep this filter unless larger samples contradict it."
    return f"{setup} outcome is mixed; keep the case in memory but avoid strong conclusions."


def entry_reason_for(trade: TradingGameTrade, prediction: HistoricalPrediction | None, simulation: ExecutionSimulation | None) -> str:
    source = f"historical prediction {prediction.id}" if prediction else "historical execution simulation"
    r_text = f"{trade.realized_r_multiple:.2f}R" if trade.realized_r_multiple is not None else "unresolved R"
    return f"BLUM opened a reproducible paper setup from {source}: {trade.setup_type} on {trade.timeframe}, decision {trade.decision_state}, modeled outcome {r_text}."


def confirmation_for(trade: TradingGameTrade, simulation: ExecutionSimulation | None) -> str:
    if simulation:
        return f"{simulation.entry_model} with exit model {simulation.exit_model}; generated from point-in-time prediction/outcome rows."
    return "Historical paper trade confirmation was stored without a linked execution simulation."


def exit_reason_for(trade: TradingGameTrade, simulation: ExecutionSimulation | None) -> str:
    if trade.missed_entry:
        return "No executed position: trigger was missed or confirmation failed."
    if trade.decision_state in {"avoid", "wait_for_trigger"}:
        return "No executed position: BLUM kept the setup in avoid/wait state."
    if trade.stop_hit:
        return "Technical invalidation or stop proxy was hit in the historical simulation."
    if trade.target_hit:
        return "Target proxy was reached in the historical simulation."
    if simulation and simulation.trailing_exit_hit:
        return "Trailing exit proxy was hit after favorable excursion."
    return "Time-stop or final horizon exit from historical simulation."


def known_risks_for(trade: TradingGameTrade) -> list[str]:
    risks = []
    if trade.market_regime_at_entry in {"risk_off", "high_volatility", "trend_down"}:
        risks.append(f"Hostile market regime: {trade.market_regime_at_entry}.")
    if trade.invalidation_level is None:
        risks.append("No stored invalidation level; process quality is penalized.")
    if safe_float(trade.risk_percent) > settings.trading_game_max_risk_percent:
        risks.append("Risk percent exceeded the configured cap.")
    if trade.reproducibility_score < 55:
        risks.append("Low reproducibility score.")
    if trade.false_breakout:
        risks.append("False-breakout flag from execution simulation.")
    return risks or ["Risk was bounded by paper capital policy and invalidation logic where available."]


def affected_module_for_lesson(lesson_type: str) -> str:
    if lesson_type in {"setup_failed", "setup_confirmed"}:
        return "sniper_score"
    if "entry" in lesson_type:
        return "entry_exit_engine"
    if "exit" in lesson_type:
        return "exit_engine"
    if "benchmark" in lesson_type:
        return "benchmark_relative_evaluator"
    if "no_trade" in lesson_type:
        return "no_trade_filter"
    return "trading_game"


def action_for_lesson(lesson_type: str) -> str:
    return {
        "setup_failed": "increase_sampling_and_lower_confidence_until_retested",
        "setup_confirmed": "add_to_positive_memory_with_sample_warning",
        "entry_timing_bad": "review_trigger_width_and_confirmation_delay",
        "no_trade_filter_confirmed": "keep_filter_active_with_reality_check",
        "no_trade_filter_missed_opportunity": "create_replay_priority_before_filter_change",
        "benchmark_underperformance": "penalize_beta_without_excess_return",
    }.get(lesson_type, "logged_for_learning")


def confidence_for_lesson(trade: TradingGameTrade) -> float:
    sample_component = 8 if trade.setup_type and trade.market_regime_at_entry else 3
    return round(clamp(35 + safe_float(trade.reproducibility_score) * 0.35 + safe_float(trade.trade_quality_score) * 0.25 + sample_component), 2)


def exit_event_type(trade: TradingGameTrade) -> str:
    label = trade.outcome_label or outcome_label_for(trade)
    if label in {"target_hit", "win"}:
        return "large_win" if safe_float(trade.realized_r_multiple) >= 2 else "trade_exit"
    if label in {"stopped_out", "loss"}:
        return "large_loss" if safe_float(trade.realized_r_multiple) <= -1.5 else "stop_hit"
    if label == "missed_entry":
        return "missed_entry"
    return "trade_exit"


def reality_explanation(warnings: list[str], trades_count: int) -> str:
    if not trades_count:
        return "No executed paper trades are available; game-level metrics cannot be audited yet."
    if "high_profit_factor_low_sample" in warnings:
        return f"Profit factor is strong, but only {trades_count} executed paper trades were evaluated. Treat this as early evidence, not proof of robust edge."
    if "profit_concentrated_in_few_trades" in warnings:
        return "A large share of profit comes from a small number of trades, so repeatability must be tested before increasing confidence."
    if warnings:
        return "The Trading Game has useful evidence, but sample size, regime coverage or realism checks still limit statistical confidence."
    return "Current paper-trade sample has passed the basic transparency reality checks, but it remains research evidence, not a performance claim."


def explain_quality(trade: TradingGameTrade, components: dict, final_score: float) -> str:
    if safe_float(trade.net_pnl_eur if trade.net_pnl_eur is not None else trade.realized_pl) > 0 and final_score < 60:
        return "Profitable paper trade, but process quality is not high enough to treat it as robust evidence."
    if safe_float(trade.net_pnl_eur if trade.net_pnl_eur is not None else trade.realized_pl) < 0 and final_score >= 60:
        return "Losing paper trade with acceptable process quality: controlled-risk losses are valid learning evidence."
    return f"Trade quality {final_score:.2f}/100 based on entry, exit, risk, reproducibility, regime, benchmark and rule compliance."


def risk_per_share_for(trade: TradingGameTrade) -> float | None:
    if safe_float(trade.position_size) > 0 and safe_float(trade.risk_amount) > 0:
        return abs(safe_float(trade.risk_amount) / safe_float(trade.position_size))
    if trade.entry_price:
        return abs(safe_float(trade.entry_price) * 0.02)
    return None


def stop_level_for(trade: TradingGameTrade, risk_per_share: float | None) -> float | None:
    if trade.entry_price is None or risk_per_share is None:
        return None
    return round(max(0.01, safe_float(trade.entry_price) - risk_per_share), 4)


def target_level_for(trade: TradingGameTrade, risk_per_share: float | None, multiple: float) -> float | None:
    if trade.entry_price is None or risk_per_share is None:
        return None
    return round(safe_float(trade.entry_price) + risk_per_share * multiple, 4)


def pnl_per_share_for(trade: TradingGameTrade) -> float | None:
    if trade.entry_price is not None and trade.exit_price is not None:
        return round(safe_float(trade.exit_price) - safe_float(trade.entry_price), 4)
    if safe_float(trade.position_size) > 0:
        return round(safe_float(trade.net_pnl_eur if trade.net_pnl_eur is not None else trade.realized_pl) / safe_float(trade.position_size), 4)
    return None


def holding_days(trade: TradingGameTrade) -> int | None:
    if trade.entry_date and trade.exit_date:
        return max(0, (trade.exit_date - trade.entry_date).days)
    return None


def price_return_pct(entry: float | None, exit: float | None) -> float | None:
    if not entry or not exit:
        return None
    return round((exit / entry - 1) * 100, 4)


def pct_return(base: float | None, value: float | None) -> float | None:
    if not base or value is None:
        return None
    return round(safe_float(value) / max(0.01, safe_float(base)) * 100, 4)


def unrealized_pnl_for_open_trade(trade: TradingGameTrade) -> float | None:
    if trade.exit_date is not None:
        return None
    return trade.net_pnl_eur if trade.net_pnl_eur is not None else trade.realized_pl


def fees_estimate(trade: TradingGameTrade) -> float:
    return round(safe_float(trade.notional_value) * 0.0002, 4)


def slippage_estimate(trade: TradingGameTrade) -> float:
    return round(safe_float(trade.notional_value) * safe_float(trade.slippage_bps) / 10000, 4)


def spread_cost_estimate(trade: TradingGameTrade) -> float:
    return round(safe_float(trade.notional_value) * safe_float(trade.spread_bps) / 10000, 4)


def contribution_to_game_pnl(db: Session, trade: TradingGameTrade) -> float | None:
    total = db.scalar(select(func.sum(TradingGameTrade.net_pnl_eur)).where(TradingGameTrade.game_id == trade.game_id))
    if total is None:
        total = db.scalar(select(func.sum(TradingGameTrade.realized_pl)).where(TradingGameTrade.game_id == trade.game_id))
    if not total:
        return None
    return round(safe_float(trade.net_pnl_eur if trade.net_pnl_eur is not None else trade.realized_pl) / safe_float(total), 4)


def holding_bucket(days: int | None) -> str:
    if days is None:
        return "open_or_unknown"
    if days <= 7:
        return "0-7d"
    if days <= 30:
        return "8-30d"
    if days <= 90:
        return "31-90d"
    return "90d+"


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def as_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    return datetime.utcnow()


def is_fractional(value: float | None) -> bool:
    if value is None:
        return False
    return abs(value - round(value)) > 0.0001


def coalesce_float(current: float | None, fallback: float | None) -> float | None:
    if current is not None:
        return current
    return safe_float(fallback) if fallback is not None else None


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, safe_float(value)))


def compact_payload(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        return {}
    return {key: payload.get(key) for key in ["prediction_id", "market_regime", "capital_policy", "guardrails"] if key in payload}


def iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
