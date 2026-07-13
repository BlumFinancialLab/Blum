from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math


REPLAY_EVIDENCE = "REPLAY_EVIDENCE"
WALK_FORWARD_EVIDENCE = "WALK_FORWARD_EVIDENCE"
PAPER_FORWARD_EVIDENCE = "PAPER_FORWARD_EVIDENCE"
INTRADAY_FORWARD_EVIDENCE = "INTRADAY_FORWARD_EVIDENCE"

FORWARD_FAILURE_STATUSES = {"FORWARD_FAILURE", "HIGH_DECAY"}
READY_STATUSES = {"COPY_READY_PAPER_ONLY", "COPY_READY_HIGH_CONFIDENCE"}


@dataclass(frozen=True)
class ReadinessThresholds:
    global_forward_trades: int = 100
    strategy_forward_trades: int = 30
    observation_days: int = 90
    max_drawdown: float = 15.0
    max_decay_pct: float = 35.0
    min_tickers: int = 5
    min_regimes: int = 2
    max_ticker_concentration: float = 0.35
    max_market_concentration: float = 0.70
    high_confidence_global_forward_trades: int = 300
    high_confidence_strategy_forward_trades: int = 100
    high_confidence_observation_days: int = 180
    high_confidence_max_drawdown: float = 12.0
    high_confidence_max_decay_pct: float = 25.0
    high_confidence_min_tickers: int = 8
    high_confidence_min_regimes: int = 3
    high_confidence_max_ticker_concentration: float = 0.30
    high_confidence_max_market_concentration: float = 0.60
    capital_global_forward_trades: int = 500
    capital_strategy_forward_trades: int = 150
    capital_observation_days: int = 270
    capital_max_drawdown: float = 10.0
    capital_max_decay_pct: float = 20.0
    capital_min_tickers: int = 10
    capital_min_regimes: int = 3
    capital_max_ticker_concentration: float = 0.30
    capital_max_market_concentration: float = 0.60


@dataclass(frozen=True)
class EvidenceProvenance:
    """Immutable metadata that identifies one persisted evidence projection."""

    canonical_evidence_class: str | None = None
    source_projection_id: str | None = None
    strategy_identity: str | None = None
    horizon: str | None = None
    terminal: bool = False
    closed_count: int | None = None


@dataclass(frozen=True)
class ForwardEvidenceProvenance(EvidenceProvenance):
    """A class-specific closed paper-forward projection eligible for maturity."""

    compatible_with_replay: bool = False


@dataclass(frozen=True)
class ReadinessContext:
    replay_sample: int | None = None
    global_forward_sample: int | None = None
    forward_sample: int | None = None
    replay_evidence: EvidenceProvenance | None = None
    strategy_forward_evidence: ForwardEvidenceProvenance | None = None
    global_forward_evidence: tuple[ForwardEvidenceProvenance, ...] = ()
    observation_days: int | None = None
    net_expectancy: float | None = None
    benchmark_excess: float | None = None
    max_drawdown: float | None = None
    decay_status: str = "INSUFFICIENT_EVIDENCE"
    decay_pct: float | None = None
    ticker_count: int | None = None
    regime_count: int | None = None
    ticker_concentration: float | None = None
    market_concentration: float | None = None
    costs_available: bool = False
    slippage_available: bool = False
    data_quality_available: bool = False
    previous_status: str | None = None


@dataclass(frozen=True)
class ReadinessDecision:
    status: str
    maturity_score: float
    passed_gates: tuple[str, ...]
    failed_gates: tuple[str, ...]
    blockers: tuple[str, ...]
    next_milestone: str | None


