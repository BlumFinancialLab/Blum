from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.analyst.release_contracts import DatasetSplit, ReleaseExample, ReleaseManifest  # noqa: E402
from app.analyst.release_redaction import sanitize_payload  # noqa: E402


def audit_dataset(source: Path) -> dict:
    with _dataset_directory(source) as directory:
        manifest = ReleaseManifest.model_validate_json(
            (directory / "manifest.json").read_text(encoding="utf-8")
        )
        rows: list[ReleaseExample] = []
        for split in DatasetSplit:
            path = directory / f"{split.value}.jsonl"
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = ReleaseExample.model_validate_json(line)
                    if row.split != split:
                        raise ValueError(f"{path.name} contains {row.split.value} row")
                    redaction = sanitize_payload(row.model_dump(mode="json"))
                    if redaction.blocked_fields or redaction.pii_matches or not redaction.publishable:
                        raise ValueError(f"Unsafe release row: {row.example_id}")
                    rows.append(row)
        lineage_splits: dict[str, set[DatasetSplit]] = {}
        for row in rows:
            lineage_splits.setdefault(row.thesis_lineage_id, set()).add(row.split)
        leaked = [lineage for lineage, splits in lineage_splits.items() if len(splits) > 1]
        if leaked:
            raise ValueError(f"Cross-split thesis leakage detected: {leaked[:5]}")
        expected = sum(manifest.split_counts.values())
        if expected != len(rows):
            raise ValueError(f"Manifest count {expected} does not match {len(rows)} rows")
        return {
            "status": "passed",
            "rows": len(rows),
            "lineages": len(lineage_splits),
            "manifest_sha256": hashlib.sha256(
                (directory / "manifest.json").read_bytes()
            ).hexdigest(),
            "source_revision": manifest.source_revision,
        }


class _dataset_directory:
    def __init__(self, source: Path):
        self.source = source
        self.temporary: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> Path:
        if self.source.is_dir():
            return self.source
        self.temporary = tempfile.TemporaryDirectory(prefix="blum-release-audit-")
        target = Path(self.temporary.name)
        with tarfile.open(self.source, "r:gz") as archive:
            archive.extractall(target, filter="data")
        return target

    def __exit__(self, *_args: object) -> None:
        if self.temporary is not None:
            self.temporary.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit a BLUM Finance dataset release.")
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit_dataset(args.source), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
