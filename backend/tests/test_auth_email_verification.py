"""Auth tests for email verification flows."""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.config import settings
from app.dependencies import get_db
from app.models.email_verification import EmailVerificationToken
from app.models.user import Base, User
from app.routers.auth import router as auth_router
from app.services.auth_service import hash_password, verify_password


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture
async def auth_email_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "auth_email.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(settings, "email_provider", "noop")
    monkeypatch.setattr(settings, "email_code_max_attempts", 5)
    monkeypatch.setattr(
        "app.services.email_verification_service._generate_code",
        lambda: "123456",
    )
    sent_emails: list[str] = []

    async def fake_send_transactional_email(
        *,
        to_email: str,
        subject: str,
        html_content: str,
    ) -> str:
        sent_emails.append(to_email)
        return "message-id"

    monkeypatch.setattr(
        "app.services.email_verification_service.send_transactional_email",
        fake_send_transactional_email,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = FastAPI(title="auth-email-test-app")
    app.include_router(auth_router)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, session_factory, sent_emails

    app.dependency_overrides.clear()
    await engine.dispose()


async def _create_user(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    email: str,
    username: str,
    password: str = "StrongPass123",
) -> None:
    async with session_factory() as db:
        db.add(
            User(
                email=email,
                username=username,
                password_hash=hash_password(password),
                programming_level=3,
                maths_level=3,
                is_admin=False,
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_register_send_code_success_and_duplicate_email_rejected(auth_email_client) -> None:
    client, _, _ = auth_email_client

    send_code = await client.post(
        "/api/auth/register/send-code",
        json={"email": "new@example.com", "username": "new_user"},
    )
    assert send_code.status_code == 200

    register = await client.post(
        "/api/auth/register",
        json={
            "email": "new@example.com",
            "username": "new_user",
            "password": "StrongPass123",
            "verification_code": "123456",
            "programming_level": 3,
            "maths_level": 3,
        },
    )
    assert register.status_code == 200

    duplicate = await client.post(
        "/api/auth/register/send-code",
        json={"email": "new@example.com", "username": "another_user"},
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["detail"] == "Email already registered"


@pytest.mark.asyncio
async def test_register_send_code_rejects_duplicate_username(
    auth_email_client,
) -> None:
    client, session_factory, _ = auth_email_client
    await _create_user(
        session_factory,
        email="existing@example.com",
        username="test_user",
    )

    send_code = await client.post(
        "/api/auth/register/send-code",
        json={"email": "new@example.com", "username": "test_user"},
    )
    assert send_code.status_code == 400
    assert send_code.json()["detail"] == "Username already taken"

    async with session_factory() as db:
        token = (
            await db.execute(
                select(EmailVerificationToken).where(
                    EmailVerificationToken.email == "new@example.com",
                    EmailVerificationToken.purpose == "register",
                )
            )
        ).scalar_one_or_none()
        assert token is None


@pytest.mark.asyncio
async def test_register_rejects_duplicate_username_after_code_issue(auth_email_client) -> None:
    client, session_factory, _ = auth_email_client
    await _create_user(
        session_factory,
        email="taken@example.com",
        username="taken_name",
    )

    send_code = await client.post(
        "/api/auth/register/send-code",
        json={"email": "new@example.com", "username": "new_name"},
    )
    assert send_code.status_code == 200

    duplicate_username = await client.post(
        "/api/auth/register",
        json={
            "email": "new@example.com",
            "username": "taken_name",
            "password": "StrongPass123",
            "verification_code": "123456",
            "programming_level": 3,
            "maths_level": 3,
        },
    )
    assert duplicate_username.status_code == 400
    assert duplicate_username.json()["detail"] == "Username already taken"

    retry = await client.post(
        "/api/auth/register",
        json={
            "email": "new@example.com",
            "username": "new_name",
            "password": "StrongPass123",
            "verification_code": "123456",
            "programming_level": 3,
            "maths_level": 3,
        },
    )
    assert retry.status_code == 200


@pytest.mark.asyncio
async def test_register_rejects_invalid_code(auth_email_client) -> None:
    client, _, _ = auth_email_client

    send_code = await client.post(
        "/api/auth/register/send-code",
        json={"email": "wrong@example.com", "username": "wrong_user"},
    )
    assert send_code.status_code == 200

    register = await client.post(
        "/api/auth/register",
        json={
            "email": "wrong@example.com",
            "username": "wrong_user",
            "password": "StrongPass123",
            "verification_code": "999999",
            "programming_level": 3,
            "maths_level": 3,
        },
    )
    assert register.status_code == 400
    assert register.json()["detail"] == "Invalid or expired verification code"


@pytest.mark.asyncio
async def test_register_rejects_expired_code(auth_email_client) -> None:
    client, session_factory, _ = auth_email_client

    send_code = await client.post(
        "/api/auth/register/send-code",
        json={"email": "expired@example.com", "username": "expired_user"},
    )
    assert send_code.status_code == 200

    async with session_factory() as db:
        token = (
            await db.execute(
                select(EmailVerificationToken).where(
                    EmailVerificationToken.email == "expired@example.com"
                )
            )
        ).scalar_one()
        token.expires_at = token.expires_at.replace(year=2000)
        await db.commit()

    register = await client.post(
        "/api/auth/register",
        json={
            "email": "expired@example.com",
            "username": "expired_user",
            "password": "StrongPass123",
            "verification_code": "123456",
            "programming_level": 3,
            "maths_level": 3,
        },
    )
    assert register.status_code == 400
    assert register.json()["detail"] == "Invalid or expired verification code"


@pytest.mark.asyncio
async def test_register_rejects_after_max_failed_attempts(auth_email_client) -> None:
    client, _, _ = auth_email_client

    send_code = await client.post(
        "/api/auth/register/send-code",
        json={"email": "attempts@example.com", "username": "attempts_user"},
    )
    assert send_code.status_code == 200

    for _ in range(settings.email_code_max_attempts):
        failed = await client.post(
            "/api/auth/register",
            json={
                "email": "attempts@example.com",
                "username": "attempts_user",
                "password": "StrongPass123",
                "verification_code": "999999",
                "programming_level": 3,
                "maths_level": 3,
            },
        )
        assert failed.status_code == 400

    final_try = await client.post(
        "/api/auth/register",
        json={
            "email": "attempts@example.com",
            "username": "attempts_user",
            "password": "StrongPass123",
            "verification_code": "123456",
            "programming_level": 3,
            "maths_level": 3,
        },
    )
    assert final_try.status_code == 400
    assert final_try.json()["detail"] == "Invalid or expired verification code"


@pytest.mark.asyncio
async def test_password_reset_send_code_returns_registered_and_missing_responses(auth_email_client) -> None:
    client, session_factory, sent_emails = auth_email_client
    await _create_user(
        session_factory,
        email="existing@example.com",
        username="existing_user",
    )

    existing = await client.post(
        "/api/auth/password-reset/send-code",
        json={"email": "existing@example.com"},
    )
    assert existing.status_code == 200
    assert existing.json()["message"] == "Verification code sent."

    missing = await client.post(
        "/api/auth/password-reset/send-code",
        json={"email": "missing@example.com"},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Email is not registered."

    async with session_factory() as db:
        missing_token = (
            await db.execute(
                select(EmailVerificationToken).where(
                    EmailVerificationToken.email == "missing@example.com",
                    EmailVerificationToken.purpose == "reset_password",
                )
            )
        ).scalar_one_or_none()
        assert missing_token is None

    assert "missing@example.com" not in sent_emails


@pytest.mark.asyncio
async def test_password_reset_confirm_success_and_single_use(auth_email_client) -> None:
    client, session_factory, _ = auth_email_client
    await _create_user(
        session_factory,
        email="reset@example.com",
        username="reset_user",
        password="OldPass123",
    )

    send_code = await client.post(
        "/api/auth/password-reset/send-code",
        json={"email": "reset@example.com"},
    )
    assert send_code.status_code == 200

    confirm = await client.post(
        "/api/auth/password-reset/confirm",
        json={
            "email": "reset@example.com",
            "verification_code": "123456",
            "new_password": "NewPass123",
        },
    )
    assert confirm.status_code == 200
    assert confirm.json()["message"] == "Password reset successfully."

    async with session_factory() as db:
        user = (
            await db.execute(select(User).where(User.email == "reset@example.com"))
        ).scalar_one()
        assert verify_password("NewPass123", user.password_hash)

    reuse = await client.post(
        "/api/auth/password-reset/confirm",
        json={
            "email": "reset@example.com",
            "verification_code": "123456",
            "new_password": "AnotherPass123",
        },
    )
    assert reuse.status_code == 400
    assert reuse.json()["detail"] == "Invalid or expired verification code"


@pytest.mark.asyncio
async def test_password_reset_confirm_returns_not_found_for_unregistered_email(
    auth_email_client,
) -> None:
    client, _, _ = auth_email_client
    response = await client.post(
        "/api/auth/password-reset/confirm",
        json={
            "email": "missing@example.com",
            "verification_code": "123456",
            "new_password": "NewPass123",
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Email is not registered."


@pytest.mark.asyncio
async def test_change_password_endpoint_resets_password(auth_email_client) -> None:
    client, session_factory, _ = auth_email_client
    await _create_user(
        session_factory,
        email="legacy@example.com",
        username="legacy_user",
    )

    login = await client.post(
        "/api/auth/login",
        json={"email": "legacy@example.com", "password": "StrongPass123"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    response = await client.put(
        "/api/auth/me/password",
        headers=_auth_headers(token),
        json={
            "current_password": "StrongPass123",
            "new_password": "NewPass123",
        },
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Password reset successfully."

    relogin = await client.post(
        "/api/auth/login",
        json={"email": "legacy@example.com", "password": "NewPass123"},
    )
    assert relogin.status_code == 200


@pytest.mark.asyncio
async def test_change_password_endpoint_rejects_wrong_current_password(
    auth_email_client,
) -> None:
    client, session_factory, _ = auth_email_client
    await _create_user(
        session_factory,
        email="wrong-pass@example.com",
        username="wrong_pass_user",
    )

    login = await client.post(
        "/api/auth/login",
        json={"email": "wrong-pass@example.com", "password": "StrongPass123"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    response = await client.put(
        "/api/auth/me/password",
        headers=_auth_headers(token),
        json={
            "current_password": "BadPass123",
            "new_password": "NewPass123",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Current password is incorrect."


@pytest.mark.asyncio
async def test_profile_update_rejects_email_field(auth_email_client) -> None:
    client, session_factory, _ = auth_email_client
    await _create_user(
        session_factory,
        email="profile@example.com",
        username="profile_user",
    )

    login = await client.post(
        "/api/auth/login",
        json={"email": "profile@example.com", "password": "StrongPass123"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    response = await client.put(
        "/api/auth/me",
        headers=_auth_headers(token),
        json={"email": "new@example.com"},
    )
    assert response.status_code == 422
