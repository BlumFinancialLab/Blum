from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0029_learning_acceleration_engine"
down_revision = "0028_paper_forward_core"
branch_labels = None
depends_on = None


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table_name: str) -> set[str]:
    if table_name not in _tables():
        return set()
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if index_name not in _indexes(table_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    if "blum_learning_experiments" not in _tables():
        op.create_table(
            "blum_learning_experiments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("experiment_id", sa.String(length=140), nullable=False),
            sa.Column("hypothesis", sa.Text(), nullable=False, server_default=""),
            sa.Column("target_market", sa.String(length=100), nullable=False, server_default=""),
            sa.Column("target_asset_class", sa.String(length=80), nullable=False, server_default=""),
            sa.Column("target_setup", sa.String(length=140), nullable=False, server_default=""),
            sa.Column("training_window", json_type, nullable=True),
            sa.Column("validation_window", json_type, nullable=True),
            sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("benchmark_asset", sa.String(length=32), nullable=False, server_default="SPY"),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="PROPOSED"),
            sa.Column("result_summary", json_type, nullable=True),
            sa.Column("conclusion", sa.Text(), nullable=False, server_default=""),
            sa.Column("next_action", sa.Text(), nullable=False, server_default=""),
            sa.Column("source_payload", json_type, nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("experiment_id", name="uq_blum_learning_experiment_id"),
        )
    _create_index_if_missing("ix_blum_learning_experiments_experiment_id", "blum_learning_experiments", ["experiment_id"])
    _create_index_if_missing("ix_blum_learning_experiments_benchmark_asset", "blum_learning_experiments", ["benchmark_asset"])
    _create_index_if_missing("ix_blum_learning_experiments_status", "blum_learning_experiments", ["status"])
    _create_index_if_missing("ix_blum_learning_experiments_target_asset_class", "blum_learning_experiments", ["target_asset_class"])
    _create_index_if_missing("ix_blum_learning_experiments_target_market", "blum_learning_experiments", ["target_market"])
    _create_index_if_missing("ix_blum_learning_experiments_target_setup", "blum_learning_experiments", ["target_setup"])
    _create_index_if_missing("ix_blum_learning_experiments_created_at", "blum_learning_experiments", ["created_at"])
    _create_index_if_missing("ix_blum_learning_experiments_sample_size", "blum_learning_experiments", ["sample_size"])
    _create_index_if_missing("ix_blum_learning_experiments_status_created", "blum_learning_experiments", ["status", "created_at"])
    _create_index_if_missing("ix_blum_learning_experiments_setup_status", "blum_learning_experiments", ["target_setup", "status"])


def downgrade() -> None:
    if "blum_learning_experiments" in _tables():
        op.drop_table("blum_learning_experiments")
