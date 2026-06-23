from app.services.learning_intelligence import (
    benchmark_result_label,
    classify_trading_power_score,
    self_improvement_action_from_weakness,
    statistical_confidence_label,
    truth_panel_from_payload,
    weakness_from_metric,
)


def test_trading_power_score_classification():
    assert classify_trading_power_score(12) == "Not usable"
    assert classify_trading_power_score(38) == "Weak / experimental"
    assert classify_trading_power_score(55) == "Learning but not reliable"
    assert classify_trading_power_score(70) == "Promising research system"
    assert classify_trading_power_score(81) == "Strong paper-trading evidence"
    assert classify_trading_power_score(91) == "Advanced alpha research candidate"
    assert classify_trading_power_score(98) == "Exceptional, requires external validation"


def test_benchmark_label_blocks_tiny_samples():
    assert benchmark_result_label(12.0, 12) == "insufficient_sample"
    assert benchmark_result_label(None, 120) == "insufficient_sample"
    assert benchmark_result_label(-3.2, 160) == "underperforming"
    assert benchmark_result_label(4.4, 160) == "outperforming"
    assert benchmark_result_label(0.2, 160) == "similar"


def test_statistical_confidence_requires_live_and_coverage():
    assert statistical_confidence_label(12, 0, {"tickers": 2, "regimes": 1}) == "very low evidence"
    assert statistical_confidence_label(80, 0, {"tickers": 12, "regimes": 4}) == "low evidence"
    assert statistical_confidence_label(180, 0, {"tickers": 12, "regimes": 4}) == "medium evidence"
    assert statistical_confidence_label(500, 15, {"tickers": 20, "regimes": 5}) == "strong evidence"


def test_weakness_map_detects_missed_entry_problem():
    metric = {
        "scope_id": "momentum_breakout",
        "trades_count": 120,
        "missed_entry_rate": 0.42,
        "stop_hit_rate": 0.25,
        "expectancy_r": 0.1,
        "benchmark_excess": 0.4,
        "trade_quality_score": 61,
        "intelligence_growth_score": 52,
    }
    row = weakness_from_metric("setup", metric)
    assert row["priority"] in {"medium", "high"}
    assert "missed-entry" in row["main_problem"]
    assert row["affected_module"] == "EntryExitEngine"


def test_self_improvement_action_is_reversible_proposal():
    weakness = {
        "dimension": "setup",
        "entity": "momentum_breakout",
        "sample_size": 120,
        "main_problem": "High missed-entry rate in setup=momentum breakout.",
        "recommended_action": "Test pullback-retest entry logic.",
        "affected_module": "EntryExitEngine",
        "priority": "high",
        "evidence": {"intelligence_growth_score": 52},
    }
    action = self_improvement_action_from_weakness(weakness)
    assert action["status"] == "proposed"
    assert action["notes_json"]["reversible"] is True
    assert action["notes_json"]["source_code_self_modification"] is False
    assert action["affected_module"] == "EntryExitEngine"


def test_truth_panel_says_underperforming_when_benchmark_beats_blum():
    rows = truth_panel_from_payload(
        42.0,
        "Learning but not reliable",
        [],
        [{"benchmark_name": "SPY", "result_label": "underperforming", "excess_return": -4.2}],
        {"missed_entry_rate": 0.1},
        {"trades_count": 0},
    )
    assert any("underperforming SPY" in item for item in rows)
    assert any("Live paper evidence is not mature" in item for item in rows)
