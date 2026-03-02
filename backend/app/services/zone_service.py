import base64
import shutil
import uuid
from pathlib import Path
from typing import Sequence

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.zone import (
    LearningZone,
    ZoneNotebook,
    ZoneNotebookProgress,
    ZoneSharedFile,
)
import app.services.chat_service as chat_service
from app.services.notebook_service import (
    ensure_zone_notebook_storage_dir,
    notebook_size_limit_bytes,
)
from app.services.notebook_utils import (
    normalise_extension,
    parse_ipynb_bytes,
    safe_delete_file,
    serialise_notebook_payload,
)
from app.services.upload_service import extract_ipynb_text

ZONE_NOTEBOOKS_SUBDIR = "notebooks"
ZONE_SHARED_SUBDIR = "shared"


class ZoneValidationError(ValueError):
    """Raised when zone operations fail validation."""


def _serialise_notebook_payload(payload: dict) -> str:
    return serialise_notebook_payload(
        payload,
        max_size_bytes=notebook_size_limit_bytes(),
        max_size_mb=settings.notebook_max_size_mb,
        error_type=ZoneValidationError,
    )


def _normalise_required_text(value: str, field: str) -> str:
    clean = value.strip()
    if not clean:
        raise ZoneValidationError(f"{field} cannot be empty.")
    return clean


def _normalise_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    clean = value.strip()
    return clean or None


def _derive_title_from_filename(filename: str) -> str:
    stem = Path(filename).stem.strip()
    compact = " ".join(stem.replace("_", " ").split())
    return compact or "Untitled Notebook"


def _normalise_relative_path(raw_path: str) -> str:
    candidate = (raw_path or "").replace("\\", "/").strip()
    if not candidate:
        raise ZoneValidationError("File path cannot be empty.")

    parts: list[str] = []
    for segment in candidate.split("/"):
        segment = segment.strip()
        if not segment or segment == ".":
            continue
        if segment == "..":
            raise ZoneValidationError("Invalid file path.")
        parts.append(segment)

    if not parts:
        raise ZoneValidationError("File path cannot be empty.")
    normalised = "/".join(parts)
    if len(normalised) > 500:
        raise ZoneValidationError("File path is too long.")
    return normalised


def _common_leading_folder(paths: Sequence[str]) -> str | None:
    if not paths:
        return None
    first_parts: list[str] = []
    for path in paths:
        segments = path.split("/")
        if len(segments) <= 1:
            return None
        first_parts.append(segments[0])
    root = first_parts[0]
    if all(part == root for part in first_parts):
        return root
    return None


def _strip_leading_folder(path: str, leading_folder: str | None) -> str:
    if not leading_folder:
        return path
    prefix = f"{leading_folder}/"
    if path.startswith(prefix):
        stripped = path[len(prefix):]
        return stripped or path
    return path


def _zone_storage_dir(zone_id: uuid.UUID) -> Path:
    return ensure_zone_notebook_storage_dir() / str(zone_id)


def _ensure_zone_subdir(zone_id: uuid.UUID, subdir: str) -> Path:
    zone_root = _zone_storage_dir(zone_id)
    target = zone_root / subdir
    target.mkdir(parents=True, exist_ok=True)
    return target


def _zone_notebooks_dir(zone_id: uuid.UUID) -> Path:
    return _ensure_zone_subdir(zone_id, ZONE_NOTEBOOKS_SUBDIR)


def _zone_shared_dir(zone_id: uuid.UUID) -> Path:
    return _ensure_zone_subdir(zone_id, ZONE_SHARED_SUBDIR)


def _resolve_shared_storage_path(zone_id: uuid.UUID, relative_path: str) -> Path:
    shared_root = _zone_shared_dir(zone_id)
    storage_path = shared_root / Path(*relative_path.split("/"))
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    return storage_path


def _safe_delete_zone_storage(zone_id: uuid.UUID) -> None:
    try:
        zone_root = _zone_storage_dir(zone_id)
        if zone_root.exists():
            shutil.rmtree(zone_root)
    except OSError:
        # Best effort cleanup only.
        pass


