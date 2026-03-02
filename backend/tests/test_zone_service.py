import pytest
import pytest_asyncio
import uuid
import app.models  # noqa: F401
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.chat import ChatMessage, ChatSession
from app.models.user import Base
from app.models.zone import LearningZone, ZoneNotebook
from app.services.zone_service import (
    ZoneValidationError,
    _common_leading_folder,
    _derive_title_from_filename,
    _normalise_relative_path,
    _strip_leading_folder,
    delete_zone,
    delete_zone_notebook,
)


def test_normalise_relative_path_compacts_and_normalises() -> None:
    relative_path = _normalise_relative_path("  data\\week1//scores.csv ")
    assert relative_path == "data/week1/scores.csv"


def test_normalise_relative_path_rejects_parent_segments() -> None:
    with pytest.raises(ZoneValidationError):
        _normalise_relative_path("../secrets.txt")


def test_derive_title_from_filename_uses_stem() -> None:
    assert _derive_title_from_filename("week_03_intro.ipynb") == "week 03 intro"


def test_common_leading_folder_detects_shared_root() -> None:
    root = _common_leading_folder(["c6/a.py", "c6/b.py", "c6/data/x.csv"])
    assert root == "c6"


def test_strip_leading_folder_removes_prefix() -> None:
    assert _strip_leading_folder("c6/a.py", "c6") == "a.py"


@pytest_asyncio.fixture
async def zone_db(tmp_path):
    db_path = tmp_path / "zone_cleanup.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        yield session_factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_zone_notebook_removes_zone_chat_sessions(zone_db, tmp_path) -> None:
    notebook_file = tmp_path / "zone.ipynb"
    notebook_file.write_text("{}", encoding="utf-8")

    async with zone_db() as db:
        zone = LearningZone(title="Zone", description=None, order=1)
        db.add(zone)
        await db.flush()
        notebook = ZoneNotebook(
            zone_id=zone.id,
            title="Notebook",
            description=None,
            original_filename="zone.ipynb",
            stored_filename=f"{uuid.uuid4().hex}.ipynb",
            storage_path=str(notebook_file),
            notebook_json="{}",
            extracted_text="",
            size_bytes=2,
            order=1,
        )
        db.add(notebook)
        await db.flush()

        from app.models.user import User

        user = User(
            email=f"{uuid.uuid4().hex}@example.com",
            username=f"u_{uuid.uuid4().hex[:6]}",
            password_hash="x",
            programming_level=3,
            maths_level=3,
        )
        db.add(user)
        await db.flush()

        session = ChatSession(
            user_id=user.id,
            session_type="zone",
            module_id=notebook.id,
        )
        db.add(session)
        await db.flush()
        db.add(ChatMessage(session_id=session.id, role="assistant", content="hi"))
        await db.commit()

        deleted = await delete_zone_notebook(db, notebook.id)
        await db.commit()

    assert deleted is True
    async with zone_db() as db:
        sessions = (
            await db.execute(select(ChatSession).where(ChatSession.module_id == notebook.id))
        ).scalars().all()
        assert sessions == []


@pytest.mark.asyncio
async def test_delete_zone_removes_all_zone_notebook_chat_sessions(zone_db, tmp_path) -> None:
    notebook_file = tmp_path / "zone2.ipynb"
    notebook_file.write_text("{}", encoding="utf-8")

    async with zone_db() as db:
        zone = LearningZone(title="Zone2", description=None, order=2)
        db.add(zone)
        await db.flush()
        notebooks: list[ZoneNotebook] = []
        for order in (1, 2):
            notebook = ZoneNotebook(
                zone_id=zone.id,
                title=f"Notebook {order}",
                description=None,
                original_filename=f"zone-{order}.ipynb",
                stored_filename=f"{uuid.uuid4().hex}.ipynb",
                storage_path=str(notebook_file),
                notebook_json="{}",
                extracted_text="",
                size_bytes=2,
                order=order,
            )
            db.add(notebook)
            notebooks.append(notebook)
        await db.flush()

        from app.models.user import User

        user = User(
            email=f"{uuid.uuid4().hex}@example.com",
            username=f"u_{uuid.uuid4().hex[:6]}",
            password_hash="x",
            programming_level=3,
            maths_level=3,
        )
        db.add(user)
        await db.flush()

        for notebook in notebooks:
            session = ChatSession(
                user_id=user.id,
                session_type="zone",
                module_id=notebook.id,
            )
            db.add(session)
            await db.flush()
            db.add(ChatMessage(session_id=session.id, role="assistant", content="hi"))
        await db.commit()

        deleted = await delete_zone(db, zone.id)
        await db.commit()

    assert deleted is True
    notebook_ids = [item.id for item in notebooks]
    async with zone_db() as db:
        sessions = (
            await db.execute(select(ChatSession).where(ChatSession.module_id.in_(notebook_ids)))
        ).scalars().all()
        assert sessions == []
