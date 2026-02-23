"""Application settings loaded from environment variables via .env file."""

from pathlib import Path
import json
import re
from typing import Literal

from pydantic import ConfigDict, field_validator
from pydantic_settings import BaseSettings

from app.ai.model_registry import (
    normalise_embedding_provider,
    normalise_llm_provider,
    normalise_model_alias,
)
from app.ai.pricing import LLM_MODEL_PRICING, LLM_PRICING

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]

def _parse_admin_email_set(raw: str) -> set[str]:
    """Parse a flexible admin email string into a normalised set."""
    value = raw.strip()
    if not value:
        return set()

    if value.startswith("["):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                candidates = [str(item) for item in parsed]
            else:
                candidates = [value]
        except json.JSONDecodeError:
            candidates = re.split(r"[,\s;]+", value)
    else:
        candidates = re.split(r"[,\s;]+", value)

    normalised: set[str] = set()
    for candidate in candidates:
        email = candidate.strip().strip("'\"").lower()
        if email:
            normalised.add(email)
    return normalised


class Settings(BaseSettings):
    # Database
    database_url: str
    sqlalchemy_echo: bool = False

    # JWT
    jwt_secret_key: str
    jwt_access_token_expire_minutes: int
    jwt_refresh_token_expire_days: int
    auth_cookie_secure: bool = False
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # CORS
    cors_origins: list[str]

    # Backend
    backend_reload: bool = False

    # LLM providers
    llm_provider: str = "google"
    llm_model_google: str = "gemini-3-flash-preview"
    llm_model_anthropic: str = "claude-sonnet-4-6"
    llm_model_openai: str = "gpt-5.2"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""  # optional legacy path; Vertex provider uses service account
    google_application_credentials: str = ""
    google_application_credentials_host_path: str = ""
    google_cloud_project_id: str = ""
    google_vertex_gemini_location: str = "global"

    # Embedding providers
    embedding_provider: str = "vertex"
    embedding_model_vertex: str = "multimodalembedding@001"
    google_vertex_embedding_location: str = "us-central1"
    cohere_api_key: str = ""
    voyageai_api_key: str = ""

    # Chat and token limits
    llm_max_context_tokens: int
    llm_max_user_input_tokens: int
    context_compression_threshold: float
    user_weekly_weighted_token_limit: int = 80000
    chat_enable_greeting_filter: bool = False
    chat_enable_off_topic_filter: bool = False
    chat_same_problem_detection_mode: Literal["llm", "embedding"] = "llm"

    # Rate limiting
    rate_limit_user_per_minute: int = 5
    rate_limit_global_per_minute: int = 300
    max_ws_connections_per_user: int = 3

    # Uploads
    upload_storage_dir: str
    upload_expiry_hours: int
    upload_max_images_per_message: int
    upload_max_documents_per_message: int
    upload_max_image_mb: int
    upload_max_document_mb: int
    upload_max_document_tokens: int

    # Notebooks
    notebook_storage_dir: str
    notebook_max_size_mb: int
    notebook_max_per_user: int
    notebook_max_context_tokens: int

    # Misc (previously hardcoded values, now configurable)
    image_token_estimate: int = 512
    notebook_max_title_length: int = 120
    session_preview_max_chars: int = 80

    # Admin
    admin_email: str = ""

    @property
    def admin_email_set(self) -> set[str]:
        return _parse_admin_email_set(self.admin_email)

    @field_validator("llm_provider", mode="before")
    @classmethod
    def _normalise_llm_provider(cls, value: str) -> str:
        return normalise_llm_provider(str(value))

    @field_validator("embedding_provider", mode="before")
    @classmethod
    def _normalise_embedding_provider(cls, value: str) -> str:
        return normalise_embedding_provider(str(value))

    @field_validator("chat_same_problem_detection_mode", mode="before")
    @classmethod
    def _normalise_same_problem_mode(cls, value: str) -> str:
        return str(value).strip().lower()

    @field_validator(
        "llm_model_google",
        "llm_model_anthropic",
        "llm_model_openai",
        "embedding_model_vertex",
        mode="before",
    )
    @classmethod
    def _normalise_model_aliases(cls, value: str) -> str:
        return normalise_model_alias(str(value))

    model_config = ConfigDict(
        env_file=(str(REPO_ROOT / ".env"), str(BACKEND_DIR / ".env")),
        extra="ignore",
    )


settings = Settings()
