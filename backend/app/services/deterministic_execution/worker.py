from __future__ import annotations

from datetime import datetime, time as datetime_time
import time

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Asset,
    BackgroundJobState,
    ExecutionParityComparison,
    LiveForwardPaperTrade,
    PriceHistory,
    ReplayMarketBar,
)
from app.services.central_brain_runtime import BackgroundJobStateService
from app.services.deterministic_execution.catalog import NautilusMarketDataProjector
from app.services.deterministic_execution.contracts import (
    ExecutionIntent,
    KernelRunRequest,
    MarketEvent,
)
from app.services.deterministic_execution.instruments import BlumInstrumentMapper
from app.services.deterministic_execution.nautilus_kernel import NautilusExecutionKernel
from app.services.deterministic_execution.parity import ExecutionParityEvaluator
from app.services.deterministic_execution.promotion import ExecutionKernelPromotionService
from app.services.deterministic_execution.repository import DeterministicExecutionRepository


class DeterministicExecutionWorker:
    """Bounded shadow worker; never owns BLUM decisions or live execution authority."""

    JOB_NAME = "deterministic_execution_core"

    def __init__(
        self,
        *,
        projector=None,
        kernel=None,
        repository=None,
    ) -> None:
        self.projector = projector or NautilusMarketDataProjector()
        self.kernel = kernel or NautilusExecutionKernel()
        self.repository = repository or DeterministicExecutionRepository()
        self.mapper = BlumInstrumentMapper()

    def run(
        self,
        db: Session,
        *,
        max_items: int | None = None,
        max_seconds: int | None = None,
        now: datetime | None = None,
    ) -> dict:
        settings = get_settings()
        item_budget = max(1, int(max_items or settings.blum_nautilus_max_items_per_job))
        time_budget = max(1, int(max_seconds or settings.blum_nautilus_max_job_seconds))
        runtime_now = now or datetime.utcnow()
        started = time.perf_counter()
        state_service = BackgroundJobStateService()
        existing_state = db.scalar(
            select(BackgroundJobState).where(
                BackgroundJobState.job_name == self.JOB_NAME,
                BackgroundJobState.stage_name == "default",
            )
        )
        cursor = dict(existing_state.cursor_json or {}) if existing_state else {}
        cursor.setdefault("replay_market_bar_id", 0)
        cursor.setdefault("paper_trade_id", 0)
        state_service.start(db, self.JOB_NAME, max_items=item_budget, cursor=cursor)
        try:
            catalog = self.projector.project(
                db,
                cursor={"replay_market_bar_id": cursor["replay_market_bar_id"]},
                limit=item_budget,
                runtime_now=runtime_now,
            )
            cursor["replay_market_bar_id"] = int(catalog.cursor.get("replay_market_bar_id", 0))
            if catalog.status == "UNAVAILABLE":
                duration = (time.perf_counter() - started) * 1000
                state_service.complete(db, self.JOB_NAME, duration_ms=duration, items_processed=0, cursor=cursor)
                return {
                    "status": "degraded",
                    "catalog": _catalog_payload(catalog),
                    "shadow_runs": 0,
                    "budgets": {"max_items": item_budget, "max_seconds": time_budget},
                }

            rows = db.scalars(
                select(LiveForwardPaperTrade)
                .where(
                    LiveForwardPaperTrade.id > int(cursor["paper_trade_id"]),
                    LiveForwardPaperTrade.status.in_(("CANDIDATE", "OPEN", "CLOSED", "EXPIRED", "INVALIDATED")),
                )
                .order_by(LiveForwardPaperTrade.id)
                .limit(item_budget)
            ).all()
            processed = 0
            completed = 0
            skipped: list[dict] = []
            for trade in rows:
                if state_service.should_stop(started, processed, item_budget, time_budget):
                    break
                processed += 1
                cursor["paper_trade_id"] = trade.id
                request = self._request_for_trade(db, trade, runtime_now)
                if request is None:
                    skipped.append({"trade_id": trade.id, "reason": "missing_point_in_time_bars_or_instrument"})
                    continue
                result = self.kernel.run_paper_step(request)
                run = self.repository.persist_result(
                    db,
                    result,
                    environment="paper",
                    source_object_type="live_forward_paper_trade",
                    source_object_id=str(trade.id),
                )
                if result.status == "COMPLETED":
                    completed += 1
                    self._persist_parity(db, trade, run.id, result)
            if len(rows) < item_budget:
                cursor["paper_trade_id"] = 0
            promotion = ExecutionKernelPromotionService().evaluate(db)
            duration = (time.perf_counter() - started) * 1000
            state_service.complete(
                db,
                self.JOB_NAME,
                duration_ms=duration,
                items_processed=processed,
                cursor=cursor,
                payload={"shadow_runs": completed, "promotion_mode": promotion["mode"]},
            )
            return {
                "status": "ok",
                "catalog": _catalog_payload(catalog),
                "shadow_runs": completed,
                "items_processed": processed,
                "skipped": skipped[:20],
                "kernel_state": promotion,
                "duration_ms": round(duration, 3),
                "budgets": {"max_items": item_budget, "max_seconds": time_budget},
            }
        except Exception as exc:
            db.rollback()
            duration = (time.perf_counter() - started) * 1000
            state_service.fail(db, self.JOB_NAME, duration_ms=duration, error_message=f"{type(exc).__name__}: {exc}")
            return {
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "budgets": {"max_items": item_budget, "max_seconds": time_budget},
            }

    def _request_for_trade(self, db: Session, trade: LiveForwardPaperTrade, runtime_now: datetime) -> KernelRunRequest | None:
        asset = db.scalar(select(Asset).where(Asset.ticker == trade.ticker).limit(1))
        if asset is None:
            return None
        try:
            instrument = self.mapper.map_asset(asset)
        except ValueError:
            return None
        replay_rows = db.scalars(
            select(ReplayMarketBar)
            .where(
                ReplayMarketBar.asset_id == asset.id,
                ReplayMarketBar.bar_timestamp <= runtime_now,
                ReplayMarketBar.acquired_at <= runtime_now,
            )
            .order_by(ReplayMarketBar.bar_timestamp.desc())
            .limit(500)
        ).all()
        events = [
            MarketEvent(
                instrument_id=instrument.instrument_id,
                event_type="bar",
                timestamp=row.bar_timestamp,
                open=float(row.open if row.open is not None else row.close),
                high=float(row.high if row.high is not None else row.close),
                low=float(row.low if row.low is not None else row.close),
                close=float(row.close),
                volume=float(row.volume or 0),
                source=row.provider,
                acquired_at=row.acquired_at,
                timeframe=row.timeframe,
            )
            for row in reversed(replay_rows)
        ]
        if not events:
            daily_rows = db.scalars(
                select(PriceHistory)
                .where(PriceHistory.asset_id == asset.id, PriceHistory.date <= runtime_now.date())
                .order_by(PriceHistory.date.desc())
                .limit(240)
            ).all()
            events = [
                MarketEvent(
                    instrument_id=instrument.instrument_id,
                    event_type="bar",
                    timestamp=datetime.combine(row.date, datetime_time.min),
                    open=float(row.open if row.open is not None else row.close),
                    high=float(row.high if row.high is not None else row.close),
                    low=float(row.low if row.low is not None else row.close),
                    close=float(row.close),
                    volume=float(row.volume or 0),
                    source=row.provider,
                    acquired_at=row.created_at,
                    timeframe="1d",
                )
                for row in reversed(daily_rows)
                if row.created_at <= runtime_now
            ]
        if not events or not trade.entry_price or not trade.position_size or not trade.decision_timestamp:
            return None
        payload = trade.frozen_decision_payload or {}
        plan = payload.get("trade_plan") if isinstance(payload.get("trade_plan"), dict) else {}
        raw_order_type = str(plan.get("order_type") or plan.get("entry_type") or "MARKET").upper()
        order_type = next((item for item in ("STOP_LIMIT", "LIMIT", "STOP", "MARKET") if item in raw_order_type), "MARKET")
        intent = ExecutionIntent(
            decision_id=trade.trade_uid,
            instrument_id=instrument.instrument_id,
            side="BUY" if str(trade.side or "LONG").upper() == "LONG" else "SELL",
            order_type=order_type,
            quantity=float(trade.position_size),
            decision_timestamp=trade.decision_timestamp,
            theoretical_price=float(trade.entry_price),
            limit_price=float(trade.entry_price) if order_type in {"LIMIT", "STOP_LIMIT"} else None,
            stop_price=float(trade.stop_loss) if trade.stop_loss else None,
            target_price=float(trade.target_1) if trade.target_1 else None,
            target_2_price=float(trade.target_2) if trade.target_2 else None,
            confirmed=trade.status not in {"SKIPPED", "DATA_BLOCKED", "WAITING_FOR_TRIGGER"},
        )
        balance = float(getattr(trade.game, "current_capital", None) or 10_000)
        return KernelRunRequest(
            run_id=f"shadow-{trade.trade_uid}-{events[-1].timestamp.isoformat()}",
            environment="paper",
            starting_balances={instrument.quote_currency: balance},
            instruments=(instrument,),
            market_events=tuple(events),
            execution_intents=(intent,),
            runtime_now=runtime_now,
        )

    def _persist_parity(self, db: Session, trade, run_id: int, result) -> None:
        if db.scalar(select(ExecutionParityComparison.id).where(ExecutionParityComparison.run_id == run_id).limit(1)):
            return
        authoritative = {
            "state": "FILLED" if trade.status in {"OPEN", "CLOSED", "EXPIRED", "INVALIDATED"} else trade.status,
            "quantity": trade.position_size,
            "fill_price": trade.exit_price if trade.status in {"CLOSED", "EXPIRED", "INVALIDATED"} else trade.entry_price,
            "costs": trade.costs_paid,
            "pnl": trade.net_pnl_eur,
            "exit_reason": trade.close_reason or "",
        }
        comparison = ExecutionParityEvaluator().compare(authoritative, result)
        metrics = dict(comparison.metrics)
        db.add(
            ExecutionParityComparison(
                run_id=run_id,
                source_object_type="live_forward_paper_trade",
                source_object_id=str(trade.id),
                asset_class="forex" if str(trade.asset_type or trade.market or "").lower() in {"forex", "fx"} else str(trade.asset_type or "equity").lower(),
                regime=((trade.frozen_decision_payload or {}).get("market_regime") or "unknown"),
                status=comparison.status,
                state_agreement=metrics.get("state_agreement"),
                quantity_difference=metrics.get("quantity_difference"),
                fill_price_difference=metrics.get("fill_price_difference"),
                cost_difference=metrics.get("cost_difference"),
                pnl_difference=metrics.get("pnl_difference"),
                reasons_json=list(comparison.reasons),
                evidence_json={"authoritative": authoritative, "shadow_fingerprint": result.reproducibility_fingerprint},
            )
        )
        db.commit()


def _catalog_payload(result) -> dict:
    return {
        "status": result.status,
        "rows_read": result.rows_read,
        "rows_written": result.rows_written,
        "rows_rejected": result.rows_rejected,
        "reason": result.reason,
    }
