from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import EquityCurveAnnotation, TradingGame, TradingGameEquityCurve, TradingGameLedgerSnapshot, TradingGameTrade
from app.services.dashboard import dashboard_overview
from app.services.dashboard_snapshots import DashboardSnapshotService
from app.services.trade_transparency import EquityCurveAnnotationService, TradeLedgerService
from app.services.trading_game_runtime import TradingGameRuntimeSnapshotService


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def seed_game(db: Session) -> TradingGame:
    game = TradingGame(
        game_id="runtime-test",
        status="active",
        starting_capital=100.0,
        current_capital=112.0,
        target_capital=10000.0,
        benchmark_ticker="SPY",
        trade_count=2,
        expectancy_r=0.5,
        profit_factor=1.8,
    )
    db.add(game)
    db.flush()
    db.add_all(
        [
            TradingGameTrade(
                game_id=game.id,
                ticker="NVDA",
                setup_type="momentum_breakout",
                decision_state="active_setup",
                entry_date=date(2025, 1, 2),
                exit_date=date(2025, 1, 10),
                entry_price=100.0,
                exit_price=112.0,
                position_size=0.5,
                risk_amount=1.0,
                risk_percent=1.0,
                realized_r_multiple=2.0,
                realized_pl=2.0,
                net_pnl_eur=2.0,
                capital_before=100.0,
                capital_after=102.0,
                benchmark_return_same_period=3.0,
                excess_return_vs_benchmark=9.0,
                trade_quality_score=74.0,
                reproducibility_score=82.0,
                outcome_label="target_hit",
                created_at=datetime(2025, 1, 2, 16, 0),
            ),
            TradingGameTrade(
                game_id=game.id,
                ticker="AAPL",
                setup_type="pullback_to_trend",
                decision_state="active_setup",
                entry_date=date(2025, 1, 11),
                exit_date=date(2025, 1, 16),
                entry_price=50.0,
                exit_price=49.0,
                position_size=1.0,
                risk_amount=1.0,
                risk_percent=1.0,
                realized_r_multiple=-1.0,
                realized_pl=-1.0,
                net_pnl_eur=-1.0,
                capital_before=102.0,
                capital_after=101.0,
                benchmark_return_same_period=1.0,
                excess_return_vs_benchmark=-3.0,
                trade_quality_score=62.0,
                reproducibility_score=70.0,
                outcome_label="stopped_out",
                created_at=datetime(2025, 1, 11, 16, 0),
            ),
        ]
    )
    db.add_all(
        [
            TradingGameEquityCurve(game_id=game.id, equity_date=date(2025, 1, 2), equity=100.0, benchmark_equity=100.0),
            TradingGameEquityCurve(game_id=game.id, equity_date=date(2025, 1, 10), equity=102.0, benchmark_equity=103.0),
            TradingGameEquityCurve(game_id=game.id, equity_date=date(2025, 1, 16), equity=101.0, benchmark_equity=104.0),
            EquityCurveAnnotation(
                game_id=game.id,
                timestamp=datetime(2025, 1, 10, 16, 0),
                event_type="trade_exit",
                label="NVDA target",
                description="Target proxy reached.",
                pnl_impact=2.0,
                capital_after_event=102.0,
            ),
        ]
    )
    db.commit()
    return game


def test_ledger_reads_snapshot_without_refresh(monkeypatch):
    with make_session() as db:
        game = seed_game(db)
        produced = TradingGameRuntimeSnapshotService().produce_ledger_snapshot(db, game_id=game.id, limit=25)
        assert produced["status"] == "ready"

        def fail_refresh(*args, **kwargs):
            raise AssertionError("GET ledger must not refresh transparency when snapshot exists")

        monkeypatch.setattr(TradeLedgerService, "refresh_game_transparency", fail_refresh)
        payload = TradeLedgerService().ledger(db, game_id=game.id, limit=25, refresh=False, use_snapshot=True)

    assert payload["snapshot_status"] == "ready"
    assert payload["rows"][0]["ticker"] == "AAPL"
    assert payload["runtime_trace"]["phases_ms"]["snapshot_lookup"] >= 0
    assert payload["runtime_trace"]["metadata"]["query_count"] == 1


def test_annotated_equity_reads_snapshot_without_refresh(monkeypatch):
    with make_session() as db:
        game = seed_game(db)
        TradingGameRuntimeSnapshotService().produce_equity_snapshot(db, game_id=game.id, limit=20)

        def fail_refresh(*args, **kwargs):
            raise AssertionError("GET annotated equity must not rebuild annotations when snapshot exists")

        monkeypatch.setattr(EquityCurveAnnotationService, "refresh", fail_refresh)
        payload = EquityCurveAnnotationService().annotated_equity(db, game_id=game.id, limit=20, refresh=False, use_snapshot=True)

    assert payload["snapshot_status"] == "ready"
    assert len(payload["equity_curve_points"]) == 3
    assert payload["runtime_trace"]["phases_ms"]["snapshot_lookup"] >= 0
    assert payload["runtime_trace"]["metadata"]["query_count"] == 1


def test_dashboard_overview_uses_snapshot_without_live_work(monkeypatch):
    with make_session() as db:
        DashboardSnapshotService().write(
            db,
            "dashboard_overview_summary",
            {"market_pulse": {"asset_count": 7}, "todays_strongest_signals": []},
            ttl_seconds=300,
        )
        payload = dashboard_overview(db)

    assert payload["market_pulse"]["asset_count"] == 7
    assert payload["runtime_policy"] == "snapshot_first_no_live_recalculation"
    assert payload["snapshot_status"] == "ready"


def test_missing_dashboard_snapshot_returns_partial_payload():
    with make_session() as db:
        payload = dashboard_overview(db)

    assert payload["snapshot_status"] == "missing"
    assert payload["market_pulse"]["signal_count"] == 0
    assert payload["runtime_policy"] == "snapshot_first_no_live_recalculation"


def test_snapshot_rows_can_be_marked_stale_and_still_read():
    with make_session() as db:
        game = seed_game(db)
        TradingGameRuntimeSnapshotService().produce_ledger_snapshot(db, game_id=game.id, limit=25)
        row = db.query(TradingGameLedgerSnapshot).filter_by(game_id=game.id).first()
        assert row is not None
        row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
        payload = TradeLedgerService().ledger(db, game_id=game.id, limit=25, refresh=False, use_snapshot=True)

    assert payload["status"] == "ok"
    assert payload["rows"]