def _validate_asset_content(filename: str, content: bytes) -> None:
    if not content:
        raise ZoneValidationError(f"File '{filename}' is empty.")
    if len(content) > notebook_size_limit_bytes():
        raise ZoneValidationError(
            f"File '{filename}' exceeds {settings.notebook_max_size_mb} MB size limit."
        )


async def _next_notebook_order(db: AsyncSession, zone_id: uuid.UUID) -> int:
    count_result = await db.execute(
        select(func.count(ZoneNotebook.id)).where(ZoneNotebook.zone_id == zone_id)
    )
    return int(count_result.scalar_one()) + 1


async def _create_notebook_from_content(
    db: AsyncSession,
    zone_id: uuid.UUID,
    filename: str,
    title: str,
    description: str | None,
    content: bytes,
    display_order: int,
) -> ZoneNotebook:
    notebook_json = parse_ipynb_bytes(content, ZoneValidationError)
    extracted_text = extract_ipynb_text(content)

    storage_dir = _zone_notebooks_dir(zone_id)
    stored_filename = f"zone_{uuid.uuid4().hex}.ipynb"
    storage_path = storage_dir / stored_filename
    storage_path.write_bytes(content)

    zone_notebook = ZoneNotebook(
        zone_id=zone_id,
        title=_normalise_required_text(title, "Notebook title"),
        description=_normalise_optional_text(description),
        original_filename=filename,
        stored_filename=stored_filename,
        storage_path=str(storage_path),
        notebook_json=notebook_json,
        extracted_text=extracted_text,
        size_bytes=len(content),
        order=display_order,
    )
    db.add(zone_notebook)
    await db.flush()
    return zone_notebook


async def _upsert_shared_file(
    db: AsyncSession,
    zone_id: uuid.UUID,
    relative_path: str,
    filename: str,
    content: bytes,
    content_type: str | None,
) -> tuple[ZoneSharedFile, bool]:
    existing_result = await db.execute(
        select(ZoneSharedFile).where(
            ZoneSharedFile.zone_id == zone_id,
            ZoneSharedFile.relative_path == relative_path,
        )
    )
    existing = existing_result.scalar_one_or_none()

    storage_path = _resolve_shared_storage_path(zone_id, relative_path)
    storage_path.write_bytes(content)
    if existing is None:
        shared = ZoneSharedFile(
            zone_id=zone_id,
            relative_path=relative_path,
            original_filename=filename,
            stored_filename=f"shared_{uuid.uuid4().hex}{normalise_extension(filename)}",
            storage_path=str(storage_path),
            content_type=(content_type or "").strip() or None,
            size_bytes=len(content),
        )
        db.add(shared)
        await db.flush()
        return shared, True

    existing.original_filename = filename
    existing.storage_path = str(storage_path)
    existing.content_type = (content_type or "").strip() or None
    existing.size_bytes = len(content)
    await db.flush()
    return existing, False


async def create_zone(
    db: AsyncSession,
    title: str,
    description: str | None = None,
) -> LearningZone:
    result = await db.execute(select(func.count(LearningZone.id)))
    zone_count = result.scalar_one()
    zone = LearningZone(
        title=_normalise_required_text(title, "Zone title"),
        description=_normalise_optional_text(description),
        order=zone_count + 1,
    )
    db.add(zone)
    await db.flush()
    return zone


async def list_zones_with_notebook_counts(
    db: AsyncSession,
) -> list[tuple[LearningZone, int]]:
    result = await db.execute(
        select(
            LearningZone,
            func.count(ZoneNotebook.id).label("notebook_count"),
        )
        .outerjoin(ZoneNotebook, ZoneNotebook.zone_id == LearningZone.id)
        .group_by(LearningZone.id)
        .order_by(LearningZone.order.asc(), LearningZone.created_at.asc())
    )
    return [(row[0], int(row[1])) for row in result.all()]


async def get_zone(
    db: AsyncSession,
    zone_id: uuid.UUID,
) -> LearningZone | None:
    result = await db.execute(select(LearningZone).where(LearningZone.id == zone_id))
    return result.scalar_one_or_none()


