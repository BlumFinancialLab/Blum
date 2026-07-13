from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    Asset,
    HyperbolicReplayRun,
    HyperbolicReplayTrade,
    LiveForwardPaperGame,
    LiveForwardPaperTrade,
    ReplayStrategyValidation,
    StrategyEvidenceSnapshot,
)
from app.services.copy_readiness_evidence import StrategyEvidenceProjector, StrategyEvidenceQuery


NOW = datetime(2026, 7, 13, 14, 30)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def seed_replay_walk_forward_and_paper_rows(db: Session) -> ReplayStrategyValidation:
    asset = Asset(
        ticker="NVDA",
        name="NVIDIA",
        category="Stock",
        asset_type="Stock",
        sector="Technology",
        country="USA",
        exchange="NASDAQ",
        currency="USD",
        is_active=True,
    )
    replay_run = HyperbolicReplayRun(run_id="replay-evidence", status="COMPLETED", completed_at=NOW)
    validation = ReplayStrategyValidation(
        setup_type="momentum_breakout",
        sample_size=25,
        markets_json=["USA", "Europe"],
        windows_json=[{"regime": "risk_on"}, {"regime": "risk_off"}],
        metrics_json={"net_expectancy": 0.4, "win_rate": 0.6, "benchmark_excess": 1.1},
        verdict="PROMOTED_TO_PAPER",
        created_at=NOW,
    )
    game = LiveForwardPaperGame(game_id="evidence-game")
    db.add_all([asset, replay_run, validation, game])
    db.flush()
    db.add(
        HyperbolicReplayTrade(
            run_id=replay_run.id,
            asset_id=asset.id,
            ticker="NVDA",
            market="USA",
            setup_type="momentum_breakout",
            timeframe="1d",
            state="CLOSED",
            decision_timestamp=NOW - timedelta(days=2),
            exit_timestamp=NOW - timedelta(days=1),
            gross_pnl=3.0,
            net_pnl=2.8,
            r_multiple=1.4,
            benchmark_excess=0.8,
            data_quality_score=95.0,
            outcome_payload={"regime": "risk_on", "slippage": 0.05},
        )
    )
    db.add_all(
        [
            forward_trade(
                game,
                uid="paper-closed",
                setup_type="momentum_breakout",
                promoted_validation_id=validation.id,
                status="CLOSED",
                evidence_type="PAPER_FORWARD",
                gross_pnl_eur=2.0,
                net_pnl_eur=1.5,
                costs_paid=0.5,
                slippage_cost=0.2,
                benchmark_return_same_period=0.4,
                excess_return_vs_benchmark=1.1,
                regime="risk_on",
            ),
            forward_trade(
                game,
                uid="intraday-closed",
                setup_type="momentum_breakout",
                promoted_validation_id=validation.id,
                status="CLOSED",
                evidence_type="PAPER_FORWARD_INTRADAY",
                trading_mode="INTRADAY_PAPER_FORWARD",
                gross_pnl_eur=1.4,
                net_pnl_eur=1.1,
                costs_paid=0.3,
                slippage_cost=0.1,
                benchmark_return_same_period=0.2,
                excess_return_vs_benchmark=0.9,
                regime="range",
                timeframe_stack=["1d", "15m", "5m", "1m"],
            ),
        ]
    )
    db.commit()
    return validation


def forward_trade(
    game: LiveForwardPaperGame,
    *,
    uid: str,
    setup_type: str = "momentum_breakout",
    status: str = "CLOSED",
    evidence_type: str = "PAPER_FORWARD",
    trading_mode: str | None = "PAPER_FORWARD",
    promoted_validation_id: int | None = None,
    gross_pnl_eur: float | None = None,
    net_pnl_eur: float | None = None,
    costs_paid: float = 0.0,
    slippage_cost: float = 0.0,
    benchmark_return_same_period: float | None = None,
    excess_return_vs_benchmark: float | None = None,
    regime: str = "risk_on",
    timeframe_stack: list[str] | None = None,
) -> LiveForwardPaperTrade:
    closed_at = NOW + timedelta(minutes=30) if status in {"CLOSED", "EXPIRED", "INVALIDATED"} else None
    return LiveForwardPaperTrade(
        trade_uid=uid,
        game_id=game.id,
        ticker="NVDA",
        asset_type="Stock",
        setup_type=setup_type,
        status=status,
        decision_timestamp=NOW,
        decision_date=NOW.date(),
        opened_at=NOW,
        closed_at=closed_at,
        entry_price=100.0,
        exit_price=102.0 if closed_at else None,
        position_size=1.0,
        gross_pnl_eur=gross_pnl_eur,
        net_pnl_eur=net_pnl_eur,
        r_multiple=1.0 if closed_at else None,
        benchmark_return_same_period=benchmark_return_same_period,
        excess_return_vs_benchmark=excess_return_vs_benchmark,
        duplicate_key=f"evidence:{uid}",
        market="USA",
        evidence_type=evidence_type,
        trading_mode=trading_mode,
        promoted_validation_id=promoted_validation_id,
        costs_paid=costs_paid,
        slippage_cost=slippage_cost,
        frozen_decision_payload={"regime": regime},
        timeframe_stack=timeframe_stack or ["1d"],
    )


