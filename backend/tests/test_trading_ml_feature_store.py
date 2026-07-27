from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import polars as pl
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    ForexDecision,
    ForexLearningEvidence,
    ForexTraderCycle,
    HistoricalPrediction,
    PredictionOutcome,
)
from app.services.trading_ml.contracts import TradingMLExample
from app.services.trading_ml.dataset import DatasetSlice, TradingMLDatasetRepository
from app.services.trading_ml.feature_store import TradingMLFeatureStoreProjector


NOW = datetime(2026, 7, 27, 10, 0)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _seed_forex_evidence(db: Session, *, suffix: int = 1) -> tuple[ForexDecision, ForexDecision]:
    cycle = ForexTraderCycle(
        cycle_uid=f"cycle-{suffix}",
        cycle_key=f"cycle-key-{suffix}",
        configuration_hash="a" * 64,
        data_coverage_hash="b" * 64,
    )
    db.add(cycle)
    db.flush()
    closed = ForexDecision(
        cycle_id=cycle.id,
        decision_uid=f"closed-{suffix}",
        pair="EURUSD=X",
        strategy_id="fx-breakout-v1",
        status="CLOSED",
        direction="LONG",
        decision_timestamp=NOW,
        proposal_json={"setup_family": "momentum_breakout", "confidence": 0.7, "expected_r": 1.2},
        input_snapshot={"session": "LONDON", "market_timestamp": NOW.isoformat()},
    )
    open_decision = ForexDecision(
        cycle_id=cycle.id,
        decision_uid=f"open-{suffix}",
        pair="GBPUSD=X",
        strategy_id="fx-breakout-v1",
        status="OPEN",
        direction="LONG",
        decision_timestamp=NOW + timedelta(minutes=1),
        proposal_json={"setup_family": "momentum_breakout", "confidence": 0.7, "expected_r": 1.2},
        input_snapshot={"session": "LONDON", "market_timestamp": (NOW + timedelta(minutes=1)).isoformat()},
    )
    db.add_all([closed, open_decision])
    db.flush()
    db.add_all(
        [
            ForexLearningEvidence(
                decision_id=closed.id,
                strategy_id=closed.strategy_id,
                pair=closed.pair,
                outcome="WIN",
                lesson="Closed outcome is eligible for supervised learning.",
                realized_result=0.8,
                evidence_type="PAPER_FORWARD_FOREX",
                payload_json={"evaluated_at": (NOW + timedelta(hours=1)).isoformat()},
            ),
            ForexLearningEvidence(
                decision_id=open_decision.id,
                strategy_id=open_decision.strategy_id,
                pair=open_decision.pair,
                outcome="PENDING",
                lesson="Open decision has no supervised label.",
                realized_result=None,
                evidence_type="PAPER_FORWARD_FOREX",
                payload_json={},
            ),
        ]
    )
    db.commit()
    return closed, open_decision


def _seed_equity_evidence(db: Session) -> HistoricalPrediction:
    prediction = HistoricalPrediction(
        ticker="NVDA",
        asset_type="Stock",
        sector="Technology",
        market="USA",
        market_regime="risk_on",
        volatility_regime="normal",
        analysis_date=NOW.date(),
        initial_price=100.0,
        expected_direction="bullish",
        confidence=72.0,
        data_quality_score=91.0,
        prediction_payload={"invalidation_level": 98.0, "setup_type": "momentum_breakout"},
        point_in_time_context={"market_timestamp": NOW.isoformat(), "market_context": {"market_regime": "risk_on"}},
        created_at=NOW,
    )
    db.add(prediction)
    db.flush()
    db.add(
        PredictionOutcome(
            prediction_id=prediction.id,
            ticker=prediction.ticker,
            timeframe="1d",
            horizon_days=1,
            evaluation_date=(NOW + timedelta(days=1)).date(),
            realized_return=2.0,
            metrics_payload={"realized_net_r": 0.95},
        )
    )
    db.commit()
    return prediction


def test_repository_excludes_open_and_unlabeled_rows(db):
    closed, _ = _seed_forex_evidence(db)

    rows = TradingMLDatasetRepository().read_slice(db, market_family="forex", after_cursor=None, limit=100)

    assert [row.source_object_id for row in rows.examples] == [str(closed.id)]
    assert rows.rows_considered == 1
    assert rows.next_cursor is not None
    assert rows.next_cursor["source_table"] == "forex_decisions"
    assert rows.next_cursor["last_source_id"] == closed.id


