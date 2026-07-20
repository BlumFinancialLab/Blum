from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import ReplayStrategyValidation, StrategyCandidateVariant, StrategyFactoryRun
from app.services.executable_strategy import ExecutableStrategySpec, canonical_strategy_spec
from app.services.strategy_promotion_frontier import StrategyPromotionFrontierService


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def add_candidate(db: Session, *, target_r: float, sample_size: int, expectancy: float) -> ExecutableStrategySpec:
    spec = ExecutableStrategySpec.from_payload(
        {**canonical_strategy_spec("intraday_breakout").to_payload(), "target_r_multiple": target_r}
    )
    run = StrategyFactoryRun(
        run_uid=f"frontier-{target_r}",
        hypothesis_family="intraday_scalping",
        generation_seed=7,
        status="COMPLETED",
    )
    db.add(run)
    db.flush()
    validation = ReplayStrategyValidation(
        setup_type="intraday_breakout",
        sample_size=sample_size,
        metrics_json={
            "net_expectancy_r": expectancy,
            "benchmark_excess": expectancy / 2,
            "cost_coverage": 1.0,
            "data_quality_score": 92.0,
            "experimental_stability_score": 70.0,
            "strategy_fingerprint": spec.fingerprint,
            "executable_strategy": spec.to_payload(),
        },
        overfitting_score=15.0,
        verdict="NEEDS_MORE_EVIDENCE",
        explanation="fixture",
        created_at=datetime.utcnow(),
    )
    db.add(validation)
    db.flush()
    db.add(
        StrategyCandidateVariant(
            factory_run_id=run.id,
            validation_id=validation.id,
            fingerprint=spec.fingerprint,
            family="intraday_scalping",
            setup_type="intraday_breakout",
            timeframe_stack=list(spec.required_timeframes),
            specification_json={
                "evidence_binding": "hyperbolic_replay_v1",
                "strategy_fingerprint": spec.fingerprint,
                "executable_strategy": spec.to_payload(),
            },
            lifecycle_state="AWAITING_EVIDENCE",
            final_verdict="NEEDS_MORE_EVIDENCE",
        )
    )
    db.commit()
    return spec


def test_frontier_prioritizes_positive_candidate_closest_to_promotion() -> None:
    with setup_db() as db:
        near = add_candidate(db, target_r=2.0, sample_size=280, expectancy=0.18)
        far = add_candidate(db, target_r=2.5, sample_size=20, expectancy=0.02)

        snapshot = StrategyPromotionFrontierService(minimum_samples=300).snapshot(db)

    assert snapshot["candidates"][0]["strategy_fingerprint"] == near.fingerprint
    assert snapshot["candidates"][0]["sample_gap"] == 20
    assert snapshot["candidates"][1]["strategy_fingerprint"] == far.fingerprint
    assert "INSUFFICIENT_SAMPLE" in snapshot["candidates"][0]["blockers"]


def test_research_specs_preserve_exploration_beside_near_frontier_candidate() -> None:
    with setup_db() as db:
        near = add_candidate(db, target_r=2.0, sample_size=280, expectancy=0.18)
        add_candidate(db, target_r=2.5, sample_size=120, expectancy=-0.08)
        add_candidate(db, target_r=3.0, sample_size=5, expectancy=0.0)

        result = StrategyPromotionFrontierService(minimum_samples=300).research_plan(db, limit=2, seed=7)

    assert result["specs"][0]["strategy_fingerprint"] == near.fingerprint
    assert len(result["specs"]) == 2
    assert result["selection_mix"]["near_frontier"] == 1
    assert result["selection_mix"]["broad_exploration"] == 1
