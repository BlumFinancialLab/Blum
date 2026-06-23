from datetime import date, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    AllocationEfficiencyAudit,
    Asset,
    BusinessQualityScore,
    CapitalAllocationSnapshot,
    CapitalInteractionRisk,
    CashAllocationDecision,
    ExecutionSimulation,
    HistoricalPrediction,
    LearningRun,
    OpportunityCapitalScore,
    PortfolioAlphaScore,
    SizingLogicAllocation,
    TradePlan,
    TradingGame,
    TradingGameTrade,
)
from app.services.capital_allocation import AdaptiveCapitalAllocationEngine
import app.services.capital_allocation as capital_allocation_module


def seed_game(db: Session) -> TradingGame:
    game = TradingGame(
        game_id="capital-test-game",
        status="active",
        starting_capital=100.0,
        current_capital=107.0,
        cash=107.0,
        peak_capital=110.0,
        max_drawdown=-4.0,
        benchmark_ticker="SPY",
        benchmark_return=2.0,
        alpha=5.0,
        trade_count=4,
    )
    db.add(game)
    db.flush()
    trades = [
        ("NVDA", "Technology", 2.2, 5.5, 1.0, 65, 88, 2.2, 100, 102.2, False, False),
        ("MSFT", "Technology", 1.1, 2.0, 1.0, 62, 82, 1.1, 102.2, 103.3, False, False),
        ("XOM", "Energy", -0.8, -2.5, 1.4, 48, 70, -1.12, 103.3, 102.18, True, False),
        ("LLY", "Healthcare", 1.7, 3.0, 0.35, 70, 76, 0.595, 102.18, 102.775, False, False),
    ]
    for index, row in enumerate(trades):
        ticker, sector, r_mult, excess, risk_pct, confidence, reproducibility, pnl, before, after, stop_hit, missed = row
        db.add(
            TradingGameTrade(
                game_id=game.id,
                mode="historical_simulation",
                ticker=ticker,
                asset_name=ticker,
                asset_type="Stock",
                sector=sector,
                setup_type="momentum_breakout",
                confidence_at_entry=confidence,
                actionability_state_at_entry="active_setup",
                market_regime_at_entry="risk_on",
                benchmark_ticker="SPY",
                timeframe="daily",
                decision_state="active_setup",
                entry_date=date(2024, 1, 2) + timedelta(days=index),
                exit_date=date(2024, 1, 12) + timedelta(days=index),
                entry_price=100 + index,
                exit_price=100 + index + r_mult,
                position_size=1.0,
                notional_value=100.0,
                risk_amount=before * risk_pct / 100,
                risk_percent=risk_pct,
                max_expected_loss=before * risk_pct / 100,
                gross_pnl_eur=pnl,
                net_pnl_eur=pnl,
                pnl_percent=pnl / before * 100,
                realized_r_multiple=r_mult,
                realized_pl=pnl,
                capital_before=before,
                capital_after=after,
                max_favorable_excursion=max(0, r_mult * 2),
                max_adverse_excursion=min(0, r_mult),
                stop_hit=stop_hit,
                target_hit=r_mult >= 1.5,
                missed_entry=missed,
                reproducibility_score=reproducibility,
                benchmark_return_same_period=1.0,
                excess_return_vs_benchmark=excess,
                trade_quality_score=75 if r_mult > 0 else 42,
                outcome_label="win" if r_mult > 0 else "loss",
                created_at=datetime.utcnow() + timedelta(seconds=index),
            )
        )
    db.add_all(
        [
            BusinessQualityScore(ticker="NVDA", sector="Technology", business_quality_score=86, data_quality_score=90),
            BusinessQualityScore(ticker="MSFT", sector="Technology", business_quality_score=82, data_quality_score=90),
            BusinessQualityScore(ticker="XOM", sector="Energy", business_quality_score=60, data_quality_score=75),
            BusinessQualityScore(ticker="LLY", sector="Healthcare", business_quality_score=78, data_quality_score=80),
            PortfolioAlphaScore(game_id=game.id, ticker="NVDA", portfolio_alpha_score=84, marginal_return_score=80, marginal_risk_score=70, benchmark_excess_score=82),
            PortfolioAlphaScore(game_id=game.id, ticker="MSFT", portfolio_alpha_score=70, marginal_return_score=68, marginal_risk_score=76, benchmark_excess_score=67),
            PortfolioAlphaScore(game_id=game.id, ticker="XOM", portfolio_alpha_score=38, marginal_return_score=35, marginal_risk_score=45, benchmark_excess_score=38),
            PortfolioAlphaScore(game_id=game.id, ticker="LLY", portfolio_alpha_score=73, marginal_return_score=72, marginal_risk_score=80, benchmark_excess_score=74),
        ]
    )
    db.commit()
    return game


