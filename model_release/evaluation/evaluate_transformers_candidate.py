from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from model_release.blum_finance.inference import _extract_json_object
from model_release.evaluation.evaluate_candidate import load_examples
from model_release.evaluation.evaluate_mlx_candidate import write_evaluation


def generate_predictions(
    *,
    model_path: Path,
    examples: list[dict[str, Any]],
    max_tokens: int,
    device: str,
    batch_size: int,
) -> tuple[list[dict[str, Any] | None], list[dict[str, Any]]]:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    ).to(device)
    tokenizer.padding_side = "left"
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token_id = tokenizer.eos_token_id
    predictions: list[dict[str, Any] | None] = []
    generations: list[dict[str, Any]] = []
    for batch_start in range(0, len(examples), batch_size):
        batch = examples[batch_start : batch_start + batch_size]
        prompts = [
            tokenizer.apply_chat_template(
                example["messages"][:-1],
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            for example in batch
        ]
        inputs = tokenizer(prompts, return_tensors="pt", padding=True).to(device)
        with torch.inference_mode():
            output = model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )
        generated_rows = tokenizer.batch_decode(
            output[:, inputs.input_ids.shape[1] :],
            skip_special_tokens=True,
        )
        errors: list[str | None] = []
        for batch_index, (example, generated) in enumerate(
            zip(batch, generated_rows, strict=True)
        ):
            index = batch_start + batch_index
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
            errors.append(error)
        print(
            json.dumps(
                {
                    "completed": batch_start + len(batch),
                    "total": len(examples),
                    "parse_errors": sum(error is not None for error in errors),
                }
            ),
            flush=True,
        )
    return predictions, generations


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate a local merged Transformers BLUM Finance candidate."
    )
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--test-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--device", default="mps")
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    examples = load_examples(args.test_file)
    if args.limit:
        examples = examples[: args.limit]
    predictions, generations = generate_predictions(
        model_path=args.model_path,
        examples=examples,
        max_tokens=args.max_tokens,
        device=args.device,
        batch_size=args.batch_size,
    )
    payload = write_evaluation(
        output_dir=args.output_dir,
        model_revision=args.revision,
        examples=examples,
        predictions=predictions,
        generations=generations,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