def latest_card(db: Session, evidence_class: str) -> StrategyEvidenceSnapshot:
    row = db.scalar(
        select(StrategyEvidenceSnapshot)
        .where(StrategyEvidenceSnapshot.evidence_class == evidence_class)
        .order_by(StrategyEvidenceSnapshot.id.desc())
        .limit(1)
    )
    assert row is not None
    return row


def test_projector_keeps_all_evidence_classes_separate(db):
    seed_replay_walk_forward_and_paper_rows(db)

    result = StrategyEvidenceProjector().project(db, max_items=100)

    classes = {row.evidence_class for row in db.scalars(select(StrategyEvidenceSnapshot)).all()}
    assert classes == {
        "REPLAY_EVIDENCE",
        "WALK_FORWARD_EVIDENCE",
        "PAPER_FORWARD_EVIDENCE",
        "INTRADAY_FORWARD_EVIDENCE",
    }
    assert result["source_rows_processed"] == 4
    walk_forward = latest_card(db, "WALK_FORWARD_EVIDENCE")
    assert walk_forward.total_trades == 25
    assert walk_forward.closed_trades == 25
    assert walk_forward.forward_trades == 0


def test_open_forward_trade_does_not_count_as_closed_evidence(db):
    game = LiveForwardPaperGame(game_id="open-evidence-game")
    db.add(game)
    db.flush()
    db.add(forward_trade(game, uid="open-paper", status="OPEN"))
    db.commit()

    StrategyEvidenceProjector().project(db)

    card = latest_card(db, "PAPER_FORWARD_EVIDENCE")
    assert card.total_trades == 1
    assert card.closed_trades == 0
    assert card.forward_trades == 0


def test_legacy_standard_forward_producer_shape_projects_as_paper_without_mutating_source(db):
    game = LiveForwardPaperGame(game_id="legacy-standard-forward-game")
    db.add(game)
    db.flush()
    # Standard paper-forward producers predate the provenance fields and leave both unset.
    source = forward_trade(
        game,
        uid="legacy-standard-forward",
        evidence_type=None,
        trading_mode=None,
        gross_pnl_eur=1.0,
        net_pnl_eur=0.8,
    )
    db.add(source)
    db.commit()

    StrategyEvidenceProjector().project(db)

    card = latest_card(db, "PAPER_FORWARD_EVIDENCE")
    db.refresh(source)
    assert card.source_rows_json[0]["source_type"] == "live_forward_paper_trade"
    assert card.source_rows_json[0]["source_id"] == source.id
    assert card.closed_trades == 1
    assert source.evidence_type is None
    assert source.trading_mode is None


def test_costs_and_slippage_reduce_net_expectancy(db):
    game = LiveForwardPaperGame(game_id="cost-evidence-game")
    db.add(game)
    db.flush()
    db.add(
        forward_trade(
            game,
            uid="cost-paper",
            gross_pnl_eur=2.0,
            net_pnl_eur=None,
            costs_paid=0.5,
            slippage_cost=0.2,
        )
    )
    db.commit()

    StrategyEvidenceProjector().project(db)

    card = latest_card(db, "PAPER_FORWARD_EVIDENCE")
    assert card.total_costs == 0.5
    assert card.average_slippage == 0.2
    assert card.gross_expectancy == 2.0
    assert card.net_expectancy == 1.5


