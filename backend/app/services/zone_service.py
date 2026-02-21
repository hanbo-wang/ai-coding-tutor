import uuid

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.zone import LearningZone, ZoneNotebook, ZoneNotebookProgress
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


class ZoneValidationError(ValueError):
    """Raised when zone operations fail validation."""


def _serialise_notebook_payload(payload: dict) -> str:
    return serialise_notebook_payload(
        payload,
        max_size_bytes=notebook_size_limit_bytes(),
        max_size_mb=settings.notebook_max_size_mb,
        error_type=ZoneValidationError,
    )


async def create_zone(
    db: AsyncSession,
    title: str,
    description: str,
) -> LearningZone:
    result = await db.execute(select(func.count(LearningZone.id)))
    zone_count = result.scalar_one()
    zone = LearningZone(
        title=title.strip(),
        description=description.strip(),
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
    for key, value in fields.items():
        if value is not None:
            setattr(zone, key, value)
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
    for notebook in notebooks:
        safe_delete_file(notebook.storage_path)

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
    if not content:
        raise ZoneValidationError("Uploaded notebook is empty.")
    if len(content) > notebook_size_limit_bytes():
        raise ZoneValidationError(
            f"Notebook exceeds {settings.notebook_max_size_mb} MB size limit."
        )

    notebook_json = parse_ipynb_bytes(content, ZoneValidationError)
    extracted_text = extract_ipynb_text(content)

    count_result = await db.execute(
        select(func.count(ZoneNotebook.id)).where(ZoneNotebook.zone_id == zone_id)
    )
    notebook_count = count_result.scalar_one()
    display_order = notebook_count + 1

    storage_dir = ensure_zone_notebook_storage_dir()
    stored_filename = f"zone_{uuid.uuid4().hex}.ipynb"
    storage_path = storage_dir / stored_filename
    storage_path.write_bytes(content)

    zone_notebook = ZoneNotebook(
        zone_id=zone_id,
        title=title.strip(),
        description=description.strip() if description else None,
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
    if not content:
        raise ZoneValidationError("Uploaded notebook is empty.")
    if len(content) > notebook_size_limit_bytes():
        raise ZoneValidationError(
            f"Notebook exceeds {settings.notebook_max_size_mb} MB size limit."
        )

    notebook_json = parse_ipynb_bytes(content, ZoneValidationError)
    extracted_text = extract_ipynb_text(content)

    old_path = notebook.storage_path
    storage_dir = ensure_zone_notebook_storage_dir()
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
