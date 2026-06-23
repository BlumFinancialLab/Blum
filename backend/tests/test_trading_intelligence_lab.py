from datetime import datetime
from types import SimpleNamespace

from app.services.trading_intelligence_lab import (
    cycle_stats,
    ledger_summary,
    live_candidate_is_actionable,
    metric_payload,
)


def fake_trade(**kwargs):
    defaults = {
        "id": 1,
        "ticker": "NVDA",
        "setup_type": "momentum_breakout",
        "decision_state": "active_setup",
        "outcome_label": "target_hit",
        "mode": "historical_simulation",
        "capital_cycle_id": 7,
        "entry_date": datetime(2024, 1, 2).date(),
        "exit_date": datetime(2024, 1, 12).date(),
        "entry_price": 100.0,
        "exit_price": 108.0,
        "position_size": 0.5,
        "net_pnl_eur": 4.0,
        "realized_pl": 4.0,
        "pnl_per_share": 8.0,
        "realized_r_multiple": 2.0,
        "capital_before": 100.0,
        "capital_after": 104.0,
        "holding_days": 10,
        "trade_quality_score": 76.0,
        "reproducibility_score": 82.0,
        "market_regime_at_entry": "risk_on",
        "sector": "Technology",
        "benchmark_return_same_period": 2.0,
        "excess_return_vs_benchmark": 6.0,
        "risk_percent": 1.0,
        "created_at": datetime(2024, 1, 12),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def fake_cycle(**kwargs):
    defaults = {
        "id": 1,
        "game_id": 1,
        "cycle_number": 1,
        "started_at": datetime(2024, 1, 1),
        "ended_at": datetime(2024, 2, 1),
        "start_capital": 100.0,
        "target_capital": 10000.0,
        "final_capital": 10000.0,
        "status": "target_reached",
        "reached_target": True,
        "went_to_zero": False,
        "return_percent": 9900.0,
        "max_drawdown": -4.0,
        "trades_count": 20,
        "wins": 13,
        "losses": 5,
        "missed_entries": 2,
        "target_hits": 9,
        "stop_hits": 4,
        "no_trade_correct": 3,
        "no_trade_missed_opportunity": 1,
        "profit_factor": 2.1,
        "expectancy_r": 0.42,
        "benchmark_return": 8.0,
        "excess_return_vs_benchmark": 84.0,
        "best_trade_id": 10,
        "worst_trade_id": 11,
        "failure_reason": None,
        "success_reason": "target reached",
        "lessons_json": {},
        "updated_at": datetime(2024, 2, 1),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_advanced_ledger_summary_counts_trade_outcomes_and_best_worst():
    rows = [
        fake_trade(id=1, ticker="NVDA", net_pnl_eur=4.0, realized_pl=4.0, realized_r_multiple=2.0),
        fake_trade(id=2, ticker="AMD", outcome_label="stopped_out", net_pnl_eur=-1.0, realized_pl=-1.0, realized_r_multiple=-1.0, target_hit=False),
        fake_trade(id=3, ticker="MSFT", outcome_label="missed_entry", net_pnl_eur=0.0, realized_pl=0.0, realized_r_multiple=0.0),
        fake_trade(id=4, ticker="SPY", decision_state="avoid", outcome_label="no_trade_correct", net_pnl_eur=0.0, realized_pl=0.0, realized_r_multiple=0.0),
    ]
    summary = ledger_summary(rows)

    assert summary["total_trades"] == 4
    assert summary["wins"] == 1
    assert summary["losses"] == 1
    assert summary["missed_entries"] == 1
    assert summary["stop_hits"] == 1
    assert summary["no_trade_correct"] == 1
    assert summary["best_trade"]["ticker"] == "NVDA"
    assert summary["worst_trade"]["ticker"] == "AMD"
    assert summary["sample_size_warning"] is True


def test_trading_intelligence_metrics_separate_wins_losses_and_missed_entries():
    rows = [
        fake_trade(id=1, outcome_label="target_hit", realized_r_multiple=2.0, net_pnl_eur=2.0, realized_pl=2.0),
        fake_trade(id=2, outcome_label="stopped_out", realized_r_multiple=-1.0, net_pnl_eur=-1.0, realized_pl=-1.0),
        fake_trade(id=3, outcome_label="missed_entry", realized_r_multiple=0.0, net_pnl_eur=0.0, realized_pl=0.0),
        fake_trade(id=4, decision_state="avoid", outcome_label="no_trade_correct", realized_r_multiple=0.0, net_pnl_eur=0.0, realized_pl=0.0),
    ]
    metrics = metric_payload(rows, scope="game", scope_id="1", window_type="all", window_size=None)

    assert metrics["trades_count"] == 4
    assert metrics["win_rate"] == 0.5
    assert metrics["loss_rate"] == 0.5
    assert metrics["missed_entry_rate"] == 0.25
    assert metrics["target_hit_rate"] == 0.5
    assert metrics["stop_hit_rate"] == 0.5
    assert metrics["expectancy_r"] == 0.5
    assert "too_few_trades" in metrics["notes_json"]["warnings"]


def test_capital_cycle_stats_count_target_and_bankruptcy_cycles():
    rows = [
        fake_cycle(id=1, cycle_number=1, reached_target=True, went_to_zero=False, status="target_reached", return_percent=9900.0),
        fake_cycle(id=2, cycle_number=2, reached_target=False, went_to_zero=True, status="bankrupt", final_capital=0.0, return_percent=-100.0),
        fake_cycle(id=3, cycle_number=3, reached_target=False, went_to_zero=False, status="active", ended_at=None, return_percent=12.0),
    ]
    stats = cycle_stats(rows)

    assert stats["cycles"] == 3
    assert stats["target_cycles_completed"] == 1
    assert stats["bankrupt_cycles"] == 1
    assert stats["active_cycles"] == 1
    assert stats["target_hit_rate"] == 0.5
    assert stats["survival_rate"] == 0.5
    assert stats["best_cycle"]["cycle_number"] == 1
    assert stats["worst_cycle"]["cycle_number"] == 2


def test_live_candidate_requires_actionable_state_and_real_price():
    actionable = {
        "ticker": "NVDA",
        "actionability": "active_setup",
        "price_context": {"latest_price": 900.0},
    }
    no_price = {
        "ticker": "NVDA",
        "actionability": "active_setup",
        "price_context": {"latest_price": None},
    }
    wait_only = {
        "ticker": "NVDA",
        "actionability": "watch",
        "price_context": {"latest_price": 900.0},
    }

    assert live_candidate_is_actionable(actionable) is True
    assert live_candidate_is_actionable(no_price) is False
    assert live_candidate_is_actionable(wait_only) is False
