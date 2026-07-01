from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0027_feedback_loop"
down_revision = "0026_alpha_operating_system"
branch_labels = None
depends_on = None


json_type = postgresql.JSONB(astext_type=sa.Text())


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table_name: str) -> set[str]:
    if table_name not in _tables():
        return set()
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if column.name not in _columns(table_name):
        op.add_column(table_name, column)


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if index_name not in _indexes(table_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    _add_column_if_missing("historical_predictions", sa.Column("model_version_used", sa.String(length=100), nullable=True))
    _add_column_if_missing("historical_predictions", sa.Column("weights_used", json_type, nullable=True))
    _add_column_if_missing("historical_predictions", sa.Column("learning_memory_used", json_type, nullable=True))
    _add_column_if_missing("historical_predictions", sa.Column("strategy_memory_used", json_type, nullable=True))
    _add_column_if_missing("historical_predictions", sa.Column("research_priority_used", json_type, nullable=True))
    _create_index_if_missing("ix_historical_predictions_model_version_used", "historical_predictions", ["model_version_used"])

    if "feedback_loop_audits" not in _tables():
        op.create_table(
            "feedback_loop_audits",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("prediction_id", sa.Integer(), nullable=True),
            sa.Column("ticker", sa.String(length=32), nullable=False),
            sa.Column("model_version_used", sa.String(length=100), nullable=False, server_default="base-static"),
            sa.Column("learned_knowledge_json", json_type, nullable=True),
            sa.Column("changes_applied_json", json_type, nullable=True),
            sa.Column("future_decision_json", json_type, nullable=True),
            sa.Column("outcome_json", json_type, nullable=True),
            sa.Column("improvement_detected", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("evidence_grade", sa.String(length=80), nullable=False, server_default="insufficient"),
            sa.Column("summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["prediction_id"], ["historical_predictions.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("ix_feedback_loop_audits_prediction_id", "feedback_loop_audits", ["prediction_id"])
    _create_index_if_missing("ix_feedback_loop_audits_ticker", "feedback_loop_audits", ["ticker"])
    _create_index_if_missing("ix_feedback_loop_audits_model_version_used", "feedback_loop_audits", ["model_version_used"])
    _create_index_if_missing("ix_feedback_loop_audits_improvement_detected", "feedback_loop_audits", ["improvement_detected"])
    _create_index_if_missing("ix_feedback_loop_audits_created_at", "feedback_loop_audits", ["created_at"])
    _create_index_if_missing("ix_feedback_loop_audits_prediction_created", "feedback_loop_audits", ["prediction_id", "created_at"])
    _create_index_if_missing("ix_feedback_loop_audits_model_created", "feedback_loop_audits", ["model_version_used", "created_at"])
    _create_index_if_missing("ix_feedback_loop_audits_improvement", "feedback_loop_audits", ["improvement_detected", "created_at"])


def downgrade() -> None:
    if "feedback_loop_audits" in _tables():
        op.drop_table("feedback_loop_audits")
    if "ix_historical_predictions_model_version_used" in _indexes("historical_predictions"):
        op.drop_index("ix_historical_predictions_model_version_used", table_name="historical_predictions")
    existing = _columns("historical_predictions")
    for column_name in [
        "research_priority_used",
        "strategy_memory_used",
        "learning_memory_used",
        "weights_used",
        "model_version_used",
    ]:
        if column_name in existing:
            op.drop_column("historical_predictions", column_name)
