from __future__ import annotations

from app.services.forex_trader import BlumForexTraderCore
from app.services.trading_ml.contracts import TradingMLAdvice
from test_forex_trader_core import NOW, db, market_input, strategy  # noqa: F401


class FakeAdvisor:
    def __init__(self, *, positive: bool):
        self.positive = positive

    def advise(self, *args, **kwargs):
        return TradingMLAdvice(
            status="ACTIVE",
            model_uid="forex-test-champion",
            probability_positive_r=0.9 if self.positive else 0.2,
            predicted_net_r=0.8 if self.positive else -0.5,
            uncertainty=0.1,
            confidence_adjustment=4.0 if self.positive else -4.0,
            veto_recommended=not self.positive,
            explanation=("test evidence",),
            guardrails=("DETERMINISTIC_AUTHORITY",),
        )


def test_forex_model_cannot_remove_stale_data_veto(db):
    core = BlumForexTraderCore()
    core.supervised_advisor = FakeAdvisor(positive=True)
    result = core.run_cycle(
        db,
        inputs=[market_input(stale_1m=True)],
        strategies={"EURUSD=X": strategy()},
        now=NOW,
        cycle_key="stale-supervised",
    )
    assert result["trades_opened"] == 0
    assert "STALE_DATA" in result["blockers"]


def test_validated_negative_forex_model_adds_veto(db):
    core = BlumForexTraderCore()
    core.supervised_advisor = FakeAdvisor(positive=False)
    result = core.run_cycle(
        db,
        inputs=[market_input()],
        strategies={"EURUSD=X": strategy()},
        now=NOW,
        cycle_key="negative-supervised",
    )
    assert result["trades_opened"] == 0
    assert "SUPERVISED_MODEL_NEGATIVE_EDGE" in result["blockers"]


def test_positive_model_is_a_bounded_advisor_not_a_risk_bypass(db):
    core = BlumForexTraderCore()
    core.supervised_advisor = FakeAdvisor(positive=True)
    result = core.run_cycle(
        db,
        inputs=[market_input()],
        strategies={"EURUSD=X": strategy()},
        now=NOW,
        cycle_key="positive-supervised",
    )
    assert result["trades_opened"] == 1
    decision = db.query(__import__("app.models", fromlist=["ForexDecision"]).ForexDecision).one()
    assert decision.proposal_json["supervised_model"]["model_uid"] == "forex-test-champion"
    assert decision.proposal_json["knowledge_context"]["supervised_model"]["combined_contextual_adjustment_points"] <= 10.0
