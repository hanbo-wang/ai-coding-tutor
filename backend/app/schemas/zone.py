from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ZoneCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)


class ZoneUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1)
    order: int | None = Field(default=None, ge=1)


class ZoneOut(BaseModel):
    id: UUID
    title: str
    description: str
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


class ZoneNotebookDetail(ZoneNotebookOut):
    notebook_json: dict


class ZoneProgressSave(BaseModel):
    notebook_state: dict


class ZoneReorder(BaseModel):
    notebook_ids: list[UUID] = Field(default_factory=list)


class ZoneDetailOut(ZoneOut):
    notebooks: list[ZoneNotebookOut] = Field(default_factory=list)
