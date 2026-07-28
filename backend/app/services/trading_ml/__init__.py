"""Trading ML contracts and point-in-time feature builders."""

from .contracts import FeatureSchema, TradingMLAdvice, TradingMLExample
from .dataset import DatasetSlice, TradingMLDatasetRepository
from .feature_store import FeatureStoreLockTimeout, ProjectionResult, TradingMLFeatureStoreProjector
from .features import EVIDENCE_WEIGHTS, FutureFeatureDataError, IneligibleFeatureDataError, TradingMLFeatureBuilder, UnlabeledFeatureDataError
from .inference import TradingMLInferenceService
from .registry import TradingMLModelRegistry, TradingMLPromotionService
from .training import BoundedOptunaChallengerSearch, OnlineShadowTrainer, SklearnTradingModelTrainer
from .worker import TradingMLLearningWorker

__all__ = [
    "EVIDENCE_WEIGHTS",
    "DatasetSlice",
    "FeatureSchema",
    "FeatureStoreLockTimeout",
    "FutureFeatureDataError",
    "IneligibleFeatureDataError",
    "TradingMLAdvice",
    "TradingMLDatasetRepository",
    "TradingMLExample",
    "TradingMLFeatureStoreProjector",
    "TradingMLFeatureBuilder",
    "TradingMLInferenceService",
    "TradingMLLearningWorker",
    "TradingMLModelRegistry",
    "TradingMLPromotionService",
    "OnlineShadowTrainer",
    "SklearnTradingModelTrainer",
    "BoundedOptunaChallengerSearch",
    "UnlabeledFeatureDataError",
    "ProjectionResult",
]
