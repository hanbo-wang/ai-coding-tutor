"""Personal notebook CRUD endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.routers._notebook_json import parse_notebook_json_or_500
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.notebook import NotebookDetail, NotebookOut, NotebookRename, NotebookSave
from app.services.notebook_service import (
    NotebookValidationError,
    delete_notebook,
    get_notebook,
    list_notebooks,
    rename_notebook,
    save_notebook,
    update_notebook_state,
)

router = APIRouter(prefix="/api/notebooks", tags=["notebooks"])


@router.get("", response_model=list[NotebookOut])
async def get_notebook_list(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await list_notebooks(db, current_user.id)


@router.post("", response_model=NotebookOut, status_code=status.HTTP_201_CREATED)
async def upload_notebook(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
):
    try:
        notebook = await save_notebook(db, current_user.id, current_user.email, file)
    except NotebookValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await db.commit()
    await db.refresh(notebook)
    return notebook


@router.get("/{notebook_id}", response_model=NotebookDetail)
async def get_notebook_detail(
    notebook_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    notebook = await get_notebook(db, current_user.id, notebook_id)
    if notebook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found")
    return NotebookDetail(
        id=notebook.id,
        title=notebook.title,
        original_filename=notebook.original_filename,
        size_bytes=notebook.size_bytes,
        created_at=notebook.created_at,
        notebook_json=parse_notebook_json_or_500(notebook.notebook_json),
    )


@router.put("/{notebook_id}", response_model=NotebookOut)
async def save_notebook_state(
    notebook_id: uuid.UUID,
    payload: NotebookSave,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        notebook = await update_notebook_state(
            db, current_user.id, notebook_id, payload.notebook_json
        )
    except NotebookValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if notebook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found")

    await db.commit()
    await db.refresh(notebook)
    return notebook


@router.delete("/{notebook_id}")
async def remove_notebook(
    notebook_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    deleted = await delete_notebook(db, current_user.id, notebook_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found")
    await db.commit()
    return {"message": "Notebook deleted"}


@router.patch("/{notebook_id}/rename", response_model=NotebookOut)
async def rename_notebook_entry(
    notebook_id: uuid.UUID,
    payload: NotebookRename,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        notebook = await rename_notebook(db, current_user.id, notebook_id, payload.title)
    except NotebookValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if notebook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found")

    await db.commit()
    await db.refresh(notebook)
    return notebook
