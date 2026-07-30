from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path

import polars as pl

from app.services.trading_ml.contracts import (
    CATEGORICAL_FEATURES,
    FeatureSchema,
    NUMERIC_FEATURES,
)
from app.services.trading_ml.finrlx import FinRLXQuantEngine
from app.services.trading_ml.finrlx_runner import _select_feature_paths


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "finrlx_runner.py"


def _install_fake_upstream_contract(root: Path) -> Path:
    strategies = root / "strategies"
    strategies.mkdir(parents=True)
    (strategies / "__init__.py").write_text("", encoding="utf-8")
    (strategies / "base_strategy.py").write_text(
        """
from dataclasses import dataclass

@dataclass
class StrategyConfig:
    name: str = "BaseStrategy"

@dataclass
class StrategyResult:
    strategy_name: str
    weights: object
    metadata: dict | None = None

class BaseStrategy:
    def __init__(self, config):
        self.config = config

    def generate_weights(self, data, target_date=None):
        raise NotImplementedError
""",
        encoding="utf-8",
    )
    return root


def _write_feature_store(root: Path, *, rows: int = 120) -> Path:
    destination = (
        root
        / "features"
        / "market_family=forex"
        / "year=2026"
        / "month=07"
    )
    destination.mkdir(parents=True)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    records = []
    for index in range(rows):
        positive = index % 3 != 0
        realized_r = 0.7 + (index % 5) * 0.05 if positive else -0.8
        record = {
            "source_uid": f"trade:{index}",
            "source_object_type": "paper_trade",
            "source_object_id": str(index),
            "market_family": "forex",
            "evidence_lane": "paper_forward",
            "decision_timestamp": start + timedelta(hours=index),
            "outcome_timestamp": start + timedelta(hours=index + 1),
            "asset_key": ["EURUSD=X", "GBPUSD=X", "USDJPY=X"][index % 3],
            "setup_type": "momentum_breakout" if index % 2 else "pullback",
            "regime": "trend_up" if positive else "range_bound",
            "realized_net_r": realized_r,
            "label_positive_r": int(positive),
            "benchmark_excess": realized_r / 100,
            "sample_weight": 1.0,
        }
        for feature in NUMERIC_FEATURES:
            record[feature] = float((index % 11) / 10)
        record["momentum_score"] = 0.9 if positive else -0.7
        record["expected_net_r"] = 1.2 if positive else -0.4
        for feature in CATEGORICAL_FEATURES:
            record[feature] = {
                "market_family": "forex",
                "setup_type": record["setup_type"],
                "regime": record["regime"],
                "session": "LONDON",
                "direction": "LONG",
                "timeframe": "15m",
                "sector_or_currency_family": "major",
            }[feature]
        records.append(record)
    pl.DataFrame(records).write_parquet(destination / "part-test.parquet")
    return root


def test_builtin_runner_trains_validated_policy_and_serves_shadow_inference(
    tmp_path,
    monkeypatch,
):
    upstream = _install_fake_upstream_contract(tmp_path / "upstream")
    feature_store = _write_feature_store(tmp_path / "feature-store")
    artifact_root = tmp_path / "artifacts"
    monkeypatch.setenv("FINRLX_UPSTREAM_SOURCE", str(upstream))

    engine = FinRLXQuantEngine(
        enabled=True,
        runner_command=str(RUNNER),
        artifact_root=artifact_root,
        feature_schema_hash=FeatureSchema.current().hash,
        timeout_seconds=20,
    )

    trained = engine.run_training(
        market_family="forex",
        request={
            "feature_store_root": str(feature_store),
            "artifact_root": str(artifact_root),
            "max_rows": 120,
            "minimum_samples": 64,
            "paper_only": True,
        },
    )
    proposal = engine.propose(
        market_family="forex",
        features={
            "momentum_score": 0.95,
            "expected_net_r": 1.3,
            "regime": "trend_up",
            "setup_type": "momentum_breakout",
            "session": "LONDON",
            "direction": "LONG",
            "timeframe": "15m",
            "market_family": "forex",
            "sector_or_currency_family": "major",
        },
        context={"pair": "EURUSD=X"},
    )

    assert trained["status"] == "VALIDATED_SHADOW"
    assert trained["manifest"]["algorithm"] == "DETERMINISTIC"
    assert trained["manifest"]["sample_count"] == 120
    assert Path(trained["manifest_path"]).is_file()
    assert proposal.status == "SHADOW"
    assert proposal.action in {"LONG", "HOLD"}
    assert proposal.model and proposal.model.startswith("finrlx:DETERMINISTIC:")
    assert proposal.paper_only is True


