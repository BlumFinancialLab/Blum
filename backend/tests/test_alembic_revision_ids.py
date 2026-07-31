from __future__ import annotations

import ast
from pathlib import Path


def test_all_alembic_revision_ids_fit_default_version_table() -> None:
    versions = Path(__file__).parents[1] / "alembic" / "versions"
    failures: list[tuple[str, str]] = []
    revisions: dict[str, str | None] = {}

    for path in sorted(versions.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        revision = None
        down_revision = None
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                continue
            if node.targets[0].id == "revision" and isinstance(node.value, ast.Constant):
                revision = node.value.value
            if node.targets[0].id == "down_revision" and isinstance(node.value, ast.Constant):
                down_revision = node.value.value
        if revision:
            revisions[str(revision)] = str(down_revision) if down_revision else None
            if len(str(revision)) > 32:
                failures.append((path.name, str(revision)))

    assert not failures, f"Alembic revision IDs exceed VARCHAR(32): {failures}"
    assert "0025_tg_runtime_snap" in revisions
    assert revisions["0026_alpha_operating_system"] == "0025_tg_runtime_snap"
