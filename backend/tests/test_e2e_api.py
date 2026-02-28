"""Backend API end-to-end tests."""

from datetime import date, timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.config import settings
from app.dependencies import get_db
from app.models.user import Base
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.chat import router as chat_router
from app.routers.upload import router as upload_router


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def _register_user(
    client: AsyncClient,
    *,
    email: str,
    username: str,
    password: str = "StrongPass123",
    programming_level: int = 3,
    maths_level: int = 3,
) -> dict:
    response = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "username": username,
            "password": password,
            "programming_level": programming_level,
            "maths_level": maths_level,
        },
    )
    assert response.status_code == 200
    return response.json()


@pytest_asyncio.fixture
async def e2e_client(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Create an isolated FastAPI app + SQLite database for end-to-end tests."""
    db_path = tmp_path / "e2e.sqlite3"
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "upload_storage_dir", str(upload_dir))
    monkeypatch.setattr(settings, "admin_email", "")

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = FastAPI(title="e2e-test-app")
    app.include_router(auth_router)
    app.include_router(chat_router)
    app.include_router(upload_router)
    app.include_router(admin_router)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_e2e_auth_profile_refresh_logout_flow(e2e_client: AsyncClient) -> None:
    """Registration, profile, refresh, and logout should work as a full flow."""
    register_payload = await _register_user(
        e2e_client,
        email="learner@example.com",
        username="learner",
    )
    access_token = register_payload["access_token"]

    me_response = await e2e_client.get("/api/auth/me", headers=_auth_headers(access_token))
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "learner@example.com"

    refresh_response = await e2e_client.post("/api/auth/refresh")
    assert refresh_response.status_code == 200
    refreshed_token = refresh_response.json()["access_token"]
    assert refreshed_token

    logout_response = await e2e_client.post("/api/auth/logout")
    assert logout_response.status_code == 200

    refresh_after_logout = await e2e_client.post("/api/auth/refresh")
    assert refresh_after_logout.status_code == 401


@pytest.mark.asyncio
async def test_e2e_usage_and_session_list_for_new_user(e2e_client: AsyncClient) -> None:
    """A newly registered user should have zero usage and no sessions."""
    register_payload = await _register_user(
        e2e_client,
        email="usage@example.com",
        username="usage_user",
    )
    headers = _auth_headers(register_payload["access_token"])

    usage_response = await e2e_client.get("/api/chat/usage", headers=headers)
    assert usage_response.status_code == 200
    usage = usage_response.json()
    week_start = date.today() - timedelta(days=date.today().weekday())
    week_end = week_start + timedelta(days=6)
    assert usage["week_start"] == week_start.isoformat()
    assert usage["week_end"] == week_end.isoformat()
    assert usage["input_tokens_used"] == 0
    assert usage["output_tokens_used"] == 0
    assert usage["weighted_tokens_used"] == 0.0
    assert usage["remaining_weighted_tokens"] == 80000.0
    assert usage["weekly_weighted_limit"] == 80000
    assert usage["usage_percentage"] == 0.0

    sessions_response = await e2e_client.get("/api/chat/sessions", headers=headers)
    assert sessions_response.status_code == 200
    assert sessions_response.json() == []


@pytest.mark.asyncio
async def test_e2e_admin_usage_requires_admin_role(e2e_client: AsyncClient) -> None:
    """Non-admin users should be denied admin usage access."""
    register_payload = await _register_user(
        e2e_client,
        email="student@example.com",
        username="student_user",
    )
    headers = _auth_headers(register_payload["access_token"])

    response = await e2e_client.get("/api/admin/usage", headers=headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_e2e_admin_usage_and_audit_log_for_admin(
    e2e_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Admin users should be able to read usage and audit-log endpoints."""
    monkeypatch.setattr(settings, "admin_email", "admin@example.com")
    register_payload = await _register_user(
        e2e_client,
        email="admin@example.com",
        username="admin_user",
    )
    headers = _auth_headers(register_payload["access_token"])

    usage_response = await e2e_client.get("/api/admin/usage", headers=headers)
    assert usage_response.status_code == 200
    usage_data = usage_response.json()
    assert set(usage_data.keys()) == {"today", "this_week", "this_month"}
    for scope in ("today", "this_week", "this_month"):
        assert usage_data[scope]["input_tokens"] == 0
        assert usage_data[scope]["output_tokens"] == 0
        assert usage_data[scope]["estimated_cost_usd"] == 0.0

    audit_response = await e2e_client.get("/api/admin/audit-log", headers=headers)
    assert audit_response.status_code == 200
    audit_data = audit_response.json()
    assert "entries" in audit_data
    assert "total" in audit_data
    assert "page" in audit_data
    assert "per_page" in audit_data
    assert "total_pages" in audit_data


@pytest.mark.asyncio
async def test_e2e_admin_model_switch_and_model_usage_endpoints(
    e2e_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Admin should be able to list and switch available LLM models with password confirmation."""

    async def _fake_model_catalog_health(force: bool = False) -> dict:
        return {
            "smoke_tested_models": {
                "llm": {
                    "anthropic": {
                        "ready": True,
                        "checked_models": {"claude-sonnet-4-6": True},
                        "available_models": ["claude-sonnet-4-6"],
                    },
                    "openai": {
                        "ready": True,
                        "checked_models": {"gpt-5-mini": True},
                        "available_models": ["gpt-5-mini"],
                    },
                    "google-aistudio": {
                        "ready": True,
                        "transport": "aistudio",
                        "checked_models": {"gemini-3-flash-preview": True},
                        "available_models": ["gemini-3-flash-preview"],
                    },
                    "google-vertex": {
                        "ready": True,
                        "transport": "vertex",
                        "checked_models": {"gemini-3.1-pro-preview": True},
                        "available_models": ["gemini-3.1-pro-preview"],
                    },
                },
            },
            "checked_at": "2026-02-27T00:00:00Z",
            "cached": force is False,
        }

    monkeypatch.setattr(
        "app.routers.admin.ai_model_catalog_health_check",
        _fake_model_catalog_health,
    )
    monkeypatch.setattr(settings, "admin_email", "admin@example.com")
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "llm_model_anthropic", "claude-sonnet-4-6")
    monkeypatch.setattr(settings, "llm_model_openai", "gpt-5-mini")
    monkeypatch.setattr(settings, "openai_api_key", "test-openai-key")

    register_payload = await _register_user(
        e2e_client,
        email="admin@example.com",
        username="admin_user",
    )
    headers = _auth_headers(register_payload["access_token"])

    models_response = await e2e_client.get("/api/admin/llm/models", headers=headers)
    assert models_response.status_code == 200
    models_data = models_response.json()
    assert models_data["current"]["provider"] == "anthropic"
    assert any(
        item["provider"] == "openai"
        and item["provider_label"] == "OpenAI"
        and item["model"] == "gpt-5-mini"
        for item in models_data["available_models"]
    )

    bad_password_response = await e2e_client.post(
        "/api/admin/llm/switch",
        headers=headers,
        json={
            "provider": "openai",
            "model": "gpt-5-mini",
            "admin_password": "WrongPass123",
        },
    )
    assert bad_password_response.status_code == 400

    switch_response = await e2e_client.post(
        "/api/admin/llm/switch",
        headers=headers,
        json={
            "provider": "openai",
            "model": "gpt-5-mini",
            "admin_password": "StrongPass123",
        },
    )
    assert switch_response.status_code == 200
    switch_data = switch_response.json()
    assert switch_data["message"] == "LLM switched successfully."
    assert switch_data["current"]["provider"] == "openai"
    assert switch_data["current"]["model"] == "gpt-5-mini"

    usage_response = await e2e_client.get(
        "/api/admin/usage/by-model?provider=openai&model=gpt-5-mini",
        headers=headers,
    )
    assert usage_response.status_code == 200
    usage_data = usage_response.json()
    assert usage_data["provider"] == "openai"
    assert usage_data["model"] == "gpt-5-mini"
    assert usage_data["today"]["input_tokens"] == 0
    assert usage_data["today"]["output_tokens"] == 0


@pytest.mark.asyncio
async def test_e2e_upload_access_is_owner_scoped(e2e_client: AsyncClient) -> None:
    """Uploaded files should only be readable by their owner."""
    owner = await _register_user(
        e2e_client,
        email="owner@example.com",
        username="owner_user",
    )
    owner_headers = _auth_headers(owner["access_token"])

    upload_response = await e2e_client.post(
        "/api/upload",
        headers=owner_headers,
        files=[("files", ("notes.txt", b"private-notes", "text/plain"))],
    )
    assert upload_response.status_code == 200
    uploaded = upload_response.json()["files"][0]
    upload_id = uploaded["id"]

    owner_get_response = await e2e_client.get(
        f"/api/upload/{upload_id}/content",
        headers=owner_headers,
    )
    assert owner_get_response.status_code == 200
    assert owner_get_response.content == b"private-notes"

    other_user = await _register_user(
        e2e_client,
        email="other@example.com",
        username="other_user",
    )
    other_headers = _auth_headers(other_user["access_token"])
    other_get_response = await e2e_client.get(
        f"/api/upload/{upload_id}/content",
        headers=other_headers,
    )
    assert other_get_response.status_code == 404
