"""Add hidden chat session summary cache fields.

Revision ID: 008
Revises: 007

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column("context_summary_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "chat_sessions",
        sa.Column("context_summary_message_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "chat_sessions",
        sa.Column("context_summary_updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_sessions", "context_summary_updated_at")
    op.drop_column("chat_sessions", "context_summary_message_count")
    op.drop_column("chat_sessions", "context_summary_text")
