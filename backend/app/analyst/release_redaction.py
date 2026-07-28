from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


BLOCKED_KEYS = {
    "access_token",
    "account_id",
    "api_key",
    "authorization",
    "broker_account_id",
    "full_report",
    "raw_article",
    "refresh_token",
}
UNLICENSED_SOURCE_KEYS = {"full_report", "raw_article"}

EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
HF_TOKEN_PATTERN = re.compile(r"\bhf_[A-Za-z0-9]{16,}\b")
BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}\b", re.IGNORECASE)


@dataclass(frozen=True)
class RedactionResult:
    payload: dict[str, Any]
    blocked_fields: list[str]
    pii_matches: list[str]
    publishable: bool


def sanitize_payload(payload: dict[str, Any]) -> RedactionResult:
    blocked_fields: set[str] = set()
    matches: set[str] = set()
    unlicensed_source_found = False

    def clean(value: Any) -> Any:
        nonlocal unlicensed_source_found
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for raw_key, child in value.items():
                key = str(raw_key)
                normalized = key.lower()
                if normalized in BLOCKED_KEYS:
                    blocked_fields.add(normalized)
                    if normalized in UNLICENSED_SOURCE_KEYS and bool(child):
                        unlicensed_source_found = True
                    continue
                result[key] = clean(child)
            return result
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, tuple):
            return [clean(item) for item in value]
        if isinstance(value, str):
            text = EMAIL_PATTERN.sub(lambda _: _mark(matches, "email", "[REDACTED_EMAIL]"), value)
            text = HF_TOKEN_PATTERN.sub(lambda _: _mark(matches, "hugging_face_token", "[REDACTED_TOKEN]"), text)
            text = BEARER_PATTERN.sub(lambda _: _mark(matches, "bearer_token", "[REDACTED_TOKEN]"), text)
            return " ".join(text.split())
        return value

    cleaned = clean(payload)
    return RedactionResult(
        payload=cleaned,
        blocked_fields=sorted(blocked_fields),
        pii_matches=sorted(matches),
        publishable=not unlicensed_source_found,
    )


def _mark(matches: set[str], label: str, replacement: str) -> str:
    matches.add(label)
    return replacement
