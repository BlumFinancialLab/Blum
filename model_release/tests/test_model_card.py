from __future__ import annotations

from pathlib import Path

import pytest

from model_release.release.build_repository import (
    MissingEvaluationEvidence,
    ReleaseManifest,
    render_model_card,
)
from model_release.release.publish import CandidateNotPromoted, validate_publication


def manifest(**overrides: object) -> ReleaseManifest:
    payload = {
        "schema_version": "blum-finance-release-v1",
        "model_repository": "Italianhype/Blum",
        "base_model": "Qwen/Qwen3-4B",
        "base_revision": "a" * 40,
        "candidate_revision": "b" * 40,
        "dataset_repository": "Italianhype/Blum-Finance-Reasoning",
        "dataset_revision": "c" * 40,
        "promoted": True,
        "evaluation_validated": True,
        "transformers_smoke_test_passed": True,
        "gguf_smoke_test_passed": True,
        "evaluation": {
            "sample_size": 120,
            "base_aggregate_score": 0.61,
            "candidate_aggregate_score": 0.68,
            "aggregate_delta": 0.07,
            "no_fabrication": 0.94,
            "structured_validity": 0.98,
            "calibration_error": 0.10,
            "trace_url": "https://huggingface.co/datasets/Italianhype/Blum-Finance-Reasoning",
        },
        "artifact_hashes": {"model.safetensors": "d" * 64},
    }
    payload.update(overrides)
    return ReleaseManifest.model_validate(payload)


def test_model_card_requires_real_evaluation_values(tmp_path) -> None:
    release = manifest(evaluation_validated=False)

    with pytest.raises(MissingEvaluationEvidence):
        render_model_card(release, output=tmp_path / "README.md")


def test_model_card_contains_discoverability_and_limitations(tmp_path) -> None:
    output = tmp_path / "README.md"

    render_model_card(manifest(), output=output)
    text = output.read_text(encoding="utf-8")

    assert "BLUM Finance 4B" in text
    assert "financial-reasoning" in text
    assert "Qwen/Qwen3-4B" in text
    assert "0.68" in text
    assert "does not prove trading alpha" in text
    assert "Not measured (0 labeled outcomes)" in text
    assert "TODO" not in text


def test_publish_refuses_unpromoted_candidate(tmp_path) -> None:
    release = manifest(promoted=False)

    with pytest.raises(CandidateNotPromoted):
        validate_publication(
            release,
            repository_dir=tmp_path,
            confirmed_repository="Italianhype/Blum",
            authenticated_user="Italianhype",
        )


@pytest.mark.parametrize(
    "field, message",
    [
        ("transformers_smoke_test_passed", "Transformers"),
        ("gguf_smoke_test_passed", "GGUF"),
    ],
)
def test_publish_requires_smoke_tests(
    tmp_path,
    field: str,
    message: str,
) -> None:
    release = manifest(**{field: False})

    with pytest.raises(CandidateNotPromoted, match=message):
        validate_publication(
            release,
            repository_dir=tmp_path,
            confirmed_repository="Italianhype/Blum",
            authenticated_user="Italianhype",
        )


def test_publish_requires_exact_repository_confirmation(tmp_path) -> None:
    release = manifest()
    (tmp_path / "model.safetensors").write_bytes(b"weights")

    with pytest.raises(ValueError, match="confirmation"):
        validate_publication(
            release,
            repository_dir=tmp_path,
            confirmed_repository="Italianhype/Other",
            authenticated_user="Italianhype",
        )


def test_mlx_release_requires_only_mlx_smoke_test(tmp_path) -> None:
    release = manifest(
        runtime="mlx",
        base_model="mlx-community/Qwen3-4B-4bit",
        transformers_smoke_test_passed=False,
        gguf_smoke_test_passed=False,
        mlx_smoke_test_passed=True,
    )
    weights = tmp_path / "model.safetensors"
    weights.write_bytes(b"weights")
    release.artifact_hashes["model.safetensors"] = __import__("hashlib").sha256(
        weights.read_bytes()
    ).hexdigest()

    validate_publication(
        release,
        repository_dir=tmp_path,
        confirmed_repository="Italianhype/Blum",
        authenticated_user="Italianhype",
    )


def test_mlx_release_refuses_missing_mlx_smoke_test(tmp_path) -> None:
    release = manifest(
        runtime="mlx",
        base_model="mlx-community/Qwen3-4B-4bit",
        transformers_smoke_test_passed=False,
        gguf_smoke_test_passed=False,
        mlx_smoke_test_passed=False,
    )

    with pytest.raises(CandidateNotPromoted, match="MLX"):
        validate_publication(
            release,
            repository_dir=tmp_path,
            confirmed_repository="Italianhype/Blum",
            authenticated_user="Italianhype",
        )


def test_mlx_model_card_uses_mlx_quick_start(tmp_path) -> None:
    release = manifest(
        runtime="mlx",
        base_model="mlx-community/Qwen3-4B-4bit",
        transformers_smoke_test_passed=False,
        gguf_smoke_test_passed=False,
        mlx_smoke_test_passed=True,
    )

    output = render_model_card(release, output=tmp_path / "README.md")
    text = output.read_text(encoding="utf-8")

    assert "library_name: mlx" in text
    assert "from mlx_lm import load, generate" in text


def test_model_card_explains_governed_incremental_learning(tmp_path) -> None:
    output = render_model_card(manifest(), output=tmp_path / "README.md")
    text = output.read_text(encoding="utf-8")

    assert "explicit opt-in" in text
    assert "versioned challenger" in text
    assert "never trains inside an inference request" in text
