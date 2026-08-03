#!/usr/bin/env python3
"""Classify a Hugging Face-to-GitHub synchronization safely."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


SyncAction = str


def classify_sync(
    github_sha: str,
    hf_sha: str,
    github_is_ancestor: bool,
    hf_is_ancestor: bool,
) -> SyncAction:
    """Return the only permitted synchronization action for two revisions."""
    if not github_sha.strip() or not hf_sha.strip():
        raise ValueError("both repositories must provide a commit SHA")
    if github_sha == hf_sha:
        return "noop_equal"
    if hf_is_ancestor:
        return "noop_hf_behind"
    if github_is_ancestor:
        return "fast_forward"
    return "pull_request"


def _boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Classify GitHub and Hugging Face main-branch ancestry."
    )
    parser.add_argument("--github-sha", required=True)
    parser.add_argument("--hf-sha", required=True)
    parser.add_argument("--github-is-ancestor", required=True, type=_boolean)
    parser.add_argument("--hf-is-ancestor", required=True, type=_boolean)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(
        classify_sync(
            github_sha=args.github_sha,
            hf_sha=args.hf_sha,
            github_is_ancestor=args.github_is_ancestor,
            hf_is_ancestor=args.hf_is_ancestor,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
