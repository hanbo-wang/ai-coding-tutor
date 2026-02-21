"""File upload handling, validation, and storage."""

import io
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence

from fastapi import UploadFile
from pypdf import PdfReader
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.chat import UploadedFile
from app.services.notebook_utils import normalise_extension as _normalise_extension

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
DOCUMENT_EXTENSIONS = {".pdf", ".txt", ".py", ".js", ".ts", ".csv", ".ipynb"}
IMAGE_MIME_TO_EXTENSION = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
DOCUMENT_MIME_TO_EXTENSION = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/x-python": ".py",
    "application/javascript": ".js",
    "text/javascript": ".js",
    "application/typescript": ".ts",
    "text/typescript": ".ts",
    "text/csv": ".csv",
    "application/x-ipynb+json": ".ipynb",
}


class UploadValidationError(ValueError):
    """Raised when an uploaded file fails validation."""


@dataclass
class UploadLimits:
    max_images: int
    max_documents: int
    max_image_bytes: int
    max_document_bytes: int
    max_document_tokens: int


def get_upload_limits() -> UploadLimits:
    return UploadLimits(
        max_images=settings.upload_max_images_per_message,
        max_documents=settings.upload_max_documents_per_message,
        max_image_bytes=settings.upload_max_image_mb * 1024 * 1024,
        max_document_bytes=settings.upload_max_document_mb * 1024 * 1024,
        max_document_tokens=settings.upload_max_document_tokens,
    )


def get_upload_slot_limits() -> tuple[int, int]:
    return settings.upload_max_images_per_message, settings.upload_max_documents_per_message


def get_upload_limits_payload() -> dict:
    limits = get_upload_limits()
    image_extensions = sorted(IMAGE_EXTENSIONS)
    document_extensions = sorted(DOCUMENT_EXTENSIONS)
    accept_extensions = sorted(IMAGE_EXTENSIONS | DOCUMENT_EXTENSIONS)
    return {
        "max_images": limits.max_images,
        "max_documents": limits.max_documents,
        "max_image_bytes": limits.max_image_bytes,
        "max_document_bytes": limits.max_document_bytes,
        "image_extensions": image_extensions,
        "document_extensions": document_extensions,
        "accept_extensions": accept_extensions,
    }


