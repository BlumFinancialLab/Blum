from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Base
from app.models import EvidenceTimelineEvent, StrategyEvidenceSnapshot, StrategyReadinessHistory
from app.services.copy_readiness_evidence import (
    BlumCopyReadinessEngine,
    CopyReadinessSummaryService,
    EvidenceTimelineService,
)


NOW = datetime(2026, 7, 13, 14, 30)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def add_card(
    db: Session,
    *,
    strategy_id: str = "validation:1",
    evidence_class: str,
    closed_trades: int = 500,
    net_expectancy: float = 0.4,
    profit_factor: float = 2.0,
    max_drawdown: float = 5.0,
    benchmark_excess: float = 0.3,
    observation_days: int = 300,
    ticker_count: int = 12,
    regime_count: int = 3,
    ticker_concentration: float = 0.20,
    market_concentration: float = 0.50,
    total_costs: float | None = 3.0,
    average_slippage: float | None = 0.1,
    warnings: list[str] | None = None,
    evaluated_at: datetime = NOW,
) -> StrategyEvidenceSnapshot:
    source_start = evaluated_at - timedelta(days=observation_days)
    card = StrategyEvidenceSnapshot(
        strategy_id=strategy_id,
        setup_type="momentum_breakout",
        evidence_class=evidence_class,
        total_trades=closed_trades,
        closed_trades=closed_trades,
        forward_trades=(closed_trades if "FORWARD" in evidence_class else 0),
        win_rate=0.60,
        gross_expectancy=net_expectancy + 0.05,
        net_expectancy=net_expectancy,
        average_r=0.6,
        profit_factor=profit_factor,
        sharpe_proxy=1.2,
        sortino_proxy=1.5,
        max_drawdown=max_drawdown,
        benchmark_return=0.1,
        benchmark_excess=benchmark_excess,
        total_costs=total_costs,
        average_slippage=average_slippage,
        metrics_json={"data_timestamp": evaluated_at.isoformat()},
        markets_json=["USA", "EUROPE"],
        timeframes_json=["1d"],
        source_rows_json=[
            {"source_type": "fixture", "source_id": 1, "timestamp": source_start.isoformat()},
            {"source_type": "fixture", "source_id": 2, "timestamp": evaluated_at.isoformat()},
        ],
        warnings_json=warnings or [],
        concentration_json={
            "tickers": {"distinct_count": ticker_count, "top_share": ticker_concentration},
            "markets": {"distinct_count": 2, "top_share": market_concentration},
        },
        regimes_json=[
            {"regime": f"regime-{index}", "closed_trades": 10, "net_expectancy": 0.2}
            for index in range(regime_count)
        ],
        confidence_interval_json={"lower": 0.50, "upper": 0.70},
        evaluated_at=evaluated_at,
    )
    db.add(card)
    db.flush()
    return card


def seed_mature_forward_cards(db: Session, *, strategy_id: str = "validation:1") -> None:
    add_card(db, strategy_id=strategy_id, evidence_class="WALK_FORWARD_EVIDENCE", net_expectancy=0.8)
    add_card(db, strategy_id=strategy_id, evidence_class="PAPER_FORWARD_EVIDENCE", net_expectancy=0.6)


def latest_readiness(db: Session, strategy_id: str = "validation:1") -> StrategyReadinessHistory:
    row = db.scalar(
        select(StrategyReadinessHistory)
        .where(StrategyReadinessHistory.strategy_id == strategy_id)
        .order_by(StrategyReadinessHistory.evaluated_at.desc(), StrategyReadinessHistory.id.desc())
        .limit(1)
    )
    assert row is not None
    return row


def readiness_settings(**overrides) -> Settings:
    values = {
        "copy_readiness_global_forward_trades": 100,
        "copy_readiness_strategy_forward_trades": 30,
        "copy_readiness_observation_days": 90,
        "copy_readiness_max_drawdown": 15.0,
        "copy_readiness_max_decay_pct": 35.0,
        "copy_readiness_min_tickers": 5,
        "copy_readiness_min_regimes": 2,
        "copy_readiness_max_ticker_concentration": 0.35,
        "copy_readiness_max_market_concentration": 0.70,
        "copy_readiness_high_confidence_global_forward_trades": 300,
        "copy_readiness_high_confidence_strategy_forward_trades": 100,
        "copy_readiness_high_confidence_observation_days": 180,
        "copy_readiness_high_confidence_max_drawdown": 12.0,
        "copy_readiness_high_confidence_max_decay_pct": 25.0,
        "copy_readiness_high_confidence_min_tickers": 8,
        "copy_readiness_high_confidence_min_regimes": 3,
        "copy_readiness_high_confidence_max_ticker_concentration": 0.30,
        "copy_readiness_high_confidence_max_market_concentration": 0.60,
        "limited_external_validation_global_forward_trades": 500,
        "limited_external_validation_strategy_forward_trades": 150,
        "limited_external_validation_observation_days": 270,
        "limited_external_validation_max_drawdown": 10.0,
        "limited_external_validation_max_decay_pct": 20.0,
        "limited_external_validation_min_tickers": 10,
        "limited_external_validation_min_regimes": 3,
        "limited_external_validation_max_ticker_concentration": 0.30,
        "limited_external_validation_max_market_concentration": 0.60,
    }
    values.update(overrides)
    return Settings(**values)


