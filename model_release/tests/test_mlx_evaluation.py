from __future__ import annotations

import json
from pathlib import Path

from model_release.evaluation.evaluate_mlx_candidate import (
    artifact_revision,
    build_generation_prompt,
)


class StubTokenizer:
    def apply_chat_template(self, messages, **kwargs):
        return json.dumps({"messages": messages, "options": kwargs}, sort_keys=True)


def test_artifact_revision_is_stable_and_changes_with_adapter(tmp_path: Path) -> None:
    (tmp_path / "adapter_config.json").write_text('{"rank": 8}\n', encoding="utf-8")
    weights = tmp_path / "adapters.safetensors"
    weights.write_bytes(b"first")

    first = artifact_revision(tmp_path)
    second = artifact_revision(tmp_path)
    weights.write_bytes(b"second")

    assert first == second
    assert len(first) == 40
    assert first != artifact_revision(tmp_path)


def test_generation_prompt_excludes_target_and_disables_thinking() -> None:
    messages = [
        {"role": "system", "content": "System"},
        {"role": "user", "content": "Evidence"},
        {"role": "assistant", "content": '{"status":"watch"}'},
    ]

    result = json.loads(build_generation_prompt(StubTokenizer(), messages))

    assert result["messages"] == messages[:-1]
    assert result["options"] == {
        "add_generation_prompt": True,
        "enable_thinking": False,
        "tokenize": False,
    }
