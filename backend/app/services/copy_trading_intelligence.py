from __future__ import annotations

from datetime import datetime
from statistics import mean
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import Asset, SniperScore, TradePlan, TradingGameTrade


COPY_TRADING_POLICY = (
    "Research-only copy trading intelligence. BLUM creates conditional paper mirror plans "
    "from stored evidence and never sends orders, connects to brokers or guarantees outcomes."
)


class CopyTradingIntelligenceService:
    """Read-only copy-trading intelligence built from persisted BLUM evidence.

    This service intentionally does not recalculate Sniper, Learning Loop or Trading Game
    state. It turns already-stored TradePlan/Sniper evidence into auditable paper plans.
    """

    def status(self, db: Session) -> dict:
        plan_count = int(db.scalar(select(func.count(TradePlan.id))) or 0)
        sniper_count = int(db.scalar(select(func.count(SniperScore.id))) or 0)
        trade_count = int(db.scalar(select(func.count(TradingGameTrade.id))) or 0)
        candidate_count = len(self.candidates(db, limit=20)["rows"])
        return {
            "status": "ready" if candidate_count else "waiting_for_trade_plans",
            "mode": "paper_copy_intelligence",
            "paper_only": True,
            "no_broker_execution": True,
            "candidate_count": candidate_count,
            "stored_trade_plans": plan_count,
            "stored_sniper_scores": sniper_count,
            "stored_trading_game_trades": trade_count,
            "policy": COPY_TRADING_POLICY,
            "guardrails": guardrails(),
            "updated_at": datetime.utcnow().isoformat(),
        }

    def dashboard(self, db: Session, limit: int = 25) -> dict:
        candidates = self.candidates(db, limit=limit)
        readiness_scores = [safe_float(row.get("copy_readiness_score")) for row in candidates["rows"] if row.get("copy_readiness_score") is not None]
        active = [row for row in candidates["rows"] if row.get("copy_readiness") in {"copy_ready_if_triggered", "wait_for_trigger"}]
        blocked = [row for row in candidates["rows"] if row.get("copy_readiness") == "blocked"]
        return {
            "status": "ok",
            "mode": "paper_copy_intelligence",
            "paper_only": True,
            "no_broker_execution": True,
            "summary": {
                "candidate_count": len(candidates["rows"]),
                "actionable_if_triggered": len([row for row in active if row.get("copy_readiness") == "copy_ready_if_triggered"]),
                "wait_for_trigger": len([row for row in active if row.get("copy_readiness") == "wait_for_trigger"]),
                "blocked": len(blocked),
                "average_readiness_score": round(mean(readiness_scores), 2) if readiness_scores else None,
                "top_candidate": candidates["rows"][0] if candidates["rows"] else None,
            },
            "rows": candidates["rows"],
            "guardrails": guardrails(),
            "truth_layer": truth_lines(candidates["rows"]),
            "policy": COPY_TRADING_POLICY,
        }

    def candidates(self, db: Session, limit: int = 25) -> dict:
        limit = max(1, min(limit, 100))
        plans = db.scalars(
            select(TradePlan)
            .order_by(desc(TradePlan.created_at))
            .limit(limit * 5)
        ).all()
        tickers: list[str] = []
        rows: list[dict] = []
        seen: set[str] = set()

        for plan in plans:
            ticker = normalize_ticker(plan.ticker)
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            tickers.append(ticker)
            rows.append(self._candidate_from_plan(plan))
            if len(rows) >= limit:
                break

        if len(rows) < limit:
            scores = db.scalars(
                select(SniperScore)
                .order_by(desc(SniperScore.created_at))
                .limit(limit * 5)
            ).all()
            for score in scores:
                ticker = normalize_ticker(score.ticker)
                if not ticker or ticker in seen:
                    continue
                seen.add(ticker)
                tickers.append(ticker)
                rows.append(self._candidate_from_sniper(score))
                if len(rows) >= limit:
                    break

        self._enrich_assets(db, rows)
        self._enrich_recent_trades(db, rows, tickers)
        rows.sort(key=lambda row: safe_float(row.get("copy_readiness_score")), reverse=True)
        return {
            "status": "ok" if rows else "empty",
            "rows": rows[:limit],
            "limit": limit,
            "policy": COPY_TRADING_POLICY,
            "generated_at": datetime.utcnow().isoformat(),
        }

    def _candidate_from_plan(self, plan: TradePlan) -> dict:
        missing = []
        if not plan.entry_trigger:
            missing.append("entry_trigger")
        if plan.invalidation_level is None:
            missing.append("invalidation_level")
        if plan.target_1 is None and plan.target_2 is None:
            missing.append("target_zone")

        readiness = copy_readiness(plan.actionability, missing)
        score = readiness_score(
            actionability=plan.actionability,
            sniper_score=None,
            confidence=plan.confidence,
            historical_reliability=plan.historical_setup_reliability,
            data_quality=None,
            missing_count=len(missing),
        )
        return {
            "source": "trade_plan",
            "trade_plan_id": plan.id,
            "sniper_score_id": plan.sniper_score_id,
            "ticker": normalize_ticker(plan.ticker),
            "setup_type": plan.setup_type,
            "actionability": plan.actionability,
            "copy_readiness": readiness,
            "copy_readiness_score": score,
            "timeframe": plan.timeframe,
            "entry_zone": plan.entry_zone or {},
            "entry_trigger": plan.entry_trigger,
            "confirmation_condition": plan.confirmation_condition,
            "invalidation_level": plan.invalidation_level,
            "stop_logic": plan.stop_logic,
            "target_1": plan.target_1,
            "target_2": plan.target_2,
            "trailing_exit_logic": plan.trailing_exit_logic,
            "partial_exit_logic": plan.partial_exit_logic,
            "no_trade_conditions": plan.no_trade_conditions or {},
            "risk_reward_estimate": plan.risk_reward_estimate or {},
            "confidence": round(safe_float(plan.confidence), 2),
            "historical_setup_reliability": round(safe_float(plan.historical_setup_reliability), 2),
            "missing_data": missing,
            "paper_instruction": paper_instruction(readiness, plan.actionability),
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
        }

    def _candidate_from_sniper(self, score: SniperScore) -> dict:
        missing = ["trade_plan"]
        readiness = copy_readiness(score.actionability, missing)
        readiness_value = readiness_score(
            actionability=score.actionability,
            sniper_score=score.sniper_score,
            confidence=score.confidence,
            historical_reliability=None,
            data_quality=score.data_quality_score,
            missing_count=len(missing),
        )
        return {
            "source": "sniper_score",
            "trade_plan_id": None,
            "sniper_score_id": score.id,
            "ticker": normalize_ticker(score.ticker),
            "setup_type": score.setup_type,
            "actionability": score.actionability,
            "copy_readiness": readiness,
            "copy_readiness_score": readiness_value,
            "timeframe": "daily/swing",
            "entry_zone": {},
            "entry_trigger": "",
            "confirmation_condition": "",
            "invalidation_level": None,
            "stop_logic": "",
            "target_1": None,
            "target_2": None,
            "trailing_exit_logic": "",
            "partial_exit_logic": "",
            "no_trade_conditions": {},
            "risk_reward_estimate": {},
            "sniper_score": round(safe_float(score.sniper_score), 2),
            "confidence": round(safe_float(score.confidence), 2),
            "data_quality_score": round(safe_float(score.data_quality_score), 2),
            "explanation": score.explanation,
            "missing_data": missing,
            "paper_instruction": paper_instruction(readiness, score.actionability),
            "created_at": score.created_at.isoformat() if score.created_at else None,
        }

    def _enrich_assets(self, db: Session, rows: list[dict]) -> None:
        tickers = [row["ticker"] for row in rows if row.get("ticker")]
        if not tickers:
            return
        assets = db.scalars(select(Asset).where(Asset.ticker.in_(tickers))).all()
        by_ticker = {asset.ticker.upper(): asset for asset in assets}
        for row in rows:
            asset = by_ticker.get(row["ticker"])
            row["asset_name"] = asset.name if asset else row["ticker"]
            row["sector"] = asset.sector if asset else "Unknown"
            row["asset_type"] = asset.asset_type if asset else "Unknown"
            row["exchange"] = asset.exchange if asset else ""

    def _enrich_recent_trades(self, db: Session, rows: list[dict], tickers: list[str]) -> None:
        if not tickers:
            return
        trades = db.scalars(
            select(TradingGameTrade)
            .where(TradingGameTrade.ticker.in_(tickers))
            .order_by(desc(TradingGameTrade.created_at))
            .limit(max(80, len(tickers) * 4))
        ).all()
        latest: dict[str, TradingGameTrade] = {}
        for trade in trades:
            ticker = normalize_ticker(trade.ticker)
            if ticker not in latest:
                latest[ticker] = trade
        for row in rows:
            trade = latest.get(row["ticker"])
            if not trade:
                row["learning_evidence"] = {"status": "missing_recent_trade"}
                continue
            row["learning_evidence"] = {
                "status": "available",
                "trade_id": trade.id,
                "outcome_label": trade.outcome_label,
                "r_multiple": round(safe_float(trade.realized_r_multiple), 3),
                "net_pnl_eur": round(safe_float(trade.net_pnl_eur), 3),
                "benchmark_excess": round(safe_float(trade.excess_return_vs_benchmark), 3),
                "trade_quality_score": round(safe_float(trade.trade_quality_score), 2),
                "lesson": trade.lesson_generated,
            }
            if row.get("source") == "sniper_score" and trade.data_quality_score is not None:
                row["data_quality_score"] = round(safe_float(trade.data_quality_score), 2)