async def update_zone(
    db: AsyncSession,
    zone_id: uuid.UUID,
    **fields,
) -> LearningZone | None:
    zone = await get_zone(db, zone_id)
    if zone is None:
        return None

    if "title" in fields:
        title = fields["title"]
        if title is not None:
            zone.title = _normalise_required_text(title, "Zone title")

    if "description" in fields:
        zone.description = _normalise_optional_text(fields["description"])

    if "order" in fields and fields["order"] is not None:
        zone.order = int(fields["order"])

    await db.flush()
    return zone


async def delete_zone(
    db: AsyncSession,
    zone_id: uuid.UUID,
) -> bool:
    zone = await get_zone(db, zone_id)
    if zone is None:
        return False

    notebooks = await list_zone_notebooks(db, zone_id)
    await chat_service.delete_sessions_for_modules(
        db,
        session_type="zone",
        module_ids=[item.id for item in notebooks],
    )
    for notebook in notebooks:
        safe_delete_file(notebook.storage_path)

    shared_files = await list_zone_shared_files(db, zone_id)
    for shared in shared_files:
        safe_delete_file(shared.storage_path)

    _safe_delete_zone_storage(zone_id)
    await db.delete(zone)
    await db.flush()
    return True


async def add_notebook(
    db: AsyncSession,
    zone_id: uuid.UUID,
    title: str,
    description: str | None,
    file: UploadFile,
) -> ZoneNotebook:
    zone = await get_zone(db, zone_id)
    if zone is None:
        raise ZoneValidationError("Zone not found.")

    filename = file.filename or "zone-notebook.ipynb"
    if normalise_extension(filename) != ".ipynb":
        raise ZoneValidationError("Only .ipynb files are allowed.")

    content = await file.read()
    await file.close()
    _validate_asset_content(filename, content)

    display_order = await _next_notebook_order(db, zone_id)
    return await _create_notebook_from_content(
        db,
        zone_id=zone_id,
        filename=filename,
        title=title,
        description=description,
        content=content,
        display_order=display_order,
    )


async def import_zone_assets(
    db: AsyncSession,
    zone_id: uuid.UUID,
    files: Sequence[UploadFile],
    relative_paths: Sequence[str] | None = None,
) -> dict:
    zone = await get_zone(db, zone_id)
    if zone is None:
        raise ZoneValidationError("Zone not found.")
    if not files:
        raise ZoneValidationError("Please select at least one file.")

    supplied_paths = list(relative_paths or [])
    prepared: list[tuple[UploadFile, str, str]] = []
    normalised_paths: list[str] = []
    for index, upload in enumerate(files):
        raw_filename = (upload.filename or "").strip() or "upload"
        supplied_path = supplied_paths[index] if index < len(supplied_paths) else ""
        relative_raw = supplied_path or raw_filename
        normalised_path = _normalise_relative_path(relative_raw)
        prepared.append((upload, raw_filename, normalised_path))
        normalised_paths.append(normalised_path)

    leading_folder = _common_leading_folder(normalised_paths)
    next_order = await _next_notebook_order(db, zone_id)
    notebooks_created = 0
    shared_files_created = 0
    shared_files_updated = 0

    for upload, raw_filename, normalised_path in prepared:
        relative_path = _strip_leading_folder(normalised_path, leading_folder)
        leaf_filename = Path(relative_path).name or raw_filename

        content = await upload.read()
        await upload.close()
        _validate_asset_content(leaf_filename, content)

        extension = normalise_extension(leaf_filename)
        if extension == ".ipynb":
            await _create_notebook_from_content(
                db,
                zone_id=zone_id,
                filename=leaf_filename,
                title=_derive_title_from_filename(leaf_filename),
                description=None,
                content=content,
                display_order=next_order,
            )
            notebooks_created += 1
            next_order += 1
            continue

        _, created = await _upsert_shared_file(
            db,
            zone_id=zone_id,
            relative_path=relative_path,
            filename=leaf_filename,
            content=content,
            content_type=upload.content_type,
        )
        if created:
            shared_files_created += 1
        else:
            shared_files_updated += 1

    return {
        "notebooks_created": notebooks_created,
        "shared_files_created": shared_files_created,
        "shared_files_updated": shared_files_updated,
    }


