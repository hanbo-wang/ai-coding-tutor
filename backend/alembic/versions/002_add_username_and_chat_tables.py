"""Add effective levels and chat tables

Revision ID: 002
Revises: 001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add effective level columns
    op.add_column(
        "users", sa.Column("effective_programming_level", sa.Float(), nullable=True)
    )
    op.add_column(
        "users", sa.Column("effective_maths_level", sa.Float(), nullable=True)
    )

    # Create chat_sessions table
    op.create_table(
        "chat_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_type", sa.String(20), nullable=False, server_default="general"),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=True, server_default=sa.text("now()")
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_chat_sessions_user_type", "chat_sessions", ["user_id", "session_type"]
    )

    # Create chat_messages table
    op.create_table(
        "chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("programming_difficulty", sa.Integer(), nullable=True),
        sa.Column("maths_difficulty", sa.Integer(), nullable=True),
        sa.Column("programming_hint_level_used", sa.Integer(), nullable=True),
        sa.Column("maths_hint_level_used", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=True, server_default=sa.text("now()")
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["chat_sessions.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_chat_messages_session_created",
        "chat_messages",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_session_created", table_name="chat_messages")
    op.drop_table("chat_messages")

    op.drop_index("ix_chat_sessions_user_type", table_name="chat_sessions")
    op.drop_table("chat_sessions")

    op.drop_column("users", "effective_maths_level")
    op.drop_column("users", "effective_programming_level")
