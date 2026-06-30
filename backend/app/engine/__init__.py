"""BLUM Engine boundary.

The Engine is the only source of truth for financial intelligence. Runtime
surfaces and future clients consume this package through explicit contracts.
"""

from app.engine.contracts import ENGINE_VERSION, PROJECT_FEATURE_SET

__all__ = ["ENGINE_VERSION", "PROJECT_FEATURE_SET"]
