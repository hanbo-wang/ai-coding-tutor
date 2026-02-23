from datetime import datetime, date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.upload import AttachmentOut


class ChatMessageIn(BaseModel):
    content: str = Field(default="", max_length=16000)
    session_id: UUID | None = None
    upload_ids: list[UUID] = Field(default_factory=list)
    notebook_id: UUID | None = None
    zone_notebook_id: UUID | None = None
    cell_code: str | None = Field(default=None, max_length=20000)
    error_output: str | None = Field(default=None, max_length=20000)


class ChatMessageOut(BaseModel):
    id: UUID
    session_id: UUID
    role: str
    content: str
    hint_level_used: int | None = None
    problem_difficulty: int | None = None
    maths_difficulty: int | None = None
    attachments: list[AttachmentOut] = Field(default_factory=list)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatSessionOut(BaseModel):
    id: UUID
    session_type: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatSessionListItem(BaseModel):
    id: UUID
    preview: str
    created_at: datetime


class TokenUsageOut(BaseModel):
    week_start: date
    week_end: date
    input_tokens_used: int
    output_tokens_used: int
    weighted_tokens_used: float
    remaining_weighted_tokens: float
    weekly_weighted_limit: int
    usage_percentage: float
