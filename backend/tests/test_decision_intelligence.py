from types import SimpleNamespace

from app.services.decision_intelligence import (
    classify_decision_superiority,
    concentration_score,
    decision_superiority_components,
    decision_superiority_metrics,
)


def test_decision_superiority_classification():
    assert classify_decision_superiority(15) == "Weak"
    assert classify_decision_superiority(35) == "Experimental"
    assert classify_decision_superiority(55) == "Learning"
    assert classify_decision_superiority(70) == "Competitive"
    assert classify_decision_superiority(84) == "Strong Alpha Research"
    assert classify_decision_superiority(94) == "Exceptional"


def test_decision_metrics_capture_missed_best_opportunity():
    decisions = [
        {
            "selected_outperformed": True,
            "best_available_return": 8.0,
            "selected_return": 6.0,
            "benchmark_return": 2.0,
            "ranking_correct": False,
            "missed_best": True,
        },
        {
            "selected_outperformed": False,
            "best_available_return": 5.0,
            "selected_return": -1.0,
            "benchmark_return": 1.0,
            "ranking_correct": True,
            "missed_best": True,
        },
    ]
    metrics = decision_superiority_metrics(decisions, [])
    assert metrics["total_outperformers"] == 2
    assert metrics["captured_outperformers"] == 1
    assert metrics["opportunity_recall"] == 0.5
    assert metrics["opportunity_precision"] == 0.5
    assert metrics["missed_opportunities"] == 2
    assert 0 < metrics["alpha_capture_rate"] < 1


def test_decision_components_penalize_low_live_validation():
    metrics = {
        "opportunity_recall": 0.5,
        "opportunity_precision": 0.5,
        "alpha_capture_rate": 0.4,
        "ranking_accuracy": 0.5,
        "benchmark_excess": 1.2,
        "status": "ok",
    }
    rows = [
        SimpleNamespace(mode="historical_simulation", market_regime_at_entry="risk_on", reproducibility_score=80, max_adverse_excursion=-2),
        SimpleNamespace(mode="historical_simulation", market_regime_at_entry="risk_on", reproducibility_score=75, max_adverse_excursion=-3),
    ]
    components = decision_superiority_components(metrics, rows)
    assert components["live_validation"] == 0
    assert components["reproducibility"] > 70


def test_concentration_score_reads_top_contributors():
    rows = [
        {"ticker": "A", "return_contribution": 50},
        {"ticker": "B", "return_contribution": 20},
        {"ticker": "C", "return_contribution": 10},
        {"ticker": "D", "return_contribution": 5},
    ]
    assert concentration_score(rows) == 80
