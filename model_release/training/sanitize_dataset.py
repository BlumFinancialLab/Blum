from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any


NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?%?")
REASONING_FIELDS = {
    "thesis",
    "bull_case",
    "bear_case",
    "risks",
    "invalidation_conditions",
    "what_would_change_the_view",
}


def sanitize_example(example: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Remove output numbers that were unavailable in the model input."""
    result = deepcopy(example)
    messages = result.get("messages") or []
    if len(messages) < 2 or messages[-1].get("role") != "assistant":
        return result, 0
    input_text = json.dumps(messages[:-1], ensure_ascii=False, sort_keys=True)
    allowed_numbers = set(NUMBER_PATTERN.findall(input_text))
    try:
        response = json.loads(messages[-1]["content"])
    except (TypeError, json.JSONDecodeError):
        return result, 0

    changes = 0
    for field in REASONING_FIELDS:
        value = response.get(field)
        sanitized, field_changes = sanitize_value(value, allowed_numbers)
        response[field] = sanitized
        changes += field_changes
    confidence = response.get("confidence")
    if isinstance(confidence, (int, float)) and confidence > 70:
        response["confidence"] = 70
        changes += 1
    messages[-1]["content"] = json.dumps(
        response,
        ensure_ascii=False,
        sort_keys=True,
    )
    return result, changes


def sanitize_value(value: Any, allowed_numbers: set[str]) -> tuple[Any, int]:
    if isinstance(value, list):
        output: list[Any] = []
        changes = 0
        for item in value:
            sanitized, item_changes = sanitize_value(item, allowed_numbers)
            output.append(sanitized)
            changes += item_changes
        return output, changes
    if not isinstance(value, str):
        return value, 0

    changes = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal changes
        token = match.group(0)
        if token in allowed_numbers:
            return token
        changes += 1
        return "the observed level"

    return NUMBER_PATTERN.sub(replace, value), changes


def sanitize_file(
    source: Path,
    *,
    source_output: Path,
    mlx_output: Path,
) -> dict[str, int]:
    examples = [
        json.loads(line)
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    sanitized_rows: list[dict[str, Any]] = []
    changes = 0
    for example in examples:
        sanitized, row_changes = sanitize_example(example)
        sanitized_rows.append(sanitized)
        changes += row_changes
    write_jsonl(source_output, sanitized_rows)
    write_jsonl(
        mlx_output,
        [{"messages": row["messages"]} for row in sanitized_rows],
    )
    return {"examples": len(sanitized_rows), "numeric_replacements": changes}


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create an evidence-bound BLUM Finance training derivative."
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-output", type=Path, required=True)
    parser.add_argument("--mlx-output", type=Path, required=True)
    args = parser.parse_args()
    result = sanitize_file(
        args.source,
        source_output=args.source_output,
        mlx_output=args.mlx_output,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
