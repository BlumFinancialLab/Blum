# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "accelerate>=1.7.0",
#   "bitsandbytes>=0.46.0",
#   "datasets>=3.6.0",
#   "huggingface-hub>=0.34.0",
#   "peft>=0.15.0",
#   "safetensors>=0.5.0",
#   "torch>=2.7.0,<3",
#   "transformers>=4.53.0",
#   "trl>=0.19.0",
# ]
# ///
from __future__ import annotations

import gc
import json
import os
from pathlib import Path
import tempfile

import torch
from datasets import load_dataset
from huggingface_hub import HfApi
from peft import LoraConfig, PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig, SFTTrainer


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def main() -> None:
    token = required("HF_TOKEN")
    dataset_repo = required("BLUM_DATASET_REPOSITORY")
    dataset_revision = required("BLUM_DATASET_REVISION")
    base_model = os.environ.get("BLUM_BASE_MODEL") or required("BLUM_CHAMPION_REPOSITORY")
    base_revision = required("BLUM_CHAMPION_REVISION")
    challenger_repo = required("BLUM_CHALLENGER_REPOSITORY")
    candidate_revision = required("BLUM_CANDIDATE_REVISION")
    seed = int(os.environ.get("BLUM_TRAINING_SEED", "3407"))
    epochs = float(os.environ.get("BLUM_TRAINING_EPOCHS", "2"))
    learning_rate = float(os.environ.get("BLUM_TRAINING_LEARNING_RATE", "0.0001"))
    max_seq_length = int(os.environ.get("BLUM_TRAINING_MAX_SEQ_LENGTH", "4096"))

    api = HfApi(token=token)
    api.create_repo(challenger_repo, repo_type="model", exist_ok=True)
    if not api.list_repo_files(challenger_repo, repo_type="model", token=token):
        api.upload_file(
            path_or_fileobj=b"# BLUM Finance 4B Challenger\n",
            path_in_repo="README.md",
            repo_id=challenger_repo,
            repo_type="model",
            token=token,
            commit_message="Initialize BLUM challenger repository",
        )
    api.create_branch(challenger_repo, branch=candidate_revision, repo_type="model", token=token, exist_ok=True)

    dataset = load_dataset(
        dataset_repo,
        revision=dataset_revision,
        data_files={
            "train": "data/train.jsonl",
            "validation": "data/validation.jsonl",
        },
        token=token,
    )
    if len(dataset["train"]) == 0:
        raise RuntimeError("The pinned BLUM training split is empty")

    tokenizer = AutoTokenizer.from_pretrained(base_model, revision=base_revision, token=token, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        revision=base_revision,
        token=token,
        torch_dtype=torch.bfloat16,
        quantization_config=quantization,
        device_map="auto",
        attn_implementation="sdpa",
    )
    model.config.use_cache = False

    def formatting_func(example: dict) -> str:
        messages = example.get("messages") or []
        if not messages:
            messages = [
                {"role": "user", "content": json.dumps(example.get("input", {}), ensure_ascii=False)},
                {"role": "assistant", "content": json.dumps(example.get("output", {}), ensure_ascii=False)},
            ]
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)

    with tempfile.TemporaryDirectory(prefix="blum-training-") as tmp:
        output_dir = Path(tmp) / "trainer"
        adapter_dir = Path(tmp) / "adapter"
        config = SFTConfig(
            output_dir=str(output_dir),
            num_train_epochs=epochs,
            learning_rate=learning_rate,
            per_device_train_batch_size=1,
            per_device_eval_batch_size=1,
            gradient_accumulation_steps=16,
            gradient_checkpointing=True,
            bf16=True,
            logging_steps=5,
            save_strategy="epoch",
            eval_strategy="epoch" if len(dataset["validation"]) else "no",
            max_length=max_seq_length,
            packing=True,
            seed=seed,
            report_to="none",
        )
        trainer = SFTTrainer(
            model=model,
            args=config,
            train_dataset=dataset["train"],
            eval_dataset=dataset["validation"] if len(dataset["validation"]) else None,
            processing_class=tokenizer,
            formatting_func=formatting_func,
            peft_config=LoraConfig(
                r=32,
                lora_alpha=64,
                lora_dropout=0.05,
                bias="none",
                task_type="CAUSAL_LM",
                target_modules="all-linear",
            ),
        )
        train_result = trainer.train()
        eval_metrics = trainer.evaluate() if len(dataset["validation"]) else {}
        trainer.model.save_pretrained(adapter_dir, safe_serialization=True)
        tokenizer.save_pretrained(adapter_dir)
        metrics = {
            "dataset_repository": dataset_repo,
            "dataset_revision": dataset_revision,
            "base_model": base_model,
            "base_revision": base_revision,
            "candidate_revision": candidate_revision,
            "train_examples": len(dataset["train"]),
            "validation_examples": len(dataset["validation"]),
            "train_metrics": train_result.metrics,
            "evaluation_metrics": eval_metrics,
            "seed": seed,
        }
        (adapter_dir / "blum_training_metrics.json").write_text(json.dumps(metrics, indent=2, default=str))

        del trainer, model
        gc.collect()
        torch.cuda.empty_cache()

        merge_base = AutoModelForCausalLM.from_pretrained(
            base_model,
            revision=base_revision,
            token=token,
            torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
            device_map="cpu",
        )
        merged = PeftModel.from_pretrained(merge_base, adapter_dir).merge_and_unload()
        merged.config.use_cache = True
        merged.push_to_hub(
            challenger_repo,
            revision=candidate_revision,
            token=token,
            safe_serialization=True,
            commit_message=f"BLUM challenger {candidate_revision}",
        )
        tokenizer.push_to_hub(
            challenger_repo,
            revision=candidate_revision,
            token=token,
            commit_message=f"Tokenizer for {candidate_revision}",
        )
        api.upload_file(
            path_or_fileobj=(adapter_dir / "blum_training_metrics.json").read_bytes(),
            path_in_repo="training/blum_training_metrics.json",
            repo_id=challenger_repo,
            repo_type="model",
            revision=candidate_revision,
            commit_message="Add BLUM training metrics",
        )


if __name__ == "__main__":
    main()