def canonical_evidence_class(value: str | None, trading_mode: str | None = None) -> str | None:
    """Map current and legacy evidence labels to a single projection class."""

    normalized_value = _normalized_label(value)
    aliases = {
        REPLAY_EVIDENCE: REPLAY_EVIDENCE,
        "REPLAY": REPLAY_EVIDENCE,
        WALK_FORWARD_EVIDENCE: WALK_FORWARD_EVIDENCE,
        "WALK_FORWARD": WALK_FORWARD_EVIDENCE,
        "WALKFORWARD": WALK_FORWARD_EVIDENCE,
        PAPER_FORWARD_EVIDENCE: PAPER_FORWARD_EVIDENCE,
        "PAPER_FORWARD": PAPER_FORWARD_EVIDENCE,
        "PAPER_FORWARD_INTRADAY": INTRADAY_FORWARD_EVIDENCE,
        INTRADAY_FORWARD_EVIDENCE: INTRADAY_FORWARD_EVIDENCE,
        "INTRADAY_PAPER_FORWARD": INTRADAY_FORWARD_EVIDENCE,
    }
    if normalized_value in aliases:
        return aliases[normalized_value]

    normalized_mode = _normalized_label(trading_mode)
    if "INTRADAY" in normalized_mode:
        return INTRADAY_FORWARD_EVIDENCE
    if "PAPER" in normalized_mode and "FORWARD" in normalized_mode:
        return PAPER_FORWARD_EVIDENCE
    if "WALK" in normalized_mode and "FORWARD" in normalized_mode:
        return WALK_FORWARD_EVIDENCE
    return None


def wilson_interval(wins: int, sample_size: int) -> dict[str, float] | None:
    """Return a two-sided 95 percent Wilson interval for a non-empty sample."""

    total = max(0, _integer(sample_size))
    if total == 0:
        return None
    successes = min(total, max(0, _integer(wins)))
    point_estimate = successes / total
    z = 1.96
    z_squared = z * z
    denominator = 1 + z_squared / total
    center = (point_estimate + z_squared / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt((point_estimate * (1 - point_estimate) + z_squared / (4 * total)) / total)
        / denominator
    )
    return {
        "point_estimate": point_estimate,
        "lower": max(0.0, center - margin),
        "upper": min(1.0, center + margin),
    }


def concentration(values: list[str]) -> dict[str, float | str | None]:
    """Summarize categorical concentration without treating no data as zero risk."""

    normalized_values = [str(value).strip() for value in values if str(value or "").strip()]
    if not normalized_values:
        return {"top_value": None, "top_share": None, "distinct_count": 0}
    counts = Counter(normalized_values)
    top_value, top_count = min(counts.items(), key=lambda item: (-item[1], item[0]))
    return {
        "top_value": top_value,
        "top_share": top_count / len(normalized_values),
        "distinct_count": len(counts),
    }


def evaluate_decay(replay: dict | None, forward: dict | None, thresholds: ReadinessThresholds) -> dict:
    """Compare compatible replay and forward projections without combining them."""

    replay = replay or {}
    forward = forward or {}
    if not _has_compatible_decay_provenance(replay, forward):
        return _insufficient_decay_result(replay, forward)

    replay_expectancy = _number(replay.get("net_expectancy", replay.get("expectancy")))
    forward_expectancy = _number(forward.get("net_expectancy", forward.get("expectancy")))
    replay_profit_factor = _number(replay.get("profit_factor"))
    forward_profit_factor = _number(forward.get("profit_factor"))
    replay_sharpe = _number(replay.get("sharpe_proxy"))
    forward_sharpe = _number(forward.get("sharpe_proxy"))
    replay_drawdown = _number(replay.get("max_drawdown"))
    forward_drawdown = _number(forward.get("max_drawdown"))
    replay_costs = _number(replay.get("total_costs"))
    forward_costs = _number(forward.get("total_costs"))
    signal_failure_rate = _number(forward.get("signal_failure_rate"))
    cost_gap = forward_costs - replay_costs if forward_costs is not None and replay_costs is not None else None

    decay_pct = None
    if replay_expectancy is not None and forward_expectancy is not None and replay_expectancy > 0:
        decay_pct = (replay_expectancy - forward_expectancy) / abs(replay_expectancy) * 100

    if forward_expectancy is not None and forward_expectancy <= 0:
        status = "FORWARD_FAILURE"
    elif forward_profit_factor is not None and forward_profit_factor <= 0:
        status = "FORWARD_FAILURE"
    elif decay_pct is None:
        status = "INSUFFICIENT_EVIDENCE"
    elif decay_pct > thresholds.max_decay_pct:
        status = "HIGH_DECAY"
    elif decay_pct > thresholds.max_decay_pct / 2:
        status = "MODERATE_DECAY"
    else:
        status = "CONSISTENT"

    return {
        "status": status,
        "replay_expectancy": replay_expectancy,
        "forward_expectancy": forward_expectancy,
        "replay_profit_factor": replay_profit_factor,
        "forward_profit_factor": forward_profit_factor,
        "replay_sharpe_proxy": replay_sharpe,
        "forward_sharpe_proxy": forward_sharpe,
        "replay_max_drawdown": replay_drawdown,
        "forward_max_drawdown": forward_drawdown,
        "execution_cost_gap": cost_gap,
        "signal_failure_rate": signal_failure_rate,
        "performance_decay_pct": decay_pct,
    }


