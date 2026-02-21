from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NotebookOut(BaseModel):
    id: UUID
    title: str
    original_filename: str
    size_bytes: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotebookDetail(NotebookOut):
    notebook_json: dict


class NotebookSave(BaseModel):
    notebook_json: dict = Field(..., description="Current notebook JSON payload")


class NotebookRename(BaseModel):
    title: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="New notebook title shown in the workspace.",
    )
