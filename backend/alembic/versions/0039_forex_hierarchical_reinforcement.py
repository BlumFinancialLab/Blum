"""Add hierarchical Forex reinforcement policy scopes.

Revision ID: 0039_forex_hierarchical_rl
Revises: 0038_forex_rl_model_council
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0039_forex_hierarchical_rl"
down_revision = "0038_forex_rl_model_council"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("forex_policy_states") as batch:
        batch.add_column(
            sa.Column(
                "cause_counts_json",
                JSON_TYPE,
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )

    with op.batch_alter_table("forex_policy_updates") as batch:
        batch.add_column(
            sa.Column(
                "policy_scope",
                sa.String(32),
                nullable=False,
                server_default="FULL_CONTEXT",
            )
        )
        batch.drop_constraint("uq_forex_policy_update_evidence", type_="unique")
        batch.create_unique_constraint(
            "uq_forex_policy_update_evidence_scope",
            ["evidence_id", "policy_scope"],
        )
        batch.create_index(
            "ix_forex_policy_updates_policy_scope",
            ["policy_scope"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("forex_policy_updates") as batch:
        batch.drop_index("ix_forex_policy_updates_policy_scope")
        batch.drop_constraint(
            "uq_forex_policy_update_evidence_scope",
            type_="unique",
        )
        batch.create_unique_constraint(
            "uq_forex_policy_update_evidence",
            ["evidence_id"],
        )
        batch.drop_column("policy_scope")

    with op.batch_alter_table("forex_policy_states") as batch:
        batch.drop_column("cause_counts_json")