async def replace_notebook_content(
    db: AsyncSession,
    notebook_id: uuid.UUID,
    file: UploadFile,
) -> ZoneNotebook | None:
    result = await db.execute(
        select(ZoneNotebook).where(ZoneNotebook.id == notebook_id)
    )
    notebook = result.scalar_one_or_none()
    if notebook is None:
        return None

    filename = file.filename or notebook.original_filename
    if normalise_extension(filename) != ".ipynb":
        raise ZoneValidationError("Only .ipynb files are allowed.")

    content = await file.read()
    await file.close()
    _validate_asset_content(filename, content)

    notebook_json = parse_ipynb_bytes(content, ZoneValidationError)
    extracted_text = extract_ipynb_text(content)

    old_path = notebook.storage_path
    storage_dir = _zone_notebooks_dir(notebook.zone_id)
    stored_filename = f"zone_{uuid.uuid4().hex}.ipynb"
    storage_path = storage_dir / stored_filename
    storage_path.write_bytes(content)

    notebook.original_filename = filename
    notebook.stored_filename = stored_filename
    notebook.storage_path = str(storage_path)
    notebook.notebook_json = notebook_json
    notebook.extracted_text = extracted_text
    notebook.size_bytes = len(content)
    await db.flush()

    safe_delete_file(old_path)
    return notebook


async def update_zone_notebook_metadata(
    db: AsyncSession,
    notebook_id: uuid.UUID,
    *,
    title: str | None = None,
    description: str | None = None,
    description_provided: bool = False,
) -> ZoneNotebook | None:
    result = await db.execute(
        select(ZoneNotebook).where(ZoneNotebook.id == notebook_id)
    )
    notebook = result.scalar_one_or_none()
    if notebook is None:
        return None

    if title is not None:
        notebook.title = _normalise_required_text(title, "Notebook title")
    if description_provided:
        notebook.description = _normalise_optional_text(description)
    await db.flush()
    return notebook


async def list_zone_notebooks(
    db: AsyncSession,
    zone_id: uuid.UUID,
) -> list[ZoneNotebook]:
    result = await db.execute(
        select(ZoneNotebook)
        .where(ZoneNotebook.zone_id == zone_id)
        .order_by(ZoneNotebook.order.asc(), ZoneNotebook.created_at.asc())
    )
    return list(result.scalars().all())


async def list_zone_notebooks_with_progress(
    db: AsyncSession,
    zone_id: uuid.UUID,
    user_id: uuid.UUID,
) -> list[tuple[ZoneNotebook, bool]]:
    notebooks = await list_zone_notebooks(db, zone_id)
    if not notebooks:
        return []

    notebook_ids = [item.id for item in notebooks]
    progress_result = await db.execute(
        select(ZoneNotebookProgress.zone_notebook_id).where(
            ZoneNotebookProgress.user_id == user_id,
            ZoneNotebookProgress.zone_notebook_id.in_(notebook_ids),
        )
    )
    progress_ids = {row[0] for row in progress_result.all()}
    return [(item, item.id in progress_ids) for item in notebooks]


