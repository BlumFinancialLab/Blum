from __future__ import annotations

from pathlib import Path
import shutil
from typing import Literal

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, ConfigDict, Field

from model_release.evaluation.metrics import EvaluationMetrics


class PromotionDecision(BaseModel):
    promoted: bool
    reasons: list[str]
    aggregate_delta: float
    base_revision: str
    candidate_revision: str


class MissingEvaluationEvidence(ValueError):
    pass


class ReleaseEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_size: int = Field(gt=0)
    base_aggregate_score: float = Field(ge=0, le=1)
    candidate_aggregate_score: float = Field(ge=0, le=1)
    aggregate_delta: float
    no_fabrication: float = Field(ge=0, le=1)
    structured_validity: float = Field(ge=0, le=1)
    calibration_error: float = Field(ge=0, le=1)
    calibration_sample_size: int = Field(default=0, ge=0)
    trace_url: str = Field(min_length=1)


class ReleaseManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(pattern=r"^blum-finance-release-v1$")
    model_repository: str = Field(pattern=r"^Italianhype/Blum$")
    base_model: str = Field(
        pattern=r"^(Qwen/Qwen3-4B|mlx-community/Qwen3-4B-4bit)$"
    )
    base_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    candidate_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    dataset_repository: str
    dataset_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    runtime: Literal["transformers", "mlx"] = "transformers"
    promoted: bool
    evaluation_validated: bool
    transformers_smoke_test_passed: bool
    gguf_smoke_test_passed: bool
    mlx_smoke_test_passed: bool = False
    evaluation: ReleaseEvaluation
    artifact_hashes: dict[str, str]


def promotion_gate(
    *,
    base: EvaluationMetrics,
    candidate: EvaluationMetrics,
    minimum_test_samples: int = 50,
) -> PromotionDecision:
    reasons: list[str] = []
    if candidate.sample_size < minimum_test_samples:
        reasons.append("insufficient_test_sample")
    if candidate.aggregate_score <= base.aggregate_score:
        reasons.append("no_target_metric_improvement")
    if candidate.aggregate_ci_lower < base.aggregate_ci_lower:
        reasons.append("aggregate_confidence_interval_regression")
    if candidate.no_fabrication < base.no_fabrication - 0.02:
        reasons.append("no_fabrication_regression")
    if candidate.no_fabrication < 0.90:
        reasons.append("no_fabrication_below_gate")
    if candidate.structured_validity < 0.95:
        reasons.append("structured_validity_below_gate")
    if candidate.risk_completeness < base.risk_completeness - 0.02:
        reasons.append("risk_completeness_regression")
    if candidate.invalidation_completeness < base.invalidation_completeness - 0.02:
        reasons.append("invalidation_completeness_regression")
    if (
        base.calibration_sample_size > 0
        and candidate.calibration_sample_size == 0
    ):
        reasons.append("confidence_calibration_evidence_missing")
    elif (
        candidate.calibration_sample_size > 0
        and base.calibration_sample_size > 0
        and candidate.calibration_error > base.calibration_error + 0.02
    ):
        reasons.append("confidence_calibration_regression")
    return PromotionDecision(
        promoted=not reasons,
        reasons=reasons,
        aggregate_delta=round(
            candidate.aggregate_score - base.aggregate_score,
            6,
        ),
        base_revision=base.model_revision,
        candidate_revision=candidate.model_revision,
    )


def render_model_card(
    manifest: ReleaseManifest,
    *,
    output: Path,
    template: Path | None = None,
) -> Path:
    if not manifest.evaluation_validated:
        raise MissingEvaluationEvidence(
            "A model card cannot be rendered without validated evaluation evidence."
        )
    if not manifest.promoted:
        raise MissingEvaluationEvidence(
            "A rejected candidate cannot be rendered as the primary BLUM Finance model."
        )
    template_path = template or (
        Path(__file__).resolve().parents[1] / "model_card" / "README.md.j2"
    )
    environment = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    rendered = environment.get_template(template_path.name).render(
        release=manifest.model_dump(mode="json")
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    return output


def assemble_repository(
    *,
    merged_model_dir: Path,
    staging_dir: Path,
    manifest: ReleaseManifest,
) -> Path:
    required = {"config.json", "tokenizer_config.json"}
    missing = sorted(
        name for name in required if not (merged_model_dir / name).is_file()
    )
    weights = list(merged_model_dir.glob("*.safetensors"))
    if missing or not weights:
        raise FileNotFoundError(
            f"Merged model is incomplete: missing={missing}, safetensors={len(weights)}."
        )
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    shutil.copytree(merged_model_dir, staging_dir)
    render_model_card(manifest, output=staging_dir / "README.md")
    release_root = Path(__file__).resolve().parents[1]
    license_source = release_root / "model_card" / "LICENSE"
    shutil.copy2(license_source, staging_dir / "LICENSE")
    shutil.copy2(release_root / "pyproject.toml", staging_dir / "pyproject.toml")
    shutil.copy2(release_root / "CONTRIBUTING.md", staging_dir / "CONTRIBUTING.md")
    shutil.copytree(
        release_root / "blum_finance",
        staging_dir / "blum_finance",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (staging_dir / "release_manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return staging_dir
