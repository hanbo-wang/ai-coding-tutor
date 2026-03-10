"""Add retained usage archive tables.

Revision ID: 010
Revises: 009

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "retained_daily_token_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("input_tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "archived_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_retained_daily_token_usage_email_date",
        "retained_daily_token_usage",
        ["email_hash", "date"],
        unique=True,
    )
    op.create_table(
        "retained_model_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("llm_provider", sa.String(length=32), nullable=True),
        sa.Column("llm_model", sa.String(length=100), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "estimated_cost_usd",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "assistant_message_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "cost_metadata_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "archived_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_retained_model_usage_date",
        "retained_model_usage",
        ["date"],
        unique=False,
    )
    op.create_index(
        "ix_retained_model_usage_provider_model_date",
        "retained_model_usage",
        ["llm_provider", "llm_model", "date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_retained_model_usage_provider_model_date",
        table_name="retained_model_usage",
    )
    op.drop_index(
        "ix_retained_model_usage_date",
        table_name="retained_model_usage",
    )
    op.drop_table("retained_model_usage")
    op.drop_index(
        "ix_retained_daily_token_usage_email_date",
        table_name="retained_daily_token_usage",
    )
    op.drop_table("retained_daily_token_usage")
