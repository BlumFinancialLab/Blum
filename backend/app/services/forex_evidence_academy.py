from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from hashlib import sha256
from math import sqrt
from statistics import mean

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from app.models import (
    ForexContextualMemory,
    ForexCurriculumAssignment,
    ForexKnowledgeSource,
    ForexLearningEvidence,
    HyperbolicReplayTrade,
)
from app.services.executable_strategy import canonical_strategy_spec
from app.services.forex_contracts import pair_config


CURATED_FOREX_SOURCES = (
    {
        "source_key": "ecb_sdmx",
        "title": "ECB Data Portal SDMX",
        "provider": "ECB",
        "source_type": "AUTHORITATIVE_CONTEXT",
        "source_url": "https://data-api.ecb.europa.eu/service/",
        "license": "official-public-data",
        "schema_json": {"domains": ["exchange_rates", "policy_rates", "effective_exchange_rates"], "point_in_time": True},
    },
    {
        "source_key": "fred_alfred",
        "title": "FRED and ALFRED macroeconomic series",
        "provider": "FRED",
        "source_type": "AUTHORITATIVE_CONTEXT",
        "source_url": "https://fred.stlouisfed.org/docs/api/fred/",
        "license": "official-public-data",
        "schema_json": {"domains": ["interest_rates", "inflation", "employment", "risk_appetite"], "vintages": "ALFRED"},
    },
    {
        "source_key": "cftc_cot",
        "title": "CFTC Commitments of Traders",
        "provider": "CFTC",
        "source_type": "AUTHORITATIVE_CONTEXT",
        "source_url": "https://publicreporting.cftc.gov/",
        "license": "us-government-public-data",
        "schema_json": {"domains": ["futures_positioning", "open_interest"], "frequency": "weekly"},
    },
    {
        "source_key": "hf_histdata_fx_1m",
        "title": "HistData FX one-minute OHLC and gap records",
        "provider": "HUGGING_FACE",
        "source_type": "REPLAY_BACKFILL_CANDIDATE",
        "source_url": "https://huggingface.co/datasets/elthariel/histdata_fx_1m",
        "license": "source-license-review-required",
        "schema_json": {"columns": ["ts", "open", "high", "low", "close", "volume"], "timezone": "UTC", "gap_records": True},
    },
    {
        "source_key": "zenodo_forex_sentiment_7976208",
        "title": "Manually annotated Forex news sentiment",
        "provider": "ZENODO",
        "source_type": "EVALUATION_CORPUS",
        "source_url": "https://doi.org/10.5281/zenodo.7976208",
        "license": "record-license-review-required",
        "schema_json": {"rows": 2291, "annotation": "human", "use": "sentiment_evaluation"},
    },
    {
        "source_key": "hf_forex_factory_calendar",
        "title": "Forex Factory historical calendar mirror",
        "provider": "HUGGING_FACE",
        "source_type": "CALENDAR_BACKFILL_CANDIDATE",
        "source_url": "https://huggingface.co/datasets/Tropstan/Forex_Factory_Calendar",
        "license": "mit-dataset-card",
        "schema_json": {"domains": ["economic_calendar", "event_surprise"], "requires_cross_validation": True},
    },
)

SETUP_CURRICULUM = (
    ("momentum_breakout", "trend", "Trade only a confirmed range break with multi-timeframe alignment and net edge after costs."),
    ("pullback_to_trend", "trend", "Test continuation after a controlled retracement and structural reclaim."),
    ("mean_reversion", "range", "Test reversion only inside a validated range and outside major event windows."),
    ("volatility_expansion", "compression", "Test expansion after measurable compression with session liquidity confirmation."),
    ("session_breakout", "session_transition", "Test London and overlap breakouts while rejecting thin-session moves."),
    ("news_reaction", "event", "Study post-event reaction only after the configured embargo and observed spread normalization."),
)
SESSIONS = ("LONDON", "LONDON_NEW_YORK_OVERLAP", "NEW_YORK")
CANONICAL_SETUP = {
    "momentum_breakout": "intraday_breakout",
    "pullback_to_trend": "pullback",
    "mean_reversion": "mean_reversion",
    "volatility_expansion": "intraday_breakout",
    "session_breakout": "intraday_breakout",
    "news_reaction": "intraday_trend",
}


