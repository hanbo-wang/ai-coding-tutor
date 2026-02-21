"""Add admin audit log and token usage schema

Revision ID: 007
Revises: 006

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("input_tokens", sa.Integer(), nullable=True))
    op.add_column("chat_messages", sa.Column("output_tokens", sa.Integer(), nullable=True))

    op.create_table(
        "daily_token_usage",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("input_tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_daily_token_usage_user_date",
        "daily_token_usage",
        ["user_id", "date"],
        unique=True,
    )

    op.create_table(
        "admin_audit_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("admin_email", sa.String(255), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", UUID(as_uuid=True), nullable=True),
        sa.Column("resource_title", sa.String(255), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_index(
        "ix_admin_audit_log_created",
        "admin_audit_log",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_admin_audit_log_created", table_name="admin_audit_log")
    op.drop_table("admin_audit_log")

    op.drop_index("ix_daily_token_usage_user_date", table_name="daily_token_usage")
    op.drop_table("daily_token_usage")

    op.drop_column("chat_messages", "output_tokens")
    op.drop_column("chat_messages", "input_tokens")
