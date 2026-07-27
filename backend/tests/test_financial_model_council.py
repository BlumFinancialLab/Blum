from __future__ import annotations

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import FinancialModelAdvisor, FinancialModelVote
from app.services.financial_model_council import FinancialModelCouncil


def make_db():
    engine = create_engine("sqlite:///:memory:", future=True)
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_council_registers_models_with_no_direct_trading_authority():
    db = make_db()

    result = FinancialModelCouncil().register(db)

    advisors = db.scalars(select(FinancialModelAdvisor).order_by(FinancialModelAdvisor.advisor_key)).all()
    assert result["registered"] == 5
    assert {row.advisor_key for row in advisors} == {
        "finbert",
        "fingpt",
        "finrobot",
        "finllama",
        "investlm",
    }
    assert all(row.direct_trading_authority is False for row in advisors)
    assert next(row for row in advisors if row.advisor_key == "finbert").execution_mode == "local_cpu"
    assert next(row for row in advisors if row.advisor_key == "finllama").execution_mode == "remote_optional"


def test_council_registration_is_idempotent():
    db = make_db()
    council = FinancialModelCouncil()

    first = council.ensure_registered(db)
    second = council.ensure_registered(db)

    assert first["registered"] == 5
    assert second == {"status": "READY", "registered": 5, "changed": False}
    assert db.query(FinancialModelAdvisor).count() == 5


def test_finrobot_review_persists_structured_vote_without_opening_trade():
    db = make_db()
    council = FinancialModelCouncil()
    council.register(db)

    result = council.review_forex_decision(
        db,
        decision_id=42,
        ticker="EURUSD=X",
        evidence={
            "approved": True,
            "confidence": 0.75,
            "blockers": [],
            "expected_net_pips": 7.5,
            "context_direction": "LONG",
            "price_direction": "LONG",
        },
    )

    vote = db.scalar(select(FinancialModelVote))
    assert result["status"] == "RECORDED"
    assert vote.advisor_key == "finrobot"
    assert vote.vote == "support"
    assert vote.direct_action_allowed is False
    assert vote.evidence_hash


def test_council_outcome_attaches_reward_to_prior_votes():
    db = make_db()
    council = FinancialModelCouncil()
    council.register(db)
    council.review_forex_decision(
        db,
        decision_id=7,
        ticker="GBPUSD=X",
        evidence={
            "approved": True,
            "confidence": 0.7,
            "blockers": [],
            "expected_net_pips": 6.0,
            "context_direction": "SHORT",
            "price_direction": "SHORT",
        },
    )

    result = council.evaluate_outcome(db, decision_id=7, reward_r=-0.6)

    vote = db.scalar(select(FinancialModelVote))
    assert result["votes_evaluated"] == 1
    assert vote.outcome_evaluated is True
    assert vote.reward_contribution == -0.6
    assert vote.was_helpful is False


def test_council_status_is_read_only_and_exposes_runtime_boundaries():
    db = make_db()
    council = FinancialModelCouncil()
    council.register(db)
    before = db.query(FinancialModelAdvisor).count()

    status = council.status(db)

    assert db.query(FinancialModelAdvisor).count() == before
    assert status["direct_trading_authority"] is False
    assert status["advisors"]["finbert"]["runtime_status"] == "CONFIGURED_LOCAL"
    assert status["advisors"]["finllama"]["execution_mode"] == "remote_optional"
    assert status["advisors"]["investlm"]["runtime_status"] == "LICENSE_AND_ENDPOINT_REQUIRED"
