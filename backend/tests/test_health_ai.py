"""Health AI endpoint helper tests."""

import pytest

from app.main import health_check as root_health_check
from app.routers import health as health_router


@pytest.mark.asyncio
async def test_ai_health_check_includes_vertex_embedding_and_caches(monkeypatch) -> None:
    calls = {"count": 0}
    seen_kwargs: dict = {}

    async def _fake_verify_all_keys(*args, **kwargs):
        calls["count"] += 1
        seen_kwargs.update(kwargs)
        return {
            "anthropic": False,
            "openai": True,
            "google": True,
            "vertex_embedding": True,
            "cohere": True,
            "voyageai": False,
        }

    monkeypatch.setattr("app.routers.health.verify_all_keys", _fake_verify_all_keys)
    health_router._last_ai_health_result = None
    health_router._last_ai_health_at = None

    first = await health_router.ai_health_check(force=True)
    second = await health_router.ai_health_check(force=False)

    assert first["vertex_embedding"] is True
    assert first["cached"] is False
    assert second["vertex_embedding"] is True
    assert second["cached"] is True
    assert calls["count"] == 1
    assert seen_kwargs["google_transport"] == health_router.settings.google_gemini_transport


@pytest.mark.asyncio
async def test_ai_model_catalog_health_check_returns_models_and_caches(monkeypatch) -> None:
    calls = {"count": 0}

    async def _fake_smoke_test_supported_models(**kwargs):
        calls["count"] += 1
        return {
            "llm": {
                "google": {
                    "configured": True,
                    "transport": "vertex",
                    "checked_models": {"gemini-3-flash-preview": True},
                    "available_models": ["gemini-3-flash-preview"],
                }
            },
            "embeddings": {
                "cohere": {
                    "configured": True,
                    "checked_models": {"embed-v4.0": True},
                    "available_models": ["embed-v4.0"],
                }
            },
        }

    monkeypatch.setattr(
        "app.routers.health.smoke_test_supported_models",
        _fake_smoke_test_supported_models,
    )
    health_router._last_ai_models_result = None
    health_router._last_ai_models_at = None

    first = await health_router.ai_model_catalog_health_check(force=True)
    second = await health_router.ai_model_catalog_health_check(force=False)

    assert first["cached"] is False
    assert second["cached"] is True
    assert first["current"]["active_llm"]["provider"] == health_router.settings.llm_provider
    assert "smoke_tested_models" in first
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_root_health_returns_html_for_browser_accept_header(monkeypatch) -> None:
    class _DummyRequest:
        headers = {"accept": "text/html,application/xhtml+xml"}

    async def _fake_model_catalog(force: bool = False):
        return {
            "current": {
                "active_llm": {
                    "provider": "google",
                    "model": "gemini-3-flash-preview",
                    "google_gemini_transport": "vertex",
                },
                "active_embedding": {"provider": "cohere", "model": "embed-v4.0"},
                "llm_models": {"google": "gemini-3-flash-preview"},
                "embedding_models": {"cohere": "embed-v4.0"},
                "google_gemini_transport": "vertex",
            },
            "smoke_tested_models": {"llm": {}, "embeddings": {}},
            "cached": True,
            "checked_at": "2026-02-25T00:00:00Z",
        }

    monkeypatch.setattr("app.main.ai_model_catalog_health_check", _fake_model_catalog)

    response = await root_health_check(_DummyRequest())

    assert response.status_code == 200
    assert response.media_type == "text/html"
    assert "System Health" in response.body.decode()
    assert "gemini-3-flash-preview" in response.body.decode()


@pytest.mark.asyncio
async def test_root_health_returns_json_for_probe_requests() -> None:
    class _DummyRequest:
        headers = {"accept": "*/*"}

    response = await root_health_check(_DummyRequest())

    assert response == {"status": "healthy"}
