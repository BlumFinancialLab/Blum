from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.engine.brain.trader_brain import paper_forward_alpha_summary
from app.models import LiveForwardPaperTrade, TradeLearningEvidence
from app.services.intraday_paper_engine import IntradayPaperLearningService
from app.services.live_forward_paper_trading import LiveForwardPaperTradingService
from app.services.paper_forward_direction import (
    ACCOUNTING_RECOMPUTED,
    CASH_BENCHMARK,
    INVALID_PENDING_RECOMPUTATION,
    DirectionalTradePlanError,
    direction_multiplier,
    directional_excursions,
    exit_reason,
    recover_trade_side,
    signed_price_change,
    signed_return,
    trade_metrics,
    validate_trade_plan,
)


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def forex_candidate(
    *,
    side: str = "LONG",
    stop: float | None = 1.095,
    target: float | None = 1.11,
) -> dict:
    plan = {
        "direction": side,
        "entry_type": "MARKET",
        "entry_trigger": "paper-only forward trigger",
        "confirmation_condition": "stored quote confirms setup",
    }
    if stop is not None:
        plan["invalidation_level"] = stop
    if target is not None:
        plan["target_1"] = target
    return {
        "ticker": "EURUSD=X",
        "asset": {
            "name": "EUR/USD",
            "asset_type": "Forex",
            "market": "forex",
        },
        "actionability": "active_setup",
        "confidence": 70.0,
        "sniper_score": 75.0,
        "setup": {"setup_type": "forex_pullback"},
        "trade_plan": plan,
        "price_context": {
            "latest_price": 1.1,
            "data_quality_score": 90.0,
            "rows": 120,
        },
    }


def legacy_forex_trade(
    db: Session,
    *,
    payload: dict,
    accounting_status: str = "PENDING_SIDE_VERIFICATION",
) -> LiveForwardPaperTrade:
    service = LiveForwardPaperTradingService()
    game = service.active_or_create_live_game(db)
    trade = LiveForwardPaperTrade(
        trade_uid=f"legacy-{datetime.utcnow().timestamp()}",
        game_id=game.id,
        ticker="EURUSD=X",
        asset_name="EUR/USD",
        asset_type="Forex",
        setup_type="forex_pullback",
        status="CLOSED",
        side=None,
        accounting_status=accounting_status,
        decision_timestamp=datetime.utcnow(),
        decision_date=date.today(),
        frozen_decision_payload=payload,
        entry_price=1.1,
        entry_date=date.today(),
        opened_at=datetime.utcnow(),
        stop_loss=1.105,
        target_1=1.09,
        position_size=10_000,
        risk_amount=50.0,
        exit_price=1.09,
        exit_date=date.today(),
        closed_at=datetime.utcnow(),
        gross_pnl_eur=-100.0,
        net_pnl_eur=-100.0,
        pnl_percent=-0.909091,
        pnl_per_share=-0.01,
        r_multiple=-2.0,
        max_favorable_excursion=0.2,
        max_adverse_excursion=-1.0,
        benchmark_ticker="SPY",
        duplicate_key=f"legacy-{datetime.utcnow().timestamp()}",
    )
    db.add(trade)
    db.flush()
    return trade


def test_direction_multiplier_is_authoritative():
    assert direction_multiplier("LONG") == 1
    assert direction_multiplier("SHORT") == -1


def test_long_profit_and_loss_are_signed_from_trade_perspective():
    assert signed_price_change("LONG", 100.0, 105.0) == 5.0
    assert signed_price_change("LONG", 100.0, 95.0) == -5.0
    assert signed_return("LONG", 100.0, 105.0) == pytest.approx(0.05)


def test_short_profit_and_loss_are_signed_from_trade_perspective():
    assert signed_price_change("SHORT", 100.0, 95.0) == 5.0
    assert signed_price_change("SHORT", 100.0, 105.0) == -5.0
    assert signed_return("SHORT", 100.0, 95.0) == pytest.approx(0.05)


def test_long_stop_and_targets_are_side_aware():
    assert exit_reason("LONG", 94.0, stop=95.0, target_1=105.0) == "STOP_HIT"
    assert exit_reason("LONG", 106.0, stop=95.0, target_1=105.0) == "TARGET_1_HIT"


def test_short_stop_and_targets_are_side_aware():
    assert exit_reason("SHORT", 106.0, stop=105.0, target_1=95.0) == "STOP_HIT"
    assert exit_reason("SHORT", 94.0, stop=105.0, target_1=95.0) == "TARGET_1_HIT"


def test_second_target_is_side_aware():
    assert exit_reason("LONG", 112.0, target_1=105.0, target_2=110.0) == "TARGET_2_HIT"
    assert exit_reason("SHORT", 88.0, target_1=95.0, target_2=90.0) == "TARGET_2_HIT"


def test_long_and_short_r_multiple_use_positive_risk_distance():
    long_metrics = trade_metrics(
        side="LONG",
        entry_price=100.0,
        exit_price=110.0,
        stop_price=95.0,
        quantity=2.0,
        costs=0.0,
    )
    short_metrics = trade_metrics(
        side="SHORT",
        entry_price=100.0,
        exit_price=90.0,
        stop_price=105.0,
        quantity=2.0,
        costs=0.0,
    )
    assert long_metrics.risk_distance == 5.0
    assert long_metrics.r_multiple == 2.0
    assert short_metrics.risk_distance == 5.0
    assert short_metrics.r_multiple == 2.0


