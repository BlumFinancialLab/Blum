from __future__ import annotations

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import ForexLearningEvidence, ForexPolicyState, ForexPolicyUpdate
from app.services.forex_reinforcement import ForexReinforcementPolicyService


def make_db():
    engine = create_engine("sqlite:///:memory:", future=True)
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def evidence(db, *, reward: float, outcome: str = "WIN") -> ForexLearningEvidence:
    row = ForexLearningEvidence(
        strategy_id="forex-exploration-bootstrap-v1",
        pair="EURUSD=X",
        session="LONDON",
        regime="trend",
        setup_family="momentum_breakout",
        direction="LONG",
        outcome=outcome,
        realized_result=reward,
        lesson="Observed terminal paper outcome.",
        evidence_strength=0.8,
        payload_json={
            "reinforcement_reward_r": reward,
            "policy_update_eligible": True,
            "reward_policy": "net_r_plus_bounded_benchmark_excess_v1",
        },
    )
    db.add(row)
    db.flush()
    return row


def test_policy_update_is_idempotent_and_auditable():
    db = make_db()
    row = evidence(db, reward=0.8)
    service = ForexReinforcementPolicyService()

    first = service.observe(db, row)
    second = service.observe(db, row)

    state = db.scalar(select(ForexPolicyState))
    assert first["status"] == "UPDATED"
    assert second["status"] == "ALREADY_APPLIED"
    assert state.sample_size == 1
    assert db.query(ForexPolicyUpdate).count() == 1


def test_policy_requires_samples_before_influencing_confidence():
    db = make_db()
    service = ForexReinforcementPolicyService()
    for _ in range(29):
        service.observe(db, evidence(db, reward=0.8))

    state = db.scalar(select(ForexPolicyState))
    assert state.sample_size == 29
    assert state.evidence_grade == "LEARNING_ONLY"
    assert state.confidence_adjustment == 0.0

    service.observe(db, evidence(db, reward=0.8))
    db.refresh(state)
    assert state.sample_size == 30
    assert state.evidence_grade == "POLICY_ELIGIBLE"
    assert 0.0 < state.confidence_adjustment <= 0.08


def test_policy_ignores_non_terminal_or_unscored_evidence():
    db = make_db()
    row = evidence(db, reward=0.0, outcome="CORRECT_NO_TRADE")
    row.payload_json = {"policy_update_eligible": False}

    result = ForexReinforcementPolicyService().observe(db, row)

    assert result["status"] == "SKIPPED"
    assert db.query(ForexPolicyState).count() == 0


def test_policy_replays_stored_evidence_incrementally_and_idempotently():
    db = make_db()
    for reward in (0.8, -0.4, 1.2):
        evidence(db, reward=reward, outcome="WIN" if reward > 0 else "LOSS")
    service = ForexReinforcementPolicyService()

    first = service.replay_pending(db, limit=2)
    second = service.replay_pending(db, limit=2)
    third = service.replay_pending(db, limit=2)

    assert first == {"status": "UPDATED", "processed": 2, "remaining_hint": True}
    assert second == {"status": "UPDATED", "processed": 1, "remaining_hint": False}
    assert third == {"status": "IDLE", "processed": 0, "remaining_hint": False}
    assert db.query(ForexPolicyUpdate).count() == 3
    assert db.scalar(select(ForexPolicyState)).sample_size == 3
