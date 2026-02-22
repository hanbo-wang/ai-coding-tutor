"""Student-facing Learning Hub zone endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.routers._notebook_json import parse_notebook_json_or_500
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.zone import (
    ZoneDetailOut,
    ZoneNotebookDetail,
    ZoneNotebookOut,
    ZoneOut,
    ZoneProgressSave,
    ZoneRuntimeFileOut,
)
from app.services.zone_service import (
    ZoneValidationError,
    get_zone,
    get_zone_notebook,
    get_zone_runtime_files,
    list_zone_notebooks_with_progress,
    list_zones_with_notebook_counts,
    reset_zone_progress,
    save_zone_progress,
)

router = APIRouter(prefix="/api/zones", tags=["zones"])


@router.get("", response_model=list[ZoneOut])
async def list_public_zones(
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    zones_with_counts = await list_zones_with_notebook_counts(db)
    return [
        ZoneOut(
            id=zone.id,
            title=zone.title,
            description=zone.description,
            order=zone.order,
            created_at=zone.created_at,
            notebook_count=count,
        )
        for zone, count in zones_with_counts
    ]


@router.get("/{zone_id}", response_model=ZoneDetailOut)
async def get_zone_detail(
    zone_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    zone = await get_zone(db, zone_id)
    if zone is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Zone not found")

    notebooks = await list_zone_notebooks_with_progress(db, zone_id, current_user.id)
    return ZoneDetailOut(
        id=zone.id,
        title=zone.title,
        description=zone.description,
        order=zone.order,
        created_at=zone.created_at,
        notebook_count=len(notebooks),
        notebooks=[
            ZoneNotebookOut(
                id=item.id,
                zone_id=item.zone_id,
                title=item.title,
                description=item.description,
                original_filename=item.original_filename,
                size_bytes=item.size_bytes,
                order=item.order,
                created_at=item.created_at,
                has_progress=has_progress,
            )
            for item, has_progress in notebooks
        ],
    )


@router.get("/{zone_id}/notebooks/{notebook_id}", response_model=ZoneNotebookDetail)
async def get_zone_notebook_detail(
    zone_id: uuid.UUID,
    notebook_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await get_zone_notebook(db, notebook_id, current_user.id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found")
    notebook, has_progress, notebook_json = result
    if notebook.zone_id != zone_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found")

    return ZoneNotebookDetail(
        id=notebook.id,
        zone_id=notebook.zone_id,
        title=notebook.title,
        description=notebook.description,
        original_filename=notebook.original_filename,
        size_bytes=notebook.size_bytes,
        order=notebook.order,
        created_at=notebook.created_at,
        has_progress=has_progress,
        notebook_json=parse_notebook_json_or_500(notebook_json),
    )


@router.get(
    "/{zone_id}/notebooks/{notebook_id}/runtime-files",
    response_model=list[ZoneRuntimeFileOut],
)
async def get_zone_notebook_runtime_files(
    zone_id: uuid.UUID,
    notebook_id: uuid.UUID,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    runtime_files = await get_zone_runtime_files(db, zone_id, notebook_id)
    if runtime_files is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found")
    return [ZoneRuntimeFileOut(**item) for item in runtime_files]


@router.put("/{zone_id}/notebooks/{notebook_id}/progress")
async def save_user_zone_progress(
    zone_id: uuid.UUID,
    notebook_id: uuid.UUID,
    payload: ZoneProgressSave,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await get_zone_notebook(db, notebook_id)
    if result is None or result[0].zone_id != zone_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found")

    try:
        await save_zone_progress(db, current_user.id, notebook_id, payload.notebook_state)
    except ZoneValidationError as exc:
        detail = str(exc)
        code = status.HTTP_404_NOT_FOUND if "not found" in detail.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=detail)

    await db.commit()
    return {"message": "Progress saved"}


@router.delete("/{zone_id}/notebooks/{notebook_id}/progress")
async def reset_user_zone_progress(
    zone_id: uuid.UUID,
    notebook_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await get_zone_notebook(db, notebook_id)
    if result is None or result[0].zone_id != zone_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found")

    deleted = await reset_zone_progress(db, current_user.id, notebook_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Progress not found")
    await db.commit()
    return {"message": "Progress reset"}
