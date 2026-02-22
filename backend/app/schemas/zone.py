from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ZoneCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None


class ZoneUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    order: int | None = Field(default=None, ge=1)


class ZoneOut(BaseModel):
    id: UUID
    title: str
    description: str | None = None
    order: int
    created_at: datetime
    notebook_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class ZoneNotebookOut(BaseModel):
    id: UUID
    zone_id: UUID
    title: str
    description: str | None = None
    original_filename: str
    size_bytes: int
    order: int
    created_at: datetime
    has_progress: bool = False

    model_config = ConfigDict(from_attributes=True)


class ZoneNotebookMetadataUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class ZoneNotebookDetail(ZoneNotebookOut):
    notebook_json: dict


class ZoneProgressSave(BaseModel):
    notebook_state: dict


class ZoneReorder(BaseModel):
    notebook_ids: list[UUID] = Field(default_factory=list)


class ZoneDetailOut(ZoneOut):
    notebooks: list[ZoneNotebookOut] = Field(default_factory=list)


class ZoneSharedFileOut(BaseModel):
    id: UUID
    zone_id: UUID
    relative_path: str
    original_filename: str
    content_type: str | None = None
    size_bytes: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ZoneRuntimeFileOut(BaseModel):
    relative_path: str
    content_base64: str
    content_type: str | None = None


class ZoneImportResult(BaseModel):
    notebooks_created: int
    shared_files_created: int
    shared_files_updated: int
