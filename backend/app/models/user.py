"""User model and SQLAlchemy declarative base."""

import uuid
from datetime import datetime

from sqlalchemy import String, Integer, Float, Boolean, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    username: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    programming_level: Mapped[int] = mapped_column(Integer, default=3)
    maths_level: Mapped[int] = mapped_column(Integer, default=3)
    effective_programming_level: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    effective_maths_level: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
