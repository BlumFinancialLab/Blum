#!/usr/bin/env python3
"""Evaluate a causal language model on the finance-related MMLU subjects."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pyarrow.parquet as parquet
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


DATASET_ID = "cais/mmlu"
DATASET_REVISION = "c30699e8356da336a370243923dbaf21066bb9fe"
DEFAULT_SUBJECTS = (
    "business_ethics",
    "econometrics",
    "high_school_macroeconomics",
    "high_school_microeconomics",
    "management",
    "marketing",
    "professional_accounting",
)
ANSWER_LABELS = ("A", "B", "C", "D")


@dataclass(frozen=True)
class MmluExample:
    question: str
    choices: tuple[str, ...]
    answer: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cache-dir", default=".artifacts/mmlu-finance")
    parser.add_argument("--revision", default=None)
    parser.add_argument("--subjects", nargs="+", default=list(DEFAULT_SUBJECTS))
    parser.add_argument("--few-shot", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--max-samples-per-subject", type=int, default=None)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda", "mps"), default="auto")
    return parser.parse_args()


def resolve_device(requested: str) -> str:
    if requested != "auto":
        return requested
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def dataset_url(subject: str, split: str) -> str:
    filename = f"{split}-00000-of-00001.parquet"
    return (
        f"https://huggingface.co/datasets/{DATASET_ID}/resolve/"
        f"{DATASET_REVISION}/{subject}/{filename}"
    )


def download_file(url: str, destination: Path, attempts: int = 6) -> None:
    if destination.exists() and destination.stat().st_size > 0:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            with (
                urllib.request.urlopen(url, timeout=120) as response,
                temporary.open("wb") as output,
            ):
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            temporary.replace(destination)
            return
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
            temporary.unlink(missing_ok=True)
            if attempt == attempts:
                break
            delay = min(2 ** (attempt - 1), 30)
            print(
                json.dumps(
                    {
                        "download_retry": attempt,
                        "delay_seconds": delay,
                        "url": url,
                        "error": str(exc),
                    }
                ),
                flush=True,
            )
            time.sleep(delay)
    raise RuntimeError(f"Unable to download {url} after {attempts} attempts") from last_error


def load_split(cache_dir: Path, subject: str, split: str) -> list[MmluExample]:
    path = cache_dir / subject / f"{split}.parquet"
    download_file(dataset_url(subject, split), path)
    records = parquet.read_table(path).to_pylist()
    return [
        MmluExample(
            question=str(record["question"]),
            choices=tuple(str(choice) for choice in record["choices"]),
            answer=int(record["answer"]),
        )
        for record in records
    ]


def format_example(example: MmluExample, include_answer: bool) -> str:
    lines = [example.question]
    lines.extend(
        f"{label}. {choice}"
        for label, choice in zip(ANSWER_LABELS, example.choices, strict=True)
    )
    if include_answer:
        lines.append(f"Answer: {ANSWER_LABELS[example.answer]}")
    else:
        lines.append("Answer:")
    return "\n".join(lines)


def build_prompt(subject: str, few_shot: Iterable[MmluExample], test: MmluExample) -> str:
    readable_subject = subject.replace("_", " ")
    header = (
        "The following are multiple choice questions (with answers) "
        f"about {readable_subject}.\n\n"
    )
    demonstrations = "\n\n".join(
        format_example(example, include_answer=True) for example in few_shot
    )
    return f"{header}{demonstrations}\n\n{format_example(test, include_answer=False)}"


def answer_token_ids(tokenizer: Any) -> list[int]:
    result: list[int] = []
    for label in ANSWER_LABELS:
        encoded = tokenizer.encode(f" {label}", add_special_tokens=False)
        if len(encoded) != 1:
            raise ValueError(f"Answer label {label!r} is not a single token: {encoded}")
        result.append(encoded[0])
    return result


def chunks(values: list[Any], size: int) -> Iterable[list[Any]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    with temporary.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, sort_keys=True) + "\n")
    temporary.replace(path)


def load_subject_checkpoint(
    output_dir: Path,
    subject: str,
    expected_config: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    subject_dir = output_dir / "subjects" / subject
    result_path = subject_dir / "result.json"
    predictions_path = subject_dir / "predictions.jsonl"
    if not result_path.exists() or not predictions_path.exists():
        return None
    result = json.loads(result_path.read_text(encoding="utf-8"))
    predictions = [
        json.loads(line)
        for line in predictions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if result.get("sample_size") != len(predictions):
        return None
    if result.get("evaluation_config") != expected_config:
        return None
    return result, predictions


def write_subject_checkpoint(
    output_dir: Path,
    subject: str,
    result: dict[str, Any],
    predictions: list[dict[str, Any]],
) -> None:
    subject_dir = output_dir / "subjects" / subject
    write_json_atomic(subject_dir / "result.json", result)
    write_jsonl_atomic(subject_dir / "predictions.jsonl", predictions)


def wilson_interval(correct: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total == 0:
        return 0.0, 0.0
    proportion = correct / total
    denominator = 1 + (z * z / total)
    centre = proportion + z * z / (2 * total)
    margin = z * math.sqrt((proportion * (1 - proportion) + z * z / (4 * total)) / total)
    return (centre - margin) / denominator, (centre + margin) / denominator


def evaluate_subject(
    *,
    model: Any,
    tokenizer: Any,
    device: str,
    subject: str,
    dev: list[MmluExample],
    test: list[MmluExample],
    few_shot_count: int,
    batch_size: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    few_shot = dev[:few_shot_count]
    answer_ids = torch.tensor(answer_token_ids(tokenizer), device=device)
    predictions: list[dict[str, Any]] = []
    started = time.perf_counter()

    for batch in chunks(test, batch_size):
        prompts = [build_prompt(subject, few_shot, example) for example in batch]
        encoded = tokenizer(
            prompts,
            padding=True,
            return_tensors="pt",
            add_special_tokens=True,
        ).to(device)
        with torch.inference_mode():
            logits = model(**encoded).logits
        # Left padding keeps every final prompt token at the final sequence index.
        final_positions = torch.full(
            (len(batch),),
            encoded["input_ids"].shape[1] - 1,
            device=device,
            dtype=torch.long,
        )
        row_indices = torch.arange(len(batch), device=device)
        final_logits = logits[row_indices, final_positions]
        choice_logits = final_logits.index_select(dim=1, index=answer_ids)
        probabilities = torch.softmax(choice_logits.float(), dim=1).cpu()
        predicted = choice_logits.argmax(dim=1).cpu().tolist()

        for example, prediction, probability in zip(
            batch, predicted, probabilities.tolist(), strict=True
        ):
            predictions.append(
                {
                    "subject": subject,
                    "expected": ANSWER_LABELS[example.answer],
                    "predicted": ANSWER_LABELS[prediction],
                    "correct": prediction == example.answer,
                    "choice_probabilities": {
                        label: round(value, 8)
                        for label, value in zip(ANSWER_LABELS, probability, strict=True)
                    },
                }
            )

    correct = sum(int(row["correct"]) for row in predictions)
    total = len(predictions)
    lower, upper = wilson_interval(correct, total)
    return (
        {
            "subject": subject,
            "correct": correct,
            "sample_size": total,
            "accuracy": round(correct / total, 8) if total else None,
            "confidence_interval_95": [round(lower, 8), round(upper, 8)],
            "duration_seconds": round(time.perf_counter() - started, 3),
        },
        predictions,
    )


def main() -> None:
    args = parse_args()
    if args.few_shot < 0 or args.batch_size < 1:
        raise ValueError("few-shot must be non-negative and batch-size must be positive")

    output_dir = Path(args.output_dir)
    cache_dir = Path(args.cache_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    device = resolve_device(args.device)
    dtype = torch.bfloat16 if device in {"cuda", "mps"} else torch.float32

    # Resolve every dataset dependency before allocating model memory. A transient
    # CDN failure must not invalidate hours of completed inference.
    splits: dict[str, tuple[list[MmluExample], list[MmluExample]]] = {}
    for subject in args.subjects:
        dev = load_split(cache_dir, subject, "dev")
        test = load_split(cache_dir, subject, "test")
        if args.max_samples_per_subject is not None:
            test = test[: args.max_samples_per_subject]
        splits[subject] = (dev, test)

    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=args.revision)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        revision=args.revision,
        dtype=dtype,
        low_cpu_mem_usage=True,
    ).to(device)
    model.eval()

    subject_results: list[dict[str, Any]] = []
    predictions: list[dict[str, Any]] = []
    for subject in args.subjects:
        dev, test = splits[subject]
        evaluation_config = {
            "dataset_revision": DATASET_REVISION,
            "few_shot": args.few_shot,
            "model_revision": args.revision,
            "sample_size": len(test),
        }
        checkpoint = load_subject_checkpoint(
            output_dir,
            subject,
            evaluation_config,
        )
        if checkpoint is None:
            result, subject_predictions = evaluate_subject(
                model=model,
                tokenizer=tokenizer,
                device=device,
                subject=subject,
                dev=dev,
                test=test,
                few_shot_count=args.few_shot,
                batch_size=args.batch_size,
            )
            result["evaluation_config"] = evaluation_config
            write_subject_checkpoint(
                output_dir,
                subject,
                result,
                subject_predictions,
            )
        else:
            result, subject_predictions = checkpoint
            print(
                json.dumps(
                    {
                        "subject": subject,
                        "status": "resumed_from_checkpoint",
                        "sample_size": result["sample_size"],
                    }
                ),
                flush=True,
            )
        subject_results.append(result)
        predictions.extend(subject_predictions)
        print(json.dumps(result, sort_keys=True), flush=True)

    total = sum(row["sample_size"] for row in subject_results)
    correct = sum(row["correct"] for row in subject_results)
    lower, upper = wilson_interval(correct, total)
    accuracies = [
        row["accuracy"] for row in subject_results if row["accuracy"] is not None
    ]
    summary = {
        "benchmark": "MMLU finance and business subset",
        "dataset": DATASET_ID,
        "dataset_revision": DATASET_REVISION,
        "model": args.model,
        "model_revision": args.revision,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "device": device,
        "dtype": str(dtype).replace("torch.", ""),
        "few_shot": args.few_shot,
        "sample_limit_per_subject": args.max_samples_per_subject,
        "subjects": subject_results,
        "sample_size": total,
        "micro_accuracy": round(correct / total, 8) if total else None,
        "macro_accuracy": round(statistics.mean(accuracies), 8) if accuracies else None,
        "confidence_interval_95": [round(lower, 8), round(upper, 8)],
        "status": "community_evaluation",
        "official_leaderboard_result": False,
    }
    write_json_atomic(output_dir / "results.json", summary)
    write_jsonl_atomic(output_dir / "predictions.jsonl", predictions)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