def evaluate_copy_readiness(context: ReadinessContext, thresholds: ReadinessThresholds) -> ReadinessDecision:
    """Classify immutable evidence into an explainable paper-copy readiness state."""

    gate_results = _paper_gate_results(context, thresholds)
    passed_gates = tuple(name for name, passed in gate_results if passed)
    failed_gates = tuple(name for name, passed in gate_results if not passed)
    maturity_score = round(100 * len(passed_gates) / len(gate_results), 2)
    forward_sample = _strategy_forward_closed_count(context)

    if forward_sample is None:
        status = "NOT_READY"
    elif forward_sample == 0:
        status = "REPLAY_ONLY" if _count(context.replay_sample) not in (None, 0) else "NOT_READY"
    elif _has_material_forward_failure(context, thresholds):
        status = "SUSPENDED"
    elif not failed_gates:
        status = "COPY_READY_HIGH_CONFIDENCE" if _high_confidence_ready(context, thresholds) else "COPY_READY_PAPER_ONLY"
    elif context.previous_status in READY_STATUSES:
        status = "DEGRADED"
    elif forward_sample < 10:
        status = "FORWARD_EVIDENCE_LOW"
    else:
        status = "FORWARD_EVIDENCE_GROWING"

    return ReadinessDecision(
        status=status,
        maturity_score=maturity_score,
        passed_gates=passed_gates,
        failed_gates=failed_gates,
        blockers=failed_gates,
        next_milestone=_next_milestone(status, failed_gates, thresholds),
    )


def evaluate_capital_eligibility(
    context: ReadinessContext,
    decision: ReadinessDecision,
    thresholds: ReadinessThresholds,
) -> str:
    """Return an autonomous research classification; this function has no execution path."""

    if decision.status in {"SUSPENDED", "DEGRADED", "NOT_READY"}:
        return "NOT_ELIGIBLE"
    if decision.status != "COPY_READY_HIGH_CONFIDENCE":
        return "PAPER_ONLY" if decision.status == "COPY_READY_PAPER_ONLY" else "OBSERVE_ONLY"
    if _capital_eligible(context, thresholds):
        return "ELIGIBLE_FOR_LIMITED_EXTERNAL_VALIDATION"
    return "PAPER_ONLY"


