from __future__ import annotations

from dataclasses import dataclass

from app.analyst.hf_training import HuggingFaceJobLauncher, JobLaunchRequest


@dataclass
class FakeStatus:
    stage: str


@dataclass
class FakeJob:
    id: str
    url: str
    status: FakeStatus


class FakeJobsClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run_uv_job(self, script: str, **kwargs):
        self.calls.append({"script": script, **kwargs})
        return FakeJob("job-123", "https://huggingface.co/jobs/Italianhype/job-123", FakeStatus("SCHEDULING"))


def test_launcher_pins_dataset_and_candidate_and_passes_token_as_secret() -> None:
    client = FakeJobsClient()
    launcher = HuggingFaceJobLauncher(client=client, token="hf-secret")
    request = JobLaunchRequest(
        script="print('train')",
        job_kind="training",
        dataset_repository="Italianhype/Blum-Finance-Reasoning",
        dataset_revision="snapshot-abc123",
        champion_repository="Italianhype/Blum-Finance-4B",
        champion_revision="champion-sha",
        challenger_repository="Italianhype/Blum-Finance-4B-Challenger",
        candidate_revision="candidate-abc123",
        flavor="a10g-large",
        timeout="8h",
    )
    result = launcher.launch(request)

    assert result.remote_job_id == "job-123"
    call = client.calls[0]
    assert call["secrets"] == {"HF_TOKEN": "hf-secret"}
    assert call["env"]["BLUM_DATASET_REVISION"] == "snapshot-abc123"
    assert call["env"]["BLUM_CHAMPION_REVISION"] == "champion-sha"
    assert call["env"]["BLUM_CANDIDATE_REVISION"] == "candidate-abc123"
    assert "hf-secret" not in repr(call["env"])
    assert call["labels"]["blum-job-kind"] == "training"
