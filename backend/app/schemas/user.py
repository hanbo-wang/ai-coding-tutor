from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8)
    programming_level: int = Field(default=3, ge=1, le=5)
    maths_level: int = Field(default=3, ge=1, le=5)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserProfile(BaseModel):
    id: UUID
    email: str
    username: str
    programming_level: int
    maths_level: int
    is_admin: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserProfileUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=50)
    programming_level: int | None = Field(default=None, ge=1, le=5)
    maths_level: int | None = Field(default=None, ge=1, le=5)


class ChangePassword(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