async def get_zone_notebook(
    db: AsyncSession,
    notebook_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> tuple[ZoneNotebook, bool, str] | None:
    result = await db.execute(
        select(ZoneNotebook).where(ZoneNotebook.id == notebook_id)
    )
    notebook = result.scalar_one_or_none()
    if notebook is None:
        return None

    if user_id is None:
        return notebook, False, notebook.notebook_json

    progress_result = await db.execute(
        select(ZoneNotebookProgress).where(
            ZoneNotebookProgress.user_id == user_id,
            ZoneNotebookProgress.zone_notebook_id == notebook_id,
        )
    )
    progress = progress_result.scalar_one_or_none()
    if progress is None:
        return notebook, False, notebook.notebook_json

    return notebook, True, progress.notebook_state


async def get_zone_notebook_for_context(
    db: AsyncSession,
    notebook_id: uuid.UUID,
) -> ZoneNotebook | None:
    result = await db.execute(
        select(ZoneNotebook).where(ZoneNotebook.id == notebook_id)
    )
    return result.scalar_one_or_none()


async def save_zone_progress(
    db: AsyncSession,
    user_id: uuid.UUID,
    zone_notebook_id: uuid.UUID,
    notebook_state: dict,
) -> ZoneNotebookProgress:
    zone_notebook = await get_zone_notebook_for_context(db, zone_notebook_id)
    if zone_notebook is None:
        raise ZoneValidationError("Zone notebook not found.")

    serialised = _serialise_notebook_payload(notebook_state)

    result = await db.execute(
        select(ZoneNotebookProgress).where(
            ZoneNotebookProgress.user_id == user_id,
            ZoneNotebookProgress.zone_notebook_id == zone_notebook_id,
        )
    )
    progress = result.scalar_one_or_none()
    if progress is None:
        progress = ZoneNotebookProgress(
            user_id=user_id,
            zone_notebook_id=zone_notebook_id,
            notebook_state=serialised,
        )
        db.add(progress)
    else:
        progress.notebook_state = serialised
    await db.flush()
    return progress


async def reset_zone_progress(
    db: AsyncSession,
    user_id: uuid.UUID,
    zone_notebook_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(ZoneNotebookProgress).where(
            ZoneNotebookProgress.user_id == user_id,
            ZoneNotebookProgress.zone_notebook_id == zone_notebook_id,
        )
    )
    progress = result.scalar_one_or_none()
    if progress is None:
        return False
    await db.delete(progress)
    await db.flush()
    return True


async def delete_zone_notebook(
    db: AsyncSession,
    notebook_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(ZoneNotebook).where(ZoneNotebook.id == notebook_id)
    )
    notebook = result.scalar_one_or_none()
    if notebook is None:
        return False

    await chat_service.delete_sessions_for_scope(
        db,
        session_type="zone",
        module_id=notebook_id,
    )
    safe_delete_file(notebook.storage_path)
    await db.delete(notebook)
    await db.flush()
    return True


async def reorder_zone_notebooks(
    db: AsyncSession,
    zone_id: uuid.UUID,
    notebook_ids: list[uuid.UUID],
) -> None:
    zone = await get_zone(db, zone_id)
    if zone is None:
        raise ZoneValidationError("Zone not found.")

    notebooks = await list_zone_notebooks(db, zone_id)
    if len(notebooks) != len(notebook_ids):
        raise ZoneValidationError("Notebook order payload is incomplete.")

    current_ids = {item.id for item in notebooks}
    requested_ids = set(notebook_ids)
    if current_ids != requested_ids:
        raise ZoneValidationError("Notebook order payload is invalid.")

    notebook_map = {item.id: item for item in notebooks}
    for index, notebook_id in enumerate(notebook_ids, start=1):
        notebook_map[notebook_id].order = index
    await db.flush()


async def list_zone_shared_files(
    db: AsyncSession,
    zone_id: uuid.UUID,
) -> list[ZoneSharedFile]:
    result = await db.execute(
        select(ZoneSharedFile)
        .where(ZoneSharedFile.zone_id == zone_id)
        .order_by(ZoneSharedFile.relative_path.asc(), ZoneSharedFile.created_at.asc())
    )
    return list(result.scalars().all())


async def delete_zone_shared_file(
    db: AsyncSession,
    shared_file_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(ZoneSharedFile).where(ZoneSharedFile.id == shared_file_id)
    )
    shared_file = result.scalar_one_or_none()
    if shared_file is None:
        return False

    safe_delete_file(shared_file.storage_path)
    await db.delete(shared_file)
    await db.flush()
    return True


async def get_zone_runtime_files(
    db: AsyncSession,
    zone_id: uuid.UUID,
    notebook_id: uuid.UUID,
) -> list[dict] | None:
    notebook = await get_zone_notebook_for_context(db, notebook_id)
    if notebook is None or notebook.zone_id != zone_id:
        return None

    shared_files = await list_zone_shared_files(db, zone_id)
    runtime_files: list[dict] = []
    for item in shared_files:
        path = Path(item.storage_path)
        if not path.exists():
            continue
        runtime_files.append(
            {
                "relative_path": item.relative_path,
                "content_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
                "content_type": item.content_type,
            }
        )
    return runtime_files