def copy_readiness(actionability: str | None, missing: list[str]) -> str:
    action = (actionability or "").lower()
    if "avoid" in action or "exit" in action or "reduce" in action:
        return "blocked"
    if missing:
        return "watch_only_missing_risk_plan"
    if action in {"active_setup", "actionable_if_confirmed"}:
        return "copy_ready_if_triggered"
    if action in {"wait_for_trigger", "watch"}:
        return "wait_for_trigger"
    return "watch_only"


def readiness_score(
    *,
    actionability: str | None,
    sniper_score: float | None,
    confidence: float | None,
    historical_reliability: float | None,
    data_quality: float | None,
    missing_count: int,
) -> float:
    action = (actionability or "").lower()
    base = 35.0
    if action == "active_setup":
        base += 25
    elif action == "actionable_if_confirmed":
        base += 18
    elif action == "wait_for_trigger":
        base += 10
    elif "avoid" in action:
        base -= 25
    components = [
        safe_float(sniper_score, 50.0) * 0.24,
        safe_float(confidence, 45.0) * 0.22,
        safe_float(historical_reliability, 45.0) * 0.18,
        safe_float(data_quality, 60.0) * 0.16,
    ]
    value = base + sum(components) - missing_count * 12
    return round(max(0.0, min(100.0, value)), 2)