def test_recalculate_appends_readiness_and_is_idempotent_for_timeline(db):
    seed_mature_forward_cards(db)
    engine = BlumCopyReadinessEngine(settings=readiness_settings())

    first = engine.recalculate(db)
    second = engine.recalculate(db)

    assert first["strategies_evaluated"] == 1
    assert first["timeline_events_created"] > 0
    assert second["strategies_evaluated"] == 1
    assert second["timeline_events_created"] == 0
    assert db.scalar(select(func.count()).select_from(StrategyReadinessHistory)) == 2
    assert db.scalar(select(func.count()).select_from(EvidenceTimelineEvent)) == first["timeline_events_created"]


def test_material_forward_decay_suspends_strategy(db):
    add_card(
        db,
        evidence_class="REPLAY_EVIDENCE",
        net_expectancy=0.8,
        profit_factor=2.0,
    )
    add_card(
        db,
        evidence_class="PAPER_FORWARD_EVIDENCE",
        net_expectancy=-0.2,
        profit_factor=0.7,
    )

    BlumCopyReadinessEngine(settings=readiness_settings()).recalculate(db)

    row = latest_readiness(db)
    assert row.copy_readiness_status == "SUSPENDED"
    assert row.decay_status == "FORWARD_FAILURE"


def test_external_validation_eligibility_is_autonomous_and_stricter(db):
    seed_mature_forward_cards(db)
    settings = readiness_settings(
        limited_external_validation_strategy_forward_trades=600,
    )

    result = BlumCopyReadinessEngine(settings=settings).recalculate(db)

    assert result["strategies"][0]["copy_readiness_status"] == "COPY_READY_HIGH_CONFIDENCE"
    assert result["strategies"][0]["real_capital_eligibility"] == "PAPER_ONLY"

    eligible_settings = readiness_settings(
        copy_readiness_threshold_version="test-v2",
        limited_external_validation_strategy_forward_trades=500,
    )
    add_card(
        db,
        evidence_class="PAPER_FORWARD_EVIDENCE",
        net_expectancy=0.65,
        evaluated_at=NOW + timedelta(minutes=1),
    )
    eligible = BlumCopyReadinessEngine(settings=eligible_settings).recalculate(db)

    assert eligible["strategies"][0]["real_capital_eligibility"] == "ELIGIBLE_FOR_LIMITED_EXTERNAL_VALIDATION"
    assert "MANUAL_REVIEW_REQUIRED" not in {
        row.real_capital_eligibility for row in db.scalars(select(StrategyReadinessHistory)).all()
    }
    assert latest_readiness(db).threshold_version == "test-v2"


def test_previous_ready_history_drives_degraded_transition(db):
    seed_mature_forward_cards(db)
    engine = BlumCopyReadinessEngine(settings=readiness_settings())
    engine.recalculate(db)
    assert latest_readiness(db).copy_readiness_status == "COPY_READY_HIGH_CONFIDENCE"

    add_card(
        db,
        evidence_class="PAPER_FORWARD_EVIDENCE",
        net_expectancy=0.6,
        ticker_count=4,
        evaluated_at=NOW + timedelta(minutes=1),
    )
    engine.recalculate(db)

    row = latest_readiness(db)
    assert row.previous_copy_readiness_status == "COPY_READY_HIGH_CONFIDENCE"
    assert row.copy_readiness_status == "DEGRADED"


def test_recalculate_uses_latest_card_per_class(db):
    add_card(
        db,
        evidence_class="PAPER_FORWARD_EVIDENCE",
        net_expectancy=-0.5,
        evaluated_at=NOW - timedelta(minutes=1),
    )
    add_card(db, evidence_class="REPLAY_EVIDENCE", net_expectancy=0.8)
    latest = add_card(
        db,
        evidence_class="PAPER_FORWARD_EVIDENCE",
        net_expectancy=0.6,
        evaluated_at=NOW + timedelta(minutes=1),
    )

    result = BlumCopyReadinessEngine(settings=readiness_settings()).recalculate(db)

    assert result["strategies"][0]["copy_readiness_status"] == "COPY_READY_HIGH_CONFIDENCE"
    assert result["strategies"][0]["forward_evidence_snapshot_id"] == latest.id