def ensure_storage_dir() -> Path:
    storage_dir = Path(settings.upload_storage_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir



def _normalise_content_type(content_type: str | None) -> str:
    if not content_type:
        return ""
    return content_type.split(";", 1)[0].strip().lower()


def _decode_text_bytes(content: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="ignore")


def _extract_pdf_text(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts)


def extract_ipynb_text(content: bytes) -> str:
    notebook_json = _decode_text_bytes(content)
    try:
        parsed = json.loads(notebook_json)
    except json.JSONDecodeError as exc:
        raise UploadValidationError("Invalid .ipynb file.") from exc
    cells = parsed.get("cells", [])
    parts: list[str] = []
    for cell in cells:
        source = cell.get("source", [])
        if isinstance(source, list):
            source_text = "".join(source).strip()
        else:
            source_text = str(source).strip()
        if source_text:
            parts.append(source_text)
    return "\n\n".join(parts)


def extract_document_text(filename: str, content: bytes) -> str:
    extension = _normalise_extension(filename)
    if extension == ".pdf":
        extracted = _extract_pdf_text(content)
    elif extension == ".ipynb":
        extracted = extract_ipynb_text(content)
    else:
        extracted = _decode_text_bytes(content)
    return extracted.strip()


def _estimate_tokens(text: str) -> int:
    # Keep token estimation lightweight and provider-agnostic.
    return max(1, len(text) // 4)


def validate_upload_count(files: Sequence[UploadFile], limits: UploadLimits) -> None:
    if len(files) == 0:
        raise UploadValidationError("Please select at least one file to upload.")

    image_count = 0
    document_count = 0
    for upload in files:
        file_type, _, _ = classify_upload(upload.filename or "", upload.content_type, limits)
        if file_type == "image":
            image_count += 1
        elif file_type == "document":
            document_count += 1

    if image_count > limits.max_images or document_count > limits.max_documents:
        raise UploadValidationError(
            f"Too many files. You can upload up to {limits.max_images} photos and "
            f"{limits.max_documents} files per message."
        )


def classify_upload(
    filename: str,
    content_type: str | None,
    limits: UploadLimits,
) -> tuple[str, int, str]:
    extension = _normalise_extension(filename)
    if extension in IMAGE_EXTENSIONS:
        return "image", limits.max_image_bytes, extension
    if extension in DOCUMENT_EXTENSIONS:
        return "document", limits.max_document_bytes, extension

    normalised_content_type = _normalise_content_type(content_type)
    image_extension = IMAGE_MIME_TO_EXTENSION.get(normalised_content_type)
    if image_extension:
        return "image", limits.max_image_bytes, image_extension
    document_extension = DOCUMENT_MIME_TO_EXTENSION.get(normalised_content_type)
    if document_extension:
        return "document", limits.max_document_bytes, document_extension

    raise UploadValidationError(
        "Unsupported file type. Allowed: PNG, JPG, JPEG, GIF, WebP, "
        "PDF, TXT, PY, JS, TS, CSV, IPYNB."
    )


async def cleanup_expired_uploads(db: AsyncSession) -> int:
    now = datetime.utcnow()
    result = await db.execute(
        select(UploadedFile).where(UploadedFile.expires_at < now)
    )
    expired = result.scalars().all()
    for item in expired:
        _delete_file_safely(item.storage_path)
    if expired:
        await db.execute(
            delete(UploadedFile).where(
                UploadedFile.id.in_([item.id for item in expired])
            )
        )
        await db.flush()
    return len(expired)


def _delete_file_safely(path: str) -> None:
    try:
        file_path = Path(path)
        if file_path.exists():
            file_path.unlink()
    except OSError:
        # Best effort cleanup; stale files are acceptable in failure cases.
        pass


async def save_uploaded_files(
    db: AsyncSession,
    user_id: uuid.UUID,
    files: Sequence[UploadFile],
) -> list[UploadedFile]:
    limits = get_upload_limits()
    validate_upload_count(files, limits)
    await cleanup_expired_uploads(db)

    storage_dir = ensure_storage_dir()
    now = datetime.utcnow()
    expires_at = now + timedelta(hours=settings.upload_expiry_hours)

    saved_files: list[UploadedFile] = []
    written_paths: list[Path] = []
    try:
        for upload in files:
            filename = (upload.filename or "").strip() or "upload"
            file_type, max_bytes, fallback_extension = classify_upload(
                filename, upload.content_type, limits
            )
            content = await upload.read()
            await upload.close()

            if len(content) == 0:
                raise UploadValidationError(f"File '{filename}' is empty.")
            if len(content) > max_bytes:
                raise UploadValidationError(f"File '{filename}' is too large.")

            extension = _normalise_extension(filename)
            if not extension:
                filename = f"{filename}{fallback_extension}"
                extension = fallback_extension
            stored_name = f"{uuid.uuid4().hex}{extension}"
            storage_path = storage_dir / stored_name
            storage_path.write_bytes(content)
            written_paths.append(storage_path)

            extracted_text = None
            if file_type == "document":
                extracted_text = extract_document_text(filename, content)
                document_tokens = _estimate_tokens(extracted_text)
                if document_tokens > limits.max_document_tokens:
                    raise UploadValidationError(f"File '{filename}' is too large.")

            saved = UploadedFile(
                user_id=user_id,
                original_filename=filename,
                stored_filename=stored_name,
                content_type=upload.content_type or "application/octet-stream",
                file_type=file_type,
                size_bytes=len(content),
                storage_path=str(storage_path),
                extracted_text=extracted_text,
                expires_at=expires_at,
            )
            db.add(saved)
            saved_files.append(saved)
    except Exception:
        for path in written_paths:
            _delete_file_safely(str(path))
        raise

    await db.flush()
    return saved_files


async def get_user_uploads_by_ids(
    db: AsyncSession,
    user_id: uuid.UUID,
    upload_ids: Sequence[uuid.UUID],
) -> list[UploadedFile]:
    if not upload_ids:
        return []

    now = datetime.utcnow()
    result = await db.execute(
        select(UploadedFile).where(
            UploadedFile.user_id == user_id,
            UploadedFile.id.in_(upload_ids),
            UploadedFile.expires_at >= now,
        )
    )
    found = result.scalars().all()
    lookup = {item.id: item for item in found}
    ordered: list[UploadedFile] = []
    for upload_id in upload_ids:
        item = lookup.get(upload_id)
        if item:
            ordered.append(item)
    return ordered


async def get_user_upload_by_id(
    db: AsyncSession,
    user_id: uuid.UUID,
    upload_id: uuid.UUID,
) -> UploadedFile | None:
    now = datetime.utcnow()
    result = await db.execute(
        select(UploadedFile).where(
            UploadedFile.id == upload_id,
            UploadedFile.user_id == user_id,
            UploadedFile.expires_at >= now,
        )
    )
    return result.scalar_one_or_none()


def attachment_payload(uploaded_file: UploadedFile) -> dict:
    return {
        "id": str(uploaded_file.id),
        "filename": uploaded_file.original_filename,
        "content_type": uploaded_file.content_type,
        "file_type": uploaded_file.file_type,
        "url": f"/api/upload/{uploaded_file.id}/content",
    }
