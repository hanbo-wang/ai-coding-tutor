"""User account deletion and owned-data cleanup helpers."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatSession, UploadedFile
from app.models.email_verification import EmailVerificationToken
from app.models.notebook import UserNotebook
from app.models.user import User
from app.models.zone import ZoneNotebookProgress
from app.services.chat_service import (
    archive_model_usage_for_deleted_sessions,
    archive_token_usage_for_deleted_user,
)


async def delete_user_account(
    db: AsyncSession,
    user: User,
) -> list[str]:
    """Delete a user account and return owned file paths for post-commit cleanup."""
    notebook_paths = list(
        (
            await db.execute(
                select(UserNotebook.storage_path).where(UserNotebook.user_id == user.id)
            )
        ).scalars()
    )
    upload_paths = list(
        (
            await db.execute(
                select(UploadedFile.storage_path).where(UploadedFile.user_id == user.id)
            )
        ).scalars()
    )
    session_ids = list(
        (
            await db.execute(select(ChatSession.id).where(ChatSession.user_id == user.id))
        ).scalars()
    )

    if session_ids:
        # Preserve admin usage visibility before removing the underlying chat rows.
        await archive_model_usage_for_deleted_sessions(db, session_ids=session_ids)
        await db.execute(
            delete(ChatMessage).where(ChatMessage.session_id.in_(session_ids))
        )
        await db.execute(delete(ChatSession).where(ChatSession.id.in_(session_ids)))

    await archive_token_usage_for_deleted_user(db, user_id=user.id, email=user.email)
    await db.execute(
        delete(ZoneNotebookProgress).where(ZoneNotebookProgress.user_id == user.id)
    )
    await db.execute(delete(UserNotebook).where(UserNotebook.user_id == user.id))
    await db.execute(delete(UploadedFile).where(UploadedFile.user_id == user.id))
    await db.execute(
        delete(EmailVerificationToken).where(EmailVerificationToken.email == user.email)
    )
    await db.delete(user)
    await db.flush()

    # File deletion happens after commit so failed transactions do not orphan DB rows.
    return list(dict.fromkeys([*notebook_paths, *upload_paths]))
