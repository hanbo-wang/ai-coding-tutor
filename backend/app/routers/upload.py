"""File upload endpoint."""

import logging
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.upload import AttachmentOut, UploadBatchOut, UploadLimitsOut
from app.services.upload_service import (
    UploadValidationError,
    attachment_payload,
    get_upload_limits_payload,
    get_user_upload_by_id,
    save_uploaded_files,
)

router = APIRouter(tags=["upload"])
logger = logging.getLogger(__name__)


@router.get("/api/upload/limits", response_model=UploadLimitsOut)
async def get_upload_limits() -> UploadLimitsOut:
    """Return client-side upload limits from backend settings."""
    return UploadLimitsOut(**get_upload_limits_payload())


@router.post("/api/upload", response_model=UploadBatchOut)
async def upload_files(
    files: Annotated[list[UploadFile], File(...)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UploadBatchOut:
    """Upload images/documents and return message attachment references."""
    try:
        saved_files = await save_uploaded_files(db, current_user.id, files)
    except UploadValidationError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        await db.rollback()
        logger.exception("Upload failed for user %s", current_user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Upload failed. Please try again.",
        )

    await db.commit()
    return UploadBatchOut(
        files=[AttachmentOut(**attachment_payload(item)) for item in saved_files]
    )


@router.get("/api/upload/{upload_id}/content")
async def get_upload_content(
    upload_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return the uploaded file content for preview/download."""
    uploaded_file = await get_user_upload_by_id(db, current_user.id, upload_id)
    if not uploaded_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found or expired",
        )

    file_path = Path(uploaded_file.storage_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File content not found",
        )

    return FileResponse(
        path=file_path,
        media_type=uploaded_file.content_type,
        filename=uploaded_file.original_filename,
    )