def paper_instruction(readiness: str, actionability: str | None) -> str:
    if readiness == "copy_ready_if_triggered":
        return "Paper mirror candidate only if the trigger and confirmation remain valid."
    if readiness == "wait_for_trigger":
        return "Wait. Do not mirror until the stored confirmation condition is satisfied."
    if readiness == "watch_only_missing_risk_plan":
        return "Watch only. Missing risk plan details prevent copy-style mirroring."
    if readiness == "blocked":
        return "Blocked. BLUM marks this setup as avoid/reduce/exit or too weak for mirroring."
    return f"Monitor only. Current actionability is {actionability or 'unknown'}."


def truth_lines(rows: list[dict]) -> list[str]:
    if not rows:
        return ["Insufficient evidence: no stored TradePlan or Sniper evidence is available for copy-style analysis."]
    active = len([row for row in rows if row.get("copy_readiness") == "copy_ready_if_triggered"])
    missing = len([row for row in rows if row.get("missing_data")])
    return [
        f"{active} paper mirror candidates are trigger-ready; none are direct trade instructions.",
        f"{missing} candidates are missing at least one risk-plan field and are downgraded.",
        "Copy Trading Intelligence is a decision-audit layer. It does not execute trades or guarantee performance.",
    ]


def guardrails() -> list[str]:
    return [
        "paper_only",
        "no_broker_connection",
        "no_automatic_execution",
        "conditional_entry_required",
        "invalidation_required",
        "risk_reward_required",
        "no_financial_advice",
    ]


def normalize_ticker(value: str | None) -> str:
    return (value or "").strip().upper()


def safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if number == number else fallback
