from app.api.routers.alpha import router as alpha_router
from app.api.routers.analyst import router as analyst_router
from app.api.routers.brain import router as brain_router
from app.api.routers.legacy import router as legacy_router
from app.api.routers.paper_trading import router as paper_trading_router
from app.api.routers.runtime import router as runtime_router
from app.api.routers.training import router as training_router

__all__ = [
    "alpha_router",
    "analyst_router",
    "brain_router",
    "legacy_router",
    "paper_trading_router",
    "runtime_router",
    "training_router",
]
