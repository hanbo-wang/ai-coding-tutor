"""Profile update tests for effective-level baseline resets."""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.dependencies import get_db
from app.models.user import Base, User
from app.routers.auth import router as auth_router


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def _register_user(
    client: AsyncClient,
    *,
    email: str,
    username: str,
    programming_level: int = 3,
    maths_level: int = 3,
    password: str = "StrongPass123",
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


async def _get_user_by_email(
    session_factory: async_sessionmaker[AsyncSession], email: str
) -> User:
    async with session_factory() as db:
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one()


@pytest_asyncio.fixture
async def auth_profile_client(tmp_path):
    """Create an isolated app and SQLite DB for auth profile update tests."""
    db_path = tmp_path / "auth_profile.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = FastAPI(title="auth-profile-test-app")
    app.include_router(auth_router)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, session_factory

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_profile_update_resets_only_updated_programming_effective_level(
    auth_profile_client,
) -> None:
    """Updating programming level resets only the programming effective baseline."""
    client, session_factory = auth_profile_client
    register = await _register_user(
        client,
        email="learner@example.com",
        username="learner",
        programming_level=2,
        maths_level=4,
    )
    headers = _auth_headers(register["access_token"])

    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.email == "learner@example.com"))).scalar_one()
        user.effective_programming_level = 4.4
        user.effective_maths_level = 1.7
        await db.commit()

    response = await client.put("/api/auth/me", headers=headers, json={"programming_level": 5})
    assert response.status_code == 200
    payload = response.json()
    assert payload["programming_level"] == 5
    assert payload["maths_level"] == 4
    assert "effective_programming_level" not in payload
    assert "effective_maths_level" not in payload

    db_user = await _get_user_by_email(session_factory, "learner@example.com")
    assert db_user.programming_level == 5
    assert db_user.maths_level == 4
    assert db_user.effective_programming_level == pytest.approx(5.0)
    assert db_user.effective_maths_level == pytest.approx(1.7)


@pytest.mark.asyncio
async def test_profile_update_resets_both_effective_levels_when_both_levels_change(
    auth_profile_client,
) -> None:
    """Updating both self-assessed levels resets both hidden effective baselines."""
    client, session_factory = auth_profile_client
    register = await _register_user(
        client,
        email="both@example.com",
        username="both_levels",
        programming_level=3,
        maths_level=3,
    )
    headers = _auth_headers(register["access_token"])

    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.email == "both@example.com"))).scalar_one()
        user.effective_programming_level = 1.2
        user.effective_maths_level = 4.8
        await db.commit()

    response = await client.put(
        "/api/auth/me",
        headers=headers,
        json={"programming_level": 4, "maths_level": 2},
    )
    assert response.status_code == 200

    db_user = await _get_user_by_email(session_factory, "both@example.com")
    assert db_user.programming_level == 4
    assert db_user.maths_level == 2
    assert db_user.effective_programming_level == pytest.approx(4.0)
    assert db_user.effective_maths_level == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_profile_update_username_only_keeps_effective_levels(
    auth_profile_client,
) -> None:
    """Updating only the username leaves hidden effective levels unchanged."""
    client, session_factory = auth_profile_client
    register = await _register_user(
        client,
        email="nameonly@example.com",
        username="name_only",
    )
    headers = _auth_headers(register["access_token"])

    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.email == "nameonly@example.com"))).scalar_one()
        user.effective_programming_level = 2.6
        user.effective_maths_level = 3.4
        await db.commit()

    response = await client.put("/api/auth/me", headers=headers, json={"username": "renamed_user"})
    assert response.status_code == 200
    assert response.json()["username"] == "renamed_user"

    db_user = await _get_user_by_email(session_factory, "nameonly@example.com")
    assert db_user.username == "renamed_user"
    assert db_user.effective_programming_level == pytest.approx(2.6)
    assert db_user.effective_maths_level == pytest.approx(3.4)
