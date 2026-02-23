"""Rolling chat summary cache service tests."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import app.models  # noqa: F401
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.chat import ChatMessage, ChatSession
from app.models.user import Base, User
from app.services.chat_summary_cache import ChatSummaryCacheService


class _DummyLLM:
    """Minimal LLM stub for summary-cache tests."""

    async def close(self) -> None:
        return None


@pytest_asyncio.fixture
async def summary_cache_db(tmp_path):
    """Create an isolated SQLite database for summary-cache service tests."""
    db_path = tmp_path / "summary_cache.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        yield session_factory
    finally:
        await engine.dispose()


async def _create_session_with_messages(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message_count: int,
    existing_summary: str | None = None,
    existing_summary_count: int | None = None,
) -> uuid.UUID:
    async with session_factory() as db:
        user = User(
            email=f"{uuid.uuid4().hex}@example.com",
            username=f"user_{uuid.uuid4().hex[:8]}",
            password_hash="x",
            programming_level=3,
            maths_level=3,
        )
        db.add(user)
        await db.flush()
        session = ChatSession(
            user_id=user.id,
            context_summary_text=existing_summary,
            context_summary_message_count=existing_summary_count,
            context_summary_updated_at=(
                datetime.now(timezone.utc).replace(tzinfo=None) if existing_summary else None
            ),
        )
        db.add(session)
        await db.flush()

        for i in range(message_count):
            db.add(
                ChatMessage(
                    session_id=session.id,
                    role="user" if i % 2 == 0 else "assistant",
                    content=f"Message {i}",
                )
            )
        await db.commit()
        return session.id


async def _get_session(
    session_factory: async_sessionmaker[AsyncSession], session_id: uuid.UUID
) -> ChatSession:
    async with session_factory() as db:
        result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
        session = result.scalar_one()
        return session


@pytest.mark.asyncio
async def test_refresh_once_writes_summary_cache(summary_cache_db, monkeypatch: pytest.MonkeyPatch) -> None:
    """Refreshing a long session should persist a hidden summary and prefix count."""
    session_id = await _create_session_with_messages(summary_cache_db, message_count=10)

    service = ChatSummaryCacheService()
    service.raw_tail_messages = 2
    service.min_summary_prefix_messages = 2

    monkeypatch.setattr("app.services.chat_summary_cache.AsyncSessionLocal", summary_cache_db)
    monkeypatch.setattr("app.services.chat_summary_cache.get_llm_provider", lambda _settings: _DummyLLM())

    async def _fake_compress(messages, llm):
        return f"summary({len(messages)})"

    monkeypatch.setattr("app.services.chat_summary_cache._compress_messages", _fake_compress)

    await service._refresh_once(session_id)

    session = await _get_session(summary_cache_db, session_id)
    assert session.context_summary_text == "summary(8)"
    assert session.context_summary_message_count == 8
    assert session.context_summary_updated_at is not None


@pytest.mark.asyncio
async def test_refresh_once_clears_summary_cache_when_history_is_short(
    summary_cache_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Short sessions should clear the hidden summary cache fields."""
    session_id = await _create_session_with_messages(
        summary_cache_db,
        message_count=3,
        existing_summary="old summary",
        existing_summary_count=2,
    )

    service = ChatSummaryCacheService()
    monkeypatch.setattr("app.services.chat_summary_cache.AsyncSessionLocal", summary_cache_db)

    await service._refresh_once(session_id)

    session = await _get_session(summary_cache_db, session_id)
    assert session.context_summary_text is None
    assert session.context_summary_message_count is None
    assert session.context_summary_updated_at is None


@pytest.mark.asyncio
async def test_schedule_refresh_requeues_once_when_marked_dirty() -> None:
    """A second schedule while running should reuse the same task and trigger another pass."""
    service = ChatSummaryCacheService()
    session_id = uuid.uuid4()
    started = asyncio.Event()
    release = asyncio.Event()
    call_count = 0

    async def _fake_refresh_once(incoming_session_id):
        nonlocal call_count
        assert incoming_session_id == session_id
        call_count += 1
        if call_count == 1:
            started.set()
            await release.wait()

    service._refresh_once = _fake_refresh_once  # type: ignore[method-assign]

    service.schedule_refresh(session_id)
    first_task = service._tasks[str(session_id)]
    await started.wait()
    service.schedule_refresh(session_id)
    second_task = service._tasks[str(session_id)]
    assert first_task is second_task

    release.set()
    await second_task

    assert call_count == 2
    assert str(session_id) not in service._tasks
    assert str(session_id) not in service._dirty
