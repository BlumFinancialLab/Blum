from __future__ import annotations

from datetime import datetime
from statistics import median
from time import perf_counter
from typing import Any

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    ForexDecision,
    ForexLearningEvidence,
    ForexPosition,
    LiveForwardPaperGame,
    LiveForwardPaperTrade,
    LiveForwardPaperTradeEvent,
)
from app.services.dashboard_snapshots import DashboardSnapshotService


SNAPSHOT_TYPE = "unified_paper_trading_summary"
TERMINAL_STATUSES = {"CLOSED", "EXPIRED", "INVALIDATED"}
OPEN_STATUSES = {"OPEN", "MANAGED"}


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _forex_confidence_score(value: Any) -> float | None:
    """Normalize the Forex agent contract (0..1) to the UI contract (0..100).

    Older persisted fixtures and imported decisions may already use the dashboard
    scale, so values above one are preserved instead of multiplied again.
    """
    parsed = _float(value)
    if parsed is None:
        return None
    if 0.0 <= parsed <= 1.0:
        return round(parsed * 100.0, 6)
    return parsed


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


class UnifiedPaperTradingProjectionService:
    """Background-built projection across paper-forward execution engines.

    The projection never copies source records and never infers missing P/L. GET
    consumers use ``latest`` and therefore cannot trigger trading or computation.
    """

    def __init__(self, snapshots: DashboardSnapshotService | None = None) -> None:
        self.snapshots = snapshots or DashboardSnapshotService()

    def build(self, db: Session, *, limit: int = 50) -> dict:
        started = perf_counter()
        limit = max(1, min(int(limit), 200))
        game = db.scalar(
            select(LiveForwardPaperGame)
            .order_by(desc(LiveForwardPaperGame.updated_at), desc(LiveForwardPaperGame.id))
            .limit(1)
        )
        paper_rows = list(
            db.scalars(select(LiveForwardPaperTrade).order_by(desc(LiveForwardPaperTrade.created_at))).all()
        )
        forex_positions = list(
            db.scalars(select(ForexPosition).order_by(desc(ForexPosition.created_at))).all()
        )
        represented_decisions = select(ForexPosition.decision_id)
        unrepresented_filter = ForexDecision.id.not_in(represented_decisions)
        forex_decision_total = int(
            db.scalar(
                select(func.count(ForexDecision.id)).where(unrepresented_filter)
            )
            or 0
        )
        forex_rejected_total = int(
            db.scalar(
                select(func.count(ForexDecision.id)).where(
                    unrepresented_filter,
                    ForexDecision.status.in_(["REJECTED", "BLOCKED", "NO_TRADE"]),
                )
            )
            or 0
        )
        forex_decisions = list(
            db.scalars(
                select(ForexDecision)
                .where(unrepresented_filter)
                .order_by(desc(ForexDecision.created_at))
                .limit(limit)
            ).all()
        )
        decision_ids = {
            *[row.decision_id for row in forex_positions],
            *[row.id for row in forex_decisions],
        }
        decisions_by_id = {
            row.id: row
            for row in db.scalars(
                select(ForexDecision).where(ForexDecision.id.in_(decision_ids))
            ).all()
        } if decision_ids else {}
        evidence_filters = []
        position_ids = [row.id for row in forex_positions]
        if position_ids:
            evidence_filters.append(ForexLearningEvidence.position_id.in_(position_ids))
        if decision_ids:
            evidence_filters.append(ForexLearningEvidence.decision_id.in_(decision_ids))
        forex_evidence = (
            list(
                db.scalars(
                    select(ForexLearningEvidence)
                    .where(or_(*evidence_filters))
                    .order_by(desc(ForexLearningEvidence.created_at))
                ).all()
            )
            if evidence_filters
            else []
        )

        evidence_by_position: dict[int, ForexLearningEvidence] = {}
        evidence_by_decision: dict[int, ForexLearningEvidence] = {}
        for evidence in forex_evidence:
            if evidence.position_id is not None and evidence.position_id not in evidence_by_position:
                evidence_by_position[evidence.position_id] = evidence
            if evidence.decision_id is not None and evidence.decision_id not in evidence_by_decision:
                evidence_by_decision[evidence.decision_id] = evidence

        paper_projection_rows = [self._paper_row(row) for row in paper_rows]
        forex_position_rows = [
            self._forex_position_row(
                row,
                decisions_by_id.get(row.decision_id),
                evidence_by_position.get(row.id) or evidence_by_decision.get(row.decision_id),
            )
            for row in forex_positions
        ]
        forex_decision_rows = [
            self._forex_decision_row(row, evidence_by_decision.get(row.id))
            for row in forex_decisions
        ]
        rows = [*paper_projection_rows, *forex_position_rows, *forex_decision_rows]
        rows.sort(key=lambda row: row.get("sort_timestamp") or "", reverse=True)

        by_market = {
            "standard": self._summarize(
                [row for row in paper_projection_rows if row["market_group"] == "standard"]
            ),
            "intraday": self._summarize(
                [row for row in paper_projection_rows if row["market_group"] == "intraday"]
            ),
            "forex": self._with_candidate_counts(
                self._summarize(forex_position_rows),
                candidate_count=forex_decision_total,
                rejected_count=forex_rejected_total,
            ),
        }
        aggregate = self._with_candidate_counts(
            self._summarize([*paper_projection_rows, *forex_position_rows]),
            candidate_count=forex_decision_total,
            rejected_count=forex_rejected_total,
        )
        warnings = self._warnings(aggregate, by_market)
        visible = self._balanced_visible_rows(rows, limit)
        candidate_rows = [
            row for row in rows
            if row["status"] not in TERMINAL_STATUSES | OPEN_STATUSES
        ]
        open_rows = [row for row in rows if row["status"] in OPEN_STATUSES]
        closed_rows = [row for row in rows if row["status"] in TERMINAL_STATUSES]
        visible_candidates = self._balanced_visible_rows(candidate_rows, limit)
        visible_open = self._balanced_visible_rows(open_rows, limit)
        visible_closed = self._balanced_visible_rows(closed_rows, limit)
        return {
            "status": "READY" if aggregate["counts"]["total"] else "NO_DECISIONS",
            "generated_at": datetime.utcnow().isoformat(),
            "game": {
                "game_id": game.game_id if game else None,
                "current_capital": _float(game.current_capital) if game else None,
                "starting_capital": _float(game.starting_capital) if game else None,
                "target_capital": _float(game.target_capital) if game else None,
                "cash": _float(game.cash) if game else None,
                "benchmark_ticker": game.benchmark_ticker if game else None,
            },
            "counts": {
                "aggregate": aggregate["counts"],
                "by_market": {key: value["counts"] for key, value in by_market.items()},
            },
            "metrics": {
                "aggregate": aggregate["metrics"],
                "by_market": {key: value["metrics"] for key, value in by_market.items()},
            },
            "trades": visible,
            "candidates": visible_candidates,
            "open_positions": visible_open,
            "recently_closed": visible_closed,
            "pagination": {
                "limit": limit,
                "returned": len(visible),
                "total": aggregate["counts"]["total"],
            },
            "candidate_pagination": {
                "limit": limit,
                "returned": len(visible_candidates),
                "total": aggregate["counts"]["candidates"],
            },
            "open_position_pagination": {
                "limit": limit,
                "returned": len(visible_open),
                "total": len(open_rows),
            },
            "recently_closed_pagination": {
                "limit": limit,
                "returned": len(visible_closed),
                "total": len(closed_rows),
            },
            "warnings": warnings,
            "evidence_policy": "Observed source records only; open and rejected decisions never contribute realized P/L.",
            "computation_duration_ms": round((perf_counter() - started) * 1000, 3),
        }

    @staticmethod
    def _balanced_visible_rows(rows: list[dict], limit: int) -> list[dict]:
        """Keep a noisy high-frequency market from evicting other journals."""
        buckets = {
            market: [row for row in rows if row.get("market_group") == market]
            for market in ("standard", "intraday", "forex")
        }
        nonempty = [bucket for bucket in buckets.values() if bucket]
        if len(nonempty) <= 1:
            return rows[:limit]
        quota = max(1, limit // len(nonempty))
        selected: list[dict] = []
        selected_ids: set[str] = set()
        for bucket in nonempty:
            for row in bucket[:quota]:
                selected.append(row)
                selected_ids.add(str(row.get("trade_id")))
        for row in rows:
            if len(selected) >= limit:
                break
            trade_id = str(row.get("trade_id"))
            if trade_id not in selected_ids:
                selected.append(row)
                selected_ids.add(trade_id)
        return sorted(selected[:limit], key=lambda row: row.get("sort_timestamp") or "", reverse=True)

    def publish(self, db: Session, *, limit: int = 50) -> dict:
        payload = self.build(db, limit=limit)
        return self.snapshots.write(
            db,
            SNAPSHOT_TYPE,
            payload,
            source_modules={
                "paper_forward": "live_forward_paper_trades",
                "forex": "forex_positions/forex_decisions",
            },
            ttl_seconds=300,
            warnings=payload["warnings"],
            computation_duration_ms=payload["computation_duration_ms"],
        )

    def latest(self, db: Session) -> dict:
        snapshot = self.snapshots.latest(db, SNAPSHOT_TYPE)
        if snapshot["status"] == "missing":
            return {
                "snapshot_status": "missing",
                "status": "NO_SNAPSHOTS",
                "explanation": "No unified paper trading snapshot is available yet.",
                "missing_sections": ["paper_forward", "forex"],
                "trades": [],
                "warnings": ["Background workers have not published the unified snapshot yet."],
            }
        payload = dict(snapshot.get("payload") or {})
        payload.update(
            {
                "snapshot_status": snapshot["status"],
                "snapshot_created_at": snapshot.get("created_at"),
                "snapshot_expires_at": snapshot.get("expires_at"),
                "is_stale": snapshot.get("is_stale", False),
            }
        )
        if snapshot.get("is_stale"):
            payload.setdefault("warnings", []).append(
                "Snapshot is stale; showing the latest completed background projection."
            )
        return payload

    def detail(self, db: Session, source_engine: str, source_trade_id: int) -> dict:
        if source_engine == "paper_forward":
            trade = db.get(LiveForwardPaperTrade, source_trade_id)
            if trade is None:
                return {"status": "NOT_FOUND", "trade": None, "events": []}
            events = list(
                db.scalars(
                    select(LiveForwardPaperTradeEvent)
                    .where(LiveForwardPaperTradeEvent.paper_trade_id == trade.id)
                    .order_by(LiveForwardPaperTradeEvent.event_timestamp)
                ).all()
            )
            return {
                "status": "READY",
                "trade": self._paper_row(trade),
                "events": [
                    {
                        "event_type": row.event_type,
                        "timestamp": _iso(row.event_timestamp),
                        "price": _float(row.price_used),
                        "reason": row.reason,
                        "payload": row.payload or {},
                    }
                    for row in events
                ],
            }
        if source_engine == "forex_trader":
            position = db.get(ForexPosition, source_trade_id)
            if position is None:
                return {"status": "NOT_FOUND", "trade": None, "events": []}
            decision = db.get(ForexDecision, position.decision_id)
            evidence = db.scalar(
                select(ForexLearningEvidence)
                .where(ForexLearningEvidence.position_id == position.id)
                .order_by(desc(ForexLearningEvidence.created_at))
                .limit(1)
            )
            return {
                "status": "READY",
                "trade": self._forex_position_row(position, decision, evidence),
                "decision": self._forex_decision_detail(decision),
                "events": self._forex_events(position, decision, evidence),
            }
        if source_engine == "forex_decision":
            decision = db.get(ForexDecision, source_trade_id)
            if decision is None:
                return {"status": "NOT_FOUND", "trade": None, "events": []}
            evidence = db.scalar(
                select(ForexLearningEvidence)
                .where(ForexLearningEvidence.decision_id == decision.id)
                .order_by(desc(ForexLearningEvidence.created_at))
                .limit(1)
            )
            events = [
                {
                    "event_type": "DECISION_RECORDED",
                    "timestamp": _iso(decision.decision_timestamp),
                    "price": _float((decision.proposal_json or {}).get("entry")),
                    "reason": "Forex decision was stored without an executed position.",
                    "payload": {"status": decision.status, "blockers": decision.blockers or []},
                }
            ]
            if evidence is not None:
                events.append(
                    {
                        "event_type": "LEARNING_EVIDENCE_RECORDED",
                        "timestamp": _iso(evidence.created_at),
                        "price": None,
                        "reason": evidence.lesson,
                        "payload": evidence.payload_json or {},
                    }
                )
            return {
                "status": "READY",
                "trade": self._forex_decision_row(decision, evidence),
                "decision": self._forex_decision_detail(decision),
                "events": events,
            }
        return {"status": "UNSUPPORTED_SOURCE", "trade": None, "events": []}

    def _paper_row(self, trade: LiveForwardPaperTrade) -> dict:
        payload = trade.frozen_decision_payload or {}
        direction = payload.get("direction") or payload.get("action") or "LONG"
        market_group = (
            "intraday"
            if trade.intraday_run_id is not None
            or "INTRADAY" in str(trade.evidence_type or "").upper()
            or "INTRADAY" in str(trade.trading_mode or "").upper()
            else "standard"
        )
        timestamp = trade.closed_at or trade.opened_at or trade.decision_timestamp or trade.created_at
        return {
            "trade_id": f"paper:{trade.id}",
            "source_trade_id": trade.id,
            "source_engine": "paper_forward",
            "market_group": market_group,
            "market": trade.market or "equity",
            "ticker": trade.ticker,
            "asset_name": trade.asset_name or trade.ticker,
            "asset_type": trade.asset_type or "public_asset",
            "setup_type": trade.setup_type,
            "status": str(trade.status or "CANDIDATE").upper(),
            "source_status": trade.status,
            "direction": str(direction).upper(),
            "decision_timestamp": _iso(trade.decision_timestamp),
            "opened_at": _iso(trade.opened_at),
            "closed_at": _iso(trade.closed_at),
            "entry_price": _float(trade.entry_price),
            "current_price": _float(trade.current_price),
            "exit_price": _float(trade.exit_price),
            "stop_loss": _float(trade.stop_loss),
            "target_1": _float(trade.target_1),
            "target_2": _float(trade.target_2),
            "position_size": _float(trade.position_size),
            "notional_value": _float(trade.notional_value),
            "risk_amount": _float(trade.risk_amount),
            "gross_pnl": _float(trade.gross_pnl_eur),
            "net_pnl": _float(trade.net_pnl_eur),
            "gross_pnl_eur": _float(trade.gross_pnl_eur),
            "net_pnl_eur": _float(trade.net_pnl_eur),
            "unrealized_pnl": _float(trade.unrealized_pnl) if trade.status in OPEN_STATUSES else None,
            "pnl_percent": _float(trade.pnl_percent),
            "pnl_per_share": _float(trade.pnl_per_share),
            "r_multiple": _float(trade.r_multiple),
            "benchmark_ticker": trade.benchmark_ticker,
            "benchmark_return": _float(trade.benchmark_return_same_period),
            "benchmark_excess": _float(trade.excess_return_vs_benchmark),
            "excess_return_vs_benchmark": _float(trade.excess_return_vs_benchmark),
            "outcome_label": trade.outcome_label,
            "lesson_learned": trade.lesson_learned,
            "close_reason": trade.close_reason,
            "blockers": payload.get("blockers") or [],
            "confidence": _float(trade.confidence),
            "sniper_score": _float(trade.sniper_score),
            "evidence_type": trade.evidence_type,
            "costs": trade.execution_costs or {
                "spread": _float(trade.spread_cost),
                "slippage": _float(trade.slippage_cost),
                "commission": _float(trade.commission_cost),
                "total": _float(trade.costs_paid),
            },
            "sort_timestamp": _iso(timestamp),
        }

    def _forex_position_row(
        self,
        position: ForexPosition,
        decision: ForexDecision | None,
        evidence: ForexLearningEvidence | None,
    ) -> dict:
        proposal = decision.proposal_json if decision else {}
        contract = position.contract_json or {}
        is_open = str(position.status).upper() in OPEN_STATUSES
        timestamp = position.closed_at or position.opened_at or position.created_at
        return {
            "trade_id": f"forex:{position.id}",
            "source_trade_id": position.id,
            "source_engine": "forex_trader",
            "market_group": "forex",
            "market": "forex",
            "ticker": position.pair,
            "asset_name": position.pair,
            "asset_type": "forex_pair",
            "setup_type": contract.get("setup_family") or proposal.get("setup_family") or position.strategy_id,
            "status": str(position.status).upper(),
            "source_status": position.status,
            "direction": position.direction,
            "decision_timestamp": _iso(decision.decision_timestamp if decision else position.created_at),
            "opened_at": _iso(position.opened_at),
            "closed_at": _iso(position.closed_at),
            "entry_price": _float(position.entry_price),
            "current_price": _float(position.current_price),
            "exit_price": _float(position.exit_price),
            "stop_loss": _float(position.stop_price),
            "target_1": _float(position.target_price),
            "target_2": None,
            "position_size": _float(position.quantity_lots),
            "notional_value": _float(contract.get("notional_value")),
            "risk_amount": _float(contract.get("risk_amount")),
            "gross_pnl": _float(position.gross_pnl) if not is_open else None,
            "net_pnl": _float(position.net_pnl) if not is_open else None,
            "gross_pnl_eur": _float(position.gross_pnl) if not is_open else None,
            "net_pnl_eur": _float(position.net_pnl) if not is_open else None,
            "unrealized_pnl": _float(contract.get("unrealized_net_pnl")) if is_open else None,
            "pnl_percent": _float(contract.get("pnl_percent")) if not is_open else None,
            "pnl_per_share": None,
            "r_multiple": _float(position.realized_r) if not is_open else _float(contract.get("current_r")),
            "benchmark_ticker": contract.get("benchmark_ticker"),
            "benchmark_return": _float((evidence.payload_json or {}).get("benchmark_return")) if evidence else None,
            "benchmark_excess": _float((evidence.payload_json or {}).get("benchmark_excess")) if evidence else None,
            "excess_return_vs_benchmark": _float((evidence.payload_json or {}).get("benchmark_excess")) if evidence else None,
            "outcome_label": evidence.outcome if evidence else position.exit_reason,
            "lesson_learned": evidence.lesson if evidence else None,
            "close_reason": position.exit_reason,
            "blockers": [],
            "confidence": _forex_confidence_score(proposal.get("confidence")),
            "confidence_raw": _float(proposal.get("confidence")),
            "confidence_components": dict(proposal.get("confidence_components") or {}),
            "actionability_status": proposal.get("actionability_status") or ("ACTIONABLE" if not decision or not decision.blockers else "BLOCKED"),
            "sniper_score": _float(proposal.get("sniper_score")),
            "evidence_type": (evidence.evidence_type if evidence else None) or (decision.evidence_type if decision else "PAPER_FORWARD_FOREX"),
            "costs": {
                "spread": _float(position.spread_cost),
                "slippage": _float(position.slippage_cost),
                "commission": _float(position.commission),
                "swap": _float(position.swap_accrued),
                "total": round(
                    float(position.spread_cost or 0)
                    + float(position.slippage_cost or 0)
                    + float(position.commission or 0)
                    + float(position.swap_accrued or 0),
                    6,
                ),
            },
            "sort_timestamp": _iso(timestamp),
        }

    def _forex_decision_row(
        self, decision: ForexDecision, evidence: ForexLearningEvidence | None
    ) -> dict:
        proposal = decision.proposal_json or {}
        status = str(decision.status or "CANDIDATE").upper()
        normalized_status = "SKIPPED" if status in {"REJECTED", "BLOCKED", "NO_TRADE"} else "CANDIDATE"
        return {
            "trade_id": f"forex-decision:{decision.id}",
            "source_trade_id": decision.id,
            "source_engine": "forex_decision",
            "market_group": "forex",
            "market": "forex",
            "ticker": decision.pair,
            "asset_name": decision.pair,
            "asset_type": "forex_pair",
            "setup_type": proposal.get("setup_family") or decision.strategy_id,
            "status": normalized_status,
            "source_status": status,
            "direction": decision.direction,
            "decision_timestamp": _iso(decision.decision_timestamp),
            "opened_at": None,
            "closed_at": None,
            "entry_price": _float(proposal.get("entry")),
            "current_price": None,
            "exit_price": None,
            "stop_loss": _float(proposal.get("stop")),
            "target_1": _float(proposal.get("target")),
            "target_2": None,
            "position_size": None,
            "notional_value": None,
            "risk_amount": _float((decision.risk_json or {}).get("risk_amount")),
            "gross_pnl": None,
            "net_pnl": None,
            "gross_pnl_eur": None,
            "net_pnl_eur": None,
            "unrealized_pnl": None,
            "pnl_percent": None,
            "pnl_per_share": None,
            "r_multiple": None,
            "benchmark_ticker": None,
            "benchmark_return": None,
            "benchmark_excess": None,
            "excess_return_vs_benchmark": None,
            "outcome_label": evidence.outcome if evidence else "NO_TRADE",
            "lesson_learned": evidence.lesson if evidence else None,
            "close_reason": None,
            "blockers": decision.blockers or [],
            "confidence": _forex_confidence_score(proposal.get("confidence")),
            "confidence_raw": _float(proposal.get("confidence")),
            "confidence_components": dict(proposal.get("confidence_components") or {}),
            "actionability_status": proposal.get("actionability_status") or ("BLOCKED" if decision.blockers else "UNASSESSED"),
            "sniper_score": _float(proposal.get("sniper_score")),
            "evidence_type": decision.evidence_type,
            "costs": {},
            "sort_timestamp": _iso(decision.decision_timestamp),
        }

    def _summarize(self, rows: list[dict]) -> dict:
        closed = [row for row in rows if row["status"] in TERMINAL_STATUSES and row["net_pnl"] is not None]
        opened = [row for row in rows if row["status"] in OPEN_STATUSES]
        rejected = [row for row in rows if row.get("source_status") in {"REJECTED", "BLOCKED", "NO_TRADE"}]
        pnl = [float(row["net_pnl"]) for row in closed]
        r_values = [float(row["r_multiple"]) for row in closed if row["r_multiple"] is not None]
        excess = [float(row["benchmark_excess"]) for row in closed if row["benchmark_excess"] is not None]
        unrealized = [float(row["unrealized_pnl"]) for row in opened if row["unrealized_pnl"] is not None]
        wins = [value for value in pnl if value > 0]
        losses = [value for value in pnl if value < 0]
        drawdown = self._max_drawdown(closed)
        return {
            "counts": {
                "total": len(rows),
                "candidates": len(rows) - len(opened) - len(closed),
                "open": len(opened),
                "closed": len(closed),
                "wins": len(wins),
                "losses": len(losses),
                "decisions_rejected": len(rejected),
            },
            "metrics": {
                "realized_pnl": round(sum(pnl), 6) if pnl else None,
                "unrealized_pnl": round(sum(unrealized), 6) if unrealized else None,
                "win_rate": round(len(wins) / len(pnl), 6) if pnl else None,
                "average_r": round(sum(r_values) / len(r_values), 6) if r_values else None,
                "median_r": round(median(r_values), 6) if r_values else None,
                "expectancy_r": round(sum(r_values) / len(r_values), 6) if r_values else None,
                "profit_factor": round(sum(wins) / abs(sum(losses)), 6) if losses else None,
                "benchmark_excess": round(sum(excess) / len(excess), 6) if excess else None,
                "max_drawdown": drawdown,
                "sample_size": len(closed),
            },
        }

    @staticmethod
    def _with_candidate_counts(
        summary: dict,
        *,
        candidate_count: int,
        rejected_count: int,
    ) -> dict:
        summary["counts"]["total"] += candidate_count
        summary["counts"]["candidates"] += candidate_count
        summary["counts"]["decisions_rejected"] += rejected_count
        return summary

    def _max_drawdown(self, rows: list[dict]) -> float | None:
        if not rows:
            return None
        equity = 0.0
        peak = 0.0
        maximum = 0.0
        for row in sorted(rows, key=lambda item: item.get("closed_at") or ""):
            equity += float(row["net_pnl"] or 0)
            peak = max(peak, equity)
            maximum = max(maximum, peak - equity)
        return round(maximum, 6)

    def _warnings(self, aggregate: dict, by_market: dict) -> list[str]:
        warnings: list[str] = []
        sample = aggregate["metrics"]["sample_size"]
        if sample < 30:
            warnings.append(
                f"Only {sample} closed paper-forward trades are available; at least 30 are required for a directional conclusion."
            )
        if by_market["forex"]["counts"]["closed"] == 0:
            warnings.append("Forex paper-forward evidence has no closed trades yet.")
        return warnings

    def _forex_decision_detail(self, decision: ForexDecision | None) -> dict | None:
        if decision is None:
            return None
        return {
            "id": decision.id,
            "decision_uid": decision.decision_uid,
            "status": decision.status,
            "direction": decision.direction,
            "blockers": decision.blockers or [],
            "proposal": decision.proposal_json or {},
            "risk": decision.risk_json or {},
            "execution": decision.execution_json or {},
            "input_snapshot": decision.input_snapshot or {},
            "decision_timestamp": _iso(decision.decision_timestamp),
        }

    def _forex_events(
        self,
        position: ForexPosition,
        decision: ForexDecision | None,
        evidence: ForexLearningEvidence | None,
    ) -> list[dict]:
        events = []
        if decision is not None:
            events.append(
                {
                    "event_type": "DECISION_CREATED",
                    "timestamp": _iso(decision.decision_timestamp),
                    "price": _float((decision.proposal_json or {}).get("entry")),
                    "reason": "Frozen Forex paper decision.",
                    "payload": {"blockers": decision.blockers or []},
                }
            )
        events.append(
            {
                "event_type": "POSITION_OPENED",
                "timestamp": _iso(position.opened_at),
                "price": _float(position.entry_price),
                "reason": "Simulated Forex execution.",
                "payload": {"quantity_lots": position.quantity_lots},
            }
        )
        if position.closed_at is not None:
            events.append(
                {
                    "event_type": "POSITION_CLOSED",
                    "timestamp": _iso(position.closed_at),
                    "price": _float(position.exit_price),
                    "reason": position.exit_reason,
                    "payload": {"net_pnl": position.net_pnl, "realized_r": position.realized_r},
                }
            )
        if evidence is not None:
            events.append(
                {
                    "event_type": "LEARNING_EVIDENCE_RECORDED",
                    "timestamp": _iso(evidence.created_at),
                    "price": None,
                    "reason": evidence.lesson,
                    "payload": evidence.payload_json or {},
                }
            )
        return events
