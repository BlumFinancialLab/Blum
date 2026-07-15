from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0010_financial_chat_memory"
down_revision = "0009_auto_dataset_intel"
branch_labels = None
depends_on = None


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_key", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=220), nullable=False),
        sa.Column("language", sa.String(length=12), nullable=False),
        sa.Column("horizon", sa.String(length=80), nullable=False),
        sa.Column("risk_profile", sa.String(length=80), nullable=False),
        sa.Column("metadata_payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_key", name="uq_chat_session_key"),
    )
    op.create_index("ix_chat_sessions_session_key", "chat_sessions", ["session_key"])
    op.create_index("ix_chat_sessions_language", "chat_sessions", ["language"])
    op.create_index("ix_chat_sessions_horizon", "chat_sessions", ["horizon"])
    op.create_index("ix_chat_sessions_risk_profile", "chat_sessions", ["risk_profile"])
    op.create_index("ix_chat_sessions_created_at", "chat_sessions", ["created_at"])
    op.create_index("ix_chat_sessions_updated", "chat_sessions", ["updated_at"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=12), nullable=False),
        sa.Column("response_payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])
    op.create_index("ix_chat_messages_role", "chat_messages", ["role"])
    op.create_index("ix_chat_messages_language", "chat_messages", ["language"])
    op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"])
    op.create_index("ix_chat_messages_session_created", "chat_messages", ["session_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_session_created", table_name="chat_messages")
    op.drop_index("ix_chat_messages_created_at", table_name="chat_messages")
    op.drop_index("ix_chat_messages_language", table_name="chat_messages")
    op.drop_index("ix_chat_messages_role", table_name="chat_messages")
    op.drop_index("ix_chat_messages_session_id", table_name="chat_messages")
    op.drop_table("chat_messages")

    op.drop_index("ix_chat_sessions_updated", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_created_at", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_risk_profile", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_horizon", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_language", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_session_key", table_name="chat_sessions")
    op.drop_table("chat_sessions")