class ForexKnowledgeCatalogService:
    def refresh(self, db: Session, *, validate: bool = False) -> dict:
        now = datetime.utcnow()
        for payload in CURATED_FOREX_SOURCES:
            row = db.scalar(select(ForexKnowledgeSource).where(ForexKnowledgeSource.source_key == payload["source_key"]))
            values = {
                **payload,
                "usage_policy": {
                    "edge_evidence": False,
                    "direct_confidence_effect": False,
                    "allowed_uses": ["feature_context", "research_curriculum", "model_evaluation"],
                    "requires_point_in_time_validation": True,
                },
                "validation_status": "METADATA_VALIDATED" if validate else "CATALOGED",
                "validation_notes": ["Network validation is background-only"] if not validate else [],
                "last_validated_at": now if validate else None,
            }
            if row is None:
                row = ForexKnowledgeSource(**values)
                db.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        db.commit()
        return {
            "status": "COMPLETED",
            "sources_cataloged": len(CURATED_FOREX_SOURCES),
            "network_used": False,
            "policy": "Knowledge sources cannot directly alter executable confidence.",
        }


class ForexCurriculumPlanner:
    def generate(self, db: Session, *, limit: int = 12) -> list[ForexCurriculumAssignment]:
        limit = max(1, min(int(limit), 48))
        evidence_counts = self._evidence_counts(db)
        candidates = []
        pairs = pair_config.all()
        for index in range(max(limit * 3, len(pairs))):
            pair = pairs[index % len(pairs)]
            setup, regime, hypothesis = SETUP_CURRICULUM[index % len(SETUP_CURRICULUM)]
            session = SESSIONS[index % len(SESSIONS)]
            context = (pair.ticker, session, regime, setup)
            observed = evidence_counts.get(context, 0)
            sample_gap = max(0, 300 - observed)
            broad = index % 4 == 0
            priority_type = "BROAD_EXPLORATION" if broad else "SAMPLE_GAP"
            information_gain = min(1.0, 0.35 + sample_gap / 500.0 + (0.1 if broad else 0.0))
            priority = information_gain * 100.0
            candidates.append((priority, context, priority_type, hypothesis, sample_gap))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        output = []
        used_pairs: set[str] = set()
        selected = []
        for candidate in candidates:
            if len(selected) >= limit:
                break
            if len(used_pairs) < min(3, limit) and candidate[1][0] in used_pairs:
                continue
            selected.append(candidate)
            used_pairs.add(candidate[1][0])
        if len(selected) < limit:
            selected_keys = {item[1] for item in selected}
            selected.extend(
                [item for item in candidates if item[1] not in selected_keys][
                    : limit - len(selected)
                ]
            )
        for priority, context, priority_type, hypothesis, sample_gap in selected:
            pair, session, regime, setup = context
            key = sha256("|".join(context).encode()).hexdigest()[:32]
            row = db.scalar(select(ForexCurriculumAssignment).where(ForexCurriculumAssignment.assignment_key == key))
            spec = canonical_strategy_spec(CANONICAL_SETUP[setup]).to_payload()
            replay_spec = {
                **spec,
                "market_filter": "forex_only",
                "supported_asset_classes": ["Forex"],
                "timeframe_stack": ["1h", "15m", "5m", "1m"],
                "required_timeframes": ["1h", "15m", "5m", "1m"],
                "execution_timeframe": "1m",
                "pair": pair,
                "session": session,
                "regime": regime,
                "curriculum_hypothesis": hypothesis,
                "minimum_relative_volume": 0.0,
                "minimum_stop_percent": 0.0005,
            }
            values = {
                "priority_type": priority_type,
                "pair": pair,
                "session": session,
                "regime": regime,
                "setup_family": setup,
                "hypothesis": hypothesis,
                "reason": f"{priority_type.lower()} with {sample_gap} samples missing from the 300-sample research target.",
                "expected_information_gain": information_gain,
                "priority_score": priority,
                "sample_gap": sample_gap,
                "status": "ACTIVE",
                "replay_spec_json": replay_spec,
            }
            if row is None:
                row = ForexCurriculumAssignment(assignment_key=key, **values)
                db.add(row)
            else:
                for field, value in values.items():
                    setattr(row, field, value)
            output.append(row)
        db.commit()
        return output

    @staticmethod
    def active(db: Session, *, limit: int = 4) -> list[ForexCurriculumAssignment]:
        return list(
            db.scalars(
                select(ForexCurriculumAssignment)
                .where(ForexCurriculumAssignment.status == "ACTIVE")
                .order_by(desc(ForexCurriculumAssignment.priority_score), ForexCurriculumAssignment.id)
                .limit(max(1, min(limit, 12)))
            ).all()
        )

    @staticmethod
    def _evidence_counts(db: Session) -> dict[tuple[str, str, str, str], int]:
        rows = db.scalars(select(ForexLearningEvidence).order_by(desc(ForexLearningEvidence.id)).limit(5000)).all()
        result: dict[tuple[str, str, str, str], int] = defaultdict(int)
        for row in rows:
            result[(row.pair, row.session or "UNKNOWN", row.regime or "UNKNOWN", row.setup_family or "UNKNOWN")] += 1
        return result


