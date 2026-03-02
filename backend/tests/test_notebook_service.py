import pytest
import pytest_asyncio
import uuid
import app.models  # noqa: F401
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models.chat import ChatMessage, ChatSession
from app.models.notebook import UserNotebook
from app.models.user import Base
from app.services.notebook_service import (
    NotebookValidationError,
    _derive_display_filename,
    _normalise_storage_segment,
    _normalise_title,
    delete_notebook,
    ensure_user_notebook_storage_dir,
    ensure_zone_notebook_storage_dir,
)


def test_normalise_title_compacts_whitespace() -> None:
    assert _normalise_title("  Coursework   C  ") == "Coursework C"


def test_normalise_title_rejects_empty_value() -> None:
    with pytest.raises(NotebookValidationError):
        _normalise_title("   ")


def test_derive_display_filename_keeps_ipynb_extension() -> None:
    filename = _derive_display_filename("Coursework C", "old-name.ipynb")
    assert filename == "Coursework C.ipynb"


def test_derive_display_filename_uses_ipynb_when_extension_is_not_ipynb() -> None:
    filename = _derive_display_filename("Coursework C", "old-name.txt")
    assert filename == "Coursework C.ipynb"


def test_derive_display_filename_replaces_path_separators() -> None:
    filename = _derive_display_filename("Course/work\\C", "old-name.ipynb")
    assert filename == "Course-work-C.ipynb"


def test_normalise_storage_segment_replaces_unsafe_chars() -> None:
    folder_name = _normalise_storage_segment("../User Name+Math@Uni.ac.uk", fallback="fallback")
    assert folder_name == "user-name+math@uni.ac.uk"


def test_ensure_user_notebook_storage_dir_uses_email_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "notebook_storage_dir", str(tmp_path))

    user_dir = ensure_user_notebook_storage_dir("Alice.Example+Math@Uni.ac.uk")

    assert user_dir == tmp_path / "alice.example+math@uni.ac.uk"
    assert user_dir.exists()
    assert user_dir.is_dir()


def test_ensure_zone_notebook_storage_dir_uses_dedicated_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "notebook_storage_dir", str(tmp_path))

    zone_dir = ensure_zone_notebook_storage_dir()

    assert zone_dir == tmp_path / "learning_zone_notebooks"
    assert zone_dir.exists()
    assert zone_dir.is_dir()


@pytest_asyncio.fixture
async def notebook_db(tmp_path):
    db_path = tmp_path / "notebook_cleanup.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        yield session_factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_notebook_removes_scoped_chat_sessions(notebook_db, tmp_path) -> None:
    notebook_file = tmp_path / "n.ipynb"
    notebook_file.write_text("{}", encoding="utf-8")

    async with notebook_db() as db:
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

        notebook = UserNotebook(
            user_id=user.id,
            title="Notebook",
            original_filename="Notebook.ipynb",
            stored_filename=f"{uuid.uuid4().hex}.ipynb",
            storage_path=str(notebook_file),
            notebook_json="{}",
            extracted_text="",
            size_bytes=2,
        )
        db.add(notebook)
        await db.flush()

        session = ChatSession(
            user_id=user.id,
            session_type="notebook",
            module_id=notebook.id,
        )
        db.add(session)
        await db.flush()
        db.add(ChatMessage(session_id=session.id, role="assistant", content="hello"))
        await db.commit()

        deleted = await delete_notebook(db, user.id, notebook.id)
        await db.commit()

    assert deleted is True

    async with notebook_db() as db:
        sessions = (
            await db.execute(select(ChatSession).where(ChatSession.module_id == notebook.id))
        ).scalars().all()
        assert sessions == []
