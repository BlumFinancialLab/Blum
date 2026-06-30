from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.analyst.dataset_pipeline import BlumAnalystDatasetPipeline
from app.core.database import Base
from app.engine.contracts import ENGINE_VERSION, PROJECT_FEATURE_SET, event_contract
from app.engine.facade import BlumEngineFacade
from app.runtime.facade import BlumRuntimeFacade


def setup_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_engine_contract_is_headless_source_of_truth():
    contract = BlumEngineFacade().contract()

    assert contract["version"] == ENGINE_VERSION
    assert contract["feature_set"] == PROJECT_FEATURE_SET
    assert contract["source_of_truth"] is True
    assert contract["headless_capable"] is True
    assert "decision_created" in contract["events"]
    assert "invalidation" in contract["decision_object"]
    assert "render" not in contract["policy"].lower()


def test_engine_status_reads_existing_brain_without_runtime_ownership():
    with setup_db() as db:
        payload = BlumEngineFacade().status(db)

    assert payload["source_of_truth"] is True
    assert payload["headless_capable"] is True
    assert payload["current_brain_status"]["status"] in {"ready", "insufficient_evidence"}
    assert payload["current_paper_trading_status"]["no_broker_execution"] is True


def test_runtime_contract_is_replaceable_and_not_intelligent():
    with setup_db() as db:
        payload = BlumRuntimeFacade().status(db)

    assert payload["owns_intelligence"] is False
    assert [surface["route"] for surface in payload["primary_surfaces"]] == ["/", "/training-ground", "/paper-trading", "/alpha"]
    assert "/performance" in payload["developer_surfaces"]
    assert "never owns financial intelligence" in payload["policy"].lower()


def test_analyst_contract_targets_future_model_without_training():
    with setup_db() as db:
        payload = BlumAnalystDatasetPipeline().status(db)

    assert payload["model_repository"] == "Italianhype/Blum-Analyst"
    assert payload["automatic_training_enabled"] is False
    assert payload["contract"]["source_of_truth"] is False
    assert "sft_jsonl" in payload["contract"]["supported_training_modes"]


def test_split_packages_do_not_depend_on_product_ui():
    root = Path(__file__).resolve().parents[1] / "app"
    checked = []
    for package in ("engine", "analyst"):
        for path in (root / package).glob("*.py"):
            text = path.read_text()
            checked.append(path.name)
            assert "frontend" not in text
            assert "next/" not in text.lower()
            assert "react" not in text.lower()
            assert "tsx" not in text.lower()
    assert checked


def test_event_contract_names_required_engine_events():
    events = set(event_contract())

    assert {
        "market_updated",
        "decision_created",
        "paper_trade_completed",
        "learning_cycle_completed",
        "dataset_exported",
        "brain_score_updated",
    }.issubset(events)
