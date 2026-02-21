"""Application settings loaded from environment variables via .env file."""

from pathlib import Path
import json
import re
from typing import Literal

from pydantic import ConfigDict
from pydantic_settings import BaseSettings


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]

# LLM pricing per million tokens (used for cost estimation only).
LLM_PRICING = {
    "anthropic": {"input_per_mtok": 3.00, "output_per_mtok": 15.00},
    "google":    {"input_per_mtok": 2.00, "output_per_mtok": 12.00},
    "openai":    {"input_per_mtok": 1.75, "output_per_mtok": 14.00},
}


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
    llm_provider: str
    anthropic_api_key: str
    openai_api_key: str
    google_api_key: str

    # Embedding providers
    embedding_provider: str
    cohere_api_key: str
    voyageai_api_key: str

    # Chat and token limits
    llm_max_context_tokens: int
    llm_max_user_input_tokens: int
    context_compression_threshold: float
    user_daily_input_token_limit: int
    user_daily_output_token_limit: int
    chat_enable_greeting_filter: bool = False
    chat_enable_off_topic_filter: bool = False

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

    model_config = ConfigDict(
        env_file=(str(REPO_ROOT / ".env"), str(BACKEND_DIR / ".env")),
        extra="ignore",
    )


settings = Settings()
