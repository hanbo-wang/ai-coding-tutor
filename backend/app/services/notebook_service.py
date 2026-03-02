"""Personal notebook lifecycle management."""

import json
import re
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.notebook import UserNotebook
import app.services.chat_service as chat_service
from app.services.notebook_utils import (
    normalise_extension,
    parse_ipynb_bytes,
    safe_delete_file,
    serialise_notebook_payload,
)
from app.services.upload_service import extract_ipynb_text


class NotebookValidationError(ValueError):
    """Raised when notebook validation fails."""


ZONE_NOTEBOOKS_DIRNAME = "learning_zone_notebooks"
_PATH_SAFE_CHARS_RE = re.compile(r"[^a-z0-9@._+-]")


def ensure_notebook_storage_dir() -> Path:
    storage_dir = Path(settings.notebook_storage_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir


def _normalise_storage_segment(value: str, *, fallback: str) -> str:
    cleaned = _PATH_SAFE_CHARS_RE.sub("-", value.strip().lower())
    cleaned = cleaned.strip(".-_ ")
    return cleaned or fallback


def ensure_user_notebook_storage_dir(user_email: str) -> Path:
    root_dir = ensure_notebook_storage_dir()
    user_segment = _normalise_storage_segment(user_email, fallback="unknown-user")
    user_dir = root_dir / user_segment
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def ensure_zone_notebook_storage_dir() -> Path:
    root_dir = ensure_notebook_storage_dir()
    zone_dir = root_dir / ZONE_NOTEBOOKS_DIRNAME
    zone_dir.mkdir(parents=True, exist_ok=True)
    return zone_dir


def notebook_size_limit_bytes() -> int:
    return settings.notebook_max_size_mb * 1024 * 1024


def _derive_title(filename: str) -> str:
    stem = Path(filename).stem.strip()
    return stem or "untitled-notebook"


def _normalise_title(title: str) -> str:
    compact = " ".join(title.strip().split())
    if not compact:
        raise NotebookValidationError("Notebook title cannot be empty.")
    if len(compact) > settings.notebook_max_title_length:
        raise NotebookValidationError("Notebook title is too long.")
    return compact


def _derive_display_filename(title: str, original_filename: str) -> str:
    suffix = Path(original_filename).suffix
    extension = suffix if suffix.lower() == ".ipynb" else ".ipynb"
    safe_title = title.replace("/", "-").replace("\\", "-")
    return f"{safe_title}{extension}"


def _serialise_payload(payload: dict) -> str:
    return serialise_notebook_payload(
        payload,
        max_size_bytes=notebook_size_limit_bytes(),
        max_size_mb=settings.notebook_max_size_mb,
        error_type=NotebookValidationError,
    )


async def save_notebook(
    db: AsyncSession,
    user_id: uuid.UUID,
    user_email: str,
    file: UploadFile,
) -> UserNotebook:
    filename = file.filename or "notebook.ipynb"
    if normalise_extension(filename) != ".ipynb":
        raise NotebookValidationError("Only .ipynb files are allowed.")

    count_result = await db.execute(
        select(func.count(UserNotebook.id)).where(UserNotebook.user_id == user_id)
    )
    notebook_count = count_result.scalar_one()
    if notebook_count >= settings.notebook_max_per_user:
        raise NotebookValidationError(
            f"Notebook limit reached ({settings.notebook_max_per_user} per user)."
        )

    content = await file.read()
    await file.close()
    if not content:
        raise NotebookValidationError("Uploaded notebook is empty.")
    if len(content) > notebook_size_limit_bytes():
        raise NotebookValidationError(
            f"Notebook exceeds {settings.notebook_max_size_mb} MB size limit."
        )

    notebook_json = parse_ipynb_bytes(content, NotebookValidationError)
    extracted_text = extract_ipynb_text(content)

    storage_dir = ensure_user_notebook_storage_dir(user_email)
    stored_filename = f"{uuid.uuid4().hex}.ipynb"
    storage_path = storage_dir / stored_filename
    storage_path.write_bytes(content)

    notebook = UserNotebook(
        user_id=user_id,
        title=_derive_title(filename),
        original_filename=filename,
        stored_filename=stored_filename,
        storage_path=str(storage_path),
        notebook_json=notebook_json,
        extracted_text=extracted_text,
        size_bytes=len(content),
    )

    db.add(notebook)
    await db.flush()
    return notebook


async def list_notebooks(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[UserNotebook]:
    result = await db.execute(
        select(UserNotebook)
        .where(UserNotebook.user_id == user_id)
        .order_by(UserNotebook.created_at.desc())
    )
    return list(result.scalars().all())


async def get_notebook(
    db: AsyncSession,
    user_id: uuid.UUID,
    notebook_id: uuid.UUID,
) -> UserNotebook | None:
    result = await db.execute(
        select(UserNotebook).where(
            UserNotebook.id == notebook_id, UserNotebook.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def update_notebook_state(
    db: AsyncSession,
    user_id: uuid.UUID,
    notebook_id: uuid.UUID,
    notebook_json: dict,
) -> UserNotebook | None:
    notebook = await get_notebook(db, user_id, notebook_id)
    if notebook is None:
        return None

    serialised = _serialise_payload(notebook_json)
    notebook.notebook_json = serialised
    await db.flush()
    return notebook


async def rename_notebook(
    db: AsyncSession,
    user_id: uuid.UUID,
    notebook_id: uuid.UUID,
    title: str,
) -> UserNotebook | None:
    notebook = await get_notebook(db, user_id, notebook_id)
    if notebook is None:
        return None

    normalised_title = _normalise_title(title)
    notebook.title = normalised_title
    notebook.original_filename = _derive_display_filename(
        normalised_title, notebook.original_filename
    )
    await db.flush()
    return notebook


async def refresh_extracted_text(
    db: AsyncSession,
    user_id: uuid.UUID,
    notebook_id: uuid.UUID,
) -> str | None:
    notebook = await get_notebook(db, user_id, notebook_id)
    if notebook is None:
        return None

    try:
        payload = json.loads(notebook.notebook_json)
    except json.JSONDecodeError:
        raise NotebookValidationError("Stored notebook JSON is invalid.")
    if not isinstance(payload, dict):
        raise NotebookValidationError("Stored notebook JSON is invalid.")

    serialised = _serialise_payload(payload)
    extracted_text = extract_ipynb_text(serialised.encode("utf-8"))
    notebook.extracted_text = extracted_text
    await db.flush()
    return extracted_text


async def delete_notebook(
    db: AsyncSession,
    user_id: uuid.UUID,
    notebook_id: uuid.UUID,
) -> bool:
    notebook = await get_notebook(db, user_id, notebook_id)
    if notebook is None:
        return False

    await chat_service.delete_sessions_for_user_scope(
        db,
        user_id,
        session_type="notebook",
        module_id=notebook_id,
    )
    safe_delete_file(notebook.storage_path)
    await db.delete(notebook)
    await db.flush()
    return True