def _paper_gate_results(context: ReadinessContext, thresholds: ReadinessThresholds) -> tuple[tuple[str, bool], ...]:
    benchmark = _number(context.benchmark_excess)
    drawdown = _number(context.max_drawdown)
    decay_pct = _number(context.decay_pct)
    global_forward_count = _global_forward_closed_count(context)
    strategy_forward_count = _strategy_forward_closed_count(context)
    observation_days = _count(context.observation_days)
    ticker_count = _count(context.ticker_count)
    regime_count = _count(context.regime_count)
    provenance_gate = _strategy_forward_provenance_gate(context)
    return (
        (
            "global_forward_trades_unavailable" if global_forward_count is None else "global_forward_trades",
            global_forward_count is not None and global_forward_count >= thresholds.global_forward_trades,
        ),
        (
            "strategy_forward_trades_unavailable" if strategy_forward_count is None else "strategy_forward_trades",
            strategy_forward_count is not None and strategy_forward_count >= thresholds.strategy_forward_trades,
        ),
        provenance_gate,
        (
            "observation_days_unavailable" if observation_days is None else "observation_days",
            observation_days is not None and observation_days >= thresholds.observation_days,
        ),
        ("net_expectancy_positive", _number(context.net_expectancy) is not None and _number(context.net_expectancy) > 0),
        (
            "benchmark_excess_unavailable" if benchmark is None else "benchmark_excess_positive",
            benchmark is not None and benchmark > 0,
        ),
        ("max_drawdown_unavailable" if drawdown is None else "max_drawdown", drawdown is not None and abs(drawdown) <= thresholds.max_drawdown),
        (
            "decay_unavailable" if decay_pct is None else "replay_forward_decay",
            _has_compatible_context_provenance(context)
            and decay_pct is not None
            and context.decay_status not in FORWARD_FAILURE_STATUSES
            and decay_pct <= thresholds.max_decay_pct,
        ),
        (
            "ticker_count_unavailable" if ticker_count is None else "ticker_count",
            ticker_count is not None and ticker_count >= thresholds.min_tickers,
        ),
        (
            "regime_count_unavailable" if regime_count is None else "regime_count",
            regime_count is not None and regime_count >= thresholds.min_regimes,
        ),
        (
            "ticker_concentration_unavailable" if context.ticker_concentration is None else "ticker_concentration",
            context.ticker_concentration is not None and context.ticker_concentration <= thresholds.max_ticker_concentration,
        ),
        (
            "market_concentration_unavailable" if context.market_concentration is None else "market_concentration",
            context.market_concentration is not None and context.market_concentration <= thresholds.max_market_concentration,
        ),
        ("costs_unavailable", context.costs_available),
        ("slippage_unavailable", context.slippage_available),
        ("data_quality_unavailable", context.data_quality_available),
    )


def _has_material_forward_failure(context: ReadinessContext, thresholds: ReadinessThresholds) -> bool:
    expectancy = _number(context.net_expectancy)
    benchmark = _number(context.benchmark_excess)
    drawdown = _number(context.max_drawdown)
    decay_pct = _number(context.decay_pct)
    return (
        (expectancy is not None and expectancy <= 0)
        or (benchmark is not None and benchmark < 0)
        or (drawdown is not None and abs(drawdown) > thresholds.max_drawdown)
        or context.decay_status in FORWARD_FAILURE_STATUSES
        or (decay_pct is not None and decay_pct > thresholds.max_decay_pct)
    )


def _high_confidence_ready(context: ReadinessContext, thresholds: ReadinessThresholds) -> bool:
    global_forward_count = _global_forward_closed_count(context)
    strategy_forward_count = _strategy_forward_closed_count(context)
    observation_days = _count(context.observation_days)
    ticker_count = _count(context.ticker_count)
    regime_count = _count(context.regime_count)
    return (
        _has_compatible_context_provenance(context)
        and global_forward_count is not None
        and global_forward_count >= thresholds.high_confidence_global_forward_trades
        and strategy_forward_count is not None
        and strategy_forward_count >= thresholds.high_confidence_strategy_forward_trades
        and observation_days is not None
        and observation_days >= thresholds.high_confidence_observation_days
        and _number(context.max_drawdown) is not None
        and abs(_number(context.max_drawdown)) <= thresholds.high_confidence_max_drawdown
        and _number(context.decay_pct) is not None
        and _number(context.decay_pct) <= thresholds.high_confidence_max_decay_pct
        and ticker_count is not None
        and ticker_count >= thresholds.high_confidence_min_tickers
        and regime_count is not None
        and regime_count >= thresholds.high_confidence_min_regimes
        and context.ticker_concentration is not None
        and context.ticker_concentration <= thresholds.high_confidence_max_ticker_concentration
        and context.market_concentration is not None
        and context.market_concentration <= thresholds.high_confidence_max_market_concentration
    )


