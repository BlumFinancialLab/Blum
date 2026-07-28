from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


COMMIT_PATTERN = r"^[0-9a-f]{40}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"


class DatasetSplit(str, Enum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class EvidenceReference(BaseModel):
    source_type: str = Field(min_length=1)
    source_id: str = Field(min_length=1)


class EvidenceBundle(BaseModel):
    supporting: list[str] = Field(default_factory=list)
    contradicting: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    provenance: list[EvidenceReference] = Field(min_length=1)


class OutcomeBundle(BaseModel):
    status: Literal["mature", "pending", "inconclusive"]
    label: str = Field(min_length=1)
    benchmark_relative_return: float | None = None


class QualityBundle(BaseModel):
    final_score: float = Field(ge=0, le=100)
    data_quality_score: float = Field(ge=0, le=100)
    contradiction_handling_score: float = Field(ge=0, le=100)
    confidence_calibration_score: float = Field(ge=0, le=100)


class ReleaseExample(BaseModel):
    schema_version: Literal["blum-finance-reasoning-v1"]
    example_id: str = Field(min_length=1)
    source_record_id: int = Field(gt=0)
    source_revision: str = Field(pattern=COMMIT_PATTERN)
    created_at: datetime
    ticker: str = Field(min_length=1, max_length=32)
    thesis_lineage_id: str = Field(min_length=1)
    split: DatasetSplit
    task_type: str = Field(min_length=1)
    messages: list[Message] = Field(min_length=2)
    evidence: EvidenceBundle
    outcome: OutcomeBundle
    quality: QualityBundle
    content_hash: str = Field(pattern=SHA256_PATTERN)


class DateRange(BaseModel):
    start: datetime
    end: datetime


class ReleaseManifest(BaseModel):
    schema_version: Literal["blum-finance-manifest-v1"]
    source_revision: str = Field(pattern=COMMIT_PATTERN)
    base_model: Literal["Qwen/Qwen3-4B"]
    generated_at: datetime
    split_counts: dict[DatasetSplit, int]
    split_date_ranges: dict[DatasetSplit, DateRange]
    exclusion_counts: dict[str, int]
    dataset_sha256: str = Field(pattern=SHA256_PATTERN)
