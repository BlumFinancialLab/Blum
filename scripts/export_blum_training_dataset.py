from __future__ import annotations

import argparse
import json
import os
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND = os.path.join(ROOT, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from app.core.database import session_scope  # noqa: E402
from app.services.blum_financial_model import export_training_jsonl  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Blum proprietary financial reasoning data as JSONL.")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--min-quality", type=float, default=60.0)
    parser.add_argument("--export-name", default=None)
    args = parser.parse_args()

    with session_scope() as db:
        result = export_training_jsonl(
            db,
            limit=args.limit,
            min_quality=args.min_quality,
            export_name=args.export_name,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