def _capital_eligible(context: ReadinessContext, thresholds: ReadinessThresholds) -> bool:
    global_forward_count = _global_forward_closed_count(context)
    strategy_forward_count = _strategy_forward_closed_count(context)
    observation_days = _count(context.observation_days)
    ticker_count = _count(context.ticker_count)
    regime_count = _count(context.regime_count)
    return (
        _has_compatible_context_provenance(context)
        and global_forward_count is not None
        and global_forward_count >= thresholds.capital_global_forward_trades
        and strategy_forward_count is not None
        and strategy_forward_count >= thresholds.capital_strategy_forward_trades
        and observation_days is not None
        and observation_days >= thresholds.capital_observation_days
        and _number(context.net_expectancy) is not None
        and _number(context.net_expectancy) > 0
        and _number(context.benchmark_excess) is not None
        and _number(context.benchmark_excess) > 0
        and _number(context.max_drawdown) is not None
        and abs(_number(context.max_drawdown)) <= thresholds.capital_max_drawdown
        and _number(context.decay_pct) is not None
        and _number(context.decay_pct) <= thresholds.capital_max_decay_pct
        and context.decay_status not in FORWARD_FAILURE_STATUSES
        and ticker_count is not None
        and ticker_count >= thresholds.capital_min_tickers
        and regime_count is not None
        and regime_count >= thresholds.capital_min_regimes
        and context.ticker_concentration is not None
        and context.ticker_concentration <= thresholds.capital_max_ticker_concentration
        and context.market_concentration is not None
        and context.market_concentration <= thresholds.capital_max_market_concentration
        and context.costs_available
        and context.slippage_available
        and context.data_quality_available
    )


def _has_compatible_decay_provenance(replay: object, forward: object) -> bool:
    if not isinstance(replay, dict) or not isinstance(forward, dict):
        return False
    replay_evidence = replay.get("provenance")
    forward_evidence = forward.get("provenance")
    return _provenance_pair_is_compatible(replay_evidence, forward_evidence)


def _has_compatible_context_provenance(context: ReadinessContext) -> bool:
    return _provenance_pair_is_compatible(context.replay_evidence, context.strategy_forward_evidence)


def _provenance_pair_is_compatible(
    replay_evidence: object,
    forward_evidence: object,
) -> bool:
    if not _is_valid_replay_provenance(replay_evidence):
        return False
    if not _is_valid_forward_provenance(forward_evidence):
        return False
    assert isinstance(replay_evidence, EvidenceProvenance)
    assert isinstance(forward_evidence, ForwardEvidenceProvenance)
    return (
        forward_evidence.compatible_with_replay is True
        and replay_evidence.strategy_identity == forward_evidence.strategy_identity
        and replay_evidence.horizon == forward_evidence.horizon
    )


def _is_valid_replay_provenance(provenance: object) -> bool:
    if not isinstance(provenance, EvidenceProvenance) or isinstance(provenance, ForwardEvidenceProvenance):
        return False
    return (
        _is_canonical_class(provenance.canonical_evidence_class, {REPLAY_EVIDENCE, WALK_FORWARD_EVIDENCE})
        and _has_identity(provenance.source_projection_id)
        and _has_identity(provenance.strategy_identity)
        and _has_identity(provenance.horizon)
        and provenance.terminal is True
        and _count(provenance.closed_count) is not None
    )


def _is_valid_forward_provenance(provenance: object) -> bool:
    if not isinstance(provenance, ForwardEvidenceProvenance):
        return False
    return (
        _is_canonical_class(
            provenance.canonical_evidence_class,
            {PAPER_FORWARD_EVIDENCE, INTRADAY_FORWARD_EVIDENCE},
        )
        and _has_identity(provenance.source_projection_id)
        and _has_identity(provenance.strategy_identity)
        and _has_identity(provenance.horizon)
        and provenance.terminal is True
        and _count(provenance.closed_count) is not None
    )


def _is_canonical_class(value: str | None, allowed: set[str]) -> bool:
    return value in allowed and canonical_evidence_class(value) == value


