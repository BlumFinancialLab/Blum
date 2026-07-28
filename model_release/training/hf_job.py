# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "accelerate>=1.2",
#   "datasets>=3.2",
#   "huggingface-hub>=0.30",
#   "peft>=0.15",
#   "trackio>=0.2",
#   "transformers>=4.51",
#   "trl>=0.20",
# ]
# ///
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any


BASE_MODEL = "Qwen/Qwen3-4B"
DATASET_FILES = (
    "train.jsonl",
    "validation.jsonl",
    "test.jsonl",
    "excluded.jsonl",
)
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SEED = 20260728


class DatasetIntegrityError(ValueError):
    pass


def dataset_digest(dataset_dir: Path) -> str:
    digest = hashlib.sha256()
    for name in DATASET_FILES:
        path = dataset_dir / name
        if not path.is_file():
            raise DatasetIntegrityError(f"Missing immutable dataset file: {name}")
        digest.update(name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _require_revision(value: str, *, label: str) -> str:
    if not REVISION_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must be an immutable 40-character commit SHA.")
    return value


def train_candidate(
    *,
    dataset_repository: str,
    dataset_revision: str,
    expected_dataset_sha256: str,
    adapter_repository: str,
    output_dir: Path,
) -> dict[str, Any]:
    from datasets import load_dataset
    from huggingface_hub import HfApi, snapshot_download
    from peft import LoraConfig
    from trl import SFTConfig, SFTTrainer

    token = os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError("HF_TOKEN is required to preserve the training result.")
    _require_revision(dataset_revision, label="dataset_revision")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_dataset_sha256):
        raise ValueError("expected_dataset_sha256 must be a SHA-256 digest.")

    dataset_dir = Path(
        snapshot_download(
            repo_id=dataset_repository,
            repo_type="dataset",
            revision=dataset_revision,
            allow_patterns=[*DATASET_FILES, "manifest.json"],
            token=token,
        )
    )
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    observed_digest = dataset_digest(dataset_dir)
    if manifest.get("dataset_sha256") != expected_dataset_sha256:
        raise DatasetIntegrityError("Manifest dataset digest does not match the job input.")
    if observed_digest != expected_dataset_sha256:
        raise DatasetIntegrityError(
            f"Dataset content digest mismatch: {observed_digest}."
        )
    if manifest.get("base_model") != BASE_MODEL:
        raise DatasetIntegrityError("Dataset targets an unexpected base model.")

    api = HfApi(token=token)
    base_revision = _require_revision(
        str(api.model_info(BASE_MODEL, token=token).sha),
        label="base_revision",
    )
    api.create_repo(
        repo_id=adapter_repository,
        repo_type="model",
        private=False,
        exist_ok=True,
        token=token,
    )
    dataset = load_dataset(
        "json",
        data_files={
            "train": str(dataset_dir / "train.jsonl"),
            "validation": str(dataset_dir / "validation.jsonl"),
        },
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("TRACKIO_PROJECT", "blum-finance")
    training_args = SFTConfig(
        output_dir=str(output_dir),
        run_name="blum-finance-4b-sft-v1",
        seed=SEED,
        learning_rate=1e-4,
        num_train_epochs=3,
        max_length=4096,
        packing=True,
        assistant_only_loss=True,
        per_device_train_batch_size=1,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=16,
        eval_strategy="steps",
        eval_steps=25,
        save_strategy="steps",
        save_steps=25,
        save_total_limit=2,
        logging_steps=5,
        warmup_ratio=0.05,
        weight_decay=0.01,
        bf16=True,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        report_to=["trackio"],
        push_to_hub=False,
        hub_model_id=adapter_repository,
        hub_token=token,
        model_init_kwargs={
            "revision": base_revision,
            "dtype": "bfloat16",
            "attn_implementation": "sdpa",
        },
    )
    trainer = SFTTrainer(
        model=BASE_MODEL,
        args=training_args,
        train_dataset=dataset["train"],
        eval_dataset=dataset["validation"],
        peft_config=LoraConfig(
            r=32,
            lora_alpha=64,
            lora_dropout=0.05,
            target_modules=[
                "q_proj",
                "k_proj",
                "v_proj",
                "o_proj",
                "gate_proj",
                "up_proj",
                "down_proj",
            ],
            bias="none",
            task_type="CAUSAL_LM",
        ),
    )
    train_result = trainer.train()
    eval_metrics = trainer.evaluate()
    trainer.save_model(str(output_dir))
    trainer.push_to_hub(
        commit_message="train: publish BLUM Finance 4B LoRA candidate",
        token=token,
    )
    candidate_revision = _require_revision(
        str(api.model_info(adapter_repository, token=token).sha),
        label="candidate_revision",
    )
    training_manifest = {
        "schema_version": "blum-finance-training-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "base_model": BASE_MODEL,
        "base_revision": base_revision,
        "dataset_repository": dataset_repository,
        "dataset_revision": dataset_revision,
        "dataset_sha256": expected_dataset_sha256,
        "adapter_repository": adapter_repository,
        "candidate_revision": candidate_revision,
        "seed": SEED,
        "metrics": {
            key: float(value)
            for key, value in {**train_result.metrics, **eval_metrics}.items()
            if isinstance(value, (int, float))
        },
    }
    manifest_path = output_dir / "training_manifest.json"
    manifest_path.write_text(
        json.dumps(training_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    commit = api.upload_file(
        repo_id=adapter_repository,
        repo_type="model",
        path_or_fileobj=str(manifest_path),
        path_in_repo="training_manifest.json",
        commit_message="train: record immutable training manifest",
        token=token,
    )
    training_manifest["manifest_commit"] = commit.oid
    return training_manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the immutable BLUM Finance 4B LoRA candidate job."
    )
    parser.add_argument("--dataset-repository", required=True)
    parser.add_argument("--dataset-revision", required=True)
    parser.add_argument("--expected-dataset-sha256", required=True)
    parser.add_argument(
        "--adapter-repository",
        default="Italianhype/Blum-Finance-4B-LoRA",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/blum-finance-lora"))
    args = parser.parse_args()
    result = train_candidate(
        dataset_repository=args.dataset_repository,
        dataset_revision=args.dataset_revision,
        expected_dataset_sha256=args.expected_dataset_sha256,
        adapter_repository=args.adapter_repository,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
