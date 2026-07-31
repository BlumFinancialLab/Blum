# /// script
# requires-python = ">=3.11"
# dependencies = ["huggingface-hub>=0.34.0"]
# ///
from __future__ import annotations

import os
from pathlib import Path
import tempfile

from huggingface_hub import HfApi, snapshot_download


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def main() -> None:
    token = required("HF_TOKEN")
    source_repo = required("BLUM_PROMOTION_SOURCE_REPOSITORY")
    source_revision = required("BLUM_PROMOTION_SOURCE_REVISION")
    destination_repo = required("BLUM_PROMOTION_DESTINATION_REPOSITORY")
    destination_revision = os.environ.get("BLUM_PROMOTION_DESTINATION_REVISION", "main")
    backup_tag = os.environ.get("BLUM_PROMOTION_BACKUP_TAG", "").strip()
    api = HfApi(token=token)

    api.create_repo(destination_repo, repo_type="model", exist_ok=True)
    if backup_tag:
        current = api.repo_info(destination_repo, repo_type="model", revision=destination_revision).sha
        api.create_tag(
            destination_repo,
            repo_type="model",
            tag=backup_tag,
            revision=current,
            tag_message=f"BLUM rollback point before promoting {source_revision}",
            exist_ok=True,
        )

    with tempfile.TemporaryDirectory(prefix="blum-promotion-") as tmp:
        source = Path(snapshot_download(source_repo, repo_type="model", revision=source_revision, token=token, local_dir=tmp))
        api.upload_folder(
            repo_id=destination_repo,
            repo_type="model",
            revision=destination_revision,
            folder_path=source,
            commit_message=f"Promote BLUM model from {source_repo}@{source_revision}",
            delete_patterns=["*"],
            ignore_patterns=[".cache/**"],
        )


if __name__ == "__main__":
    main()