def test_setup_identity_fallback_warns_without_blocking_mature_evidence(db):
    add_card(
        db,
        strategy_id="setup:momentum_breakout",
        evidence_class="WALK_FORWARD_EVIDENCE",
        net_expectancy=0.8,
        warnings=["strategy_identity_fallback"],
    )
    add_card(
        db,
        strategy_id="setup:momentum_breakout",
        evidence_class="PAPER_FORWARD_EVIDENCE",
        net_expectancy=0.65,
        warnings=["strategy_identity_fallback"],
    )

    result = BlumCopyReadinessEngine(settings=readiness_settings()).recalculate(db)

    assert result["strategies"][0]["copy_readiness_status"] == "COPY_READY_HIGH_CONFIDENCE"


def test_recalculate_bounds_number_of_strategies(db):
    for index in range(3):
        add_card(
            db,
            strategy_id=f"validation:{index}",
            evidence_class="PAPER_FORWARD_EVIDENCE",
            evaluated_at=NOW + timedelta(minutes=index),
        )

    result = BlumCopyReadinessEngine(settings=readiness_settings()).recalculate(db, max_strategies=2)

    assert result["max_strategies"] == 2
    assert result["strategies_evaluated"] == 2
    assert db.scalar(select(func.count()).select_from(StrategyReadinessHistory)) == 2


def test_timeline_append_once_returns_existing_and_propagates_unrelated_db_errors(db):
    service = EvidenceTimelineService()
    first = service.append_once(
        db,
        event_key="readiness:validation-1:v1",
        event_type="copy_readiness_change",
        strategy_id="validation:1",
        trade_id=None,
        payload={"from": None, "to": "REPLAY_ONLY"},
    )
    duplicate = service.append_once(
        db,
        event_key="readiness:validation-1:v1",
        event_type="different-payload-is-not-written",
        strategy_id="validation:1",
        trade_id=None,
        payload={"from": "unexpected", "to": "unexpected"},
    )

    assert duplicate.id == first.id
    assert duplicate.event_type == "copy_readiness_change"
    assert db.scalar(select(func.count()).select_from(EvidenceTimelineEvent)) == 1

    with pytest.raises(IntegrityError):
        service.append_once(
            db,
            event_key="invalid-event",
            event_type=None,  # type: ignore[arg-type]
            strategy_id=None,
            trade_id=None,
            payload={},
        )


def test_summary_uses_only_latest_readiness_per_strategy(db):
    db.add_all(
        [
            readiness_row(
                strategy_id="validation:1",
                status="SUSPENDED",
                eligibility="NOT_ELIGIBLE",
                evaluated_at=NOW - timedelta(hours=1),
            ),
            readiness_row(
                strategy_id="validation:1",
                status="COPY_READY_HIGH_CONFIDENCE",
                eligibility="ELIGIBLE_FOR_LIMITED_EXTERNAL_VALIDATION",
                evaluated_at=NOW,
            ),
            readiness_row(
                strategy_id="validation:2",
                status="FORWARD_EVIDENCE_GROWING",
                eligibility="OBSERVE_ONLY",
                evaluated_at=NOW,
            ),
        ]
    )
    db.flush()

    summary = CopyReadinessSummaryService(settings=readiness_settings()).summary(db)

    assert summary["total_strategies"] == 2
    assert summary["ready_strategies"] == 1
    assert summary["not_ready_strategies"] == 1
    assert summary["copy_readiness_status"] == "COPY_READY_HIGH_CONFIDENCE"
    assert summary["real_capital_eligibility"] == "ELIGIBLE_FOR_LIMITED_EXTERNAL_VALIDATION"
    assert summary["decay_summary"] == {"CONSISTENT": 2}
    assert summary["required_strategy_forward_trades"] == 30
    assert summary["required_capital_global_forward_trades"] == 500
    assert summary["required_capital_strategy_forward_trades"] == 150
    assert summary["required_capital_observation_days"] == 270
    assert summary["selected_strategy_id"] == "validation:1"
    assert summary["threshold_version"] == "copy-readiness-v1"


def readiness_row(
    *,
    strategy_id: str,
    status: str,
    eligibility: str,
    evaluated_at: datetime,
) -> StrategyReadinessHistory:
    return StrategyReadinessHistory(
        strategy_id=strategy_id,
        previous_copy_readiness_status=None,
        copy_readiness_status=status,
        maturity_score=80.0,
        global_forward_trades=500,
        strategy_forward_trades=150,
        observation_days=300,
        passed_gates_json=["sample"],
        failed_gates_json=[] if "COPY_READY" in status else ["ticker_count"],
        blockers_json=[] if "COPY_READY" in status else ["ticker_count"],
        reasons_json=[],
        decay_status="CONSISTENT",
        real_capital_eligibility=eligibility,
        threshold_version="copy-readiness-v1",
        evaluated_at=evaluated_at,
    )