def test_costs_remain_negative_for_short_profit():
    metrics = trade_metrics(
        side="SHORT",
        entry_price=100.0,
        exit_price=95.0,
        stop_price=105.0,
        quantity=2.0,
        costs=1.5,
    )
    assert metrics.gross_pnl == 10.0
    assert metrics.net_pnl == 8.5


def test_short_mae_and_mfe_are_directional():
    mfe, mae = directional_excursions(
        side="SHORT",
        entry_price=100.0,
        high_price=103.0,
        low_price=94.0,
        current_mfe=0.0,
        current_mae=0.0,
        percent=True,
    )
    assert mfe == 6.0
    assert mae == -3.0


def test_invalid_short_trade_plan_is_rejected():
    try:
        validate_trade_plan("SHORT", entry=100.0, stop=95.0, targets=[105.0])
    except DirectionalTradePlanError as exc:
        assert exc.reason == "invalid_trade_plan_geometry"
    else:
        raise AssertionError("Invalid SHORT geometry was accepted")


def test_missing_forex_plan_is_rejected_without_percentage_defaults():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(
            db,
            forex_candidate(side="LONG", stop=None, target=None),
        )
        db.commit()

        assert trade.status == "SKIPPED"
        assert trade.side == "LONG"
        assert trade.stop_loss is None
        assert trade.target_1 is None
        assert trade.accounting_status == INVALID_PENDING_RECOMPUTATION
        assert trade.outcome_label == "missing_valid_forex_trade_plan"


def test_legacy_side_is_recovered_from_frozen_trade_plan():
    recovered = recover_trade_side(
        {
            "trade_plan": {"direction": "sell_short"},
            "asset": {"asset_type": "Forex"},
        }
    )
    assert recovered == "SHORT"


def test_legacy_recompute_dry_run_does_not_mutate_trade():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()
        trade = legacy_forex_trade(
            db,
            payload={"trade_plan": {"direction": "SHORT"}},
        )
        db.commit()

        result = service.recompute_legacy_forex_accounting(db, dry_run=True)
        db.refresh(trade)

        assert result["recoverable"] == 1
        assert result["recomputed"] == 0
        assert trade.side is None
        assert trade.net_pnl_eur == -100.0
        assert trade.accounting_status == "PENDING_SIDE_VERIFICATION"


def test_recomputation_corrects_recoverable_short_and_is_idempotent():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()
        trade = legacy_forex_trade(
            db,
            payload={"trade_plan": {"direction": "SHORT"}},
        )
        db.commit()

        first = service.recompute_legacy_forex_accounting(db, dry_run=False)
        db.commit()
        second = service.recompute_legacy_forex_accounting(db, dry_run=False)
        db.commit()
        stored = db.get(LiveForwardPaperTrade, trade.id)

        assert first["recoverable"] == 1
        assert first["unrecoverable"] == 0
        assert stored.side == "SHORT"
        assert stored.accounting_status == ACCOUNTING_RECOMPUTED
        assert stored.net_pnl_eur == 100.0
        assert stored.r_multiple == 2.0
        assert stored.pnl_percent > 0
        assert stored.benchmark_ticker == CASH_BENCHMARK
        assert stored.benchmark_return_same_period == 0.0
        assert second["recomputed"] == 0
        assert second["already_current"] == 1


def test_unrecoverable_legacy_forex_is_quarantined_and_excluded():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()
        trade = legacy_forex_trade(db, payload={"trade_plan": {}})
        db.commit()

        result = service.recompute_legacy_forex_accounting(db, dry_run=False)
        db.commit()
        stored = db.get(LiveForwardPaperTrade, trade.id)
        game = service.active_or_create_live_game(db)

        assert result["unrecoverable"] == 1
        assert stored.accounting_status == INVALID_PENDING_RECOMPUTATION
        assert stored.outcome_label == "EVIDENCE_QUARANTINED"
        assert service.create_lesson_from_trade(db, stored) is None
        assert db.scalar(select(func.count(TradeLearningEvidence.id))) == 0
        assert paper_forward_alpha_summary([stored], game)["closed_count"] == 0


def test_intraday_learning_rejects_quarantined_forex_trade():
    with setup_db() as db:
        trade = legacy_forex_trade(db, payload={"trade_plan": {}})
        trade.accounting_status = INVALID_PENDING_RECOMPUTATION
        db.commit()

        result = IntradayPaperLearningService().apply_closed_trade(db, trade)

        assert result["status"] == "quarantined"
        assert db.scalar(select(func.count(TradeLearningEvidence.id))) == 0


def test_forex_candidate_does_not_default_to_spy():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(
            db,
            forex_candidate(side="SHORT", stop=1.105, target=1.09),
        )
        db.commit()

        assert trade.benchmark_ticker == CASH_BENCHMARK
        assert trade.side == "SHORT"


def test_long_forex_candidate_is_explicit_and_uses_cash_benchmark():
    with setup_db() as db:
        service = LiveForwardPaperTradingService()
        trade = service.create_candidate(
            db,
            forex_candidate(side="LONG", stop=1.095, target=1.11),
        )
        db.commit()

        assert trade.side == "LONG"
        assert trade.benchmark_ticker == CASH_BENCHMARK
        assert trade.accounting_status == "VALID"