def test_new_engine_auto_discovers_persisted_market_manifest(tmp_path, monkeypatch):
    upstream = _install_fake_upstream_contract(tmp_path / "upstream")
    feature_store = _write_feature_store(tmp_path / "feature-store")
    artifact_root = tmp_path / "artifacts"
    monkeypatch.setenv("FINRLX_UPSTREAM_SOURCE", str(upstream))
    first = FinRLXQuantEngine(
        enabled=True,
        runner_command=str(RUNNER),
        artifact_root=artifact_root,
        feature_schema_hash=FeatureSchema.current().hash,
        timeout_seconds=20,
    )
    result = first.run_training(
        market_family="forex",
        request={
            "feature_store_root": str(feature_store),
            "artifact_root": str(artifact_root),
            "max_rows": 120,
            "minimum_samples": 64,
        },
    )
    assert result["status"] == "VALIDATED_SHADOW"

    restarted = FinRLXQuantEngine(
        enabled=True,
        runner_command=str(RUNNER),
        artifact_root=artifact_root,
        feature_schema_hash=FeatureSchema.current().hash,
    )

    status = restarted.status(market_family="forex")

    assert status["status"] == "READY_SHADOW"
    assert status["manifest"]["market_family"] == "forex"


def test_runner_reports_insufficient_evidence_without_fabricating_artifact(
    tmp_path,
    monkeypatch,
):
    upstream = _install_fake_upstream_contract(tmp_path / "upstream")
    feature_store = _write_feature_store(tmp_path / "feature-store", rows=12)
    artifact_root = tmp_path / "artifacts"
    monkeypatch.setenv("FINRLX_UPSTREAM_SOURCE", str(upstream))
    engine = FinRLXQuantEngine(
        enabled=True,
        runner_command=str(RUNNER),
        artifact_root=artifact_root,
        feature_schema_hash=FeatureSchema.current().hash,
        timeout_seconds=20,
    )

    result = engine.run_training(
        market_family="forex",
        request={
            "feature_store_root": str(feature_store),
            "artifact_root": str(artifact_root),
            "max_rows": 12,
            "minimum_samples": 64,
        },
    )

    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["sample_count"] == 12
    assert not (artifact_root / "forex" / "manifest.json").exists()


def test_docker_enables_pinned_upstream_runner_without_broker_execution():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "AI4Finance-Foundation/FinRL-Trading.git@" in dockerfile
    assert "e65d6f0483ead7d2ef4a5fc940cdf960392a25c1" in dockerfile
    assert "BLUM_FINRLX_ENABLED=true" in dockerfile
    assert "BLUM_FINRLX_RUNNER_COMMAND=/app/scripts/finrlx_runner.py" in dockerfile
    assert "APCA_API_KEY" not in dockerfile


def test_runner_selects_only_recent_manifest_partitions_needed_for_sample(tmp_path):
    root = tmp_path / "feature-store"
    partitions = []
    for index, rows in enumerate((400, 300, 250)):
        relative = (
            Path("features")
            / "market_family=equity"
            / "year=2026"
            / f"month={index + 1:02d}"
            / f"part-{index}.parquet"
        )
        target = root / relative
        target.parent.mkdir(parents=True)
        target.touch()
        partitions.append(
            {
                "path": str(relative),
                "market_family": "equity",
                "rows": rows,
            }
        )
    (root / "manifest.json").write_text(
        json.dumps({"partitions": partitions}),
        encoding="utf-8",
    )

    selected = _select_feature_paths(root, "equity", max_rows=500)

    assert selected == [
        root / partitions[1]["path"],
        root / partitions[2]["path"],
    ]