def test_adaptive_capital_allocation_engine_scores_cash_and_persists():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(
        engine,
        tables=[
            Asset.__table__,
            LearningRun.__table__,
            HistoricalPrediction.__table__,
            TradePlan.__table__,
            ExecutionSimulation.__table__,
            TradingGame.__table__,
            TradingGameTrade.__table__,
            BusinessQualityScore.__table__,
            PortfolioAlphaScore.__table__,
            CapitalAllocationSnapshot.__table__,
            OpportunityCapitalScore.__table__,
            CashAllocationDecision.__table__,
            AllocationEfficiencyAudit.__table__,
            SizingLogicAllocation.__table__,
            CapitalInteractionRisk.__table__,
        ],
    )
    allocation = AdaptiveCapitalAllocationEngine()
    original_lookup = capital_allocation_module.correlation_lookup
    capital_allocation_module.correlation_lookup = lambda db: {tuple(sorted(["NVDA", "MSFT"])): 0.82}
    with Session(engine) as db:
        try:
            game = seed_game(db)
            plan = allocation.allocation_plan(db, persist=False)
            assert plan["status"] == "ok"
            assert plan["cash_reserve_percent"] >= 20
            assert plan["allocations"][0]["ticker"] == "NVDA"
            assert sum(item["recommended_weight"] for item in plan["allocations"]) + plan["cash_reserve_percent"] >= 99.0

            cash = allocation.cash_policy(db, persist=False)
            assert cash["decision_state"] in {"partial_cash", "defensive_cash", "balanced_cash", "selective_deployment"}
            assert "sample_size" in cash["evidence"]

            efficiency = allocation.allocation_efficiency(db, persist=False)
            assert efficiency["sample_size"] == 4
            assert any(item["ticker"] == "NVDA" for item in efficiency["underallocated_winners"])
            assert any(item["ticker"] == "XOM" for item in efficiency["overallocated_losers"])

            sizing = allocation.sizing_logic_effectiveness(db, persist=False)
            assert sizing["rows"]
            assert any(row["sizing_logic"] == "confidence_adjusted_fractional" for row in sizing["rows"])

            interactions = allocation.interaction_risks(db, persist=False)
            assert any(row["interaction_type"] == "correlation_concentration" for row in interactions["rows"])

            persisted = allocation.recalculate(db)
            assert persisted["status"] == "ok"
            assert db.scalar(select(CapitalAllocationSnapshot).where(CapitalAllocationSnapshot.game_id == game.id)) is not None
            assert db.scalar(select(OpportunityCapitalScore).where(OpportunityCapitalScore.ticker == "NVDA")) is not None
            assert db.scalar(select(CashAllocationDecision).where(CashAllocationDecision.game_id == game.id)) is not None
            assert db.scalar(select(AllocationEfficiencyAudit).where(AllocationEfficiencyAudit.game_id == game.id)) is not None
            assert db.scalar(select(SizingLogicAllocation).where(SizingLogicAllocation.game_id == game.id)) is not None
        finally:
            capital_allocation_module.correlation_lookup = original_lookup


if __name__ == "__main__":
    test_adaptive_capital_allocation_engine_scores_cash_and_persists()
