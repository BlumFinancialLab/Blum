from __future__ import annotations

import ast
from pathlib import Path


def test_hf_training_routes_are_explicit_and_write_actions_are_post_only() -> None:
    path = Path(__file__).parents[1] / "app" / "api" / "routers" / "analyst.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    routes: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            method = decorator.func.attr.lower()
            if method not in {"get", "post", "put", "delete", "patch"} or not decorator.args:
                continue
            route = ast.literal_eval(decorator.args[0])
            routes.setdefault(route, set()).add(method)

    assert routes["/api/analyst/hf-training/status"] == {"get"}
    assert routes["/api/analyst/hf-training/snapshot"] == {"post"}
    assert routes["/api/analyst/hf-training/launch"] == {"post"}
    assert routes["/api/analyst/hf-training/sync"] == {"post"}
    assert routes["/api/analyst/hf-training/promote/{job_id}"] == {"post"}
    assert routes["/api/analyst/hf-training/rollback/{job_id}"] == {"post"}
    assert routes["/api/analyst/hf-training/local-snapshot"] == {"get"}
    assert routes["/api/analyst/hf-training/local-snapshot/archive"] == {"get"}


def test_snapshot_post_exposes_explicit_local_persistence_without_get_side_effects() -> None:
    path = Path(__file__).parents[1] / "app" / "api" / "routers" / "analyst.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "hf_training_snapshot"
    )

    argument_names = [argument.arg for argument in function.args.args]
    assert "persist_local" in argument_names


def test_default_uv_job_image_is_not_a_non_uv_pytorch_image() -> None:
    from app.core.config import Settings

    settings = Settings(DATABASE_URL="sqlite+pysqlite:///:memory:")
    assert settings.hf_training_job_image == ""
    assert settings.hf_dataset_snapshot_enabled is True
    assert settings.hf_training_supervisor_minutes == 60


def test_general_analyst_status_uses_lightweight_hf_configuration_only() -> None:
    path = Path(__file__).parents[1] / "app" / "analyst" / "dataset_pipeline.py"
    source = path.read_text(encoding="utf-8")
    assert ".configuration_status()" in source
    assert "BlumHFTrainingService().status(db)" not in source
