from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    ForexContextualMemory,
    ForexCurriculumAssignment,
    ForexKnowledgeIngestionRun,
    ForexKnowledgeSource,
    ForexLearningEvidence,
    Asset,
    HyperbolicReplayRun,
    HyperbolicReplayTrade,
)
from app.services.forex_evidence_academy import (
    ForexCurriculumPlanner,
    ForexEvidenceAcademyService,
    ForexKnowledgeCatalogService,
    ForexMemoryCompiler,
)


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_forex_academy_models_are_cross_database_safe() -> None:
    with setup_db() as db:
        db.add(
            ForexKnowledgeSource(
                source_key="ecb_sdmx",
                title="ECB Data Portal",
                provider="ECB",
                source_type="AUTHORITATIVE_CONTEXT",
                source_url="https://data-api.ecb.europa.eu",
                license="official-public-data",
                usage_policy={"edge_evidence": False},
                validation_status="CATALOGED",
            )
        )
        db.add(
            ForexKnowledgeIngestionRun(
                source_key="ecb_sdmx",
                status="COMPLETED",
                cursor_json={"series": "EXR"},
                validation_json={"schema": "valid"},
            )
        )
        db.commit()

        source = db.scalar(select(ForexKnowledgeSource))
        run = db.scalar(select(ForexKnowledgeIngestionRun))
        assert source is not None and source.usage_policy["edge_evidence"] is False
        assert run is not None and run.cursor_json == {"series": "EXR"}


def test_catalog_persists_provenance_without_creating_edge_evidence() -> None:
    with setup_db() as db:
        result = ForexKnowledgeCatalogService().refresh(db, validate=False)
        sources = db.scalars(select(ForexKnowledgeSource)).all()

        assert result["sources_cataloged"] >= 6
        assert {row.provider for row in sources} >= {"ECB", "FRED", "CFTC", "HUGGING_FACE", "ZENODO"}
        assert all(row.usage_policy.get("direct_confidence_effect") is False for row in sources)
        assert all(row.usage_policy.get("edge_evidence") is False for row in sources)


def test_curriculum_is_bounded_and_preserves_exploration() -> None:
    with setup_db() as db:
        assignments = ForexCurriculumPlanner().generate(db, limit=6)

        assert len(assignments) == 6
        assert any(row.priority_type == "BROAD_EXPLORATION" for row in assignments)
        assert len({row.pair for row in assignments}) >= 3
        assert all(row.expected_information_gain > 0 for row in assignments)


def test_curriculum_generation_is_unique_and_idempotent_at_max_batch_size() -> None:
    with setup_db() as db:
        first = ForexCurriculumPlanner().generate(db, limit=48)
        second = ForexCurriculumPlanner().generate(db, limit=48)

        assert len(first) == 48
        assert len({row.assignment_key for row in first}) == 48
        assert {row.assignment_key for row in second} == {row.assignment_key for row in first}
        assert db.scalar(select(func.count()).select_from(ForexCurriculumAssignment)) == 48


def add_evidence(
    db: Session,
    *,
    count: int,
    strategy_id: str = "fx-breakout-v1",
    realized_r: float = 0.3,
    benchmark_excess: float = 0.1,
) -> None:
    for index in range(count):
        db.add(
            ForexLearningEvidence(
                strategy_id=strategy_id,
                pair="EURUSD=X" if index % 2 == 0 else "GBPUSD=X",
                session="LONDON",
                regime="trend",
                setup_family="momentum_breakout",
                direction="LONG",
                outcome="WIN" if realized_r > 0 else "LOSS",
                expected_result=0.2,
                realized_result=realized_r,
                difference=realized_r - 0.2,
                likely_cause="TARGET_HIT" if realized_r > 0 else "STOP_HIT",
                lesson="Observed point-in-time outcome",
                evidence_strength=0.8,
                model_update_justified=True,
                evidence_type="REPLAY_FOREX",
                payload_json={"benchmark_excess": benchmark_excess},
            )
        )
    db.commit()


def test_memory_compiler_keeps_small_samples_learning_only() -> None:
    with setup_db() as db:
        add_evidence(db, count=12)
        result = ForexMemoryCompiler().compile(db)
        memory = db.scalar(select(ForexContextualMemory))

        assert result["cells_compiled"] == 1
        assert memory is not None
        assert memory.sample_size == 12
        assert memory.evidence_grade == "LEARNING_ONLY"
        assert memory.confidence_adjustment == 0.0


def test_memory_compiler_promotes_only_validated_positive_context() -> None:
    with setup_db() as db:
        add_evidence(db, count=40, realized_r=0.35, benchmark_excess=0.12)
        ForexMemoryCompiler().compile(db)
        memory = db.scalar(select(ForexContextualMemory))

        assert memory is not None
        assert memory.evidence_grade == "CONTEXT_ELIGIBLE"
        assert 0 < memory.confidence_adjustment <= 0.08
        assert memory.net_expectancy_r > 0
        assert memory.benchmark_excess > 0


def test_memory_compiler_reads_persisted_forex_replay_outcomes() -> None:
    with setup_db() as db:
        asset = Asset(
            ticker="EURUSD=X",
            name="EUR/USD",
            category="Forex",
            sector="Currencies",
            country="FOREX",
            asset_type="Forex",
        )
        run = HyperbolicReplayRun(run_id="fx-memory-replay", status="COMPLETED")
        db.add_all([asset, run])
        db.flush()
        for index in range(30):
            timestamp = datetime(2026, 1, 1) + timedelta(minutes=index)
            db.add(
                HyperbolicReplayTrade(
                    run_id=run.id,
                    asset_id=asset.id,
                    ticker=asset.ticker,
                    market="FOREX",
                    setup_type="momentum_breakout",
                    strategy_fingerprint="fx-replay-fingerprint",
                    timeframe="1m",
                    state="REPLAY_EVALUATED",
                    evidence_type="REPLAY_EVIDENCE",
                    decision_timestamp=timestamp,
                    entry_timestamp=timestamp,
                    exit_timestamp=timestamp + timedelta(minutes=5),
                    r_multiple=0.25,
                    benchmark_excess=0.08,
                    data_quality_score=95.0,
                    decision_payload={"regime": "trend", "session": "LONDON"},
                    execution_payload={"total_cost": 0.1},
                )
            )
        db.commit()

        result = ForexMemoryCompiler().compile(db)
        memory = db.scalar(select(ForexContextualMemory))

        assert result["replay_rows_read"] == 30
        assert memory is not None
        assert memory.strategy_id == "fx-replay-fingerprint"
        assert memory.evidence_grade == "CONTEXT_ELIGIBLE"


def test_background_slice_catalogs_plans_and_compiles_without_network() -> None:
    with setup_db() as db:
        result = ForexEvidenceAcademyService().run_background_slice(db, max_assignments=4)

        assert result["status"] == "COMPLETED"
        assert result["catalog"]["network_used"] is False
        assert result["curriculum"]["assignments_created"] == 4
        assert result["memory"]["cells_compiled"] == 0
        assert db.scalar(select(ForexCurriculumAssignment)) is not None
