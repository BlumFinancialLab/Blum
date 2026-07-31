# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "accelerate>=1.7.0",
#   "datasets>=3.6.0",
#   "huggingface-hub>=0.34.0",
#   "safetensors>=0.5.0",
#   "torch>=2.7.0,<3",
#   "transformers>=4.53.0",
# ]
# ///
from __future__ import annotations

import gc
import json
import os
import re
from typing import Any

import torch
from datasets import load_dataset
from huggingface_hub import HfApi
from transformers import AutoModelForCausalLM, AutoTokenizer


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    candidates = [text]
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue
    return None


def numeric_tokens(value: Any) -> set[str]:
    return set(re.findall(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)?%?", json.dumps(value, ensure_ascii=False)))


def date_tokens(value: Any) -> set[str]:
    return set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", json.dumps(value, ensure_ascii=False)))


def score_model(repo: str, revision: str, rows: list[dict], token: str) -> dict[str, float | int]:
    tokenizer = AutoTokenizer.from_pretrained(repo, revision=revision, token=token, use_fast=True)
    model = AutoModelForCausalLM.from_pretrained(
        repo,
        revision=revision,
        token=token,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        attn_implementation="sdpa",
    )
    model.eval()
    valid = grounded = directional = temporal = 0
    critical_regressions = 0
    temporal_leakage = 0
    for row in rows:
        messages = list(row.get("messages") or [])
        if messages and messages[-1].get("role") == "assistant":
            messages = messages[:-1]
        messages.append({"role": "user", "content": "Return only the final BLUM JSON contract. Do not invent evidence or numerical values."})
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        with torch.inference_mode():
            generated = model.generate(**inputs, max_new_tokens=700, do_sample=False, temperature=None, top_p=None)
        answer = tokenizer.decode(generated[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
        parsed = extract_json(answer)
        if parsed is not None:
            valid += 1
            expected = row.get("output") or {}
            required_keys = set(expected) if isinstance(expected, dict) else set()
            if not required_keys or required_keys.issubset(parsed):
                temporal += 1
            allowed_numbers = numeric_tokens(row.get("input")) | numeric_tokens(expected)
            produced_numbers = numeric_tokens(parsed)
            if produced_numbers.issubset(allowed_numbers):
                grounded += 1
            allowed_dates = date_tokens(row.get("input")) | date_tokens(expected)
            produced_dates = date_tokens(parsed)
            if not produced_dates.issubset(allowed_dates):
                temporal_leakage += 1
            side = str((row.get("input") or {}).get("direction") or (row.get("input") or {}).get("side") or "").upper()
            if side not in {"LONG", "SHORT"} or str(parsed.get("direction") or parsed.get("side") or side).upper() == side:
                directional += 1
        else:
            critical_regressions += 1
    total = max(1, len(rows))
    structured = valid / total
    no_fabrication = grounded / total
    directional_score = directional / total
    temporal_score = temporal / total
    aggregate = (structured + no_fabrication + directional_score + temporal_score) / 4
    del model, tokenizer
    gc.collect()
    torch.cuda.empty_cache()
    return {
        "aggregate_contract_score": round(aggregate, 6),
        "structured_validity": round(structured, 6),
        "no_fabrication": round(no_fabrication, 6),
        "directional_accounting": round(directional_score, 6),
        "temporal_contract": round(temporal_score, 6),
        "critical_regressions": critical_regressions,
        "temporal_leakage": temporal_leakage,
        "examples": len(rows),
    }


def main() -> None:
    token = required("HF_TOKEN")
    dataset_repo = required("BLUM_DATASET_REPOSITORY")
    dataset_revision = required("BLUM_DATASET_REVISION")
    champion_repo = required("BLUM_CHAMPION_REPOSITORY")
    champion_revision = required("BLUM_CHAMPION_REVISION")
    challenger_repo = required("BLUM_CHALLENGER_REPOSITORY")
    candidate_revision = required("BLUM_CANDIDATE_REVISION")
    maximum = int(os.environ.get("BLUM_EVAL_MAX_EXAMPLES", "53"))

    dataset = load_dataset(
        dataset_repo,
        revision=dataset_revision,
        data_files={"test": "data/test.jsonl"},
        token=token,
    )
    rows = [dict(row) for row in dataset["test"].select(range(min(maximum, len(dataset["test"]))))]
    if not rows:
        raise RuntimeError("The pinned BLUM test split is empty")

    champion = score_model(champion_repo, champion_revision, rows, token)
    candidate = score_model(challenger_repo, candidate_revision, rows, token)
    result = {
        "dataset_repository": dataset_repo,
        "dataset_revision": dataset_revision,
        "champion_repository": champion_repo,
        "champion_revision": champion_revision,
        "challenger_repository": challenger_repo,
        "candidate_revision": candidate_revision,
        "champion": champion,
        "candidate": candidate,
        "temporal_leakage": int(candidate.get("temporal_leakage", 0)),
        "evaluation_contract": "blum-champion-challenger-v1",
    }
    HfApi(token=token).upload_file(
        path_or_fileobj=(json.dumps(result, indent=2, sort_keys=True) + "\n").encode(),
        path_in_repo="evaluation/evaluation.json",
        repo_id=challenger_repo,
        repo_type="model",
        revision=candidate_revision,
        commit_message="Add BLUM champion-challenger evaluation",
    )


if __name__ == "__main__":
    main()
