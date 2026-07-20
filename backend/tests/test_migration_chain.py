from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, inspect, text


def test_full_migration_chain_reaches_head_on_sqlite(tmp_path):
    backend_dir = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "migration-audit.db"
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite:///{database_path}"

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    engine = create_engine(f"sqlite:///{database_path}")
    tables = set(inspect(engine).get_table_names())
    required_tables = {
        "learning_runs",
        "historical_predictions",
        "prediction_outcomes",
        "strategy_memory",
        "model_versions",
        "feedback_loop_audits",
        "live_forward_paper_trades",
        "strategy_factory_runs",
        "strategy_candidate_variants",
        "paper_execution_orders",
        "dashboard_snapshots",
        "brain_runtime_events",
        "background_job_state",
    }

    assert required_tables.issubset(tables)
    with engine.connect() as connection:
        assert connection.execute(text("select version_num from alembic_version")).scalar_one() == "0035_decision_execution_parity"

    downgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert downgrade.returncode == 0, downgrade.stderr
