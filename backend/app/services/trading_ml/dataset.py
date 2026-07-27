"""Bounded, point-in-time retrieval of labeled trading ML examples."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ForexDecision, ForexLearningEvidence, HistoricalPrediction, HyperbolicReplayTrade, PredictionOutcome

from .contracts import TradingMLExample
from .features import IneligibleFeatureDataError, TradingMLFeatureBuilder, UnlabeledFeatureDataError


MarketFamily = Literal["equity", "forex"]


@dataclass(frozen=True)
class DatasetSlice:
    """A bounded page of validated examples and its resumable source cursor."""

    examples: tuple[TradingMLExample, ...]
    next_cursor: dict[str, object] | None
    rows_considered: int
    rows_rejected: int
    exhausted: bool


class TradingMLDatasetRepository:
    """Reads terminal evidence without hydrating an unbounded ORM collection."""

    _SOURCES: dict[MarketFamily, tuple[str, ...]] = {
        "equity": ("historical_predictions", "hyperbolic_replay_trades"),
        "forex": ("forex_decisions", "hyperbolic_replay_trades"),
    }

    def __init__(self, *, builder: TradingMLFeatureBuilder | None = None) -> None:
        self._builder = builder or TradingMLFeatureBuilder()

    def read_slice(
        self,
        db: Session,
        *,
        market_family: MarketFamily,
        after_cursor: dict[str, object] | None,
        limit: int,
    ) -> DatasetSlice:
        """Return at most ``limit`` terminal examples after a persisted cursor.

        Each source query applies its primary-key predicate, ordering, and limit
        before SQLAlchemy creates ORM objects. Invalid historical rows are
        counted and skipped, never repaired or guessed at read time.
        """

        if limit <= 0:
            raise ValueError("limit must be positive")
        sources = self._SOURCES[market_family]
        source_index, source_offsets = self._cursor_position(sources, after_cursor)
        examples: list[TradingMLExample] = []
        rows_considered = 0
        rows_rejected = 0
        last_cursor: dict[str, object] | None = after_cursor

        for offset in range(len(sources)):
            if len(examples) >= limit:
                break
            current_index = (source_index + offset) % len(sources)
            source = sources[current_index]
            remaining = limit - len(examples)
            records = self._read_source(
                db,
                source=source,
                market_family=market_family,
                after_id=source_offsets[source],
                limit=remaining,
            )
            rows_considered += len(records)

            for source_id, source_records in records:
                source_offsets[source] = source_id
                last_cursor = self._cursor(source, source_offsets)
                try:
                    examples.append(self._build_example(source, source_records))
                except (IneligibleFeatureDataError, UnlabeledFeatureDataError, ValueError):
                    rows_rejected += 1

            if len(records) == remaining:
                return DatasetSlice(
                    examples=tuple(examples),
                    next_cursor=last_cursor,
                    rows_considered=rows_considered,
                    rows_rejected=rows_rejected,
                    exhausted=False,
                )

            next_source = sources[(current_index + 1) % len(sources)]
            last_cursor = self._cursor(next_source, source_offsets)

        return DatasetSlice(
            examples=tuple(examples),
            next_cursor=last_cursor,
            rows_considered=rows_considered,
            rows_rejected=rows_rejected,
            exhausted=True,
        )

    @staticmethod
    def _cursor_position(sources: tuple[str, ...], cursor: dict[str, object] | None) -> tuple[int, dict[str, int]]:
        offsets = {source: 0 for source in sources}
        if not cursor:
            return 0, offsets
        raw_offsets = cursor.get("source_offsets")
        if isinstance(raw_offsets, dict):
            for source in sources:
                try:
                    offsets[source] = max(0, int(raw_offsets.get(source, 0)))
                except (TypeError, ValueError):
                    pass
        source_table = str(cursor.get("source_table", sources[0]))
        try:
            source_index = sources.index(source_table)
        except ValueError:
            return 0, offsets
        try:
            offsets[source_table] = max(0, int(cursor.get("last_source_id", offsets[source_table])))
        except (TypeError, ValueError):
            pass
        return source_index, offsets

    @staticmethod
    def _cursor(source_table: str, source_offsets: dict[str, int]) -> dict[str, object]:
        return {
            "source_table": source_table,
            "last_source_id": source_offsets[source_table],
            "source_offsets": dict(source_offsets),
        }

    def _read_source(
        self,
        db: Session,
        *,
        source: str,
        market_family: MarketFamily,
        after_id: int,
        limit: int,
    ) -> list[tuple[int, tuple[object, ...]]]:
        if source == "historical_predictions":
            latest_outcome_id = (
                select(func.max(PredictionOutcome.id))
                .where(
                    PredictionOutcome.prediction_id == HistoricalPrediction.id,
                    PredictionOutcome.evaluation_date.is_not(None),
                )
                .correlate(HistoricalPrediction)
                .scalar_subquery()
            )
            rows = db.execute(
                select(HistoricalPrediction, PredictionOutcome)
                .join(PredictionOutcome, PredictionOutcome.id == latest_outcome_id)
                .where(HistoricalPrediction.id > after_id)
                .order_by(HistoricalPrediction.id)
                .limit(limit)
            ).all()
            return [(prediction.id, (prediction, outcome)) for prediction, outcome in rows]

        if source == "forex_decisions":
            latest_evidence_id = (
                select(func.max(ForexLearningEvidence.id))
                .where(
                    ForexLearningEvidence.decision_id == ForexDecision.id,
                    ForexLearningEvidence.realized_result.is_not(None),
                )
                .correlate(ForexDecision)
                .scalar_subquery()
            )
            rows = db.execute(
                select(ForexDecision, ForexLearningEvidence)
                .join(ForexLearningEvidence, ForexLearningEvidence.id == latest_evidence_id)
                .where(
                    ForexDecision.id > after_id,
                    ForexLearningEvidence.realized_result.is_not(None),
                )
                .order_by(ForexDecision.id)
                .limit(limit)
            ).all()
            return [(decision.id, (decision, evidence)) for decision, evidence in rows]

        if source == "hyperbolic_replay_trades":
            market_filter = (
                func.upper(HyperbolicReplayTrade.market).in_(("FOREX", "FX"))
                if market_family == "forex"
                else func.upper(HyperbolicReplayTrade.market).not_in(("FOREX", "FX"))
            )
            rows = db.scalars(
                select(HyperbolicReplayTrade)
                .where(
                    HyperbolicReplayTrade.id > after_id,
                    HyperbolicReplayTrade.state == "REPLAY_EVALUATED",
                    HyperbolicReplayTrade.r_multiple.is_not(None),
                    HyperbolicReplayTrade.exit_timestamp.is_not(None),
                    market_filter,
                )
                .order_by(HyperbolicReplayTrade.id)
                .limit(limit)
            ).all()
            return [(trade.id, (trade,)) for trade in rows]

        raise ValueError(f"Unsupported trading ML evidence source: {source}")

    def _build_example(self, source: str, records: tuple[object, ...]) -> TradingMLExample:
        if source == "historical_predictions":
            prediction, outcome = records
            return self._builder.from_equity(prediction, outcome)  # type: ignore[arg-type]
        if source == "forex_decisions":
            decision, evidence = records
            return self._builder.from_forex(decision, evidence)  # type: ignore[arg-type]
        if source == "hyperbolic_replay_trades":
            return self._builder.from_replay(records[0])  # type: ignore[arg-type]
        raise ValueError(f"Unsupported trading ML evidence source: {source}")