def test_repository_applies_limit_before_materializing_rows(db):
    first_closed, _ = _seed_forex_evidence(db)
    _seed_forex_evidence(db, suffix=2)

    rows = TradingMLDatasetRepository().read_slice(db, market_family="forex", after_cursor=None, limit=1)

    assert len(rows.examples) == 1
    assert rows.rows_considered == 1
    assert rows.next_cursor is not None
    assert rows.next_cursor["source_table"] == "forex_decisions"
    assert rows.next_cursor["last_source_id"] == first_closed.id


def test_repository_cursor_resumes_forex_source_after_other_sources_are_exhausted(db):
    first_closed, _ = _seed_forex_evidence(db)
    first = TradingMLDatasetRepository().read_slice(db, market_family="forex", after_cursor=None, limit=100)
    second_closed, _ = _seed_forex_evidence(db, suffix=2)

    second = TradingMLDatasetRepository().read_slice(
        db,
        market_family="forex",
        after_cursor=first.next_cursor,
        limit=100,
    )

    assert [row.source_object_id for row in first.examples] == [str(first_closed.id)]
    assert [row.source_object_id for row in second.examples] == [str(second_closed.id)]


def test_projector_is_incremental_and_idempotent(db, tmp_path):
    _seed_equity_evidence(db)
    projector = TradingMLFeatureStoreProjector(root=tmp_path)

    first = projector.project(db, market_family="equity", limit=100)
    second = projector.project(db, market_family="equity", limit=100)

    assert first.rows_written == 1
    assert second.rows_written == 0
    assert second.dataset_hash == first.dataset_hash
    assert projector.manifest()["source_cursors"]["equity"]["source_table"] == "historical_predictions"


def test_repository_selects_one_deterministic_terminal_outcome_per_prediction(db):
    prediction = _seed_equity_evidence(db)
    db.add(
        PredictionOutcome(
            prediction_id=prediction.id,
            ticker=prediction.ticker,
            timeframe="5d",
            horizon_days=5,
            evaluation_date=(NOW + timedelta(days=5)).date(),
            realized_return=3.0,
            metrics_payload={"realized_net_r": 1.1},
        )
    )
    db.commit()

    rows = TradingMLDatasetRepository().read_slice(db, market_family="equity", after_cursor=None, limit=100)

    assert [row.source_object_id for row in rows.examples] == [str(prediction.id)]
    assert rows.examples[0].realized_net_r == 1.1


class _SyntheticRepository:
    def __init__(self, examples: list[TradingMLExample]) -> None:
        self.examples = examples

    def read_slice(self, _db, *, market_family: str, after_cursor: dict | None, limit: int) -> DatasetSlice:
        assert market_family == "forex"
        offset = int((after_cursor or {}).get("last_source_id", 0))
        page = tuple(self.examples[offset : offset + limit])
        next_offset = offset + len(page)
        return DatasetSlice(
            examples=page,
            next_cursor=(
                {"source_table": "synthetic", "last_source_id": next_offset}
                if page
                else after_cursor
            ),
            rows_considered=len(page),
            rows_rejected=0,
            exhausted=next_offset >= len(self.examples),
        )


class _ConcurrentRepository:
    def __init__(self, example: TradingMLExample, barrier: Barrier) -> None:
        self.example = example
        self.barrier = barrier

    def read_slice(self, _db, *, market_family: str, after_cursor: dict | None, limit: int) -> DatasetSlice:
        assert market_family == self.example.market_family
        assert after_cursor is None
        assert limit > 0
        self.barrier.wait(timeout=5)
        return DatasetSlice(
            examples=(self.example,),
            next_cursor={"source_table": f"{market_family}_source", "last_source_id": 1},
            rows_considered=1,
            rows_rejected=0,
            exhausted=True,
        )


