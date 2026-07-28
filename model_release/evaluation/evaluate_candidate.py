from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from huggingface_hub import HfApi

from model_release.blum_finance.inference import _extract_json_object
from model_release.evaluation.tasks.blum_finance_eval import evaluate_predictions


def load_examples(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def generate_predictions(
    *,
    model_id: str,
    revision: str,
    examples: list[dict[str, Any]],
) -> list[dict[str, Any] | None]:
    from transformers import pipeline

    generator = pipeline(
        "text-generation",
        model=model_id,
        revision=revision,
        device_map="auto",
    )
    predictions: list[dict[str, Any] | None] = []
    for example in examples:
        result = generator(
            example["messages"][:-1],
            max_new_tokens=768,
            do_sample=False,
            return_full_text=False,
        )
        generated = result[0]["generated_text"]
        if isinstance(generated, list):
            generated = generated[-1]["content"]
        try:
            predictions.append(_extract_json_object(str(generated)))
        except (ValueError, json.JSONDecodeError):
            predictions.append(None)
    return predictions


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a BLUM Finance model candidate.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", default=None)
    parser.add_argument("--test-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    revision = args.revision or HfApi().model_info(args.model).sha
    examples = load_examples(args.test_file)
    predictions = generate_predictions(
        model_id=args.model,
        revision=revision,
        examples=examples,
    )
    metrics, traces = evaluate_predictions(
        model_revision=revision,
        examples=examples,
        predictions=predictions,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "evaluation_summary.json").write_text(
        json.dumps(metrics.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with (args.output_dir / "evaluation_traces.jsonl").open("w", encoding="utf-8") as handle:
        for trace in traces:
            handle.write(json.dumps(trace, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps(metrics.model_dump(mode="json"), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
