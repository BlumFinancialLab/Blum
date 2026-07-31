from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_job_scripts_are_valid_python_and_do_not_hardcode_tokens() -> None:
    for name in ("train_blum_challenger.py", "evaluate_blum_challenger.py", "promote_blum_model.py"):
        path = ROOT / "scripts" / name
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))
        assert "hf_" not in source
        assert 'required("HF_TOKEN")' in source


def test_training_script_pushes_only_to_challenger_repository() -> None:
    source = (ROOT / "scripts" / "train_blum_challenger.py").read_text(encoding="utf-8")
    assert 'challenger_repo = required("BLUM_CHALLENGER_REPOSITORY")' in source
    assert "merged.push_to_hub(\n            challenger_repo" in source
    assert "BLUM_PROMOTION_DESTINATION_REPOSITORY" not in source


def test_promotion_is_a_separate_explicit_script() -> None:
    source = (ROOT / "scripts" / "promote_blum_model.py").read_text(encoding="utf-8")
    assert 'required("BLUM_PROMOTION_SOURCE_REPOSITORY")' in source
    assert 'required("BLUM_PROMOTION_DESTINATION_REPOSITORY")' in source
    assert "create_tag" in source


def test_job_script_loader_returns_existing_local_path() -> None:
    from app.analyst.hf_job_scripts import load_job_script

    path = Path(load_job_script("training"))
    assert path.is_file()
    assert path.name == "train_blum_challenger.py"


def test_gpu_scripts_declare_torch_for_default_uv_image() -> None:
    for name in ("train_blum_challenger.py", "evaluate_blum_challenger.py"):
        source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert '"torch>=' in source
