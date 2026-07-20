from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.executable_strategy import ExecutableStrategySpec, StrategySignalEvaluator


START = datetime(2026, 1, 5, 14, 0)


def bar(index: int, close: float, *, volume: float = 1_000_000, minutes: int = 1):
    return SimpleNamespace(
        bar_timestamp=START + timedelta(minutes=index * minutes),
        open=close - 0.1,
        high=close + 0.3,
        low=close - 0.4,
        close=close,
        volume=volume,
    )


def payload(**overrides) -> dict:
    value = {
        "schema_version": "executable-strategy-v1",
        "family": "intraday_scalping",
        "setup_type": "intraday_breakout",
        "required_timeframes": ["1d", "15m", "5m", "1m"],
        "execution_timeframe": "1m",
        "entry_rule": "breakout_close",
        "lookback": 10,
        "minimum_relative_volume": 1.2,
        "higher_timeframe_min_trend": 0.0,
        "atr_period": 14,
        "stop_atr_multiple": 1.5,
        "minimum_stop_percent": 0.002,
        "target_r_multiple": 2.0,
        "trailing_atr_multiple": 1.2,
        "maximum_holding_bars": 30,
        "regime_filter": "all",
        "market_filter": "all",
    }
    value.update(overrides)
    return value


def aligned_bars(*, final_close: float = 112.0, final_volume: float = 2_000_000) -> dict:
    one_minute = [bar(index, 100.0 + index * 0.2) for index in range(20)]
    one_minute.append(bar(20, final_close, volume=final_volume))
    return {
        "1d": [bar(index - 20, 100.0 + index, minutes=1440) for index in range(21)],
        "15m": [bar(index - 20, 100.0 + index * 0.5, minutes=15) for index in range(21)],
        "5m": [bar(index - 20, 100.0 + index * 0.3, minutes=5) for index in range(21)],
        "1m": one_minute,
    }


def test_strategy_fingerprint_changes_when_executable_parameter_changes():
    first = ExecutableStrategySpec.from_payload(payload(lookback=10))
    second = ExecutableStrategySpec.from_payload(payload(lookback=20))

    assert first.fingerprint != second.fingerprint
    assert first.to_payload()["lookback"] == 10
    assert second.to_payload()["lookback"] == 20


def test_unsupported_entry_rule_is_rejected_instead_of_counted_as_strategy():
    with pytest.raises(ValueError, match="unsupported entry rule"):
        ExecutableStrategySpec.from_payload(payload(entry_rule="marketing_label_only"))


def test_point_in_time_breakout_requires_volume_and_higher_timeframe_alignment():
    spec = ExecutableStrategySpec.from_payload(payload())
    evaluator = StrategySignalEvaluator()

    triggered = evaluator.evaluate(spec, aligned_bars(), as_of=START + timedelta(minutes=20))
    weak_volume = evaluator.evaluate(
        spec,
        aligned_bars(final_volume=900_000),
        as_of=START + timedelta(minutes=20),
    )

    assert triggered.status == "triggered"
    assert triggered.reason_code == "ENTRY_TRIGGERED"
    assert triggered.relative_volume >= 1.2
    assert weak_volume.status == "waiting"
    assert weak_volume.reason_code == "RELATIVE_VOLUME_BELOW_THRESHOLD"


def test_evaluator_ignores_bars_after_as_of_timestamp():
    spec = ExecutableStrategySpec.from_payload(payload(minimum_relative_volume=0.0))
    bars = aligned_bars(final_close=102.0)
    bars["1m"].append(bar(21, 150.0, volume=5_000_000))

    result = StrategySignalEvaluator().evaluate(
        spec,
        bars,
        as_of=START + timedelta(minutes=20),
    )

    assert result.status == "waiting"
    assert result.reason_code == "ENTRY_NOT_TRIGGERED"
    assert result.decision_timestamp == START + timedelta(minutes=20)


def test_trade_geometry_uses_strategy_atr_stop_and_target_r():
    spec = ExecutableStrategySpec.from_payload(
        payload(stop_atr_multiple=2.0, minimum_stop_percent=0.001, target_r_multiple=2.5)
    )
    history = aligned_bars()["1m"]

    geometry = StrategySignalEvaluator().geometry(spec, entry_price=112.0, execution_history=history)

    expected_distance = max(geometry.atr * 2.0, 112.0 * 0.001)
    assert geometry.stop_price == pytest.approx(112.0 - expected_distance)
    assert geometry.target_price == pytest.approx(112.0 + expected_distance * 2.5)
    assert geometry.risk_distance == pytest.approx(expected_distance)
