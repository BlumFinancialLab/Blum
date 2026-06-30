from __future__ import annotations

from sqlalchemy.orm import Session

from app.analyst.contracts import analyst_dataset_contract
from app.core.config import get_settings
from app.services.blum_financial_model import export_training_jsonl, training_manifest


class BlumAnalystDatasetPipeline:
    """Dataset pipeline boundary for the future BLUM Analyst model.

    This service prepares and reports on training data. It intentionally does
    not start fine-tuning, require GPU, or make model outputs authoritative.
    """

    def contract(self) -> dict:
        return analyst_dataset_contract(get_settings().blum_analyst_repository).to_dict()

    def status(self, db: Session) -> dict:
        settings = get_settings()
        manifest = training_manifest()
        manifest["target_repository"] = settings.blum_analyst_repository
        return {
            "status": "ready",
            "contract": self.contract(),
            "training_manifest": manifest,
            "automatic_training_enabled": False,
            "model_repository": settings.blum_analyst_repository,
            "policy": "Dataset export is allowed; automatic model training and inference dependencies are not enabled in Runtime.",
        }

    def export(self, db: Session, *, limit: int = 1000, min_quality: float = 60.0, export_name: str | None = None) -> dict:
        result = export_training_jsonl(db, limit=limit, min_quality=min_quality, export_name=export_name)
        result["target_model_repository"] = get_settings().blum_analyst_repository
        result["contract"] = self.contract()
        result["policy"] = "Exported dataset is for supervised or preference training review; no training job was started."
        return result