class ForexMemoryCompiler:
    minimum_context_samples = 30

    def compile(self, db: Session, *, limit: int = 1000) -> dict:
        forex_rows = db.scalars(
            select(ForexLearningEvidence)
            .where(ForexLearningEvidence.evidence_type.in_(("REPLAY_FOREX", "PAPER_FORWARD_FOREX")))
            .order_by(desc(ForexLearningEvidence.id))
            .limit(max(1, min(limit, 5000)))
        ).all()
        replay_rows = db.scalars(
            select(HyperbolicReplayTrade)
            .where(
                HyperbolicReplayTrade.state == "REPLAY_EVALUATED",
                HyperbolicReplayTrade.evidence_type == "REPLAY_EVIDENCE",
                or_(HyperbolicReplayTrade.market == "FOREX", HyperbolicReplayTrade.ticker.like("%=X")),
            )
            .order_by(desc(HyperbolicReplayTrade.id))
            .limit(max(1, min(limit, 5000)))
        ).all()
        records = [
            {
                "source_id": f"forex:{row.id}",
                "strategy_id": row.strategy_id,
                "session": row.session or "UNKNOWN",
                "regime": row.regime or "UNKNOWN",
                "setup_family": row.setup_family or "UNKNOWN",
                "outcome": row.outcome,
                "realized_r": row.realized_result,
                "benchmark_excess": (row.payload_json or {}).get("benchmark_excess"),
            }
            for row in forex_rows
        ]
        records.extend(
            {
                "source_id": f"replay:{row.id}",
                "strategy_id": row.strategy_fingerprint,
                "session": (row.decision_payload or {}).get("session") or "UNKNOWN",
                "regime": (row.decision_payload or {}).get("regime") or "UNKNOWN",
                "setup_family": row.setup_type or "UNKNOWN",
                "outcome": "WIN" if float(row.r_multiple or 0.0) > 0 else "LOSS" if float(row.r_multiple or 0.0) < 0 else "BREAKEVEN",
                "realized_r": row.r_multiple,
                "benchmark_excess": row.benchmark_excess,
            }
            for row in replay_rows
        )
        groups: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
        for row in records:
            groups[(row["strategy_id"], row["session"], row["regime"], row["setup_family"])].append(row)
        compiled = 0
        for context, evidence in groups.items():
            closed = [row for row in evidence if row["outcome"] in {"WIN", "LOSS", "BREAKEVEN"} and row["realized_r"] is not None]
            values = [float(row["realized_r"]) for row in closed]
            benchmark = [float(row["benchmark_excess"] or 0.0) for row in closed]
            expectancy = mean(values) if values else None
            benchmark_excess = mean(benchmark) if benchmark else None
            interval = self._confidence_interval(values)
            cost_failures = sum(row["outcome"] == "EDGE_DESTROYED_BY_COSTS" for row in evidence)
            eligible = bool(
                len(closed) >= self.minimum_context_samples
                and expectancy is not None
                and expectancy > 0
                and benchmark_excess is not None
                and benchmark_excess > 0
                and interval[0] > 0
            )
            adjustment = min(0.08, 0.02 + len(closed) / 3000.0 + max(0.0, expectancy or 0.0) * 0.05) if eligible else 0.0
            strategy_id, session, regime, setup = context
            key = "|".join(context)
            row = db.scalar(select(ForexContextualMemory).where(ForexContextualMemory.memory_key == key))
            values_to_store = {
                "strategy_id": strategy_id,
                "pair_family": "MULTI_PAIR",
                "session": session,
                "regime": regime,
                "setup_family": setup,
                "sample_size": len(closed),
                "win_rate": (sum(item["outcome"] == "WIN" for item in closed) / len(closed)) if closed else None,
                "net_expectancy_r": expectancy,
                "benchmark_excess": benchmark_excess,
                "cost_failure_rate": cost_failures / len(evidence) if evidence else None,
                "confidence_interval_json": {"lower": interval[0], "upper": interval[1]},
                "evidence_grade": "CONTEXT_ELIGIBLE" if eligible else "LEARNING_ONLY",
                "confidence_adjustment": adjustment,
                "source_evidence_ids": [item["source_id"] for item in evidence[:100]],
                "explanation": (
                    f"Validated contextual edge across {len(closed)} outcomes."
                    if eligible
                    else f"Learning-only context: {len(closed)} of {self.minimum_context_samples} required outcomes."
                ),
                "compiled_at": datetime.utcnow(),
            }
            if row is None:
                row = ForexContextualMemory(memory_key=key, **values_to_store)
                db.add(row)
            else:
                for field, value in values_to_store.items():
                    setattr(row, field, value)
            compiled += 1
        db.commit()
        return {
            "status": "COMPLETED",
            "cells_compiled": compiled,
            "evidence_rows_read": len(records),
            "paper_rows_read": len(forex_rows),
            "replay_rows_read": len(replay_rows),
        }

    def context_for(
        self,
        db: Session,
        *,
        strategy_id: str,
        pair: str,
        session: str,
        regime: str,
        setup_family: str,
    ) -> dict:
        row = db.scalar(
            select(ForexContextualMemory)
            .where(
                ForexContextualMemory.strategy_id == strategy_id,
                ForexContextualMemory.session == session,
                ForexContextualMemory.regime == regime,
                ForexContextualMemory.setup_family == setup_family,
            )
            .order_by(desc(ForexContextualMemory.sample_size), desc(ForexContextualMemory.updated_at))
            .limit(1)
        )
        if row is None:
            return {"status": "NO_CONTEXT", "pair": pair, "confidence_adjustment": 0.0}
        return {
            "status": row.evidence_grade,
            "memory_id": row.id,
            "sample_size": row.sample_size,
            "net_expectancy_r": row.net_expectancy_r,
            "benchmark_excess": row.benchmark_excess,
            "confidence_adjustment": row.confidence_adjustment if row.evidence_grade == "CONTEXT_ELIGIBLE" else 0.0,
            "explanation": row.explanation,
            "pair": pair,
        }

    @staticmethod
    def _confidence_interval(values: list[float]) -> tuple[float, float]:
        if not values:
            return 0.0, 0.0
        average = mean(values)
        if len(values) == 1:
            return average, average
        variance = sum((value - average) ** 2 for value in values) / (len(values) - 1)
        margin = 1.96 * sqrt(variance) / sqrt(len(values))
        return average - margin, average + margin


class ForexEvidenceAcademyService:
    def run_background_slice(self, db: Session, *, max_assignments: int = 12) -> dict:
        catalog = ForexKnowledgeCatalogService().refresh(db, validate=False)
        assignments = ForexCurriculumPlanner().generate(db, limit=max_assignments)
        memory = ForexMemoryCompiler().compile(db)
        return {
            "status": "COMPLETED",
            "catalog": catalog,
            "curriculum": {"assignments_created": len(assignments)},
            "memory": memory,
        }
