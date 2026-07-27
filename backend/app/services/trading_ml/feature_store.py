"""Incremental immutable Polars/Parquet feature-store projection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable, Literal, Protocol

import polars as pl
from sqlalchemy.orm import Session

from .contracts import CATEGORICAL_FEATURES, FeatureSchema, NUMERIC_FEATURES, TradingMLExample
from .dataset import DatasetSlice, TradingMLDatasetRepository


MarketFamily = Literal["equity", "forex"]
_MANIFEST_NAME = "manifest.json"


class DatasetReader(Protocol):
    def read_slice(
        self,
        db: Session | None,
        *,
        market_family: MarketFamily,
        after_cursor: dict[str, object] | None,
        limit: int,
    ) -> DatasetSlice: ...


@dataclass(frozen=True)
class ProjectionResult:
    rows_written: int
    partitions_written: int
    dataset_hash: str
    source_cursor: dict[str, object] | None
    rows_considered: int
    rows_rejected: int
    is_exhausted: bool


class TradingMLFeatureStoreProjector:
    """Projects source-of-truth examples into immutable, append-only Parquet parts."""

    def __init__(
        self,
        *,
        root: Path | str,
        repository: DatasetReader | None = None,
        max_rows_per_projection: int = 5_000,
        max_partition_rows: int = 1_000,
    ) -> None:
        if max_rows_per_projection <= 0 or max_partition_rows <= 0:
            raise ValueError("projection and partition limits must be positive")
        self.root = Path(root)
        self._repository = repository or TradingMLDatasetRepository()
        self._max_rows_per_projection = max_rows_per_projection
        self._max_partition_rows = max_partition_rows

    def project(
        self,
        db: Session | None,
        *,
        market_family: MarketFamily,
        limit: int | None = None,
    ) -> ProjectionResult:
        """Append one bounded source slice; never rehydrate historical store rows."""

        row_limit = min(max(1, limit or self._max_rows_per_projection), self._max_rows_per_projection)
        manifest = self._load_manifest()
        cursor = self._cursor_for(manifest, market_family)
        dataset_slice = self._repository.read_slice(
            db,
            market_family=market_family,
            after_cursor=cursor,
            limit=row_limit,
        )
        unique_examples, rejected_duplicates = _deduplicate_examples(dataset_slice.examples)
        partitions = self._write_partitions(unique_examples, market_family)

        if dataset_slice.next_cursor is not None:
            manifest.setdefault("source_cursors", {})[market_family] = dataset_slice.next_cursor
        manifest["partitions"].extend(partitions)
        manifest["evidence_lane_counts"] = self._evidence_lane_counts(manifest["partitions"])
        manifest["dataset_hash"] = self._dataset_hash(manifest["partitions"])
        self._write_manifest(manifest)
        return ProjectionResult(
            rows_written=sum(partition["rows"] for partition in partitions),
            partitions_written=len(partitions),
            dataset_hash=manifest["dataset_hash"],
            source_cursor=dataset_slice.next_cursor,
            rows_considered=dataset_slice.rows_considered,
            rows_rejected=dataset_slice.rows_rejected + rejected_duplicates,
            is_exhausted=dataset_slice.exhausted,
        )

    def scan(
        self,
        *,
        market_family: MarketFamily,
        columns: Iterable[str] | None = None,
        predicate: pl.Expr | None = None,
    ) -> pl.LazyFrame:
        """Return a lazy scan over requested columns only."""

        manifest = self._load_manifest()
        paths = [
            str(self.root / partition["path"])
            for partition in manifest["partitions"]
            if partition["market_family"] == market_family
        ]
        if not paths:
            frame = pl.LazyFrame(schema=_POLARS_SCHEMA)
        else:
            frame = pl.scan_parquet(paths)
        if predicate is not None:
            frame = frame.filter(predicate)
        if columns is not None:
            frame = frame.select(list(columns))
        return frame

    def manifest(self) -> dict:
        """Return a defensive manifest copy for status and tests."""

        return json.loads(json.dumps(self._load_manifest()))

    def _write_partitions(self, examples: tuple[TradingMLExample, ...], market_family: MarketFamily) -> list[dict]:
        partitions: list[dict] = []
        for year, month, monthly_examples in _examples_by_month(examples):
            for start in range(0, len(monthly_examples), self._max_partition_rows):
                chunk = monthly_examples[start : start + self._max_partition_rows]
                rows = [_row_from_example(example) for example in chunk]
                content_hash = _content_hash(rows)
                directory = self.root / "features" / f"market_family={market_family}" / f"year={year}" / f"month={month:02d}"
                directory.mkdir(parents=True, exist_ok=True)
                filename = f"part-{content_hash}.parquet"
                target = directory / filename
                if not target.exists():
                    temporary = directory / f".{filename}.tmp"
                    _frame_from_rows(rows).write_parquet(temporary, compression="zstd")
                    verified = pl.read_parquet(temporary)
                    if (
                        verified.height != len(rows)
                        or set(verified["source_uid"].to_list()) != {row["source_uid"] for row in rows}
                        or _content_hash(verified.to_dicts()) != content_hash
                    ):
                        temporary.unlink(missing_ok=True)
                        raise RuntimeError("Parquet feature partition verification failed")
                    os.replace(temporary, target)
                partitions.append(
                    {
                        "path": str(target.relative_to(self.root)),
                        "market_family": market_family,
                        "rows": len(rows),
                        "content_hash": content_hash,
                        "source_uid_hash": _source_uid_hash(rows),
                        "evidence_lane_counts": _lane_counts(rows),
                        "created_at": datetime.now(UTC).isoformat(),
                    }
                )
        return partitions

    def _load_manifest(self) -> dict:
        path = self.root / _MANIFEST_NAME
        if not path.exists():
            return {
                "schema_version": FeatureSchema.current().version,
                "schema_hash": FeatureSchema.current().hash,
                "dataset_hash": _dataset_hash(()),
                "partitions": [],
                "source_cursors": {},
                "evidence_lane_counts": {},
            }
        with path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        if manifest.get("schema_hash") != FeatureSchema.current().hash:
            raise RuntimeError("Feature-store schema hash does not match the active feature contract")
        manifest.setdefault("partitions", [])
        manifest.setdefault("source_cursors", {})
        manifest.setdefault("evidence_lane_counts", {})
        return manifest

    def _write_manifest(self, manifest: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / f".{_MANIFEST_NAME}.tmp"
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(manifest, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.root / _MANIFEST_NAME)

    @staticmethod
    def _cursor_for(manifest: dict, market_family: MarketFamily) -> dict[str, object] | None:
        cursor = manifest.get("source_cursors", {}).get(market_family)
        return cursor if isinstance(cursor, dict) else None

    @staticmethod
    def _evidence_lane_counts(partitions: list[dict]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for partition in partitions:
            for lane, count in partition.get("evidence_lane_counts", {}).items():
                counts[lane] = counts.get(lane, 0) + count
        return counts

    @staticmethod
    def _dataset_hash(partitions: Iterable[dict]) -> str:
        return _dataset_hash(partitions)


def _row_from_example(example: TradingMLExample) -> dict:
    row: dict[str, object] = {
        "source_uid": _source_uid(example),
        "source_object_type": example.source_object_type,
        "source_object_id": example.source_object_id,
        "market_family": example.market_family,
        "evidence_lane": example.evidence_lane,
        "decision_timestamp": example.decision_timestamp,
        "outcome_timestamp": example.outcome_timestamp,
        "asset_key": example.asset_key,
        "setup_type": example.setup_type,
        "regime": example.regime,
        "realized_net_r": example.realized_net_r,
        "label_positive_r": example.label_positive_r,
        "benchmark_excess": example.benchmark_excess,
        "sample_weight": example.sample_weight,
        "feature_schema_version": FeatureSchema.current().version,
        "feature_schema_hash": FeatureSchema.current().hash,
        "feature_hash": _feature_hash(example),
    }
    for name in NUMERIC_FEATURES:
        row[name] = example.features.get(name)
    for name in CATEGORICAL_FEATURES:
        row[name] = example.features.get(name, "unknown")
    return row


def _source_uid(example: TradingMLExample) -> str:
    return f"{example.source_object_type}:{example.source_object_id}"


def _feature_hash(example: TradingMLExample) -> str:
    return hashlib.sha256(
        json.dumps(dict(example.features), sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _content_hash(rows: list[dict]) -> str:
    serialized = json.dumps(
        rows,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda value: value.isoformat() if isinstance(value, datetime) else str(value),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _source_uid_hash(rows: list[dict]) -> str:
    source_uids = sorted(str(row["source_uid"]) for row in rows)
    return hashlib.sha256("\n".join(source_uids).encode("utf-8")).hexdigest()


def _deduplicate_examples(examples: tuple[TradingMLExample, ...]) -> tuple[tuple[TradingMLExample, ...], int]:
    seen: set[str] = set()
    unique: list[TradingMLExample] = []
    for example in examples:
        source_uid = _source_uid(example)
        if source_uid in seen:
            continue
        seen.add(source_uid)
        unique.append(example)
    return tuple(unique), len(examples) - len(unique)


def _dataset_hash(partitions: Iterable[dict]) -> str:
    payload = [
        {
            "content_hash": partition["content_hash"],
            "market_family": partition["market_family"],
            "path": partition["path"],
            "rows": partition["rows"],
        }
        for partition in partitions
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _lane_counts(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        lane = str(row["evidence_lane"])
        counts[lane] = counts.get(lane, 0) + 1
    return counts


def _examples_by_month(examples: tuple[TradingMLExample, ...]) -> list[tuple[int, int, tuple[TradingMLExample, ...]]]:
    buckets: dict[tuple[int, int], list[TradingMLExample]] = {}
    for example in examples:
        bucket = (example.decision_timestamp.year, example.decision_timestamp.month)
        buckets.setdefault(bucket, []).append(example)
    return [
        (year, month, tuple(bucket_examples))
        for (year, month), bucket_examples in sorted(buckets.items())
    ]


_POLARS_SCHEMA = {
    "source_uid": pl.String,
    "source_object_type": pl.String,
    "source_object_id": pl.String,
    "market_family": pl.String,
    "evidence_lane": pl.String,
    "decision_timestamp": pl.Datetime,
    "outcome_timestamp": pl.Datetime,
    "asset_key": pl.String,
    "setup_type": pl.String,
    "regime": pl.String,
    "realized_net_r": pl.Float64,
    "label_positive_r": pl.Int8,
    "benchmark_excess": pl.Float64,
    "sample_weight": pl.Float64,
    "feature_schema_version": pl.String,
    "feature_schema_hash": pl.String,
    "feature_hash": pl.String,
    **{name: pl.Float64 for name in NUMERIC_FEATURES},
    **{name: pl.String for name in CATEGORICAL_FEATURES},
}


def _frame_from_rows(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=_POLARS_SCHEMA, strict=False)