def _has_identity(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _strategy_forward_closed_count(context: ReadinessContext) -> int | None:
    provenance = context.strategy_forward_evidence
    if not _is_valid_forward_provenance(provenance):
        return None
    assert provenance is not None
    closed_count = _count(provenance.closed_count)
    reported_count = _count(context.forward_sample)
    if closed_count is None or (context.forward_sample is not None and reported_count != closed_count):
        return None
    return closed_count


def _global_forward_closed_count(context: ReadinessContext) -> int | None:
    evidence = context.global_forward_evidence
    if not evidence:
        return None
    source_ids: set[str] = set()
    total = 0
    for provenance in evidence:
        if not _is_valid_forward_provenance(provenance):
            return None
        assert provenance.source_projection_id is not None
        closed_count = _count(provenance.closed_count)
        if closed_count is None or provenance.source_projection_id in source_ids:
            return None
        source_ids.add(provenance.source_projection_id)
        total += closed_count
    reported_count = _count(context.global_forward_sample)
    if context.global_forward_sample is not None and reported_count != total:
        return None
    return total


def _strategy_forward_provenance_gate(context: ReadinessContext) -> tuple[str, bool]:
    provenance = context.strategy_forward_evidence
    if not isinstance(provenance, ForwardEvidenceProvenance):
        return ("strategy_forward_evidence_unavailable", False)
    if not _is_canonical_class(
        provenance.canonical_evidence_class,
        {PAPER_FORWARD_EVIDENCE, INTRADAY_FORWARD_EVIDENCE},
    ):
        return ("strategy_forward_evidence_class_invalid", False)
    if not _has_identity(provenance.source_projection_id):
        return ("strategy_forward_evidence_source_unavailable", False)
    if provenance.terminal is not True:
        return ("strategy_forward_evidence_not_terminal", False)
    if _count(provenance.closed_count) is None:
        return ("strategy_forward_evidence_count_unavailable", False)
    if not _has_compatible_context_provenance(context):
        return ("replay_forward_incompatible", False)
    return ("forward_evidence_provenance", True)


def _insufficient_decay_result(replay: object, forward: object) -> dict:
    replay_payload = replay if isinstance(replay, dict) else {}
    forward_payload = forward if isinstance(forward, dict) else {}
    return {
        "status": "INSUFFICIENT_EVIDENCE",
        "replay_expectancy": _number(replay_payload.get("net_expectancy", replay_payload.get("expectancy"))),
        "forward_expectancy": _number(forward_payload.get("net_expectancy", forward_payload.get("expectancy"))),
        "replay_profit_factor": _number(replay_payload.get("profit_factor")),
        "forward_profit_factor": _number(forward_payload.get("profit_factor")),
        "replay_sharpe_proxy": _number(replay_payload.get("sharpe_proxy")),
        "forward_sharpe_proxy": _number(forward_payload.get("sharpe_proxy")),
        "replay_max_drawdown": _number(replay_payload.get("max_drawdown")),
        "forward_max_drawdown": _number(forward_payload.get("max_drawdown")),
        "execution_cost_gap": None,
        "signal_failure_rate": _number(forward_payload.get("signal_failure_rate")),
        "performance_decay_pct": None,
    }


def _next_milestone(status: str, failed_gates: tuple[str, ...], thresholds: ReadinessThresholds) -> str | None:
    if status == "COPY_READY_HIGH_CONFIDENCE":
        return None
    if status == "COPY_READY_PAPER_ONLY":
        return f"Reach {thresholds.high_confidence_strategy_forward_trades} strategy forward trades for high confidence."
    if status == "REPLAY_ONLY":
        return "Collect closed terminal forward trades."
    if status == "FORWARD_EVIDENCE_LOW":
        return "Collect at least 10 closed terminal forward trades."
    if status == "SUSPENDED":
        return "Restore positive forward evidence before reassessment."
    if failed_gates:
        return f"Satisfy {failed_gates[0]}."
    return "Collect compatible replay or forward evidence."


def _normalized_label(value: str | None) -> str:
    return str(value or "").strip().upper().replace("-", "_").replace(" ", "_")


def _integer(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
