from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
import yaml


class DatasetIntegrityError(ValueError):
    pass


class TrainingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_model: str
    seed: int
    learning_rate: float = Field(gt=0)
    num_train_epochs: int = Field(gt=0)
    max_length: int = Field(gt=0)
    packing: bool
    assistant_only_loss: bool
    lora_r: int = Field(gt=0)
    lora_alpha: int = Field(gt=0)
    lora_dropout: float = Field(ge=0, lt=1)
    target_modules: list[str] = Field(min_length=1)
    per_device_train_batch_size: int = Field(gt=0)
    per_device_eval_batch_size: int = Field(gt=0)
    gradient_accumulation_steps: int = Field(gt=0)
    eval_steps: int = Field(gt=0)
    save_steps: int = Field(gt=0)
    logging_steps: int = Field(gt=0)
    warmup_ratio: float = Field(ge=0, lt=1)
    weight_decay: float = Field(ge=0)
    bf16: bool
    gradient_checkpointing: bool
    push_to_hub: bool
    report_to: list[str]


def load_training_config(path: Path) -> TrainingConfig:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return TrainingConfig.model_validate(payload)


def verify_dataset_manifest(
    dataset_dir: Path,
    *,
    expected_sha256: str,
) -> dict[str, Any]:
    manifest_path = dataset_dir / "manifest.json"
    if not manifest_path.is_file():
        raise DatasetIntegrityError(f"Missing dataset manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "blum-finance-manifest-v1":
        raise DatasetIntegrityError("Unsupported BLUM Finance dataset schema.")
    observed = str(manifest.get("dataset_sha256") or "")
    if observed != expected_sha256:
        raise DatasetIntegrityError(
            f"Dataset hash mismatch: expected {expected_sha256}, observed {observed or 'missing'}."
        )
    if manifest.get("base_model") != "Qwen/Qwen3-4B":
        raise DatasetIntegrityError("Dataset manifest targets an unexpected base model.")
    for split in ("train", "validation", "test"):
        split_path = dataset_dir / f"{split}.jsonl"
        if not split_path.is_file() or split_path.stat().st_size == 0:
            raise DatasetIntegrityError(f"Missing or empty split: {split}.")
    return manifest


def train(
    *,
    dataset_dir: Path,
    expected_sha256: str,
    output_dir: Path,
    config_path: Path,
    adapter_repository: str | None = None,
    push_adapter: bool = False,
) -> dict[str, Any]:
    config = load_training_config(config_path)
    manifest = verify_dataset_manifest(
        dataset_dir,
        expected_sha256=expected_sha256,
    )

    from datasets import load_dataset
    from huggingface_hub import HfApi
    from peft import LoraConfig
    from trl import SFTConfig, SFTTrainer

    model_info = HfApi().model_info(config.base_model)
    base_revision = model_info.sha
    dataset = load_dataset(
        "json",
        data_files={
            "train": str(dataset_dir / "train.jsonl"),
            "validation": str(dataset_dir / "validation.jsonl"),
        },
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    training_args = SFTConfig(
        output_dir=str(output_dir),
        run_name="blum-finance-4b-sft-v1",
        seed=config.seed,
        learning_rate=config.learning_rate,
        num_train_epochs=config.num_train_epochs,
        max_length=config.max_length,
        packing=config.packing,
        assistant_only_loss=config.assistant_only_loss,
        per_device_train_batch_size=config.per_device_train_batch_size,
        per_device_eval_batch_size=config.per_device_eval_batch_size,
        gradient_accumulation_steps=config.gradient_accumulation_steps,
        eval_strategy="steps",
        eval_steps=config.eval_steps,
        save_strategy="steps",
        save_steps=config.save_steps,
        save_total_limit=2,
        logging_steps=config.logging_steps,
        warmup_ratio=config.warmup_ratio,
        weight_decay=config.weight_decay,
        bf16=config.bf16,
        gradient_checkpointing=config.gradient_checkpointing,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        report_to=config.report_to,
        push_to_hub=False,
        hub_model_id=adapter_repository if push_adapter else None,
        model_init_kwargs={"revision": base_revision, "dtype": "bfloat16"},
    )
    peft_config = LoraConfig(
        r=config.lora_r,
        lora_alpha=config.lora_alpha,
        lora_dropout=config.lora_dropout,
        target_modules=config.target_modules,
        bias="none",
        task_type="CAUSAL_LM",
    )
    trainer = SFTTrainer(
        model=config.base_model,
        args=training_args,
        train_dataset=dataset["train"],
        eval_dataset=dataset["validation"],
        peft_config=peft_config,
    )
    result = trainer.train()
    trainer.save_model(str(output_dir))
    if push_adapter:
        if not adapter_repository:
            raise ValueError("adapter_repository is required when push_adapter is enabled.")
        trainer.push_to_hub(
            commit_message="train: publish BLUM Finance 4B LoRA candidate"
        )

    training_manifest = {
        "schema_version": "blum-finance-training-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "base_model": config.base_model,
        "base_revision": base_revision,
        "dataset_sha256": manifest["dataset_sha256"],
        "dataset_source_revision": manifest["source_revision"],
        "seed": config.seed,
        "adapter_repository": adapter_repository,
        "pushed": bool(push_adapter),
        "metrics": {
            key: float(value)
            for key, value in result.metrics.items()
            if isinstance(value, (int, float))
        },
        "config": config.model_dump(mode="json"),
    }
    (output_dir / "training_manifest.json").write_text(
        json.dumps(training_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return training_manifest


def main() -> None:
    default_config = Path(__file__).with_name("config.yaml")
    parser = argparse.ArgumentParser(description="Train the BLUM Finance 4B LoRA.")
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=default_config)
    parser.add_argument(
        "--adapter-repository",
        default="Italianhype/Blum-Finance-4B-LoRA",
    )
    parser.add_argument("--push-adapter", action="store_true")
    args = parser.parse_args()
    result = train(
        dataset_dir=args.dataset_dir,
        expected_sha256=args.expected_sha256,
        output_dir=args.output_dir,
        config_path=args.config,
        adapter_repository=args.adapter_repository,
        push_adapter=args.push_adapter,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
