"""Chat session and message persistence."""

import uuid
import json
from datetime import date, datetime, timezone

from sqlalchemy import and_, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.models.chat import ChatSession, ChatMessage, DailyTokenUsage, UploadedFile
from app.config import settings
from app.services.upload_service import attachment_payload


def _utc_now_naive() -> datetime:
    """Return a naive UTC datetime without deprecated utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def get_or_create_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    session_id: uuid.UUID | None = None,
    session_type: str = "general",
    module_id: uuid.UUID | None = None,
) -> ChatSession:
    """Return the given session or create a new scoped session."""
    if session_id:
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.id == session_id, ChatSession.user_id == user_id
            )
        )
        session = result.scalar_one_or_none()
        if session:
            return session

    if module_id is not None and session_type in {"notebook", "zone"}:
        existing = await get_session_by_scope(db, user_id, session_type, module_id)
        if existing:
            return existing

        try:
            async with db.begin_nested():
                session = ChatSession(
                    user_id=user_id,
                    session_type=session_type,
                    module_id=module_id,
                )
                db.add(session)
                await db.flush()
                return session
        except IntegrityError:
            existing_after_conflict = await get_session_by_scope(
                db, user_id, session_type, module_id
            )
            if existing_after_conflict:
                return existing_after_conflict
            raise

    session = ChatSession(user_id=user_id, session_type=session_type, module_id=module_id)
    db.add(session)
    await db.flush()
    return session


async def get_session_by_scope(
    db: AsyncSession,
    user_id: uuid.UUID,
    session_type: str,
    module_id: uuid.UUID,
) -> ChatSession | None:
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.user_id == user_id,
            ChatSession.session_type == session_type,
            ChatSession.module_id == module_id,
        ).order_by(ChatSession.created_at.desc())
    )
    return result.scalars().first()


async def save_message(
    db: AsyncSession,
    session_id: uuid.UUID,
    role: str,
    content: str,
    hint_level_used: int | None = None,
    problem_difficulty: int | None = None,
    maths_difficulty: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    attachment_ids: list[str] | None = None,
) -> ChatMessage:
    """Persist a chat message to the database."""
    msg = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        hint_level_used=hint_level_used,
        problem_difficulty=problem_difficulty,
        maths_difficulty=maths_difficulty,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        attachments_json=json.dumps(attachment_ids) if attachment_ids else None,
    )
    db.add(msg)
    await db.flush()
    return msg


async def get_chat_history(
    db: AsyncSession, session_id: uuid.UUID
) -> list[dict]:
    """Load all messages from a session in chronological order."""
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    messages = result.scalars().all()
    return [{"role": m.role, "content": m.content} for m in messages]


async def get_session_messages(
    db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID
) -> list[dict] | None:
    """Load all messages for a session (with ownership check)."""
    sess_result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id, ChatSession.user_id == user_id
        )
    )
    if not sess_result.scalar_one_or_none():
        return None

    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    messages = result.scalars().all()

    all_attachment_ids: list[uuid.UUID] = []
    message_attachment_ids: list[list[str]] = []
    for message in messages:
        if not message.attachments_json:
            message_attachment_ids.append([])
            continue
        try:
            ids = json.loads(message.attachments_json)
            if not isinstance(ids, list):
                ids = []
        except json.JSONDecodeError:
            ids = []
        str_ids = [str(item) for item in ids]
        message_attachment_ids.append(str_ids)
        for item in str_ids:
            try:
                all_attachment_ids.append(uuid.UUID(item))
            except ValueError:
                continue

    attachment_map: dict[str, dict] = {}
    if all_attachment_ids:
        now = _utc_now_naive()
        attachment_result = await db.execute(
            select(UploadedFile).where(
                UploadedFile.user_id == user_id,
                UploadedFile.id.in_(all_attachment_ids),
                UploadedFile.expires_at >= now,
            )
        )
        attachment_rows = attachment_result.scalars().all()
        attachment_map = {
            str(row.id): attachment_payload(row) for row in attachment_rows
        }

    return [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "hint_level_used": m.hint_level_used,
            "problem_difficulty": m.problem_difficulty,
            "maths_difficulty": m.maths_difficulty,
            "attachments": [
                attachment_map[item_id]
                for item_id in attachment_ids
                if item_id in attachment_map
            ],
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m, attachment_ids in zip(messages, message_attachment_ids)
    ]


async def get_user_sessions(
    db: AsyncSession, user_id: uuid.UUID
) -> list[dict]:
    """Return all sessions for a user, newest first, with preview text."""
    first_user_message = (
        select(
            ChatMessage.session_id.label("session_id"),
            ChatMessage.content.label("content"),
            func.row_number()
            .over(
                partition_by=ChatMessage.session_id,
                order_by=ChatMessage.created_at.asc(),
            )
            .label("rn"),
        )
        .where(ChatMessage.role == "user")
        .subquery()
    )

    result = await db.execute(
        select(ChatSession, first_user_message.c.content)
        .outerjoin(
            first_user_message,
            and_(
                first_user_message.c.session_id == ChatSession.id,
                first_user_message.c.rn == 1,
            ),
        )
        .where(
            ChatSession.user_id == user_id,
            ChatSession.session_type == "general",
        )
        .order_by(ChatSession.created_at.desc())
    )

    session_list = []
    for session, first_msg in result.all():
        preview = first_msg[:settings.session_preview_max_chars] if first_msg else "New conversation"
        session_list.append(
            {
                "id": str(session.id),
                "preview": preview,
                "created_at": session.created_at.isoformat() if session.created_at else None,
            }
        )
    return session_list


async def delete_session(
    db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID
) -> bool:
    """Delete a session and all its messages. Returns True if deleted."""
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id, ChatSession.user_id == user_id
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return False

    await db.execute(
        delete(ChatMessage).where(ChatMessage.session_id == session_id)
    )
    await db.delete(session)
    await db.flush()
    return True


async def get_daily_usage(db: AsyncSession, user_id: uuid.UUID) -> DailyTokenUsage:
    """Get or create today's token usage record."""
    today = date.today()
    result = await db.execute(
        select(DailyTokenUsage).where(
            DailyTokenUsage.user_id == user_id, DailyTokenUsage.date == today
        )
    )
    usage = result.scalar_one_or_none()
    if not usage:
        usage = DailyTokenUsage(
            user_id=user_id, date=today, input_tokens_used=0, output_tokens_used=0
        )
        db.add(usage)
        await db.flush()
    return usage


async def check_daily_limit(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """Return True if the user still has daily token budget remaining.

    This is a pre-call check only. Precise usage is recorded after the
    LLM call via record_token_usage().
    """
    usage = await get_daily_usage(db, user_id)
    if usage.input_tokens_used >= settings.user_daily_input_token_limit:
        return False
    if usage.output_tokens_used >= settings.user_daily_output_token_limit:
        return False
    return True


async def record_token_usage(
    db: AsyncSession,
    user_id: uuid.UUID,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Atomically record precise input and output tokens to today's usage.

    Called after the LLM API returns, using the exact token counts
    reported by the provider.
    """
    today = date.today()
    stmt = (
        pg_insert(DailyTokenUsage)
        .values(
            user_id=user_id,
            date=today,
            input_tokens_used=input_tokens,
            output_tokens_used=output_tokens,
        )
        .on_conflict_do_update(
            index_elements=[DailyTokenUsage.user_id, DailyTokenUsage.date],
            set_={
                "input_tokens_used": DailyTokenUsage.input_tokens_used + input_tokens,
                "output_tokens_used": DailyTokenUsage.output_tokens_used + output_tokens,
            },
        )
    )
    await db.execute(stmt)

