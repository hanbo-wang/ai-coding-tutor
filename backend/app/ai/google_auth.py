"""Google Cloud service-account auth helpers for Vertex AI requests."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_GOOGLE_AUTH_IMPORT_ERROR: Exception | None = None

try:  # pragma: no cover - exercised indirectly; guarded for local dev without dependency.
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2 import service_account
except Exception as exc:  # pragma: no cover
    GoogleAuthRequest = None  # type: ignore[assignment]
    service_account = None  # type: ignore[assignment]
    _GOOGLE_AUTH_IMPORT_ERROR = exc

GOOGLE_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
REPO_ROOT = Path(__file__).resolve().parents[3]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _candidate_paths(raw_path: str) -> list[Path]:
    path = Path(raw_path)
    candidates: list[Path] = [path]
    if not path.is_absolute():
        candidates.append((REPO_ROOT / path).resolve())
    return candidates


def resolve_google_credentials_path(
    credentials_path: str,
    host_credentials_path: str = "",
) -> str:
    """Resolve a usable Google service-account path for local and container runs.

    Resolution order:
    1. `GOOGLE_APPLICATION_CREDENTIALS`
    2. explicit host path (for local runs)
    3. `GOOGLE_APPLICATION_CREDENTIALS_HOST_PATH` from process environment
    4. common repository-local service-account locations by filename
    """
    configured = (credentials_path or "").strip()
    host = (host_credentials_path or "").strip()
    env_host = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_HOST_PATH", "").strip()

    seen: set[str] = set()
    raw_candidates = [configured, host, env_host]
    for raw in raw_candidates:
        if not raw:
            continue
        for candidate in _candidate_paths(raw):
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            if candidate.exists() and candidate.is_file():
                return key

    # Convenience fallback for local development when `.env` stores a container path.
    for pattern in ("ai-coding-tutor-*.json",):
        for folder in (REPO_ROOT, REPO_ROOT / ".vscode"):
            for candidate in sorted(folder.glob(pattern)):
                key = str(candidate.resolve())
                if key in seen:
                    continue
                seen.add(key)
                if candidate.is_file():
                    return key

    return configured or host or env_host


def _load_service_account_json(credentials_path: str) -> dict[str, Any]:
    if not credentials_path:
        raise ValueError(
            "GOOGLE_APPLICATION_CREDENTIALS is required for Vertex AI providers"
        )
    path = Path(credentials_path)
    if not path.exists():
        raise ValueError(f"Google credentials file not found: {credentials_path}")
    if not path.is_file():
        raise ValueError(f"Google credentials path is not a file: {credentials_path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid Google credentials JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Invalid Google credentials JSON: expected an object")
    if data.get("type") != "service_account":
        raise ValueError(
            "Google credentials must be a service account JSON file (type=service_account)"
        )
    return data


def resolve_google_project_id(
    credentials_path: str,
    explicit_project_id: str = "",
) -> str:
    """Resolve Vertex project ID from settings or the service-account JSON."""
    if explicit_project_id.strip():
        return explicit_project_id.strip()
    resolved_path = resolve_google_credentials_path(credentials_path)
    data = _load_service_account_json(resolved_path)
    project_id = str(data.get("project_id", "")).strip()
    if not project_id:
        raise ValueError(
            "Google Cloud project ID not found. Set GOOGLE_CLOUD_PROJECT_ID or use a "
            "service account JSON containing project_id."
        )
    return project_id


class GoogleServiceAccountTokenProvider:
    """Loads a service-account JSON and refreshes OAuth access tokens on demand."""

    def __init__(self, credentials_path: str) -> None:
        if service_account is None or GoogleAuthRequest is None:
            detail = f" ({_GOOGLE_AUTH_IMPORT_ERROR})" if _GOOGLE_AUTH_IMPORT_ERROR else ""
            raise RuntimeError(
                "Google auth dependencies are unavailable. Add 'google-auth' and "
                f"'requests' to backend dependencies{detail}."
            )
        resolved_path = resolve_google_credentials_path(credentials_path)
        _load_service_account_json(resolved_path)
        self.credentials_path = resolved_path
        self._credentials = service_account.Credentials.from_service_account_file(
            resolved_path,
            scopes=[GOOGLE_CLOUD_PLATFORM_SCOPE],
        )
        self._lock = asyncio.Lock()

    def _needs_refresh(self) -> bool:
        token = getattr(self._credentials, "token", None)
        expiry = getattr(self._credentials, "expiry", None)
        if not token:
            return True
        if expiry is None:
            return True
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return (_utc_now() + timedelta(seconds=60)) >= expiry

    def _refresh_sync(self) -> None:
        self._credentials.refresh(GoogleAuthRequest())

    async def get_access_token(self) -> str:
        async with self._lock:
            if self._needs_refresh():
                await asyncio.to_thread(self._refresh_sync)
            token = getattr(self._credentials, "token", None)
            if not token:
                raise RuntimeError("Failed to obtain Google OAuth access token")
            return str(token)