def _market_example(market_family: str) -> TradingMLExample:
    asset_key = "EURUSD=X" if market_family == "forex" else "NVDA"
    return TradingMLExample(
        source_object_type=f"{market_family}_trade",
        source_object_id="1",
        market_family=market_family,
        evidence_lane="REPLAY_EVIDENCE",
        decision_timestamp=NOW,
        outcome_timestamp=NOW + timedelta(minutes=1),
        asset_key=asset_key,
        setup_type="momentum_breakout",
        regime="trend_up",
        features={
            "aggregate_score": 70.0,
            "confidence": 60.0,
            "market_family": market_family,
            "setup_type": "momentum_breakout",
            "regime": "trend_up",
            "session": "LONDON" if market_family == "forex" else "regular",
            "direction": "LONG",
            "timeframe": "1m" if market_family == "forex" else "1d",
            "sector_or_currency_family": "EURUSD" if market_family == "forex" else "Technology",
        },
        realized_net_r=0.8,
        label_positive_r=1,
        benchmark_excess=0.1,
        sample_weight=0.25,
    )


def test_concurrent_market_projections_preserve_both_partitions_and_cursors(tmp_path):
    barrier = Barrier(2)
    equity_projector = TradingMLFeatureStoreProjector(
        root=tmp_path,
        repository=_ConcurrentRepository(_market_example("equity"), barrier),
    )
    forex_projector = TradingMLFeatureStoreProjector(
        root=tmp_path,
        repository=_ConcurrentRepository(_market_example("forex"), barrier),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        equity_future = executor.submit(equity_projector.project, None, market_family="equity", limit=10)
        forex_future = executor.submit(forex_projector.project, None, market_family="forex", limit=10)
        equity_future.result(timeout=10)
        forex_future.result(timeout=10)

    manifest = equity_projector.manifest()
    equity_rows = equity_projector.scan(market_family="equity", columns=["source_uid"]).collect()
    forex_rows = equity_projector.scan(market_family="forex", columns=["source_uid"]).collect()

    assert set(manifest["source_cursors"]) == {"equity", "forex"}
    assert {partition["market_family"] for partition in manifest["partitions"]} == {"equity", "forex"}
    assert equity_rows["source_uid"].to_list() == ["equity_trade:1"]
    assert forex_rows["source_uid"].to_list() == ["forex_trade:1"]


def _synthetic_example(index: int) -> TradingMLExample:
    timestamp = NOW + timedelta(minutes=index)
    return TradingMLExample(
        source_object_type="synthetic_trade",
        source_object_id=str(index + 1),
        market_family="forex",
        evidence_lane="REPLAY_EVIDENCE",
        decision_timestamp=timestamp,
        outcome_timestamp=timestamp + timedelta(minutes=1),
        asset_key="EURUSD=X",
        setup_type="momentum_breakout",
        regime="trend_up",
        features={
            "aggregate_score": float(index % 100),
            "confidence": 60.0,
            "market_family": "forex",
            "setup_type": "momentum_breakout",
            "regime": "trend_up",
            "session": "LONDON",
            "direction": "LONG",
            "timeframe": "1m",
            "sector_or_currency_family": "EURUSD",
        },
        realized_net_r=1.0 if index % 2 else -0.5,
        label_positive_r=index % 2,
        benchmark_excess=0.1,
        sample_weight=0.25,
    )


def test_feature_store_scans_lazily_and_projects_large_input_in_bounded_partitions(tmp_path):
    examples = [_synthetic_example(index) for index in range(20_000)]
    projector = TradingMLFeatureStoreProjector(
        root=tmp_path,
        repository=_SyntheticRepository(examples),
        max_rows_per_projection=5_000,
        max_partition_rows=750,
    )

    for _ in range(5):
        projector.project(db=None, market_family="forex", limit=20_000)

    scan = projector.scan(
        market_family="forex",
        columns=["source_uid", "label_positive_r"],
        predicate=pl.col("label_positive_r") == 1,
    )
    assert isinstance(scan, pl.LazyFrame)
    result = scan.collect()
    manifest = projector.manifest()

    assert result.height == 10_000
    assert result["source_uid"].n_unique() == 10_000
    assert len(manifest["partitions"]) >= 27
    assert sum(partition["rows"] for partition in manifest["partitions"]) == 20_000
    assert manifest["evidence_lane_counts"] == {"REPLAY_EVIDENCE": 20_000}
