from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

os.environ["DATABASE_URL"] = "sqlite+pysqlite:////tmp/blum-hf-runtime-test.db"
os.environ["BLUM_HF_TRAINING_ENABLED"] = "true"
os.environ["BLUM_HF_TRAINING_MINIMUM_EXAMPLES"] = "1"
os.environ["BLUM_HF_TRAINING_MINIMUM_MATURED_RATIO"] = "1.0"
os.environ["BLUM_HF_TRAINING_MINIMUM_DAYS_BETWEEN_RUNS"] = "0"
os.environ["BLUM_HF_TRAINING_MINIMUM_QUALITY"] = "70"
os.environ["BLUM_HF_TRAINING_MAX_EXAMPLES"] = "100"

from app.analyst.hf_training_runtime import BlumHFTrainingService
from app.core.database import Base
from app.models import (
    BlumKnowledgeRecord,
    BlumModelTrainingJob,
    BlumThesisOutcome,
    BlumTrainingExample,
    TrainingExampleQualityScore,
)


class FakeApi:
    def __init__(self) -> None:
        self.run_calls: list[dict] = []
        self.commits: list[dict] = []

    def create_repo(self, *args, **kwargs):
        return SimpleNamespace()

    def create_branch(self, *args, **kwargs):
        return None

    def file_exists(self, *args, **kwargs):
        return False

    def create_commit(self, *args, **kwargs):
        self.commits.append(kwargs)
        return SimpleNamespace(oid="dataset-commit", commit_url="https://hf.example/commit")

    def repo_info(self, *args, **kwargs):
        return SimpleNamespace(sha="champion-sha")

    def run_uv_job(self, script: str, **kwargs):
        self.run_calls.append({"script": script, **kwargs})
        return SimpleNamespace(
            id="remote-training-1",
            url="https://huggingface.co/jobs/Italianhype/remote-training-1",
            status=SimpleNamespace(stage="SCHEDULING"),
        )


test_engine = create_engine("sqlite+pysqlite:///:memory:", future=True)


def reset_database() -> None:
    Base.metadata.drop_all(test_engine)
    Base.metadata.create_all(test_engine)


def seed_one_matured_example() -> None:
    with Session(test_engine) as db:
        for index in range(1, 4):
            record = BlumKnowledgeRecord(
                ticker=f"BLUM{index}",
                reasoning_hash=f"lineage-blum-{index}",
                blum_reasoning={"thesis": "Evidence-bound thesis"},
                training_sample={},
            )
            db.add(record)
            db.flush()
            example = BlumTrainingExample(
                knowledge_record_id=record.id,
                task_type="financial_thesis_generation",
                input_payload={"ticker": f"BLUM{index}", "as_of": "2026-07-01"},
                output_payload={"thesis": "Evidence-bound thesis", "confidence": 0.6},
                messages={
                    "items": [
                        {"role": "user", "content": "Analyze the supplied BLUM evidence."},
                        {"role": "assistant", "content": "Return the structured thesis."},
                    ]
                },
                quality_scores={"overall_score": 90},
                preference_payload={},
                export_ready=True,
            )
            db.add(example)
            db.flush()
            db.add(
                TrainingExampleQualityScore(
                    training_example_id=example.id,
                    thesis_id=record.id,
                    final_training_value_score=90,
                    include_in_sft=True,
                )
            )
            db.add(
                BlumThesisOutcome(
                    knowledge_record_id=record.id,
                    ticker=f"BLUM{index}",
                    horizon_days=20,
                    expected_direction="up_or_resilient",
                    realized_return=2.5,
                    outcome="correct",
                    success=True,
                )
            )
        db.commit()


def test_runtime_launch_publishes_snapshot_and_queues_external_job_without_persisting_token() -> None:
    reset_database()
    seed_one_matured_example()
    api = FakeApi()
    service = BlumHFTrainingService(api=api, token="hf-super-secret")
    # The full suite may populate the cached Settings object before this module's
    # environment overrides are collected. Keep this integration test explicit.
    service.settings.hf_training_enabled = True
    service.settings.hf_training_minimum_examples = 1
    service.settings.hf_training_minimum_matured_ratio = 1.0
    service.settings.hf_training_minimum_days_between_runs = 0
    service.settings.hf_training_minimum_quality = 70

    with Session(test_engine) as db:
        result = service.launch(db)
        job = db.query(BlumModelTrainingJob).one()

        assert result["status"] == "training_queued"
        assert job.status == "training_queued"
        assert job.training_config["remote_training_job_id"] == "remote-training-1"
        assert job.training_config["dataset_revision"].startswith("snapshot-")
        assert "hf-super-secret" not in repr(job.training_config)
        assert "hf-super-secret" not in repr(job.metrics)

    assert len(api.commits) == 1
    assert len(api.run_calls) == 1
    assert api.run_calls[0]["secrets"] == {"HF_TOKEN": "hf-super-secret"}
    assert "Italianhype/Blum-Finance-4B" == api.run_calls[0]["env"]["BLUM_CHAMPION_REPOSITORY"]
