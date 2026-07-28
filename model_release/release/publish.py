from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from model_release.release.build_repository import ReleaseManifest


class CandidateNotPromoted(ValueError):
    pass


def validate_publication(
    manifest: ReleaseManifest,
    *,
    repository_dir: Path,
    confirmed_repository: str,
    authenticated_user: str,
) -> None:
    if not manifest.promoted:
        raise CandidateNotPromoted("The candidate did not pass the promotion gate.")
    if not manifest.evaluation_validated:
        raise CandidateNotPromoted("Evaluation evidence has not been validated.")
    if not manifest.transformers_smoke_test_passed:
        raise CandidateNotPromoted("Transformers smoke test has not passed.")
    if not manifest.gguf_smoke_test_passed:
        raise CandidateNotPromoted("GGUF smoke test has not passed.")
    if confirmed_repository != manifest.model_repository:
        raise ValueError(
            "Repository confirmation does not match the release manifest."
        )
    if authenticated_user != "Italianhype":
        raise PermissionError(
            f"Expected Hugging Face user Italianhype, got {authenticated_user}."
        )
    for relative_path, expected_hash in manifest.artifact_hashes.items():
        path = repository_dir / relative_path
        if not path.is_file():
            raise FileNotFoundError(f"Missing release artifact: {relative_path}")
        observed_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if observed_hash != expected_hash:
            raise ValueError(
                f"Artifact hash mismatch for {relative_path}: {observed_hash}."
            )


def publish_release(
    manifest: ReleaseManifest,
    *,
    repository_dir: Path,
    confirmed_repository: str,
) -> str:
    from huggingface_hub import HfApi

    api = HfApi()
    identity = api.whoami()
    authenticated_user = str(identity.get("name") or "")
    validate_publication(
        manifest,
        repository_dir=repository_dir,
        confirmed_repository=confirmed_repository,
        authenticated_user=authenticated_user,
    )
    api.create_repo(
        repo_id=manifest.model_repository,
        repo_type="model",
        exist_ok=True,
        private=False,
    )
    return api.upload_folder(
        repo_id=manifest.model_repository,
        repo_type="model",
        folder_path=str(repository_dir),
        commit_message="release: publish BLUM Finance 4B",
    ).oid


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publish a promoted BLUM Finance model release."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--repository-dir", type=Path, required=True)
    parser.add_argument("--confirm-repository", required=True)
    args = parser.parse_args()
    manifest = ReleaseManifest.model_validate_json(
        args.manifest.read_text(encoding="utf-8")
    )
    commit = publish_release(
        manifest,
        repository_dir=args.repository_dir,
        confirmed_repository=args.confirm_repository,
    )
    print(json.dumps({"status": "published", "commit": commit}, indent=2))


if __name__ == "__main__":
    main()
