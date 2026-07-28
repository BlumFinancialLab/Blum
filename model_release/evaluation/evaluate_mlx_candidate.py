from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from model_release.blum_finance.inference import _extract_json_object
from model_release.evaluation.evaluate_candidate import load_examples
from model_release.evaluation.tasks.blum_finance_eval import evaluate_predictions


def artifact_revision(path: Path) -> str:
    """Return a stable 40-character revision for a local adapter artifact."""
    digest = hashlib.sha1()  # nosec B324 - compatibility identifier, not security
    for item in sorted(candidate_files(path)):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with item.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def candidate_files(path: Path) -> list[Path]:
    return [
        item
        for item in path.rglob("*")
        if item.is_file() and not item.name.startswith(".")
    ]


def build_generation_prompt(tokenizer: Any, messages: list[dict[str, str]]) -> str:
    return tokenizer.apply_chat_template(
        messages[:-1],
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )


def generate_predictions(
    *,
    model_path: Path,
    adapter_path: Path | None,
    examples: list[dict[str, Any]],
    max_tokens: int,
) -> tuple[list[dict[str, Any] | None], list[dict[str, Any]]]:
    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    model, tokenizer = load(
        str(model_path),
        adapter_path=str(adapter_path) if adapter_path else None,
        tokenizer_config={"trust_remote_code": True},
    )
    sampler = make_sampler(temp=0.0)
    predictions: list[dict[str, Any] | None] = []
    generations: list[dict[str, Any]] = []
    for index, example in enumerate(examples):
        prompt = build_generation_prompt(tokenizer, example["messages"])
        generated = generate(
            model,
            tokenizer,
            prompt=prompt,
            max_tokens=max_tokens,
            sampler=sampler,
            verbose=False,
        )
        try:
            parsed = _extract_json_object(generated)
            error = None
        except (ValueError, json.JSONDecodeError) as exc:
            parsed = None
            error = str(exc)
        predictions.append(parsed)
        generations.append(
            {
                "example_id": example.get("example_id"),
                "index": index,
                "generated_text": generated,
                "parse_error": error,
            }
        )
    return predictions, generations


def write_evaluation(
    *,
    output_dir: Path,
    model_revision: str,
    examples: list[dict[str, Any]],
    predictions: list[dict[str, Any] | None],
    generations: list[dict[str, Any]],
) -> dict[str, Any]:
    metrics, traces = evaluate_predictions(
        model_revision=model_revision,
        examples=examples,
        predictions=predictions,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = metrics.model_dump(mode="json")
    (output_dir / "evaluation_summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_jsonl(output_dir / "evaluation_traces.jsonl", traces)
    write_jsonl(output_dir / "generations.jsonl", generations)
    return payload


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate a local MLX BLUM Finance base model or LoRA adapter."
    )
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--adapter-path", type=Path)
    parser.add_argument("--revision")
    parser.add_argument("--test-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-tokens", type=int, default=512)
    args = parser.parse_args()

    examples = load_examples(args.test_file)
    revision = args.revision or (
        artifact_revision(args.adapter_path)
        if args.adapter_path
        else artifact_revision(args.model_path)
    )
    predictions, generations = generate_predictions(
        model_path=args.model_path,
        adapter_path=args.adapter_path,
        examples=examples,
        max_tokens=args.max_tokens,
    )
    payload = write_evaluation(
        output_dir=args.output_dir,
        model_revision=revision,
        examples=examples,
        predictions=predictions,
        generations=generations,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
