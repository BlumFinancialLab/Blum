from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.analyst.dataset_pipeline import BlumAnalystDatasetPipeline  # noqa: E402
from app.core.database import session_scope  # noqa: E402


def current_revision() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
    ).strip()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export a redacted, leakage-safe BLUM Finance release dataset."
    )
    parser.add_argument("--source-revision", default=current_revision())
    parser.add_argument("--min-score", type=float, default=70.0)
    parser.add_argument("--limit", type=int, default=10_000)
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Overrides BLUM_TRAINING_EXPORT_DIR for this process.",
    )
    args = parser.parse_args()
    if args.output_dir:
        os.environ["BLUM_TRAINING_EXPORT_DIR"] = args.output_dir

    with session_scope() as db:
        result = BlumAnalystDatasetPipeline().export_release(
            db,
            source_revision=args.source_revision,
            min_score=args.min_score,
            limit=args.limit,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
