from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import pstdev

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import ExecutionSimulation, HistoricalPrediction, LearningBenchmarkComparison, PredictionOutcome, RMultipleMetric, SignalPerformance, StrategyMemory


APPROVED_FOR_PAPER = "APPROVED_FOR_PAPER"
WATCHLIST_ONLY = "WATCHLIST_ONLY"
REJECTED_NO_EDGE = "REJECTED_NO_EDGE"
REJECTED_INSUFFICIENT_SAMPLE = "REJECTED_INSUFFICIENT_SAMPLE"
REJECTED_BAD_RISK_REWARD = "REJECTED_BAD_RISK_REWARD"
REJECTED_OVERFITTING_RISK = "REJECTED_OVERFITTING_RISK"
REJECTED_BENCHMARK_UNDERPERFORMANCE = "REJECTED_BENCHMARK_UNDERPERFORMANCE"
DATA_BLOCKED = "DATA_BLOCKED"


@dataclass(frozen=True)
class QuantEdgeAssessment:
    verdict: str
    sample_size: int
    win_rate: float | None
    avg_win: float | None
    avg_loss: float | None
    payoff_ratio: float | None
    expectancy: float | None
    profit_factor: float | None
    max_drawdown: float | None
    sharpe: float | None
    sortino: float | None
    benchmark_excess: float | None
    walk_forward_score: float | None
    stability_score: float | None
    overfitting_risk: float
    edge_score: float | None
    evidence_sources: list[str]
    explanation: str

    def to_dict(self) -> dict:
        return asdict(self)


