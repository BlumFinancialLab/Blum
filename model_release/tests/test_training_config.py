from __future__ import annotations

import json
from pathlib import Path

import pytest

from model_release.training.train_sft import (
    DatasetIntegrityError,
    load_training_config,
    verify_dataset_manifest,
)


CONFIG_PATH = (
    Path(__file__).resolve().parents[1] / "training" / "config.yaml"
)


def test_training_config_pins_base_and_assistant_only_loss() -> None:
    config = load_training_config(CONFIG_PATH)

    assert config.base_model == "Qwen/Qwen3-4B"
    assert config.assistant_only_loss is True
    assert config.seed == 20260728
    assert config.push_to_hub is False


def test_training_refuses_mismatched_dataset_hash(tmp_path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "blum-finance-manifest-v1",
                "dataset_sha256": "a" * 64,
                "base_model": "Qwen/Qwen3-4B",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DatasetIntegrityError):
        verify_dataset_manifest(tmp_path, expected_sha256="b" * 64)


def test_training_accepts_expected_manifest_hash(tmp_path) -> None:
    expected = "c" * 64
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "blum-finance-manifest-v1",
                "dataset_sha256": expected,
                "base_model": "Qwen/Qwen3-4B",
            }
        ),
        encoding="utf-8",
    )
    for split in ("train", "validation", "test"):
        (tmp_path / f"{split}.jsonl").write_text('{"messages":[]}\n', encoding="utf-8")

    manifest = verify_dataset_manifest(tmp_path, expected_sha256=expected)

    assert manifest["dataset_sha256"] == expected
