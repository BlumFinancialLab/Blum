from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from app.services.trading_ml.finrlx import (
    FINRLX_UPSTREAM_REVISION,
    FinRLXArtifactValidator,
    FinRLXQuantEngine,
    InvalidFinRLXArtifact,
)


SCHEMA_HASH = "feature-schema-v1"


def write_artifact(
    root: Path,
    *,
    algorithm: str = "PPO",
    market_family: str = "forex",
    feature_schema_hash: str = SCHEMA_HASH,
    paper_only: bool = True,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    artifact = root / "policy.bin"
    artifact.write_bytes(b"verified-finrlx-policy")
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "provider": "finrlx",
                "upstream_repository": "AI4Finance-Foundation/FinRL-Trading",
                "upstream_revision": FINRLX_UPSTREAM_REVISION,
                "algorithm": algorithm,
                "market_family": market_family,
                "feature_schema_hash": feature_schema_hash,
                "action_schema": (
                    "directional_score_v1"
                    if market_family == "forex"
                    else "target_weights_v1"
                ),
                "artifact_path": artifact.name,
                "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "sample_count": 500,
                "paper_only": paper_only,
            }
        ),
        encoding="utf-8",
    )
    return manifest


def write_runner(path: Path) -> Path:
    path.write_text(
        """#!/usr/bin/env python3
import json
import sys

request = json.load(sys.stdin)
if request["operation"] == "propose":
    json.dump({
        "action": "LONG",
        "directional_score": 0.72,
        "confidence": 0.68,
        "uncertainty": 0.21,
        "reason": "validated shadow proposal"
    }, sys.stdout)
elif request["operation"] == "train":
    json.dump({"manifest_path": request["request"]["manifest_path"]}, sys.stdout)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def test_artifact_validator_accepts_pinned_paper_only_manifest(tmp_path):
    manifest_path = write_artifact(tmp_path)

    manifest = FinRLXArtifactValidator(
        root=tmp_path,
        expected_feature_schema_hash=SCHEMA_HASH,
    ).validate(manifest_path, market_family="forex")

    assert manifest.algorithm == "PPO"
    assert manifest.sample_count == 500
    assert manifest.paper_only is True


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ({"algorithm": "UNSUPPORTED"}, "algorithm"),
        ({"market_family": "equity"}, "market"),
        ({"feature_schema_hash": "wrong"}, "schema"),
        ({"paper_only": False}, "paper"),
        ({"upstream_revision": "unpinned"}, "revision"),
    ],
)
def test_artifact_validator_rejects_incompatible_manifest(tmp_path, mutation, expected):
    manifest_path = write_artifact(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload.update(mutation)
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(InvalidFinRLXArtifact, match=expected):
        FinRLXArtifactValidator(
            root=tmp_path,
            expected_feature_schema_hash=SCHEMA_HASH,
        ).validate(manifest_path, market_family="forex")


def test_artifact_validator_rejects_tampered_binary(tmp_path):
    manifest_path = write_artifact(tmp_path)
    (tmp_path / "policy.bin").write_bytes(b"tampered")

    with pytest.raises(InvalidFinRLXArtifact, match="hash"):
        FinRLXArtifactValidator(
            root=tmp_path,
            expected_feature_schema_hash=SCHEMA_HASH,
        ).validate(manifest_path, market_family="forex")


def test_disabled_and_missing_runner_are_non_fatal(tmp_path):
    disabled = FinRLXQuantEngine(
        enabled=False,
        runner_command="",
        artifact_root=tmp_path,
        feature_schema_hash=SCHEMA_HASH,
    )
    unavailable = FinRLXQuantEngine(
        enabled=True,
        runner_command=str(tmp_path / "missing-runner"),
        artifact_root=tmp_path,
        feature_schema_hash=SCHEMA_HASH,
    )

    assert disabled.status()["status"] == "DISABLED"
    assert disabled.propose(market_family="forex", features={}).action == "HOLD"
    assert unavailable.status()["status"] == "UNAVAILABLE"
    assert unavailable.propose(market_family="forex", features={}).status == "UNAVAILABLE"


def test_runner_proposal_is_normalized_and_blockers_are_preserved(tmp_path):
    manifest_path = write_artifact(tmp_path)
    runner = write_runner(tmp_path / "runner.py")
    engine = FinRLXQuantEngine(
        enabled=True,
        runner_command=str(runner),
        artifact_root=tmp_path,
        manifest_path=manifest_path,
        feature_schema_hash=SCHEMA_HASH,
        timeout_seconds=5,
    )

    proposal = engine.propose(
        market_family="forex",
        features={"momentum_5": 0.8},
        context={"pair": "EURUSD=X"},
    )
    blocked = engine.propose(
        market_family="forex",
        features={"momentum_5": 0.8},
        deterministic_blockers=["STALE_DATA"],
    )

    assert proposal.status == "SHADOW"
    assert proposal.action == "LONG"
    assert proposal.directional_score == 0.72
    assert blocked.action == "HOLD"
    assert blocked.directional_score == 0.0
    assert "EXISTING_BLOCKER_PRESERVED" in blocked.guardrails


def test_runner_cannot_return_leverage_or_order_authority(tmp_path):
    manifest_path = write_artifact(tmp_path)
    runner = tmp_path / "unsafe-runner.py"
    runner.write_text(
        """#!/usr/bin/env python3
import json
import sys
json.load(sys.stdin)
json.dump({"action": "LONG", "directional_score": 1, "leverage": 30}, sys.stdout)
""",
        encoding="utf-8",
    )
    runner.chmod(0o755)
    engine = FinRLXQuantEngine(
        enabled=True,
        runner_command=str(runner),
        artifact_root=tmp_path,
        manifest_path=manifest_path,
        feature_schema_hash=SCHEMA_HASH,
    )

    proposal = engine.propose(market_family="forex", features={})

    assert proposal.status == "REJECTED"
    assert proposal.action == "HOLD"
    assert "FORBIDDEN_EXECUTION_FIELD" in proposal.guardrails


def test_training_result_is_accepted_only_after_manifest_validation(tmp_path):
    manifest_path = write_artifact(tmp_path)
    runner = write_runner(tmp_path / "runner.py")
    engine = FinRLXQuantEngine(
        enabled=True,
        runner_command=str(runner),
        artifact_root=tmp_path,
        feature_schema_hash=SCHEMA_HASH,
        timeout_seconds=5,
    )

    result = engine.run_training(
        market_family="forex",
        request={"manifest_path": str(manifest_path), "max_rows": 500},
    )

    assert result["status"] == "VALIDATED_SHADOW"
    assert result["manifest"]["algorithm"] == "PPO"
    assert result["manifest"]["paper_only"] is True


def test_equity_target_weights_are_normalized_without_order_authority(tmp_path):
    manifest_path = write_artifact(tmp_path, market_family="equity")
    runner = tmp_path / "equity-runner.py"
    runner.write_text(
        """#!/usr/bin/env python3
import json
import sys
json.load(sys.stdin)
json.dump({"target_weights": {"NVDA": 0.8, "MSFT": 0.8}, "confidence": 0.7}, sys.stdout)
""",
        encoding="utf-8",
    )
    runner.chmod(0o755)
    engine = FinRLXQuantEngine(
        enabled=True,
        runner_command=str(runner),
        artifact_root=tmp_path,
        manifest_path=manifest_path,
        feature_schema_hash=SCHEMA_HASH,
    )

    proposal = engine.propose(market_family="equity", features={})

    assert proposal.action == "TARGET_WEIGHTS"
    assert dict(proposal.target_weights) == {"MSFT": 0.5, "NVDA": 0.5}
    assert proposal.paper_only is True


def test_runner_timeout_returns_hold_without_escaping_cycle(tmp_path, monkeypatch):
    manifest_path = write_artifact(tmp_path)
    runner = write_runner(tmp_path / "runner.py")
    engine = FinRLXQuantEngine(
        enabled=True,
        runner_command=str(runner),
        artifact_root=tmp_path,
        manifest_path=manifest_path,
        feature_schema_hash=SCHEMA_HASH,
    )

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="runner", timeout=1)

    monkeypatch.setattr(subprocess, "run", timeout)

    proposal = engine.propose(market_family="forex", features={})

    assert proposal.status == "TIMEOUT"
    assert proposal.action == "HOLD"
