"""Auth helper and token tests."""

import pytest
from fastapi import Response

from app.routers.auth import set_refresh_cookie
from app.services.auth_service import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_round_trip() -> None:
    """Hashed passwords should verify the original plain text."""
    hashed = hash_password("CorrectHorseBatteryStaple")
    assert hashed != "CorrectHorseBatteryStaple"
    assert hashed.startswith("$2")
    assert verify_password("CorrectHorseBatteryStaple", hashed)
    assert not verify_password("wrong-password", hashed)
    assert not verify_password("CorrectHorseBatteryStaple", "invalid-hash")


def test_access_token_contains_expected_claims() -> None:
    """Access tokens should encode subject and token type."""
    token = create_access_token("user-123")
    payload = decode_token(token)
    assert payload["sub"] == "user-123"
    assert payload["token_type"] == "access"
    assert "exp" in payload


def test_refresh_token_contains_expected_claims() -> None:
    """Refresh tokens should encode subject and token type."""
    token = create_refresh_token("user-456")
    payload = decode_token(token)
    assert payload["sub"] == "user-456"
    assert payload["token_type"] == "refresh"
    assert "exp" in payload


def test_decode_token_rejects_invalid_input() -> None:
    """Invalid JWT values should raise ValueError."""
    with pytest.raises(ValueError):
        decode_token("not-a-jwt")


def test_set_refresh_cookie_uses_http_only_scoped_cookie(monkeypatch) -> None:
    """Refresh cookie should use the expected security and path settings."""
    monkeypatch.setattr("app.routers.auth.settings.jwt_refresh_token_expire_days", 7)
    monkeypatch.setattr("app.routers.auth.settings.auth_cookie_secure", True)
    monkeypatch.setattr("app.routers.auth.settings.auth_cookie_samesite", "strict")

    response = Response()
    set_refresh_cookie(response, "refresh-token-value")

    cookie_header = response.headers.get("set-cookie", "")
    cookie_header_lower = cookie_header.lower()

    assert "refresh_token=refresh-token-value" in cookie_header
    assert "httponly" in cookie_header_lower
    assert "secure" in cookie_header_lower
    assert "path=/api/auth" in cookie_header_lower
    assert "samesite=strict" in cookie_header_lower
    assert "max-age=604800" in cookie_header_lower
