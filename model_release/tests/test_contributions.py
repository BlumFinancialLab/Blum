from __future__ import annotations

import json

import pytest

from model_release.blum_finance.contributions import (
    ConsentRequired,
    build_contribution_bundle,
    validate_contribution_bundle,
)


def example(**overrides: object) -> dict:
    payload = {
        "model_revision": "a" * 40,
        "request": {
            "ticker": "EURUSD",
            "as_of": "2026-07-28T10:00:00Z",
            "evidence": [{"type": "technical", "value": "price above MA20"}],
        },
        "response": {
            "status": "watch",
            "thesis": "Wait for confirmation.",
        },
        "feedback": {"rating": 4, "correction": "Require volume confirmation."},
        "outcome": {
            "observed_at": "2026-07-29T10:00:00Z",
            "status": "closed",
            "realized_r": 0.5,
            "benchmark_excess": 0.2,
            "lesson": "Waiting for confirmation improved the entry quality.",
        },
        "quality": {"score": 85, "source_verified": True},
    }
    payload.update(overrides)
    return payload


def test_contribution_is_disabled_until_explicit_confirmation(tmp_path) -> None:
    with pytest.raises(ConsentRequired):
        build_contribution_bundle(
            example(),
            output=tmp_path / "bundle.json",
        )


def test_bundle_never_contains_secrets_or_email(tmp_path) -> None:
    bundle = build_contribution_bundle(
        example(
            api_key="hf_super_secret",
            contact="trader@example.com",
            broker_account_id="ABC-123",
        ),
        output=tmp_path / "bundle.json",
        consent=True,
    )
    text = bundle.path.read_text(encoding="utf-8")

    assert "hf_super_secret" not in text
    assert "trader@example.com" not in text
    assert "ABC-123" not in text
    assert bundle.uploaded is False
    assert json.loads(text)["consent"]["explicit"] is True


def test_bundle_hash_is_deterministic_for_same_payload(tmp_path) -> None:
    first = build_contribution_bundle(
        example(),
        output=tmp_path / "first.json",
        consent=True,
    )
    second = build_contribution_bundle(
        example(),
        output=tmp_path / "second.json",
        consent=True,
    )

    assert first.content_hash == second.content_hash


def test_push_submits_quarantined_contribution_as_pull_request(tmp_path) -> None:
    class FakeApi:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def upload_file(self, **kwargs):
            self.calls.append(kwargs)
            return "https://huggingface.co/datasets/Italianhype/Blum-Finance-Memory/discussions/7"

    api = FakeApi()
    result = build_contribution_bundle(
        example(),
        output=tmp_path / "bundle.json",
        consent=True,
        push=True,
        api=api,
    )

    assert result.uploaded is True
    assert result.submission_url.endswith("/discussions/7")
    assert api.calls[0]["create_pr"] is True
    assert api.calls[0]["path_in_repo"].startswith("quarantine/")


def test_validator_rejects_tampered_bundle(tmp_path) -> None:
    result = build_contribution_bundle(
        example(),
        output=tmp_path / "bundle.json",
        consent=True,
    )
    bundle = json.loads(result.path.read_text(encoding="utf-8"))
    bundle["payload"]["response"]["thesis"] = "tampered"

    validation = validate_contribution_bundle(bundle)

    assert validation.accepted is False
    assert "content_hash_mismatch" in validation.blockers
