from __future__ import annotations

from importlib import import_module
from typing import Callable

from app.services.deterministic_execution.contracts import KernelHealth


def _load_nautilus():
    return import_module("nautilus_trader")


def kernel_health(*, loader: Callable = _load_nautilus, mode: str = "shadow") -> KernelHealth:
    try:
        module = loader()
    except (ImportError, ModuleNotFoundError, OSError) as exc:
        return KernelHealth(
            status="UNAVAILABLE",
            available=False,
            version=None,
            mode="unavailable",
            reason=str(exc),
        )
    return KernelHealth(
        status="READY",
        available=True,
        version=str(getattr(module, "__version__", "unknown")),
        mode=mode,
        capabilities=("backtest", "paper", "equity", "etf", "forex"),
    )
