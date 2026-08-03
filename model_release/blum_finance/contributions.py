from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import json
from pathlib import Path
import re
from typing import Any


TARGET_REPOSITORY = "Italianhype/Blum-Finance-Memory"
BLOCKED_KEYS = {
    "access_token",
    "account_id",
    "api_key",
    "authorization",
    "broker_account_id",
    "refresh_token",
}
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
HF_TOKEN_PATTERN = re.compile(r"\bhf_[A-Za-z0-9_]{8,}\b")


class ConsentRequired(ValueError):
    pass


@dataclass(frozen=True)
class ContributionBundleResult:
    path: Path
    content_hash: str
    uploaded: bool
    repository: str
    submission_url: str | None = None


@dataclass(frozen=True)
class ContributionValidation:
    accepted: bool
    blockers: tuple[str, ...]
    status: str


def build_contribution_bundle(
    payload: dict[str, Any],
    *,
    output: Path,
    consent: bool = False,
    push: bool = False,
    repository: str = TARGET_REPOSITORY,
    api: Any | None = None,
) -> ContributionBundleResult:
    if not consent:
        raise ConsentRequired(
            "Community contribution is disabled until explicit consent is provided."
        )
    sanitized, redactions = _sanitize(payload)
    canonical = json.dumps(
        sanitized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    bundle = {
        "schema_version": "blum-finance-contribution-v2",
        "content_hash": content_hash,
        "created_at": datetime.now(UTC).isoformat(),
        "target_repository": repository,
        "consent": {
            "explicit": True,
            "telemetry_default": "disabled",
            "license": "cc-by-4.0",
        },
        "redactions": redactions,
        "quarantine_status": "pending_validation",
        "payload": sanitized,
    }
    validation = validate_contribution_bundle(bundle)
    bundle["quarantine_status"] = validation.status
    bundle["validation_blockers"] = list(validation.blockers)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    uploaded = False
    submission_url = None
    if push:
        if api is None:
            from huggingface_hub import HfApi

            api = HfApi()

        result = api.upload_file(
            path_or_fileobj=str(output),
            path_in_repo=f"quarantine/{content_hash}.json",
            repo_id=repository,
            repo_type="dataset",
            commit_message=f"contrib: add quarantined example {content_hash[:12]}",
            create_pr=True,
        )
        uploaded = True
        submission_url = str(
            getattr(result, "pr_url", None)
            or getattr(result, "commit_url", None)
            or result
        )
    return ContributionBundleResult(
        path=output,
        content_hash=content_hash,
        uploaded=uploaded,
        repository=repository,
        submission_url=submission_url,
    )


def validate_contribution_bundle(bundle: dict[str, Any]) -> ContributionValidation:
    blockers: list[str] = []
    payload = bundle.get("payload")
    if not isinstance(payload, dict):
        return ContributionValidation(False, ("payload_missing",), "rejected")
    expected_hash = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if not hmac.compare_digest(str(bundle.get("content_hash") or ""), expected_hash):
        blockers.append("content_hash_mismatch")
    if (bundle.get("consent") or {}).get("explicit") is not True:
        blockers.append("explicit_consent_missing")
    request = payload.get("request")
    response = payload.get("response")
    outcome = payload.get("outcome")
    quality = payload.get("quality")
    if not isinstance(request, dict) or not request.get("evidence") or not request.get("as_of"):
        blockers.append("point_in_time_request_missing")
    if not isinstance(response, dict) or not response.get("thesis"):
        blockers.append("model_response_missing")
    if not isinstance(outcome, dict) or not outcome.get("observed_at"):
        blockers.append("mature_outcome_missing")
    else:
        try:
            decision_at = _parse_datetime((request or {}).get("as_of"))
            observed_at = _parse_datetime(outcome.get("observed_at"))
            if observed_at <= decision_at:
                blockers.append("outcome_chronology_invalid")
        except (TypeError, ValueError):
            blockers.append("outcome_timestamp_invalid")
        if str(outcome.get("status") or "").lower() in {"", "pending", "unresolved", "inconclusive"}:
            blockers.append("mature_outcome_missing")
    if not isinstance(quality, dict) or quality.get("source_verified") is not True:
        blockers.append("source_provenance_unverified")
    return ContributionValidation(
        accepted=not blockers,
        blockers=tuple(dict.fromkeys(blockers)),
        status="eligible_for_curation" if not blockers else "pending_validation",
    )


def _sanitize(value: Any) -> tuple[Any, list[str]]:
    redactions: set[str] = set()

    def clean(item: Any) -> Any:
        if isinstance(item, dict):
            result: dict[str, Any] = {}
            for raw_key, child in item.items():
                key = str(raw_key)
                if key.lower() in BLOCKED_KEYS:
                    redactions.add(key.lower())
                    continue
                result[key] = clean(child)
            return result
        if isinstance(item, list):
            return [clean(child) for child in item]
        if isinstance(item, str):
            text = EMAIL_PATTERN.sub(
                lambda _: _replace(redactions, "email", "[REDACTED_EMAIL]"),
                item,
            )
            return HF_TOKEN_PATTERN.sub(
                lambda _: _replace(redactions, "hugging_face_token", "[REDACTED_TOKEN]"),
                text,
            )
        return item

    return clean(value), sorted(redactions)


def _replace(redactions: set[str], label: str, replacement: str) -> str:
    redactions.add(label)
    return replacement


def _parse_datetime(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create an explicit, redacted BLUM Finance contribution bundle."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--consent", action="store_true")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--repository", default=TARGET_REPOSITORY)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    result = build_contribution_bundle(
        payload,
        output=args.output,
        consent=args.consent,
        push=args.push,
        repository=args.repository,
    )
    print(
        json.dumps(
            {
                "path": str(result.path),
                "content_hash": result.content_hash,
                "uploaded": result.uploaded,
                "repository": result.repository,
                "submission_url": result.submission_url,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