class BlumQuantEdgeAgent:
    def __init__(
        self,
        *,
        min_score: float,
        min_sample_size: int,
        reject_high_overfitting_risk: bool = True,
        min_risk_reward: float = 1.0,
    ):
        self.min_score = float(min_score)
        self.min_sample_size = max(1, int(min_sample_size))
        self.reject_high_overfitting_risk = bool(reject_high_overfitting_risk)
        self.min_risk_reward = float(min_risk_reward)

    def assess(self, db: Session, candidate: dict) -> dict:
        if data_is_blocked(candidate):
            return self._empty(DATA_BLOCKED, "Candidate market data is blocked or incomplete.").to_dict()

        ticker = str(candidate.get("ticker") or "").upper()
        setup_type = str((candidate.get("setup") or {}).get("setup_type") or "unknown")
        metric = db.scalar(
            select(RMultipleMetric)
            .where(RMultipleMetric.setup_type == setup_type)
            .order_by(desc(RMultipleMetric.sample_count), desc(RMultipleMetric.updated_at))
            .limit(1)
        )
        outcomes = list(
            db.scalars(
                select(PredictionOutcome)
                .join(HistoricalPrediction, HistoricalPrediction.id == PredictionOutcome.prediction_id)
                .where(HistoricalPrediction.ticker == ticker)
                .order_by(desc(PredictionOutcome.created_at))
                .limit(250)
            ).all()
        )
        simulations = list(
            db.scalars(
                select(ExecutionSimulation)
                .where(ExecutionSimulation.setup_type == setup_type)
                .order_by(desc(ExecutionSimulation.created_at))
                .limit(250)
            ).all()
        )
        signal = db.scalar(
            select(SignalPerformance)
            .where(SignalPerformance.signal_name.contains(setup_type))
            .order_by(desc(SignalPerformance.sample_count), desc(SignalPerformance.updated_at))
            .limit(1)
        )
        memory = db.scalar(
            select(StrategyMemory)
            .where(StrategyMemory.category == setup_type)
            .order_by(desc(StrategyMemory.sample_count), desc(StrategyMemory.updated_at))
            .limit(1)
        )
        benchmark = db.scalar(
            select(LearningBenchmarkComparison)
            .where(LearningBenchmarkComparison.benchmark_name == str(candidate.get("benchmark_asset") or "SPY"))
            .order_by(desc(LearningBenchmarkComparison.calculated_at))
            .limit(1)
        )

        r_values = [float(row.realized_r_multiple) for row in simulations if row.realized_r_multiple is not None]
        outcome_returns = [float(row.realized_return) for row in outcomes if row.realized_return is not None]
        sample_size = max(
            int(metric.sample_count or 0) if metric else 0,
            len(outcomes),
            len(simulations),
            int(signal.sample_count or 0) if signal else 0,
            int(memory.sample_count or 0) if memory else 0,
        )
        sources = [
            name
            for name, present in (
                ("r_multiple_metrics", metric is not None),
                ("prediction_outcomes", bool(outcomes)),
                ("execution_simulations", bool(simulations)),
                ("signal_performance", signal is not None),
                ("strategy_memory", memory is not None),
                ("benchmark_comparison", benchmark is not None),
            )
            if present
        ]
        if sample_size < self.min_sample_size:
            return QuantEdgeAssessment(
                verdict=REJECTED_INSUFFICIENT_SAMPLE,
                sample_size=sample_size,
                win_rate=None,
                avg_win=None,
                avg_loss=None,
                payoff_ratio=None,
                expectancy=None,
                profit_factor=None,
                max_drawdown=None,
                sharpe=None,
                sortino=None,
                benchmark_excess=float(benchmark.excess_return) if benchmark and benchmark.excess_return is not None else None,
                walk_forward_score=None,
                stability_score=None,
                overfitting_risk=100.0,
                edge_score=None,
                evidence_sources=sources,
                explanation=f"Stored evidence has {sample_size} samples; at least {self.min_sample_size} are required.",
            ).to_dict()

        wins = [value for value in (r_values or outcome_returns) if value > 0]
        losses = [value for value in (r_values or outcome_returns) if value < 0]
        win_rate = percentage_score(metric.hit_rate) if metric and metric.hit_rate is not None else round(100.0 * len(wins) / max(1, len(wins) + len(losses)), 4)
        avg_win = average(wins)
        avg_loss = average(losses)
        payoff_ratio = float(metric.payoff_ratio) if metric and metric.payoff_ratio is not None else ratio(avg_win, abs(avg_loss) if avg_loss is not None else None)
        expectancy = float(metric.expectancy_r) if metric and metric.expectancy_r is not None else average(r_values or outcome_returns)
        profit_factor = float(metric.profit_factor) if metric and metric.profit_factor is not None else ratio(sum(wins), abs(sum(losses)) if losses else None)
        max_drawdown = float(metric.max_drawdown_r) if metric and metric.max_drawdown_r is not None else minimum([float(row.max_adverse_excursion) for row in simulations if row.max_adverse_excursion is not None])
        stability_score = evidence_float(metric, "stability_score", default=stability(r_values or outcome_returns))
        walk_forward_score = evidence_float(metric, "walk_forward_score", default=win_rate)
        benchmark_excess = float(benchmark.excess_return) if benchmark and benchmark.excess_return is not None else None
        reliability = percentage_score(signal.reliability_score) if signal else percentage_score(memory.reliability_score) if memory else win_rate
        dispersion = pstdev(r_values or outcome_returns) if len(r_values or outcome_returns) > 1 else 0.0
        overfitting_risk = round(min(100.0, max(0.0, 55.0 - min(sample_size, 100) * 0.35 + dispersion * 12.0 + (15.0 if not benchmark else 0.0))), 4)
        edge_score = round(
            max(
                0.0,
                min(
                    100.0,
                    reliability * 0.25
                    + min(100.0, max(0.0, 50.0 + float(expectancy or 0.0) * 50.0)) * 0.25
                    + float(stability_score or 0.0) * 0.2
                    + float(walk_forward_score or 0.0) * 0.2
                    + benchmark_component(benchmark_excess) * 0.1,
                ),
            ),
            4,
        )

        risk_reward = float(candidate.get("risk_reward_ratio") or 0.0)
        if risk_reward < self.min_risk_reward:
            verdict = REJECTED_BAD_RISK_REWARD
            explanation = f"Risk/reward {risk_reward:.2f} is below the required {self.min_risk_reward:.2f}."
        elif self.reject_high_overfitting_risk and overfitting_risk >= 70.0:
            verdict = REJECTED_OVERFITTING_RISK
            explanation = f"Overfitting risk is {overfitting_risk:.1f}/100."
        elif benchmark_excess is not None and benchmark_excess < 0:
            verdict = REJECTED_BENCHMARK_UNDERPERFORMANCE
            explanation = f"Stored evidence underperforms its benchmark by {benchmark_excess:.2f}."
        elif edge_score >= self.min_score and float(expectancy or 0.0) > 0:
            verdict = APPROVED_FOR_PAPER
            explanation = f"Stored evidence supports a positive edge score of {edge_score:.1f}/100 across {sample_size} samples."
        elif edge_score >= max(40.0, self.min_score - 15.0):
            verdict = WATCHLIST_ONLY
            explanation = f"Edge score {edge_score:.1f}/100 is not high enough for paper approval."
        else:
            verdict = REJECTED_NO_EDGE
            explanation = f"Stored evidence does not show sufficient positive edge ({edge_score:.1f}/100)."

        return QuantEdgeAssessment(
            verdict=verdict,
            sample_size=sample_size,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            payoff_ratio=payoff_ratio,
            expectancy=expectancy,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            sharpe=None,
            sortino=None,
            benchmark_excess=benchmark_excess,
            walk_forward_score=walk_forward_score,
            stability_score=stability_score,
            overfitting_risk=overfitting_risk,
            edge_score=edge_score,
            evidence_sources=sources,
            explanation=explanation,
        ).to_dict()

    def _empty(self, verdict: str, explanation: str) -> QuantEdgeAssessment:
        return QuantEdgeAssessment(verdict, 0, None, None, None, None, None, None, None, None, None, None, None, None, None, 100.0, None, [], explanation)


def data_is_blocked(candidate: dict) -> bool:
    return str(candidate.get("data_quality_status") or "").upper() not in {"", "OK"}


def evidence_float(metric: RMultipleMetric | None, key: str, *, default: float | None) -> float | None:
    if metric and isinstance(metric.evidence, dict) and metric.evidence.get(key) is not None:
        return float(metric.evidence[key])
    return default


def average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def minimum(values: list[float]) -> float | None:
    return min(values) if values else None


def ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in {None, 0.0}:
        return None
    return round(float(numerator) / float(denominator), 4)


def stability(values: list[float]) -> float | None:
    if not values:
        return None
    dispersion = pstdev(values) if len(values) > 1 else 0.0
    return round(max(0.0, min(100.0, 100.0 - dispersion * 20.0)), 4)


def benchmark_component(excess: float | None) -> float:
    if excess is None:
        return 50.0
    return max(0.0, min(100.0, 50.0 + excess * 5.0))


def percentage_score(value: float | None) -> float:
    numeric = float(value or 0.0)
    return round(numeric * 100.0 if -1.0 <= numeric <= 1.0 else numeric, 4)
