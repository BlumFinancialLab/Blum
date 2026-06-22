from types import SimpleNamespace

from app.services.trade_transparency import (
    outcome_label_for,
    pnl_per_share_for,
    price_return_pct,
    reality_check_payload,
    trade_quality_components,
)


def fake_trade(**kwargs):
    defaults = {
        "decision_state": "active_setup",
        "setup_type": "momentum_breakout",
        "entry_price": 100.0,
        "exit_price": 108.0,
        "entry_trigger": "close above resistance",
        "entry_reason": "paper setup generated from point-in-time simulation",
        "position_size": 0.5,
        "risk_amount": 1.0,
        "risk_percent": 1.0,
        "invalidation_level": 98.0,
        "stop_loss": 98.0,
        "realized_r_multiple": 2.0,
        "realized_pl": 2.0,
        "net_pnl_eur": 2.0,
        "capital_before": 100.0,
        "capital_after": 102.0,
        "max_favorable_excursion": 8.0,
        "max_adverse_excursion": -1.0,
        "stop_hit": False,
        "target_hit": True,
        "exit_reason": "target proxy reached",
        "missed_entry": False,
        "false_breakout": False,
        "reproducibility_score": 78.0,
        "trade_quality_score": 72.0,
        "confidence_at_entry": 62.0,
        "thesis_id": 10,
        "market_regime_at_entry": "risk_on",
        "sector": "Technology",
        "ticker": "TEST",
        "timeframe": "daily",
        "exit_date": "2024-01-15",
        "holding_days": 12,
        "excess_return_vs_benchmark": 3.0,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_outcome_label_distinguishes_target_stop_and_no_trade():
    assert outcome_label_for(fake_trade(target_hit=True, realized_r_multiple=1.4), None) == "target_hit"
    assert outcome_label_for(fake_trade(stop_hit=True, target_hit=False, realized_r_multiple=-1.0), None) == "stopped_out"
    assert outcome_label_for(fake_trade(decision_state="avoid", target_hit=False, realized_r_multiple=0.0), None) == "no_trade_correct"


def test_pnl_per_share_uses_entry_and_exit_prices():
    assert pnl_per_share_for(fake_trade(entry_price=42.0, exit_price=45.5)) == 3.5


def test_benchmark_excess_uses_same_period_asset_return():
    assert price_return_pct(100.0, 110.0) == 10.0
    excess = price_return_pct(100.0, 110.0) - 4.0
    assert excess == 6.0


def test_trade_quality_penalizes_lucky_profit_with_bad_process():
    poor = fake_trade(entry_trigger="", invalidation_level=None, stop_loss=None, reproducibility_score=28.0, net_pnl_eur=3.0, realized_pl=3.0)
    components = trade_quality_components(poor)
    assert components["entry_quality"] < 55
    assert components["rule_compliance"] < 70
    assert components["luck_factor"] > 0


def test_losing_trade_can_still_have_acceptable_process_quality():
    controlled_loss = fake_trade(realized_r_multiple=-1.0, net_pnl_eur=-1.0, realized_pl=-1.0, target_hit=False, stop_hit=True)
    components = trade_quality_components(controlled_loss)
    assert components["entry_quality"] >= 60
    assert components["sizing_quality"] >= 80
    assert components["rule_compliance"] >= 80


def test_reality_check_warns_on_small_high_profit_factor_sample():
    game = SimpleNamespace(id=1, profit_factor=5.0, max_drawdown=-0.5)
    trades = [
        fake_trade(ticker=f"T{i}", sector="Tech", market_regime_at_entry="risk_on", net_pnl_eur=10.0 if i == 0 else 0.2)
        for i in range(8)
    ]
    payload = reality_check_payload(game, trades)
    assert "insufficient_sample_size" in payload["warnings"]
    assert "high_profit_factor_low_sample" in payload["warnings"]
    assert "profit_concentrated_in_few_trades" in payload["warnings"]
    assert payload["statistical_confidence"] == "low"
