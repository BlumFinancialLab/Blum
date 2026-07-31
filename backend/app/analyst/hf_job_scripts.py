from __future__ import annotations

from functools import lru_cache
from pathlib import Path


_SCRIPT_NAMES = {
    "training": "train_blum_challenger.py",
    "evaluation": "evaluate_blum_challenger.py",
    "promotion": "promote_blum_model.py",
    "rollback": "promote_blum_model.py",
}


@lru_cache(maxsize=4)
def load_job_script(job_kind: str) -> str:
    try:
        name = _SCRIPT_NAMES[job_kind]
    except KeyError as exc:
        raise ValueError(f"Unsupported BLUM HF job kind: {job_kind}") from exc
    root = Path(__file__).resolve().parents[3]
    path = root / "scripts" / name
    if not path.is_file():
        raise RuntimeError(f"BLUM HF Job script is missing: {path}")
    return str(path)
