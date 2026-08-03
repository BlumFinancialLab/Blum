from __future__ import annotations

from dataclasses import dataclass
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from .schemas import FinancialReasoningRequest, FinancialReasoningResponse


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]{2,}")


class InvalidMemoryRecord(ValueError):
    """Raised when a record cannot safely become retrieval memory."""


@dataclass(frozen=True)
class StoredMemoryRecord:
    content_hash: str
    payload: dict[str, Any]


class BlumFinanceMemoryStore:
    """Small, auditable local memory with strict point-in-time retrieval.

    This store never changes model weights. It exposes only matured observations
    available before a new request and labels them as historical analogies.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()

    def add(self, payload: dict[str, Any]) -> StoredMemoryRecord:
        normalized = _validate_memory_payload(payload)
        content_hash = _content_hash(normalized)
        row = {"content_hash": content_hash, "payload": normalized}
        existing = self._rows()
        if not any(item.get("content_hash") == content_hash for item in existing):
            self._replace([*existing, row])
        return StoredMemoryRecord(content_hash=content_hash, payload=normalized)

    def add_bundle(self, bundle: str | Path | dict[str, Any]) -> StoredMemoryRecord:
        from .contributions import validate_contribution_bundle

        if isinstance(bundle, (str, Path)):
            value = json.loads(Path(bundle).read_text(encoding="utf-8"))
        else:
            value = bundle
        validation = validate_contribution_bundle(value)
        if not validation.accepted:
            raise InvalidMemoryRecord(
                "Contribution is not eligible for memory: " + ", ".join(validation.blockers)
            )
        return self.add(value["payload"])

    def retrieve(
        self,
        request: FinancialReasoningRequest,
        *,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        request_tokens = _request_tokens(request.model_dump(mode="json"))
        candidates: list[tuple[float, datetime, dict[str, Any]]] = []
        for row in self._rows():
            payload = row.get("payload")
            if not isinstance(payload, dict):
                continue
            try:
                normalized = _validate_memory_payload(payload)
                observed_at = _timestamp(normalized["outcome"]["observed_at"])
            except (InvalidMemoryRecord, KeyError, TypeError, ValueError):
                continue
            if observed_at > _aware(request.as_of):
                continue
            memory_request = normalized["request"]
            memory_tokens = _request_tokens(memory_request)
            overlap = len(request_tokens & memory_tokens) / max(1, len(request_tokens | memory_tokens))
            ticker_match = str(memory_request.get("ticker", "")).upper() == request.ticker.upper()
            horizon_match = str(memory_request.get("horizon", "")) == request.horizon
            score = overlap + (2.0 if ticker_match else 0.0) + (0.5 if horizon_match else 0.0)
            candidates.append((score, observed_at, _retrieval_payload(normalized, row.get("content_hash"))))
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in candidates[:limit] if item[0] > 0]

    def _rows(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
        return rows

    def _replace(self, rows: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        body = "".join(_canonical_json(row) + "\n" for row in rows)
        temporary.write_text(body, encoding="utf-8")
        os.replace(temporary, self.path)


def _validate_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise InvalidMemoryRecord("Memory payload must be an object")
    request = payload.get("request")
    response = payload.get("response")
    outcome = payload.get("outcome")
    quality = payload.get("quality")
    try:
        parsed_request = FinancialReasoningRequest.model_validate(request)
        parsed_response = FinancialReasoningResponse.model_validate(response)
    except Exception as exc:
        raise InvalidMemoryRecord(f"Invalid BLUM request or response: {exc}") from exc
    if not isinstance(outcome, dict) or not outcome.get("observed_at"):
        raise InvalidMemoryRecord("A matured outcome with observed_at is required")
    observed_at = _timestamp(outcome["observed_at"])
    if observed_at <= _aware(parsed_request.as_of):
        raise InvalidMemoryRecord("The outcome must be observed after the decision")
    status = str(outcome.get("status") or "").strip().lower()
    if status in {"", "pending", "unresolved", "inconclusive"}:
        raise InvalidMemoryRecord("The outcome is not mature")
    if not isinstance(quality, dict) or quality.get("source_verified") is not True:
        raise InvalidMemoryRecord("Memory requires verified source provenance")
    try:
        score = float(quality.get("score"))
    except (TypeError, ValueError) as exc:
        raise InvalidMemoryRecord("Memory quality score is missing") from exc
    if score < 70:
        raise InvalidMemoryRecord("Memory quality is below 70")
    return {
        **payload,
        "request": parsed_request.model_dump(mode="json"),
        "response": parsed_response.model_dump(mode="json"),
        "outcome": dict(outcome),
        "quality": {**quality, "score": score},
    }


def _retrieval_payload(payload: dict[str, Any], content_hash: Any) -> dict[str, Any]:
    request = payload["request"]
    response = payload["response"]
    outcome = payload["outcome"]
    return {
        "memory_id": str(content_hash or _content_hash(payload)),
        "ticker": request.get("ticker"),
        "horizon": request.get("horizon"),
        "decision_as_of": request.get("as_of"),
        "observed_at": outcome.get("observed_at"),
        "prior_status": response.get("status"),
        "prior_thesis": response.get("thesis"),
        "outcome": {
            key: outcome.get(key)
            for key in ("status", "realized_r", "benchmark_excess")
            if outcome.get(key) is not None
        },
        "lesson": outcome.get("lesson") or "No explicit lesson was supplied.",
        "quality_score": payload["quality"]["score"],
    }


def _request_tokens(payload: dict[str, Any]) -> set[str]:
    return {
        token.lower()
        for token in TOKEN_PATTERN.findall(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    }


def _content_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _aware(value)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return _aware(parsed)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import a validated BLUM contribution into local point-in-time memory."
    )
    parser.add_argument("bundle", type=Path)
    parser.add_argument(
        "--memory",
        type=Path,
        default=Path.home() / ".blum-finance" / "memory.jsonl",
    )
    args = parser.parse_args()
    stored = BlumFinanceMemoryStore(args.memory).add_bundle(args.bundle)
    print(
        json.dumps(
            {"status": "stored", "content_hash": stored.content_hash, "memory": str(args.memory)},
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
