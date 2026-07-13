from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from app.services.intraday_contracts import (
    INTRADAY_BLOCKED,
    INTRADAY_DATA_BLOCKED,
    INTRADAY_TRADE_CANDIDATE,
    INTRADAY_WATCHLIST,
    IntradayDataBundle,
    IntradayDecision,
    IntradayPositionSize,
    PromotedIntradayStrategy,
)
from app.services.replay_execution import ReplayExecutionModel, ReplayPositionSizer


@dataclass(frozen=True)
class IntradayPortfolioState:
    capital: float
    open_tickers: frozenset[str] = frozenset()
    positions_by_market: dict[str, int] = field(default_factory=dict)
    positions_by_desk: dict[str, int] = field(default_factory=dict)
    positions_by_asset_class: dict[str, int] = field(default_factory=dict)
    total_open_positions: int = 0
    total_risk_percent: float = 0.0


class BlumIntradayOpportunityEngine:
    def __init__(
        self,
        *,
        min_expected_move_bps: float = 12.0,
        max_spread_to_target_ratio: float = 0.25,
        min_liquidity_score: float = 35.0,
        max_open_positions: int = 5,
        max_positions_per_market: int = 3,
        max_positions_per_desk: int = 2,
        max_total_risk_percent: float = 5.0,
    ):
        self.min_expected_move_bps = float(min_expected_move_bps)
        self.max_spread_to_target_ratio = float(max_spread_to_target_ratio)
        self.min_liquidity_score = float(min_liquidity_score)
        self.max_open_positions = int(max_open_positions)
        self.max_positions_per_market = int(max_positions_per_market)
        self.max_positions_per_desk = int(max_positions_per_desk)
        self.max_total_risk_percent = float(max_total_risk_percent)
        self.cost_model = ReplayExecutionModel()
        self.sizer = ReplayPositionSizer(max_risk_fraction=0.01)

    def evaluate(
        self,
        *,
        strategy: PromotedIntradayStrategy,
        data: IntradayDataBundle,
        portfolio: IntradayPortfolioState,
        desk: str,
        benchmark_ticker: str,
        asset_type: str = "Stock",
    ) -> IntradayDecision:
        base = dict(
            ticker=data.ticker,
            market=data.market,
            desk=desk,
            benchmark_ticker=benchmark_ticker,
            strategy_id=strategy.strategy_id,
            validation_id=strategy.validation_id,
            setup_type=strategy.setup_type,
            decision_timestamp=data.as_of,
        )
        if not data.ready:
            return IntradayDecision(INTRADAY_DATA_BLOCKED, data.blockers[0] if data.blockers else "DATA_BLOCKED", "Strict timeframe data is incomplete or stale.", **base)
        ticker = data.ticker.upper()
        if ticker in portfolio.open_tickers:
            return IntradayDecision(INTRADAY_BLOCKED, "TICKER_CONCENTRATION", "One intraday position per ticker is already open.", **base)
        if portfolio.total_open_positions >= self.max_open_positions:
            return IntradayDecision(INTRADAY_BLOCKED, "MAX_OPEN_POSITIONS", "Portfolio open-position limit reached.", **base)
        if portfolio.positions_by_market.get(data.market, 0) >= self.max_positions_per_market:
            return IntradayDecision(INTRADAY_BLOCKED, "MARKET_CONCENTRATION", "Market concentration limit reached.", **base)
        if portfolio.positions_by_desk.get(desk, 0) >= self.max_positions_per_desk:
            return IntradayDecision(INTRADAY_BLOCKED, "DESK_CONCENTRATION", "Desk concentration limit reached.", **base)
        if portfolio.total_risk_percent >= self.max_total_risk_percent:
            return IntradayDecision(INTRADAY_BLOCKED, "TOTAL_RISK_LIMIT", "Portfolio paper-risk limit reached.", **base)

        daily, setup, confirmation, trigger = (data.bars[key] for key in ("1d", "15m", "5m", "1m"))
        regime_up = daily[-1].close > mean(float(row.close) for row in daily[-20:])
        setup_up = setup[-1].close > mean(float(row.close) for row in setup[-20:])
        confirmed = confirmation[-1].close > confirmation[-2].close
        triggered = trigger[-1].close > trigger[-2].close
        regime = "trend_up" if regime_up else "trend_down"
        if not regime_up or not setup_up:
            return IntradayDecision(INTRADAY_BLOCKED, "REGIME_MISMATCH", "Daily regime or 15-minute setup contradicts the promoted strategy.", regime=regime, **base)
        if not confirmed or not triggered:
            return IntradayDecision(INTRADAY_WATCHLIST, "WAITING_FOR_TRIGGER", "Setup exists but 5-minute confirmation or 1-minute trigger is missing.", regime=regime, **base)

        latest = trigger[-1]
        entry = float(latest.close)
        true_ranges = [max(float(row.high or row.close) - float(row.low or row.close), abs(float(row.close) - float(row.open or row.close))) for row in trigger[-20:]]
        atr = max(0.0001, mean(true_ranges))
        volatility_bps = atr / entry * 10_000
        volumes = [float(row.volume or 0.0) for row in trigger[-20:]]
        latest_volume = volumes[-1]
        average_volume = max(1.0, mean(volumes))
        liquidity_score = max(0.0, min(100.0, 55.0 + (latest_volume / average_volume - 1.0) * 30.0))
        if liquidity_score < self.min_liquidity_score:
            return IntradayDecision(INTRADAY_BLOCKED, "LIQUIDITY_TOO_LOW", "Observed one-minute liquidity is below the configured threshold.", liquidity_score=liquidity_score, volatility_bps=volatility_bps, regime=regime, **base)

        session = session_name(data.market, data.as_of.hour)
        if session != "regular":
            return IntradayDecision(INTRADAY_BLOCKED, "SESSION_NOT_ALLOWED", "The current timestamp is outside the permitted regular session.", liquidity_score=liquidity_score, volatility_bps=volatility_bps, regime=regime, session=session, **base)

        cost = self.cost_model.profile(market=data.market, asset_type=asset_type, liquidity_score=liquidity_score, session=session)
        risk_distance = max(atr, entry * 0.0015)
        target_multiple = float(strategy.target_rules.get("risk_multiple") or 1.8)
        stop = entry - risk_distance
        target = entry + risk_distance * target_multiple
        expected_move_bps = (target - entry) / entry * 10_000
        net_expectancy_bps = expected_move_bps - cost.total_round_trip_bps
        costs = cost.to_dict()
        if expected_move_bps < self.min_expected_move_bps:
            return IntradayDecision(INTRADAY_BLOCKED, "EXPECTED_MOVE_TOO_SMALL", "Expected move is below the configured minimum.", entry_price=entry, stop_price=stop, target_price=target, expected_move_bps=expected_move_bps, net_expectancy_bps=net_expectancy_bps, liquidity_score=liquidity_score, volatility_bps=volatility_bps, regime=regime, session=session, costs=costs, **base)
        if net_expectancy_bps <= 0:
            return IntradayDecision(INTRADAY_BLOCKED, "COSTS_KILL_EDGE", "Round-trip costs eliminate expected edge.", entry_price=entry, stop_price=stop, target_price=target, expected_move_bps=expected_move_bps, net_expectancy_bps=net_expectancy_bps, liquidity_score=liquidity_score, volatility_bps=volatility_bps, regime=regime, session=session, costs=costs, **base)
        if cost.spread_bps / max(expected_move_bps, 0.01) > self.max_spread_to_target_ratio:
            return IntradayDecision(INTRADAY_BLOCKED, "SPREAD_TOO_WIDE", "Estimated spread is too large relative to the target.", costs=costs, **base)

        confidence = max(strategy.minimum_confidence, min(95.0, strategy.walk_forward_score))
        edge_score = max(strategy.minimum_edge_score, min(100.0, 50.0 + float(strategy.metrics.get("expectancy_r") or 0.0) * 100.0))
        size = self.sizer.size(
            capital=portfolio.capital,
            entry=entry,
            stop=stop,
            atr=atr,
            liquidity_score=liquidity_score,
            confidence=confidence,
            edge_score=edge_score,
            data_quality=min(data.quality_scores.values()),
            regime_alignment=80.0,
        )
        if size.units <= 0:
            return IntradayDecision(INTRADAY_BLOCKED, size.blocker or "SIZING_BLOCKED", "Dynamic position sizing rejected the setup.", **base)
        sizing = IntradayPositionSize(size.units, size.notional, size.risk_amount, size.risk_fraction * 100.0, "Volatility, liquidity, confidence, edge, regime, data quality and stop distance.")
        return IntradayDecision(
            INTRADAY_TRADE_CANDIDATE,
            "APPROVED",
            "Promoted strategy passed strict multi-timeframe, cost, liquidity, session and concentration gates.",
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            trailing_stop=entry - atr * 1.2,
            confidence=confidence,
            edge_score=edge_score,
            expected_move_bps=expected_move_bps,
            net_expectancy_bps=net_expectancy_bps,
            liquidity_score=liquidity_score,
            volatility_bps=volatility_bps,
            regime=regime,
            session=session,
            costs=costs,
            sizing=sizing,
            evidence={"timeframes": list(strategy.timeframe_stack), "data_timestamps": {key: value.isoformat() if value else None for key, value in data.latest_timestamps.items()}},
            **base,
        )


def session_name(market: str, utc_hour: int) -> str:
    key = str(market or "").upper()
    if key in {"USA", "US", "UNITED STATES"}:
        return "regular" if 13 <= utc_hour <= 20 else "closed"
    if key in {"ITALY", "GERMANY", "FRANCE", "EUROPE"}:
        return "regular" if 7 <= utc_hour <= 16 else "closed"
    return "closed"
