"""Auth tests for email verification flows."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.config import settings
from app.dependencies import get_db
from app.models.audit import AdminAuditLog
from app.models.chat import (
    ChatMessage,
    ChatSession,
    DailyTokenUsage,
    RetainedDailyTokenUsage,
    UploadedFile,
)
from app.models.email_verification import EmailVerificationToken
from app.models.notebook import UserNotebook
from app.models.user import Base, User
from app.models.zone import LearningZone, ZoneNotebook, ZoneNotebookProgress
from app.routers.admin import router as admin_router
from app.routers.auth import (
    REGISTRATION_EMAIL_POLICY_DETAIL,
    USER_NOTICE_ACCEPTANCE_DETAIL,
    router as auth_router,
)
from app.routers.chat import router as chat_router
from app.services.auth_service import hash_password, verify_password


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture
async def auth_email_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "auth_email.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(settings, "email_provider", "noop")
    monkeypatch.setattr(settings, "admin_email", "")
    monkeypatch.setattr(settings, "email_code_max_attempts", 5)
    monkeypatch.setattr(settings, "email_code_resend_cooldown_seconds", 120)
    monkeypatch.setattr(settings, "enable_ucl_registration_email_policy", False)
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
    app.include_router(chat_router)
    app.include_router(admin_router)

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


async def _register_user(
    client: AsyncClient,
    *,
    email: str,
    username: str,
    password: str = "StrongPass123",
) -> str:
    send_code = await client.post(
        "/api/auth/register/send-code",
        json={"email": email, "username": username},
    )
    assert send_code.status_code == 200

    register = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "username": username,
            "password": password,
            "verification_code": "123456",
            "accepted_user_notice": True,
            "programming_level": 3,
            "maths_level": 3,
        },
    )
    assert register.status_code == 200
    return register.json()["access_token"]


@pytest.mark.asyncio
async def test_register_send_code_success_and_duplicate_email_rejected(auth_email_client) -> None:
    client, _, _ = auth_email_client

    send_code = await client.post(
        "/api/auth/register/send-code",
        json={"email": "new.user@example.com", "username": "new_user"},
    )
    assert send_code.status_code == 200
    assert send_code.json() == {
        "message": "Verification code sent.",
        "resend_cooldown_seconds": 120,
    }

    register = await client.post(
        "/api/auth/register",
        json={
            "email": "new.user@example.com",
            "username": "new_user",
            "password": "StrongPass123",
            "verification_code": "123456",
            "accepted_user_notice": True,
            "programming_level": 3,
            "maths_level": 3,
        },
    )
    assert register.status_code == 200

    duplicate = await client.post(
        "/api/auth/register/send-code",
        json={"email": "new.user@example.com", "username": "another_user"},
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["detail"] == "Email already registered"


@pytest.mark.asyncio
async def test_register_send_code_rejects_immediate_resend_with_retry_after_header(
    auth_email_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, _ = auth_email_client
    fixed_now = datetime(2026, 3, 11, 12, 0, 0)
    monkeypatch.setattr(
        "app.services.email_verification_service._now_utc",
        lambda: fixed_now,
    )

    first = await client.post(
        "/api/auth/register/send-code",
        json={"email": "new.user@example.com", "username": "new_user"},
    )
    assert first.status_code == 200

    retry = await client.post(
        "/api/auth/register/send-code",
        json={"email": "new.user@example.com", "username": "new_user"},
    )
    assert retry.status_code == 429
    assert retry.headers["Retry-After"] == "120"
    assert (
        retry.json()["detail"]
        == "Please wait 120s before requesting another code."
    )


@pytest.mark.asyncio
async def test_registration_policy_endpoint_returns_default_disabled(auth_email_client) -> None:
    client, _, _ = auth_email_client

    response = await client.get("/api/auth/register/policy")
    assert response.status_code == 200
    assert response.json() == {"enable_ucl_registration_email_policy": False}


@pytest.mark.asyncio
async def test_register_send_code_allows_non_ucl_domain_email_when_policy_disabled(
    auth_email_client,
) -> None:
    client, _, _ = auth_email_client

    response = await client.post(
        "/api/auth/register/send-code",
        json={"email": "learner@example.com", "username": "open_signup"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_registration_policy_endpoint_returns_enabled_when_configured(
    auth_email_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, _ = auth_email_client
    monkeypatch.setattr(settings, "enable_ucl_registration_email_policy", True)

    response = await client.get("/api/auth/register/policy")
    assert response.status_code == 200
    assert response.json() == {"enable_ucl_registration_email_policy": True}


@pytest.mark.asyncio
async def test_register_send_code_rejects_non_ucl_domain_email_when_policy_enabled(
    auth_email_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, _ = auth_email_client
    monkeypatch.setattr(settings, "enable_ucl_registration_email_policy", True)

    response = await client.post(
        "/api/auth/register/send-code",
        json={"email": "learner.24@example.com", "username": "non_ucl"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == REGISTRATION_EMAIL_POLICY_DETAIL


@pytest.mark.asyncio
async def test_register_send_code_rejects_ucl_email_without_numeric_suffix_when_policy_enabled(
    auth_email_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, _ = auth_email_client
    monkeypatch.setattr(settings, "enable_ucl_registration_email_policy", True)

    response = await client.post(
        "/api/auth/register/send-code",
        json={"email": "v.pedrosa@ucl.ac.uk", "username": "ucl_staff"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == REGISTRATION_EMAIL_POLICY_DETAIL


@pytest.mark.asyncio
async def test_register_allows_admin_email_exemption_when_policy_enabled(
    auth_email_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory, _ = auth_email_client
    monkeypatch.setattr(settings, "enable_ucl_registration_email_policy", True)
    monkeypatch.setattr(settings, "admin_email", "v.pedrosa@ucl.ac.uk")

    send_code = await client.post(
        "/api/auth/register/send-code",
        json={"email": "v.pedrosa@ucl.ac.uk", "username": "admin_user"},
    )
    assert send_code.status_code == 200

    register = await client.post(
        "/api/auth/register",
        json={
            "email": "v.pedrosa@ucl.ac.uk",
            "username": "admin_user",
            "password": "StrongPass123",
            "verification_code": "123456",
            "accepted_user_notice": True,
            "programming_level": 3,
            "maths_level": 3,
        },
    )
    assert register.status_code == 200

    async with session_factory() as db:
        user = (
            await db.execute(select(User).where(User.email == "v.pedrosa@ucl.ac.uk"))
        ).scalar_one()
        assert user.is_admin is True


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
        json={"email": "candidate.user@example.com", "username": "test_user"},
    )
    assert send_code.status_code == 400
    assert send_code.json()["detail"] == "Username already taken"

    async with session_factory() as db:
        token = (
            await db.execute(
                select(EmailVerificationToken).where(
                    EmailVerificationToken.email == "candidate.user@example.com",
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
        json={"email": "retry.user@example.com", "username": "new_name"},
    )
    assert send_code.status_code == 200

    duplicate_username = await client.post(
        "/api/auth/register",
        json={
            "email": "retry.user@example.com",
            "username": "taken_name",
            "password": "StrongPass123",
            "verification_code": "123456",
            "accepted_user_notice": True,
            "programming_level": 3,
            "maths_level": 3,
        },
    )
    assert duplicate_username.status_code == 400
    assert duplicate_username.json()["detail"] == "Username already taken"

    retry = await client.post(
        "/api/auth/register",
        json={
            "email": "retry.user@example.com",
            "username": "new_name",
            "password": "StrongPass123",
            "verification_code": "123456",
            "accepted_user_notice": True,
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
        json={"email": "wrong.user@example.com", "username": "wrong_user"},
    )
    assert send_code.status_code == 200

    register = await client.post(
        "/api/auth/register",
        json={
            "email": "wrong.user@example.com",
            "username": "wrong_user",
            "password": "StrongPass123",
            "verification_code": "999999",
            "accepted_user_notice": True,
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
        json={"email": "expired.user@example.com", "username": "expired_user"},
    )
    assert send_code.status_code == 200

    async with session_factory() as db:
        token = (
            await db.execute(
                select(EmailVerificationToken).where(
                    EmailVerificationToken.email == "expired.user@example.com"
                )
            )
        ).scalar_one()
        token.expires_at = token.expires_at.replace(year=2000)
        await db.commit()

    register = await client.post(
        "/api/auth/register",
        json={
            "email": "expired.user@example.com",
            "username": "expired_user",
            "password": "StrongPass123",
            "verification_code": "123456",
            "accepted_user_notice": True,
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
        json={"email": "attempts.user@example.com", "username": "attempts_user"},
    )
    assert send_code.status_code == 200

    for _ in range(settings.email_code_max_attempts):
        failed = await client.post(
            "/api/auth/register",
            json={
                "email": "attempts.user@example.com",
                "username": "attempts_user",
                "password": "StrongPass123",
                "verification_code": "999999",
                "accepted_user_notice": True,
                "programming_level": 3,
                "maths_level": 3,
            },
        )
        assert failed.status_code == 400

    final_try = await client.post(
        "/api/auth/register",
        json={
            "email": "attempts.user@example.com",
            "username": "attempts_user",
            "password": "StrongPass123",
            "verification_code": "123456",
            "accepted_user_notice": True,
            "programming_level": 3,
            "maths_level": 3,
        },
    )
    assert final_try.status_code == 400
    assert final_try.json()["detail"] == "Invalid or expired verification code"


@pytest.mark.asyncio
async def test_register_requires_user_notice_acceptance(auth_email_client) -> None:
    client, _, _ = auth_email_client

    send_code = await client.post(
        "/api/auth/register/send-code",
        json={"email": "notice.user@example.com", "username": "notice_user"},
    )
    assert send_code.status_code == 200

    rejected = await client.post(
        "/api/auth/register",
        json={
            "email": "notice.user@example.com",
            "username": "notice_user",
            "password": "StrongPass123",
            "verification_code": "123456",
            "accepted_user_notice": False,
            "programming_level": 3,
            "maths_level": 3,
        },
    )
    assert rejected.status_code == 400
    assert rejected.json()["detail"] == USER_NOTICE_ACCEPTANCE_DETAIL

    retry = await client.post(
        "/api/auth/register",
        json={
            "email": "notice.user@example.com",
            "username": "notice_user",
            "password": "StrongPass123",
            "verification_code": "123456",
            "accepted_user_notice": True,
            "programming_level": 3,
            "maths_level": 3,
        },
    )
    assert retry.status_code == 200


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
    assert existing.json() == {
        "message": "Verification code sent.",
        "resend_cooldown_seconds": 120,
    }

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
async def test_password_reset_send_code_rejects_immediate_resend_with_retry_after_header(
    auth_email_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory, _ = auth_email_client
    fixed_now = datetime(2026, 3, 11, 12, 0, 0)
    monkeypatch.setattr(
        "app.services.email_verification_service._now_utc",
        lambda: fixed_now,
    )
    await _create_user(
        session_factory,
        email="existing@example.com",
        username="existing_user",
    )

    first = await client.post(
        "/api/auth/password-reset/send-code",
        json={"email": "existing@example.com"},
    )
    assert first.status_code == 200

    retry = await client.post(
        "/api/auth/password-reset/send-code",
        json={"email": "existing@example.com"},
    )
    assert retry.status_code == 429
    assert retry.headers["Retry-After"] == "120"
    assert (
        retry.json()["detail"]
        == "Please wait 120s before requesting another code."
    )


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


@pytest.mark.asyncio
async def test_delete_account_removes_owned_data_and_files(
    auth_email_client,
    tmp_path,
) -> None:
    client, session_factory, _ = auth_email_client
    token = await _register_user(
        client,
        email="delete.user@example.com",
        username="delete_user",
    )
    headers = _auth_headers(token)

    notebook_dir = tmp_path / "notebooks"
    upload_dir = tmp_path / "uploads"
    notebook_dir.mkdir(parents=True, exist_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)
    notebook_path = notebook_dir / "owned.ipynb"
    upload_path = upload_dir / "owned.txt"
    notebook_path.write_text('{"cells":[]}', encoding="utf-8")
    upload_path.write_text("owned upload", encoding="utf-8")

    async with session_factory() as db:
        user = (
            await db.execute(select(User).where(User.email == "delete.user@example.com"))
        ).scalar_one()

        session = ChatSession(user_id=user.id, session_type="general")
        zone = LearningZone(title="Zone", description="Delete test", order=1)
        db.add_all([session, zone])
        await db.flush()

        zone_notebook = ZoneNotebook(
            zone_id=zone.id,
            title="Zone Notebook",
            description="Delete test notebook",
            original_filename="zone.ipynb",
            stored_filename="zone.ipynb",
            storage_path=str(tmp_path / "zone.ipynb"),
            notebook_json='{"cells":[]}',
            extracted_text=None,
            size_bytes=12,
            order=1,
        )
        db.add(zone_notebook)
        await db.flush()

        db.add_all(
            [
                ChatMessage(session_id=session.id, role="user", content="hello"),
                DailyTokenUsage(
                    user_id=user.id,
                    date=datetime(2026, 3, 10, tzinfo=timezone.utc).date(),
                    input_tokens_used=12,
                    output_tokens_used=8,
                ),
                UploadedFile(
                    user_id=user.id,
                    original_filename="owned.txt",
                    stored_filename="owned.txt",
                    content_type="text/plain",
                    file_type="document",
                    size_bytes=11,
                    storage_path=str(upload_path),
                    extracted_text="owned upload",
                    expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
                    + timedelta(hours=1),
                ),
                UserNotebook(
                    user_id=user.id,
                    title="Owned Notebook",
                    original_filename="owned.ipynb",
                    stored_filename="owned.ipynb",
                    storage_path=str(notebook_path),
                    notebook_json='{"cells":[]}',
                    extracted_text="owned notebook",
                    size_bytes=12,
                ),
                ZoneNotebookProgress(
                    user_id=user.id,
                    zone_notebook_id=zone_notebook.id,
                    notebook_state='{"cells":[]}',
                ),
                EmailVerificationToken(
                    email=user.email,
                    purpose="reset_password",
                    code_hash="hash",
                    expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
                    + timedelta(minutes=10),
                    resend_available_at=datetime.now(timezone.utc).replace(
                        tzinfo=None
                    ),
                ),
                AdminAuditLog(
                    admin_email=user.email,
                    action="delete",
                    resource_type="zone",
                    details="owned audit row",
                ),
            ]
        )
        await db.commit()

    deleted = await client.delete("/api/auth/me", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["message"] == "Account deleted successfully."
    cookie_header = deleted.headers.get("set-cookie", "").lower()
    assert "refresh_token=" in cookie_header
    assert "max-age=0" in cookie_header

    me_after_delete = await client.get("/api/auth/me", headers=headers)
    assert me_after_delete.status_code == 401
    assert me_after_delete.json()["detail"] == "User not found"

    async with session_factory() as db:
        assert (
            await db.execute(select(User).where(User.email == "delete.user@example.com"))
        ).scalar_one_or_none() is None
        assert (await db.execute(select(ChatSession))).scalars().all() == []
        assert (await db.execute(select(ChatMessage))).scalars().all() == []
        assert (await db.execute(select(DailyTokenUsage))).scalars().all() == []
        retained_rows = (
            await db.execute(select(RetainedDailyTokenUsage))
        ).scalars().all()
        assert len(retained_rows) == 1
        assert retained_rows[0].input_tokens_used == 12
        assert retained_rows[0].output_tokens_used == 8
        assert (await db.execute(select(UploadedFile))).scalars().all() == []
        assert (await db.execute(select(UserNotebook))).scalars().all() == []
        assert (await db.execute(select(ZoneNotebookProgress))).scalars().all() == []
        assert (await db.execute(select(EmailVerificationToken))).scalars().all() == []
        audit_rows = (await db.execute(select(AdminAuditLog))).scalars().all()
        assert len(audit_rows) == 1
        assert audit_rows[0].admin_email == "delete.user@example.com"
        assert (await db.execute(select(LearningZone))).scalars().all() != []
        assert (await db.execute(select(ZoneNotebook))).scalars().all() != []

    assert not notebook_path.exists()
    assert not upload_path.exists()


@pytest.mark.asyncio
async def test_register_restores_retained_usage_for_same_email_in_current_week(
    auth_email_client,
) -> None:
    client, session_factory, _ = auth_email_client
    token = await _register_user(
        client,
        email="restore.user@example.com",
        username="restore_user",
    )
    headers = _auth_headers(token)
    today = date.today()

    async with session_factory() as db:
        user = (
            await db.execute(select(User).where(User.email == "restore.user@example.com"))
        ).scalar_one()
        db.add(
            DailyTokenUsage(
                user_id=user.id,
                date=today,
                input_tokens_used=50,
                output_tokens_used=20,
            )
        )
        await db.commit()

    deleted = await client.delete("/api/auth/me", headers=headers)
    assert deleted.status_code == 200

    replacement_token = await _register_user(
        client,
        email="restore.user@example.com",
        username="restore_user_again",
    )
    replacement_headers = _auth_headers(replacement_token)

    usage_response = await client.get("/api/chat/usage", headers=replacement_headers)
    assert usage_response.status_code == 200
    usage = usage_response.json()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    assert usage["week_start"] == week_start.isoformat()
    assert usage["week_end"] == week_end.isoformat()
    assert usage["input_tokens_used"] == 50
    assert usage["output_tokens_used"] == 20
    assert usage["weighted_tokens_used"] == 30.0

    async with session_factory() as db:
        restored_user = (
            await db.execute(select(User).where(User.email == "restore.user@example.com"))
        ).scalar_one()
        restored_rows = (
            await db.execute(
                select(DailyTokenUsage).where(DailyTokenUsage.user_id == restored_user.id)
            )
        ).scalars().all()
        assert len(restored_rows) == 1
        assert restored_rows[0].date == today
        assert restored_rows[0].input_tokens_used == 50
        assert restored_rows[0].output_tokens_used == 20
        assert (await db.execute(select(RetainedDailyTokenUsage))).scalars().all() == []


@pytest.mark.asyncio
async def test_register_does_not_restore_retained_usage_for_different_email(
    auth_email_client,
) -> None:
    client, session_factory, _ = auth_email_client
    token = await _register_user(
        client,
        email="archive.only@example.com",
        username="archive_only",
    )
    headers = _auth_headers(token)
    today = date.today()

    async with session_factory() as db:
        user = (
            await db.execute(select(User).where(User.email == "archive.only@example.com"))
        ).scalar_one()
        db.add(
            DailyTokenUsage(
                user_id=user.id,
                date=today,
                input_tokens_used=25,
                output_tokens_used=10,
            )
        )
        await db.commit()

    deleted = await client.delete("/api/auth/me", headers=headers)
    assert deleted.status_code == 200

    replacement_token = await _register_user(
        client,
        email="different.user@example.com",
        username="different_user",
    )
    usage_response = await client.get(
        "/api/chat/usage",
        headers=_auth_headers(replacement_token),
    )
    assert usage_response.status_code == 200
    usage = usage_response.json()
    assert usage["input_tokens_used"] == 0
    assert usage["output_tokens_used"] == 0
    assert usage["weighted_tokens_used"] == 0.0

    async with session_factory() as db:
        retained_rows = (
            await db.execute(select(RetainedDailyTokenUsage))
        ).scalars().all()
        assert len(retained_rows) == 1
        assert retained_rows[0].input_tokens_used == 25
        assert retained_rows[0].output_tokens_used == 10


@pytest.mark.asyncio
async def test_register_restores_previous_week_usage_without_counting_it_in_current_week(
    auth_email_client,
) -> None:
    client, session_factory, _ = auth_email_client
    token = await _register_user(
        client,
        email="week.boundary@example.com",
        username="week_boundary",
    )
    headers = _auth_headers(token)
    today = date.today()
    current_week_start = today - timedelta(days=today.weekday())
    previous_week_day = current_week_start - timedelta(days=1)

    async with session_factory() as db:
        user = (
            await db.execute(select(User).where(User.email == "week.boundary@example.com"))
        ).scalar_one()
        db.add(
            DailyTokenUsage(
                user_id=user.id,
                date=previous_week_day,
                input_tokens_used=70,
                output_tokens_used=35,
            )
        )
        await db.commit()

    deleted = await client.delete("/api/auth/me", headers=headers)
    assert deleted.status_code == 200

    replacement_token = await _register_user(
        client,
        email="week.boundary@example.com",
        username="week_boundary_again",
    )
    replacement_headers = _auth_headers(replacement_token)

    usage_response = await client.get("/api/chat/usage", headers=replacement_headers)
    assert usage_response.status_code == 200
    usage = usage_response.json()
    week_end = current_week_start + timedelta(days=6)
    assert usage["week_start"] == current_week_start.isoformat()
    assert usage["week_end"] == week_end.isoformat()
    assert usage["input_tokens_used"] == 0
    assert usage["output_tokens_used"] == 0
    assert usage["weighted_tokens_used"] == 0.0

    async with session_factory() as db:
        restored_user = (
            await db.execute(
                select(User).where(User.email == "week.boundary@example.com")
            )
        ).scalar_one()
        restored_rows = (
            await db.execute(
                select(DailyTokenUsage).where(DailyTokenUsage.user_id == restored_user.id)
            )
        ).scalars().all()
        assert len(restored_rows) == 1
        assert restored_rows[0].date == previous_week_day
        assert restored_rows[0].input_tokens_used == 70
        assert restored_rows[0].output_tokens_used == 35
        assert (await db.execute(select(RetainedDailyTokenUsage))).scalars().all() == []


@pytest.mark.asyncio
async def test_admin_usage_totals_and_model_stats_remain_after_user_deletion(
    auth_email_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory, _ = auth_email_client
    monkeypatch.setattr(settings, "admin_email", "admin@example.com")

    admin_token = await _register_user(
        client,
        email="admin@example.com",
        username="admin_user",
    )
    student_token = await _register_user(
        client,
        email="tracked.user@example.com",
        username="tracked_user",
    )
    admin_headers = _auth_headers(admin_token)
    student_headers = _auth_headers(student_token)
    created_at = datetime.now(timezone.utc).replace(tzinfo=None)

    async with session_factory() as db:
        student = (
            await db.execute(select(User).where(User.email == "tracked.user@example.com"))
        ).scalar_one()
        session = ChatSession(
            user_id=student.id,
            session_type="general",
        )
        db.add(session)
        await db.flush()
        db.add(
            ChatMessage(
                session_id=session.id,
                role="assistant",
                content="Tracked assistant reply",
                input_tokens=120,
                output_tokens=80,
                llm_provider="openai",
                llm_model="gpt-5-mini",
                estimated_cost_usd=0.0456,
                created_at=created_at,
            )
        )
        db.add(
            DailyTokenUsage(
                user_id=student.id,
                date=created_at.date(),
                input_tokens_used=120,
                output_tokens_used=80,
            )
        )
        await db.commit()

    usage_before = await client.get("/api/admin/usage", headers=admin_headers)
    assert usage_before.status_code == 200
    usage_by_model_before = await client.get(
        "/api/admin/usage/by-model",
        headers=admin_headers,
        params={"provider": "openai", "model": "gpt-5-mini"},
    )
    assert usage_by_model_before.status_code == 200

    deleted = await client.delete("/api/auth/me", headers=student_headers)
    assert deleted.status_code == 200

    usage_after = await client.get("/api/admin/usage", headers=admin_headers)
    assert usage_after.status_code == 200
    usage_by_model_after = await client.get(
        "/api/admin/usage/by-model",
        headers=admin_headers,
        params={"provider": "openai", "model": "gpt-5-mini"},
    )
    assert usage_by_model_after.status_code == 200

    before_totals = usage_before.json()
    after_totals = usage_after.json()
    assert after_totals["today"] == before_totals["today"]
    assert after_totals["this_week"] == before_totals["this_week"]
    assert after_totals["this_month"] == before_totals["this_month"]

    before_model = usage_by_model_before.json()
    after_model = usage_by_model_after.json()
    assert after_model["today"] == before_model["today"]
    assert after_model["this_week"] == before_model["this_week"]
    assert after_model["this_month"] == before_model["this_month"]