def test_missing_benchmark_remains_null(db):
    game = LiveForwardPaperGame(game_id="benchmark-evidence-game")
    db.add(game)
    db.flush()
    db.add(forward_trade(game, uid="benchmark-paper", gross_pnl_eur=1.0, net_pnl_eur=1.0))
    db.commit()

    StrategyEvidenceProjector().project(db)

    card = latest_card(db, "PAPER_FORWARD_EVIDENCE")
    assert card.benchmark_return is None
    assert card.benchmark_excess is None


def test_open_only_evidence_persists_and_serializes_no_confidence_interval(db):
    game = LiveForwardPaperGame(game_id="open-confidence-game")
    db.add(game)
    db.flush()
    db.add(forward_trade(game, uid="open-confidence", status="OPEN"))
    db.commit()

    StrategyEvidenceProjector().project(db)

    card = latest_card(db, "PAPER_FORWARD_EVIDENCE")
    page = StrategyEvidenceQuery().latest_cards(db, limit=1, offset=0)
    assert card.confidence_interval_json is None
    assert page["items"][0]["confidence_interval"] is None


def test_summary_only_evidence_persists_and_serializes_no_confidence_interval(db):
    db.add(
        ReplayStrategyValidation(
            setup_type="summary_only",
            sample_size=25,
            metrics_json={"net_expectancy": 0.4, "win_rate": 0.6},
            created_at=NOW,
        )
    )
    db.commit()

    StrategyEvidenceProjector().project(db)

    card = latest_card(db, "WALK_FORWARD_EVIDENCE")
    page = StrategyEvidenceQuery().latest_cards(db, limit=1, offset=0, strategy_id=card.strategy_id)
    assert card.confidence_interval_json is None
    assert page["items"][0]["confidence_interval"] is None


def test_strategy_identity_uses_validation_then_warns_on_setup_fallback(db):
    validation = seed_replay_walk_forward_and_paper_rows(db)
    game = db.scalar(select(LiveForwardPaperGame).where(LiveForwardPaperGame.game_id == "evidence-game"))
    assert game is not None
    db.add(forward_trade(game, uid="fallback-paper", setup_type=" Momentum Breakout ", gross_pnl_eur=1.0, net_pnl_eur=1.0))
    db.commit()

    StrategyEvidenceProjector().project(db)

    promoted = db.scalar(
        select(StrategyEvidenceSnapshot).where(
            StrategyEvidenceSnapshot.evidence_class == "PAPER_FORWARD_EVIDENCE",
            StrategyEvidenceSnapshot.strategy_id == f"validation:{validation.id}",
        )
    )
    fallback = db.scalar(
        select(StrategyEvidenceSnapshot).where(
            StrategyEvidenceSnapshot.evidence_class == "PAPER_FORWARD_EVIDENCE",
            StrategyEvidenceSnapshot.strategy_id == "setup:momentum_breakout",
        )
    )
    assert promoted is not None
    assert fallback is not None
    assert "strategy_identity_fallback" in fallback.warnings_json


def test_projection_reruns_append_new_cards_without_mutating_prior_snapshot(db):
    seed_replay_walk_forward_and_paper_rows(db)
    projector = StrategyEvidenceProjector()

    projector.project(db)
    first_rows = db.scalars(select(StrategyEvidenceSnapshot).order_by(StrategyEvidenceSnapshot.id)).all()
    first_ids = [row.id for row in first_rows]
    first_metrics = [row.metrics_json.copy() for row in first_rows]

    projector.project(db)
    rows = db.scalars(select(StrategyEvidenceSnapshot).order_by(StrategyEvidenceSnapshot.id)).all()

    assert len(rows) == len(first_rows) * 2
    assert [row.id for row in rows[: len(first_rows)]] == first_ids
    assert [row.metrics_json for row in rows[: len(first_rows)]] == first_metrics


def test_projector_and_query_are_bounded(db):
    seed_replay_walk_forward_and_paper_rows(db)

    result = StrategyEvidenceProjector().project(db, max_items=2)
    page = StrategyEvidenceQuery().latest_cards(db, limit=1, offset=0)

    assert result["source_rows_processed"] <= 2
    assert page["limit"] == 1
    assert page["offset"] == 0
    assert len(page["items"]) == 1
    assert page["has_more"] is True
    assert page["next_offset"] == 1
    assert "total" not in page

    next_page = StrategyEvidenceQuery().latest_cards(db, limit=101, offset=page["next_offset"])
    assert next_page["limit"] == 100
    assert next_page["offset"] == 1
    assert next_page["has_more"] is False
    assert next_page["next_offset"] is None
