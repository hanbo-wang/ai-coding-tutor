"""Add unique index for scoped chat sessions

Revision ID: 006
Revises: 005

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_chat_sessions_scoped",
        "chat_sessions",
        ["user_id", "session_type", "module_id"],
        unique=True,
        postgresql_where=sa.text(
            "module_id IS NOT NULL AND session_type IN ('notebook', 'zone')"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_chat_sessions_scoped", table_name="chat_sessions")
