#!/usr/bin/env python3
"""Executable boundary for the BLUM FinRL-X background runner."""

from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.trading_ml.finrlx_runner import main


if __name__ == "__main__":
    main()
