"""Health AI endpoint helper tests."""

import pytest

from app.main import health_check as root_health_check
from app.routers import health as health_router


@pytest.mark.asyncio
async def test_ai_health_check_returns_llm_keys_and_caches(monkeypatch) -> None:
    calls = {"count": 0}

    async def _fake_verify_all_keys(*args, **kwargs):
        calls["count"] += 1
        return {
            "anthropic": False,
            "openai": True,
            "google_ai_studio": True,
            "google_vertex": False,
            "google": True,
        }

    monkeypatch.setattr("app.routers.health.verify_all_keys", _fake_verify_all_keys)
    health_router._last_ai_health_result = None
    health_router._last_ai_health_at = None

    first = await health_router.ai_health_check(force=True)
    second = await health_router.ai_health_check(force=False)

    assert first["google"] is True
    assert first["cached"] is False
    assert second["google"] is True
    assert second["cached"] is True
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_ai_model_catalog_health_check_returns_llm_only_and_caches(monkeypatch) -> None:
    calls = {"count": 0}

    async def _fake_smoke_test_supported_models(**kwargs):
        calls["count"] += 1
        return {
            "llm": {
                "google-aistudio": {
                    "ready": True,
                    "transport": "aistudio",
                    "checked_models": {"gemini-3-flash-preview": True},
                    "available_models": ["gemini-3-flash-preview"],
                }
            }
        }

    monkeypatch.setattr(
        "app.routers.health.smoke_test_supported_models",
        _fake_smoke_test_supported_models,
    )
    monkeypatch.setattr("app.routers.health.settings.llm_provider", "openai")
    monkeypatch.setattr("app.routers.health.settings.llm_model_openai", "gpt-5-mini")
    health_router._last_ai_models_result = None
    health_router._last_ai_models_at = None

    first = await health_router.ai_model_catalog_health_check(force=True)
    second = await health_router.ai_model_catalog_health_check(force=False)

    assert first["cached"] is False
    assert second["cached"] is True
    assert first["current"]["provider"] == "openai"
    assert first["current"]["model"] == "gpt-5-mini"
    assert "smoke_tested_models" in first
    assert "llm" in first["smoke_tested_models"]
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_root_health_returns_json_liveness_response() -> None:
    response = await root_health_check()

    assert response == {"status": "healthy"}
