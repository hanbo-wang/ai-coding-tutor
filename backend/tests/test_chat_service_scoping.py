"""Chat session scope-matching tests for session reuse."""

from __future__ import annotations

import uuid

import app.models  # noqa: F401
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.chat import ChatMessage, ChatSession
from app.models.user import Base, User
from app.services import chat_service


@pytest_asyncio.fixture
async def chat_service_db(tmp_path):
    """Create an isolated SQLite database for chat-service scope tests."""
    db_path = tmp_path / "chat_service_scoping.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        yield session_factory
    finally:
        await engine.dispose()


async def _create_user(session_factory: async_sessionmaker[AsyncSession]) -> User:
    async with session_factory() as db:
        user = User(
            email=f"{uuid.uuid4().hex}@example.com",
            username=f"user_{uuid.uuid4().hex[:8]}",
            password_hash="x",
            programming_level=3,
            maths_level=3,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def _create_session(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id,
    session_type: str,
    module_id: uuid.UUID | None = None,
) -> ChatSession:
    async with session_factory() as db:
        session = ChatSession(user_id=user_id, session_type=session_type, module_id=module_id)
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session


@pytest.mark.asyncio
async def test_get_or_create_session_ignores_general_session_id_for_notebook_scope(
    chat_service_db,
) -> None:
    """A general session ID should not be reused for a notebook-scoped request."""
    user = await _create_user(chat_service_db)
    general_session = await _create_session(
        chat_service_db,
        user_id=user.id,
        session_type="general",
    )
    notebook_id = uuid.uuid4()

    async with chat_service_db() as db:
        resolved = await chat_service.get_or_create_session(
            db,
            user.id,
            session_id=general_session.id,
            session_type="notebook",
            module_id=notebook_id,
        )
        await chat_service.save_message(db, resolved.id, "user", "hello")
        await db.commit()

        messages = (
            await db.execute(select(ChatMessage).order_by(ChatMessage.created_at.asc()))
        ).scalars().all()

    assert resolved.id != general_session.id
    assert resolved.session_type == "notebook"
    assert resolved.module_id == notebook_id
    assert len(messages) == 1
    assert messages[0].session_id == resolved.id


@pytest.mark.asyncio
async def test_get_or_create_session_resolves_current_scope_after_mismatched_scoped_id(
    chat_service_db,
) -> None:
    """A mismatched scoped session ID should fall back to the requested scoped session."""
    user = await _create_user(chat_service_db)
    notebook_a = uuid.uuid4()
    notebook_b = uuid.uuid4()
    session_a = await _create_session(
        chat_service_db,
        user_id=user.id,
        session_type="notebook",
        module_id=notebook_a,
    )
    session_b = await _create_session(
        chat_service_db,
        user_id=user.id,
        session_type="notebook",
        module_id=notebook_b,
    )

    async with chat_service_db() as db:
        resolved = await chat_service.get_or_create_session(
            db,
            user.id,
            session_id=session_a.id,
            session_type="notebook",
            module_id=notebook_b,
        )

    assert resolved.id == session_b.id
    assert resolved.module_id == notebook_b


@pytest.mark.asyncio
async def test_get_or_create_session_ignores_scoped_session_id_for_general_request(
    chat_service_db,
) -> None:
    """A notebook-scoped session ID should not be reused for a general chat request."""
    user = await _create_user(chat_service_db)
    scoped = await _create_session(
        chat_service_db,
        user_id=user.id,
        session_type="notebook",
        module_id=uuid.uuid4(),
    )

    async with chat_service_db() as db:
        resolved = await chat_service.get_or_create_session(
            db,
            user.id,
            session_id=scoped.id,
            session_type="general",
            module_id=None,
        )

    assert resolved.id != scoped.id
    assert resolved.session_type == "general"
    assert resolved.module_id is None


@pytest.mark.asyncio
async def test_get_or_create_session_reuses_matching_session_id(chat_service_db) -> None:
    """A matching scoped session ID should still be reused."""
    user = await _create_user(chat_service_db)
    zone_notebook_id = uuid.uuid4()
    scoped = await _create_session(
        chat_service_db,
        user_id=user.id,
        session_type="zone",
        module_id=zone_notebook_id,
    )

    async with chat_service_db() as db:
        resolved = await chat_service.get_or_create_session(
            db,
            user.id,
            session_id=scoped.id,
            session_type="zone",
            module_id=zone_notebook_id,
        )

    assert resolved.id == scoped.id
    assert resolved.session_type == "zone"
    assert resolved.module_id == zone_notebook_id
