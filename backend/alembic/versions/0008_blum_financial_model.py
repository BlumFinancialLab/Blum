from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008_blum_financial_model"
down_revision = "0007_chart_vision"
branch_labels = None
depends_on = None


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "blum_knowledge_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("signal_id", sa.Integer(), nullable=True),
        sa.Column("ai_insight_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=False),
        sa.Column("industry", sa.String(length=160), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("reasoning_hash", sa.String(length=128), nullable=False),
        sa.Column("market_regime", sa.String(length=120), nullable=False),
        sa.Column("volatility_regime", sa.String(length=80), nullable=False),
        sa.Column("risk_sentiment", sa.String(length=80), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("conviction_score", sa.Float(), nullable=False),
        sa.Column("market_context", json_type, nullable=False),
        sa.Column("asset_context", json_type, nullable=False),
        sa.Column("blum_reasoning", json_type, nullable=False),
        sa.Column("prediction_horizons", json_type, nullable=False),
        sa.Column("quality_scores", json_type, nullable=False),
        sa.Column("self_critique", json_type, nullable=False),
        sa.Column("training_sample", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["ai_insight_id"], ["ai_insights.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["signal_id"], ["signal_snapshots.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reasoning_hash", name="uq_blum_knowledge_reasoning_hash"),
    )
    for column in ["asset_id", "signal_id", "ai_insight_id", "ticker", "source_type", "reasoning_hash", "market_regime", "volatility_regime", "risk_sentiment", "confidence", "conviction_score", "created_at", "updated_at"]:
        op.create_index(f"ix_blum_knowledge_records_{column}", "blum_knowledge_records", [column])
    op.create_index("ix_blum_knowledge_ticker_created", "blum_knowledge_records", ["ticker", "created_at"])
    op.create_index("ix_blum_knowledge_regime_created", "blum_knowledge_records", ["market_regime", "created_at"])

    op.create_table(
        "blum_thesis_outcomes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("knowledge_record_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("expected_direction", sa.String(length=80), nullable=False),
        sa.Column("price_at_thesis", sa.Float(), nullable=True),
        sa.Column("price_after_horizon", sa.Float(), nullable=True),
        sa.Column("realized_return", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("max_upside", sa.Float(), nullable=True),
        sa.Column("realized_volatility", sa.Float(), nullable=True),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=True),
        sa.Column("outcome_payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["knowledge_record_id"], ["blum_knowledge_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("knowledge_record_id", "horizon_days", name="uq_blum_thesis_outcome_record_horizon"),
    )
    for column in ["knowledge_record_id", "asset_id", "ticker", "horizon_days", "expected_direction", "realized_return", "outcome", "success", "created_at", "updated_at"]:
        op.create_index(f"ix_blum_thesis_outcomes_{column}", "blum_thesis_outcomes", [column])
    op.create_index("ix_blum_thesis_outcomes_ticker_horizon", "blum_thesis_outcomes", ["ticker", "horizon_days"])

    op.create_table(
        "blum_reasoning_memory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("knowledge_record_id", sa.Integer(), nullable=True),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=True),
        sa.Column("memory_type", sa.String(length=80), nullable=False),
        sa.Column("embedding_model", sa.String(length=160), nullable=False),
        sa.Column("embedding", json_type, nullable=False),
        sa.Column("memory_text", sa.Text(), nullable=False),
        sa.Column("metadata_payload", json_type, nullable=False),
        sa.Column("outcome_label", sa.String(length=80), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["knowledge_record_id"], ["blum_knowledge_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ["knowledge_record_id", "asset_id", "ticker", "memory_type", "embedding_model", "outcome_label", "quality_score", "created_at"]:
        op.create_index(f"ix_blum_reasoning_memory_{column}", "blum_reasoning_memory", [column])
    op.create_index("ix_blum_reasoning_memory_ticker_type_created", "blum_reasoning_memory", ["ticker", "memory_type", "created_at"])

    op.create_table(
        "blum_training_examples",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("knowledge_record_id", sa.Integer(), nullable=True),
        sa.Column("task_type", sa.String(length=100), nullable=False),
        sa.Column("dataset_split", sa.String(length=40), nullable=False),
        sa.Column("base_model_family", sa.String(length=80), nullable=False),
        sa.Column("input_payload", json_type, nullable=False),
        sa.Column("output_payload", json_type, nullable=False),
        sa.Column("messages", json_type, nullable=False),
        sa.Column("quality_scores", json_type, nullable=False),
        sa.Column("preference_payload", json_type, nullable=False),
        sa.Column("export_ready", sa.Boolean(), nullable=False),
        sa.Column("exported_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["knowledge_record_id"], ["blum_knowledge_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("knowledge_record_id", "task_type", name="uq_blum_training_record_task"),
    )
    for column in ["knowledge_record_id", "task_type", "dataset_split", "base_model_family", "export_ready", "exported_at", "created_at", "updated_at"]:
        op.create_index(f"ix_blum_training_examples_{column}", "blum_training_examples", [column])
    op.create_index("ix_blum_training_examples_ready_created", "blum_training_examples", ["export_ready", "created_at"])

    op.create_table(
        "blum_thesis_quality_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("knowledge_record_id", sa.Integer(), nullable=False),
        sa.Column("reasoning_depth", sa.Float(), nullable=False),
        sa.Column("consistency", sa.Float(), nullable=False),
        sa.Column("contradiction_handling", sa.Float(), nullable=False),
        sa.Column("confidence_calibration", sa.Float(), nullable=False),
        sa.Column("historical_alignment", sa.Float(), nullable=False),
        sa.Column("narrative_quality", sa.Float(), nullable=False),
        sa.Column("explainability_quality", sa.Float(), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("evaluator_version", sa.String(length=80), nullable=False),
        sa.Column("quality_payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["knowledge_record_id"], ["blum_knowledge_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("knowledge_record_id", name="uq_blum_quality_record"),
    )
    for column in ["knowledge_record_id", "overall_score", "evaluator_version", "created_at"]:
        op.create_index(f"ix_blum_thesis_quality_scores_{column}", "blum_thesis_quality_scores", [column])

    op.create_table(
        "blum_self_critiques",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("knowledge_record_id", sa.Integer(), nullable=False),
        sa.Column("analyst_view", json_type, nullable=False),
        sa.Column("skeptic_view", json_type, nullable=False),
        sa.Column("historical_view", json_type, nullable=False),
        sa.Column("final_view", json_type, nullable=False),
        sa.Column("critique_payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["knowledge_record_id"], ["blum_knowledge_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("knowledge_record_id", name="uq_blum_self_critique_record"),
    )
    op.create_index("ix_blum_self_critiques_knowledge_record_id", "blum_self_critiques", ["knowledge_record_id"])
    op.create_index("ix_blum_self_critiques_created_at", "blum_self_critiques", ["created_at"])

    op.create_table(
        "blum_narrative_memory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("narrative", sa.String(length=160), nullable=False),
        sa.Column("lifecycle_stage", sa.String(length=80), nullable=False),
        sa.Column("intensity", sa.Float(), nullable=False),
        sa.Column("velocity", sa.Float(), nullable=False),
        sa.Column("saturation", sa.Float(), nullable=False),
        sa.Column("crowding", sa.Float(), nullable=False),
        sa.Column("linked_assets", json_type, nullable=False),
        sa.Column("sectors", json_type, nullable=False),
        sa.Column("outcome_summary", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ["narrative", "lifecycle_stage", "intensity", "created_at", "updated_at"]:
        op.create_index(f"ix_blum_narrative_memory_{column}", "blum_narrative_memory", [column])
    op.create_index("ix_blum_narrative_stage_updated", "blum_narrative_memory", ["lifecycle_stage", "updated_at"])

    op.create_table(
        "blum_regime_memory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("market_regime", sa.String(length=120), nullable=False),
        sa.Column("volatility_regime", sa.String(length=80), nullable=False),
        sa.Column("liquidity_regime", sa.String(length=80), nullable=False),
        sa.Column("macro_context", json_type, nullable=False),
        sa.Column("reasoning_patterns", json_type, nullable=False),
        sa.Column("outcome_summary", json_type, nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ["market_regime", "volatility_regime", "liquidity_regime", "sample_count", "created_at", "updated_at"]:
        op.create_index(f"ix_blum_regime_memory_{column}", "blum_regime_memory", [column])
    op.create_index("ix_blum_regime_memory_regime_updated", "blum_regime_memory", ["market_regime", "updated_at"])

    op.create_table(
        "blum_knowledge_graph_nodes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("node_type", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=220), nullable=False),
        sa.Column("canonical_key", sa.String(length=260), nullable=False),
        sa.Column("properties", json_type, nullable=False),
        sa.Column("embedding", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_key", name="uq_blum_graph_node_key"),
    )
    for column in ["node_type", "label", "canonical_key", "created_at", "updated_at"]:
        op.create_index(f"ix_blum_knowledge_graph_nodes_{column}", "blum_knowledge_graph_nodes", [column])

    op.create_table(
        "blum_knowledge_graph_edges",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_node_id", sa.Integer(), nullable=False),
        sa.Column("target_node_id", sa.Integer(), nullable=False),
        sa.Column("relation_type", sa.String(length=100), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("evidence", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_node_id"], ["blum_knowledge_graph_nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_node_id"], ["blum_knowledge_graph_nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_node_id", "target_node_id", "relation_type", name="uq_blum_graph_edge"),
    )
    for column in ["source_node_id", "target_node_id", "relation_type", "weight", "created_at", "updated_at"]:
        op.create_index(f"ix_blum_knowledge_graph_edges_{column}", "blum_knowledge_graph_edges", [column])
    op.create_index("ix_blum_graph_edges_relation_created", "blum_knowledge_graph_edges", ["relation_type", "created_at"])

    op.create_table(
        "blum_dataset_exports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("export_name", sa.String(length=180), nullable=False),
        sa.Column("format", sa.String(length=40), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("filters", json_type, nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("payload_summary", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ["export_name", "format", "status", "created_at"]:
        op.create_index(f"ix_blum_dataset_exports_{column}", "blum_dataset_exports", [column])
    op.create_index("ix_blum_dataset_exports_status_created", "blum_dataset_exports", ["status", "created_at"])

    op.create_table(
        "blum_model_training_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_name", sa.String(length=180), nullable=False),
        sa.Column("model_family", sa.String(length=80), nullable=False),
        sa.Column("base_model", sa.String(length=180), nullable=False),
        sa.Column("method", sa.String(length=80), nullable=False),
        sa.Column("dataset_export_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("training_config", json_type, nullable=False),
        sa.Column("metrics", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_export_id"], ["blum_dataset_exports.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ["job_name", "model_family", "base_model", "method", "dataset_export_id", "status", "created_at", "updated_at"]:
        op.create_index(f"ix_blum_model_training_jobs_{column}", "blum_model_training_jobs", [column])
    op.create_index("ix_blum_training_jobs_status_created", "blum_model_training_jobs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_table("blum_model_training_jobs")
    op.drop_table("blum_dataset_exports")
    op.drop_table("blum_knowledge_graph_edges")
    op.drop_table("blum_knowledge_graph_nodes")
    op.drop_table("blum_regime_memory")
    op.drop_table("blum_narrative_memory")
    op.drop_table("blum_self_critiques")
    op.drop_table("blum_thesis_quality_scores")
    op.drop_table("blum_training_examples")
    op.drop_table("blum_reasoning_memory")
    op.drop_table("blum_thesis_outcomes")
    op.drop_table("blum_knowledge_records")
